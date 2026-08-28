from __future__ import annotations

import argparse
import inspect
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable


CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag import retriever, vector_db


DEFAULT_CASES_PATH = BACKEND_DIR / "eval" / "rag_eval_cases.json"
DEFAULT_RETRIEVAL_MODE = "vector"

# 知识库当前覆盖的全部 9 个目的地。污染检查不能只看最早的 5 个 Markdown 城市。
ALL_DESTINATIONS = [
    "大理",
    "成都",
    "西安",
    "厦门",
    "三亚",
    "苏州",
    "扬州",
    "杭州",
    "南京",
]

SOURCE_DESTINATION_ALIASES = {
    "dali": "大理",
    "chengdu": "成都",
    "xian": "西安",
    "xiamen": "厦门",
    "sanya": "三亚",
    "suzhou": "苏州",
    "yangzhou": "扬州",
    "hangzhou": "杭州",
    "nanjing": "南京",
    "大理": "大理",
    "成都": "成都",
    "西安": "西安",
    "厦门": "厦门",
    "三亚": "三亚",
    "苏州": "苏州",
    "扬州": "扬州",
    "杭州": "杭州",
    "南京": "南京",
}

EMPTY_USAGE = {"prompt_tokens": 0, "completion_tokens": 0}


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError("RAG eval cases file must contain a JSON list.")

    seen_ids: set[str] = set()
    for index, case in enumerate(data, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"RAG eval case #{index} must be a JSON object.")
        case_id = str(case.get("id", "")).strip()
        if not case_id:
            raise ValueError(f"RAG eval case #{index} is missing id.")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate RAG eval case id: {case_id}")
        seen_ids.add(case_id)

        for field in ("destination", "retrieval_query", "rerank_query"):
            if not str(case.get(field, "")).strip():
                raise ValueError(f"RAG eval case {case_id} is missing {field}.")
        relevant_documents = case.get("relevant_documents")
        if not isinstance(relevant_documents, list) or not relevant_documents:
            raise ValueError(
                f"RAG eval case {case_id} must define relevant_documents."
            )
        if int(case.get("top_k", 5)) <= 0:
            raise ValueError(f"RAG eval case {case_id} has an invalid top_k.")
    return data


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def _document_text(chunk: dict[str, Any]) -> str:
    return "\n".join(
        str(chunk.get(field, ""))
        for field in ("breadcrumb", "title", "text", "source")
    )


def _target_matches_chunk(
    target: dict[str, Any], chunk: dict[str, Any]
) -> bool:
    """用稳定 metadata 和可选正文锚点匹配金标，避免只靠宽泛标题词。"""
    exact_fields = (
        "id",
        "source",
        "title",
        "destination",
        "page_start",
        "page_end",
    )
    for field in exact_fields:
        if field in target and str(chunk.get(field, "")) != str(target[field]):
            return False

    title = str(chunk.get("title", ""))
    if "title_contains" in target and str(target["title_contains"]) not in title:
        return False

    combined_text = _document_text(chunk)
    all_terms = [str(item) for item in target.get("text_contains_all", [])]
    if any(term not in combined_text for term in all_terms):
        return False
    any_terms = [str(item) for item in target.get("text_contains_any", [])]
    if any_terms and not any(term in combined_text for term in any_terms):
        return False

    matcher_fields = set(exact_fields) | {
        "title_contains",
        "text_contains_all",
        "text_contains_any",
    }
    return any(field in target for field in matcher_fields)


def _target_grade(target: dict[str, Any]) -> int:
    return max(1, int(target.get("relevance", 1)))


def _matched_target_indices(
    chunks: list[dict[str, Any]], targets: list[dict[str, Any]]
) -> set[int]:
    return {
        index
        for index, target in enumerate(targets)
        if any(_target_matches_chunk(target, chunk) for chunk in chunks)
    }


def _ranked_relevance_grades(
    chunks: list[dict[str, Any]], targets: list[dict[str, Any]]
) -> list[int]:
    """每个金标最多计一次，避免重复 chunk 人为抬高 Precision/nDCG。"""
    used_targets: set[int] = set()
    grades: list[int] = []
    for chunk in chunks:
        matches = [
            (index, _target_grade(target))
            for index, target in enumerate(targets)
            if index not in used_targets and _target_matches_chunk(target, chunk)
        ]
        if not matches:
            grades.append(0)
            continue
        target_index, grade = max(matches, key=lambda item: item[1])
        used_targets.add(target_index)
        grades.append(grade)
    return grades


