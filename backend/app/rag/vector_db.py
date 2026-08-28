from __future__ import annotations

import logging
import re
import unicodedata
from hashlib import md5
from pathlib import Path
from typing import Any

import httpx

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.rag.pdf_loader import load_pdf_pages

from app.config import (
    BACKEND_DIR,
    CHROMA_COLLECTION_NAME,
    CHROMA_DB_DIR,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    RAG_MAX_VECTOR_DISTANCE,
)


DATA_DIR = BACKEND_DIR / "data"
logger = logging.getLogger(__name__)


# H1/H2/H3 都作为结构边界，metadata 里保留各自层级
_HEADERS_TO_SPLIT_ON = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]

# 中文优先的递归分隔符：先段落、再换行、再中文句末/句中标点，最后才退化到单字符。
# RecursiveCharacterTextSplitter 默认是 ["\n\n", "\n", " ", ""]，对中文几乎只能按字符硬切，必须自定义。
_CHINESE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", "、", " ", ""]

# 单个片段的目标字符数与重叠，按文档密度和 embedding 上下文调整
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 80

_KNOWLEDGE_PATTERNS = ("*.md", "*.markdown", "*.pdf")
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")


def _title_from_metadata(metadata: dict) -> str:
    """取最细一级标题作为片段 title，保持与旧实现一致（rerank 仍按标题匹配）。"""
    return (
        metadata.get("h3")
        or metadata.get("h2")
        or metadata.get("h1")
        or "文档开头"
    )


def _breadcrumb_from_metadata(metadata: dict) -> str:
    """拼出 H1 > H2 > H3 面包屑，给片段补充层级上下文。"""
    parts = [metadata.get(level) for level in ("h1", "h2", "h3")]
    parts = [p for p in parts if p]
    return " > ".join(parts) if parts else "文档开头"


def _destination_from_metadata(metadata: dict) -> str:
    """从攻略 H1（如“2026 成都深度游玩全攻略”）提取目的地。"""
    heading = str(metadata.get("h1", "")).strip()
    if not heading:
        return ""
    match = re.match(
        r"^(?:\d{4}\s*)?(.+?)(?:深度|旅游|旅行|自由行|游玩|全攻略|攻略)",
        heading,
    )
    if match:
        return match.group(1).strip(" -—：:")
    return ""


def _clean_markdown_text(text: str) -> str:
    """在结构切分前做保守清洗，不破坏 Markdown 标题和列表。"""
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{4,}", "\n\n\n", text).strip()


def _destination_from_pdf(text: str, source_name: str) -> str:
    first_lines = [line.strip() for line in text.splitlines() if line.strip()][:5]
    for line in first_lines:
        destination = _destination_from_metadata({"h1": line})
        if destination:
            return destination

    stem = re.sub(
        r"(?:[_-]?guide|[_-]?攻略|[_-]?旅游指南|[_-]?旅行指南)$",
        "",
        source_name.rsplit(".", 1)[0],
        flags=re.IGNORECASE,
    )
    return stem.strip(" _-")


def _title_from_pdf_page(text: str, page_number: int) -> str:
    for line in text.splitlines():
        candidate = line.strip(" #\t")
        if 2 <= len(candidate) <= 60:
            return candidate
    return f"第 {page_number} 页"


def _split_markdown_into_chunks(
    markdown_text: str,
    source_name: str,
    chunk_size: int = _CHUNK_SIZE,
    chunk_overlap: int = _CHUNK_OVERLAP,
) -> list[dict[str, str]]:
    """先按标题结构切分并保留层级，再对过长片段做带重叠的二次切分。"""
    markdown_text = _clean_markdown_text(markdown_text)
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS_TO_SPLIT_ON,
        strip_headers=True,  # 正文去掉 # 标题行，标题改由 metadata 承载，避免重复
    )
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_CHINESE_SEPARATORS,
        keep_separator=True,  # 保留句末标点，切完更像完整句子
    )

    chunks: list[dict[str, str]] = []
    for section in header_splitter.split_text(markdown_text):
        # 第一个标题之前的内容 metadata 为空 -> 仍归到“文档开头”，
        # 这样 retriever.py 里对“文档开头”的降权逻辑继续生效。
        title = _title_from_metadata(section.metadata)
        breadcrumb = _breadcrumb_from_metadata(section.metadata)
        destination = _destination_from_metadata(section.metadata)

        section_text = section.page_content.strip()
        if not section_text:
            continue

        for piece in size_splitter.split_text(section_text):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(
                {
                    "title": title,
                    "breadcrumb": breadcrumb,
                    "text": piece,
                    "source": source_name,
                    "destination": destination,
                }
            )

    return chunks


