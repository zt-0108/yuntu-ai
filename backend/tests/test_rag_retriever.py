from pathlib import Path
import sys


# 允许测试文件直接导入 backend/app 下的模块。
CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.rag.retriever as retriever  # noqa: E402
from app.rag.vector_db import load_guide_chunks  # noqa: E402


def _real_guide_chunk(destination: str, title_keyword: str) -> dict[str, str]:
    return next(
        chunk
        for chunk in load_guide_chunks()
        if chunk.get("destination") == destination
        and title_keyword in chunk.get("title", "")
    )


def test_retrieve_travel_guide_formats_chunks_as_text(monkeypatch) -> None:
    """测试 retriever 会把检索结果格式化成可直接引用的文本片段。"""

    def fake_search_guide_chunks_with_usage(
        query: str,
        top_k: int = 3,
        destination: str | None = None,
        *,
        lexical_query: str | None = None,
    ) -> tuple[list[dict[str, str]], dict[str, int]]:
        assert query == "大理 古城 美食"
        assert lexical_query == "大理 古城 美食"
        assert top_k == 6
        assert destination == "大理"
        return [
            {
                "source": "dali_guide.pdf",
                "title": "大理古城",
                "text": "大理古城适合慢游和拍照。",
                "page_start": 3,
                "page_end": 3,
            }
        ], {"prompt_tokens": 0, "completion_tokens": 0}

    monkeypatch.setattr(retriever, "search_guide_chunks_with_usage", fake_search_guide_chunks_with_usage)
    monkeypatch.setattr(
        retriever,
        "rerank_guide_chunks",
        lambda query, matched_chunks, top_k, destination=None: (
            matched_chunks[:top_k],
            {"prompt_tokens": 0, "completion_tokens": 0},
        ),
    )

    results, _, _ = retriever.retrieve_travel_guide(
        "大理 古城 美食",
        top_k=2,
        destination="大理",
    )

    assert results == [
        "[来源: dali_guide.pdf | 页码: 3 | 标题: 大理古城]\n"
        "大理古城适合慢游和拍照。"
    ]


def test_retrieve_travel_guide_returns_empty_when_no_chunks(monkeypatch) -> None:
    """测试没有召回任何片段时，会返回空列表。"""

    def fake_search_guide_chunks_with_usage(
        query: str,
        top_k: int = 3,
        destination: str | None = None,
        *,
        lexical_query: str | None = None,
    ) -> tuple[list[dict[str, str]], dict[str, int]]:
        assert query == "火星 沙漠 极地科考"
        assert lexical_query == "火星 沙漠 极地科考"
        assert top_k == 6
        assert destination == "火星"
        return [], {"prompt_tokens": 0, "completion_tokens": 0}

    monkeypatch.setattr(retriever, "search_guide_chunks_with_usage", fake_search_guide_chunks_with_usage)
    monkeypatch.setattr(
        retriever,
        "rerank_guide_chunks",
        lambda query, matched_chunks, top_k, destination=None: (
            matched_chunks[:top_k],
            {"prompt_tokens": 0, "completion_tokens": 0},
        ),
    )

    results, _, _ = retriever.retrieve_travel_guide(
        "火星 沙漠 极地科考",
        top_k=2,
        destination="火星",
    )

    assert results == []


