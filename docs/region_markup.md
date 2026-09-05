# Region-based markup API

`DocumentProcessor.apply_markup_regions` adds typed, local PDF markup for
explicit page rectangles. It is independent of application storage, sessions,
jobs, and UI.

```python
from platen_document import (
    DocumentProcessor,
    MarkupAction,
    MarkupMode,
    MarkupRegion,
    Rect,
)

processor = DocumentProcessor()
result = processor.apply_markup_regions(
    "input.pdf",
    "output.pdf",
    action=MarkupAction.HIGHLIGHT,
    mode=MarkupMode.MANUAL,
    regions=(
        MarkupRegion(
            page_number=1,
            rect=Rect(x=72, y=144, width=180, height=18),
            region_id="review-note-7",
            color=(1.0, 0.85, 0.0),
        ),
    ),
)
```

## Coordinate and page contract

`MarkupRegion.page_number` is one-based. `MarkupRegion.rect` uses PDF points,
the visible CropBox, a top-left origin, X increasing right, and Y increasing
down. This is the same canonical coordinate space recorded in
`PageGeometry.coordinate_space` as
`pdf_points_visible_cropbox_top_left`. `PageGeometry.rotation` describes the
visible page orientation; callers must provide the rectangle in that visible
orientation. Region rectangles are clipped to the visible page. Zero or
negative-area rectangles resolve as `EMPTY`; rectangles with no visible area
or a page number beyond the PDF resolve as `OUT_OF_BOUNDS`. Page numbers below
one are rejected when constructing `MarkupRegion`.

## Modes and OCR work

`MarkupMode.MANUAL` annotates each clipped input rectangle directly. It does
not call text extraction, OCR, indexing, or any background process.

`SMART`, `OCR`, and `NATIVE` are OCR-aware modes. They resolve canonical words
that intersect a region, preserve canonical reading order and word IDs, group
the selected words into line-level rectangles, then write a highlight,
underline, or strikeout annotation. Each input region is independent, so
overlapping regions intentionally retain separate resolutions and annotations.

Pass a compatible public `DocumentResult` to avoid a second extraction pass:

```python
document = processor.extract_text("input.pdf", language="eng")
marked = processor.apply_markup_regions(
    "input.pdf",
    "output.pdf",
    action="underline",
    regions=(MarkupRegion(1, Rect(72, 144, 180, 18)),),
    result=document,
)
```

The SDK verifies supplied-result page coverage, canonical page order, visible
page dimensions, rotation, and coordinate-space label before reuse. It cannot
prove content identity without an application-owned source identity, so the
caller must ensure that the result belongs to the same input artifact.

Without a supplied result, an OCR-aware call performs exactly one public
`extract_text` invocation with the passed password, language, routing policy,
cancellation check, page timeout, and page-progress callback.

## Results, colors, cancellation, and progress

`RegionMarkupExecutionResult` exposes the output path, total annotation count,
per-region `ResolvedMarkupRegion` outcomes, selected text, canonical word IDs,
line-level annotation rectangles, and the supplied-result/extraction flags.
Each `MarkupRegion` has its own RGB float color tuple in the inclusive range
`0.0..1.0`.

`cancellation_check` is called before work, between region resolutions,
before annotation writes, and before saving. A cancellation exception raised
by the caller is propagated. `page_progress_callback` is passed only to the
single extraction when one occurs. `progress_callback(done, total)` reports
completed region work; it does not fabricate OCR progress when a supplied
result or manual mode avoids OCR.

Password-protected PDFs use the same controlled password failure as
`extract_text`: a missing or incorrect password raises `ValueError("PDF
password authentication failed")`.

The existing query-based `DocumentProcessor.apply_markup` remains available
and unchanged. `MarkupMode.MANUAL` is meaningful only for
`apply_markup_regions`.
