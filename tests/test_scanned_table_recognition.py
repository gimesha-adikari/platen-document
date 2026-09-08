from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

from platen_document import DocumentProcessor, EngineConfiguration
from platen_document.engine.structured import StructuredElementType


_TABLE_ROWS = (
    ("001", "Alice", "10", "15", "12", "37"),
    ("002", "Bob", "8", "9", "11", "28"),
    ("003", "Charlie", "20", "18", "22", "60"),
    ("004", "Dave", "5", "5", "5", "15"),
)
_TABLE_HEADERS = ("ID", "Name", "Q1", "Q2", "Q3", "Total")
_OCR_HEADER_ALIASES = ({"ID"}, {"Name"}, {"Q1", "Ql"}, {"Q2"}, {"Q3"}, {"Total", "Tota1"})


def _centered_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font: ImageFont.FreeTypeFont) -> None:
    left, top, right, bottom = box
    text_box = draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    draw.text(
        (
            left + (right - left - text_width) / 2 - text_box[0],
            top + (bottom - top - text_height) / 2 - text_box[1],
        ),
        text,
        fill="black",
        font=font,
    )


def _scanned_table_pdf(path: Path) -> None:
    image = Image.new("RGB", (1200, 900), "white")
    draw = ImageDraw.Draw(image)
    x_edges = (80, 240, 500, 640, 780, 920, 1120)
    y_edges = (100, 220, 340, 460, 580, 700)
    for x in x_edges:
        draw.line((x, y_edges[0], x, y_edges[-1]), fill="black", width=5)
    for y in y_edges:
        draw.line((x_edges[0], y, x_edges[-1], y), fill="black", width=5)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 38)
    for row, row_values in enumerate((_TABLE_HEADERS, *_TABLE_ROWS)):
        for column, value in enumerate(row_values):
            _centered_text(draw, (x_edges[column] + 10, y_edges[row] + 10, x_edges[column + 1] - 10, y_edges[row + 1] - 10), value, font)
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    with fitz.open() as document:
        page = document.new_page(width=600, height=450)
        page.insert_image(page.rect, stream=encoded.getvalue())
        document.save(str(path))


def test_public_sdk_opt_in_recovers_scanned_table_structure(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned-table.pdf"
    _scanned_table_pdf(pdf_path)

    processor = DocumentProcessor(EngineConfiguration(
        raster_dpi=200,
        enable_scanned_table_recognition=True,
    ))
    result = processor.extract_document(pdf_path, routing_policy="FAST")

    tables = [
        element
        for page in result.pages
        for element in page.elements
        if element.type is StructuredElementType.TABLE
    ]
    assert result.validation["valid"] is True
    assert len(tables) == 1
    assert tables[0].data["column_count"] == 6
    assert tables[0].data["row_count"] == 4
    assert [cell["text"] in aliases for cell, aliases in zip(tables[0].data["headers"], _OCR_HEADER_ALIASES)] == [True] * len(_TABLE_HEADERS)
    assert [[cell["text"] for cell in row] for row in tables[0].data["rows"]] == [list(row) for row in _TABLE_ROWS]


def test_scanned_table_recognition_is_structured_opt_in() -> None:
    default = DocumentProcessor()
    enabled = DocumentProcessor(EngineConfiguration(enable_scanned_table_recognition=True))

    assert default.config.enable_scanned_table_recognition is False
    assert default._structured_processor.enable_scanned_table_recognition is False
    assert default._structured_processor.ocr_worker.table_aware_ocr is False
    assert enabled._structured_processor.enable_scanned_table_recognition is True
    assert enabled._structured_processor.ocr_worker.table_aware_ocr is True
    assert enabled._ocr_worker.table_aware_ocr is False
    assert enabled._ocr_worker.adapters["tesseract_v2"].table_aware_ocr is False
