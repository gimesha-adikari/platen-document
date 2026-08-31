"""Neutral native-table adapter used by the copied structured processor."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class TableCell:
    text: str = ""
    colspan: int = 1
    rowspan: int = 1


@dataclass
class TableNode:
    x0: float
    y0: float
    x1: float
    y1: float
    headers: list[TableCell]
    rows: list[list[TableCell]]


SECTION_KEYWORDS = {
    "SUMMARY", "EDUCATION", "SKILLS", "PROJECTS", "EXPERIENCE",
    "WORK EXPERIENCE", "LEADERSHIP", "LANGUAGES",
}


def extract_table_nodes_from_pdfplumber(pdfplumber_page: Any, page_num: int) -> list[TableNode]:
    """Preserve the frozen pdfplumber table acceptance rules without IR types."""
    try:
        tables = pdfplumber_page.find_tables()
    except Exception as exc:
        logger.warning("pdfplumber find_tables failed on page %s: %s", page_num, exc)
        return []
    if not tables:
        return []
    page_width = float(pdfplumber_page.width)
    page_height = float(pdfplumber_page.height)
    valid: list[TableNode] = []
    for table in tables:
        x0, y0, x1, y1 = table.bbox
        width, height = x1 - x0, y1 - y0
        if x0 < -5.0 or y0 < -5.0 or x1 > page_width + 10.0 or y1 > page_height + 10.0:
            continue
        if width > 0.65 * page_width and height > 0.65 * page_height:
            continue
        extracted = table.extract()
        if not extracted or len(extracted) < 2:
            continue
        cell_texts = [str(cell).strip() for row in extracted for cell in row if cell]
        if any(len(value) > 150 or value.count("\n") >= 3 for value in cell_texts):
            continue
        if any(keyword in value for value in cell_texts for keyword in SECTION_KEYWORDS):
            continue
        headers = [TableCell(str(cell or "").strip()) for cell in extracted[0]]
        rows = [[TableCell(str(cell or "").strip()) for cell in row] for row in extracted[1:]]
        if len(headers) < 2:
            continue
        valid.append(TableNode(max(0.0, x0), max(0.0, y0), min(page_width, x1), min(page_height, y1), headers, rows))
    return valid
