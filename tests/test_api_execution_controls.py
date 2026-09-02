from __future__ import annotations

from types import SimpleNamespace

import pytest

from platen_document.api.engine import DocumentProcessor
from platen_document.engine.contracts import PageContentClassification
from platen_document.engine.native import NativeDecision, NativeValidationResult
from platen_document.engine.routing import OCRRouter, RoutePolicy
from platen_document import MarkupAction, MarkupMode
import platen_document.api.engine as engine_module


class _FakeWorker:
    def __init__(self) -> None:
        self.calls: dict[str, object] = {}
        self.result = object()

    def process_document(self, path: str, **kwargs: object) -> object:
        self.calls["path"] = path
        self.calls.update(kwargs)
        return self.result


class _FakeStructuredProcessor:
    def __init__(self) -> None:
        self.calls: dict[str, object] = {}
        self.result = object()

    def process_document(self, path: str, **kwargs: object) -> object:
        self.calls["path"] = path
        self.calls.update(kwargs)
        return self.result


def _processor(worker: _FakeWorker) -> DocumentProcessor:
    processor = DocumentProcessor.__new__(DocumentProcessor)
    processor.config = SimpleNamespace(max_raster_pixels=None)
    processor._ocr_worker = worker
    return processor


def test_extract_text_preserves_lifecycle_controls_on_default_route() -> None:
    worker = _FakeWorker()
    processor = _processor(worker)
    cancel = lambda: None
    progress = lambda _done, _total, _page: None

    result = processor.extract_text(
        "/tmp/input.pdf",
        password="document-password",
        language="auto",
        language_mode="AUTO",
        languages=("eng", "sin"),
        language_usage={"sin": 0.5},
        cancellation_check=cancel,
        page_timeout_seconds=9.0,
        page_progress_callback=progress,
    )

    assert result is worker.result
    assert worker.calls["path"] == "/tmp/input.pdf"
    assert worker.calls["password"] == "document-password"
    assert worker.calls["language"] == "auto"
    assert worker.calls["language_mode"] == "AUTO"
    assert worker.calls["languages"] == ("eng", "sin")
    assert worker.calls["language_usage"] == {"sin": 0.5}
    assert worker.calls["profile"].value == "OCR_TEXT_V2"
    assert worker.calls["cancellation_check"] is cancel
    assert worker.calls["page_timeout_seconds"] == 9.0
    assert worker.calls["page_progress_callback"] is progress


def test_extract_text_selects_non_default_route_policy() -> None:
    default_worker = _FakeWorker()
    selected_worker = _FakeWorker()
    processor = _processor(default_worker)
    created: dict[str, object] = {}

    def make_worker(max_raster_pixels: int | None, routing_policy: str = "AUTO") -> _FakeWorker:
        created["max_raster_pixels"] = max_raster_pixels
        created["routing_policy"] = routing_policy
        return selected_worker

    processor._make_worker = make_worker  # type: ignore[method-assign]

    result = processor.extract_text("/tmp/input.pdf", routing_policy="FAST")

    assert result is selected_worker.result
    assert created == {"max_raster_pixels": None, "routing_policy": "FAST"}


def test_force_ocr_route_disables_native_shortcut_without_changing_default() -> None:
    assert engine_module._route_policy(None) == RoutePolicy()
    assert engine_module._route_policy("FORCE_OCR") == RoutePolicy(
        preferred_engine="tesseract_v2",
        fallback_engine="tesseract_v2",
        allow_native=False,
    )


def test_force_ocr_route_reaches_ocr_for_trusted_native_pages() -> None:
    adapters = {"tesseract_v2": object()}
    decision = NativeValidationResult(
        NativeDecision.TRUST_NATIVE,
        PageContentClassification.TEXT_NATIVE,
    )

    plan = OCRRouter(
        adapters,
        RoutePolicy(
            preferred_engine="tesseract_v2",
            fallback_engine="tesseract_v2",
            allow_native=False,
        ),
    ).plan(decision, profile=engine_module.OCRProfile.OCR_TEXT_V2)

    assert plan.action == "OCR"
    assert plan.engine_id == "tesseract_v2"


