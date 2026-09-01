# Standalone SDK Architecture

The initial package uses a thin boundary around a copied engine:

```text
local Python caller
        |
        v
platen_document.DocumentProcessor
        |
        v
copied engine contracts / routing / OCR / structure / renderers
        |
        +--> PyMuPDF, Pillow, pdfplumber
        +--> installed local Tesseract
```

The first controlled PDFNest consumer relationship was OCR Text V2. Its
boundary remains the reference shape for the later consumer-specific seams:

```text
PDFNest OCR Text V2 application orchestration
        |  OCR_TEXT_ENGINE=internal (default) | sdk (opt-in)
        |
        v
PDFNest OCR Text engine boundary
        |                         |
        v                         v
frozen internal engine       platen-document SDK
        |
        v
document processing
```

The existing internal implementation remains the default, configuration-only
rollback, and parity reference. The SDK copy is independently importable and testable, while
PDFNest application concerns remain excluded from the package:

- authentication and user accounts;
- guest identity, quotas, and rate limiting;
- HTTP routes and frontend state;
- PostgreSQL/Redis/Dramatiq jobs;
- local/remote application storage and cleanup;
- billing, subscriptions, Studio sessions, and product messages.

Current PDFNest consumer status:

- OCR Text V2, Searchable PDF V2, Document Extraction V2, PDF-to-Markdown V2,
  OCR-aware Highlight/Underline/Strikeout, and General Editor OCR each have an
  independent `internal|sdk` boundary;
- every selector defaults to `internal`, with `sdk` as explicit opt-in; and
- PDF-to-Word OCR fallback and Studio OCR/document paths remain internal-only.

No runtime fallback is implicit when an SDK engine is explicitly selected.

The copied engine preserves the current canonical OCR and structured-document
contracts, including `ocr_v2_structured_document.v1`, page indexing, geometry,
reading order, provenance, warnings, bounded scanned structure, searchable-PDF
requirements, and fail-closed validation.
