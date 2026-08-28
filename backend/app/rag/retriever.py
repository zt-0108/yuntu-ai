import hashlib
import inspect
import json
import logging
import re

import httpx

from app.config import (
    LLM_API_KEY,
    RAG_MIN_CROSS_ENCODER_SCORE,
    RAG_MIN_RULE_RERANK_SCORE,
    REDIS_RAG_TTL_SECONDS,
    REDIS_RERANK_TTL_SECONDS,
    RERANK_MODEL,
)
from app.rag.vector_db import search_guide_chunks_with_usage
from app.services.cache_service import get_cached_json, set_cached_json


DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"


logger = logging.getLogger(__name__)


_RERANK_CACHE_VERSION = "v2"
_GUIDE_CACHE_VERSION = "v2"
_RERANK_QUERY_LABELS = {
    "用户旅行需求",
    "目的地",
    "旅行偏好",
    "偏好",
    "行程节奏",
    "节奏",
    "特别备注",
    "备注",
}
_RERANK_INTENT_TERMS = (
    "日落",
    "傍晚",
    "日出",
    "清晨",
    "拍照",
    "摄影",
    "出片",
    "美食",
    "小吃",
    "海鲜",
    "轻松",
    "慢节奏",
    "休闲",
    "古镇",
    "骑行",
    "熊猫",
    "大熊猫",
    "潜水",
    "亲子",
    "历史",
    "文化",
    "自然风景",
    "购物",
    "夜景",
    "预算",
    "省钱",
    "路线",
    "行程",
)
_DINING_QUERY_TERMS = ("餐饮", "美食", "小吃", "吃", "海鲜")
_BUDGET_QUERY_TERMS = ("预算", "费用", "价格", "省钱", "花费", "人均", "多少钱")
_NEGATED_ITINERARY_RE = re.compile(
    r"(?:不想|不要|无需|不需要|不必|避免)[^，。；;\n]{0,10}(?:行程|路线|安排|规划|日程)"
)


def _normalize_cache_text(value: str) -> str:
    """把检索 query 做简单标准化，避免大小写和空格造成重复 key。"""
    return " ".join(value.strip().lower().split())


def _extract_query_keywords(
    query: str,
    destination: str | None = None,
) -> list[str]:
    """从关键词串或结构化自然语言需求中提取规则重排词。"""
    normalized_destination = (destination or "").strip().lower()
    raw_parts = re.split(r"[\s,，。；;、:：！？!?（）()【】\[\]]+", query)
    keywords: list[str] = []
    for part in raw_parts:
        normalized = part.strip()
        if not normalized or normalized in _RERANK_QUERY_LABELS:
            continue
        if normalized_destination and normalized.lower() == normalized_destination:
            continue
        if normalized not in keywords:
            keywords.append(normalized)

    # “行程节奏”是字段名，不代表用户需要行程类文档。
    intent_text = re.sub(
        r"(?:行程节奏|旅行节奏)\s*[：:]\s*[^\n]*",
        "",
        query,
    )
    # 中文整句没有天然空格；补出常见旅行意图词供无模型时的规则重排使用。
    for term in _RERANK_INTENT_TERMS:
        if normalized_destination and term.lower() == normalized_destination:
            continue
        if term in intent_text and term not in keywords:
            keywords.append(term)
    return keywords


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _has_itinerary_intent(query: str) -> bool:
    """区分用户主动要求排行程与结构化查询里的“行程节奏”字段名。"""
    intent_text = re.sub(
        r"(?:行程节奏|旅行节奏)\s*[：:]\s*[^\n]*",
        "",
        query,
    )
    intent_text = _NEGATED_ITINERARY_RE.sub("", intent_text)
    return _contains_any(intent_text, ["行程", "路线", "安排", "规划", "几天", "日程"])


def _canonical_chunk_title(title: str) -> str:
    """移除章节编号和说明后缀，用于识别用户明确点名的标题实体。"""
    normalized = re.sub(r"^\s*\d+(?:\.\d+)*[.、]?\s*", "", title).strip()
    return re.sub(r"\s*[（(][^（）()]*[）)]\s*$", "", normalized).strip()


