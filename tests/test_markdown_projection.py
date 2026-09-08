from __future__ import annotations

from types import SimpleNamespace

from platen_document.engine.structured import (
    StructuredElement,
    StructuredElementType,
    _native_elements,
    render_structured_markdown,
)


def _result(*pages: tuple[StructuredElement, ...]) -> object:
    page_values = []
    all_elements = []
    for page_index, elements in enumerate(pages):
        page_values.append(SimpleNamespace(
            page_index=page_index,
            geometry={"width": 600.0, "height": 400.0},
            elements=elements,
            reading_order=tuple(element.element_id for element in elements),
        ))
        all_elements.extend(elements)
    return SimpleNamespace(pages=tuple(page_values), elements=tuple(all_elements))


def _element(element_id: str, element_type: StructuredElementType, **kwargs: object) -> StructuredElement:
    return StructuredElement(element_id=element_id, type=element_type, page_index=0, **kwargs)


def test_markdown_table_is_one_contiguous_safe_gfm_block() -> None:
    table = _element(
        "table-0",
        StructuredElementType.TABLE,
        data={
            "headers": [{"text": "Name"}, {"text": "Notes"}, {"text": "Amount"}],
            "rows": [
                [{"text": "Smith"}, {"text": "line one\nline two"}, {"text": "10"}],
                [{"text": "Doe"}, {"text": "A | B"}, {"text": ""}],
            ],
        },
    )

    markdown = render_structured_markdown(_result((table,)))

    assert markdown == (
        "| Name | Notes | Amount |\n"
        "| --- | --- | --- |\n"
        "| Smith | line one<br>line two | 10 |\n"
        "| Doe | A \\| B |  |\n"
    )
    assert "\n\n|" not in markdown


def test_markdown_normalizes_existing_list_markers_and_page_breaks() -> None:
    unordered = _element(
        "list-0",
        StructuredElementType.LIST,
        ordered=False,
        data={"items": [{"text": "- First item"}, {"text": "* Second item"}]},
    )
    ordered = _element(
        "list-1",
        StructuredElementType.LIST,
        ordered=True,
        data={"items": [{"text": "1. First ordered"}, {"text": "2. Second ordered"}]},
    )
    page_one = _element("paragraph-1", StructuredElementType.PARAGRAPH, text="Page one")
    page_two = StructuredElement("paragraph-2", StructuredElementType.PARAGRAPH, page_index=1, text="Page two")

    markdown = render_structured_markdown(_result((page_one, unordered, ordered), (page_two,)))

    assert markdown == (
        "Page one\n\n"
        "- First item\n"
        "- Second item\n\n"
        "1. First ordered\n"
        "2. Second ordered\n\n"
        "<!-- pagebreak -->\n\n"
        "Page two\n"
    )
    assert "- -" not in markdown
    assert "1. 1." not in markdown


def test_native_line_geometry_reconstructs_column_order() -> None:
    class FakePage:
        def get_text(self, mode: str) -> dict[str, object]:
            assert mode == "dict"
            return {
                    "blocks": [{
                        "type": 0,
                        "bbox": (40.0, 80.0, 410.0, 140.0),
                        "lines": [
                            {"bbox": (40.0, 80.0, 80.0, 90.0), "spans": [{"text": "Left one", "size": 10.0, "font": "Helvetica", "flags": 0, "bbox": (40.0, 80.0, 80.0, 90.0)}]},
                            {"bbox": (320.0, 81.0, 380.0, 91.0), "spans": [{"text": "Right one", "size": 10.0, "font": "Helvetica", "flags": 0, "bbox": (320.0, 81.0, 380.0, 91.0)}]},
                            {"bbox": (40.0, 100.0, 80.0, 110.0), "spans": [{"text": "Left two", "size": 10.0, "font": "Helvetica", "flags": 0, "bbox": (40.0, 100.0, 80.0, 110.0)}]},
                            {"bbox": (320.0, 101.0, 380.0, 111.0), "spans": [{"text": "Right two", "size": 10.0, "font": "Helvetica", "flags": 0, "bbox": (320.0, 101.0, 380.0, 111.0)}]},
                            {"bbox": (40.0, 120.0, 85.0, 130.0), "spans": [{"text": "Left three", "size": 10.0, "font": "Helvetica", "flags": 0, "bbox": (40.0, 120.0, 85.0, 130.0)}]},
                            {"bbox": (320.0, 121.0, 390.0, 131.0), "spans": [{"text": "Right three", "size": 10.0, "font": "Helvetica", "flags": 0, "bbox": (320.0, 121.0, 390.0, 131.0)}]},
                        ],
                    }],
                }

    elements = _native_elements(FakePage(), 0, 10.0)
    result = _result(tuple(elements))

    assert render_structured_markdown(result) == "Left one Left two Left three\n\nRight one Right two Right three\n"
