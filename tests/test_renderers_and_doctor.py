from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw

from platen_document import DocumentProcessor
from platen_document.engine.image_pages import build_image_source_pdf
from platen_document.engine.renderers import SearchablePdfRenderer
from platen_document.engine.validation import OCRProfile


def _searchable_fixture(tmp_path: Path) -> tuple[Path, Path]:
    image_path = tmp_path / "fixture.png"
    image = Image.new("RGB", (800, 500), "white")
    ImageDraw.Draw(image).text((80, 180), "Forensics 123", fill="black")
    image.save(image_path)
    source = tmp_path / "source.pdf"
    build_image_source_pdf([image_path], source)
    return image_path, source


def test_doctor_reports_safe_local_capabilities() -> None:
    report = DocumentProcessor().capabilities()
    assert report["package"]["name"] == "platen-document"
    assert report["tesseract"]["available"] is True
    assert set(report["tesseract"]["installed_languages"]) >= {"eng", "sin", "tam"}
    assert report["capabilities"]["searchable_pdf"] is True


def test_standalone_searchable_pdf_uses_canonical_word_geometry(tmp_path: Path) -> None:
    _, source = _searchable_fixture(tmp_path)
    output = tmp_path / "rendered.pdf"
    result = DocumentProcessor().extract_text(source, language="eng", profile=OCRProfile.SEARCHABLE_PDF_V2)
    assert result.validation.valid
    SearchablePdfRenderer().render(source, result, output)
    with fitz.open(output) as document:
        assert document[0].get_text("words")
        assert "Forensics" in document[0].get_text("text")
        assert len(document[0].get_images(full=True)) == 1
