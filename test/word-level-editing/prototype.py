"""Throwaway Phase 1 prototype; deliberately isolated from SDK source."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

import pymupdf as fitz
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


def _clip_box(box: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(size[0], x1), min(size[1], y1)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("target pixel box is empty or outside the patch")
    return x0, y0, x1, y1


def detect_protected_overlap(image: Image.Image, target: tuple[int, int, int, int]) -> str | None:
    """Fail closed when colored marks or continuous rules cross a word box."""
    rgb = image.convert("RGB")
    x0, y0, x1, y1 = _clip_box(target, rgb.size)
    crop = rgb.crop((x0, y0, x1, y1))
    raw = crop.tobytes()
    colorful = sum(
        1
        for offset in range(0, len(raw), 3)
        if max(raw[offset : offset + 3]) - min(raw[offset : offset + 3]) >= 55
        and min(raw[offset : offset + 3]) < 210
    )
    if colorful >= max(4, (len(raw) // 3) // 500):
        return "COLORED_OVERLAP"

    gray = ImageOps.grayscale(crop)
    width, height = gray.size
    dark_rows = [sum(1 for x in range(width) if gray.getpixel((x, y)) < 105) for y in range(height)]
    dark_columns = [sum(1 for y in range(height) if gray.getpixel((x, y)) < 105) for x in range(width)]
    if any(count >= width * 0.92 for count in dark_rows) or any(count >= height * 0.92 for count in dark_columns):
        return "LINEAR_STRUCTURE_OVERLAP"
    return None


def repair_ink_mask(
    image: Image.Image,
    target: tuple[int, int, int, int],
    *,
    background_margin: int = 32,
) -> tuple[Image.Image, Image.Image]:
    """Repair only dark selected ink, sampling the same scan line on both sides."""
    rgb = image.convert("RGB")
    x0, y0, x1, y1 = _clip_box(target, rgb.size)
    gray = ImageOps.grayscale(rgb)

    # Estimate local paper luminance from a one-pixel perimeter.  The fixed
    # contrast margin keeps mild paper texture out of the ink mask.
    perimeter: list[int] = []
    for x in range(x0, x1):
        perimeter.extend((gray.getpixel((x, max(0, y0 - 1))), gray.getpixel((x, min(rgb.height - 1, y1)))))
    for y in range(y0, y1):
        perimeter.extend((gray.getpixel((max(0, x0 - 1), y)), gray.getpixel((min(rgb.width - 1, x1), y))))
    background = median(perimeter) if perimeter else 255
    threshold = max(72, int(background) - background_margin)

    box_mask = Image.new("L", rgb.size, 0)
    ImageDraw.Draw(box_mask).rectangle((x0, y0, x1 - 1, y1 - 1), fill=255)
    dark = Image.eval(gray, lambda value: 255 if value < threshold else 0)
    seed = ImageChops.multiply(dark, box_mask)
    # A one-pixel allowance absorbs scan antialiasing while remaining clipped
    # to the OCR word box (the PDF overlay itself has a separate 1pt safety band).
    expanded = seed.filter(ImageFilter.MaxFilter(3))
    ink_mask = ImageChops.multiply(expanded, box_mask)

    repaired = rgb.copy()
    source = rgb.load()
    destination = repaired.load()
    mask_pixels = ink_mask.load()
    for y in range(y0, y1):
        x = x0
        while x < x1:
            if not mask_pixels[x, y]:
                x += 1
                continue
            run_start = x
            while x < x1 and mask_pixels[x, y]:
                x += 1
            run_end = x - 1
            left_x = run_start - 1 if run_start > 0 else None
            right_x = x if x < rgb.width else None
            while left_x is not None and mask_pixels[left_x, y]:
                left_x -= 1
                if left_x < 0:
                    left_x = None
            while right_x is not None and mask_pixels[right_x, y]:
                right_x += 1
                if right_x >= rgb.width:
                    right_x = None
            if left_x is None and right_x is None:
                raise ValueError("BACKGROUND_UNCERTAIN: no unmasked scan-line samples surround selected ink")
            left = source[left_x, y] if left_x is not None else None
            right = source[right_x, y] if right_x is not None else None
            span = max(1, run_end - run_start + 2)
            for pixel_x in range(run_start, run_end + 1):
                if left is not None and right is not None:
                    fraction = (pixel_x - run_start + 1) / span
                    destination[pixel_x, y] = tuple(
                        round(left[channel] * (1 - fraction) + right[channel] * fraction)
                        for channel in range(3)
                    )
                else:
                    destination[pixel_x, y] = left if left is not None else right
    return repaired, ink_mask


def edit_pdf(source_pdf, output_pdf, *, page_index=0, target_text="Ministry", replacement="hello") -> dict:
    """Edit one uniquely OCR-resolved scan word; refuse uncertain cases."""
    source_path = Path(source_pdf).resolve()
    output_path = Path(output_pdf).resolve()
    if source_path == output_path:
        return _refusal("SOURCE_AND_OUTPUT_ARE_IDENTICAL")
    if output_path.exists():
        return _refusal("OUTPUT_ALREADY_EXISTS")
    try:
        source_hash = _sha256(source_path)
        with fitz.open(source_path) as source:
            if source.needs_pass:
                return _refusal("PROTECTED_SOURCE_UNSUPPORTED")
            if page_index < 0 or page_index >= len(source):
                return _refusal("PAGE_INDEX_OUT_OF_RANGE")
            page = source[page_index]
            if not _supported_geometry(page):
                return _refusal("UNSUPPORTED_PAGE_GEOMETRY", page_count=len(source))
            if not page.get_images(full=True):
                return _refusal("NOT_AN_IMAGE_SCAN", page_count=len(source))

            ocr_page = _ocr_page(source_path, page_index)
            matches = [token for token in ocr_page.tokens if _normalize_text(token.text) == _normalize_text(target_text)]
            if len(matches) != 1:
                return _refusal("TARGET_NOT_UNIQUE", match_count=len(matches), page_count=len(source))
            token = matches[0]
            confidence = token.confidence.raw_value if token.confidence else None
            if confidence is None or confidence < 70:
                return _refusal("LOW_OCR_CONFIDENCE", confidence=confidence, page_count=len(source))
            target_rect = _token_rect(token)
            allowed_rect = fitz.Rect(target_rect.x0 - 1, target_rect.y0 - 1, target_rect.x1 + 1, target_rect.y1 + 1) & page.rect
            detect_rect = fitz.Rect(target_rect.x0 - 1.5, target_rect.y0 - 1.5, target_rect.x1 + 1.5, target_rect.y1 + 1.5) & page.rect
            context_rect = fitz.Rect(target_rect.x0 - 4, target_rect.y0 - 4, target_rect.x1 + 4, target_rect.y1 + 4) & page.rect

            dpi = 288
            scale = dpi / 72
            page_pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
            page_image = Image.frombytes("RGB", (page_pixmap.width, page_pixmap.height), page_pixmap.samples)
            context_px = _rect_pixels(context_rect, scale, page_image.size)
            detect_px = _rect_pixels(detect_rect, scale, page_image.size)
            allowed_px = _rect_pixels(allowed_rect, scale, page_image.size)
            local_allowed = (
                allowed_px[0] - context_px[0],
                allowed_px[1] - context_px[1],
                allowed_px[2] - context_px[0],
                allowed_px[3] - context_px[1],
            )
            context_image = page_image.crop(context_px)
            local_detect = (
                detect_px[0] - context_px[0],
                detect_px[1] - context_px[1],
                detect_px[2] - context_px[0],
                detect_px[3] - context_px[1],
            )
            refusal = detect_protected_overlap(context_image, local_detect)
            if refusal:
                return _refusal(refusal, page_count=len(source), page_index=page_index)
            try:
                repaired_context, ink_mask = repair_ink_mask(context_image, local_allowed)
            except ValueError:
                return _refusal("BACKGROUND_UNCERTAIN", page_count=len(source), page_index=page_index)
            patch = repaired_context.crop(
                (
                    allowed_px[0] - context_px[0],
                    allowed_px[1] - context_px[1],
                    allowed_px[2] - context_px[0],
                    allowed_px[3] - context_px[1],
                )
            )
            ink_color = _ink_color(context_image, ink_mask)

            hidden_rect, hidden_reason = _hidden_target_rect(page, target_rect, _normalize_text(target_text))
            if hidden_reason:
                return _refusal(hidden_reason, page_count=len(source), page_index=page_index)

            source_page_count = len(source)
            source_geometry = [tuple(page.rect), page.rotation, tuple(page.cropbox), tuple(page.mediabox)]
            source_image_hashes = _image_hashes(source)
            source_native_words = _word_records(page)
            source_ocr_tokens = _token_records(ocr_page.tokens, allowed_rect)
            # Phase 1 deliberately uses a local Base14 approximation, not
            # font recognition.  The serif bold face matched this source
            # heading better in visual inspection than the first Helvetica
            # draft.  Size and baseline derive only from the frozen OCR box.
            font_name = "tibo"
            font_size = target_rect.height * 1.10
            baseline = target_rect.y0 + target_rect.height * 0.80
            image_stream = _png_bytes(patch)
            page_count = len(source)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(output_path.name + ".phase1-tmp")
        if temporary.exists():
            temporary.unlink()
        # Avoid garbage collection and stream recompression so original scan
        # image bytes remain present; the new patch is one separate XObject.
        document = fitz.open(source_path)
        page = document[page_index]
        if hidden_rect is not None:
            page.add_redact_annot(hidden_rect, fill=None, cross_out=False)
            page.apply_redactions(images=0, graphics=0, text=0)
        page.insert_image(allowed_rect, stream=image_stream, overlay=True, keep_proportion=False)
        page.insert_text(
            fitz.Point(target_rect.x0, baseline),
            replacement,
            fontname=font_name,
            fontsize=font_size,
            color=ink_color,
            overlay=True,
        )
        document.save(temporary, garbage=0, deflate=False, deflate_images=False)
        document.close()

        validation = _validate_candidate(
            source_path,
            temporary,
            page_index=page_index,
            target_rect=target_rect,
            allowed_rect=allowed_rect,
            target_text=target_text,
            replacement=replacement,
            source_hash=source_hash,
            source_page_count=source_page_count,
            source_geometry=source_geometry,
            source_image_hashes=source_image_hashes,
            source_native_words=source_native_words,
            source_ocr_tokens=source_ocr_tokens,
            hidden_target=hidden_rect is not None,
        )
        if not validation["valid"]:
            temporary.unlink(missing_ok=True)
            return _refusal("CANDIDATE_VALIDATION_FAILED", checks=validation)
        os.replace(temporary, output_path)
        return {
            "status": "EDITED",
            "page_count": page_count,
            "page_index": page_index,
            "target_token_id": token.id,
            "target_bbox_points": [round(value, 3) for value in target_rect],
            "replacement_font_approximation": font_name,
            "source_hidden_target_present": hidden_rect is not None,
            "source_native_word_count": len(source_native_words),
            "candidate_native_word_count": validation["candidate_native_word_count"],
            "ocr_confidence_raw": round(confidence, 2),
            "ocr_confidence_scale": token.confidence.scale,
            "replacement_hits_in_target": validation["replacement_hits_in_target"],
            "old_target_hits_in_target": validation["old_target_hits_in_target"],
            "replacement_ocr_hits_in_target": validation["replacement_ocr_hits_in_target"],
            "old_ocr_target_hits": validation["old_ocr_target_hits"],
            "unexpected_ocr_target_tokens": validation["unexpected_ocr_target_tokens"],
            "hidden_target_removed": validation["hidden_target_removed"],
            "neighbor_tokens_preserved": validation["neighbor_tokens_preserved"],
            "neighbor_text_layer_preserved": validation["neighbor_text_layer_preserved"],
            "image_streams_preserved": validation["image_streams_preserved"],
            "unedited_pages_pixel_identical_144dpi": validation["unedited_pages_pixel_identical_144dpi"],
            "outside_changed_pixels_144dpi": validation["outside_changed_pixels_144dpi"],
            "outside_changed_pixels_by_dpi": validation["outside_changed_pixels_by_dpi"],
            "max_channel_delta_by_dpi": validation["max_channel_delta_by_dpi"],
            "source_sha256": source_hash,
            "candidate_sha256": _sha256(output_path),
        }
    except Exception as error:
        return _refusal("PROTOTYPE_ERROR", error_type=type(error).__name__, error=str(error)[:240])


def _refusal(reason: str, **fields: Any) -> dict[str, Any]:
    return {"status": "REFUSED", "reason": reason, **fields}


def _normalize_text(value: str) -> str:
    return value.strip().strip(".,;:!?\"'()[]{}<>–—").casefold()


def _token_rect(token: Any) -> fitz.Rect:
    box = token.bbox
    return fitz.Rect(box.x, box.y, box.x + box.width, box.y + box.height)


def _supported_geometry(page: fitz.Page) -> bool:
    return (
        page.rotation == 0
        and abs(page.cropbox.x0 - page.mediabox.x0) < 0.05
        and abs(page.cropbox.y0 - page.mediabox.y0) < 0.05
        and abs(page.cropbox.x1 - page.mediabox.x1) < 0.05
        and abs(page.cropbox.y1 - page.mediabox.y1) < 0.05
    )


def _ocr_page(source: Path, page_index: int):
    from platen_document import DocumentProcessor, OCRProfile

    result = DocumentProcessor().extract_text(
        source,
        languages=["eng"],
        profile=OCRProfile.OCR_TEXT_V2,
        routing_policy="FAST",
        page_indices=[page_index],
    )
    page = next((page for page in result.pages if page.page_index == page_index), None)
    if page is None:
        raise ValueError("OCR did not return the selected page")
    return page


def _rect_pixels(rect: fitz.Rect, scale: float, size: tuple[int, int]) -> tuple[int, int, int, int]:
    return (
        max(0, round(rect.x0 * scale)),
        max(0, round(rect.y0 * scale)),
        min(size[0], round(rect.x1 * scale)),
        min(size[1], round(rect.y1 * scale)),
    )


def _ink_color(image: Image.Image, mask: Image.Image) -> tuple[float, float, float]:
    pixels = image.convert("RGB").load()
    selected = [pixels[x, y] for y in range(image.height) for x in range(image.width) if mask.getpixel((x, y))]
    if not selected:
        return (0.0, 0.0, 0.0)
    selected.sort(key=lambda pixel: sum(pixel) / 3)
    darkest = selected[: max(1, round(len(selected) * 0.20))]
    return tuple(median([pixel[channel] for pixel in darkest]) / 255 for channel in range(3))


def _word_records(page: fitz.Page) -> list[tuple[str, tuple[float, float, float, float]]]:
    return [
        (str(word[4]), tuple(round(float(value), 2) for value in word[:4]))
        for word in page.get_text("words")
    ]


def _token_records(tokens: tuple[Any, ...], excluded_rect: fitz.Rect) -> list[tuple[str, tuple[float, float, float, float]]]:
    records = []
    for token in tokens:
        rect = _token_rect(token)
        if rect.intersects(excluded_rect):
            continue
        records.append((token.text, tuple(round(value, 3) for value in rect)))
    return records


def _same_neighbor_tokens(source_records: list[tuple[str, tuple[float, float, float, float]]], candidate_records: list[tuple[str, tuple[float, float, float, float]]], tolerance_points: float = 0.5) -> bool:
    if Counter(_normalize_text(text) for text, _ in source_records) != Counter(_normalize_text(text) for text, _ in candidate_records):
        return False
    source_by_text: dict[str, list[tuple[float, float, float, float]]] = {}
    candidate_by_text: dict[str, list[tuple[float, float, float, float]]] = {}
    for text, box in source_records:
        source_by_text.setdefault(_normalize_text(text), []).append(box)
    for text, box in candidate_records:
        candidate_by_text.setdefault(_normalize_text(text), []).append(box)
    for text, boxes in source_by_text.items():
        remaining = candidate_by_text[text][:]
        for source_box in boxes:
            closest = min(remaining, key=lambda box: max(abs(left - right) for left, right in zip(source_box, box)))
            delta = max(abs(left - right) for left, right in zip(source_box, closest))
            if delta > tolerance_points:
                return False
            remaining.remove(closest)
    return True


def _hidden_target_rect(page: fitz.Page, target_rect: fitz.Rect, normalized_target: str) -> tuple[fitz.Rect | None, str | None]:
    overlapping = []
    for word in page.get_text("words"):
        if _normalize_text(str(word[4])) != normalized_target:
            continue
        rect = fitz.Rect(word[:4])
        if rect.intersects(target_rect):
            overlapping.append(rect)
    if not overlapping:
        return None, None
    if len(overlapping) != 1:
        return None, "HIDDEN_TEXT_TARGET_AMBIGUOUS"
    text_rect = overlapping[0]
    intersection = text_rect & target_rect
    if intersection.is_empty or intersection.get_area() / max(0.01, min(text_rect.get_area(), target_rect.get_area())) < 0.65:
        return None, "HIDDEN_TEXT_ALIGNMENT_UNCERTAIN"
    trace = []
    for span in page.get_texttrace():
        text = "".join(chr(character[0]) for character in span.get("chars", ()))
        if _normalize_text(text) == normalized_target and fitz.Rect(span["bbox"]).intersects(target_rect):
            trace.append((span.get("type"), fitz.Rect(span["bbox"])))
    if len(trace) != 1:
        return None, "HIDDEN_TEXT_RENDER_MODE_UNCERTAIN"
    if trace[0][0] != 3:
        return None, "VISIBLE_NATIVE_TARGET_UNSUPPORTED"
    visible_box = fitz.Rect(target_rect.x0 - 1, target_rect.y0 - 1, target_rect.x1 + 1, target_rect.y1 + 1)
    redact = fitz.Rect(text_rect.x0 - 0.1, text_rect.y0 - 0.1, text_rect.x1 + 0.1, text_rect.y1 + 0.1)
    if not visible_box.contains(redact):
        return None, "HIDDEN_TEXT_ALIGNMENT_UNCERTAIN"
    return redact, None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_hashes(document: fitz.Document) -> set[str]:
    hashes = set()
    for page in document:
        for image in page.get_images(full=True):
            xref = int(image[0])
            if xref > 0:
                hashes.add(hashlib.sha256(document.extract_image(xref)["image"]).hexdigest())
    return hashes


def _render_image(page: fitz.Page, dpi: int) -> Image.Image:
    pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def _pixel_difference(original: Image.Image, candidate: Image.Image, allowed: fitz.Rect | None, dpi: int) -> tuple[int, int, int]:
    if original.size != candidate.size:
        return -1, -1, 255
    difference = ImageChops.difference(original, candidate)
    red, green, blue = difference.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    changed = maximum.point(lambda value: 255 if value > 2 else 0)
    changed_count = changed.histogram()[255]
    if allowed is None:
        outside_count = changed_count
    else:
        scale = dpi / 72
        x0, y0 = max(0, math.floor(allowed.x0 * scale)), max(0, math.floor(allowed.y0 * scale))
        x1, y1 = min(original.width, math.ceil(allowed.x1 * scale)), min(original.height, math.ceil(allowed.y1 * scale))
        allowed_mask = Image.new("L", original.size, 0)
        ImageDraw.Draw(allowed_mask).rectangle((x0, y0, x1 - 1, y1 - 1), fill=255)
        outside = ImageChops.multiply(changed, ImageChops.invert(allowed_mask))
        outside_count = outside.histogram()[255]
    max_delta = max(maximum.getextrema())
    return changed_count, outside_count, max_delta


def _validate_candidate(
    source_path: Path,
    candidate_path: Path,
    *,
    page_index: int,
    target_rect: fitz.Rect,
    allowed_rect: fitz.Rect,
    target_text: str,
    replacement: str,
    source_hash: str,
    source_page_count: int,
    source_geometry: list[Any],
    source_image_hashes: set[str],
    source_native_words: list[tuple[str, tuple[float, float, float, float]]],
    source_ocr_tokens: list[tuple[str, tuple[float, float, float, float]]],
    hidden_target: bool,
) -> dict[str, Any]:
    checks: dict[str, Any] = {"valid": False}
    with fitz.open(source_path) as source, fitz.open(candidate_path) as candidate:
        checks["page_count_preserved"] = len(candidate) == source_page_count
        checks["page_geometry_preserved"] = all(
            abs(float(left) - float(right)) < 0.01
            for left, right in zip(source_geometry[0], candidate[page_index].rect)
        ) and candidate[page_index].rotation == source_geometry[1]
        candidate_page = candidate[page_index]
        candidate_words = _word_records(candidate_page)
        replacement_hits = [
            record for record in candidate_words
            if _normalize_text(record[0]) == _normalize_text(replacement)
            and fitz.Rect(record[1]).intersects(target_rect)
        ]
        old_hits = [
            record for record in candidate_words
            if _normalize_text(record[0]) == _normalize_text(target_text)
            and fitz.Rect(record[1]).intersects(target_rect)
        ]
        checks["replacement_hits_in_target"] = len(replacement_hits)
        checks["old_target_hits_in_target"] = len(old_hits)
        checks["hidden_target_removed"] = (not hidden_target) or len(old_hits) == 0
        source_neighbors = Counter(record for record in source_native_words if not fitz.Rect(record[1]).intersects(allowed_rect) and _normalize_text(record[0]) != _normalize_text(target_text))
        candidate_neighbors = Counter(record for record in candidate_words if not fitz.Rect(record[1]).intersects(allowed_rect) and _normalize_text(record[0]) != _normalize_text(replacement) and _normalize_text(record[0]) != _normalize_text(target_text))
        checks["neighbor_text_layer_preserved"] = source_neighbors == candidate_neighbors
        checks["image_streams_preserved"] = source_image_hashes.issubset(_image_hashes(candidate))

        diffs: dict[str, int] = {}
        maxima: dict[str, int] = {}
        for dpi in (72, 144, 288):
            source_image = _render_image(source[page_index], dpi)
            candidate_image = _render_image(candidate_page, dpi)
            changed, outside, max_delta = _pixel_difference(source_image, candidate_image, allowed_rect, dpi)
            diffs[str(dpi)] = outside
            maxima[str(dpi)] = max_delta
            if dpi == 144:
                checks["outside_changed_pixels_144dpi"] = outside
                checks["changed_pixels_144dpi"] = changed

        unchanged = True
        for index in range(len(source)):
            if index == page_index:
                continue
            if _render_image(source[index], 144).tobytes() != _render_image(candidate[index], 144).tobytes():
                unchanged = False
                break
        checks["unedited_pages_pixel_identical_144dpi"] = unchanged

        candidate_ocr = _ocr_page(candidate_path, page_index)
        target_ocr_tokens = [token for token in candidate_ocr.tokens if _token_rect(token).intersects(allowed_rect)]
        checks["replacement_ocr_hits_in_target"] = sum(
            1 for token in target_ocr_tokens if _normalize_text(token.text) == _normalize_text(replacement)
        )
        checks["old_ocr_target_hits"] = sum(
            1 for token in target_ocr_tokens if _normalize_text(token.text) == _normalize_text(target_text)
        )
        checks["unexpected_ocr_target_tokens"] = sum(
            1 for token in target_ocr_tokens if _normalize_text(token.text) != _normalize_text(replacement)
        )
        candidate_ocr_tokens = _token_records(candidate_ocr.tokens, allowed_rect)
        checks["neighbor_tokens_preserved"] = _same_neighbor_tokens(source_ocr_tokens, candidate_ocr_tokens)
        checks["candidate_native_word_count"] = len(candidate_words)
        checks["replacement_hits_in_target"] = len(replacement_hits)
        checks["old_target_hits_in_target"] = len(old_hits)
        checks["outside_changed_pixels_by_dpi"] = diffs
        checks["max_channel_delta_by_dpi"] = maxima
        checks["source_sha256_unchanged"] = _sha256(source_path) == source_hash
        checks["valid"] = (
            checks["page_count_preserved"]
            and checks["page_geometry_preserved"]
            and checks["replacement_hits_in_target"] == 1
            and checks["old_target_hits_in_target"] == 0
            and checks["replacement_ocr_hits_in_target"] == 1
            and checks["old_ocr_target_hits"] == 0
            and checks["unexpected_ocr_target_tokens"] == 0
            and checks["hidden_target_removed"]
            and checks["neighbor_text_layer_preserved"]
            and checks["image_streams_preserved"]
            and checks["unedited_pages_pixel_identical_144dpi"]
            and checks["outside_changed_pixels_144dpi"] == 0
            and diffs["72"] == 0
            and diffs["288"] == 0
            and checks["neighbor_tokens_preserved"]
            and checks["source_sha256_unchanged"]
        )
    return checks


def _png_bytes(image: Image.Image) -> bytes:
    from io import BytesIO

    stream = BytesIO()
    image.save(stream, format="PNG", optimize=False)
    return stream.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--page-index", type=int, default=0, help="zero-based PDF page index")
    parser.add_argument("--target", default="Ministry")
    parser.add_argument("--replacement", default="hello")
    args = parser.parse_args()
    result = edit_pdf(args.source, args.output, page_index=args.page_index, target_text=args.target, replacement=args.replacement)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "EDITED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
