"""Neutral copies of the small native-Markdown helpers used by structured OCR."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import pymupdf as fitz

BULLET_REGEX = re.compile(r"^([\u2022\u25cf\u25cb\u25a0\u2013\u2014\-*•]|(cid:\d+))\s*")
NUMBERED_LIST_REGEX = re.compile(r"^((\d+|[a-zA-Z]|[ivxIVX]+)[\.\)]|\(\d+\))\s+")
NUMBERED_HEADING_REGEX = re.compile(r"^(\d+(\.\d+)*|SECTION\s+[A-Z0-9]+|CHAPTER\s+[A-Z0-9]+)\.?\s+[A-Z]")


def calculate_document_base_font_size(doc: fitz.Document) -> float:
    font_counter: Counter[float] = Counter()
    for page in doc:
        text_page = page.get_text("dict")
        for block in text_page.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = str(span.get("text", "")).strip()
                    if text:
                        font_counter[round(float(span.get("size", 10.0)), 1)] += len(text)
    return font_counter.most_common(1)[0][0] if font_counter else 10.0


def is_bold_font(font_flags: int, font_name: str) -> bool:
    return bool(font_flags & 2 or any(value in font_name.lower() for value in ("bold", "black", "heavy")))


def is_italic_font(font_flags: int, font_name: str) -> bool:
    return bool(font_flags & 1 or any(value in font_name.lower() for value in ("italic", "oblique")))


def classify_heading_level(
    span_size: float,
    base_size: float,
    is_bold: bool,
    text: str,
    is_isolated: bool,
) -> int | None:
    clean_text = text.strip()
    if not clean_text or clean_text.endswith((".", ",", ";")):
        return None
    if ":" in clean_text:
        prefix = clean_text.split(":", 1)[0].strip()
        if len(prefix) < 35 and len(clean_text) > len(prefix) + 2:
            return None
    ratio = span_size / base_size if base_size > 0 else 1.0
    is_uppercase = clean_text.isupper() and len(clean_text) >= 3
    is_numbered = bool(NUMBERED_HEADING_REGEX.match(clean_text))
    if ratio >= 1.70 or (ratio >= 1.45 and (is_bold or is_uppercase)):
        return 1
    if ratio >= 1.35 or (ratio >= 1.20 and (is_bold or is_uppercase)):
        return 2
    if ratio >= 1.20 or (ratio >= 1.12 and is_bold and is_uppercase):
        return 3
    if is_uppercase and is_bold and is_isolated and len(clean_text) < 40:
        return 2
    if is_numbered and len(clean_text) < 80:
        return 3
    return None
