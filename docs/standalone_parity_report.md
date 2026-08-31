# Standalone Parity Report

## Scope

This is the first differential harness for the frozen PDFNest internal engine
and the standalone `platen-document` copy. Each side runs in a separate Python
process so source package names and dataclass identities cannot mask import
coupling.

The comparison is safe-metadata based: page counts, status/classification,
text lengths and hashes, language metadata, token/line/block counts, geometry
summaries, structured element summaries, Markdown structure summaries, and
searchable-PDF artifact facts. Full OCR text is not written to ordinary
evidence.

## Required fixture set

The harness covers representative native, scanned, Sinhala, bilingual/AUTO,
structured, current scanned-Markdown, searchable-PDF, and mixed cases when
approved local fixtures are available. Tamil evidence is labelled as synthetic
or regression-only if it is used; it is not presented as an approved real
corpus.

## Executed result — 2026-08-31

The comparison completed successfully with **10/10 behavioral cases matched**.
The cases were:

| Case | Operation | Input boundary | Result |
| --- | --- | --- | --- |
| `native_text` | OCR text | repository-approved native fixture | matched |
| `scanned_text` | OCR text | approved real scanned PDF | matched |
| `sinhala_text` | explicit OCR text | approved real Sinhala image-derived PDF | matched |
| `bilingual_explicit_text` | explicit OCR text | approved real English/Sinhala image-derived PDF | matched |
| `bilingual_auto_text` | AUTO OCR text | same approved bilingual PDF | matched |
| `native_structured` | structured document | repository-approved native fixture | matched |
| `scanned_structured` | structured document | approved real scanned PDF | matched |
| `mixed_structured` | mixed native/scanned structure | native page plus approved bilingual page | matched |
| `current_scanned_markdown` | structured/Markdown | approved current scanned-Markdown fixture | matched |
| `searchable_bilingual` | searchable PDF | approved bilingual image-derived PDF | matched |

For the searchable-PDF case, both outputs had a valid PDF header, one page,
identical page dimensions (`345.6 x 488.64` points), identical visible raster
hash, identical extracted-text hash, 658 extracted words, and identical word
geometry summary. The SDK artifact was 862,699 bytes versus 862,624 bytes for
the internal artifact; this 75-byte container difference is non-semantic and
was retained as evidence rather than treated as a parity failure.

The exact approved scanned-Markdown fixture hash was verified as:

`120f36b0ae84432beb9a4ae1df987afc4b7d80c4f85586c6eb8730ced8c151af`

The bilingual and Sinhala derived inputs were generated only from approved
images (`images/1.jpeg` and `images/1q.jpeg`) and their source hashes are
persisted in `output/extraction-parity-01/fixture-inventory.json`.

Observed representative result facts were:

- native OCR: 3 pages, native extraction, 136 characters and 22 words per
  page;
- scanned OCR: 3 pages, OCR recognition, 311/315/423 words by page;
- Sinhala OCR: 1 page, 548 characters and 85 words;
- bilingual explicit and AUTO OCR: 1 page, 4,000 characters and 658 words,
  with requested and detected `eng` + `sin`;
- native structured Markdown: 3 headings and 2 page breaks;
- scanned structured Markdown: 6 headings, 27 table lines, and 2 page
  breaks;
- mixed structured output: 2 pages, native first and OCR second, with one
  page break and no duplicate element IDs.

All text and geometry comparisons were represented by hashes, lengths, counts,
coordinates, and structural metadata. Full OCR document text was not written
to ordinary evidence.

## Installation, tests, and source-isolation result

The package was installed editable into the existing local worker virtual
environment with no dependency installation or download. The standalone
focused suite passed **11 tests**. Python compilation passed using a temporary
bytecode cache. No PDFNest consumer source imports `platen_document`, and the
internal worker tree remains intact.

The executable result is persisted under:

`output/extraction-parity-01/`

It contains the fixture inventory, freeze/runtime metadata, test summary,
parity summary, and the two behaviorally equivalent searchable-PDF artifacts.