def test_extract_text_selects_force_ocr_route_policy() -> None:
    default_worker = _FakeWorker()
    selected_worker = _FakeWorker()
    processor = _processor(default_worker)
    created: dict[str, object] = {}

    def make_worker(max_raster_pixels: int | None, routing_policy: str = "AUTO") -> _FakeWorker:
        created["max_raster_pixels"] = max_raster_pixels
        created["routing_policy"] = routing_policy
        return selected_worker

    processor._make_worker = make_worker  # type: ignore[method-assign]

    result = processor.extract_text("/tmp/input.pdf", routing_policy="FORCE_OCR")

    assert result is selected_worker.result
    assert created == {"max_raster_pixels": None, "routing_policy": "FORCE_OCR"}


def test_extract_text_rejects_unknown_routing_policy() -> None:
    processor = _processor(_FakeWorker())

    with pytest.raises(ValueError, match="unsupported OCR routing policy"):
        processor.extract_text("/tmp/input.pdf", routing_policy="UNKNOWN")


def test_extract_document_preserves_lifecycle_controls() -> None:
    worker = _FakeWorker()
    structured = _FakeStructuredProcessor()
    processor = _processor(worker)
    processor._structured_processor = structured  # type: ignore[attr-defined]
    cancel = lambda: None
    progress = lambda _done, _total, _page: None

    result = processor.extract_document(
        "/tmp/input.pdf",
        language="auto",
        language_mode="AUTO",
        languages=("eng", "sin"),
        language_usage={"sin": 0.5},
        routing_policy="AUTO",
        cancellation_check=cancel,
        page_progress_callback=progress,
    )

    assert result is structured.result
    assert structured.calls["path"] == "/tmp/input.pdf"
    assert structured.calls["language"] == "auto"
    assert structured.calls["language_mode"] == "AUTO"
    assert structured.calls["languages"] == ("eng", "sin")
    assert structured.calls["language_usage"] == {"sin": 0.5}
    assert structured.calls["routing_policy"] == "AUTO"
    assert structured.calls["cancellation_check"] is cancel
    assert structured.calls["page_progress_callback"] is progress


def test_apply_markup_public_api_maps_strings_to_canonical_markup_types(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    marker = object()

    def apply_markup(input_path: str, output_path: str, **kwargs: object) -> object:
        calls["input_path"] = input_path
        calls["output_path"] = output_path
        calls.update(kwargs)
        return marker

    monkeypatch.setattr(engine_module, "apply_ocr_markup", apply_markup)
    processor = DocumentProcessor.__new__(DocumentProcessor)
    cancel = lambda: None
    progress = lambda _done, _total: None

    result = processor.apply_markup(
        "/tmp/input.pdf",
        "/tmp/output.pdf",
        action="underline",
        query="Alpha Bravo",
        language="eng+sin",
        language_mode="EXPLICIT",
        languages=("eng", "sin"),
        language_usage={"sin": 0.5},
        mode="ocr",
        color=(0.1, 0.2, 0.3),
        cancellation_check=cancel,
        progress_callback=progress,
    )

    assert result is marker
    assert calls["input_path"] == "/tmp/input.pdf"
    assert calls["output_path"] == "/tmp/output.pdf"
    assert calls["action"] is MarkupAction.UNDERLINE
    assert calls["mode"] is MarkupMode.OCR
    assert calls["query"] == "Alpha Bravo"
    assert calls["language"] == "eng+sin"
    assert calls["language_mode"] == "EXPLICIT"
    assert calls["languages"] == ("eng", "sin")
    assert calls["language_usage"] == {"sin": 0.5}
    assert calls["color"] == (0.1, 0.2, 0.3)
    assert calls["cancellation_check"] is cancel
    assert calls["progress_callback"] is progress
