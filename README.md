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
this package. PDFNest has not been connected to this SDK in this milestone;
the existing internal engine remains the fallback and parity reference.

No package has been published to a public registry.
