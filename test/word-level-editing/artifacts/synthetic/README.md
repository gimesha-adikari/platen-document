# Synthetic Phase 1 comparison crops

These small PNGs and `summary.json` are generated from deterministic test-only scans. They show the clean, textured, hidden-OCR, lossy/skew, stamp, and table-border cases. The full one-page PDFs are created in a temporary directory by `generate_synthetic_artifacts.py` and removed after the crops and metrics are saved.

Regenerate from the `platen-document` repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:test/word-level-editing .venv/bin/python test/word-level-editing/generate_synthetic_artifacts.py
```

No original user PDF, original page crop, or source-derived PDF is included here.
