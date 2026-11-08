"""CLI contract tests: commands use the public SDK without PDFNest services."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from platen_document import cli


class FakeDocumentProcessor:
    def __init__(self):
        self.calls = []
        self.result = SimpleNamespace(
            pages=[SimpleNamespace(text="hello world\n")],
            source=SimpleNamespace(page_count=1),
            validation=SimpleNamespace(valid=True),
            to_dict=lambda: {"schema_version": "ocr_v2.1", "pages": [{"text": "hello world"}]},
        )
        self.structured = SimpleNamespace(
            validation={"valid": True},
            to_dict=lambda: {"pages": [{"elements": [{"type": "PARAGRAPH"}]}]},
        )

    def extract_text(self, path, **kwargs):
        self.calls.append(("extract_text", path, kwargs))
        return self.result

    def render_text(self, result):
        self.calls.append(("render_text", result))
        return "hello world\n"

    def extract_document(self, path, **kwargs):
        self.calls.append(("extract_document", path, kwargs))
        return self.structured

    def to_markdown(self, result, **kwargs):
        self.calls.append(("to_markdown", result, kwargs))
        return "# Hello\n"

    def make_searchable_pdf(self, source, output, **kwargs):
        self.calls.append(("make_searchable_pdf", source, output, kwargs))
        return self.result

    def apply_markup(self, source, output, **kwargs):
        self.calls.append(("apply_markup", source, output, kwargs))
        return SimpleNamespace(to_dict=lambda: {"selection_count": 2})

    def apply_markup_regions(self, source, output, **kwargs):
        self.calls.append(("apply_markup_regions", source, output, kwargs))
        return SimpleNamespace(to_dict=lambda: {"annotation_count": 1})

    def capabilities(self):
        return {"capabilities": {"native_pdf_extraction": True}}


@pytest.fixture
def fake(monkeypatch):
    processor = FakeDocumentProcessor()
    monkeypatch.setattr(cli, "DocumentProcessor", lambda _config: processor)
    return processor


def test_commands_exist_and_doctor_still_works(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["-h"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for name in ("doctor", "capabilities", "ocr", "text", "document", "markdown", "searchable-pdf", "markup", "regions"):
        assert name in output


def test_text_prints_validated_sdk_output(fake, capsys):
    assert cli.main(["text", "source.pdf", "--language", "tam"]) == 0
    assert capsys.readouterr().out == "hello world\n"
    name, path, kwargs = fake.calls[0]
    assert name == "extract_text" and str(path) == "source.pdf"
    assert kwargs["language"] == "tam"
    assert kwargs["routing_policy"] == "AUTO"
    assert fake.calls[1][0] == "render_text"


def test_ocr_forces_visual_recognition_by_default(fake, capsys):
    assert cli.main(["ocr", "source.pdf", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == "ocr_v2.1"
    assert fake.calls[0][2]["routing_policy"] == "FORCE_OCR"


def test_explicit_pages_are_one_based_and_do_not_require_full_document(fake, capsys):
    assert cli.main(["text", "a.pdf", "--pages", "1,3-4"]) == 0
    assert fake.calls[0][2]["page_indices"] == (0, 2, 3)
    assert not any(call[0] == "render_text" for call in fake.calls)
    assert "hello world" in capsys.readouterr().out


def test_structured_and_markdown_use_public_sdk(fake, tmp_path):
    out = tmp_path / "nested" / "output.md"
    assert cli.main(["markdown", "a.pdf", "-o", str(out), "--no-page-breaks", "--routing-policy", "FAST"]) == 0
    assert out.read_text() == "# Hello\n"
    assert fake.calls[0][2]["routing_policy"] == "FAST"
    assert fake.calls[1][2]["emit_page_breaks"] is False
    assert cli.main(["document", "a.pdf", "-o", str(tmp_path / "out.json")]) == 0
    assert json.loads((tmp_path / "out.json").read_text())["pages"]


def test_searchable_pdf_passes_output_to_public_sdk(fake, tmp_path, capsys):
    target = tmp_path / "nested" / "out.pdf"
    metadata = tmp_path / "details.json"
    assert cli.main(["searchable-pdf", "a.pdf", str(target), "--result-json", str(metadata)]) == 0
    assert fake.calls[0][0] == "make_searchable_pdf"
    assert fake.calls[0][2] == target
    assert metadata.is_file()
    assert json.loads(capsys.readouterr().out)["output"] == str(target)


def test_markup_passes_query_mode_color(fake, tmp_path, capsys):
    assert cli.main(["markup", "a.pdf", str(tmp_path / "out.pdf"), "--action", "highlight", "--query", "Invoice", "--color", "#ff0000"]) == 0
    details = fake.calls[0][-1]
    assert details["query"] == "Invoice"
    assert details["color"] == (1.0, 0.0, 0.0)
    assert json.loads(capsys.readouterr().out)["selection_count"] == 2


def test_regions_support_manual_geometry_and_json_file(fake, tmp_path):
    target = str(tmp_path / "out.pdf")
    assert cli.main(["regions", "a.pdf", target, "--action", "underline", "--mode", "manual", "--region", "1:72,144,180,18"]) == 0
    details = fake.calls[0][-1]
    assert details["mode"] == "manual"
    assert details["regions"][0].page_number == 1
    assert details["regions"][0].rect.width == 180

    region_path = tmp_path / "regions.json"
    region_path.write_text(json.dumps({"regions": [{"page_number": 2, "rect": {"x": 4, "y": 5, "width": 6, "height": 7}, "color": "#00ff00", "region_id": "a"}]}))
    assert cli.main(["regions", "a.pdf", target, "--action", "highlight", "--regions-file", str(region_path)]) == 0
    assert fake.calls[1][-1]["regions"][0].region_id == "a"
    assert fake.calls[1][-1]["regions"][0].color == (0.0, 1.0, 0.0)


def test_invalid_color_returns_error(fake, tmp_path, capsys):
    assert cli.main(["markup", "a.pdf", str(tmp_path / "out.pdf"), "--action", "highlight", "--query", "x", "--color", "1,2,3"]) == 1
    assert "color" in capsys.readouterr().err.lower()
    assert not fake.calls


def test_capabilities_command_uses_processor(fake, capsys):
    assert cli.main(["capabilities"]) == 0
    assert json.loads(capsys.readouterr().out)["capabilities"]["native_pdf_extraction"] is True


def test_bad_pages_return_error(fake, capsys):
    assert cli.main(["ocr", "file.pdf", "--pages", "0"]) == 1
    assert "positive" in capsys.readouterr().err
