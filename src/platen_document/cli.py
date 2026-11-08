"""Local command-line interface for the public platen-document SDK.

This module is intentionally a thin adapter over DocumentProcessor. It has no
PDFNest application, cloud, database, job queue, or service dependencies.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Sequence

from .api import DocumentProcessor, EngineConfiguration
from .engine.contracts import Rect
from .engine.markup import MarkupRegion
from .engine.validation import OCRProfile


_ROUTES = ("AUTO", "FAST", "QUALITY", "GEOMETRY", "LANGUAGE_FALLBACK", "FORCE_OCR")


def _package_version() -> str:
    try:
        return version("platen-document")
    except PackageNotFoundError:
        return "development"


def _add_config(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("local engine configuration")
    group.add_argument("--tesseract-binary", help="Path to an installed Tesseract executable")
    group.add_argument("--tessdata-dir", help="Directory containing installed language .traineddata files")
    group.add_argument("--tesseract-timeout", type=float, help="Tesseract subprocess timeout in seconds")
    group.add_argument("--raster-dpi", type=int, help="Page raster resolution (default: 200)")
    group.add_argument("--raster-dpi-metadata-policy", choices=("embed_dpi", "omit_dpi"))
    group.add_argument("--max-raster-pixels", type=int, help="Maximum pixels per rendered page")
    group.add_argument("--structured-max-raster-pixels", type=int)
    group.add_argument("--scanned-table-recognition", action="store_true", help="Enable optional scanned-table recognition")


def _add_language(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--language", default="eng", help="Tesseract language ID or 'auto' (default: eng)")
    parser.add_argument("--language-mode", choices=("explicit", "auto"))
    parser.add_argument("--languages", help="Comma-separated allowed OCR language IDs")
    parser.add_argument("--language-usage-file", type=Path, help="JSON object of language IDs and usage weights")


def _add_route(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--routing-policy", choices=_ROUTES, default="AUTO")


def _add_progress(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--progress", action="store_true", help="Report SDK processing progress on stderr")


def _add_password(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--password", help="PDF password (visible in command-line history)")
    group.add_argument("--password-file", type=Path, help="Read PDF password from the first line of a file")


def _add_result_file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--result-json", type=Path, help="Also write operation metadata as JSON")


def _add_color(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--color", default="#ffff00", help="Annotation RGB: #RRGGBB or R,G,B floats 0..1")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="platen-document",
        description="Process local PDFs using only the platen-document SDK.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_package_version()}")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="Report installed local OCR and SDK capabilities")
    _add_config(doctor)
    capabilities = commands.add_parser("capabilities", help="Report DocumentProcessor.capabilities()")
    _add_config(capabilities)

    for name in ("text", "ocr"):
        cmd = commands.add_parser(name, help="Extract text (ocr forces visual recognition by default)" if name == "ocr" else "Extract text, with native/OCR routing")
        cmd.add_argument("input", type=Path)
        cmd.add_argument("-o", "--output", type=Path, help="Output text/JSON path; otherwise print to stdout")
        cmd.add_argument("--format", choices=("text", "json"), default="text")
        cmd.add_argument("--profile", choices=tuple(member.value for member in OCRProfile), default=OCRProfile.OCR_TEXT_V2.value)
        cmd.add_argument("--pages", help="One-based pages, e.g. 1,3-5")
        cmd.add_argument("--page-timeout", type=float, help="Per-page OCR timeout in seconds")
        _add_language(cmd)
        _add_route(cmd)
        if name == "ocr":
            cmd.set_defaults(routing_policy="FORCE_OCR")
        _add_password(cmd)
        _add_config(cmd)
        _add_progress(cmd)

    structured = commands.add_parser("document", aliases=["structured"], help="Extract canonical structured document JSON")
    structured.add_argument("input", type=Path)
    structured.add_argument("-o", "--output", type=Path)
    _add_language(structured)
    _add_route(structured)
    _add_config(structured)
    _add_progress(structured)

    markdown = commands.add_parser("markdown", help="Extract a document and convert to Markdown")
    markdown.add_argument("input", type=Path)
    markdown.add_argument("-o", "--output", type=Path)
    markdown.add_argument("--page-breaks", action=argparse.BooleanOptionalAction, default=True)
    _add_language(markdown)
    _add_route(markdown)
    _add_config(markdown)
    _add_progress(markdown)

    searchable = commands.add_parser("searchable-pdf", help="Create a searchable PDF with an invisible OCR text layer")
    searchable.add_argument("input", type=Path)
    searchable.add_argument("output", type=Path)
    searchable.add_argument("--job-id", help="Optional diagnostic correlation identifier")
    _add_result_file(searchable)
    _add_language(searchable)
    _add_config(searchable)

    markup = commands.add_parser("markup", help="Highlight, underline or strike out matching text")
    markup.add_argument("input", type=Path)
    markup.add_argument("output", type=Path)
    markup.add_argument("--action", required=True, choices=("highlight", "underline", "strikeout"))
    markup.add_argument("--query", required=True, help="Text to match using canonical reading-order words")
    markup.add_argument("--mode", default="smart", choices=("smart", "native", "ocr"))
    _add_color(markup)
    _add_result_file(markup)
    _add_language(markup)
    _add_config(markup)
    _add_progress(markup)

    regions = commands.add_parser("regions", help="Highlight, underline or strike out page rectangles")
    regions.add_argument("input", type=Path)
    regions.add_argument("output", type=Path)
    regions.add_argument("--action", required=True, choices=("highlight", "underline", "strikeout"))
    regions.add_argument("--mode", default="smart", choices=("smart", "native", "ocr", "manual"))
    region_source = regions.add_mutually_exclusive_group(required=True)
    region_source.add_argument("--region", action="append", metavar="PAGE:X,Y,W,H", help="Repeat for multiple one-based page regions")
    region_source.add_argument("--regions-file", type=Path, help="JSON list of page rectangles with optional colors and IDs")
    _add_color(regions)
    regions.add_argument("--page-timeout", type=float)
    _add_password(regions)
    _add_result_file(regions)
    _add_language(regions)
    _add_route(regions)
    _add_config(regions)
    _add_progress(regions)

    return parser


def _config(args: argparse.Namespace) -> EngineConfiguration:
    config = EngineConfiguration.from_env()
    updates: dict[str, Any] = {}
    for key in (
        "tesseract_binary", "tessdata_dir", "tesseract_timeout", "raster_dpi",
        "raster_dpi_metadata_policy", "max_raster_pixels", "structured_max_raster_pixels",
    ):
        value = getattr(args, key, None)
        if value is not None:
            updates[key] = value
    if getattr(args, "scanned_table_recognition", False):
        updates["enable_scanned_table_recognition"] = True
    return replace(config, **updates)


def _language_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    languages = tuple(part.strip() for part in (args.languages or "").split(",") if part.strip()) or None
    usage = None
    if args.language_usage_file is not None:
        usage = json.loads(args.language_usage_file.read_text(encoding="utf-8"))
        if not isinstance(usage, dict) or any(
            not isinstance(key, str) or not isinstance(value, (int, float)) or isinstance(value, bool)
            for key, value in usage.items()
        ):
            raise ValueError("language usage file must contain a JSON object of numeric language weights")
    return {
        "language": args.language,
        "language_mode": args.language_mode.upper() if args.language_mode else None,
        "languages": languages,
        "language_usage": usage,
    }


def _password(args: argparse.Namespace) -> str | None:
    if getattr(args, "password_file", None):
        return args.password_file.read_text(encoding="utf-8").splitlines()[0]
    return getattr(args, "password", None)


def _pages(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    indexes: list[int] = []
    for fragment in value.split(","):
        bits = fragment.strip().split("-", maxsplit=1)
        if not bits[0].isdigit() or (len(bits) == 2 and not bits[1].isdigit()):
            raise ValueError("--pages must use one-based page numbers, e.g. 1,3-5")
        first = int(bits[0])
        last = int(bits[1]) if len(bits) == 2 else first
        if first < 1 or last < first:
            raise ValueError("--pages must contain positive, increasing page ranges")
        indexes.extend(range(first - 1, last))
    if not indexes:
        raise ValueError("--pages must not be empty")
    return tuple(dict.fromkeys(indexes))


def _color(value: str) -> tuple[float, float, float]:
    if value.startswith("#") and len(value) == 7:
        try:
            return tuple(int(value[i:i + 2], 16) / 255.0 for i in (1, 3, 5))  # type: ignore[return-value]
        except ValueError as exc:
            raise ValueError(f"invalid hex color: {value}") from exc
    try:
        parts = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise ValueError(f"invalid color: {value}; expected #RRGGBB or R,G,B floats") from exc
    if len(parts) != 3 or any(not 0.0 <= part <= 1.0 for part in parts):
        raise ValueError("color must contain three finite RGB numbers from 0 to 1")
    return parts  # type: ignore[return-value]


def _regions(args: argparse.Namespace) -> tuple[MarkupRegion, ...]:
    default_color = _color(args.color)
    if args.region:
        regions = []
        for spec in args.region:
            try:
                page_text, values = spec.split(":", maxsplit=1)
                page = int(page_text)
                x, y, width, height = (float(number) for number in values.split(","))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"invalid region '{spec}'; expected PAGE:X,Y,W,H") from exc
            regions.append(MarkupRegion(page, Rect(x, y, width, height), color=default_color))
        return tuple(regions)
    data = json.loads(args.regions_file.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("regions")
    if not isinstance(data, list) or not data:
        raise ValueError("regions file must contain a nonempty JSON array or {'regions': [...]} object")
    regions = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"region {index} must be a JSON object")
        rect = item.get("rect", item)
        if not isinstance(rect, dict):
            raise ValueError(f"region {index} rect must be an object with x, y, width, height")
        value = item.get("color", default_color)
        color = _color(value) if isinstance(value, str) else tuple(value)
        regions.append(MarkupRegion(
            page_number=int(item["page_number"]),
            rect=Rect(*(float(rect[key]) for key in ("x", "y", "width", "height"))),
            region_id=item.get("region_id"),
            color=color,
        ))
    return tuple(regions)


def _write(value: str, path: Path | None) -> None:
    if path is None or str(path) == "-":
        print(value, end="" if value.endswith("\n") else "\n")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _progress(done: int, total: int, _page: object = None) -> None:
    print(f"Processed {done}/{total}", file=sys.stderr)


def _valid_result(result: Any) -> None:
    validation = getattr(result, "validation", None)
    valid = validation.get("valid", True) if isinstance(validation, dict) else getattr(validation, "valid", True)
    if not valid:
        raise RuntimeError("SDK reported an invalid document result; use --format json to inspect page validation details")


def _prepare_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def run(args: argparse.Namespace) -> int:
    config = _config(args)
    if args.command == "doctor":
        from .diagnostics import build_doctor_report
        _write(_json(build_doctor_report(config)), None)
        return 0

    processor = DocumentProcessor(config)
    if args.command == "capabilities":
        _write(_json(processor.capabilities()), None)
        return 0

    language = _language_kwargs(args)
    progress = _progress if getattr(args, "progress", False) else None
    if args.command in ("text", "ocr"):
        result = processor.extract_text(
            args.input, password=_password(args), **language,
            profile=OCRProfile(args.profile), routing_policy=args.routing_policy,
            page_timeout_seconds=args.page_timeout, page_progress_callback=progress,
            page_indices=_pages(args.pages),
        )
        if args.format == "json":
            _write(_json(result.to_dict()), args.output)
        elif args.pages is not None:
            _write("\n\n".join(page.text.rstrip() for page in result.pages), args.output)
        else:
            _write(processor.render_text(result), args.output)
        _valid_result(result)
        return 0

    if args.command in ("document", "structured", "markdown"):
        result = processor.extract_document(
            args.input, **language, routing_policy=args.routing_policy,
            page_progress_callback=progress,
        )
        if args.command == "markdown":
            _write(processor.to_markdown(result, emit_page_breaks=args.page_breaks), args.output)
        else:
            _write(_json(result.to_dict()), args.output)
        _valid_result(result)
        return 0

    if args.command == "searchable-pdf":
        _prepare_pdf(args.output)
        result = processor.make_searchable_pdf(args.input, args.output, **language, job_id=args.job_id)
        if args.result_json:
            _write(_json(result.to_dict()), args.result_json)
        _write(_json({"output": str(args.output), "page_count": result.source.page_count}), None)
        _valid_result(result)
        return 0

    if args.command == "markup":
        _prepare_pdf(args.output)
        result = processor.apply_markup(
            args.input, args.output, action=args.action, query=args.query,
            mode=args.mode, color=_color(args.color), **language,
            progress_callback=(lambda done, total: _progress(done, total)) if progress else None,
        )
        data = result.to_dict()
        if args.result_json:
            _write(_json(data), args.result_json)
        _write(_json(data), None)
        return 0

    if args.command == "regions":
        _prepare_pdf(args.output)
        result = processor.apply_markup_regions(
            args.input, args.output, action=args.action, regions=_regions(args),
            mode=args.mode, password=_password(args), **language,
            routing_policy=args.routing_policy, page_timeout_seconds=args.page_timeout,
            page_progress_callback=progress,
            progress_callback=(lambda done, total: _progress(done, total)) if progress else None,
        )
        data = result.to_dict()
        if args.result_json:
            _write(_json(data), args.result_json)
        _write(_json(data), None)
        return 0

    raise ValueError(f"unsupported command: {args.command}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"platen-document: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
