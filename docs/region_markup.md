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

The public input space is deliberately distinct from the source geometry used
for word intersection:

| Space | Meaning |
| --- | --- |
| Visible region | The caller's rotated CropBox-relative rectangle, top-left origin, X right, Y down. |
| Native word geometry | PyMuPDF `page.get_text("words")` boxes in unrotated CropBox-relative PDF coordinates. |
| OCR word geometry | Raster/OCR boxes in the visible rotated CropBox-relative space. |
| Annotation geometry | Canonical unrotated PDF coordinates consumed by PyMuPDF annotation writers. |

For native pages, the selector maps the visible region through the page
rotation into native PDF space before intersecting native words. The selected
native word boxes are already in annotation space, so they are written without
a second transform. For OCR/scanned pages, the existing visible OCR boxes and
selection behavior are preserved for region intersection. After selection,
those visible OCR and hybrid line rectangles are mapped exactly once into
native annotation coordinates at the PyMuPDF writer boundary. This keeps the
public region contract visible-space while ensuring the generated annotation
is placed in the unrotated PDF space. Callers must not add a frontend rotation
or derotation.

For a page with visible width `W`, visible height `H`, and rectangle
`(x, y, width, height)`, the native mapping is:

- 0°: `(x, y, width, height)`;
- 90°: `(y, W - (x + width), height, width)`;
- 180°: `(W - (x + width), H - (y + height), width, height)`; and
- 270°: `(H - (y + height), x, height, width)`.

These mappings correspond to PyMuPDF's `rotation_matrix` and
`derotation_matrix` for the visible `page.rect`; they also work with a
non-zero CropBox because the SDK geometry is CropBox-relative. Version 0.1.1
uses this mapping for native word intersection, version 0.1.2 also uses it at
the manual annotation-writer boundary, and OCR/hybrid selection annotations
use the same mapping at the annotation-writer boundary. In every
source-aware path the conversion occurs exactly once.

## Modes and OCR work

`MarkupMode.MANUAL` annotates each clipped input rectangle without calling text
extraction, OCR, indexing, or any background process. The visible input is
mapped exactly once into canonical unrotated PDF coordinates at the PyMuPDF
annotation boundary, including for rotated pages.

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