def _score_chunk_for_rerank(
    query: str,
    chunk: dict[str, str],
    destination: str | None = None,
) -> int:
    """根据 query 关键词对召回片段做轻量打分。"""
    title = chunk.get("title", "")
    text = chunk.get("text", "")
    source = chunk.get("source", "")
    breadcrumb = chunk.get("breadcrumb", "")
    reasons: list[str] = []

    score = 0
    has_keyword_match = False
    for keyword in _extract_query_keywords(query, destination=destination):
        if keyword in title:
            score += 3
            has_keyword_match = True
            reasons.append(f"title+3:{keyword}")
        if keyword in text:
            score += 1
            has_keyword_match = True
            reasons.append(f"text+1:{keyword}")

    canonical_title = _canonical_chunk_title(title)
    if (
        len(canonical_title) >= 2
        and canonical_title != (destination or "").strip()
        and canonical_title in query
    ):
        score += 5
        has_keyword_match = True
        reasons.append(f"title-exact+5:{canonical_title}")

    # 文档开头通常是低信息量噪声片段。
    if title == "文档开头":
        score -= 8
        reasons.append("noise-8:文档开头")

    has_itinerary_intent = _has_itinerary_intent(query)
    # 用户明确要求路线或日程时，行程参考本身也是高价值候选。
    if "行程" in title and has_itinerary_intent:
        score += 4
        reasons.append("domain+4:行程标题")

    # "经典行程参考"内容较泛，只对没有行程意图的具体查询降权。
    if "行程参考" in title and not has_itinerary_intent:
        score -= 4
        reasons.append("domain-4:行程参考降权")

    # "目的地简介"内容过于泛化，对具体查询（美食、亲子等）不是最优候选。
    if "目的地简介" in title:
        score -= 2
        reasons.append("domain-2:目的地简介降权")

    # 语料把餐饮和预算放在同一片段；任一主题相关时都不应惩罚整段。
    has_dining_title = "餐饮" in title
    has_budget_title = "预算" in title
    has_dining_intent = _contains_any(query, list(_DINING_QUERY_TERMS))
    has_budget_intent = _contains_any(query, list(_BUDGET_QUERY_TERMS))
    if has_dining_title and has_dining_intent and "餐饮" not in query:
        score += 3
        reasons.append("domain+3:餐饮意图")
    if has_budget_title and has_budget_intent and "预算" not in query:
        score += 3
        reasons.append("domain+3:预算意图")

    if has_dining_title and has_budget_title:
        if not has_dining_intent and not has_budget_intent and not has_keyword_match:
            score -= 3
            reasons.append("domain-3:餐饮预算弱相关")
    elif has_dining_title and not has_dining_intent and not has_keyword_match:
        score -= 3
        reasons.append("domain-3:餐饮弱相关")
    elif has_budget_title and not has_budget_intent and not has_keyword_match:
        score -= 3
        reasons.append("domain-3:预算弱相关")

    # 目的地不匹配降权：片段来源与查询目的地不一致时降权。
    if destination:
        chunk_lower = (
            f"{source} {breadcrumb} {title} {text} {chunk.get('destination', '')}"
        ).lower()
        if destination.lower() not in chunk_lower:
            score -= 5
            reasons.append(f"dest-5:非{destination}片段")

    chunk["rerank_reasons"] = reasons
    return score


_NOISE_TITLES = {"文档开头"}


def _extract_rerank_token_usage(response_data: dict) -> tuple[dict[str, int], bool]:
    """只读取接口返回的官方 usage；没有 usage 时不做本地估算。"""
    usage = response_data.get("usage") or response_data.get("output", {}).get("usage") or {}
    prompt_tokens = (
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("input_token_count")
        or 0
    )
    completion_tokens = (
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("output_token_count")
        or 0
    )
    total_tokens = usage.get("total_tokens") or usage.get("total_token_count") or 0

    if not prompt_tokens and not completion_tokens and total_tokens:
        prompt_tokens = total_tokens

    if prompt_tokens or completion_tokens:
        return {
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
        }, True

    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
    }, False


