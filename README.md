# platen-document

`platen-document` is a standalone local Python document-processing SDK copied
from PDFNest's proven local OCR V2 engine.

The first release is parity-focused. It is intentionally not an OCR-quality
redesign and does not change the current detector, structure heuristics,
geometry, rendering, or validation contracts.

## Included capabilities

- native PDF text extraction and conservative native/scanned routing;
- local Tesseract OCR with explicit languages and the current bounded AUTO
  policy;
- canonical word, line, block, reading-order, provenance, and validation
  results;
- structured-document extraction with the current bounded headings, lists,
  and simple-table behavior;
- Markdown rendering;
- searchable-PDF rendering with invisible text and independent validation;
- query-based and typed region-based Highlight, Underline, and Strikeout
  markup; and
- local capability inspection through `DocumentProcessor.capabilities()` or
  `platen-document doctor`.

## Minimal usage

```python
from platen_document import DocumentProcessor

processor = DocumentProcessor()
ocr_result = processor.extract_text("document.pdf")
structured = processor.extract_document("document.pdf")
markdown = processor.to_markdown(structured)
processor.make_searchable_pdf("scanned.pdf", "scanned-searchable.pdf")
```

Application adapters that need to preserve the canonical searchable-PDF
profile can use the public profile enum and pass an already extracted result to
the render step, avoiding a second OCR pass:

```python
from platen_document import DocumentProcessor, OCRProfile

processor = DocumentProcessor()
result = processor.extract_text("scanned.pdf", profile=OCRProfile.SEARCHABLE_PDF_V2)
processor.make_searchable_pdf(
    "scanned.pdf",
    "scanned-searchable.pdf",
    result=result,
    job_id="optional-diagnostic-correlation",
)
```

`extract_text` also accepts the copied worker's `routing_policy` plus optional
cooperative `cancellation_check`, `page_timeout_seconds`, and
`page_progress_callback` controls. These are thin engine controls for an
application adapter; the SDK still does not own application jobs or storage.
The default routing policy preserves validated native text when appropriate.
An application adapter with a historical OCR-only contract may opt into
`routing_policy="FORCE_OCR"`; this selects the OCR route without changing the
default behavior of existing consumers.

The package can process local files without PDFNest backend, PostgreSQL,
Redis, Dramatiq, frontend, HTTP services, authentication, billing, or
application storage.

## Region-based markup

`DocumentProcessor.apply_markup_regions` accepts typed, one-based page regions
in the existing visible CropBox-relative PDF-point coordinate space. Manual
regions annotate directly without OCR. OCR-aware regions can reuse a public
`DocumentResult` to avoid a second extraction pass, or perform one public
`extract_text` pass when no result is supplied. Per-region colors, cooperative
cancellation, and real annotation progress are supported. See
[the region markup API guide](docs/region_markup.md) for the full coordinate,
password, result, and overlap contract.

## Configuration and system dependencies

Python dependencies are declared in `pyproject.toml`. The runtime expects a
system Tesseract installation and discovers its executable, tessdata
directory, and installed language packs. It never installs operating-system
packages or downloads OCR models.

```python
from platen_document import DocumentProcessor, EngineConfiguration

processor = DocumentProcessor(EngineConfiguration(
    tesseract_binary="/usr/bin/tesseract",
    tessdata_dir="/usr/share/tesseract-ocr/5/tessdata",
))
```

The encoded OCR raster normally carries the configured DPI as PNG metadata.
An adapter that must reproduce a historical OCR input contract can opt into
the neutral public compatibility policy without changing rendered pixels:

```python
from platen_document import (
    DocumentProcessor,
    EngineConfiguration,
    RasterDpiMetadataPolicy,
)

processor = DocumentProcessor(EngineConfiguration(
    raster_dpi=144,
    raster_dpi_metadata_policy=RasterDpiMetadataPolicy.OMIT_DPI,
))
```

`EMBED_DPI` is the default. `OMIT_DPI` changes only the DPI metadata in the
encoded OCR image; it does not change raster dimensions, page geometry, or
the Tesseract language/routing policy. This option is intended for a
consumer-specific compatibility adapter, not for a product-wide environment
switch.

The copied engine retains its known tessdata fallback behavior, including
fallback from a stale `TESSDATA_PREFIX` when a known local system directory is
available.

## Diagnostics

```bash
platen-document doctor
```

The doctor output contains safe local capability metadata only. It does not
know about PDFNest users, guests, quotas, jobs, queues, storage providers, or
secrets.

## Boundary and current PDFNest consumer status

PDFNest authentication, anonymous ownership, quotas, rate limits, durable job
orchestration, storage policy, cleanup, product routes, and UI remain outside
this package. The following PDFNest consumers now have independent,
consumer-specific `internal|sdk` execution boundaries:

- OCR Text V2 (`OCR_TEXT_ENGINE`);
- Searchable PDF V2 (`SEARCHABLE_PDF_ENGINE`);
- Document Extraction V2 (`DOCUMENT_EXTRACTION_ENGINE`);
- PDF-to-Markdown V2 (`PDF_TO_MARKDOWN_ENGINE`);
- OCR-aware Highlight/Underline/Strikeout (`OCR_MARKUP_ENGINE`); and
- General Editor OCR (`EDITOR_OCR_ENGINE`).

Each selector defaults to `internal`; `sdk` is an explicit opt-in. The frozen
PDFNest implementation remains available as the default and configuration-only
rollback/reference path; there is no implicit runtime fallback from a selected
SDK engine. PDF-to-Word OCR fallback and Studio OCR/document paths remain
internal-only and are not migrated.

Registry delivery remains separately classified
`DOCUMENT_SDK_REGISTRY_DEPENDENCY_DELIVERY_BLOCKED_EXTERNAL`; no package has
been published to a public registry.
