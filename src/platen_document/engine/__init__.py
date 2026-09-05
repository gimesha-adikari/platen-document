"""Copied, parity-preserving PDFNest OCR V2 engine namespace."""

from .contracts import *
from .geometry import PreparedRaster, RasterDpiMetadataPolicy, RasterPreparer, normalize_rotation, page_geometry_from_pdf, pixel_rect_to_points
from .image_pages import build_image_source_pdf, normalize_image
from .language_policy import *
from .native import NativeDecision, NativeExtractor, NativeValidator
from .orchestration import OCRV2Worker
from .profiles import product_verdict, searchable_pdf_reason
from .routing import OCRRouter, RoutePlan, RoutePolicy
from .structured import StructuredDocumentProcessor, StructuredDocumentResult, StructuredElement, StructuredElementType, StructuredPage, render_structured_markdown
from .validation import OCRProfile, profile_disposition, require_profile, validate_document, validate_page
from .markup import (
    MarkupAction,
    MarkupColor,
    MarkupExecutionResult,
    MarkupMode,
    MarkupRegion,
    MarkupRegionStatus,
    MarkupSelection,
    MarkupSourceType,
    RegionMarkupExecutionResult,
    ResolvedMarkupRegion,
    apply_ocr_markup,
    apply_region_markup,
    select_query,
    select_regions,
)

__all__ = [
    "OCRV2Worker", "StructuredDocumentProcessor", "StructuredDocumentResult",
    "StructuredElement", "StructuredElementType", "StructuredPage",
    "render_structured_markdown", "OCRProfile", "RoutePolicy", "OCRRouter",
    "MarkupAction", "MarkupExecutionResult", "MarkupMode", "MarkupSelection",
    "MarkupSourceType", "MarkupColor", "MarkupRegion", "MarkupRegionStatus",
    "ResolvedMarkupRegion", "RegionMarkupExecutionResult", "apply_ocr_markup",
    "apply_region_markup", "select_query", "select_regions",
    "RasterDpiMetadataPolicy",
]