def _ndcg_at_k(grades: list[int], targets: list[dict[str, Any]], k: int) -> float:
    def dcg(values: list[int]) -> float:
        return sum(
            (2**grade - 1) / math.log2(rank + 1)
            for rank, grade in enumerate(values, start=1)
            if grade > 0
        )

    actual = dcg(grades[:k])
    ideal_grades = sorted(
        (_target_grade(target) for target in targets), reverse=True
    )[:k]
    ideal = dcg(ideal_grades)
    return actual / ideal if ideal else 0.0


def _infer_chunk_destination(chunk: dict[str, Any]) -> str:
    metadata_destination = str(chunk.get("destination", "")).strip()
    if metadata_destination:
        return metadata_destination

    source = str(chunk.get("source", "")).lower()
    for alias, destination in SOURCE_DESTINATION_ALIASES.items():
        if alias.lower() in source:
            return destination

    metadata_text = " ".join(
        str(chunk.get(field, "")) for field in ("source", "breadcrumb", "title")
    )
    matches = [city for city in ALL_DESTINATIONS if city in metadata_text]
    return matches[0] if len(matches) == 1 else ""


def _count_destination_pollution(
    chunks: list[dict[str, Any]], destination: str
) -> int:
    return sum(
        1
        for chunk in chunks
        if (inferred := _infer_chunk_destination(chunk)) and inferred != destination
    )


def _is_noise_chunk(case: dict[str, Any], chunk: dict[str, Any]) -> bool:
    title = str(chunk.get("title", ""))
    title_keywords = [str(item) for item in case.get("noise_title_keywords", [])]
    if _contains_any(title, title_keywords):
        return True
    return any(
        _target_matches_chunk(target, chunk)
        for target in case.get("noise_documents", [])
    )


def _call_with_supported_kwargs(
    function: Callable[..., Any], kwargs: dict[str, Any]
) -> Any:
    """阶段 1/2 API 过渡期适配：只传目标函数已声明的可选参数。"""
    signature = inspect.signature(function)
    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_var_kwargs:
        return function(**kwargs)
    supported = {
        name: value for name, value in kwargs.items() if name in signature.parameters
    }
    return function(**supported)


