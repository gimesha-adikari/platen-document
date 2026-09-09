from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pymupdf as fitz
import pytest

from platen_document import DocumentProcessor, MarkupAction, MarkupMode, MarkupRegion, MarkupRegionStatus, Rect
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


TEXT = "Alpha Bravo"
ROTATIONS = (0, 90, 180, 270)
ACTIONS = (
    (MarkupAction.HIGHLIGHT, "Highlight"),
    (MarkupAction.UNDERLINE, "Underline"),
    (MarkupAction.STRIKEOUT, "StrikeOut"),
)


def _make_native_pdf(path: Path, rotations: tuple[int, ...] = (0,)) -> None:
    document = fitz.open()
    for page_index, rotation in enumerate(rotations):
        page = document.new_page(width=400, height=300)
        page.insert_text((55, 90), f"{TEXT} {page_index}" if len(rotations) > 1 else TEXT, fontsize=20, fontname="helv")
        page.set_rotation(rotation)
    document.save(path)
    document.close()


def _visible_text_region(page: fitz.Page, *, text: str = TEXT) -> Rect:
    words = [word for word in page.get_text("words") if word[4] in text.split()]
    assert words
    canonical = fitz.Rect(
        min(word[0] for word in words),
        min(word[1] for word in words),
        max(word[2] for word in words),
        max(word[3] for word in words),
    )
    visible = canonical * page.rotation_matrix
    return Rect(visible.x0, visible.y0, visible.width, visible.height)


def _canonical_text_rect(page: fitz.Page, *, text: str = TEXT) -> fitz.Rect:
    words = [word for word in page.get_text("words") if word[4] in text.split()]
    return fitz.Rect(
        min(word[0] for word in words),
        min(word[1] for word in words),
        max(word[2] for word in words),
        max(word[3] for word in words),
    )


def _visible_ocr_result(path: Path) -> DocumentResult:
    with fitz.open(path) as document:
        pages: list[PageResult] = []
        for page_index, page in enumerate(document):
            words = [word for word in page.get_text("words") if word[4] in TEXT.split()]
            tokens = tuple(
                OCRToken(
                    id=f"ocr-{page_index}-{word_index}",
                    text=word[4],
                    bbox=(
                        lambda visible: Rect(visible.x0, visible.y0, visible.width, visible.height)
                    )(fitz.Rect(word[:4]) * page.rotation_matrix),
                )
                for word_index, word in enumerate(words)
            )
            pages.append(
                PageResult(
                    page_index=page_index,
                    page_id=f"page-{page_index}",
                    geometry=PageGeometry(float(page.rect.width), float(page.rect.height), int(page.rotation) % 360),
                    content_classification=PageContentClassification.IMAGE_SCAN,
                    processing_source=PageProcessingSource.OCR_RECOGNITION,
                    status=PageStatus.SUCCESS,
                    text=TEXT,
                    tokens=tokens,
                    reading_order=tuple(token.id for token in tokens),
                    capabilities=frozenset({ResultCapability.TEXT.value, ResultCapability.WORD_GEOMETRY.value, ResultCapability.READING_ORDER.value}),
                )
            )
    return DocumentResult(
        schema_version="ocr_v2_document_result.v1",
        result_id="visible-ocr-result",
        source=SourceMetadata("visible-ocr-source", len(pages), path.name),
        pages=tuple(pages),
        capabilities=frozenset({ResultCapability.TEXT.value, ResultCapability.WORD_GEOMETRY.value, ResultCapability.READING_ORDER.value}),
    )


