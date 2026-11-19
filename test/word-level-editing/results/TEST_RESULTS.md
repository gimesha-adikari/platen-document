# Phase 1 test results

**Verdict: PASS for the supplied English scanned-PDF case and the listed synthetic controls.** This is a local feasibility result for one selected word. It is not a production integration or a general PDF editing support claim.

## Supplied 13-page PDF

- Source: `/home/gimesha/Downloads/CamScanner 10-25-2026 1749_261028_125948.pdf`
- Source SHA-256: `06e72ff352512df22781b2e9b331aed35c74c2d082370f934e7526666cba5101`
- Page count: 13. Page 1 is 595 x 842 pt, rotation 0, CropBox equal to MediaBox.
- Target: OCR V2/Tesseract English, page index 0, token `page-0-token-0`, confidence 96.32/100, fixed OCR rectangle `(135.702, 45.358)–(188.255, 57.957)` pt.
- Candidate SHA-256: `b74619ed6d5ae1c1a245ed8cce3704257e69aa262806bed8ef60949e15e35250`

The output PDF keeps 13 pages and changes the target to `hello` once. MuPDF extracts exactly one replacement word in the selected area, no old `Ministry` there, and no extra OCR token in the fixed target plus 1 pt band. The original page has no hidden `Ministry` text in that area; the synthetic hidden-layer case separately proves aligned text-only removal and neighboring text preservation. One unrelated source text word on the page remains unchanged.

| Check | Result |
|---|---:|
| MuPDF changed pixels outside target + 1 pt at 72 DPI, threshold >2/255 | 0 |
| MuPDF changed pixels outside target + 1 pt at 144 DPI, threshold >2/255 | 0 |
| MuPDF changed pixels outside target + 1 pt at 288 DPI, threshold >2/255 | 0 |
| Poppler changed pixels outside target + 1 pt at 288 DPI, threshold >2/255 | 0 |
| Unedited pages pixel-identical at 144 DPI in MuPDF | 12/12 |
| Original image streams retained | Yes |
| Neighbor OCR token text and boxes retained outside target, within 0.5 pt | Yes |
| Poppler `pdftotext`: `hello` in target | 1 |
| Poppler `pdftotext`: stale `Ministry` in target | 0 |
| qpdf `--check` | PASS; no syntax or stream encoding errors |

The 288 DPI Poppler page-1 comparison has 6,029 changed pixels overall, all inside the predeclared target plus antialias band. The source-derived candidate PDF and cropped before/after image are retained locally under `artifacts/private-source/`; those files are ignored by Git and were not published.

## Synthetic fixtures

The test suite covers clean white paper, mildly textured paper, lossy JPEG with 2.5 degree scan skew, a red stamp overlap, a crossing table rule, aligned hidden OCR, 90 degree rotation, and a nonzero CropBox. The clean, textured, hidden-OCR, and lossy/skew fixtures edit successfully. Stamp and table-rule cases refuse without writing a candidate. Rotated and cropped geometry refuse with `UNSUPPORTED_PAGE_GEOMETRY`.

Against the known no-text synthetic texture oracle, mean absolute RGB error over the fixed repair region falls from **43.0164** to **1.3634**. This measurement is for the generated mild-texture fixture only; the original page has no no-text oracle.

Synthetic comparison crops and case summaries are committed under `artifacts/synthetic/`. They are generated from test-only content and contain no user-document pages.

## Commands and results

| Command | Result |
|---|---|
| `pytest -q -p no:cacheprovider` (initial default-shell attempt) | Collection failed: system Python 3.14 was selected and does not have PyMuPDF installed. This was an invocation/environment error; rerunning through the repository `.venv` below passes. |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -s -q -p no:cacheprovider test/word-level-editing/test_word_level_editing.py` | 12 passed; texture oracle line printed above |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider` | 443 passed, 1 skipped |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python test/word-level-editing/prototype.py --source "/home/gimesha/Downloads/CamScanner 10-25-2026 1749_261028_125948.pdf" --output test/word-level-editing/artifacts/private-source/phase1-edited-13p.pdf --page-index 0 --target Ministry --replacement hello` | `EDITED`; all prototype checks pass |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python test/word-level-editing/compare_pdf.py --source "/home/gimesha/Downloads/CamScanner 10-25-2026 1749_261028_125948.pdf" --candidate test/word-level-editing/artifacts/private-source/phase1-edited-13p.pdf --manifest test/word-level-editing/artifacts/private-source/phase1-source-run.json --output-dir test/word-level-editing/artifacts/private-source` | Poppler/qpdf PASS; zero changed pixels outside target + 1 pt |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:test/word-level-editing .venv/bin/python test/word-level-editing/generate_synthetic_artifacts.py` | Six synthetic cases regenerated; four edit and two refuse as expected |

## Limits and unresolved issues

- The inserted font is a Times-Bold Base14 approximation selected after visual inspection (`tibo`); embedded font identification and exact style matching are not solved.
- Background beneath the original ink is unknowable. The local row-sampling repair is measured on the synthetic texture oracle only; the source-derived crop receives visual review but has no ground-truth no-text scan.
- Only the first page and one English word are edited in the supplied file. The other 12 pages remain visually identical. No Sinhala/Tamil, native-text surgery, arbitrary stamp/table overlap, signatures, protection, forms, or annotation cases are qualified.
- The existing SDK full suite is local-source evidence only. No CI, browser, worker, backend, deployed-service, or production integration was run.
