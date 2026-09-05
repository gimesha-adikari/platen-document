from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pymupdf as fitz
import pytest

from platen_document import (
    DocumentProcessor,
    MarkupAction,
    MarkupMode,
    MarkupRegion,
    MarkupRegionStatus,
    OCRCancellationError,
    Rect,
    RegionMarkupExecutionResult,
)
from platen_document.engine.contracts import (
    DocumentResult,
    OCRToken,
    PageContentClassification,
    PageGeometry,
    PageProcessingSource,
    PageResult,
    PageStatus,
    ResultCapability,
    SourceMetadata,
)


def _make_pdf(path: Path, *, pages: int = 1, rotation: int = 0, cropbox: bool = False) -> None:
    document = fitz.open()
    for page_index in range(pages):
        page = document.new_page(width=300, height=200)
        page.insert_text((40, 55), f"Alpha Bravo {page_index}")
        if cropbox:
            page.set_cropbox(fitz.Rect(20, 20, 280, 180))
        if rotation:
            page.set_rotation(rotation)
    document.save(path)
    document.close()


def _canonical_result(
    path: Path,
    *,
    pages: int = 1,
    source: PageProcessingSource = PageProcessingSource.NATIVE_EXTRACTION,
    text: str = "Alpha Bravo",
    token_texts: tuple[str, ...] = ("Alpha", "Bravo"),
) -> DocumentResult:
    document = fitz.open(path)
    page_results: list[PageResult] = []
    for page_index in range(pages):
        page = document[page_index]
        token_prefix = f"page-{page_index}"
        tokens = tuple(
            OCRToken(f"{token_prefix}-word-{word_index}", token_text, Rect(35 + word_index * 50, 30, 45, 16))
            for word_index, token_text in enumerate(token_texts)
        ) if text else ()
        classification = (
            PageContentClassification.TEXT_NATIVE
            if source is PageProcessingSource.NATIVE_EXTRACTION
            else PageContentClassification.IMAGE_SCAN
            if source is PageProcessingSource.OCR_RECOGNITION
            else PageContentClassification.MIXED
        )
        page_results.append(
            PageResult(
                page_index=page_index,
                page_id=f"page-{page_index}",
                geometry=PageGeometry(float(page.rect.width), float(page.rect.height), int(page.rotation) % 360),
                content_classification=classification,
                processing_source=source,
                status=PageStatus.SUCCESS,
                text=text,
                tokens=tokens,
                reading_order=tuple(token.id for token in tokens),
                capabilities=frozenset({ResultCapability.TEXT.value, ResultCapability.WORD_GEOMETRY.value, ResultCapability.READING_ORDER.value}),
                provenance_refs=("test-canonical",),
            )
        )
    document.close()
    return DocumentResult(
        schema_version="ocr_v2_document_result.v1",
        result_id="test-result",
        source=SourceMetadata("test-source", pages, path.name),
        pages=tuple(page_results),
        capabilities=frozenset({ResultCapability.TEXT.value, ResultCapability.WORD_GEOMETRY.value, ResultCapability.READING_ORDER.value}),
    )


def _with_sources(result: DocumentResult, sources: tuple[PageProcessingSource, ...]) -> DocumentResult:
    pages: list[PageResult] = []
    for page, source in zip(result.pages, sources, strict=True):
        classification = (
            PageContentClassification.TEXT_NATIVE
            if source is PageProcessingSource.NATIVE_EXTRACTION
            else PageContentClassification.IMAGE_SCAN
            if source is PageProcessingSource.OCR_RECOGNITION
            else PageContentClassification.MIXED
        )
        pages.append(replace(page, processing_source=source, content_classification=classification))
    return replace(result, pages=tuple(pages))


def _annotation_types(path: Path) -> list[str]:
    document = fitz.open(path)
    values = [annotation.type[1] for page in document for annotation in (page.annots() or ())]
    document.close()
    return values


def _annotation_colors(path: Path) -> list[tuple[float, float, float]]:
    document = fitz.open(path)
    values = [tuple(annotation.colors["stroke"]) for page in document for annotation in (page.annots() or ())]
    document.close()
    return values


def test_public_region_markup_imports_are_available() -> None:
    assert MarkupRegion(page_number=1, rect=Rect(1, 2, 3, 4)).page_number == 1
    assert RegionMarkupExecutionResult.__name__ == "RegionMarkupExecutionResult"


@pytest.mark.parametrize(
    ("action", "expected_type"),
    [
        (MarkupAction.HIGHLIGHT, "Highlight"),
        (MarkupAction.UNDERLINE, "Underline"),
        (MarkupAction.STRIKEOUT, "StrikeOut"),
    ],
)
def test_manual_regions_write_annotations_without_text_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: MarkupAction,
    expected_type: str,
) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / f"{action.value}.pdf"
    _make_pdf(source)
    processor = DocumentProcessor.__new__(DocumentProcessor)

    def unexpected_extract(*_args: object, **_kwargs: object) -> DocumentResult:
        raise AssertionError("manual region markup must not extract text")

    monkeypatch.setattr(processor, "extract_text", unexpected_extract)
    result = processor.apply_markup_regions(
        source,
        output,
        action=action,
        mode=MarkupMode.MANUAL,
        regions=(MarkupRegion(1, Rect(35, 30, 100, 18), region_id="manual", color=(0.2, 0.4, 0.6)),),
    )

    assert result.extraction_performed is False
    assert result.document_result_reused is False
    assert result.annotation_count == 1
    assert result.regions[0].status is MarkupRegionStatus.ANNOTATED
    assert result.regions[0].selection is None
    assert _annotation_types(output) == [expected_type]


