from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pymupdf as fitz
import pytest

from platen_document import DocumentProcessor, MarkupAction, MarkupMode, MarkupRegion, Rect


PRODUCTION_REGION_270 = Rect(37.0, 250.0, 42.0, 300.0)
PRODUCTION_TITLE = "Sample Text Document - Page 1"
ROTATIONS = (0, 90, 180, 270)
ACTIONS = (
    (MarkupAction.HIGHLIGHT, "Highlight"),
    (MarkupAction.UNDERLINE, "Underline"),
    (MarkupAction.STRIKEOUT, "StrikeOut"),
)


def _make_production_shaped_pdf(path: Path, rotation: int) -> None:
    """Create the deterministic title geometry used by the production fixture."""
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((50, 62), PRODUCTION_TITLE, fontsize=20, fontname="helv")
    page.insert_text(
        (50, 122),
        "This is paragraph content on page 1 used for verifying text highlight, underline, and strikeout previews.",
        fontsize=12,
        fontname="helv",
    )
    page.set_rotation(rotation)
    document.save(path)
    document.close()


def _canonical_title_rect(page: fitz.Page) -> fitz.Rect:
    words = [word for word in page.get_text("words") if word[4] in PRODUCTION_TITLE.split()]
    assert words
    return fitz.Rect(
        min(word[0] for word in words),
        min(word[1] for word in words),
        max(word[2] for word in words),
        max(word[3] for word in words),
    )


def _visible_rect(rect: fitz.Rect, page: fitz.Page) -> Rect:
    visible = rect * page.rotation_matrix
    return Rect(visible.x0, visible.y0, visible.width, visible.height)


def _assert_qpdf_valid(path: Path) -> None:
    qpdf = shutil.which("qpdf")
    if qpdf is None:
        pytest.fail("qpdf is required for the rotated manual markup regression")
    checked = subprocess.run([qpdf, "--check", str(path)], capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr


def _colored_bbox(path: Path, color: tuple[int, int, int] = (1, 1, 0)) -> tuple[int, int, int, int]:
    with fitz.open(path) as document:
        page = document[0]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False, annots=True)
        width, height = pixmap.width, pixmap.height
        samples = pixmap.samples

    red, green, blue = (255 * value for value in color)
    points: list[tuple[int, int]] = []
    for y in range(height):
        for x in range(width):
            offset = (y * width + x) * 3
            pixel = samples[offset : offset + 3]
            if pixel[0] >= red - 35 and pixel[1] >= green - 35 and pixel[2] <= blue + 120:
                points.append((x, y))
    assert points, f"expected rendered annotation color {color} in {path}"
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def _annotation_snapshot(path: Path) -> tuple[str, tuple[tuple[float, float], ...]]:
    with fitz.open(path) as document:
        page = document[0]
        annotations = list(page.annots() or ())
        assert annotations
        annotation = annotations[0]
        return annotation.type[1], tuple(annotation.vertices)


def _assert_vertices(vertices: tuple[tuple[float, float], ...], rect: fitz.Rect) -> None:
    expected = ((rect.x0, rect.y0), (rect.x1, rect.y0), (rect.x0, rect.y1), (rect.x1, rect.y1))
    assert len(vertices) == len(expected)
    for actual_point, expected_point in zip(vertices, expected, strict=True):
        assert actual_point[0] == pytest.approx(expected_point[0])
        assert actual_point[1] == pytest.approx(expected_point[1])


def _assert_rect_close(actual: Rect, expected: fitz.Rect) -> None:
    assert actual.x == pytest.approx(expected.x0)
    assert actual.y == pytest.approx(expected.y0)
    assert actual.width == pytest.approx(expected.width)
    assert actual.height == pytest.approx(expected.height)


@pytest.mark.parametrize("action,expected_type", ACTIONS)
def test_exact_production_270_manual_region_is_written_in_canonical_space(
    tmp_path: Path,
    action: MarkupAction,
    expected_type: str,
) -> None:
    source = tmp_path / "native-270.pdf"
    output = tmp_path / f"native-270-{action.value}.pdf"
    _make_production_shaped_pdf(source, 270)

    result = DocumentProcessor().apply_markup_regions(
        source,
        output,
        action=action,
        mode=MarkupMode.MANUAL,
        regions=(MarkupRegion(1, PRODUCTION_REGION_270, region_id="production-270"),),
    )

    assert result.regions[0].selected_text == ""
    assert result.regions[0].annotation_rects == (Rect(45.0, 37.0, 300.0, 42.0),)
    annotation_type, vertices = _annotation_snapshot(output)
    assert annotation_type == expected_type
    _assert_vertices(vertices, fitz.Rect(45.0, 37.0, 345.0, 79.0))
    _assert_qpdf_valid(output)

    rendered = _colored_bbox(output)
    assert rendered[0] <= 85
    assert rendered[2] >= 31
    assert rendered[1] <= 260
    assert rendered[3] <= 565


@pytest.mark.parametrize("rotation", ROTATIONS)
@pytest.mark.parametrize("action,expected_type", ACTIONS)
def test_manual_region_rendering_matches_visible_contract_for_all_rotations(
    tmp_path: Path,
    rotation: int,
    action: MarkupAction,
    expected_type: str,
) -> None:
    source = tmp_path / f"native-{rotation}.pdf"
    output = tmp_path / f"native-{rotation}-{action.value}.pdf"
    _make_production_shaped_pdf(source, rotation)
    with fitz.open(source) as document:
        page = document[0]
        canonical = _canonical_title_rect(page)
        visible = _visible_rect(canonical, page)

    result = DocumentProcessor().apply_markup_regions(
        source,
        output,
        action=action,
        mode=MarkupMode.MANUAL,
        regions=(MarkupRegion(1, visible, region_id=f"manual-{rotation}"),),
    )

    annotation_type, vertices = _annotation_snapshot(output)
    assert annotation_type == expected_type
    resolved = result.regions[0]
    assert len(resolved.annotation_rects) == 1
    _assert_rect_close(resolved.annotation_rects[0], canonical)
    _assert_vertices(vertices, canonical)
    _assert_qpdf_valid(output)
    rendered = _colored_bbox(output)
    # PyMuPDF expands highlight caps beyond the requested rectangle; the
    # tighter annotation vertices above remain the canonical geometry oracle.
    margin = 20
    assert rendered[0] >= max(0, int(visible.x) - margin)
    assert rendered[2] <= int(visible.x1) + margin
    assert rendered[1] >= max(0, int(visible.y) - margin)
    assert rendered[3] <= int(visible.y1) + margin
