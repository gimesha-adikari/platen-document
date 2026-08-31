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

The long-term PDFNest relationship is intentionally not active yet:

```text
PDFNest application orchestration  (future consumer integration)
        |
        v
platen-document SDK                  (this milestone)
        |
        v
document processing
```

PDFNest currently continues to use its original `pdfnest-worker/app/core/ocr_v2`
implementation. The SDK copy is independently importable and testable, while
PDFNest application concerns remain excluded:

- authentication and user accounts;
- guest identity, quotas, and rate limiting;
- HTTP routes and frontend state;
- PostgreSQL/Redis/Dramatiq jobs;
- local/remote application storage and cleanup;
- billing, subscriptions, Studio sessions, and product messages.

The copied engine preserves the current canonical OCR and structured-document
contracts, including `ocr_v2_structured_document.v1`, page indexing, geometry,
reading order, provenance, warnings, bounded scanned structure, searchable-PDF
requirements, and fail-closed validation.
