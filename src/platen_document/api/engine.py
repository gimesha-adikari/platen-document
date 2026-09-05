"""Thin public API over the extracted document-processing engine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from ..diagnostics.doctor import build_doctor_report
from ..engine.adapters import PPOCRv6MediumAdapter, TesseractAdapter
from ..engine.geometry import RasterDpiMetadataPolicy, RasterPreparer
from ..engine.markup import (
    MarkupAction,
    MarkupExecutionResult,
    MarkupMode,
    MarkupRegion,
    RegionMarkupExecutionResult,
    apply_ocr_markup,
    apply_region_markup,
)
from ..engine.orchestration import OCRV2Worker
from ..engine.renderers import SearchablePdfRenderer, TextRenderer
from ..engine.routing import RoutePolicy
from ..engine.structured import (
    StructuredDocumentProcessor,
    StructuredDocumentResult,
    render_structured_markdown,
    structured_max_raster_pixels,
)
from ..engine.validation import OCRProfile
from ..engine.contracts import DocumentResult


@dataclass(frozen=True)
class EngineConfiguration:
    """Optional local engine settings.

    Defaults intentionally follow the copied PDFNest worker behavior.  The
    SDK does not install system packages or fetch OCR models.
    """

    tesseract_binary: str | None = None
    tessdata_dir: str | None = None
    tesseract_timeout: float = 300.0
    raster_dpi: int = 200
    raster_dpi_metadata_policy: RasterDpiMetadataPolicy = RasterDpiMetadataPolicy.EMBED_DPI
    max_raster_pixels: int | None = None
    structured_max_raster_pixels: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "raster_dpi_metadata_policy",
            RasterDpiMetadataPolicy.coerce(self.raster_dpi_metadata_policy),
        )

    @classmethod
    def from_env(cls) -> "EngineConfiguration":
        """Read only neutral engine settings from the process environment."""
        timeout = _positive_float(os.getenv("PLATEN_DOCUMENT_TESSERACT_TIMEOUT"), 300.0)
        dpi = _positive_int(os.getenv("PLATEN_DOCUMENT_RASTER_DPI"), 200)
        max_pixels = _optional_positive_int(os.getenv("PLATEN_DOCUMENT_MAX_RASTER_PIXELS"))
        structured_pixels = _optional_positive_int(os.getenv("PLATEN_DOCUMENT_STRUCTURED_MAX_RASTER_PIXELS"))
        return cls(
            tesseract_binary=os.getenv("TESSERACT_BINARY") or None,
            tessdata_dir=os.getenv("TESSDATA_PREFIX") or None,
            tesseract_timeout=timeout,
            raster_dpi=dpi,
            max_raster_pixels=max_pixels,
            structured_max_raster_pixels=structured_pixels,
        )


def _positive_float(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_int(raw: str | None, default: int) -> int:
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def _optional_positive_int(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _route_policy(value: str | object | None) -> RoutePolicy:
    """Translate the PDFNest-facing routing name to the copied engine policy."""
    raw = getattr(value, "value", value)
    normalized = str(raw or "AUTO").strip().upper()
    if normalized in {"FAST", "LANGUAGE_FALLBACK"}:
        return RoutePolicy(preferred_engine="tesseract_v2", fallback_engine="tesseract_v2")
    if normalized == "FORCE_OCR":
        return RoutePolicy(
            preferred_engine="tesseract_v2",
            fallback_engine="tesseract_v2",
            allow_native=False,
        )
    if normalized in {"AUTO", "QUALITY", "GEOMETRY"}:
        return RoutePolicy(preferred_engine="ppocrv6_medium_v2", fallback_engine="tesseract_v2")
    raise ValueError(f"unsupported OCR routing policy: {normalized}")


class DocumentProcessor:
    """Process local PDF files without PDFNest application infrastructure."""

    def __init__(self, config: EngineConfiguration | None = None) -> None:
        self.config = config or EngineConfiguration.from_env()
        self._ocr_worker = self._make_worker(self.config.max_raster_pixels)
        structured_limit = self.config.structured_max_raster_pixels
        if structured_limit is None:
            structured_limit = structured_max_raster_pixels()
        self._structured_processor = StructuredDocumentProcessor(
            ocr_worker=self._make_worker(structured_limit)
        )
        self._text_renderer = TextRenderer()
        self._searchable_pdf_renderer = SearchablePdfRenderer()

    def _make_worker(self, max_raster_pixels: int | None, routing_policy: str = "AUTO") -> OCRV2Worker:
        tesseract = TesseractAdapter(
            "eng",
            timeout=self.config.tesseract_timeout,
            tessdata_dir=self.config.tessdata_dir,
            tesseract_binary=self.config.tesseract_binary,
        )
        return OCRV2Worker(
            adapters={
                "tesseract_v2": tesseract,
                "ppocrv6_medium_v2": PPOCRv6MediumAdapter(),
            },
            raster_preparer=RasterPreparer(
                self.config.raster_dpi,
                dpi_metadata_policy=self.config.raster_dpi_metadata_policy,
            ),
            route_policy=_route_policy(routing_policy),
            max_raster_pixels=max_raster_pixels,
        )

    def extract_text(
        self,
        pdf_path: str | Path,
        *,
        password: str | None = None,
        language: str = "eng",
        language_mode: str | None = None,
        languages: Sequence[str] | None = None,
        language_usage: Mapping[str, float] | None = None,
        profile: OCRProfile = OCRProfile.OCR_TEXT_V2,
        routing_policy: str = "AUTO",
        cancellation_check: Callable[[], None] | None = None,
        page_timeout_seconds: float | None = None,
        page_progress_callback: Callable[[int, int, object], None] | None = None,
    ) -> DocumentResult:
        """Return the copied canonical OCR result for a local PDF.

        ``routing_policy`` and the lifecycle callbacks are thin pass-throughs
        for application consumers that need the same route and cooperative
        cancellation contract as the original worker.  They do not add
        PDFNest job or storage concerns to the SDK.
        """
        selected_policy = _route_policy(routing_policy)
        worker = self._ocr_worker if selected_policy == RoutePolicy() else self._make_worker(self.config.max_raster_pixels, routing_policy)
        return worker.process_document(
            pdf_path,
            password=password,
            language=language,
            language_mode=language_mode,
            languages=languages,
            language_usage=language_usage,
            profile=profile,
            cancellation_check=cancellation_check,
            page_timeout_seconds=page_timeout_seconds,
            page_progress_callback=page_progress_callback,
        )

    def extract_document(
        self,
        pdf_path: str | Path,
        *,
        language: str = "eng",
        language_mode: str | None = None,
        languages: Sequence[str] | None = None,
        language_usage: Mapping[str, float] | None = None,
        routing_policy: str = "AUTO",
        cancellation_check: Callable[[], None] | None = None,
        page_progress_callback: Callable[[int, int, object], None] | None = None,
    ) -> StructuredDocumentResult:
        """Return the copied canonical structured-document result.

        The callbacks are thin lifecycle pass-throughs for application
        consumers.  They keep cancellation and per-page progress outside the
        SDK while preserving the structured processor's existing behavior.
        """
        return self._structured_processor.process_document(
            pdf_path,
            language=language,
            language_mode=language_mode,
            languages=languages,
            language_usage=language_usage,
            routing_policy=routing_policy,
            cancellation_check=cancellation_check,
            page_progress_callback=page_progress_callback,
        )

    def to_markdown(
        self,
        source_or_result: str | Path | StructuredDocumentResult,
        *,
        emit_page_breaks: bool = True,
    ) -> str:
        """Render a structured result, or extract one from a local PDF first."""
        result = (
            source_or_result
            if isinstance(source_or_result, StructuredDocumentResult)
            else self.extract_document(source_or_result)
        )
        return render_structured_markdown(result, emit_page_breaks=emit_page_breaks)

    def extract_markdown(
        self,
        pdf_path: str | Path,
        *,
        emit_page_breaks: bool = True,
        language: str = "eng",
        language_mode: str | None = None,
        languages: Sequence[str] | None = None,
    ) -> str:
        """Convenience alias for structured extraction followed by Markdown."""
        result = self._structured_processor.process_document(
            pdf_path,
            language=language,
            language_mode=language_mode,
            languages=languages,
        )
        return render_structured_markdown(result, emit_page_breaks=emit_page_breaks)

    def make_searchable_pdf(
        self,
        source_pdf: str | Path,
        output_pdf: str | Path,
        *,
        language: str = "eng",
        language_mode: str | None = None,
        languages: Sequence[str] | None = None,
        language_usage: Mapping[str, float] | None = None,
        result: DocumentResult | None = None,
        job_id: str | None = None,
    ) -> DocumentResult:
        """Create and independently validate a searchable PDF from a PDF.

        ``job_id`` is an optional diagnostic correlation value for application
        consumers. It is not persisted in the document or used for ownership.
        """
        checked = result or self.extract_text(
            source_pdf,
            language=language,
            language_mode=language_mode,
            languages=languages,
            language_usage=language_usage,
            profile=OCRProfile.SEARCHABLE_PDF_V2,
        )
        self._searchable_pdf_renderer.render(source_pdf, checked, output_pdf, job_id=job_id)
        return checked

    def apply_markup(
        self,
        input_path: str | Path,
        output_path: str | Path,
        *,
        action: MarkupAction | str,
        query: str,
        language: str = "eng",
        language_mode: str | None = None,
        languages: Sequence[str] | None = None,
        language_usage: Mapping[str, float] | None = None,
        mode: MarkupMode | str = MarkupMode.SMART,
        color: tuple[float, float, float] = (1.0, 1.0, 0.0),
        cancellation_check: Callable[[], None] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> MarkupExecutionResult:
        """Apply one OCR-aware markup operation to a local PDF.

        This is a deliberately thin public wrapper around the extracted
        markup engine.  It accepts the string values used by application
        consumers while retaining the canonical SDK enums and result schema.
        PDFNest owns storage, jobs, authorization, and lifecycle concerns.
        """
        selected_action = action if isinstance(action, MarkupAction) else MarkupAction(str(action))
        selected_mode = mode if isinstance(mode, MarkupMode) else MarkupMode(str(mode))
        return apply_ocr_markup(
            input_path,
            output_path,
            action=selected_action,
            query=query,
            language=language,
            language_mode=language_mode,
            languages=languages,
            language_usage=language_usage,
            mode=selected_mode,
            color=color,
            cancellation_check=cancellation_check,
            progress_callback=progress_callback,
        )

    def apply_markup_regions(
        self,
        input_path: str | Path,
        output_path: str | Path,
        *,
        action: MarkupAction | str,
        regions: Sequence[MarkupRegion],
        mode: MarkupMode | str = MarkupMode.SMART,
        result: DocumentResult | None = None,
        password: str | None = None,
        language: str = "eng",
        language_mode: str | None = None,
        languages: Sequence[str] | None = None,
        language_usage: Mapping[str, float] | None = None,
        routing_policy: str = "AUTO",
        cancellation_check: Callable[[], None] | None = None,
        page_timeout_seconds: float | None = None,
        page_progress_callback: Callable[[int, int, object], None] | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> RegionMarkupExecutionResult:
        """Apply markup to typed page rectangles using canonical PDF geometry.

        ``MarkupMode.MANUAL`` writes the supplied rectangles directly and never
        extracts text.  OCR-aware modes either reuse a compatible public
        :class:`DocumentResult` or make exactly one ``extract_text`` call.
        ``MarkupRegion.page_number`` is one-based; its rectangle is in visible
        CropBox-relative PDF points with a top-left origin.
        """
        selected_action = action if isinstance(action, MarkupAction) else MarkupAction(str(action))
        selected_mode = mode if isinstance(mode, MarkupMode) else MarkupMode(str(mode))
        selected_regions = tuple(regions)
        reused = selected_mode is not MarkupMode.MANUAL and result is not None
        extracted = False
        canonical_result = result
        if selected_mode is not MarkupMode.MANUAL and canonical_result is None:
            canonical_result = self.extract_text(
                input_path,
                password=password,
                language=language,
                language_mode=language_mode,
                languages=languages,
                language_usage=language_usage,
                profile=OCRProfile.OCR_TEXT_V2,
                routing_policy=routing_policy,
                cancellation_check=cancellation_check,
                page_timeout_seconds=page_timeout_seconds,
                page_progress_callback=page_progress_callback,
            )
            extracted = True
        return apply_region_markup(
            input_path,
            output_path,
            action=selected_action,
            regions=selected_regions,
            mode=selected_mode,
            result=canonical_result,
            document_result_reused=reused,
            extraction_performed=extracted,
            password=password,
            cancellation_check=cancellation_check,
            progress_callback=progress_callback,
        )

    def render_text(self, result: DocumentResult) -> str:
        """Render validated canonical OCR text without application concerns."""
        return self._text_renderer.render(result)

    def capabilities(self) -> dict[str, object]:
        """Return safe local capability information for this processor."""
        return build_doctor_report(self.config)


DocumentEngine = DocumentProcessor
