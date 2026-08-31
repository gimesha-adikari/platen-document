"""Installed Tesseract language discovery for the standalone engine."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def normalize_tesseract_lang_code(code: str | None) -> str:
    return code.strip().lower() if code else ""


@lru_cache(maxsize=1)
def get_installed_tesseract_languages() -> tuple[str, ...]:
    """Find usable traineddata without trusting a stale prefix blindly."""
    candidates: list[Path] = []
    override = os.getenv("TESSDATA_PREFIX", "").strip()
    if override:
        candidates.append(Path(override))
    candidates.extend(Path(path) for path in (
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tessdata",
        "/usr/local/share/tessdata",
    ))
    for tessdata in candidates:
        if not tessdata.is_dir():
            continue
        languages = [
            path.stem
            for path in tessdata.glob("*.traineddata")
            if path.is_file() and path.stem not in {"osd", "pdf"}
        ]
        if languages:
            return tuple(sorted(languages))
    return ()
