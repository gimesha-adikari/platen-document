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

The first controlled PDFNest consumer relationship is now active only for
OCR Text V2:

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

The existing internal implementation remains the default, fallback, and parity
reference. The SDK copy is independently importable and testable, while
PDFNest application concerns remain excluded from the package:

- authentication and user accounts;
- guest identity, quotas, and rate limiting;
- HTTP routes and frontend state;
- PostgreSQL/Redis/Dramatiq jobs;
- local/remote application storage and cleanup;
- billing, subscriptions, Studio sessions, and product messages.

Only the OCR Text V2 execution consumer uses the boundary in the first
migration milestone. Structured extraction, Markdown, Searchable PDF, markup,
Editor, Studio, and other consumers remain on their existing PDFNest paths.

The copied engine preserves the current canonical OCR and structured-document
contracts, including `ocr_v2_structured_document.v1`, page indexing, geometry,
reading order, provenance, warnings, bounded scanned structure, searchable-PDF
requirements, and fail-closed validation.
