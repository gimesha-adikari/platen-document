"""Regenerate reviewable, source-safe crops and metrics from synthetic fixtures."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont

from prototype import _ocr_page, _token_rect, edit_pdf
from test_word_level_editing import _write_fixture


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts" / "synthetic"


def _render_crop(pdf_path: Path, bbox: list[float], dpi: int = 144) -> Image.Image:
    x0, y0, x1, y1 = bbox
    crop = fitz.Rect(max(0, x0 - 15), max(0, y0 - 8), x1 + 105, y1 + 8)
    with fitz.open(pdf_path) as document:
        pixmap = document[0].get_pixmap(dpi=dpi, clip=crop, colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _labeled_pair(before: Image.Image, after: Image.Image, label: str) -> Image.Image:
    panel_width = max(before.width, after.width)
    label_height = 34
    canvas = Image.new("RGB", (panel_width * 2, max(before.height, after.height) + label_height), "white")
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
    draw.text((8, 5), f"{label}: SOURCE", fill="black", font=font)
    draw.text((panel_width + 8, 5), f"{label}: EDITED", fill="black", font=font)
    canvas.paste(before, (0, label_height))
    canvas.paste(after, (panel_width, label_height))
    return canvas


def generate() -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = {
        "clean": {},
        "textured": {"background": "textured"},
        "hidden_ocr": {"hidden_text": True},
        "stamp": {"stamp": True},
        "table_border": {"rule": True},
        "lossy_skew": {"jpeg": True, "skew": True},
    }
    summary = {"artifact_scope": "synthetic fixtures only; no user PDF or source-derived page image", "cases": {}}
    with tempfile.TemporaryDirectory(prefix="platen-word-phase1-fixtures-") as temp:
        temp_root = Path(temp)
        for name, fixture_options in cases.items():
            source = _write_fixture(temp_root / f"{name}.pdf", **fixture_options)
            candidate = temp_root / f"{name}-edited.pdf"
            result = edit_pdf(source, candidate, page_index=0, target_text="Ministry", replacement="hello")
            summary["cases"][name] = {
                key: value
                for key, value in result.items()
                if key in {
                    "status",
                    "reason",
                    "replacement_hits_in_target",
                    "old_target_hits_in_target",
                    "replacement_ocr_hits_in_target",
                    "unexpected_ocr_target_tokens",
                    "neighbor_tokens_preserved",
                    "neighbor_text_layer_preserved",
                    "outside_changed_pixels_144dpi",
                    "outside_changed_pixels_by_dpi",
                    "image_streams_preserved",
                    "source_hidden_target_present",
                }
            }
            if result["status"] == "EDITED":
                before = _render_crop(source, result["target_bbox_points"])
                after = _render_crop(candidate, result["target_bbox_points"])
                comparison = _labeled_pair(before, after, name.replace("_", " ").upper())
            else:
                token = next(token for token in _ocr_page(source, 0).tokens if token.text.casefold() == "ministry")
                rect = _token_rect(token)
                before = _render_crop(source, [rect.x0, rect.y0, rect.x1, rect.y1])
                after = Image.new("RGB", before.size, "white")
                draw = ImageDraw.Draw(after)
                message = f"REFUSED: {result.get('reason', 'unknown')}"
                draw.text((12, max(12, before.height // 2 - 8)), message, fill=(150, 0, 0))
                comparison = _labeled_pair(before, after, name.replace("_", " ").upper())
            comparison.save(OUTPUT / f"{name}-comparison.png", optimize=True)
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


if __name__ == "__main__":
    print(json.dumps(generate(), indent=2, sort_keys=True))
