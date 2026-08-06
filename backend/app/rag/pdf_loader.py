from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_PAGE_NUMBER_RE = re.compile(
    r"^(?:第\s*)?[-—–]?\s*\d{1,5}\s*[-—–]?(?:\s*页)?(?:\s*/\s*\d{1,5})?$",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^(?:[-*•·]|\d+[.)、]|[（(]?\d+[）)])\s*")
_SENTENCE_ENDINGS = tuple("。！？!?；;：:")
_ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"}


@dataclass(frozen=True)
class PdfPage:
    number: int
    blocks: tuple[tuple[float, float, float, float, str], ...]
    height: float
    used_ocr: bool = False


def _normalize_text(value: str) -> str:
    """标准化 PDF 提取文本，同时保留换行和制表符。"""
    value = unicodedata.normalize("NFKC", value)
    cleaned: list[str] = []
    for char in value:
        if char in _ZERO_WIDTH:
            continue
        if char in "\n\t" or unicodedata.category(char) != "Cc":
            cleaned.append(char)
    value = "".join(cleaned).replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r" *\n *", "\n", value)
    return value.strip()


def _canonical_margin_text(value: str) -> str:
    value = _normalize_text(value).lower()
    value = re.sub(r"\d+", "#", value)
    return re.sub(r"\s+", "", value)


def _is_latin_word_break(previous: str, current: str) -> bool:
    return bool(
        previous.endswith("-")
        and len(previous) >= 2
        and current
        and previous[-2].isascii()
        and previous[-2].isalpha()
        and current[0].isascii()
        and current[0].islower()
    )


def _join_wrapped_lines(value: str) -> str:
    """合并 PDF 坐标布局制造的硬换行，保留列表和自然段边界。"""
    lines = [_normalize_text(line) for line in value.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    result = lines[0]
    for line in lines[1:]:
        if _BULLET_RE.match(line):
            result += f"\n{line}"
        elif _is_latin_word_break(result, line):
            result = result[:-1] + line
        elif result.endswith(_SENTENCE_ENDINGS):
            result += f"\n{line}"
        elif result[-1:].isascii() and line[:1].isascii():
            result += f" {line}"
        else:
            result += line
    return result.strip()


def _extract_page(page: Any, page_number: int) -> PdfPage:
    text_page = None
    raw_text = page.get_text("text").strip()
    used_ocr = False

    if len(raw_text) < 20:
        try:
            text_page = page.get_textpage_ocr(
                language="chi_sim+eng",
                dpi=200,
                full=True,
            )
            used_ocr = True
        except Exception as exc:
            logger.warning(
                "[RAG·PDF] 页面缺少可提取文本且 OCR 不可用 page=%s error_type=%s",
                page_number,
                type(exc).__name__,
            )

    kwargs = {"sort": True}
    if text_page is not None:
        kwargs["textpage"] = text_page
    raw_blocks = page.get_text("blocks", **kwargs)

    blocks: list[tuple[float, float, float, float, str]] = []
    for block in raw_blocks:
        if len(block) < 5:
            continue
        text = _join_wrapped_lines(str(block[4]))
        if text:
            blocks.append(
                (
                    float(block[0]),
                    float(block[1]),
                    float(block[2]),
                    float(block[3]),
                    text,
                )
            )

    return PdfPage(
        number=page_number,
        blocks=tuple(blocks),
        height=float(page.rect.height),
        used_ocr=used_ocr,
    )


def _repeated_margin_keys(pages: list[PdfPage]) -> set[str]:
    if len(pages) < 2:
        return set()

    appearances: Counter[str] = Counter()
    for page in pages:
        keys_on_page: set[str] = set()
        for _, y0, _, y1, text in page.blocks:
            in_margin = y1 <= page.height * 0.12 or y0 >= page.height * 0.88
            if in_margin:
                key = _canonical_margin_text(text)
                if key:
                    keys_on_page.add(key)
        appearances.update(keys_on_page)

    threshold = max(2, math.ceil(len(pages) * 0.5))
    return {key for key, count in appearances.items() if count >= threshold}


def _clean_page(page: PdfPage, repeated_margin_keys: set[str]) -> str:
    paragraphs: list[str] = []
    for _, y0, _, y1, text in page.blocks:
        normalized = _normalize_text(text)
        if not normalized:
            continue

        in_margin = y1 <= page.height * 0.12 or y0 >= page.height * 0.88
        margin_key = _canonical_margin_text(normalized)
        if in_margin and (
            margin_key in repeated_margin_keys or _PAGE_NUMBER_RE.fullmatch(normalized)
        ):
            continue
        paragraphs.append(normalized)

    text = "\n\n".join(paragraphs)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf_pages(path: Path) -> list[dict[str, object]]:
    """解析并清洗 PDF，返回带页码的页面文本；单页失败不影响其他页面。"""
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "缺少 PyMuPDF，无法解析 PDF。请安装 backend/requirements.txt 中的依赖。"
        ) from exc

    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise ValueError(f"无法打开 PDF: {path.name}") from exc

    try:
        if document.needs_pass:
            raise ValueError(f"PDF 已加密且需要密码: {path.name}")
        pages: list[PdfPage] = []
        for index, page in enumerate(document):
            try:
                pages.append(_extract_page(page, index + 1))
            except Exception as exc:
                logger.warning(
                    "[RAG·PDF] 跳过解析失败页面 file=%s page=%s error_type=%s",
                    path.name,
                    index + 1,
                    type(exc).__name__,
                )
    finally:
        document.close()

    repeated_keys = _repeated_margin_keys(pages)
    results: list[dict[str, object]] = []
    for page in pages:
        text = _clean_page(page, repeated_keys)
        if not text:
            logger.warning(
                "[RAG·PDF] 跳过无有效文本页面 file=%s page=%s",
                path.name,
                page.number,
            )
            continue
        results.append(
            {
                "text": text,
                "page_start": page.number,
                "page_end": page.number,
                "parser": "pymupdf+ocr" if page.used_ocr else "pymupdf",
            }
        )

    if not results:
        raise ValueError(
            f"PDF 未提取到有效文本: {path.name}；扫描件请安装 Tesseract 中文语言包后重试。"
        )
    return results
