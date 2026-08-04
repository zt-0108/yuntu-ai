from __future__ import annotations

from app.rag import vector_db


def test_loaded_chunks_include_destination_metadata() -> None:
    chunks = vector_db.load_guide_chunks()

    assert chunks
    assert {chunk["destination"] for chunk in chunks} == {
        "成都",
        "大理",
        "三亚",
        "厦门",
        "西安",
    }


def test_keyword_fallback_returns_empty_for_missing_destination() -> None:
    results = vector_db._search_guide_chunks_by_keywords(
        query="苏州 园林 景点 行程 攻略 推荐",
        top_k=5,
        destination="苏州",
    )

    assert results == []


def test_vector_search_filters_by_destination_and_distance(monkeypatch) -> None:
    class FakeCollection:
        def count(self) -> int:
            return 2

        def query(self, **kwargs):
            assert kwargs["where"] == {"destination": "大理"}
            assert "distances" in kwargs["include"]
            return {
                "documents": [["大理 > 景点\n大理古城适合慢游。", "大理 > 其他\n弱相关内容。"]],
                "metadatas": [[
                    {
                        "source": "dali_guide.md",
                        "title": "大理古城",
                        "breadcrumb": "大理 > 景点",
                        "destination": "大理",
                    },
                    {
                        "source": "dali_guide.md",
                        "title": "其他",
                        "breadcrumb": "大理 > 其他",
                        "destination": "大理",
                    },
                ]],
                "distances": [[0.18, 0.92]],
            }

    monkeypatch.setattr(vector_db, "_get_chroma_collection", lambda: FakeCollection())
    monkeypatch.setattr(
        vector_db,
        "_embed_query_with_usage",
        lambda query: ([0.1, 0.2], {"prompt_tokens": 2, "completion_tokens": 0}),
    )
    monkeypatch.setattr(vector_db, "RAG_MAX_VECTOR_DISTANCE", 0.75)

    results, usage = vector_db._search_guide_chunks_by_chroma(
        query="大理 古城",
        top_k=2,
        destination="大理",
    )

    assert [item["title"] for item in results] == ["大理古城"]
    assert usage == {"prompt_tokens": 2, "completion_tokens": 0}
