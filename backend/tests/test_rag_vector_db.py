from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas

from app.rag import vector_db
from app.rag.pdf_loader import load_pdf_pages


def test_loaded_chunks_include_destination_metadata() -> None:
    chunks = vector_db.load_guide_chunks()

    assert chunks
    assert {chunk["destination"] for chunk in chunks} == {
        "成都",
        "大理",
        "三亚",
        "厦门",
        "西安",
        "苏州",
        "扬州",
        "杭州",
        "南京",
    }


def test_keyword_fallback_returns_empty_for_missing_destination() -> None:
    results = vector_db._search_guide_chunks_by_keywords(
        query="合肥 园林 景点 行程 攻略 推荐",
        top_k=5,
        destination="合肥",
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
                "ids": [["chunk-dali-old-city", "chunk-dali-weak"]],
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
    assert [item["id"] for item in results] == ["chunk-dali-old-city"]
    assert usage == {"prompt_tokens": 2, "completion_tokens": 0}


def test_vector_fallback_uses_independent_lexical_query(monkeypatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        vector_db,
        "_search_guide_chunks_by_chroma",
        lambda **kwargs: ([], {"prompt_tokens": 0, "completion_tokens": 0}),
    )

    def fake_keyword_search(query: str, top_k: int, destination: str | None):
        captured.update(query=query, top_k=top_k, destination=destination)
        return [{"title": "鼓浪屿", "text": "精确词回退结果"}]

    monkeypatch.setattr(
        vector_db,
        "_search_guide_chunks_by_keywords",
        fake_keyword_search,
    )

    results, usage = vector_db.search_guide_chunks_with_usage(
        query="厦门 海岛 文艺",
        lexical_query="鼓浪屿 日光岩 票价",
        top_k=4,
        destination="厦门",
    )

    assert captured == {
        "query": "鼓浪屿 日光岩 票价",
        "top_k": 4,
        "destination": "厦门",
    }
    assert results[0]["title"] == "鼓浪屿"
    assert usage == {"prompt_tokens": 0, "completion_tokens": 0}


def _write_text_pdf(path: Path) -> None:
    pdf = canvas.Canvas(str(path))
    for page_number in range(1, 4):
        pdf.drawString(72, 800, "YUNTU KNOWLEDGE BASE")
        pdf.drawString(
            72,
            720,
            f"Suzhou travel guide page {page_number}. Gardens and local food are recommended.",
        )
        pdf.drawString(280, 30, f"Page {page_number}")
        pdf.showPage()
    pdf.save()


def test_pdf_loader_removes_repeated_headers_and_footers(tmp_path: Path) -> None:
    pdf_path = tmp_path / "suzhou_guide.pdf"
    _write_text_pdf(pdf_path)

    pages = load_pdf_pages(pdf_path)

    assert len(pages) == 3
    assert [page["page_start"] for page in pages] == [1, 2, 3]
    assert all("YUNTU KNOWLEDGE BASE" not in str(page["text"]) for page in pages)
    assert all("Page 1" not in str(page["text"]) for page in pages)
    assert "Gardens and local food" in str(pages[0]["text"])


def test_pdf_chunks_keep_page_and_parser_metadata(monkeypatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "suzhou_guide.pdf"
    pdf_path.touch()
    monkeypatch.setattr(
        vector_db,
        "load_pdf_pages",
        lambda path: [
            {
                "text": "苏州旅游攻略\n拙政园适合上午游览。平江路适合傍晚散步。",
                "page_start": 2,
                "page_end": 2,
                "parser": "pymupdf",
            }
        ],
    )

    chunks = vector_db._split_pdf_into_chunks(pdf_path, chunk_size=30, chunk_overlap=5)

    assert chunks
    assert {chunk["destination"] for chunk in chunks} == {"苏州"}
    assert {chunk["page_start"] for chunk in chunks} == {2}
    assert {chunk["parser"] for chunk in chunks} == {"pymupdf"}


def test_markdown_is_cleaned_before_splitting() -> None:
    chunks = vector_db._split_markdown_into_chunks(
        "# 2026 苏州旅游攻略\r\n\r\n园林\u200b推荐。   \r\n",
        "suzhou.md",
    )

    assert chunks[0]["text"] == "园林推荐。"
