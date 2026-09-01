"""Standalone PDFNest document-processing SDK extraction."""

from .api import DocumentEngine, DocumentProcessor, EngineConfiguration
from .engine.errors import (
    AnnotationWriteError,
    AmbiguousSelectionError,
    EngineUnavailableError,
    MarkupError,
    OCRTimeoutError,
    TextNotFoundError,
    WordGeometryUnavailableError,
)
from .engine.markup import MarkupAction, MarkupExecutionResult, MarkupMode, MarkupSelection, MarkupSourceType
from .engine.validation import OCRProfile

__all__ = [
    "AnnotationWriteError",
    "AmbiguousSelectionError",
    "DocumentEngine",
    "DocumentProcessor",
    "EngineConfiguration",
    "EngineUnavailableError",
    "MarkupAction",
    "MarkupError",
    "MarkupExecutionResult",
    "MarkupMode",
    "MarkupSelection",
    "MarkupSourceType",
    "OCRTimeoutError",
    "OCRProfile",
    "TextNotFoundError",
    "WordGeometryUnavailableError",
]
