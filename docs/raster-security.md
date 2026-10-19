# Raster admission security contract

The proposed 0.1.9 patch enforces admission before SDK PDF rasterization.
This is source hardening for F-11, not a claim that F-11 is fully closed.

## Mandatory policy

- At most **10,000,000 conservative estimated pixels** per raster.
- Integer DPI from **1 through 600**, retaining the **200 DPI** OCR default.
- At most **32,768 pixels** on either conservative estimated axis.
- Finite, ordered, positive visible page/clip rectangles. Absolute input and
  scaled coordinates are bounded to 1,048,576 to keep native conversions and
  float32 precision within the estimator's guard.
- Missing optional limits use the ceiling; larger limits are capped. Smaller
  positive global, structured, preparer and active-context limits combine by
  minimum. Explicit malformed raster settings raise `ConfigurationError`.

The estimator uses the visible, already rotated `page.rect`, an unshifted
uniform DPI matrix, and an optional visible-coordinate clip intersection.
It rounds endpoint minima down and maxima up, then reserves one extra pixel
on each edge. That guard exceeds MuPDF's 1e-3 rounding tolerance and float32
error within the bounded coordinate range. The conservative dimensions can
reject a raster whose eventual observed dimensions would fit exactly.
No automatic downsampling or engine fallback is performed on rejection.

`render_page_pixmap` is the sole SDK `get_pixmap` boundary. It checks cancellation
before rendering and immediately after return, checks actual dimensions before
encoding/PIL, and rejects actual dimensions exceeding the admitted bounds.
Actual raster dimensions still drive OCR coordinate mapping and DPI metadata
policy remains unchanged.

Worker policy travels through a scoped `ContextVar`, retaining the existing
`prepare(page)` calling convention, including adapters that delegate to
`RasterPreparer`. Injected Python preparers are trusted application code: code
that implements its own native renderer must use the guarded helper itself.
This policy is not a sandbox against arbitrary Python code.

## Failure and artifacts

`RasterAdmissionError` and raster `ConfigurationError` escape page-error
conversion and abort the document, including page subsets and documents with
previous progress. Structured projection retains unrelated failed OCR pages as
`FAILED` with invalid validation instead of manufacturing blank/success status.

Searchable metadata performs admission and reports conservative estimates in
`raster_width`/`raster_height`, with `raster_dimensions_estimated: true`; it no
longer rasterizes for diagnostics. Visual validation admits source and output
independently before either raster allocation, compares their pixels, and
releases both pixmaps per page. Searchable output is staged beside the target
and atomically replaced only after validation. Failure removes only the owned
staging file and preserves an existing target.

## Compatibility and remaining risk

Standard A4/Letter at 200 and 300 DPI remain admissible. Large scans, unusually
long/narrow pages, extreme coordinate offsets, DPI over 600, fractional DPI and
inputs previously admitted under 25-million-pixel settings can now reject.
An uploaded image's decoded pixel allowance is distinct from the OCR raster
budget: placing an image at 150 DPI then rendering at 200 DPI increases its
raster area by approximately 1.78 times. Invalid explicit environment values
now fail configuration rather than silently falling back.

Output pixels do not bound PDF parsing, embedded image/font decoding,
transparency/display lists, encoder/PIL copies, OCR model allocations or
concurrent workloads. Native rendering still runs in the calling process and
cannot reliably be preempted by cooperative cancellation or a post-work timeout.
Resource-limited, killable native execution remains open. Worker raster paths
and F-12 render-session limits/cache/event-loop behavior remain separate work.

## Focused qualification

Run fake-page tests first (`tests/test_raster_admission.py -k 'not small_native'`).
Hostile geometry tests never render a large page. Then run the small native
crop/rotation cases and selected metadata, API lifecycle, structured, searchable
and markup fixtures sequentially. Use time/address-space limits and disable
automatic pytest plugins; do not use large parity fixtures or stress workloads.
The release workflow does not run on pull requests; source qualification must
be reviewed independently before any later release authorization.