def test_ocr_aware_region_reuses_supplied_result_without_second_extraction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source)
    canonical = _canonical_result(source)
    processor = DocumentProcessor.__new__(DocumentProcessor)
    monkeypatch.setattr(processor, "extract_text", lambda *_args, **_kwargs: pytest.fail("provided result must be reused"))

    result = processor.apply_markup_regions(
        source,
        output,
        action="highlight",
        regions=(MarkupRegion(1, Rect(30, 25, 110, 30), region_id="words"),),
        result=canonical,
    )

    region = result.regions[0]
    assert result.document_result_reused is True
    assert result.extraction_performed is False
    assert region.status is MarkupRegionStatus.ANNOTATED
    assert region.selected_text == "Alpha Bravo"
    assert region.word_ids == ("page-0-word-0", "page-0-word-1")
    assert len(region.annotation_rects) == 1
    assert _annotation_types(output) == ["Highlight"]


def test_region_selection_preserves_native_scanned_and_mixed_provenance(tmp_path: Path) -> None:
    source = tmp_path / "mixed.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source, pages=3)
    canonical = _with_sources(
        _canonical_result(source, pages=3),
        (
            PageProcessingSource.NATIVE_EXTRACTION,
            PageProcessingSource.OCR_RECOGNITION,
            PageProcessingSource.HYBRID,
        ),
    )
    result = DocumentProcessor.__new__(DocumentProcessor).apply_markup_regions(
        source,
        output,
        action="highlight",
        result=canonical,
        regions=tuple(MarkupRegion(page_number, Rect(30, 25, 110, 30)) for page_number in (1, 2, 3)),
    )

    assert [region.selection.source_type.value for region in result.regions if region.selection] == ["native", "ocr", "hybrid"]
    assert result.annotation_count == 3


def test_ocr_aware_region_extracts_once_with_public_controls(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source)
    canonical = _canonical_result(source)
    processor = DocumentProcessor.__new__(DocumentProcessor)
    calls: list[dict[str, object]] = []
    page_progress: list[tuple[int, int, object]] = []

    def extract_text(path: Path, **kwargs: object) -> DocumentResult:
        assert path == source
        calls.append(kwargs)
        return canonical

    processor.extract_text = extract_text  # type: ignore[method-assign]
    result = processor.apply_markup_regions(
        source,
        output,
        action="underline",
        regions=(MarkupRegion(1, Rect(30, 25, 110, 30)),),
        password="password-pass-through",
        language="eng",
        routing_policy="FAST",
        page_timeout_seconds=12.0,
        page_progress_callback=lambda done, total, page: page_progress.append((done, total, page)),
    )

    assert result.extraction_performed is True
    assert result.document_result_reused is False
    assert len(calls) == 1
    assert calls[0]["password"] == "password-pass-through"
    assert calls[0]["profile"].value == "OCR_TEXT_V2"
    assert calls[0]["routing_policy"] == "FAST"
    assert calls[0]["page_timeout_seconds"] == 12.0
    assert page_progress == []


def test_multiple_overlapping_and_multipage_regions_are_independent(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source, pages=2)
    canonical = _canonical_result(source, pages=2, source=PageProcessingSource.HYBRID)
    result = DocumentProcessor.__new__(DocumentProcessor).apply_markup_regions(
        source,
        output,
        action="strikeout",
        result=canonical,
        regions=(
            MarkupRegion(1, Rect(30, 25, 45, 30), region_id="first", color=(1, 0, 0)),
            MarkupRegion(1, Rect(30, 25, 110, 30), region_id="overlap", color=(0, 1, 0)),
            MarkupRegion(2, Rect(30, 25, 110, 30), region_id="second-page", color=(0, 0, 1)),
        ),
    )

    assert [region.status for region in result.regions] == [MarkupRegionStatus.ANNOTATED] * 3
    assert result.regions[0].word_ids == ("page-0-word-0",)
    assert result.regions[1].word_ids == ("page-0-word-0", "page-0-word-1")
    assert result.regions[2].word_ids == ("page-1-word-0", "page-1-word-1")
    assert result.annotation_count == 3
    assert _annotation_types(output) == ["StrikeOut", "StrikeOut", "StrikeOut"]
    assert _annotation_colors(output) == pytest.approx([(1, 0, 0), (0, 1, 0), (0, 0, 1)], abs=0.001)


