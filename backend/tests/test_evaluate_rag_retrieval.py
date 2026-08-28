from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.rag.vector_db import load_guide_chunks
from scripts import evaluate_rag_retrieval as evaluator


def test_eval_cases_have_frozen_queries_and_resolvable_gold_documents() -> None:
    cases = evaluator._load_cases(evaluator.DEFAULT_CASES_PATH)
    chunks = load_guide_chunks()

    assert len(cases) >= 20
    assert {case["destination"] for case in cases} == set(
        evaluator.ALL_DESTINATIONS
    )
    assert any("numeric" in case.get("tags", []) for case in cases)
    assert any("alias" in case.get("tags", []) for case in cases)
    assert any("semantic" in case.get("tags", []) for case in cases)
    assert any("hard_negative" in case.get("tags", []) for case in cases)

    for case in cases:
        assert case["retrieval_query"].strip()
        assert case["lexical_query"].strip()
        assert case["rerank_query"].strip()
        relevant_chunk_ids: set[str] = set()
        for target in case["relevant_documents"]:
            matches = [
                chunk
                for chunk in chunks
                if evaluator._target_matches_chunk(target, chunk)
            ]
            assert len(matches) == 1, (case["id"], target, matches)
            relevant_chunk_ids.add(str(matches[0]["id"]))

        noise_chunk_ids = {
            str(chunk["id"])
            for chunk in chunks
            if evaluator._is_noise_chunk(case, chunk)
        }
        assert relevant_chunk_ids.isdisjoint(noise_chunk_ids), case["id"]


def test_evaluate_case_separates_candidate_and_rerank_metrics() -> None:
    case = {
        "id": "frozen_query_case",
        "destination": "大理",
        "retrieval_query": "固定 dense query",
        "lexical_query": "精确 lexical query",
        "rerank_query": "完整的用户自然语言问题",
        "top_k": 2,
        "candidate_k": 3,
        "expected_title_keywords": ["目标甲"],
        "required_content_keywords": ["答案"],
        "relevant_documents": [
            {"source": "dali.md", "title": "目标甲", "relevance": 3},
            {"source": "dali.md", "title": "目标乙", "relevance": 1},
        ],
        "noise_documents": [{"source": "chengdu.md", "title": "易混淆文档"}],
    }
    candidates = [
        {
            "source": "dali.md",
            "destination": "大理",
            "title": "目标甲",
            "text": "答案甲",
        },
        {
            "source": "dali.md",
            "destination": "大理",
            "title": "目标乙",
            "text": "答案乙",
        },
        {
            "source": "chengdu.md",
            "destination": "成都",
            "title": "易混淆文档",
            "text": "答案噪声",
        },
    ]
    calls: dict[str, Any] = {}

    def fake_search(
        query: str,
        top_k: int,
        destination: str,
        *,
        lexical_query: str,
        retrieval_mode: str,
    ):
        calls["search"] = (
            query,
            lexical_query,
            retrieval_mode,
            top_k,
            destination,
        )
        return candidates, {"prompt_tokens": 7, "completion_tokens": 0}

    def fake_rerank(
        query: str,
        matched_chunks: list[dict[str, Any]],
        top_k: int,
        destination: str,
    ):
        calls["rerank"] = (query, top_k, destination)
        return [matched_chunks[0], matched_chunks[2]], {
            "prompt_tokens": 11,
            "completion_tokens": 0,
        }

    result = evaluator._evaluate_case(
        case,
        retrieval_mode="hybrid",
        search_function=fake_search,
        rerank_function=fake_rerank,
    )

    assert calls["search"] == (
        "固定 dense query",
        "精确 lexical query",
        "hybrid",
        3,
        "大理",
    )
    assert calls["rerank"] == ("完整的用户自然语言问题", 2, "大理")
    assert result["candidate_recall_at_k"] == 1.0
    assert result["final_recall_at_k"] == 0.5
    assert result["precision_at_k"] == 0.5
    assert result["ndcg_at_k"] == pytest.approx(7 / (7 + 1 / 1.5849625))
    assert result["candidate_pollution_count"] == 1
    assert result["pollution_count"] == 1
    assert result["noise_count"] == 1
    assert result["embedding_prompt_tokens"] == 7
    assert result["rerank_prompt_tokens"] == 11


def test_summary_noise_rate_uses_actual_returned_chunks() -> None:
    base = {
        "top1_title_hit": True,
        "topk_title_hit": True,
        "noise_count": 1,
        "returned_count": 2,
        "required_keyword_hits": 1,
        "required_keyword_total": 1,
        "candidate_relevant_hits": 1,
        "relevant_total": 1,
        "final_relevant_hits": 1,
        "relevant_result_count": 1,
        "candidate_recall_at_k": 1.0,
        "candidate_count": 3,
        "candidate_noise_count": 1,
        "candidate_pollution_count": 0,
        "candidate_latency_ms": 10.0,
        "final_recall_at_k": 1.0,
        "precision_at_k": 0.5,
        "ndcg_at_k": 1.0,
        "relevant_reciprocal_rank": 1.0,
        "reciprocal_rank": 1.0,
        "pollution_count": 0,
        "latency_ms": 15.0,
        "embedding_prompt_tokens": 0,
        "rerank_prompt_tokens": 0,
    }
    second = dict(base, noise_count=0, returned_count=1, candidate_noise_count=0)

    summary = evaluator._summarize_results([base, second], "vector")

    assert summary["final_metrics"]["noise_rate"] == pytest.approx(1 / 3)
    assert summary["final_metrics"]["returned_count_total"] == 3


def test_pollution_check_covers_all_nine_destinations() -> None:
    chunks = [
        {"source": "杭州_guide.pdf", "title": "西湖", "destination": "杭州"},
        {"source": "nanjing_guide.pdf", "title": "夫子庙"},
        {"source": "suzhou_guide.pdf", "title": "园林"},
    ]

    assert evaluator._count_destination_pollution(chunks, "杭州") == 2


def test_load_cases_rejects_generated_or_missing_queries(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        '[{"id":"bad","destination":"大理","rerank_query":"问题",'
        '"relevant_documents":[{"source":"dali.md"}]}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="retrieval_query"):
        evaluator._load_cases(cases_path)
