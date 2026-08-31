"""Run a safe-metadata differential comparison of PDFNest and the SDK copy.

The parent process creates only small derived image PDFs from approved local
fixtures. Each engine runs in an isolated child process with its own
``PYTHONPATH``. Evidence contains hashes, counts, classifications, and
geometry summaries; it does not persist document OCR text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
WORKER_ROOT = ROOT.parent / "platen" / "pdfnest-worker"
REPO_ROOT = ROOT.parent / "platen"
APPROVED_ROOT = Path("/home/gimesha/pdfnest-tests")
OUTPUT_ROOT = ROOT / "output" / "extraction-parity-01"
PYTHON_CACHE = Path("/tmp/platen-document-parity-pycache")


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _sha(value: str | bytes) -> str:
    data = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(data).hexdigest()


def _text_summary(text: str) -> dict[str, Any]:
    return {"length": len(text), "sha256": _sha(text)}


def _rounded(value: Any) -> float:
    return round(float(value), 4)


def _bbox_summary(box: Any) -> list[float] | None:
    if box is None:
        return None
    if isinstance(box, dict):
        return [_rounded(box.get(name, 0.0)) for name in ("x", "y", "width", "height")]
    return [_rounded(getattr(box, name)) for name in ("x", "y", "width", "height")]


def _language_summary(language: Any) -> dict[str, Any]:
    if language is None:
        return {}
    return {
        "requested": list(getattr(language, "requested_languages", ())),
        "detected": list(getattr(language, "detected_languages", ())),
        "status": getattr(language, "language_status", ""),
        "scripts": list(getattr(language, "detected_scripts", ())),
        "script_status": getattr(language, "script_status", ""),
        "mode": getattr(language, "requested_mode", ""),
        "confidence": getattr(language, "detection_confidence", None),
        "reason": getattr(language, "detection_reason", None),
    }


def _token_summary(page: Any) -> dict[str, Any]:
    tokens = list(getattr(page, "tokens", ()))
    token_shape = [
        {
            "text_sha256": _sha(str(token.text)),
            "text_length": len(str(token.text)),
            "bbox": _bbox_summary(token.bbox),
            "line_id": token.line_id,
            "block_id": token.block_id,
        }
        for token in tokens
    ]
    return {
        "count": len(tokens),
        "reading_order_count": len(getattr(page, "reading_order", ())),
        "reading_order_sha256": _sha("|".join(str(value) for value in getattr(page, "reading_order", ()))),
        "shape_sha256": _sha(json.dumps(token_shape, sort_keys=True, ensure_ascii=False)),
    }


def _ocr_result_summary(result: Any) -> dict[str, Any]:
    pages = []
    for page in result.pages:
        pages.append(
            {
                "page_index": page.page_index,
                "classification": _value(page.content_classification),
                "processing_source": _value(page.processing_source),
                "status": _value(page.status),
                "geometry": {
                    "width": _rounded(page.geometry.width),
                    "height": _rounded(page.geometry.height),
                    "rotation": page.geometry.rotation,
                    "coordinate_space": page.geometry.coordinate_space,
                },
                "text": _text_summary(page.text),
                "tokens": _token_summary(page),
                "line_count": len(page.lines),
                "block_count": len(page.blocks),
                "language": _language_summary(page.language),
                "capabilities": sorted(page.capabilities),
                "validation_valid": page.validation.valid,
                "failure_code": page.failure_code,
            }
        )
    return {
        "schema_version": result.schema_version,
        "page_count": len(result.pages),
        "pages": pages,
        "capabilities": sorted(result.capabilities),
        "provenance": [
            {
                "producer_id": item.producer_id,
                "producer_version": item.producer_version,
                "source": item.source,
            }
            for item in result.provenance
        ],
        "validation_valid": result.validation.valid,
    }


def _data_shape(data: Any) -> Any:
    if isinstance(data, dict):
        shaped: dict[str, Any] = {}
        for key, value in sorted(data.items(), key=lambda pair: str(pair[0])):
            if key in {"text", "marker"} and isinstance(value, str):
                shaped[str(key)] = {"length": len(value), "sha256": _sha(value)}
            elif key in {"spans", "line_ids", "items", "headers", "rows"}:
                shaped[str(key)] = _data_shape(value)
            elif isinstance(value, (dict, list, tuple)):
                shaped[str(key)] = _data_shape(value)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                shaped[str(key)] = value
        return shaped
    if isinstance(data, (list, tuple)):
        return [_data_shape(value) for value in data]
    if isinstance(data, str):
        return {"length": len(data), "sha256": _sha(data)}
    return data


def _structured_element_summary(element: Any) -> dict[str, Any]:
    return {
        "type": _value(element.type),
        "page_index": element.page_index,
        "text": _text_summary(element.text),
        "bbox": _bbox_summary(element.bbox),
        "source": element.source,
        "confidence": element.confidence,
        "level": element.level,
        "ordered": element.ordered,
        "data": _data_shape(element.data),
    }


def _markdown_summary(markdown: str) -> dict[str, Any]:
    lines = markdown.splitlines()
    return {
        "length": len(markdown),
        "sha256": _sha(markdown),
        "heading_count": sum(line.startswith("# ") or line.startswith("## ") or line.startswith("### ") or line.startswith("#### ") or line.startswith("##### ") or line.startswith("###### ") for line in lines),
        "list_item_count": sum(line.lstrip().startswith(("- ", "* ")) or (len(line) > 2 and line[0].isdigit() and ". " in line[:4]) for line in lines),
        "table_line_count": sum(line.startswith("|") for line in lines),
        "page_break_count": markdown.count("<!-- pagebreak -->"),
    }


def _structured_result_summary(result: Any, markdown: str) -> dict[str, Any]:
    pages = []
    for page in result.pages:
        pages.append(
            {
                "page_index": page.page_index,
                "classification": page.classification,
                "processing_source": page.processing_source,
                "status": page.status,
                "geometry": page.geometry,
                "element_count": len(page.elements),
                "element_types": [_value(element.type) for element in page.elements],
                "reading_order_count": len(page.reading_order),
                "reading_order_sha256": _sha("|".join(page.reading_order)),
                "warnings": list(page.warnings),
                "language": page.language,
            }
        )
    elements = [_structured_element_summary(element) for element in result.elements]
    return {
        "schema_version": result.schema_version,
        "page_count": len(result.pages),
        "pages": pages,
        "elements": elements,
        "element_type_counts": {
            str(_value(element.type)): sum(1 for item in result.elements if _value(item.type) == _value(element.type))
            for element in result.elements
        },
        "capabilities": list(result.capabilities),
        "available_capabilities": list(result.available_capabilities),
        "warnings": list(result.warnings),
        "validation_valid": bool(result.validation.get("valid")),
        "markdown": _markdown_summary(markdown),
    }


def _artifact_summary(path: Path) -> dict[str, Any]:
    import pymupdf as fitz

    with fitz.open(str(path)) as document:
        pages = []
        for page in document:
            words = page.get_text("words")
            text = page.get_text("text")
            pages.append(
                {
                    "width": _rounded(page.rect.width),
                    "height": _rounded(page.rect.height),
                    "text": _text_summary(text),
                    "word_count": len(words),
                    "word_shape_sha256": _sha(json.dumps([
                        [_rounded(word[0]), _rounded(word[1]), _rounded(word[2]), _rounded(word[3]), str(word[4])]
                        for word in words
                    ], ensure_ascii=False)),
                    "image_count": len(page.get_images(full=True)),
                    "raster_sha256": _sha(page.get_pixmap(alpha=False).samples),
                }
            )
    return {
        "header_valid": path.read_bytes()[:5] == b"%PDF-",
        "byte_length": path.stat().st_size,
        "page_count": len(pages),
        "pages": pages,
    }


def _child_summary(side: str, operation: str, path: Path, language: str, language_mode: str | None, languages: tuple[str, ...], output: Path | None) -> dict[str, Any]:
    if side == "internal":
        from app.core.ocr_v2 import OCRProfile, OCRV2Worker
        from app.core.ocr_v2.renderers import SearchablePdfRenderer
        from app.core.ocr_v2.structured import StructuredDocumentProcessor, render_structured_markdown

        if operation == "structured":
            result = StructuredDocumentProcessor().process_document(path, language=language, language_mode=language_mode, languages=languages or None)
            return {"result": _structured_result_summary(result, render_structured_markdown(result))}
        profile = OCRProfile.SEARCHABLE_PDF_V2 if operation == "searchable" else OCRProfile.OCR_TEXT_V2
        result = OCRV2Worker().process_document(path, language=language, language_mode=language_mode, languages=languages or None, profile=profile)
        summary: dict[str, Any] = {"result": _ocr_result_summary(result)}
        if operation == "searchable":
            if output is None:
                raise ValueError("searchable operation requires output path")
            SearchablePdfRenderer().render(path, result, output)
            summary["artifact"] = _artifact_summary(output)
        return summary

    from platen_document import DocumentProcessor
    from platen_document.engine.renderers import SearchablePdfRenderer
    from platen_document.engine.structured import render_structured_markdown
    from platen_document.engine.validation import OCRProfile

    processor = DocumentProcessor()
    if operation == "structured":
        result = processor.extract_document(path, language=language, language_mode=language_mode, languages=languages or None)
        return {"result": _structured_result_summary(result, render_structured_markdown(result))}
    profile = OCRProfile.SEARCHABLE_PDF_V2 if operation == "searchable" else OCRProfile.OCR_TEXT_V2
    result = processor.extract_text(path, language=language, language_mode=language_mode, languages=languages or None, profile=profile)
    summary = {"result": _ocr_result_summary(result)}
    if operation == "searchable":
        if output is None:
            raise ValueError("searchable operation requires output path")
        SearchablePdfRenderer().render(path, result, output)
        summary["artifact"] = _artifact_summary(output)
    return summary


def _child_main(args: argparse.Namespace) -> int:
    try:
        summary = _child_summary(args.side, args.operation, Path(args.path), args.language, args.language_mode, tuple(args.languages.split(",")) if args.languages else (), Path(args.output) if args.output else None)
        print(json.dumps(summary, sort_keys=True, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}, sort_keys=True))
        return 1


def _run_child(side: str, operation: str, path: Path, language: str = "eng", language_mode: str | None = None, languages: Iterable[str] = (), output: Path | None = None) -> dict[str, Any]:
    source_root = WORKER_ROOT if side == "internal" else ROOT / "src"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--side",
        side,
        "--operation",
        operation,
        "--path",
        str(path),
        "--language",
        language,
    ]
    if language_mode:
        command.extend(["--language-mode", language_mode])
    if languages:
        command.extend(["--languages", ",".join(languages)])
    if output:
        command.extend(["--output", str(output)])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    env["PYTHONPYCACHEPREFIX"] = str(PYTHON_CACHE)
    completed = subprocess.run(command, capture_output=True, text=True, env=env, timeout=420)
    if completed.returncode != 0:
        try:
            parsed = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            parsed = {}
        return {"error": parsed.get("error", "CHILD_PROCESS_FAILED"), "returncode": completed.returncode}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"error": "CHILD_OUTPUT_INVALID", "returncode": completed.returncode}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _behavioral_projection(value: Any, *, in_artifact: bool = False) -> Any:
    """Ignore only renderer-container bytes that are not behavioral output."""
    if isinstance(value, dict):
        return {
            key: _behavioral_projection(item, in_artifact=in_artifact or key == "artifact")
            for key, item in value.items()
            if not (in_artifact and key == "byte_length")
        }
    if isinstance(value, list):
        return [_behavioral_projection(item, in_artifact=in_artifact) for item in value]
    return value


def _non_material_differences(internal: dict[str, Any], sdk: dict[str, Any]) -> list[str]:
    differences: list[str] = []
    left = internal.get("artifact", {})
    right = sdk.get("artifact", {})
    if left.get("byte_length") != right.get("byte_length"):
        differences.append(f"searchable PDF container byte length differs: {left.get('byte_length')} vs {right.get('byte_length')}")
    return differences


def _make_image_pdf(image_paths: list[Path], target: Path) -> None:
    from io import BytesIO

    import pymupdf as fitz
    from PIL import Image, ImageOps

    target.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open() as document:
        for image_path in image_paths:
            with Image.open(image_path) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                encoded = BytesIO()
                image.save(encoded, format="PNG", dpi=(150, 150))
                width, height = image.size
            page = document.new_page(width=max(1.0, width * 72.0 / 150), height=max(1.0, height * 72.0 / 150))
            page.insert_image(page.rect, stream=encoded.getvalue(), keep_proportion=False, overlay=False)
        document.save(str(target), garbage=3, deflate=True)


def _make_mixed_pdf(native_path: Path, image_pdf: Path, target: Path) -> None:
    import pymupdf as fitz

    with fitz.open(str(native_path)) as native, fitz.open(str(image_pdf)) as image_document, fitz.open() as output:
        output.insert_pdf(native, from_page=0, to_page=0)
        output.insert_pdf(image_document)
        output.save(str(target), garbage=3, deflate=True)


def _fixture_metadata(name: str, source: Path, kind: str) -> dict[str, Any]:
    import pymupdf as fitz

    item: dict[str, Any] = {
        "fixture": name,
        "kind": kind,
        "source_sha256": _sha(source.read_bytes()),
        "source_bytes": source.stat().st_size,
    }
    if source.suffix.lower() == ".pdf":
        with fitz.open(str(source)) as document:
            item["page_count"] = len(document)
            item["page_dimensions"] = [[_rounded(page.rect.width), _rounded(page.rect.height)] for page in document]
    return item


def _run_parent() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    inputs = OUTPUT_ROOT / "inputs"
    native = REPO_ROOT / "pdfnest" / "tests" / "fixtures" / "normal_text.pdf"
    scanned = APPROVED_ROOT / "ocr-extracted-text-29-rotated (1).pdf"
    sinhala_image = APPROVED_ROOT / "images" / "1q.jpeg"
    bilingual_image = APPROVED_ROOT / "images" / "1.jpeg"
    english_image = APPROVED_ROOT / "images" / "page-001.jpg"
    sinhala_pdf = inputs / "approved-sinhala.pdf"
    bilingual_pdf = inputs / "approved-bilingual.pdf"
    english_pdf = inputs / "approved-english.pdf"
    mixed_pdf = inputs / "approved-mixed-native-bilingual.pdf"
    _make_image_pdf([sinhala_image], sinhala_pdf)
    _make_image_pdf([bilingual_image], bilingual_pdf)
    _make_image_pdf([english_image], english_pdf)
    _make_mixed_pdf(native, bilingual_pdf, mixed_pdf)

    fixtures = [
        _fixture_metadata("native-text", native, "repository-approved-native-pdf"),
        _fixture_metadata("scanned-markdown", scanned, "approved-real-scanned-pdf"),
        _fixture_metadata("sinhala", sinhala_image, "approved-real-image-derived-pdf"),
        _fixture_metadata("bilingual", bilingual_image, "approved-real-image-derived-pdf"),
        _fixture_metadata("english", english_image, "approved-real-image-derived-pdf"),
        _fixture_metadata("derived-sinhala-pdf", sinhala_pdf, "derived-from-approved-image"),
        _fixture_metadata("derived-bilingual-pdf", bilingual_pdf, "derived-from-approved-image"),
        _fixture_metadata("derived-mixed-pdf", mixed_pdf, "derived-native-plus-approved-image"),
    ]
    _write_json(OUTPUT_ROOT / "fixture-inventory.json", fixtures)

    cases = [
        ("native_text", "text", native, "eng", None, (), None),
        ("scanned_text", "text", scanned, "eng", None, (), None),
        ("sinhala_text", "text", sinhala_pdf, "sin", None, (), None),
        ("bilingual_explicit_text", "text", bilingual_pdf, "eng+sin", None, (), None),
        ("bilingual_auto_text", "text", bilingual_pdf, "auto", "AUTO", ("eng", "sin"), None),
        ("native_structured", "structured", native, "eng", None, (), None),
        ("scanned_structured", "structured", scanned, "eng", None, (), None),
        ("mixed_structured", "structured", mixed_pdf, "eng", None, (), None),
        ("current_scanned_markdown", "structured", scanned, "eng", None, (), None),
        ("searchable_bilingual", "searchable", bilingual_pdf, "eng+sin", None, (), OUTPUT_ROOT / "searchable-bilingual"),
    ]
    records = []
    for name, operation, path, language, language_mode, languages, output_base in cases:
        outputs: dict[str, Path | None] = {}
        for side in ("internal", "sdk"):
            output = None
            if output_base is not None:
                output = output_base.with_name(output_base.name + f"-{side}.pdf")
                output.parent.mkdir(parents=True, exist_ok=True)
            outputs[side] = output
        internal = _run_child("internal", operation, path, language, language_mode, languages, outputs["internal"])
        sdk = _run_child("sdk", operation, path, language, language_mode, languages, outputs["sdk"])
        mismatches = []
        non_material_differences: list[str] = []
        if "error" in internal or "error" in sdk:
            mismatches.append("child execution failure")
        else:
            non_material_differences = _non_material_differences(internal, sdk)
        if "error" not in internal and "error" not in sdk and _behavioral_projection(internal) != _behavioral_projection(sdk):
            mismatches.append("safe result summaries differ")
        records.append({
            "case": name,
            "operation": operation,
            "input_sha256": _sha(path.read_bytes()),
            "internal": internal,
            "sdk": sdk,
            "match": not mismatches,
            "mismatches": mismatches,
            "non_material_differences": non_material_differences,
        })

    summary = {
        "harness": "internal-vs-standalone-sdk-safe-metadata-parity-v1",
        "freeze_reference": "pdfnest-worker b02d48cc57cac581b40d27519aeee4db5134c61b",
        "sdk_project": str(ROOT),
        "internal_source": str(WORKER_ROOT / "app" / "core" / "ocr_v2"),
        "full_text_persisted": False,
        "cases": records,
        "case_count": len(records),
        "matched_case_count": sum(1 for record in records if record["match"]),
        "all_cases_matched": all(record["match"] for record in records),
        "unrepresented_real_language": ["tam"],
    }
    _write_json(OUTPUT_ROOT / "parity-summary.json", summary)
    _write_json(OUTPUT_ROOT / "environment.json", {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "tesseract": "system capability recorded separately by doctor",
        "execution": "sequential child processes; no PDFNest services",
    })
    print(json.dumps({"output": str(OUTPUT_ROOT), "matched": summary["matched_case_count"], "total": summary["case_count"], "all_cases_matched": summary["all_cases_matched"]}, sort_keys=True))
    return 0 if summary["all_cases_matched"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--side", choices=("internal", "sdk"))
    parser.add_argument("--operation", choices=("text", "structured", "searchable"))
    parser.add_argument("--path")
    parser.add_argument("--language", default="eng")
    parser.add_argument("--language-mode")
    parser.add_argument("--languages", default="")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.child:
        return _child_main(args)
    return _run_parent()


if __name__ == "__main__":
    raise SystemExit(main())
