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
processor.make_searchable_pdf("scanned.pdf", "scanned-searchable.pdf", result=result)
```

`extract_text` also accepts the copied worker's `routing_policy` plus optional
cooperative `cancellation_check`, `page_timeout_seconds`, and
`page_progress_callback` controls. These are thin engine controls for an
application adapter; the SDK still does not own application jobs or storage.

The package can process local files without PDFNest backend, PostgreSQL,
Redis, Dramatiq, frontend, HTTP services, authentication, billing, or
application storage.

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

## Boundary and status

PDFNest authentication, anonymous ownership, quotas, rate limits, durable job
orchestration, storage policy, cleanup, product routes, and UI remain outside
this package. OCR Text V2 has a controlled PDFNest-side opt-in adapter that
uses this public API; `OCR_TEXT_ENGINE=internal` remains the default and keeps
the existing internal engine as the fallback and parity reference. Searchable
PDF V2 has a separate consumer-specific opt-in boundary in the same form;
`SEARCHABLE_PDF_ENGINE=internal` remains its default. Other PDFNest consumers
have not been migrated.

No package has been published to a public registry.
