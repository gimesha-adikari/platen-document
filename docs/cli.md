# Standalone CLI

The platen-document CLI uses only the public Python SDK. It has no PDFNest HTTP,
PostgreSQL, Redis, billing, authentication, storage or job queue dependencies.

## Installation

Requires Python 3.12+ and locally installed Tesseract with language packs for
scanned-page OCR.

    pip install -e .
    platen-document --help
    platen-document doctor

## Examples

Extract native or OCR text to a file:

    platen-document text input.pdf -o output.txt --language eng

Force OCR, even when a PDF already contains native text:

    platen-document ocr scanned.pdf -o output.txt --language sin

Extract text with canonical page and word metadata:

    platen-document text input.pdf --format json -o words.json --pages 1,3-5

Extract structured document data:

    platen-document document input.pdf -o document.json --scanned-table-recognition

Convert to Markdown:

    platen-document markdown input.pdf -o output.md --no-page-breaks

Create a searchable PDF:

    platen-document searchable-pdf scanned.pdf searchable.pdf --language eng

Highlight a matching phrase:

    platen-document markup input.pdf marked.pdf --action highlight --query "Invoice Number" --mode smart

Underline a region without running OCR:

    platen-document regions input.pdf marked.pdf --action underline --mode manual --region 1:72,144,180,18

Annotate multiple regions from JSON:

    platen-document regions input.pdf marked.pdf --action strikeout --regions-file regions.json

Print local capabilities:

    platen-document capabilities

The document command also accepts the alias structured. Text, document and
Markdown commands print to stdout unless -o is provided. For PDF-producing
commands, specify an output PDF path. Markup and regions print JSON operation
metadata and can also save it using --result-json; searchable-pdf supports
--result-json for the underlying OCR result.

## Options

Text/OCR support language, language-mode, comma-separated languages, a JSON
language-usage-file, routing-policy, profile, page ranges, per-page timeout,
password/password-file, progress, output format and engine configuration.

Structured/Markdown support language, routing and engine configuration.
The Markdown command can disable page break markers with --no-page-breaks.
The structured processor supports optional scanned table recognition.

Searchable PDF supports language configuration and engine settings. Its
public SDK method does not have a routing-policy parameter.

Markup supports highlight, underline and strikeout, with query-based
smart/native/ocr selection modes and configurable color.

Regions supports highlight, underline and strikeout using repeatable
--region PAGE:X,Y,WIDTH,HEIGHT arguments or a --regions-file JSON file.
Modes are smart, native, ocr and manual. Manual annotations do not run OCR.
Passwords, progress, routing and timeout are exposed where supported by
the public SDK method.

Engine options include --tesseract-binary, --tessdata-dir,
--tesseract-timeout, --raster-dpi, --raster-dpi-metadata-policy,
--max-raster-pixels, and --structured-max-raster-pixels.
Run platen-document COMMAND --help for exact flags.

## Region JSON file

    {
      "regions": [
        {
          "page_number": 1,
          "rect": {"x": 72, "y": 144, "width": 180, "height": 18},
          "region_id": "review-note",
          "color": "#ffff00"
        }
      ]
    }

Regions use one-based page numbers and visible-page PDF-point coordinates.
Colors accept hex #RRGGBB or comma-separated floating-point RGB values from
zero to one. The CLI does not download external OCR models or packages.

## SDK API mappings

| Command | Public SDK operation |
|---|---|
| text, ocr | DocumentProcessor.extract_text and render_text |
| document, structured | DocumentProcessor.extract_document |
| markdown | DocumentProcessor.extract_document and to_markdown |
| searchable-pdf | DocumentProcessor.make_searchable_pdf |
| markup | DocumentProcessor.apply_markup |
| regions | DocumentProcessor.apply_markup_regions |
| capabilities | DocumentProcessor.capabilities |
| doctor | Existing SDK doctor diagnostics |

The public extract_markdown method is a convenience alternative for the
same document-to-Markdown workflow. The CLI invokes extract_document then
to_markdown so it can expose routing policy options.

In-memory DocumentResult reuse across operations remains available in the
Python API. Each CLI invocation processes an independent request rather
than serializing and reconstructing internal result objects.
