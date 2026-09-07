from __future__ import annotations

import io
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

from platen_document import DocumentProcessor
from platen_document.engine.contracts import (
    OCRLine,
    OCRToken,
    PageContentClassification,
    PageGeometry,
    PageProcessingSource,
    PageResult,
    PageStatus,
    Rect,
)
from platen_document.engine.structured import (
    StructuredElementType,
    _ocr_structured_elements,
    render_structured_markdown,
)


def _scanned_pdf(path: Path) -> None:
    image = Image.new("RGB", (1000, 420), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48)
    draw.text((45, 100), "Scanned paragraph 123", fill="black", font=font)
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    with fitz.open() as document:
        page = document.new_page(width=720, height=302)
        page.insert_image(page.rect, stream=encoded.getvalue())
        document.save(str(path))


def _native_table_pdf(path: Path) -> None:
    with fitz.open() as document:
        page = document.new_page(width=600, height=400)
        x_edges = (50, 130, 340, 430, 550)
        y_edges = (60, 100, 140, 180, 220)
        shape = page.new_shape()
        for x in x_edges:
            shape.draw_line((x, y_edges[0]), (x, y_edges[-1]))
        for y in y_edges:
            shape.draw_line((x_edges[0], y), (x_edges[-1], y))
        shape.finish(color=(0, 0, 0), width=0.8)
        shape.commit()
        cells = (
            ("No.", "Module", "Credits", "Status"),
            ("01", "Alpha", "21", "Followed"),
            ("02", "Beta", "16", "Followed"),
            ("03", "Gamma", "12", "Followed"),
        )
        for row, values in enumerate(cells):
            for column, value in enumerate(values):
                page.insert_text((x_edges[column] + 5, y_edges[row] + 25), value, fontsize=10)
        document.save(str(path))


def _synthetic_page(lines: list[tuple[str, float, list[tuple[str, float]]]]) -> PageResult:
    ocr_lines = []
    tokens = []
    for index, (text, y, token_values) in enumerate(lines):
        token_ids = []
        for token_index, (token_text, x) in enumerate(token_values):
            token_id = f"t-{index}-{token_index}"
            token_ids.append(token_id)
            tokens.append(OCRToken(token_id, token_text, Rect(x, y, max(5.0, len(token_text) * 4.0), 8.0)))
        ocr_lines.append(OCRLine(f"line-{index}", text, Rect(40.0, y, 420.0, 8.0), tuple(token_ids)))
    return PageResult(
        page_index=0,
        page_id="page-0",
        geometry=PageGeometry(500.0, 500.0),
        content_classification=PageContentClassification.IMAGE_SCAN,
        processing_source=PageProcessingSource.OCR_RECOGNITION,
        status=PageStatus.SUCCESS,
        text="\n".join(item[0] for item in lines),
        tokens=tuple(tokens),
        lines=tuple(ocr_lines),
    )


def test_native_document_uses_canonical_structured_schema() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "normal_text.pdf"
    result = DocumentProcessor().extract_document(fixture_path)
    assert result.schema_version == "ocr_v2_structured_document.v1"
    assert result.validation["valid"] is True
    assert all(page.processing_source == "NATIVE_EXTRACTION" for page in result.pages)
    assert any(element.type is StructuredElementType.HEADING for page in result.pages for element in page.elements)
    assert any(line.startswith("## ") for line in render_structured_markdown(result).splitlines())


def test_native_table_preserves_structured_table_contract(tmp_path: Path) -> None:
    pdf_path = tmp_path / "native-table.pdf"
    _native_table_pdf(pdf_path)

    result = DocumentProcessor().extract_document(pdf_path, language="eng", language_mode="EXPLICIT", languages=("eng",), routing_policy="FAST")

    table_elements = [
        element
        for page in result.pages
        for element in page.elements
        if element.type is StructuredElementType.TABLE
    ]
    assert len(table_elements) == 1
    assert result.validation["valid"] is True
    assert "| No. | Module | Credits | Status |" in render_structured_markdown(result)