def _split_pdf_into_chunks(
    pdf_path: Path,
    chunk_size: int = _CHUNK_SIZE,
    chunk_overlap: int = _CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """按页保留来源信息，再在页内按中文标点递归切分。"""
    pages = load_pdf_pages(pdf_path)
    size_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_CHINESE_SEPARATORS,
        keep_separator=True,
    )

    document_sample = "\n".join(str(page["text"]) for page in pages[:3])
    destination = _destination_from_pdf(document_sample, pdf_path.name)
    chunks: list[dict[str, Any]] = []
    for page in pages:
        page_text = str(page["text"]).strip()
        page_number = int(page["page_start"])
        title = _title_from_pdf_page(page_text, page_number)
        for piece in size_splitter.split_text(page_text):
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(
                {
                    "title": title,
                    "breadcrumb": f"{title} > 第 {page_number} 页",
                    "text": piece,
                    "source": pdf_path.name,
                    "destination": destination,
                    "page_start": page_number,
                    "page_end": int(page["page_end"]),
                    "parser": str(page["parser"]),
                }
            )
    return chunks


def _build_chunk_id(
    source: str,
    title: str,
    text: str,
    page_start: int = 0,
) -> str:
    """基于 source、title 和 text 生成稳定片段 ID。"""
    page_part = f"|page={page_start}" if page_start else ""
    digest = md5(f"{source}|{title}|{text}{page_part}".encode("utf-8")).hexdigest()
    return f"{source}_{digest}"


def _build_document_text(chunk: dict[str, str]) -> str:
    """
    把（面包屑）标题和正文拼成送入向量库的文档文本。

    用 breadcrumb 替代单一标题，让 embedding 能感知“这段属于哪个城市/哪个主题下”。
    第一行仍是单行 heading，剩下是正文，与 _search_guide_chunks_by_chroma 里
    `document.split("\\n", 1)[1]` 的取正文逻辑兼容。
    """
    heading = chunk.get("breadcrumb") or chunk.get("title", "")
    return f"{heading}\n{chunk['text']}"


def load_guide_chunks() -> list[dict[str, str]]:
    """读取 backend/data 下的攻略文件，并切分成可检索片段。单个文件失败不影响整体。"""
    chunks: list[dict[str, str]] = []
    seen_fingerprints: set[str] = set()

    guide_files = sorted(
        {
            path
            for pattern in _KNOWLEDGE_PATTERNS
            for path in DATA_DIR.glob(pattern)
        }
    )

    for guide_file in guide_files:
        try:
            if guide_file.suffix.lower() == ".pdf":
                raw_chunks = _split_pdf_into_chunks(guide_file)
            else:
                text = guide_file.read_text(encoding="utf-8")
                raw_chunks = _split_markdown_into_chunks(text, guide_file.name)
        except (OSError, UnicodeDecodeError, RuntimeError, ValueError) as exc:
            logger.warning(
                "[RAG] 跳过无法解析的知识库文件 file=%s error_type=%s message=%s",
                guide_file.name,
                type(exc).__name__,
                exc,
            )
            continue

        for chunk in raw_chunks:
            fingerprint = md5(
                f"{chunk['source']}|{chunk['title']}|{chunk['text']}".encode("utf-8")
            ).hexdigest()
            if fingerprint in seen_fingerprints:
                logger.info(
                    "[RAG] 跳过重复片段 file=%s title=%s",
                    chunk["source"],
                    chunk["title"],
                )
                continue
            seen_fingerprints.add(fingerprint)
            page_start = int(chunk.get("page_start", 0))
            chunks.append(
                {
                    "id": _build_chunk_id(
                        chunk["source"],
                        chunk["title"],
                        chunk["text"],
                        page_start=page_start,
                    ),
                    "title": chunk["title"],
                    "text": chunk["text"],
                    "source": chunk["source"],
                    "breadcrumb": chunk.get("breadcrumb", chunk["title"]),
                    "destination": chunk.get("destination", ""),
                    "page_start": page_start,
                    "page_end": int(chunk.get("page_end", page_start)),
                    "parser": chunk.get("parser", "markdown"),
                }
            )
    return chunks


