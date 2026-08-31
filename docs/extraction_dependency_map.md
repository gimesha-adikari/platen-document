# Extraction Dependency Map

This map records what was copied, neutralized, retained in PDFNest, or kept as
a third-party/system dependency. The source module paths refer to the frozen
`pdfnest-worker/app/core/ocr_v2/` tree.

| Source module | Internal dependencies | Third-party dependencies | PDFNest-specific dependency | Decision |
| --- | --- | --- | --- | --- |
| `contracts.py` | none | stdlib | none | A — copy unchanged |
| `errors.py` | none | stdlib | none | A — copy unchanged |
| `geometry.py` | contracts | PyMuPDF, Pillow | none | A/D — copy; declare packages |
| `image_pages.py` | none | PyMuPDF, Pillow | none | A/D — copy; declare packages |
| `native.py` | contracts | stdlib | none | A — copy unchanged |
| `normalization.py` | contracts, geometry | stdlib | none | A — copy unchanged |
| `validation.py` | contracts, errors | stdlib | none | A — copy unchanged |
| `routing.py` | adapters, contracts, errors, validation | stdlib | none | A — copy unchanged |
| `profiles.py` | contracts, validation | stdlib | none | A — copy unchanged |
| `language_policy.py` | contracts/errors only by local imports | stdlib | none | A — copy unchanged |
| `language_catalog.py` | none | stdlib | formerly PDFNest language capability helper | B — neutral local installed-pack discovery |
| `adapters/base.py` | contracts, geometry | stdlib | none | A — copy unchanged |
| `adapters/tesseract.py` | contracts, errors, geometry, language policy, adapter base | Pillow, system Tesseract | PDFNest subprocess/capacity helper | B — neutral local subprocess/capacity helper |
| `adapters/ppocrv6_medium.py` | contracts, errors, geometry, adapter base | optional lazy PaddleOCR; no package declared | none | A — copy; remain unavailable unless already installed, no downloads |
| `adapters/structured_slot.py` | contracts, errors, geometry, adapter base | stdlib | none | A — copy unchanged |
| `orchestration.py` | adapters, contracts, errors, geometry, language policy, native, normalization, routing, telemetry, validation | PyMuPDF, Pillow | dynamic PDFNest language helper | B — local language catalog import; otherwise copy |
| `structured.py` | contracts, geometry, orchestration, Tesseract adapter | PyMuPDF, pdfplumber, stdlib | legacy Markdown extractor/table IR helpers | B/D — neutral Markdown/table helpers; declare pdfplumber |
| `markdown_support.py` | none | PyMuPDF, stdlib | copied from legacy helper by value | B/D — neutral helper |
| `native_tables.py` | none | pdfplumber, stdlib | legacy `DocumentIR`/node types | B/D — neutral table-node adapter preserving filters |
| `renderers/text.py` | contracts, validation | stdlib | none | A — copy unchanged |
| `renderers/searchable_pdf.py` | contracts, diagnostics, errors, validation | PyMuPDF, local fontconfig | none | A/D — copy; local system tools only |
| `renderers/validation.py` | contracts, diagnostics, errors | PyMuPDF | none | A/D — copy; declare PyMuPDF |
| `renderers/__init__.py` | renderer modules | none | none | A — copy |
| `markup.py` | contracts, errors, orchestration, routing, validation | PyMuPDF, stdlib | none | A — copy unchanged |
| `diagnostics.py` | none | stdlib | PDFNest logging name only | A — copy safe local diagnostics |
| `telemetry.py` | none | stdlib | logger namespace only | A — copy with standalone-safe logger |

## Deliberately retained in PDFNest

The following application infrastructure was inspected but not copied into the
SDK:

| PDFNest area | Decision |
| --- | --- |
| HTTP/API routes and authentication | C — keep in PDFNest |
| guest identity, ownership, quotas, and rate limiting | C — keep in PDFNest |
| PostgreSQL models and durable job records | C — keep in PDFNest |
| Redis/Dramatiq orchestration and actor lifecycle | C — keep in PDFNest |
| local/remote storage policy, R2/S3, cleanup, and idempotency | C — keep in PDFNest |
| frontend workspaces, UI messages, and product registry | C — keep in PDFNest |
| PDFNest legacy Markdown `DocumentIR` | C — keep in PDFNest; neutral table adapter used in SDK |
| billing, subscriptions, Studio, and product-specific limits | C — keep in PDFNest |

## System dependency boundary

Tesseract is a system dependency, not a Python runtime dependency. The SDK
discovers the executable and installed `*.traineddata` files, exposes safe
capability metadata, and raises typed engine errors when an explicitly
requested engine/language is unavailable. It never runs package installation
commands or downloads models.
