# Phase 1: isolated word-level editing prototype

This directory contains the disposable Phase 1 prototype and its tests. It edits one OCR-selected English word in an image-backed PDF by repairing a bounded local ink mask, placing a small patch on the original page, and inserting one searchable replacement word.

No frontend, backend, worker, or SDK source code was changed. No package was installed. The prototype uses the existing SDK OCR path, PyMuPDF, Pillow, system Tesseract, and local Poppler/qpdf tools.

## Plan and scope

The validated Phase 1 plan and review reports were read from the available review package at `/tmp/platen-word-review-20261108-tfzb44uu/`. The requested `platen-docs/word-level-editing/` directory is absent from the current workspace checkout. The source plan and review prompt supplied in Downloads were also read. `results/PLAN_ALIGNMENT.md` records the bounded acceptance criteria used here.

This prototype is not production integration. It supports one uniquely resolved word on an unrotated, uncropped image-backed page, refuses structural overlap and uncertain geometry, and emits a candidate only after local PDF validation succeeds.

## Reproduce

From the `platen-document` repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -s -q -p no:cacheprovider test/word-level-editing/test_word_level_editing.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python test/word-level-editing/prototype.py --source "/home/gimesha/Downloads/CamScanner 10-25-2026 1749_261028_125948.pdf" --output test/word-level-editing/artifacts/private-source/phase1-edited-13p.pdf --page-index 0 --target Ministry --replacement hello
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python test/word-level-editing/compare_pdf.py --source "/home/gimesha/Downloads/CamScanner 10-25-2026 1749_261028_125948.pdf" --candidate test/word-level-editing/artifacts/private-source/phase1-edited-13p.pdf --manifest test/word-level-editing/artifacts/private-source/phase1-source-run.json --output-dir test/word-level-editing/artifacts/private-source
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:test/word-level-editing .venv/bin/python test/word-level-editing/generate_synthetic_artifacts.py
```

The comparison command uses Poppler (`pdftoppm`, `pdftotext`) and `qpdf`. Its full-page renders are temporary; only the cropped source-derived comparison is retained locally. The crop and edited original PDF are ignored by Git in `artifacts/private-source/`.

## Files

- `prototype.py` — the isolated OCR, scan patch, text-layer reconciliation, refusal, and PDF validation code.
- `test_word_level_editing.py` — synthetic clean, textured, lossy/skew, stamp, rule, hidden-OCR, rotation, crop-box, and texture-oracle tests.
- `compare_pdf.py` — independent Poppler/qpdf validation and a cropped visual comparison for the supplied PDF.
- `generate_synthetic_artifacts.py` — regenerates source-safe comparison crops and JSON results under `artifacts/synthetic/`.
- `results/` — plan alignment, final measurements, and iteration notes.
- `artifacts/private-source/` — local-only source PDF output, run manifests, and visual comparison; all contents except its `.gitignore` are excluded from Git.
- `artifacts/synthetic/` — synthetic comparison images and a JSON manifest; these contain no source-document pages.
