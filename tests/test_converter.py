from __future__ import annotations

import json
from pathlib import Path

import fitz

from pdf_card_mcp.converter import TextBlock, convert_pdf_to_card_html, merge_text_blocks


def make_table_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Sample Table Paper", fontsize=18)
    page.insert_text(
        (72, 112),
        "This paragraph should become readable card text without changing the source words.",
        fontsize=12,
    )
    page.insert_text((72, 154), "Table 1. Accuracy by model", fontsize=11)

    x0, y0 = 72, 176
    col_widths = [150, 120, 120]
    row_height = 28
    rows = [
        ["Model", "Accuracy", "Latency"],
        ["Baseline", "81.2", "220"],
        ["Reader", "88.4", "180"],
    ]
    total_width = sum(col_widths)
    total_height = row_height * len(rows)

    for row in range(len(rows) + 1):
        y = y0 + row * row_height
        page.draw_line((x0, y), (x0 + total_width, y), color=(0, 0, 0), width=0.8)
    current_x = x0
    for width in [0, *col_widths]:
        if width:
            current_x += width
        page.draw_line((current_x, y0), (current_x, y0 + total_height), color=(0, 0, 0), width=0.8)
    for row_index, row in enumerate(rows):
        current_x = x0 + 8
        for col_index, value in enumerate(row):
            page.insert_text(
                (current_x, y0 + 19 + row_index * row_height),
                value,
                fontsize=10,
            )
            current_x += col_widths[col_index]

    page.insert_text((72, 310), "Conclusion", fontsize=16)
    page.insert_text((72, 340), "The reader keeps table layout available as an image.", fontsize=12)
    document.save(path)
    document.close()


def make_figure_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Sample Figure Paper", fontsize=18)
    page.insert_text((72, 95), "arXiv:2606.02470v1 [cs.AI] 1 Jun 2026", fontsize=9)
    page.insert_text((72, 115), "*Equal contribution Project lead Example University", fontsize=9)
    page.draw_rect((130, 150, 482, 330), color=(0.5, 0.2, 0.35), fill=(0.95, 0.88, 0.9))
    page.draw_line((160, 295), (450, 185), color=(0.2, 0.4, 0.35), width=2)
    page.insert_text((160, 210), "Vector diagram", fontsize=20, color=(0.2, 0.2, 0.2))
    page.insert_text((72, 360), "Figure 1. A vector diagram that is not an embedded bitmap.", fontsize=11)
    page.insert_text((72, 400), "The captioned graphic should become an image card.", fontsize=12)
    page.insert_text((306, 760), "1", fontsize=9)
    document.save(path)
    document.close()


def make_formula_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((72, 72), "Sample Formula Paper", fontsize=18)
    page.insert_text(
        (72, 120),
        "The transition function is represented below.",
        fontsize=12,
    )
    page.insert_text(
        (220, 166),
        "f_t : (C_current, x) -> (C_new, y),",
        fontsize=12,
    )
    page.insert_text(
        (72, 214),
        "The screenshot should preserve the equation layout.",
        fontsize=12,
    )
    document.save(path)
    document.close()


def test_converter_embeds_detected_tables_as_images(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample-table.pdf"
    html_path = tmp_path / "reader.html"
    make_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Sample")

    assert result.html_path == html_path
    assert result.html_path.exists()
    assert result.manifest_path.exists()
    assert result.table_count >= 1
    assert result.card_count >= 3

    html = html_path.read_text(encoding="utf-8")
    assert "data:image/png;base64" in html
    assert "Table 1. Accuracy by model" in html
    assert "Source page" in html

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["table_count"] >= 1
    assert any(asset["kind"] == "table" for asset in manifest["assets"])
    assert all("data_uri" not in asset for asset in manifest["assets"])


def test_converter_embeds_captioned_vector_figures_as_images(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample-figure.pdf"
    html_path = tmp_path / "figure-reader.html"
    make_figure_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Figure Sample")

    assert result.figure_count >= 1
    html = html_path.read_text(encoding="utf-8")
    assert "Figure 1. A vector diagram" in html
    assert '"kind": "figure"' in html
    assert "data:image/png;base64" in html

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    paragraph_texts = [
        card["text"]
        for card in manifest["cards"]
        if card["kind"] == "paragraph"
    ]
    assert "Vector diagram" not in paragraph_texts
    assert "1" not in paragraph_texts
    assert not any(text.startswith("arXiv:") for text in paragraph_texts)
    assert not any(text.startswith("*Equal contribution") for text in paragraph_texts)


def test_converter_embeds_display_formulas_as_images(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample-formula.pdf"
    html_path = tmp_path / "formula-reader.html"
    make_formula_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Formula Sample")

    assert result.formula_count >= 1
    html = html_path.read_text(encoding="utf-8")
    assert '"kind": "formula"' in html
    assert "Formula" in html
    assert "data:image/png;base64" in html

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["formula_count"] >= 1
    assert any(asset["kind"] == "formula" for asset in manifest["assets"])
    paragraph_texts = [
        card["text"]
        for card in manifest["cards"]
        if card["kind"] == "paragraph"
    ]
    assert not any("C_current" in text for text in paragraph_texts)


def test_converter_reports_missing_pdf(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"
    try:
        convert_pdf_to_card_html(missing)
    except FileNotFoundError as error:
        assert str(missing) in str(error)
    else:
        raise AssertionError("Expected FileNotFoundError")


def test_merge_text_blocks_repairs_cross_column_continuations() -> None:
    blocks = [
        TextBlock(
            page=1,
            bbox=(55.0, 566.0, 289.0, 588.0),
            text="The Model Context Protocol connects large language",
        ),
        TextBlock(
            page=1,
            bbox=(307.0, 207.0, 543.0, 349.0),
            text="models with external tools and data sources.",
        ),
        TextBlock(
            page=1,
            bbox=(307.0, 357.0, 543.0, 522.0),
            text="2. Related Work",
        ),
    ]

    merged = merge_text_blocks(blocks)

    assert len(merged) == 2
    assert merged[0].text == (
        "The Model Context Protocol connects large language models with external tools and data sources."
    )
    assert merged[1].text == "2. Related Work"