def test_empty_out_of_bounds_and_no_word_regions_are_reported(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source)
    canonical = _canonical_result(source)
    result = DocumentProcessor.__new__(DocumentProcessor).apply_markup_regions(
        source,
        output,
        action="highlight",
        result=canonical,
        regions=(
            MarkupRegion(1, Rect(20, 20, 0, 10)),
            MarkupRegion(1, Rect(999, 999, 10, 10)),
            MarkupRegion(1, Rect(150, 25, 20, 20)),
            MarkupRegion(2, Rect(20, 20, 10, 10)),
        ),
    )

    assert [region.status for region in result.regions] == [
        MarkupRegionStatus.EMPTY,
        MarkupRegionStatus.OUT_OF_BOUNDS,
        MarkupRegionStatus.NO_WORDS,
        MarkupRegionStatus.OUT_OF_BOUNDS,
    ]
    assert result.annotation_count == 0
    assert _annotation_types(output) == []


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_manual_region_preserves_rotated_visible_page_geometry(tmp_path: Path, rotation: int) -> None:
    source = tmp_path / "rotated.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source, rotation=rotation)
    result = DocumentProcessor.__new__(DocumentProcessor).apply_markup_regions(
        source,
        output,
        action="highlight",
        mode="manual",
        regions=(MarkupRegion(1, Rect(20, 20, 50, 20)),),
    )
    document = fitz.open(output)
    assert document[0].rotation == rotation
    assert result.annotation_count == 1
    document.close()


def test_ocr_aware_region_preserves_rotated_canonical_geometry(tmp_path: Path) -> None:
    source = tmp_path / "rotated.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source, rotation=90)
    canonical = _canonical_result(source, source=PageProcessingSource.OCR_RECOGNITION)
    result = DocumentProcessor.__new__(DocumentProcessor).apply_markup_regions(
        source,
        output,
        action="strikeout",
        result=canonical,
        regions=(MarkupRegion(1, Rect(30, 25, 110, 30)),),
    )
    document = fitz.open(output)
    assert document[0].rotation == 90
    assert result.regions[0].selection.source_type.value == "ocr"
    document.close()


def test_cropbox_and_unicode_canonical_regions_use_visible_geometry(tmp_path: Path) -> None:
    source = tmp_path / "cropbox.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source, cropbox=True)
    canonical = _canonical_result(source, text="Ångström", token_texts=("Ångström",))
    result = DocumentProcessor.__new__(DocumentProcessor).apply_markup_regions(
        source,
        output,
        action="underline",
        result=canonical,
        regions=(MarkupRegion(1, Rect(30, 25, 110, 30)),),
    )
    assert result.regions[0].status is MarkupRegionStatus.ANNOTATED
    assert result.regions[0].selected_text == "Ångström"


def test_manual_password_contract_and_malformed_input(tmp_path: Path) -> None:
    plain = tmp_path / "plain.pdf"
    encrypted = tmp_path / "encrypted.pdf"
    _make_pdf(plain)
    document = fitz.open(plain)
    document.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    document.close()
    processor = DocumentProcessor.__new__(DocumentProcessor)
    region = (MarkupRegion(1, Rect(20, 20, 50, 20)),)

    with pytest.raises(ValueError, match="password authentication failed"):
        processor.apply_markup_regions(encrypted, tmp_path / "missing.pdf", action="highlight", mode="manual", regions=region)
    with pytest.raises(ValueError, match="password authentication failed"):
        processor.apply_markup_regions(encrypted, tmp_path / "wrong.pdf", action="highlight", mode="manual", regions=region, password="wrong")
    result = processor.apply_markup_regions(encrypted, tmp_path / "correct.pdf", action="highlight", mode="manual", regions=region, password="secret")
    assert result.annotation_count == 1

    malformed = tmp_path / "malformed.pdf"
    malformed.write_bytes(b"not a pdf")
    with pytest.raises(fitz.FileDataError):
        processor.apply_markup_regions(malformed, tmp_path / "bad-output.pdf", action="highlight", mode="manual", regions=region)


def test_manual_progress_is_real_annotation_progress_and_cancellation_is_cooperative(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "marked.pdf"
    _make_pdf(source)
    processor = DocumentProcessor.__new__(DocumentProcessor)
    progress: list[tuple[int, int]] = []
    processor.apply_markup_regions(
        source,
        output,
        action="highlight",
        mode="manual",
        regions=(MarkupRegion(1, Rect(20, 20, 30, 20)), MarkupRegion(1, Rect(70, 20, 30, 20))),
        progress_callback=lambda done, total: progress.append((done, total)),
    )
    assert progress == [(1, 2), (2, 2)]

    calls = 0

    def cancel() -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise OCRCancellationError("cancelled")

    with pytest.raises(OCRCancellationError, match="cancelled"):
        processor.apply_markup_regions(
            source,
            tmp_path / "cancelled.pdf",
            action="highlight",
            mode="manual",
            regions=(MarkupRegion(1, Rect(20, 20, 30, 20)),),
            cancellation_check=cancel,
        )