def test_cross_encoder_rerank_drops_low_relevance_results(monkeypatch) -> None:
    chunks = [
        {"source": "dali.md", "title": "大理古城", "text": "适合慢游。"},
        {"source": "dali.md", "title": "无关内容", "text": "普通说明。"},
    ]
    monkeypatch.setattr(retriever, "get_cached_json", lambda key: None)
    monkeypatch.setattr(retriever, "set_cached_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(retriever, "RAG_MIN_CROSS_ENCODER_SCORE", 0.2)
    monkeypatch.setattr(
        retriever,
        "_rerank_with_dashscope",
        lambda query, matched_chunks, top_k: (
            [(0.91, 0), (0.08, 1)],
            {"prompt_tokens": 0, "completion_tokens": 0},
        ),
    )

    results, _ = retriever.rerank_guide_chunks(
        query="大理 古城",
        matched_chunks=chunks,
        top_k=2,
        destination="大理",
    )

    assert [item["title"] for item in results] == ["大理古城"]


def test_retrieve_chunks_uses_separate_queries_for_search_and_rerank(monkeypatch) -> None:
    captured: dict[str, object] = {}
    chunks = [{"source": "dali.md", "title": "双廊", "text": "适合看日落。"}]

    def fake_search(**kwargs):
        captured["search"] = kwargs
        return chunks, {"prompt_tokens": 7, "completion_tokens": 0}

    def fake_rerank(**kwargs):
        captured["rerank"] = kwargs
        return chunks, {"prompt_tokens": 9, "completion_tokens": 0}

    monkeypatch.setattr(retriever, "search_guide_chunks_with_usage", fake_search)
    monkeypatch.setattr(retriever, "rerank_guide_chunks", fake_rerank)

    result, rerank_usage, embedding_usage = retriever.retrieve_travel_guide_chunks(
        query="大理 洱海 日落",
        lexical_query="大理 双廊 日落",
        rerank_query="目的地：大理\n特别备注：不想早起，傍晚去双廊看日落",
        top_k=3,
        destination="大理",
    )

    assert captured["search"] == {
        "query": "大理 洱海 日落",
        "lexical_query": "大理 双廊 日落",
        "top_k": 6,
        "destination": "大理",
    }
    assert captured["rerank"] == {
        "query": "目的地：大理\n特别备注：不想早起，傍晚去双廊看日落",
        "matched_chunks": chunks,
        "top_k": 3,
        "destination": "大理",
    }
    assert result == chunks
    assert rerank_usage["prompt_tokens"] == 9
    assert embedding_usage["prompt_tokens"] == 7


def test_retrieve_chunks_remains_compatible_with_legacy_search_signature(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def legacy_search(query: str, top_k: int, destination: str | None):
        captured.update(query=query, top_k=top_k, destination=destination)
        return [], {"prompt_tokens": 0, "completion_tokens": 0}

    monkeypatch.setattr(retriever, "search_guide_chunks_with_usage", legacy_search)
    monkeypatch.setattr(
        retriever,
        "rerank_guide_chunks",
        lambda **kwargs: ([], {"prompt_tokens": 0, "completion_tokens": 0}),
    )

    results, _, _ = retriever.retrieve_travel_guide_chunks(
        query="dense query",
        lexical_query="independent lexical query",
        rerank_query="完整需求",
        top_k=2,
        destination="大理",
    )

    assert results == []
    assert captured == {"query": "dense query", "top_k": 6, "destination": "大理"}


def test_rerank_cache_key_distinguishes_same_title_with_different_text() -> None:
    first = [{"source": "dali.md", "title": "双廊", "text": "适合看日落。"}]
    second = [{"source": "dali.md", "title": "双廊", "text": "适合清晨看日出。"}]

    first_key = retriever._build_rerank_cache_key("大理 日落", first, top_k=3)
    second_key = retriever._build_rerank_cache_key("大理 日落", second, top_k=3)
    larger_top_k_key = retriever._build_rerank_cache_key("大理 日落", first, top_k=5)

    assert first_key != second_key
    assert first_key != larger_top_k_key


def test_guide_cache_key_distinguishes_lexical_and_rerank_queries() -> None:
    common = {
        "query": "大理 洱海",
        "destination": "大理",
        "top_k": 5,
    }
    first_key = retriever._build_guide_cache_key(
        **common,
        lexical_query="大理 双廊",
        rerank_query="想在双廊看日落",
    )
    lexical_key = retriever._build_guide_cache_key(
        **common,
        lexical_query="大理 龙龛",
        rerank_query="想在双廊看日落",
    )
    rerank_key = retriever._build_guide_cache_key(
        **common,
        lexical_query="大理 双廊",
        rerank_query="想在龙龛看日出",
    )

    assert len({first_key, lexical_key, rerank_key}) == 3


def test_rule_rerank_does_not_boost_itinerary_without_itinerary_intent(monkeypatch) -> None:
    chunks = [
        {
            "source": "dali.md",
            "title": "特色行程",
            "text": "大理常规路线。",
            "destination": "大理",
        },
        {
            "source": "dali.md",
            "title": "双廊日落",
            "text": "双廊适合傍晚看日落。",
            "destination": "大理",
        },
    ]
    monkeypatch.setattr(retriever, "get_cached_json", lambda key: None)
    monkeypatch.setattr(retriever, "_rerank_with_dashscope", lambda *args, **kwargs: (None, {}))
    monkeypatch.setattr(retriever, "RAG_MIN_RULE_RERANK_SCORE", -100)

    results, _ = retriever.rerank_guide_chunks(
        query="目的地：大理\n行程节奏：轻松\n特别备注：不想早起，想去双廊看日落",
        matched_chunks=chunks,
        top_k=2,
        destination="大理",
    )

    assert [item["title"] for item in results] == ["双廊日落", "特色行程"]
    assert "domain+4:行程标题" not in results[1]["rerank_reasons"]


def test_rule_rerank_real_corpus_ignores_destination_as_topic_keyword() -> None:
    old_city = _real_guide_chunk("大理", "大理古城")
    pagoda = _real_guide_chunk("大理", "崇圣寺三塔")
    query = "目的地：大理\n特别备注：只去崇圣寺三塔，下午三点以后出发"

    old_city_score = retriever._score_chunk_for_rerank(
        query, dict(old_city), destination="大理"
    )
    pagoda_copy = dict(pagoda)
    pagoda_score = retriever._score_chunk_for_rerank(
        query, pagoda_copy, destination="大理"
    )

    assert "大理" not in retriever._extract_query_keywords(query, destination="大理")
    assert pagoda_score > old_city_score
    assert "title-exact+5:崇圣寺三塔" in pagoda_copy["rerank_reasons"]


def test_rule_rerank_real_corpus_keeps_combined_food_budget_chunk() -> None:
    old_city = _real_guide_chunk("大理", "大理古城")
    dining = _real_guide_chunk("大理", "特色餐饮与预算参考")
    query = "目的地：大理\n旅行偏好：美食"

    old_city_score = retriever._score_chunk_for_rerank(
        query, dict(old_city), destination="大理"
    )
    dining_copy = dict(dining)
    dining_score = retriever._score_chunk_for_rerank(
        query, dining_copy, destination="大理"
    )

    assert dining_score >= retriever.RAG_MIN_RULE_RERANK_SCORE
    assert dining_score > old_city_score
    assert "domain+3:餐饮意图" in dining_copy["rerank_reasons"]
    assert not any("弱相关" in reason for reason in dining_copy["rerank_reasons"])


def test_rule_rerank_real_corpus_boosts_explicit_itinerary_reference() -> None:
    old_city = _real_guide_chunk("大理", "大理古城")
    itinerary = _real_guide_chunk("大理", "经典三日行程参考")
    query = "目的地：大理\n特别备注：请给我经典三日行程参考"

    old_city_score = retriever._score_chunk_for_rerank(
        query, dict(old_city), destination="大理"
    )
    itinerary_copy = dict(itinerary)
    itinerary_score = retriever._score_chunk_for_rerank(
        query, itinerary_copy, destination="大理"
    )

    assert itinerary_score >= retriever.RAG_MIN_RULE_RERANK_SCORE
    assert itinerary_score > old_city_score
    assert "domain+4:行程标题" in itinerary_copy["rerank_reasons"]
    assert "domain-4:行程参考降权" not in itinerary_copy["rerank_reasons"]


def test_rule_rerank_does_not_treat_negated_itinerary_as_positive_intent() -> None:
    assert not retriever._has_itinerary_intent(
        "目的地：三亚\n特别备注：不需要紧凑的景点行程"
    )
