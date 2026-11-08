"""Regression tests for the isolated Phase 1 word-editing prototype."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import random

import pymupdf as fitz
import pytest
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

from prototype import detect_protected_overlap, edit_pdf, repair_ink_mask


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
RASTER_SCALE = 2
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"


def _scan_image(*, background: str = "white", stamp: bool = False, rule: bool = False, skew: bool = False, include_text: bool = True) -> Image.Image:
    width, height = PAGE_WIDTH * RASTER_SCALE, PAGE_HEIGHT * RASTER_SCALE
    if background == "textured":
        rng = random.Random(27)
        pixels = bytearray()
        for y in range(height):
            base = 244 + round(2 * __import__("math").sin(y / 90))
            for _ in range(width):
                value = max(0, min(255, base + rng.randrange(-5, 6)))
                pixels.extend((value, max(0, value - 2), max(0, value - 8)))
        image = Image.frombytes("RGB", (width, height), bytes(pixels))
    else:
        image = Image.new("RGB", (width, height), (255, 255, 255))

    font = ImageFont.truetype(FONT_PATH, 34)
    draw = ImageDraw.Draw(image)
    if include_text:
        draw.text((120, 146), "Ministry of Education, Higher", font=font, fill=(18, 18, 18))
        draw.text((120, 230), "Neighbor text stays at its source position", font=font, fill=(18, 18, 18))
    if stamp:
        draw.ellipse((100, 132, 330, 208), outline=(185, 25, 32), width=3)
        draw.line((122, 154, 250, 154), fill=(185, 25, 32), width=1)
    if rule:
        draw.line((90, 154, 400, 154), fill=(18, 18, 18), width=2)
    if skew:
        image = image.rotate(2.5, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255))
    return image


def _write_fixture(
    path: Path,
    *,
    background: str = "white",
    stamp: bool = False,
    rule: bool = False,
    skew: bool = False,
    jpeg: bool = False,
    hidden_text: bool = False,
    rotation: int = 0,
    cropped: bool = False,
) -> Path:
    image = _scan_image(background=background, stamp=stamp, rule=rule, skew=skew)
    encoded = BytesIO()
    image.save(encoded, format="JPEG" if jpeg else "PNG", quality=68 if jpeg else None)
    document = fitz.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_image(page.rect, stream=encoded.getvalue())
    if rotation:
        page.set_rotation(rotation)
    if cropped:
        page.set_cropbox(fitz.Rect(0, 0, PAGE_WIDTH - 20, PAGE_HEIGHT))
    document.save(path)
    document.close()
    if hidden_text:
        from platen_document import DocumentProcessor, OCRProfile

        recognized = DocumentProcessor().extract_text(
            path,
            languages=["eng"],
            profile=OCRProfile.OCR_TEXT_V2,
            routing_policy="FAST",
            page_indices=[0],
        ).pages[0]
        document = fitz.open(path)
        page = document[0]
        for token in recognized.tokens:
            bounds = token.bbox
            font_size = max(4, bounds.height * 0.70)
            page.insert_text(
                fitz.Point(bounds.x, bounds.y + bounds.height * 0.78),
                token.text,
                fontname="helv",
                fontsize=font_size,
                render_mode=3,
            )
        temporary = path.with_suffix(".hidden.pdf")
        document.save(temporary)
        document.close()
        temporary.replace(path)
    return path


def test_red_stamp_crossing_target_is_classified_as_protected_content():
    image = Image.new("RGB", (180, 56), "white")
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), "Ministry", fill="black")
    draw.line((18, 50, 140, 5), fill=(190, 24, 28), width=4)

    assert detect_protected_overlap(image, (8, 4, 150, 52)) == "COLORED_OVERLAP"


def test_crossing_table_rule_is_classified_as_protected_content():
    image = Image.new("RGB", (180, 56), "white")
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), "Ministry", fill="black")
    draw.line((4, 35, 170, 35), fill=(20, 20, 20), width=2)

    assert detect_protected_overlap(image, (8, 4, 150, 52)) == "LINEAR_STRUCTURE_OVERLAP"


def test_ink_repair_preserves_pixels_outside_the_detected_ink_mask():
    image = Image.new("RGB", (180, 56), "white")
    draw = ImageDraw.Draw(image)
    draw.text((12, 12), "Ministry", fill=(12, 12, 12))
    repaired, ink_mask = repair_ink_mask(image, (8, 4, 150, 52))

    assert repaired.size == image.size
    assert ink_mask.getbbox() is not None
    for y in range(image.height):
        for x in range(image.width):
            if ink_mask.getpixel((x, y)) == 0:
                assert repaired.getpixel((x, y)) == image.getpixel((x, y))


@pytest.mark.parametrize("background", ["white", "textured"])
def test_clean_and_textured_scans_change_only_the_selected_word(tmp_path: Path, background: str):
    source = _write_fixture(tmp_path / f"{background}.pdf", background=background)
    output = tmp_path / f"{background}-edited.pdf"

    result = edit_pdf(source, output, page_index=0, target_text="Ministry", replacement="hello")

    assert result["status"] == "EDITED", result
    assert result["replacement_hits_in_target"] == 1
    assert result["old_target_hits_in_target"] == 0
    assert result["replacement_ocr_hits_in_target"] == 1
    assert result["unexpected_ocr_target_tokens"] == 0
    assert result["neighbor_tokens_preserved"] is True
    assert result["outside_changed_pixels_144dpi"] == 0


@pytest.mark.parametrize("kind", ["stamp", "rule"])
def test_stamp_and_table_rule_overlap_refuse_without_writing_candidate(tmp_path: Path, kind: str):
    source = _write_fixture(tmp_path / f"{kind}.pdf", stamp=kind == "stamp", rule=kind == "rule")
    output = tmp_path / f"{kind}-edited.pdf"

    result = edit_pdf(source, output, page_index=0, target_text="Ministry", replacement="hello")

    assert result["status"] == "REFUSED", result
    assert result["reason"] in {"COLORED_OVERLAP", "LINEAR_STRUCTURE_OVERLAP"}
    assert not output.exists()


def test_aligned_hidden_ocr_target_is_removed_and_neighbors_are_retained(tmp_path: Path):
    source = _write_fixture(tmp_path / "hidden-layer.pdf", hidden_text=True)
    output = tmp_path / "hidden-layer-edited.pdf"

    result = edit_pdf(source, output, page_index=0, target_text="Ministry", replacement="hello")

    assert result["status"] == "EDITED", result
    assert result["hidden_target_removed"] is True
    assert result["replacement_hits_in_target"] == 1
    assert result["replacement_ocr_hits_in_target"] == 1
    assert result["unexpected_ocr_target_tokens"] == 0
    assert result["neighbor_text_layer_preserved"] is True


@pytest.mark.parametrize("geometry", ["rotation", "cropbox"])
def test_unsupported_page_geometry_refuses_before_writing_candidate(tmp_path: Path, geometry: str):
    source = _write_fixture(
        tmp_path / f"{geometry}.pdf",
        rotation=90 if geometry == "rotation" else 0,
        cropped=geometry == "cropbox",
    )
    output = tmp_path / f"{geometry}-edited.pdf"

    result = edit_pdf(source, output, page_index=0, target_text="Ministry", replacement="hello")

    assert result["status"] == "REFUSED", result
    assert result["reason"] == "UNSUPPORTED_PAGE_GEOMETRY"
    assert not output.exists()


def test_lossy_and_mildly_skewed_scan_is_checked_end_to_end(tmp_path: Path):
    source = _write_fixture(tmp_path / "lossy-skewed.pdf", jpeg=True, skew=True)
    output = tmp_path / "lossy-skewed-edited.pdf"

    result = edit_pdf(source, output, page_index=0, target_text="Ministry", replacement="hello")

    assert result["status"] == "EDITED", result
    assert result["outside_changed_pixels_144dpi"] == 0
    assert result["neighbor_tokens_preserved"] is True


def test_textured_repair_improves_mae_against_a_synthetic_no_text_oracle(tmp_path: Path):
    from platen_document import DocumentProcessor, OCRProfile

    source_image = _scan_image(background="textured")
    oracle_image = _scan_image(background="textured", include_text=False)
    source_pdf = _write_fixture(tmp_path / "texture-oracle-source.pdf", background="textured")
    page_result = DocumentProcessor().extract_text(
        source_pdf,
        languages=["eng"],
        profile=OCRProfile.OCR_TEXT_V2,
        routing_policy="FAST",
        page_indices=[0],
    ).pages[0]
    token = next(token for token in page_result.tokens if token.text.casefold() == "ministry")
    box_points = (token.bbox.x - 1, token.bbox.y - 1, token.bbox.x + token.bbox.width + 1, token.bbox.y + token.bbox.height + 1)
    box_pixels = tuple(round(value * RASTER_SCALE) for value in box_points)
    repaired, _ = repair_ink_mask(source_image, box_pixels)
    source_crop = source_image.crop(box_pixels)
    oracle_crop = oracle_image.crop(box_pixels)
    repaired_crop = repaired.crop(box_pixels)
    before_mae = sum(ImageStat.Stat(ImageChops.difference(source_crop, oracle_crop)).mean) / 3
    after_mae = sum(ImageStat.Stat(ImageChops.difference(repaired_crop, oracle_crop)).mean) / 3

    print(f"TEXTURE_ORACLE_MAE before={before_mae:.4f} after={after_mae:.4f}")
    assert after_mae < before_mae
