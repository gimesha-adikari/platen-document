from __future__ import annotations

from types import SimpleNamespace

import pytest

from platen_document.api.engine import DocumentProcessor


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