def _assert_qpdf_valid(path: Path) -> None:
    qpdf = shutil.which("qpdf")
    if qpdf is None:
        pytest.fail("qpdf is required for the PDF validity regression tests")
    checked = subprocess.run([qpdf, "--check", str(path)], capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.mark.parametrize("rotation", ROTATIONS)
@pytest.mark.parametrize("action,expected_type", ACTIONS)
@pytest.mark.parametrize("mode", (MarkupMode.SMART, MarkupMode.NATIVE))
def test_native_rotated_visible_regions_select_and_annotate_exact_words(
    tmp_path: Path,
    rotation: int,
    action: MarkupAction,
    expected_type: str,
    mode: MarkupMode,
) -> None:
    source = tmp_path / f"native-{rotation}.pdf"
    output = tmp_path / f"native-{rotation}-{action.value}-{mode.value}.pdf"
    _make_native_pdf(source, (rotation,))
    with fitz.open(source) as document:
        page = document[0]
        visible_region = _visible_text_region(page)
        canonical_text = _canonical_text_rect(page)

    result = DocumentProcessor().apply_markup_regions(
        source,
        output,
        action=action,
        mode=mode,
        regions=(MarkupRegion(1, visible_region, region_id=f"native-{rotation}"),),
    )

    resolved = result.regions[0]
    assert resolved.status is MarkupRegionStatus.ANNOTATED
    assert resolved.selected_text == TEXT
    assert len(resolved.word_ids) == 2
    assert result.annotation_count == 1
    assert len(resolved.annotation_rects) == 1
    annotation_rect = resolved.annotation_rects[0]
    assert annotation_rect.x == pytest.approx(canonical_text.x0)
    assert annotation_rect.y == pytest.approx(canonical_text.y0)
    assert annotation_rect.width == pytest.approx(canonical_text.width)
    assert annotation_rect.height == pytest.approx(canonical_text.height)
    _assert_qpdf_valid(output)
    with fitz.open(output) as document:
        annotation_types = [annotation.type[1] for page in document for annotation in (page.annots() or ())]
        assert annotation_types == [expected_type]


def test_native_rotated_region_selection_handles_cropbox_and_preserves_visible_contract(tmp_path: Path) -> None:
    for rotation in ROTATIONS:
        source = tmp_path / f"cropbox-{rotation}.pdf"
        output = tmp_path / f"cropbox-{rotation}-marked.pdf"
        document = fitz.open()
        page = document.new_page(width=400, height=300)
        page.set_cropbox(fitz.Rect(20, 20, 320, 200))
        page.insert_text((55, 90), TEXT, fontsize=20, fontname="helv")
        page.set_rotation(rotation)
        visible_region = _visible_text_region(page)
        document.save(source)
        document.close()

        result = DocumentProcessor().apply_markup_regions(
            source,
            output,
            action=MarkupAction.HIGHLIGHT,
            mode=MarkupMode.SMART,
            regions=(MarkupRegion(1, visible_region, region_id=f"cropbox-{rotation}"),),
        )

        assert result.regions[0].status is MarkupRegionStatus.ANNOTATED
        assert result.regions[0].selected_text == TEXT
        _assert_qpdf_valid(output)


def test_native_multipage_rotations_keep_region_identity_and_colors(tmp_path: Path) -> None:
    source = tmp_path / "multipage-native.pdf"
    output = tmp_path / "multipage-native-marked.pdf"
    rotations = (0, 90, 180, 270)
    _make_native_pdf(source, rotations)
    regions: list[MarkupRegion] = []
    colors = ((1.0, 1.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.5, 1.0))
    with fitz.open(source) as document:
        for page_number, color in enumerate(colors, start=1):
            regions.append(
                MarkupRegion(
                    page_number,
                    _visible_text_region(document[page_number - 1], text=f"{TEXT}"),
                    region_id=f"region-{page_number}",
                    color=color,
                )
            )

    result = DocumentProcessor().apply_markup_regions(
        source,
        output,
        action=MarkupAction.UNDERLINE,
        mode=MarkupMode.SMART,
        regions=tuple(regions),
    )

    assert [region.region_id for region in result.regions] == [f"region-{i}" for i in range(1, 5)]
    assert [region.selected_text for region in result.regions] == [TEXT] * 4
    assert [region.color for region in result.regions] == list(colors)
    assert result.annotation_count == 4
    _assert_qpdf_valid(output)
    with fitz.open(output) as document:
        annotation_colors = [
            tuple(annotation.colors["stroke"])
            for page in document
            for annotation in (page.annots() or ())
        ]
        assert annotation_colors == list(colors)


def test_native_overlapping_regions_preserve_exact_pairing_and_colors(tmp_path: Path) -> None:
    source = tmp_path / "overlap-native.pdf"
    output = tmp_path / "overlap-native-marked.pdf"
    _make_native_pdf(source, (90,))
    with fitz.open(source) as document:
        page = document[0]
        words = page.get_text("words")
        alpha = fitz.Rect(words[0][:4]) * page.rotation_matrix
        full = _visible_text_region(page)

    result = DocumentProcessor().apply_markup_regions(
        source,
        output,
        action=MarkupAction.STRIKEOUT,
        mode=MarkupMode.SMART,
        regions=(
            MarkupRegion(1, Rect(alpha.x0, alpha.y0, alpha.width, alpha.height), region_id="alpha", color=(1.0, 0.0, 0.0)),
            MarkupRegion(1, full, region_id="all", color=(0.0, 1.0, 0.0)),
        ),
    )

    assert [(region.region_id, region.selected_text, region.color) for region in result.regions] == [
        ("alpha", "Alpha", (1.0, 0.0, 0.0)),
        ("all", TEXT, (0.0, 1.0, 0.0)),
    ]
    assert result.annotation_count == 2
    _assert_qpdf_valid(output)


@pytest.mark.parametrize("rotation", ROTATIONS)
@pytest.mark.parametrize("mode", (MarkupMode.SMART, MarkupMode.OCR))
@pytest.mark.parametrize("action,expected_type", ACTIONS)
def test_ocr_visible_geometry_maps_annotation_back_to_native_space(
    rotation: int,
    mode: MarkupMode,
    action: MarkupAction,
    expected_type: str,
    tmp_path: Path,
) -> None:
    source = tmp_path / f"ocr-{rotation}.pdf"
    output = tmp_path / f"ocr-{rotation}-{mode.value}-{action.value}.pdf"
    _make_native_pdf(source, (rotation,))
    visible_result = _visible_ocr_result(source)
    with fitz.open(source) as document:
        page = document[0]
        region = MarkupRegion(1, _visible_text_region(page))
        canonical_text = _canonical_text_rect(page)

    result = DocumentProcessor().apply_markup_regions(
        source,
        output,
        action=action,
        mode=mode,
        result=visible_result,
        regions=(region,),
    )

    assert result.document_result_reused is True
    assert result.regions[0].status is MarkupRegionStatus.ANNOTATED
    assert result.regions[0].selected_text == TEXT
    resolved = result.regions[0]
    assert resolved.annotation_rects
    annotation_union = fitz.Rect(
        min(rect.x for rect in resolved.annotation_rects),
        min(rect.y for rect in resolved.annotation_rects),
        max(rect.x1 for rect in resolved.annotation_rects),
        max(rect.y1 for rect in resolved.annotation_rects),
    )
    assert annotation_union.x0 == pytest.approx(canonical_text.x0, abs=0.01)
    assert annotation_union.y0 == pytest.approx(canonical_text.y0, abs=0.01)
    assert annotation_union.x1 == pytest.approx(canonical_text.x1, abs=0.01)
    assert annotation_union.y1 == pytest.approx(canonical_text.y1, abs=0.01)
    _assert_qpdf_valid(output)
    with fitz.open(output) as document:
        annotation_types = [annotation.type[1] for page in document for annotation in (page.annots() or ())]
        assert annotation_types == [expected_type]
