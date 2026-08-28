from pathlib import Path
import sys


CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.agents.tools.rag_tool as rag_tool  # noqa: E402


def test_build_destination_queries_keeps_each_query_role_separate(monkeypatch) -> None:
    rewrite_usage = {"prompt_tokens": 12, "completion_tokens": 4}
    monkeypatch.setattr(
        rag_tool,
        "llm_rewrite_query",
        lambda **kwargs: ("大理 洱海 双廊 日落 摄影", rewrite_usage),
    )

    queries, usage = rag_tool.build_destination_queries(
        destination="大理",
        preferences=["自然风景", "摄影"],
        pace="轻松",
        special_notes="不想太早起床，想在双廊看日落",
    )

    assert queries.dense_query == "大理 洱海 双廊 日落 摄影"
    assert "不想太早起床，想在双廊看日落" in queries.lexical_query
    assert "双廊" in queries.lexical_query
    assert queries.rerank_query == (
        "目的地：大理\n"
        "旅行偏好：自然风景、摄影\n"
        "行程节奏：轻松\n"
        "特别备注：不想太早起床，想在双廊看日落"
    )
    assert "洱海" not in queries.rerank_query
    assert usage == rewrite_usage


def test_rule_query_preserves_unknown_entities_without_generic_noise(monkeypatch) -> None:
    monkeypatch.setattr(
        rag_tool,
        "llm_rewrite_query",
        lambda **kwargs: (None, {"prompt_tokens": 0, "completion_tokens": 0}),
    )

    query, _ = rag_tool.build_destination_query(
        destination="北京",
        special_notes="只去智化寺，下午三点以后出发",
    )

    assert "智化寺" in query
    assert "下午三点以后出发" in query
    assert "行程" not in query
    assert "推荐" not in query


def test_lexical_query_does_not_add_guessed_destination_entities() -> None:
    query = rag_tool._build_lexical_query(
        destination="大理",
        preferences=["摄影"],
        pace="轻松",
        special_notes="想在苍山看日落",
    )

    assert query == "大理 摄影 轻松 想在苍山看日落"
    assert "洱海" not in query
    assert "双廊" not in query


def test_get_destination_context_passes_dense_lexical_and_rerank_queries(monkeypatch) -> None:
    queries = rag_tool.DestinationRetrievalQueries(
        dense_query="dense query",
        lexical_query="lexical query",
        rerank_query="完整原始需求",
    )
    rewrite_usage = {"prompt_tokens": 2, "completion_tokens": 1}
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        rag_tool,
        "build_destination_queries",
        lambda **kwargs: (queries, rewrite_usage),
    )

    def fake_retrieve_travel_guide(**kwargs):
        captured.update(kwargs)
        return (
            ["context"],
            {"prompt_tokens": 3, "completion_tokens": 0},
            {"prompt_tokens": 5, "completion_tokens": 0},
        )

    monkeypatch.setattr(rag_tool, "retrieve_travel_guide", fake_retrieve_travel_guide)

    result = rag_tool.get_destination_guide_context(destination="大理", top_k=4)

    assert captured == {
        "query": "dense query",
        "top_k": 4,
        "destination": "大理",
        "lexical_query": "lexical query",
        "rerank_query": "完整原始需求",
    }
    assert result == (
        ["context"],
        rewrite_usage,
        {"prompt_tokens": 3, "completion_tokens": 0},
        {"prompt_tokens": 5, "completion_tokens": 0},
    )