def _extract_keywords(query: str) -> list[str]:
    """把查询语句切成简单关键词，用于回退匹配。"""
    raw_keywords = re.split(r"[\s,，。；;、]+", query)
    return [keyword.strip() for keyword in raw_keywords if keyword.strip()]


def _score_chunk(query: str, chunk_text: str) -> int:
    """按关键词出现次数给片段打分。"""
    keywords = _extract_keywords(query)
    return sum(1 for keyword in keywords if keyword in chunk_text)


def _search_guide_chunks_by_keywords(
    query: str,
    top_k: int = 3,
    destination: str | None = None,
) -> list[dict[str, str]]:
    """回退方案：使用关键词匹配本地攻略片段。"""
    scored_chunks: list[tuple[int, dict[str, str]]] = []
    for chunk in load_guide_chunks():
        if destination and chunk.get("destination") != destination:
            continue
        score = _score_chunk(query, _build_document_text(chunk))
        if score > 0:
            scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _, chunk in scored_chunks[:top_k]]


def _build_embeddings():
    """创建 embedding 模型实例。"""
    if not LLM_API_KEY:
        return None

    try:
        from langchain_openai import OpenAIEmbeddings
    except ImportError:
        return None

    try:
        return OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL or None,
            chunk_size=EMBEDDING_BATCH_SIZE,
            check_embedding_ctx_length=False,
        )
    except TypeError:
        return OpenAIEmbeddings(
            model=EMBEDDING_MODEL,
            openai_api_key=LLM_API_KEY,
            openai_api_base=LLM_BASE_URL or None,
            chunk_size=EMBEDDING_BATCH_SIZE,
            check_embedding_ctx_length=False,
        )


def _extract_embedding_token_usage(response_data: dict) -> dict[str, int]:
    """读取 embeddings 接口返回的官方 usage；没有 usage 时保持 0。"""
    usage = response_data.get("usage") or {}
    prompt_tokens = (
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("input_token_count")
        or usage.get("total_tokens")
        or usage.get("total_token_count")
        or 0
    )
    return {
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": 0,
    }


