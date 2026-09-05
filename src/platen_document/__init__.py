"""Standalone PDFNest document-processing SDK extraction."""

from .api import DocumentEngine, DocumentProcessor, EngineConfiguration, RasterDpiMetadataPolicy
from .engine.errors import (
    AnnotationWriteError,
    AmbiguousSelectionError,
    EngineUnavailableError,
    MarkupError,
    OCRCancellationError,
    OCRTimeoutError,
    TextNotFoundError,
    WordGeometryUnavailableError,
)
from .engine.contracts import DocumentResult, PageGeometry, Rect
from .engine.markup import (
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
)
from .engine.validation import OCRProfile

__all__ = [
    "AnnotationWriteError",
    "AmbiguousSelectionError",
    "DocumentEngine",
    "DocumentProcessor",
    "DocumentResult",
    "EngineConfiguration",
    "RasterDpiMetadataPolicy",
    "EngineUnavailableError",
    "MarkupAction",
    "MarkupColor",
    "MarkupError",
    "MarkupExecutionResult",
    "MarkupMode",
    "MarkupRegion",
    "MarkupRegionStatus",
    "MarkupSelection",
    "MarkupSourceType",
    "OCRTimeoutError",
    "OCRProfile",
    "OCRCancellationError",
    "Rect",
    "PageGeometry",
    "RegionMarkupExecutionResult",
    "ResolvedMarkupRegion",
    "TextNotFoundError",
    "WordGeometryUnavailableError",
]
