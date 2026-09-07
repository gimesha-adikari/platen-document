"""Shared OCR-aware markup selection and annotation foundation.

This module is the only V2 path that resolves text selections for Highlight,
Underline, and Strikeout.  It consumes the canonical OCR V2 result; it never
calls an OCR engine directly.  Legacy markup remains in ``app.api.tools``.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pymupdf as fitz

from .contracts import DocumentResult, OCRToken, PageGeometry, PageProcessingSource, Rect
from .errors import (
    AnnotationWriteError,
    EngineUnavailableError,
    OCRTimeoutError,
    WordGeometryUnavailableError,
    TextNotFoundError,
)
from .geometry import clamp_rect, visible_rect_to_native_pdf
from .orchestration import OCRV2Worker
from .routing import RoutePolicy
from .validation import OCRProfile


class MarkupAction(str, Enum):
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"


class MarkupMode(str, Enum):
    SMART = "smart"
    OCR = "ocr"
    NATIVE = "native"
    MANUAL = "manual"


class MarkupSourceType(str, Enum):
    NATIVE = "native"
    OCR = "ocr"
    HYBRID = "hybrid"


MarkupColor = tuple[float, float, float]


@dataclass(frozen=True)
class MarkupRegion:
    """A page-indexed rectangle in visible CropBox-relative PDF points.

    ``page_number`` is one-based because it is intended for public callers.
    ``rect`` uses the same top-left, X-right/Y-down coordinate space exposed by
    :class:`PageGeometry`. A zero-area rectangle is accepted and reported as
    an ``EMPTY`` resolution; negative width or height is treated the same way.
    """

    page_number: int
    rect: Rect
    region_id: str | None = None
    color: MarkupColor = (1.0, 1.0, 0.0)

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("MarkupRegion.page_number must be one-based and positive")
        values = (*self.color, self.rect.x, self.rect.y, self.rect.width, self.rect.height)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("MarkupRegion coordinates and color values must be finite")
        if len(self.color) != 3 or any(float(value) < 0.0 or float(value) > 1.0 for value in self.color):
            raise ValueError("MarkupRegion.color must contain three values in the inclusive range 0.0 to 1.0")
        object.__setattr__(self, "color", tuple(float(value) for value in self.color))


class MarkupRegionStatus(str, Enum):
    ANNOTATED = "annotated"
    EMPTY = "empty"
    OUT_OF_BOUNDS = "out_of_bounds"
    NO_WORDS = "no_words"


@dataclass(frozen=True)
class ResolvedMarkupRegion:
    """One input region and its deterministic annotation outcome."""

    region_index: int
    region_id: str | None
    page_number: int
    requested_rect: Rect
    resolved_rect: Rect | None
    color: MarkupColor
    status: MarkupRegionStatus
    selection: "MarkupSelection | None" = None
    annotation_rects: tuple[Rect, ...] = ()
    annotation_count: int = 0

    @property
    def selected_text(self) -> str:
        return self.selection.matched_text if self.selection else ""

    @property
    def word_ids(self) -> tuple[str, ...]:
        return self.selection.word_ids if self.selection else ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_index": self.region_index,
            "region_id": self.region_id,
            "page_number": self.page_number,
            "requested_rect": asdict(self.requested_rect),
            "resolved_rect": asdict(self.resolved_rect) if self.resolved_rect else None,
            "color": list(self.color),
            "status": self.status.value,
            "selected_text": self.selected_text,
            "word_ids": list(self.word_ids),
            "selection": self.selection.to_dict() if self.selection else None,
            "annotation_rects": [asdict(rect) for rect in self.annotation_rects],
            "annotation_count": self.annotation_count,
        }


@dataclass(frozen=True)
class CanonicalMarkupWord:
    id: str
    text: str
    page_index: int
    bbox: Rect
    confidence: float | None
    source_type: MarkupSourceType
    provenance: tuple[str, ...]


@dataclass(frozen=True)
class MarkupSelection:
    page_index: int
    matched_text: str
    word_ids: tuple[str, ...]
    reading_order_start: int
    reading_order_end: int
    words: tuple[CanonicalMarkupWord, ...]
    group_rects: tuple[Rect, ...]
    source_type: MarkupSourceType
    confidence: tuple[float, ...]
    provenance: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        def convert(value: Any) -> Any:
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, tuple):
                return [convert(item) for item in value]
            if isinstance(value, Rect):
                return asdict(value)
            if isinstance(value, CanonicalMarkupWord):
                return {key: convert(item) for key, item in asdict(value).items()}
            return value

        return {key: convert(value) for key, value in asdict(self).items()}


@dataclass(frozen=True)
class MarkupExecutionResult:
    action: MarkupAction
    mode: MarkupMode
    source_policy: str
    page_count: int
    selections: tuple[MarkupSelection, ...]
    page_sources: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "ocr_v2_markup_result.v1",
            "action": self.action.value,
            "mode": self.mode.value,
            "source_policy": self.source_policy,
            "page_count": self.page_count,
            "selection_count": len(self.selections),
            "selections": [selection.to_dict() for selection in self.selections],
            "page_sources": list(self.page_sources),
        }


@dataclass(frozen=True)
class RegionMarkupExecutionResult:
    """Public result for a region-based markup operation."""

    action: MarkupAction
    mode: MarkupMode
    source_policy: str
    output_path: str
    page_count: int
    regions: tuple[ResolvedMarkupRegion, ...]
    page_sources: tuple[dict[str, Any], ...]
    document_result_reused: bool
    extraction_performed: bool

    @property
    def annotation_count(self) -> int:
        return sum(region.annotation_count for region in self.regions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "ocr_v2_region_markup_result.v1",
            "action": self.action.value,
            "mode": self.mode.value,
            "source_policy": self.source_policy,
            "output_path": self.output_path,
            "page_count": self.page_count,
            "region_count": len(self.regions),
            "annotation_count": self.annotation_count,
            "document_result_reused": self.document_result_reused,
            "extraction_performed": self.extraction_performed,
            "regions": [region.to_dict() for region in self.regions],
            "page_sources": list(self.page_sources),
        }


def _query_tokens(value: str) -> tuple[str, ...]:
    # Exact matching is performed over canonical reading-order tokens.  Word
    # punctuation is retained as a token so punctuation-sensitive queries do
    # not silently become fuzzy matches.
    return tuple(token.casefold() for token in re.findall(r"\w+|[^\w\s]", value, flags=re.UNICODE))


def _token_parts(value: str) -> tuple[str, ...]:
    return _query_tokens(value)


def _source_type(page: Any) -> MarkupSourceType:
    source = page.processing_source
    if source is PageProcessingSource.NATIVE_EXTRACTION:
        return MarkupSourceType.NATIVE
    if source is PageProcessingSource.HYBRID:
        return MarkupSourceType.HYBRID
    return MarkupSourceType.OCR


def _canonical_words(page: Any, mode: MarkupMode) -> tuple[CanonicalMarkupWord, ...]:
    source_type = _source_type(page)
    if mode is MarkupMode.NATIVE and source_type is not MarkupSourceType.NATIVE:
        return ()
    if mode is MarkupMode.OCR and source_type is MarkupSourceType.NATIVE:
        return ()
    tokens_by_id = page.tokens_by_id
    words: list[CanonicalMarkupWord] = []
    for token_id in page.reading_order:
        token = tokens_by_id.get(token_id)
        if token is None or not token.text.strip():
            continue
        words.append(
            CanonicalMarkupWord(
                id=token.id,
                text=token.text,
                page_index=page.page_index,
                bbox=token.bbox,
                confidence=token.confidence.raw_value if token.confidence else None,
                source_type=source_type,
                provenance=tuple(page.provenance_refs),
            )
        )
    return tuple(words)


def _line_groups(words: tuple[CanonicalMarkupWord, ...]) -> tuple[Rect, ...]:
    groups: list[list[CanonicalMarkupWord]] = []
    for word in words:
        if not groups:
            groups.append([word])
            continue
        current = groups[-1]
        current_rect = Rect(
            min(item.bbox.x for item in current),
            min(item.bbox.y for item in current),
            max(item.bbox.x1 for item in current) - min(item.bbox.x for item in current),
            max(item.bbox.y1 for item in current) - min(item.bbox.y for item in current),
        )
        if abs(word.bbox.y - current_rect.y) <= max(current_rect.height, word.bbox.height) * 0.6:
            current.append(word)
        else:
            groups.append([word])
    return tuple(
        Rect(
            min(item.bbox.x for item in group),
            min(item.bbox.y for item in group),
            max(item.bbox.x1 for item in group) - min(item.bbox.x for item in group),
            max(item.bbox.y1 for item in group) - min(item.bbox.y for item in group),
        )
        for group in groups
    )


def select_query(result: DocumentResult, query: str, *, mode: MarkupMode = MarkupMode.SMART) -> tuple[MarkupSelection, ...]:
    wanted = _query_tokens(query)
    if not wanted:
        raise TextNotFoundError("text query is empty")

    selections: list[MarkupSelection] = []
    for page in result.pages:
        words = _canonical_words(page, mode)
        if not words:
            continue
        flattened: list[str] = []
        word_indices: list[int] = []
        for index, word in enumerate(words):
            parts = _token_parts(word.text)
            flattened.extend(parts)
            word_indices.extend([index] * len(parts))
        for start in range(0, len(flattened) - len(wanted) + 1):
            if tuple(flattened[start : start + len(wanted)]) != wanted:
                continue
            selected_indexes = tuple(dict.fromkeys(word_indices[start : start + len(wanted)]))
            selected_words = tuple(words[index] for index in selected_indexes)
            confidence = tuple(word.confidence for word in selected_words if word.confidence is not None)
            selections.append(
                MarkupSelection(
                    page_index=page.page_index,
                    matched_text=" ".join(word.text for word in selected_words),
                    word_ids=tuple(word.id for word in selected_words),
                    reading_order_start=start,
                    reading_order_end=start + len(wanted) - 1,
                    words=selected_words,
                    group_rects=_line_groups(selected_words),
                    source_type=selected_words[0].source_type,
                    confidence=confidence,
                    provenance=tuple(sorted({ref for word in selected_words for ref in word.provenance})),
                )
            )
    if not selections:
        if any(page.text.strip() for page in result.pages) and not any(page.tokens for page in result.pages):
            raise WordGeometryUnavailableError("canonical OCR result has no genuine word geometry")
        raise TextNotFoundError(f"text query was not found: {query[:80]}")
    return tuple(selections)


def select_regions(
    result: DocumentResult,
    boxes: list[dict[str, Any]],
    *,
    mode: MarkupMode = MarkupMode.SMART,
) -> tuple[MarkupSelection, ...]:
    """Resolve visible page rectangles against source-aware word geometry.

    Public boxes are always visible CropBox-relative rectangles.  Native
    PyMuPDF words remain in unrotated PDF coordinates, so only a native page's
    input rectangle is derotated for intersection.  OCR word boxes are already
    visible and pass through unchanged.
    """
    if mode is MarkupMode.MANUAL:
        raise ValueError("MarkupMode.MANUAL does not resolve canonical document words")
    selections: list[MarkupSelection] = []
    for box in boxes:
        try:
            page_index = int(box.get("page", 0)) - 1
            x = float(box.get("x", 0))
            y = float(box.get("y", 0))
            width = float(box.get("width", 0))
            height = float(box.get("height", 0))
        except (TypeError, ValueError):
            continue
        if page_index < 0 or page_index >= len(result.pages) or width <= 0 or height <= 0:
            continue
        page = result.pages[page_index]
        words = _canonical_words(page, mode)
        if not words:
            if page.text.strip() and "WORD_GEOMETRY" not in page.capabilities:
                raise WordGeometryUnavailableError("canonical OCR result has no genuine word geometry")
            continue
        region = Rect(x, y, width, height)
        if _source_type(page) is MarkupSourceType.NATIVE:
            region = visible_rect_to_native_pdf(region, page.geometry)
        selected = tuple(
            (index, word)
            for index, word in enumerate(words)
            if word.bbox.x < region.x1 and word.bbox.x1 > region.x and word.bbox.y < region.y1 and word.bbox.y1 > region.y
        )
        if not selected:
            continue
        selected_words = tuple(word for _, word in selected)
        selections.append(
            MarkupSelection(
                page_index=page_index,
                matched_text=" ".join(word.text for word in selected_words),
                word_ids=tuple(word.id for word in selected_words),
                reading_order_start=selected[0][0],
                reading_order_end=selected[-1][0],
                words=selected_words,
                group_rects=_line_groups(selected_words),
                source_type=selected_words[0].source_type,
                confidence=tuple(word.confidence for word in selected_words if word.confidence is not None),
                provenance=tuple(sorted({ref for word in selected_words for ref in word.provenance})),
            )
        )
    if not selections and any(page.text.strip() for page in result.pages):
        raise TextNotFoundError("no canonical words intersected the selected regions")
    return tuple(selections)


def _page_sources(result: DocumentResult) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "page_index": page.page_index,
            "source_type": _source_type(page).value,
            "classification": page.content_classification.value,
            "word_geometry": "WORD_GEOMETRY" in page.capabilities,
            "reading_order": "READING_ORDER" in page.capabilities,
        }
        for page in result.pages
    )


def _check(cancellation_check: Callable[[], None] | None) -> None:
    if cancellation_check:
        cancellation_check()


def _validate_result_for_pdf(result: DocumentResult, document: fitz.Document) -> None:
    """Fail closed when a supplied canonical result cannot describe this PDF."""
    if result.source.page_count != len(document) or len(result.pages) != len(document):
        raise ValueError("provided DocumentResult page coverage does not match the input PDF")
    if tuple(page.page_index for page in result.pages) != tuple(range(len(document))):
        raise ValueError("provided DocumentResult pages are not in canonical order")
    for index, result_page in enumerate(result.pages):
        page = document[index]
        geometry = PageGeometry(
            width=float(page.rect.width),
            height=float(page.rect.height),
            rotation=int(page.rotation) % 360,
        )
        if (
            abs(result_page.geometry.width - geometry.width) > 0.01
            or abs(result_page.geometry.height - geometry.height) > 0.01
            or result_page.geometry.rotation % 360 != geometry.rotation
            or result_page.geometry.coordinate_space != "pdf_points_visible_cropbox_top_left"
        ):
            raise ValueError("provided DocumentResult geometry is not compatible with the input PDF")


def _clipped_region(rect: Rect, geometry: PageGeometry) -> Rect | None:
    if rect.width <= 0 or rect.height <= 0:
        return None
    clipped = clamp_rect(rect, geometry)
    return clipped if clipped.width > 0 and clipped.height > 0 else None


def _empty_resolution(region_index: int, region: MarkupRegion, status: MarkupRegionStatus) -> ResolvedMarkupRegion:
    return ResolvedMarkupRegion(
        region_index=region_index,
        region_id=region.region_id,
        page_number=region.page_number,
        requested_rect=region.rect,
        resolved_rect=None,
        color=region.color,
        status=status,
    )


def _select_one_region(result: DocumentResult, region: MarkupRegion, clipped: Rect, mode: MarkupMode) -> MarkupSelection | None:
    try:
        selections = select_regions(
            result,
            [{"page": region.page_number, "x": clipped.x, "y": clipped.y, "width": clipped.width, "height": clipped.height}],
            mode=mode,
        )
    except TextNotFoundError:
        return None
    return selections[0] if selections else None


def _annotate_rect(page: fitz.Page, rect: Rect, action: MarkupAction, color: MarkupColor) -> None:
    try:
        annotation_rect = fitz.Rect(rect.x, rect.y, rect.x1, rect.y1)
        if action is MarkupAction.HIGHLIGHT:
            annotation = page.add_highlight_annot(annotation_rect)
        elif action is MarkupAction.UNDERLINE:
            annotation = page.add_underline_annot(annotation_rect)
        else:
            annotation = page.add_strikeout_annot(annotation_rect)
        if annotation is None:
            raise RuntimeError("PyMuPDF did not create the annotation")
        annotation.set_colors(stroke=color)
        annotation.update()
    except Exception as exc:
        raise AnnotationWriteError(f"could not write {action.value} annotation") from exc


def apply_region_markup(
    input_path: str | Path,
    output_path: str | Path,
    *,
    action: MarkupAction,
    regions: Sequence[MarkupRegion],
    mode: MarkupMode,
    result: DocumentResult | None = None,
    document_result_reused: bool = False,
    extraction_performed: bool = False,
    password: str | None = None,
    cancellation_check: Callable[[], None] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> RegionMarkupExecutionResult:
    """Resolve typed regions and write annotations without invoking OCR itself.

    Callers supply a canonical result for OCR-aware modes.  Manual mode does
    not need one and writes the clipped rectangles directly.
    """
    if mode is MarkupMode.MANUAL and result is not None:
        result = None
        document_result_reused = False
        extraction_performed = False
    if mode is not MarkupMode.MANUAL and result is None:
        raise ValueError("OCR-aware region markup requires a canonical DocumentResult")

    _check(cancellation_check)
    with fitz.open(str(input_path)) as document:
        page_count = len(document)
        if document.needs_pass and (not password or document.authenticate(password) <= 0):
            raise ValueError("PDF password authentication failed")
        if result is not None:
            _validate_result_for_pdf(result, document)

        resolved: list[ResolvedMarkupRegion] = []
        total = len(regions)
        for region_index, region in enumerate(regions):
            _check(cancellation_check)
            page_index = region.page_number - 1
            if page_index < 0 or page_index >= len(document):
                resolved.append(_empty_resolution(region_index, region, MarkupRegionStatus.OUT_OF_BOUNDS))
            else:
                page = document[page_index]
                geometry = PageGeometry(
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    rotation=int(page.rotation) % 360,
                )
                clipped = _clipped_region(region.rect, geometry)
                if clipped is None:
                    status = MarkupRegionStatus.EMPTY if region.rect.width <= 0 or region.rect.height <= 0 else MarkupRegionStatus.OUT_OF_BOUNDS
                    resolved.append(_empty_resolution(region_index, region, status))
                elif mode is MarkupMode.MANUAL:
                    _check(cancellation_check)
                    _annotate_rect(page, clipped, action, region.color)
                    resolved.append(
                        ResolvedMarkupRegion(
                            region_index=region_index,
                            region_id=region.region_id,
                            page_number=region.page_number,
                            requested_rect=region.rect,
                            resolved_rect=clipped,
                            color=region.color,
                            status=MarkupRegionStatus.ANNOTATED,
                            annotation_rects=(clipped,),
                            annotation_count=1,
                        )
                    )
                else:
                    selection = _select_one_region(result, region, clipped, mode)  # type: ignore[arg-type]
                    if selection is None:
                        resolved.append(
                            ResolvedMarkupRegion(
                                region_index=region_index,
                                region_id=region.region_id,
                                page_number=region.page_number,
                                requested_rect=region.rect,
                                resolved_rect=clipped,
                                color=region.color,
                                status=MarkupRegionStatus.NO_WORDS,
                            )
                        )
                    else:
                        _check(cancellation_check)
                        _annotate(page, selection, action, region.color)
                        resolved.append(
                            ResolvedMarkupRegion(
                                region_index=region_index,
                                region_id=region.region_id,
                                page_number=region.page_number,
                                requested_rect=region.rect,
                                resolved_rect=clipped,
                                color=region.color,
                                status=MarkupRegionStatus.ANNOTATED,
                                selection=selection,
                                annotation_rects=selection.group_rects,
                                annotation_count=1,
                            )
                        )
            if progress_callback:
                progress_callback(region_index + 1, total)
        _check(cancellation_check)
        document.save(str(output_path), garbage=4, deflate=True)

    return RegionMarkupExecutionResult(
        action=action,
        mode=mode,
        source_policy=(
            "MANUAL_RECTANGLES_NO_TEXT_EXTRACTION"
            if mode is MarkupMode.MANUAL
            else "CANONICAL_DOCUMENT_RESULT_REUSED" if document_result_reused else "EXTRACT_TEXT_ONCE_THEN_CANONICAL_REGION_SELECTION"
        ),
        output_path=str(Path(output_path)),
        page_count=len(result.pages) if result is not None else page_count,
        regions=tuple(resolved),
        page_sources=_page_sources(result) if result is not None else (),
        document_result_reused=document_result_reused,
        extraction_performed=extraction_performed,
    )


def _annotate(page: fitz.Page, selection: MarkupSelection, action: MarkupAction, color: tuple[float, float, float]) -> None:
    try:
        # PyMuPDF accepts rectangles here and converts them to axis-aligned
        # annotation quads while retaining the canonical PDF-point geometry.
        quads = [fitz.Rect(rect.x, rect.y, rect.x1, rect.y1) for rect in selection.group_rects]
        if action is MarkupAction.HIGHLIGHT:
            annotation = page.add_highlight_annot(quads)
        elif action is MarkupAction.UNDERLINE:
            annotation = page.add_underline_annot(quads)
        else:
            annotation = page.add_strikeout_annot(quads)
        if annotation is None:
            raise RuntimeError("PyMuPDF did not create the annotation")
        annotation.set_colors(stroke=color)
        annotation.update()
    except Exception as exc:
        raise AnnotationWriteError(f"could not write {action.value} annotation") from exc


def apply_ocr_markup(
    input_path: str | Path,
    output_path: str | Path,
    *,
    action: MarkupAction,
    query: str,
    language: str = "eng",
    language_mode: str | None = None,
    languages: Sequence[str] | None = None,
    language_usage: Mapping[str, float] | None = None,
    mode: MarkupMode = MarkupMode.SMART,
    color: tuple[float, float, float] = (1.0, 1.0, 0.0),
    cancellation_check: Callable[[], None] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> MarkupExecutionResult:
    """Run canonical OCR once, resolve all matches, then annotate the PDF."""
    if mode is MarkupMode.MANUAL:
        raise ValueError("MarkupMode.MANUAL is only supported by apply_markup_regions")
    worker = OCRV2Worker(route_policy=RoutePolicy(preferred_engine="tesseract_v2", fallback_engine="tesseract_v2"))
    result = worker.process_document(
        input_path,
        language=language,
        language_mode=language_mode,
        languages=languages,
        language_usage=language_usage,
        profile=OCRProfile.OCR_TEXT_V2,
        cancellation_check=cancellation_check,
        page_progress_callback=lambda done, total, _page: progress_callback(done, total) if progress_callback else None,
    )
    failed = next((page for page in result.pages if page.status.value == "FAILED"), None)
    if failed:
        if failed.failure_code == "EngineUnavailableError":
            raise EngineUnavailableError("OCR engine was unavailable while processing a markup page")
        if failed.failure_code == "OCRTimeoutError":
            raise OCRTimeoutError("OCR exceeded the markup page deadline")
        raise WordGeometryUnavailableError(f"OCR page {failed.page_index} did not produce selectable word geometry")
    selections = select_query(result, query, mode=mode)
    with fitz.open(str(input_path)) as document:
        for selection in selections:
            _annotate(document[selection.page_index], selection, action, color)
        document.save(str(output_path), garbage=4, deflate=True)
    page_sources = tuple(
        {
            "page_index": page.page_index,
            "source_type": _source_type(page).value,
            "classification": page.content_classification.value,
            "word_geometry": "WORD_GEOMETRY" in page.capabilities,
            "reading_order": "READING_ORDER" in page.capabilities,
        }
        for page in result.pages
    )
    return MarkupExecutionResult(
        action=action,
        mode=mode,
        source_policy="NATIVE_TRUSTED_ELSE_OCR_V2; MIXED_USES_SINGLE_OCR_SOURCE_TO_AVOID_DUPLICATES",
        page_count=len(result.pages),
        selections=selections,
        page_sources=page_sources,
    )
