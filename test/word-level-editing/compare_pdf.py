"""Independent Poppler comparison for one source PDF and its private candidate."""

from __future__ import annotations

import argparse
from collections import Counter
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import subprocess
import tempfile
import tempfile

import pymupdf as fitz
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps


class PdfTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.words = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "word":
            self.current = {key.lower(): value for key, value in attrs}

    def handle_data(self, data):
        if self.current is not None and data.strip():
            record = self.current
            self.words.append((data.strip(), tuple(float(record[k]) for k in ("xmin", "ymin", "xmax", "ymax"))))
            self.current = None


def _text_words(path: Path) -> list[tuple[str, tuple[float, float, float, float]]]:
    process = subprocess.run(
        ["pdftotext", "-f", "1", "-l", "1", "-bbox", str(path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    parser = PdfTextParser()
    parser.feed(process.stdout)
    return parser.words


def _normalize(value: str) -> str:
    return value.strip(".,;:!?\"'()[]{}<>–—").casefold()


def _inside(record, rect: fitz.Rect) -> bool:
    return fitz.Rect(record[1]).intersects(rect)


def _pixel_metrics(source: Image.Image, candidate: Image.Image, allowed: fitz.Rect, dpi: int) -> tuple[int, int, int]:
    if source.size != candidate.size:
        return -1, -1, 255
    difference = ImageChops.difference(source, candidate)
    r, g, b = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(r, g), b)
    changed = maximum.point(lambda value: 255 if value > 2 else 0)
    changed_count = changed.histogram()[255]
    scale = dpi / 72
    x0, y0 = max(0, math.floor(allowed.x0 * scale)), max(0, math.floor(allowed.y0 * scale))
    x1, y1 = min(source.width, math.ceil(allowed.x1 * scale)), min(source.height, math.ceil(allowed.y1 * scale))
    mask = Image.new("L", source.size, 0)
    ImageDraw.Draw(mask).rectangle((x0, y0, x1 - 1, y1 - 1), fill=255)
    outside_count = ImageChops.multiply(changed, ImageChops.invert(mask)).histogram()[255]
    return changed_count, outside_count, max(maximum.getextrema())


def _poppler_render(path: Path, prefix: Path, dpi: int) -> Path:
    subprocess.run(
        ["pdftoppm", "-f", "1", "-l", "1", "-r", str(dpi), "-png", "-singlefile", str(path), str(prefix)],
        check=True,
        capture_output=True,
        text=True,
    )
    return prefix.with_suffix(".png")


def compare(source_path: Path, candidate_path: Path, prototype_manifest: Path, output_dir: Path) -> dict:
    source_path = source_path.resolve()
    candidate_path = candidate_path.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(prototype_manifest.read_text())
    x0, y0, x1, y1 = manifest["target_bbox_points"]
    target_rect = fitz.Rect(x0, y0, x1, y1)
    allowed_rect = fitz.Rect(x0 - 1, y0 - 1, x1 + 1, y1 + 1)

    qpdf = subprocess.run(["qpdf", "--check", str(candidate_path)], check=False, capture_output=True, text=True)
    qpdf_ok = qpdf.returncode == 0

    source_words = _text_words(source_path)
    candidate_words = _text_words(candidate_path)
    source_inside = [record for record in source_words if _inside(record, allowed_rect)]
    candidate_inside = [record for record in candidate_words if _inside(record, allowed_rect)]
    source_outside = Counter(
        (_normalize(text), tuple(round(value, 1) for value in box))
        for text, box in source_words if not _inside((text, box), allowed_rect)
    )
    candidate_outside = Counter(
        (_normalize(text), tuple(round(value, 1) for value in box))
        for text, box in candidate_words if not _inside((text, box), allowed_rect)
    )
    old_inside = sum(1 for text, _ in candidate_inside if _normalize(text) == "ministry")
    new_inside = sum(1 for text, _ in candidate_inside if _normalize(text) == "hello")

    dpi = 288
    comparison_path = output_dir / "poppler-target-before-after.png"
    with tempfile.TemporaryDirectory(prefix="platen-poppler-word-compare-") as temporary:
        temporary_dir = Path(temporary)
        source_image_path = _poppler_render(source_path, temporary_dir / "source-page1", dpi)
        candidate_image_path = _poppler_render(candidate_path, temporary_dir / "edited-page1", dpi)
        with Image.open(source_image_path) as image:
            source_image = image.convert("RGB")
        with Image.open(candidate_image_path) as image:
            candidate_image = image.convert("RGB")
        changed, outside, maximum = _pixel_metrics(source_image, candidate_image, allowed_rect, dpi)

        crop_rect = fitz.Rect(max(0, x0 - 15), max(0, y0 - 8), x1 + 105, y1 + 8)
        scale = dpi / 72
        crop_box = tuple(round(value * scale) for value in (crop_rect.x0, crop_rect.y0, crop_rect.x1, crop_rect.y1))
        before_crop = source_image.crop(crop_box)
        after_crop = candidate_image.crop(crop_box)
        label_height = 36
        panel_width = max(before_crop.width, after_crop.width)
        comparison = Image.new("RGB", (panel_width * 2, max(before_crop.height, after_crop.height) + label_height), "white")
        draw = ImageDraw.Draw(comparison)
        try:
            label_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        except OSError:
            label_font = ImageFont.load_default()
        draw.text((8, 6), "SOURCE", fill="black", font=label_font)
        draw.text((panel_width + 8, 6), "EDITED", fill="black", font=label_font)
        comparison.paste(before_crop, (0, label_height))
        comparison.paste(after_crop, (panel_width, label_height))
        comparison.save(comparison_path)

    with fitz.open(source_path) as source, fitz.open(candidate_path) as candidate:
        page_count_match = len(source) == len(candidate) == manifest["page_count"]
    qpdf_text = (qpdf.stdout + qpdf.stderr).strip()
    return {
        "renderer": "Poppler pdftoppm and pdftotext",
        "page_count_match": page_count_match,
        "qpdf_check_passed": qpdf_ok,
        "target_logical_text": {
            "source_text_words_in_allowed_region": len(source_inside),
            "candidate_hello_words_in_allowed_region": new_inside,
            "candidate_ministry_words_in_allowed_region": old_inside,
            "outside_target_words_and_positions_preserved": source_outside == candidate_outside,
        },
        "visual_288dpi": {
            "changed_pixels_over_2": changed,
            "changed_pixels_outside_fixed_target_plus_1pt": outside,
            "max_channel_delta": maximum,
        },
        "comparison_image": comparison_path.name,
        "qpdf_check_output": qpdf_text,
        "pass": (
            page_count_match
            and qpdf_ok
            and new_inside == 1
            and old_inside == 0
            and source_outside == candidate_outside
            and outside == 0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = compare(args.source, args.candidate, args.manifest, args.output_dir)
    (args.output_dir / "poppler-comparison-summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
