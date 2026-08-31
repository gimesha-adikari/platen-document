"""Safe local capability reporting for the standalone SDK."""

from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..engine.adapters import TesseractAdapter
from ..engine.language_catalog import get_installed_tesseract_languages


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _resolved_binary(config: Any) -> str | None:
    configured = getattr(config, "tesseract_binary", None)
    if configured:
        path = Path(configured)
        if path.is_file():
            return str(path)
    return shutil.which(configured or "tesseract")


def _tesseract_version(binary: str | None) -> str | None:
    if not binary:
        return None
    try:
        completed = subprocess.run(
            [binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = (completed.stdout or completed.stderr).splitlines()
    return first_line[0].strip() if first_line else None


def build_doctor_report(config: Any) -> dict[str, object]:
    """Return non-secret package, system, and engine capability metadata."""
    binary = _resolved_binary(config)
    adapter = TesseractAdapter(
        "eng",
        timeout=float(getattr(config, "tesseract_timeout", 300.0)),
        tessdata_dir=getattr(config, "tessdata_dir", None),
        tesseract_binary=getattr(config, "tesseract_binary", None),
    )
    availability = adapter.availability()
    data_dir = adapter._data_dir()
    return {
        "package": {
            "name": "platen-document",
            "version": _package_version("platen-document") or "0.1.0",
            "python": __import__("sys").version.split()[0],
        },
        "tesseract": {
            "available": bool(binary and availability.available),
            "binary": binary,
            "version": _tesseract_version(binary),
            "tessdata_dir": str(data_dir) if data_dir else None,
            "installed_languages": list(get_installed_tesseract_languages()),
            "eng_ready": availability.available,
            "availability_reason": availability.reason,
        },
        "python_dependencies": {
            "PyMuPDF": _package_version("PyMuPDF"),
            "Pillow": _package_version("Pillow"),
            "pdfplumber": _package_version("pdfplumber"),
        },
        "capabilities": {
            "native_pdf_extraction": True,
            "text_ocr": availability.available,
            "searchable_pdf": availability.available,
            "structured_document": availability.available,
            "markdown": True,
        },
    }