def _embed_query_with_usage(query: str) -> tuple[list[float] | None, dict[str, int]]:
    """在线 query embedding：优先直接调接口拿官方 usage，失败时回退 LangChain 但 usage 为 0。"""
    empty_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    if not LLM_API_KEY:
        return None, empty_usage

    base_url = (LLM_BASE_URL or "https://api.openai.com/v1").rstrip("/")
    endpoint = f"{base_url}/embeddings"
    payload = {
        "model": EMBEDDING_MODEL,
        "input": query,
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(endpoint, json=payload, headers=headers)
        if response.status_code == 200:
            data = response.json()
            items = data.get("data") or []
            if items and "embedding" in items[0]:
                usage = _extract_embedding_token_usage(data)
                logger.info(
                    "[RAG·Embedding] 完成 input_tokens=%s output_tokens=0 total_tokens=%s",
                    usage["prompt_tokens"],
                    usage["prompt_tokens"],
                )
                return items[0]["embedding"], usage
            logger.warning("[RAG·Embedding] 接口响应缺少向量")
        else:
            logger.warning("[RAG·Embedding] 接口调用失败 status=%s", response.status_code)
    except Exception as exc:
        logger.warning("[RAG·Embedding] 接口调用失败 error_type=%s", type(exc).__name__)

    embeddings = _build_embeddings()
    if embeddings is None:
        return None, empty_usage
    logger.info("[RAG·Embedding] 使用 LangChain 回退，无法取得官方 Token 用量")
    return embeddings.embed_query(query), empty_usage


def _get_chroma_collection():
    """获取 Chroma collection。"""
    try:
        import chromadb
    except ImportError:
        return None

    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    return client.get_or_create_collection(
        name=CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def ingest_guide_chunks_to_chroma() -> int:
    """
    把本地攻略片段写入 Chroma。

    流程是：
    1. 创建 embedding 模型
    2. 获取 Chroma collection
    3. 读取并切分本地攻略
    4. 生成向量
    5. 把向量、文本和 metadata 一起写入 Chroma
    """
    embeddings = _build_embeddings()
    collection = _get_chroma_collection()
    chunks = load_guide_chunks()

    if embeddings is None:
        raise RuntimeError("当前环境缺少 embedding 能力，无法写入 Chroma。")
    if collection is None:
        raise RuntimeError("当前环境缺少 chromadb，无法写入 Chroma。")

    documents = [_build_document_text(chunk) for chunk in chunks]
    vectors = embeddings.embed_documents(documents)
    ids = [chunk["id"] for chunk in chunks]
    metadatas = [
        {
            "title": chunk["title"],
            "source": chunk["source"],
            "breadcrumb": chunk.get("breadcrumb", chunk["title"]),
            "destination": chunk.get("destination", ""),
            "page_start": chunk.get("page_start", 0),
            "page_end": chunk.get("page_end", 0),
            "parser": chunk.get("parser", "markdown"),
        }
        for chunk in chunks
    ]

    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=vectors,
    )
    return len(chunks)


def _search_guide_chunks_by_chroma(
    query: str,
    top_k: int = 3,
    destination: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """优先使用 Chroma 做向量检索，并返回在线 query embedding token。"""
    collection = _get_chroma_collection()
    empty_usage = {"prompt_tokens": 0, "completion_tokens": 0}

    if collection is None:
        return [], empty_usage
    if collection.count() == 0:
        return [], empty_usage

    query_embedding, embedding_usage = _embed_query_with_usage(query)
    if query_embedding is None:
        return [], empty_usage
    query_kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if destination:
        query_kwargs["where"] = {"destination": destination}
    result = collection.query(
        **query_kwargs,
    )

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    result_ids = result.get("ids", [[]])[0]

    matched_chunks: list[dict[str, Any]] = []
    for index, (document, metadata, distance) in enumerate(
        zip(documents, metadatas, distances)
    ):
        if distance is None or float(distance) > RAG_MAX_VECTOR_DISTANCE:
            continue
        title = metadata.get("title", "未命名片段") if metadata else "未命名片段"
        source = metadata.get("source", "未知来源") if metadata else "未知来源"
        breadcrumb = metadata.get("breadcrumb", title) if metadata else title
        text = document.split("\n", 1)[1] if "\n" in document else document
        page_start = metadata.get("page_start", 0) if metadata else 0
        chunk_id = (
            str(result_ids[index])
            if index < len(result_ids) and result_ids[index]
            else _build_chunk_id(
                source=source,
                title=title,
                text=text,
                page_start=int(page_start or 0),
            )
        )
        matched_chunks.append(
            {
                "id": chunk_id,
                "title": title,
                "text": text,
                "source": source,
                "breadcrumb": breadcrumb,
                "destination": metadata.get("destination", "") if metadata else "",
                "page_start": page_start,
                "page_end": metadata.get("page_end", 0) if metadata else 0,
                "parser": metadata.get("parser", "unknown") if metadata else "unknown",
            }
        )

    return matched_chunks, embedding_usage


def search_guide_chunks_with_usage(
    query: str,
    top_k: int = 3,
    destination: str | None = None,
    *,
    lexical_query: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    从本地攻略片段里找最相关的 top_k 条结果。

    优先走向量检索；向量不可用时使用独立 lexical query 做关键词回退。
    """
    empty_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    if top_k <= 0:
        return [], empty_usage

    chroma_results, embedding_usage = _search_guide_chunks_by_chroma(
        query=query,
        top_k=top_k,
        destination=destination,
    )
    if chroma_results:
        return chroma_results, embedding_usage
    effective_lexical_query = lexical_query if lexical_query is not None else query
    return _search_guide_chunks_by_keywords(
        query=effective_lexical_query,
        top_k=top_k,
        destination=destination,
    ), empty_usage


def search_guide_chunks(
    query: str,
    top_k: int = 3,
    destination: str | None = None,
) -> list[dict[str, str]]:
    """兼容旧调用：只返回检索片段，不返回 token usage。"""
    chunks, _ = search_guide_chunks_with_usage(
        query=query,
        top_k=top_k,
        destination=destination,
    )
    return chunks
