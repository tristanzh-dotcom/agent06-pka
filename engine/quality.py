import re
from typing import List, Optional, Set

from engine.models import ParseQuality
from engine.text_normalizer import normalize_pdf_text


_PAGE_PATTERNS = [
    re.compile(r"^\d{1,4}$"),
    re.compile(r"^page\s*\d{1,4}$", re.IGNORECASE),
    re.compile(r"^第\s*\d{1,4}\s*页$"),
    re.compile(r"^-\s*\d{1,4}\s*-$"),
]

_WATERMARK_KEYWORDS = [
    "仅供",
    "机密",
    "confidential",
    "internal use",
    "扫描全能王",
    "camscanner",
    "adobe scan",
    "created with",
    "powered by",
    "evaluation only",
    "试用版",
    "免费版",
    "©亿欧智库",
]

FREQ_DEDUP_MIN_PAGES = 3
FREQ_DEDUP_THRESHOLD = 0.3


def clean_pdf_text(
    raw_text: str,
    page_texts: Optional[List[str]] = None,
    page_count: int = 0,
) -> str:
    repeated_lines = _page_repeated_lines(page_texts or [], page_count)
    lines = raw_text.splitlines()
    cleaned: List[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append("")
            continue
        if _is_page_line(stripped):
            continue
        if _is_watermark_line(stripped):
            continue
        if _normalize_line(stripped) in repeated_lines:
            continue
        cleaned.append(line)
    return normalize_pdf_text("\n".join(cleaned).strip())


def assess_pdf_quality(
    raw_text: str,
    cleaned_text: str,
    page_count: int,
    non_empty_pages: int,
) -> ParseQuality:
    raw = raw_text or ""
    cleaned = cleaned_text or ""
    reasons: List[str] = []
    raw_lines = [line.strip() for line in raw.splitlines() if line.strip()]
    cleaned_lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    raw_chars = len(raw.strip())
    cleaned_chars = len(cleaned.strip())
    cleaned_chars_ratio = round(cleaned_chars / raw_chars, 3) if raw_chars else 0.0
    non_empty_page_ratio = round(non_empty_pages / page_count, 3) if page_count else 0.0
    effective_chars_per_page = round(cleaned_chars / page_count, 1) if page_count else 0.0

    if not raw_chars or page_count <= 0:
        return ParseQuality(
            status="needs_ocr",
            action="needs_ocr_skipped",
            valid_ratio=0.0,
            short_line_ratio=1.0,
            watermark_ratio=0.0,
            unique_line_ratio=0.0,
            non_empty_pages=non_empty_pages,
            page_count=page_count,
            non_empty_page_ratio=non_empty_page_ratio,
            effective_chars_per_page=0.0,
            cleaned_chars_ratio=cleaned_chars_ratio,
            reasons=["文本层为空，需要 OCR"],
        )

    total_raw_lines = max(1, len(raw_lines))
    short_line_ratio = round(
        sum(1 for line in raw_lines if len(line) < 10) / total_raw_lines,
        3,
    )
    removed_lines = max(0, len(raw_lines) - len(cleaned_lines))
    watermark_ratio = round(removed_lines / total_raw_lines, 3)
    valid_ratio = round(cleaned_chars / raw_chars, 3) if raw_chars else 0.0
    unique_line_ratio = _unique_line_ratio(cleaned_lines)

    if cleaned_chars == 0:
        reasons.append("清洗后无有效正文，需要 OCR")
        status = "needs_ocr"
    elif non_empty_page_ratio < 0.15:
        reasons.append(f"非空页面占比 {non_empty_page_ratio:.1%}，低于 15%，需要 OCR")
        status = "needs_ocr"
    elif page_count >= 3 and effective_chars_per_page < 80:
        reasons.append(f"有效正文每页约 {effective_chars_per_page:.1f} 字，低于 80 字，需要 OCR")
        status = "needs_ocr"
    elif unique_line_ratio < 0.2 and watermark_ratio > 0.4:
        reasons.append(f"重复/水印文本占比 {watermark_ratio:.1%}，需要 OCR")
        status = "needs_ocr"
    elif valid_ratio < 0.1:
        reasons.append(f"有效文本占比 {valid_ratio:.1%}，低于 10%，需要 OCR")
        status = "needs_ocr"
    elif watermark_ratio > 0.5:
        reasons.append(f"水印/页码占比 {watermark_ratio:.1%}，超过 50%")
        status = "low"
    elif short_line_ratio > 0.6:
        reasons.append(f"极短行占比 {short_line_ratio:.1%}，超过 60%")
        status = "low"
    else:
        status = "high"

    action = "direct" if status == "high" and cleaned == raw.strip() else "cleaned"
    if status == "low":
        action = "low_indexed"
    if status == "needs_ocr":
        action = "needs_ocr_skipped"

    return ParseQuality(
        status=status,
        action=action,
        valid_ratio=valid_ratio,
        short_line_ratio=short_line_ratio,
        watermark_ratio=watermark_ratio,
        unique_line_ratio=unique_line_ratio,
        non_empty_pages=non_empty_pages,
        page_count=page_count,
        non_empty_page_ratio=non_empty_page_ratio,
        effective_chars_per_page=effective_chars_per_page,
        cleaned_chars_ratio=cleaned_chars_ratio,
        reasons=reasons,
    )


def _is_page_line(line: str) -> bool:
    return any(pattern.match(line) for pattern in _PAGE_PATTERNS)


def _is_watermark_line(line: str) -> bool:
    lowered = line.lower()
    return any(keyword in lowered for keyword in _WATERMARK_KEYWORDS)


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip().lower())


def _page_repeated_lines(page_texts: List[str], page_count: int) -> Set[str]:
    if page_count < FREQ_DEDUP_MIN_PAGES or not page_texts:
        return set()
    page_presence = {}
    for page_text in page_texts:
        seen_on_page = {
            _normalize_line(line)
            for line in page_text.splitlines()
            if _normalize_line(line) and not _is_page_line(line.strip())
        }
        for line in seen_on_page:
            page_presence[line] = page_presence.get(line, 0) + 1
    threshold = max(2, int(page_count * FREQ_DEDUP_THRESHOLD))
    if threshold < page_count * FREQ_DEDUP_THRESHOLD:
        threshold += 1
    return {line for line, count in page_presence.items() if count >= threshold}


def _unique_line_ratio(lines: List[str]) -> float:
    normalized = [_normalize_line(line) for line in lines if _normalize_line(line)]
    if not normalized:
        return 0.0
    denominator = min(len(normalized), 10)
    return round(len(set(normalized)) / denominator, 3)
