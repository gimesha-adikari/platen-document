from __future__ import annotations

import csv
import hashlib
import io
import os
import struct
import subprocess
from pathlib import Path

import pymupdf as fitz
import pytest

from platen_document import EngineConfiguration, RasterDpiMetadataPolicy
from platen_document.engine.geometry import RasterPreparer


def _png_phys(data: bytes) -> tuple[int, int, int] | None:
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        if chunk_type == b"pHYs" and len(chunk) == 9:
            return struct.unpack(">IIB", chunk)
        offset += 12 + length
    return None


def _fixture_page(path: Path) -> tuple[fitz.Document, fitz.Page]:
    document = fitz.open(path)
    for page in document:
        if not page.get_text("words"):
            return document, page
    document.close()
    raise AssertionError(f"fixture has no scanned page: {path}")


def _tesseract_tokens(path: Path) -> list[str]:
    completed = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "eng", "tsv"],
        check=True,
        capture_output=True,
        text=True,
    )
    rows = csv.DictReader(io.StringIO(completed.stdout), delimiter="\t")
    return [str(row.get("text", "")).strip() for row in rows if str(row.get("text", "")).strip()]


def _token_digest(tokens: list[str]) -> str:
    return hashlib.sha256("\n".join(tokens).encode("utf-8")).hexdigest()


def test_default_raster_metadata_policy_is_current_embedded_dpi() -> None:
    config = EngineConfiguration()

    assert config.raster_dpi_metadata_policy is RasterDpiMetadataPolicy.EMBED_DPI


def test_raster_metadata_policy_validation_is_deterministic() -> None:
    assert (
        EngineConfiguration(raster_dpi_metadata_policy="omit_dpi").raster_dpi_metadata_policy
        is RasterDpiMetadataPolicy.OMIT_DPI
    )

    with pytest.raises(ValueError, match="unsupported raster DPI metadata policy"):
        EngineConfiguration(raster_dpi_metadata_policy="unknown")


def test_omit_dpi_preserves_raster_pixels_and_geometry(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    with fitz.open() as document:
        page = document.new_page(width=300, height=200)
        page.insert_text((24, 80), "Raster compatibility control", fontsize=18)
        document.save(source)

    with fitz.open(source) as document:
        page = document[0]
        embedded = RasterPreparer(144).prepare(page)
        omitted = RasterPreparer(144, dpi_metadata_policy=RasterDpiMetadataPolicy.OMIT_DPI).prepare(page)

    assert embedded.image.mode == omitted.image.mode == "RGB"
    assert embedded.image.size == omitted.image.size
    assert embedded.image.tobytes() == omitted.image.tobytes()
    assert embedded.geometry == omitted.geometry
    assert embedded.dpi == omitted.dpi == 144
    assert _png_phys(embedded.png_bytes) is not None
    assert _png_phys(omitted.png_bytes) is None
    assert embedded.png_bytes != omitted.png_bytes


@pytest.mark.skipif(
    not os.getenv("PLATEN_DOCUMENT_LEGACY_PARITY_FIXTURE"),
    reason="set PLATEN_DOCUMENT_LEGACY_PARITY_FIXTURE to run the approved OCR input control",
)
def test_omit_dpi_reproduces_no_dpi_tesseract_input_control(tmp_path: Path) -> None:
    fixture = Path(os.environ["PLATEN_DOCUMENT_LEGACY_PARITY_FIXTURE"])
    document, page = _fixture_page(fixture)
    try:
        embedded = RasterPreparer(144).prepare(page)
        omitted = RasterPreparer(144, dpi_metadata_policy=RasterDpiMetadataPolicy.OMIT_DPI).prepare(page)
    finally:
        document.close()

    embedded_path = tmp_path / "embedded.png"
    omitted_path = tmp_path / "omitted.png"
    embedded_path.write_bytes(embedded.png_bytes)
    omitted_path.write_bytes(omitted.png_bytes)

    embedded_tokens = _tesseract_tokens(embedded_path)
    omitted_tokens = _tesseract_tokens(omitted_path)

    assert embedded.image.tobytes() == omitted.image.tobytes()
    assert embedded_tokens != omitted_tokens
    assert _token_digest(embedded_tokens) != _token_digest(omitted_tokens)