def _normalize_search_response(
    response: Any,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if isinstance(response, tuple) and len(response) == 2:
        chunks, usage = response
    else:
        chunks, usage = response, EMPTY_USAGE
    return list(chunks or []), {
        "prompt_tokens": int((usage or {}).get("prompt_tokens", 0)),
        "completion_tokens": int((usage or {}).get("completion_tokens", 0)),
    }


def _search_candidates(
    *,
    retrieval_query: str,
    lexical_query: str,
    candidate_k: int,
    destination: str,
    retrieval_mode: str,
    search_function: Callable[..., Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """检索候选层；模式参数存在时走公开 API，否则兼容当前 vector 实现。"""
    search_function = search_function or vector_db.search_guide_chunks_with_usage
    signature = inspect.signature(search_function)
    supports_mode = any(
        name in signature.parameters
        for name in ("retrieval_mode", "search_mode", "mode")
    ) or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )

    kwargs: dict[str, Any] = {
        "query": retrieval_query,
        "top_k": candidate_k,
        "destination": destination,
        "lexical_query": lexical_query,
    }
    if supports_mode:
        mode_parameter = next(
            (
                name
                for name in ("retrieval_mode", "search_mode", "mode")
                if name in signature.parameters
            ),
            "retrieval_mode",
        )
        kwargs[mode_parameter] = retrieval_mode
        return _normalize_search_response(
            _call_with_supported_kwargs(search_function, kwargs)
        )

    normalized_mode = retrieval_mode.strip().lower()
    if search_function is not vector_db.search_guide_chunks_with_usage:
        # 注入的测试/A-B adapter 没有 mode 参数时，由 adapter 自己决定检索实现。
        return _normalize_search_response(
            _call_with_supported_kwargs(search_function, kwargs)
        )
    if normalized_mode in {"default", "auto", "current"}:
        return _normalize_search_response(
            _call_with_supported_kwargs(search_function, kwargs)
        )
    if normalized_mode in {"vector", "dense"}:
        return _normalize_search_response(
            vector_db._search_guide_chunks_by_chroma(
                query=retrieval_query,
                top_k=candidate_k,
                destination=destination,
            )
        )

    raise ValueError(
        f"Retrieval mode '{retrieval_mode}' is not supported by the current "
        "search_guide_chunks_with_usage API."
    )


def _evaluate_case(
    case: dict[str, Any],
    *,
    retrieval_mode: str = DEFAULT_RETRIEVAL_MODE,
    candidate_k_override: int | None = None,
    search_function: Callable[..., Any] | None = None,
    rerank_function: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    top_k = int(case.get("top_k", 5))
    candidate_k = int(
        candidate_k_override
        if candidate_k_override is not None
        else case.get("candidate_k", max(top_k * 2, 6))
    )
    if candidate_k < top_k:
        raise ValueError(
            f"Case {case.get('id', '<unknown>')} candidate_k must be >= top_k."
        )

    destination = str(case["destination"])
    retrieval_query = str(case["retrieval_query"]).strip()
    lexical_query = str(case.get("lexical_query") or retrieval_query).strip()
    rerank_query = str(case["rerank_query"]).strip()

    start_time = time.perf_counter()
    candidates, embedding_usage = _search_candidates(
        retrieval_query=retrieval_query,
        lexical_query=lexical_query,
        candidate_k=candidate_k,
        destination=destination,
        retrieval_mode=retrieval_mode,
        search_function=search_function,
    )
    candidate_latency_ms = round((time.perf_counter() - start_time) * 1000, 1)

    rerank_function = rerank_function or retriever.rerank_guide_chunks
    rerank_start = time.perf_counter()
    reranked_response = _call_with_supported_kwargs(
        rerank_function,
        {
            "query": rerank_query,
            "matched_chunks": candidates,
            "top_k": top_k,
            "destination": destination,
        },
    )
    chunks, rerank_usage = _normalize_search_response(reranked_response)
    rerank_latency_ms = round((time.perf_counter() - rerank_start) * 1000, 1)
    latency_ms = round(candidate_latency_ms + rerank_latency_ms, 1)

    expected_title_keywords = [
        str(item) for item in case.get("expected_title_keywords", [])
    ]
    required_content_keywords = [
        str(item) for item in case.get("required_content_keywords", [])
    ]
    relevant_documents = list(case.get("relevant_documents", []))

    titles = [str(chunk.get("title", "")) for chunk in chunks]
    candidate_titles = [str(chunk.get("title", "")) for chunk in candidates]
    combined_text = "\n".join(_document_text(chunk) for chunk in chunks)

    top1_title = titles[0] if titles else ""
    top1_title_hit = bool(expected_title_keywords) and _contains_any(
        top1_title, expected_title_keywords
    )
    topk_title_hit = bool(expected_title_keywords) and any(
        _contains_any(title, expected_title_keywords) for title in titles
    )
    required_keyword_hits = _count_keyword_hits(
        combined_text, required_content_keywords
    )
    noise_count = sum(1 for chunk in chunks if _is_noise_chunk(case, chunk))
    candidate_noise_count = sum(
        1 for chunk in candidates if _is_noise_chunk(case, chunk)
    )

    # 旧 MRR：保留标题关键词口径，便于与历史报告纵向比较。
    reciprocal_rank = 0.0
    for rank, title in enumerate(titles, start=1):
        if _contains_any(title, expected_title_keywords):
            reciprocal_rank = 1.0 / rank
            break

    candidate_target_hits = _matched_target_indices(candidates, relevant_documents)
    candidate_recall = len(candidate_target_hits) / len(relevant_documents)
    final_target_hits = _matched_target_indices(chunks, relevant_documents)
    final_recall = len(final_target_hits) / len(relevant_documents)
    relevance_grades = _ranked_relevance_grades(chunks, relevant_documents)
    relevant_result_count = sum(1 for grade in relevance_grades if grade > 0)
    precision_at_k = relevant_result_count / top_k
    precision_at_returned = (
        relevant_result_count / len(chunks) if chunks else 0.0
    )
    ndcg_at_k = _ndcg_at_k(relevance_grades, relevant_documents, top_k)
    relevant_reciprocal_rank = next(
        (1.0 / rank for rank, grade in enumerate(relevance_grades, start=1) if grade),
        0.0,
    )

    return {
        "id": case.get("id", "<unknown>"),
        "tags": list(case.get("tags", [])),
        "destination": destination,
        "retrieval_mode": retrieval_mode,
        "query": retrieval_query,
        "retrieval_query": retrieval_query,
        "lexical_query": lexical_query,
        "rerank_query": rerank_query,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "candidate_count": len(candidates),
        "returned_count": len(chunks),
        "candidate_relevant_hits": len(candidate_target_hits),
        "relevant_total": len(relevant_documents),
        "candidate_recall_at_k": candidate_recall,
        "candidate_noise_count": candidate_noise_count,
        "candidate_pollution_count": _count_destination_pollution(
            candidates, destination
        ),
        "final_relevant_hits": len(final_target_hits),
        "relevant_result_count": relevant_result_count,
        "final_recall_at_k": final_recall,
        "precision_at_k": precision_at_k,
        "precision_at_returned": precision_at_returned,
        "ndcg_at_k": ndcg_at_k,
        "relevant_reciprocal_rank": relevant_reciprocal_rank,
        "top1_title": top1_title,
        "top1_title_hit": top1_title_hit,
        "topk_title_hit": topk_title_hit,
        "required_keyword_hits": required_keyword_hits,
        "required_keyword_total": len(required_content_keywords),
        "noise_count": noise_count,
        "reciprocal_rank": reciprocal_rank,
        "pollution_count": _count_destination_pollution(chunks, destination),
        "candidate_latency_ms": candidate_latency_ms,
        "rerank_latency_ms": rerank_latency_ms,
        "latency_ms": latency_ms,
        "embedding_prompt_tokens": embedding_usage.get("prompt_tokens", 0),
        "rerank_prompt_tokens": rerank_usage.get("prompt_tokens", 0),
        "candidate_titles": candidate_titles,
        "titles": titles,
    }


def _safe_average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _summarize_results(
    results: list[dict[str, Any]], retrieval_mode: str
) -> dict[str, Any]:
    total = len(results)
    if not total:
        raise ValueError("Cannot summarize an empty RAG evaluation run.")

    top1_hits = sum(1 for result in results if result["top1_title_hit"])
    topk_hits = sum(1 for result in results if result["topk_title_hit"])
    total_noise = sum(int(result["noise_count"]) for result in results)
    total_returned = sum(int(result["returned_count"]) for result in results)
    total_required_hits = sum(
        int(result["required_keyword_hits"]) for result in results
    )
    total_required_keywords = sum(
        int(result["required_keyword_total"]) for result in results
    )
    total_candidate_hits = sum(
        int(result["candidate_relevant_hits"]) for result in results
    )
    total_relevant = sum(int(result["relevant_total"]) for result in results)
    total_final_hits = sum(int(result["final_relevant_hits"]) for result in results)
    total_relevant_results = sum(
        int(result["relevant_result_count"]) for result in results
    )

    candidate_metrics = {
        "recall_at_k_macro": _safe_average(
            [float(result["candidate_recall_at_k"]) for result in results]
        ),
        "recall_at_k_micro": total_candidate_hits / total_relevant,
        "relevant_targets_hit": total_candidate_hits,
        "relevant_targets_total": total_relevant,
        "avg_candidates_returned": _safe_average(
            [float(result["candidate_count"]) for result in results]
        ),
        "noise_count_total": sum(
            int(result["candidate_noise_count"]) for result in results
        ),
        "cross_destination_pollution": sum(
            int(result["candidate_pollution_count"]) for result in results
        ),
        "avg_latency_ms": _safe_average(
            [float(result["candidate_latency_ms"]) for result in results]
        ),
    }
    final_metrics = {
        "recall_at_k_macro": _safe_average(
            [float(result["final_recall_at_k"]) for result in results]
        ),
        "recall_at_k_micro": total_final_hits / total_relevant,
        "precision_at_k_macro": _safe_average(
            [float(result["precision_at_k"]) for result in results]
        ),
        "precision_at_returned_micro": total_relevant_results / total_returned
        if total_returned
        else 0.0,
        "ndcg_at_k_macro": _safe_average(
            [float(result["ndcg_at_k"]) for result in results]
        ),
        "mrr_relevant": _safe_average(
            [float(result["relevant_reciprocal_rank"]) for result in results]
        ),
        "top1_title_hit_rate": top1_hits / total,
        "top1_title_hits": top1_hits,
        "topk_title_hit_rate": topk_hits / total,
        "topk_title_hits": topk_hits,
        "required_keyword_coverage": total_required_hits / total_required_keywords
        if total_required_keywords
        else 0.0,
        "required_keyword_hits": total_required_hits,
        "required_keyword_total": total_required_keywords,
        "mrr_legacy_title": _safe_average(
            [float(result["reciprocal_rank"]) for result in results]
        ),
        "noise_count_total": total_noise,
        # 修正旧脚本分母：按实际返回 chunk 数，而非 cases * 第一条 top_k。
        "noise_rate": total_noise / total_returned if total_returned else 0.0,
        "returned_count_total": total_returned,
        "cross_destination_pollution": sum(
            int(result["pollution_count"]) for result in results
        ),
        "avg_latency_ms": _safe_average(
            [float(result["latency_ms"]) for result in results]
        ),
    }
    usage = {
        "embedding_prompt_tokens_total": sum(
            int(result["embedding_prompt_tokens"]) for result in results
        ),
        "rerank_prompt_tokens_total": sum(
            int(result["rerank_prompt_tokens"]) for result in results
        ),
    }
    return {
        "retrieval_mode": retrieval_mode,
        "cases": total,
        "candidate_metrics": candidate_metrics,
        "final_metrics": final_metrics,
        "usage": usage,
    }


def _comparison_deltas(
    summaries: dict[str, dict[str, Any]], baseline_mode: str
) -> dict[str, Any]:
    baseline = summaries[baseline_mode]
    metric_paths = {
        "candidate_recall_at_k_macro": ("candidate_metrics", "recall_at_k_macro"),
        "candidate_recall_at_k_micro": ("candidate_metrics", "recall_at_k_micro"),
        "final_recall_at_k_macro": ("final_metrics", "recall_at_k_macro"),
        "final_precision_at_k_macro": ("final_metrics", "precision_at_k_macro"),
        "final_ndcg_at_k_macro": ("final_metrics", "ndcg_at_k_macro"),
        "final_mrr_relevant": ("final_metrics", "mrr_relevant"),
        "final_noise_rate": ("final_metrics", "noise_rate"),
        "avg_latency_ms": ("final_metrics", "avg_latency_ms"),
    }
    deltas: dict[str, dict[str, float]] = {}
    for mode, summary in summaries.items():
        mode_deltas: dict[str, float] = {}
        for output_name, (section, metric) in metric_paths.items():
            mode_deltas[output_name] = round(
                float(summary[section][metric])
                - float(baseline[section][metric]),
                6,
            )
        deltas[mode] = mode_deltas
    return {"baseline_mode": baseline_mode, "deltas": deltas}


def _print_case_result(result: dict[str, Any]) -> None:
    print(f"case: {result['id']}")
    print(f"destination: {result['destination']}")
    print(f"retrieval_mode: {result['retrieval_mode']}")
    print(f"retrieval_query: {result['retrieval_query']}")
    print(f"lexical_query: {result['lexical_query']}")
    print(f"rerank_query: {result['rerank_query']}")
    print(
        "candidate_recall: "
        f"{result['candidate_relevant_hits']}/{result['relevant_total']} "
        f"({result['candidate_recall_at_k']:.3f})"
    )
    print(f"top1_title: {result['top1_title']}")
    print(f"top1_title_hit: {result['top1_title_hit']}")
    print(f"topk_title_hit: {result['topk_title_hit']}")
    print(
        "required_keyword_hits: "
        f"{result['required_keyword_hits']}/{result['required_keyword_total']}"
    )
    print(f"precision_at_k: {result['precision_at_k']:.3f}")
    print(f"ndcg_at_k: {result['ndcg_at_k']:.3f}")
    print(f"noise_count: {result['noise_count']}")
    print(f"reciprocal_rank: {result['reciprocal_rank']:.3f}")
    print(f"relevant_reciprocal_rank: {result['relevant_reciprocal_rank']:.3f}")
    print(f"pollution_count: {result['pollution_count']}")
    print(f"candidate_latency_ms: {result['candidate_latency_ms']}")
    print(f"rerank_latency_ms: {result['rerank_latency_ms']}")
    print(f"latency_ms: {result['latency_ms']}")
    print(f"embedding_prompt_tokens: {result['embedding_prompt_tokens']}")
    print(f"rerank_prompt_tokens: {result['rerank_prompt_tokens']}")
    print("candidate_titles:")
    for index, title in enumerate(result["candidate_titles"], start=1):
        print(f"  {index}. {title}")
    print("titles:")
    for index, title in enumerate(result["titles"], start=1):
        print(f"  {index}. {title}")
    print("-" * 60)


def _print_summary(summary: dict[str, Any]) -> None:
    candidate = summary["candidate_metrics"]
    final = summary["final_metrics"]
    usage = summary["usage"]
    total = int(summary["cases"])

    print(f"=== Summary [{summary['retrieval_mode']}] ===")
    print(f"cases: {total}")
    print(
        "candidate_recall_at_k: "
        f"{candidate['relevant_targets_hit']}/{candidate['relevant_targets_total']} "
        f"(macro={candidate['recall_at_k_macro']:.3f}, "
        f"micro={candidate['recall_at_k_micro']:.3f})"
    )
    print(f"final_recall_at_k_macro: {final['recall_at_k_macro']:.3f}")
    print(f"precision_at_k_macro: {final['precision_at_k_macro']:.3f}")
    print(f"ndcg_at_k_macro: {final['ndcg_at_k_macro']:.3f}")
    print(f"MRR_relevant: {final['mrr_relevant']:.3f}")
    print(
        "top1_title_hit_rate: "
        f"{final['top1_title_hits']}/{total} "
        f"({final['top1_title_hit_rate']*100:.1f}%)"
    )
    print(
        "topk_title_hit_rate: "
        f"{final['topk_title_hits']}/{total} "
        f"({final['topk_title_hit_rate']*100:.1f}%)"
    )
    print(
        "required_keyword_coverage: "
        f"{final['required_keyword_hits']}/{final['required_keyword_total']}"
    )
    print(f"MRR: {final['mrr_legacy_title']:.3f}")
    print(f"noise_count_total: {final['noise_count_total']}")
    print(f"noise_rate: {final['noise_rate']*100:.1f}%")
    print(
        "cross_destination_pollution: "
        f"{final['cross_destination_pollution']}"
    )
    print(f"avg_latency_ms: {final['avg_latency_ms']:.1f}")
    print(
        "embedding_prompt_tokens_total: "
        f"{usage['embedding_prompt_tokens_total']}"
    )
    print(
        "rerank_prompt_tokens_total: "
        f"{usage['rerank_prompt_tokens_total']}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate candidate retrieval and final reranking with frozen queries "
            "and gold chunk annotations."
        )
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Path to the RAG eval cases JSON file.",
    )
    parser.add_argument(
        "--retrieval-mode",
        "--mode",
        dest="retrieval_modes",
        action="append",
        help="Run one retrieval mode; repeat the flag for an A/B comparison.",
    )
    parser.add_argument(
        "--compare-modes",
        "--retrieval-modes",
        nargs="+",
        help="Run the same frozen cases for all listed modes, e.g. vector hybrid.",
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        help="Override candidate_k for every mode and case (fair A/B pool size).",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Write cases, summaries and baseline deltas as machine-readable JSON.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Suppress per-case console details.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cases = _load_cases(args.cases)
    retrieval_modes = (
        args.compare_modes
        or args.retrieval_modes
        or [DEFAULT_RETRIEVAL_MODE]
    )
    retrieval_modes = list(dict.fromkeys(retrieval_modes))

    runs: dict[str, dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for mode in retrieval_modes:
        results = [
            _evaluate_case(
                case,
                retrieval_mode=mode,
                candidate_k_override=args.candidate_k,
            )
            for case in cases
        ]
        summary = _summarize_results(results, mode)
        summaries[mode] = summary
        runs[mode] = {"summary": summary, "cases": results}

        if not args.summary_only:
            for result in results:
                _print_case_result(result)
        _print_summary(summary)

    comparison = _comparison_deltas(summaries, retrieval_modes[0])
    if len(retrieval_modes) > 1:
        print(f"=== A/B deltas (baseline={retrieval_modes[0]}) ===")
        for mode, deltas in comparison["deltas"].items():
            if mode == retrieval_modes[0]:
                continue
            print(f"{mode}: {json.dumps(deltas, ensure_ascii=False, sort_keys=True)}")

    if args.json_output:
        payload = {
            "schema_version": 2,
            "cases_path": str(args.cases.resolve()),
            "retrieval_modes": retrieval_modes,
            "candidate_k_override": args.candidate_k,
            "runs": runs,
            "comparison": comparison,
        }
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"json_output: {args.json_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