def test_scanned_document_uses_real_tesseract_and_markdown(tmp_path: Path) -> None:
    # This is a small local test fixture, not benchmark ground truth.
    pdf_path = tmp_path / "scanned.pdf"
    _scanned_pdf(pdf_path)
    result = DocumentProcessor().extract_document(pdf_path, language="eng")
    assert result.schema_version == "ocr_v2_structured_document.v1"
    assert result.validation["valid"] is True
    assert result.pages[0].classification == "IMAGE_SCAN"
    assert result.pages[0].processing_source == "OCR_RECOGNITION"
    assert any(element.type is StructuredElementType.PARAGRAPH for element in result.pages[0].elements)
    assert "Scanned" in render_structured_markdown(result)


def test_scanned_geometry_recovers_headings_and_grouped_paragraphs() -> None:
    page = _synthetic_page([
        ("FACULTY OF ENGINEERING TECHNOLOGY", 40.0, [("FACULTY", 170.0), ("OF", 220.0), ("ENGINEERING", 240.0), ("TECHNOLOGY", 300.0)]),
        ("This is the first body line", 75.0, [("This", 40.0), ("is", 70.0), ("the", 85.0), ("first", 105.0), ("body", 135.0), ("line", 165.0)]),
        ("This is the second body line", 84.0, [("This", 40.0), ("is", 70.0), ("the", 85.0), ("second", 105.0), ("body", 140.0), ("line", 170.0)]),
        ("Confirmation of Academic Details", 115.0, [("Confirmation", 175.0), ("of", 230.0), ("Academic", 245.0), ("Details", 290.0)]),
    ])
    elements = _ocr_structured_elements(page)
    assert [element.type for element in elements].count(StructuredElementType.HEADING) == 2
    assert any(element.type is StructuredElementType.PARAGRAPH and "first body line" in element.text and "second body line" in element.text for element in elements)


def test_scanned_geometry_recovers_only_repeated_aligned_simple_table() -> None:
    rows = [
        ("01 Module Alpha 21 Followed", 60.0),
        ("02 Module Beta 16 Followed", 72.0),
        ("03 Module Gamma 14 Followed", 84.0),
        ("04 Module Delta 10 Followed", 96.0),
    ]
    lines = [("NO MODULE CREDITS STATUS", 48.0, [("NO", 40.0), ("MODULE", 120.0), ("CREDITS", 300.0), ("STATUS", 360.0)])]
    for text, y in rows:
        parts = text.split()
        lines.append((text, y, [(parts[0], 40.0), (f"{parts[1]} {parts[2]}", 120.0), (parts[3], 300.0), (parts[4], 360.0)]))
    elements = _ocr_structured_elements(_synthetic_page(lines))
    table = next(element for element in elements if element.type is StructuredElementType.TABLE)
    assert table.data["row_count"] == 4
    assert "| NO | MODULE | CREDITS | STATUS |" in render_structured_markdown(type("Result", (), {"pages": [type("Page", (), {"elements": tuple(elements), "reading_order": tuple(element.element_id for element in elements)})()]})())


def test_scanned_geometry_does_not_fabricate_ambiguous_table_or_numbered_prose() -> None:
    page = _synthetic_page([
        ("01 One 21", 60.0, [("01", 40.0), ("One", 120.0), ("21", 300.0)]),
        ("02 Two 16", 72.0, [("02", 40.0), ("Two", 120.0), ("16", 300.0)]),
        ("03 Three 14", 84.0, [("03", 40.0), ("Three", 120.0), ("14", 300.0)]),
    ])
    assert not any(element.type is StructuredElementType.TABLE for element in _ocr_structured_elements(page))

    prose = _synthetic_page([("The result is 1.5 percent.", 60.0, [("The", 40.0), ("result", 65.0), ("is", 105.0), ("1.5", 120.0), ("percent.", 145.0)])])
    assert not any(element.type is StructuredElementType.LIST for element in _ocr_structured_elements(prose))