def _rerank_with_dashscope(
    query: str,
    chunks: list[dict[str, str]],
    top_k: int,
) -> tuple[list[tuple[float, int]] | None, dict[str, int]]:
    """调用 DashScope qwen3-rerank 模型做语义重排序。返回 (scored, token_usage)。"""
    empty_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    if not LLM_API_KEY or not chunks:
        logger.info("[RAG·Rerank] 已跳过：无密钥或无候选片段")
        return None, empty_usage

    # 过滤已知噪声片段，避免浪费 rerank 名额
    filtered = [
        (i, chunk) for i, chunk in enumerate(chunks)
        if chunk.get("title", "") not in _NOISE_TITLES
    ]
    if not filtered:
        logger.info("[RAG·Rerank] 已跳过：候选片段均被过滤")
        return None, empty_usage

    original_indices = [i for i, _ in filtered]
    clean_chunks = [chunk for _, chunk in filtered]

    documents = [
        (
            f"路径：{chunk.get('breadcrumb', '')}\n"
            f"标题：{chunk.get('title', '')}\n"
            f"正文：{chunk.get('text', '')}"
        )
        for chunk in clean_chunks
    ]
    instruct = (
        "你是一个旅行攻略检索专家。"
        "查询中包含用户完整的目的地、偏好、节奏和特别备注。"
        "请综合判断所有原始约束，包括时间、否定要求和指定实体，"
        "从候选文档中检索出最具体、最详细、最能直接回答用户问题的片段。"
        "优先选择包含具体景点名称、活动推荐、实用信息的片段，"
        "避免选择泛化的目的地简介、文档开头等信息量低的片段。"
    )
    payload = {
        "model": RERANK_MODEL,
        "documents": documents,
        "query": query,
        "top_n": min(top_k, len(documents)),
        "instruct": instruct,
    }

    try:
        logger.info(
            "[RAG·Rerank] 正在调用模型 model=%s candidates=%s top_k=%s",
            RERANK_MODEL,
            len(clean_chunks),
            top_k,
        )
        with httpx.Client(timeout=30) as client:
            response = client.post(
                DASHSCOPE_RERANK_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code != 200:
                logger.warning(
                    "[RAG·Rerank] 接口调用失败 status=%d response=%s",
                    response.status_code,
                    response.text[:500],
                )
                return None, empty_usage
            data = response.json()

        # 只提取接口返回的官方 token usage；没有 usage 时保持 0，不做估算。
        token_usage, has_official_usage = _extract_rerank_token_usage(data)
        logger.info(
            "[RAG·Rerank] 调用完成 input_tokens=%s output_tokens=%s total_tokens=%s usage=%s",
            token_usage["prompt_tokens"],
            token_usage["completion_tokens"],
            token_usage["prompt_tokens"] + token_usage["completion_tokens"],
            "official" if has_official_usage else "unavailable",
        )

        # 兼容两种响应格式
        results = data.get("output", {}).get("results", []) or data.get("results", [])
        if not results:
            logger.warning("[RAG·Rerank] 模型未返回结果")
            return None, token_usage

        scored = [
            (float(item.get("relevance_score", 0)), original_indices[int(item.get("index", 0))])
            for item in results
            if int(item.get("index", 0)) < len(original_indices)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        logger.info("[RAG·Rerank] 已返回 results=%d", len(scored))
        return scored, token_usage

    except Exception as exc:
        logger.warning("[RAG·Rerank] 调用失败，改用规则排序 error_type=%s", type(exc).__name__)
        return None, empty_usage


def _build_rerank_cache_key(
    query: str,
    chunks: list[dict[str, str]],
    top_k: int | None = None,
) -> str:
    """按完整重排查询、候选内容和返回数量生成稳定缓存键。"""
    normalized_query = _normalize_cache_text(query)
    query_hash = hashlib.sha256(normalized_query.encode("utf-8")).hexdigest()[:20]
    content_fingerprint = [
        {
            "id": chunk.get("id", ""),
            "chunk_id": chunk.get("chunk_id", ""),
            "source": chunk.get("source", ""),
            "breadcrumb": chunk.get("breadcrumb", ""),
            "title": chunk.get("title", ""),
            "text": chunk.get("text", ""),
            "page_start": chunk.get("page_start", 0),
            "page_end": chunk.get("page_end", 0),
        }
        for chunk in chunks
    ]
    serialized_chunks = json.dumps(
        content_fingerprint,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    chunks_hash = hashlib.sha256(serialized_chunks.encode("utf-8")).hexdigest()[:20]
    return (
        f"rerank:{_RERANK_CACHE_VERSION}:{RERANK_MODEL}:"
        f"{query_hash}:{chunks_hash}:{top_k or 0}"
    )


def _build_guide_cache_key(
    query: str,
    lexical_query: str,
    rerank_query: str,
    destination: str | None,
    top_k: int,
) -> str:
    """让最终结果缓存同时区分三路查询。"""
    fingerprint = {
        "dense_query": _normalize_cache_text(query),
        "lexical_query": _normalize_cache_text(lexical_query),
        "rerank_query": _normalize_cache_text(rerank_query),
        "destination": _normalize_cache_text(destination or ""),
        "top_k": top_k,
    }
    serialized = json.dumps(
        fingerprint,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    fingerprint_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]
    return f"rag:guide:{_GUIDE_CACHE_VERSION}:{fingerprint_hash}"


def rerank_guide_chunks(
    query: str,
    matched_chunks: list[dict[str, str]],
    top_k: int,
    destination: str | None = None,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """对召回候选做重排序，优先 Cross-encoder，fallback 规则级。返回 (chunks, rerank_token_usage)。"""
    empty_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    if not matched_chunks:
        logger.info("rerank skipped: no retrieval candidates")
        return [], empty_usage

    # 尝试从缓存读取 rerank 结果
    cache_key = _build_rerank_cache_key(query, matched_chunks, top_k=top_k)
    cached = get_cached_json(cache_key)
    if cached is not None:
        logger.info("[RAG·Rerank] 命中缓存，不消耗 Token")
        reranked: list[dict[str, str]] = []
        for item in cached:
            idx = item["i"]
            if 0 <= idx < len(matched_chunks):
                enriched = dict(matched_chunks[idx])
                enriched["rerank_score"] = item["s"]
                enriched["rerank_reasons"] = [f"cross-encoder:{item['s']:.4f}"]
                reranked.append(enriched)
        return reranked[:top_k], empty_usage
    logger.debug("[RAG·Rerank] 缓存未命中")

    # 优先尝试 DashScope Cross-encoder Rerank
    dashscope_results, rerank_token_usage = _rerank_with_dashscope(query, matched_chunks, top_k)
    if dashscope_results is not None:
        dashscope_results = [
            (score, index)
            for score, index in dashscope_results
            if score >= RAG_MIN_CROSS_ENCODER_SCORE
        ]
        # 写入缓存：只存索引和分数，不重复存文本
        cache_value = [
            {"i": idx, "s": round(score, 4)}
            for score, idx in dashscope_results
        ]
        set_cached_json(cache_key, cache_value, expire_seconds=REDIS_RERANK_TTL_SECONDS)

        reranked = []
        for score, original_index in dashscope_results:
            if 0 <= original_index < len(matched_chunks):
                enriched_chunk = dict(matched_chunks[original_index])
                enriched_chunk["rerank_score"] = round(score, 4)
                enriched_chunk["rerank_reasons"] = [f"cross-encoder:{score:.4f}"]
                reranked.append(enriched_chunk)
        return reranked[:top_k], rerank_token_usage

    # fallback 到规则级 Rerank
    logger.info("[RAG·Rerank] 使用规则排序，不额外消耗 Token")
    scored_chunks: list[tuple[int, int, dict[str, str]]] = []
    for index, chunk in enumerate(matched_chunks):
        enriched_chunk = dict(chunk)
        score = _score_chunk_for_rerank(query, enriched_chunk, destination=destination)
        enriched_chunk["rerank_score"] = score
        scored_chunks.append((score, -index, enriched_chunk))

    scored_chunks.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        chunk
        for score, _, chunk in scored_chunks
        if score >= RAG_MIN_RULE_RERANK_SCORE
    ][:top_k], empty_usage


def _search_retrieval_candidates(
    query: str,
    lexical_query: str,
    top_k: int,
    destination: str | None,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """兼容尚未支持独立 lexical query 的旧版向量检索接口。"""
    search_kwargs: dict[str, object] = {
        "query": query,
        "top_k": top_k,
        "destination": destination,
    }
    try:
        parameters = inspect.signature(search_guide_chunks_with_usage).parameters
        supports_lexical_query = "lexical_query" in parameters or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
    except (TypeError, ValueError):
        supports_lexical_query = False

    if supports_lexical_query:
        search_kwargs["lexical_query"] = lexical_query
    return search_guide_chunks_with_usage(**search_kwargs)


def retrieve_travel_guide_chunks(
    query: str,
    top_k: int = 3,
    destination: str | None = None,
    *,
    lexical_query: str | None = None,
    rerank_query: str | None = None,
) -> tuple[list[dict[str, str]], dict[str, int], dict[str, int]]:
    """用独立的召回和重排查询返回攻略片段。"""
    effective_lexical_query = query if lexical_query is None else lexical_query
    effective_rerank_query = query if rerank_query is None else rerank_query
    candidate_k = max(top_k * 2, 6)
    matched_chunks, embedding_usage = _search_retrieval_candidates(
        query=query,
        lexical_query=effective_lexical_query,
        top_k=candidate_k,
        destination=destination,
    )
    reranked_chunks, rerank_usage = rerank_guide_chunks(
        query=effective_rerank_query,
        matched_chunks=matched_chunks,
        top_k=top_k,
        destination=destination,
    )
    return reranked_chunks, rerank_usage, embedding_usage


def retrieve_travel_guide(
    query: str,
    top_k: int = 3,
    destination: str | None = None,
    *,
    lexical_query: str | None = None,
    rerank_query: str | None = None,
) -> tuple[list[str], dict[str, int], dict[str, int]]:
    """返回最相关的攻略片段。返回 (texts, rerank_usage, embedding_usage)。"""
    empty_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    effective_lexical_query = query if lexical_query is None else lexical_query
    effective_rerank_query = query if rerank_query is None else rerank_query
    cache_key = _build_guide_cache_key(
        query=query,
        lexical_query=effective_lexical_query,
        rerank_query=effective_rerank_query,
        destination=destination,
        top_k=top_k,
    )
    cached_value = get_cached_json(cache_key)
    if cached_value is not None:
        logger.info("[1/4 RAG 检索] 命中结果缓存，不消耗检索 Token")
        return [str(item) for item in cached_value], empty_usage, empty_usage
    logger.debug("[1/4 RAG 检索] 结果缓存未命中")

    matched_chunks, rerank_usage, embedding_usage = retrieve_travel_guide_chunks(
        query=query,
        top_k=top_k,
        destination=destination,
        lexical_query=effective_lexical_query,
        rerank_query=effective_rerank_query,
    )

    results: list[str] = []
    for chunk in matched_chunks:
        page_start = int(chunk.get("page_start", 0) or 0)
        page_end = int(chunk.get("page_end", page_start) or page_start)
        page_label = ""
        if page_start:
            page_label = (
                f" | 页码: {page_start}"
                if page_end == page_start
                else f" | 页码: {page_start}-{page_end}"
            )
        results.append(
            f"[来源: {chunk['source']}{page_label} | 标题: {chunk['title']}]\n"
            f"{chunk['text']}"
        )

    set_cached_json(cache_key, results, expire_seconds=REDIS_RAG_TTL_SECONDS)
    return results, rerank_usage, embedding_usage
