from __future__ import annotations

from platen_document.engine.contracts import (
    PageContentClassification,
    PageGeometry,
    PageProcessingSource,
    PageStatus,
    Rect,
)
from platen_document.engine.geometry import pixel_rect_to_points


def test_canonical_contract_names_and_geometry() -> None:
    geometry = PageGeometry(300.0, 200.0, pixel_width=600, pixel_height=400)
    assert pixel_rect_to_points((100, 80, 300, 180), geometry) == Rect(50.0, 40.0, 100.0, 50.0)
    assert PageContentClassification.IMAGE_SCAN.value == "IMAGE_SCAN"
    assert PageProcessingSource.OCR_RECOGNITION.value == "OCR_RECOGNITION"
    assert PageStatus.SUCCESS.value == "SUCCESS"
