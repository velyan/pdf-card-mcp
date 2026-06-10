from __future__ import annotations

import json
from pathlib import Path

import pytest
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from pdf_card_mcp.converter import (
    TextBlock,
    convert_pdf_to_card_html,
    find_caption_lines_from_segments,
    merge_text_blocks,
    normalize_block_lines,
    smooth_reader_cards,
    split_chars_into_reading_order_segments,
    split_words_into_reading_order_segments,
)
from pdf_card_mcp.models import Card

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
ACTION_CHANGE_PDF = Path(
    "/Users/vel/Library/Mobile Documents/com~apple~CloudDocs/research/action-change.pdf"
)


def draw_text(
    page: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    *,
    size: int,
    color: colors.Color = colors.black,
) -> None:
    page.setFillColor(color)
    page.setFont("Times-Roman", size)
    page.drawString(x, PAGE_HEIGHT - y, text)
    page.setFillColor(colors.black)


def draw_line(
    page: canvas.Canvas,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    color: colors.Color = colors.black,
    width: float = 1.0,
) -> None:
    page.setStrokeColor(color)
    page.setLineWidth(width)
    page.line(start[0], PAGE_HEIGHT - start[1], end[0], PAGE_HEIGHT - end[1])
    page.setStrokeColor(colors.black)


def draw_rect(
    page: canvas.Canvas,
    bbox: tuple[float, float, float, float],
    *,
    stroke: colors.Color,
    fill: colors.Color,
) -> None:
    x0, top, x1, bottom = bbox
    page.setStrokeColor(stroke)
    page.setFillColor(fill)
    page.rect(x0, PAGE_HEIGHT - bottom, x1 - x0, bottom - top, stroke=1, fill=1)
    page.setStrokeColor(colors.black)
    page.setFillColor(colors.black)


def make_unspaced_chars(
    text: str,
    *,
    x: float = 72.0,
    top: float = 120.0,
    size: float = 10.0,
) -> list[dict[str, float | str | bool]]:
    chars: list[dict[str, float | str | bool]] = []
    cursor = x
    for character in text:
        if character == " ":
            cursor += size * 0.22
            continue
        width = size * (0.22 if character in ".,;:!?)" else 0.45)
        chars.append(
            {
                "text": character,
                "x0": cursor,
                "x1": cursor + width,
                "top": top,
                "bottom": top + size,
                "size": size,
                "upright": True,
            }
        )
        cursor += width
    return chars


def make_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Sample Table Paper", size=18)
    draw_text(
        page,
        72,
        112,
        "This paragraph should become readable card text without changing the source words.",
        size=12,
    )
    draw_text(page, 72, 154, "Table 1. Accuracy by model", size=11)

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
        draw_line(page, (x0, y), (x0 + total_width, y), width=0.8)
    current_x = x0
    for width in [0, *col_widths]:
        if width:
            current_x += width
        draw_line(page, (current_x, y0), (current_x, y0 + total_height), width=0.8)
    for row_index, row in enumerate(rows):
        current_x = x0 + 8
        for col_index, value in enumerate(row):
            draw_text(
                page,
                current_x,
                y0 + 19 + row_index * row_height,
                value,
                size=10,
            )
            current_x += col_widths[col_index]

    draw_text(page, 72, 310, "Conclusion", size=16)
    draw_text(page, 72, 340, "The reader keeps table layout available as an image.", size=12)
    page.save()


def make_column_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Two Column Table Paper", size=18)
    draw_text(page, 72, 126, "Table 1. Ablation study on candidate settings.", size=11)
    rows = [
        ("Model", "All", "Selected"),
        ("GPT-5", "41.04", "46.23"),
        ("Gemini", "20.23", "11.79"),
        ("Qwen", "40.46", "47.64"),
    ]
    y = 158
    for model, all_tools, selected in rows:
        draw_text(page, 72, y, model, size=10)
        draw_text(page, 170, y, all_tools, size=10)
        draw_text(page, 230, y, selected, size=10)
        y += 18
    draw_text(
        page,
        330,
        158,
        "This neighboring prose should not be included in the table crop.",
        size=12,
    )
    draw_text(
        page,
        330,
        176,
        "It sits in the right column beside the table.",
        size=12,
    )
    draw_text(page, 72, 252, "Body text resumes below the table.", size=12)
    page.save()


def make_figure_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Sample Figure Paper", size=18)
    draw_text(page, 72, 95, "arXiv:2606.02470v1 [cs.AI] 1 Jun 2026", size=9)
    draw_text(page, 72, 115, "*Equal contribution Project lead Example University", size=9)
    draw_rect(
        page,
        (130, 150, 482, 330),
        stroke=colors.Color(0.5, 0.2, 0.35),
        fill=colors.Color(0.95, 0.88, 0.9),
    )
    draw_line(
        page,
        (160, 295),
        (450, 185),
        color=colors.Color(0.2, 0.4, 0.35),
        width=2,
    )
    draw_text(page, 160, 210, "Vector diagram", size=20, color=colors.Color(0.2, 0.2, 0.2))
    draw_text(page, 72, 360, "Figure 1. A vector diagram that is not an embedded bitmap.", size=11)
    draw_text(page, 72, 400, "The captioned graphic should become an image card.", size=12)
    draw_text(page, 306, 760, "1", size=9)
    page.save()


def make_column_figure_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Two Column Figure Paper", size=18)
    draw_text(page, 120, 130, "Diagram title", size=12)
    draw_rect(
        page,
        (72, 150, 286, 276),
        stroke=colors.Color(0.2, 0.45, 0.32),
        fill=colors.Color(0.90, 0.95, 0.90),
    )
    draw_rect(
        page,
        (94, 178, 154, 222),
        stroke=colors.Color(0.35, 0.35, 0.65),
        fill=colors.Color(0.88, 0.90, 0.98),
    )
    draw_rect(
        page,
        (198, 178, 258, 222),
        stroke=colors.Color(0.65, 0.42, 0.25),
        fill=colors.Color(0.98, 0.92, 0.85),
    )
    draw_line(
        page,
        (154, 200),
        (198, 200),
        color=colors.Color(0.2, 0.45, 0.32),
        width=2,
    )
    draw_text(page, 105, 204, "Input", size=10)
    draw_text(page, 207, 204, "Output", size=10)
    draw_text(
        page,
        330,
        154,
        "This neighboring prose should not be included in the figure crop.",
        size=12,
    )
    draw_text(
        page,
        330,
        176,
        "It sits beside the visual in a separate text column.",
        size=12,
    )
    draw_text(page, 72, 304, "Figure 1. A left-column diagram with a caption", size=11)
    draw_text(
        page,
        330,
        304,
        "Right column prose sharing the caption baseline.",
        size=12,
    )
    draw_text(page, 72, 318, "that continues onto a second line.", size=11)
    draw_text(page, 72, 356, "Body text resumes below the figure.", size=12)
    page.save()


def make_narrow_figure_caption_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Narrow Figure Paper", size=18)
    draw_rect(
        page,
        (72, 140, 170, 230),
        stroke=colors.Color(0.2, 0.45, 0.32),
        fill=colors.Color(0.90, 0.95, 0.90),
    )
    draw_text(page, 90, 185, "Box", size=12)
    draw_text(
        page,
        72,
        260,
        "Figure 1. This caption is deliberately much wider than the small graphic and should stay intact.",
        size=11,
    )
    draw_text(page, 72, 320, "Next paragraph should remain separate.", size=12)
    page.save()


def make_uncaptioned_visual_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Uncaptioned Visual Paper", size=18)
    draw_rect(
        page,
        (72, 140, 540, 310),
        stroke=colors.Color(0.35, 0.35, 0.65),
        fill=colors.Color(0.92, 0.94, 0.98),
    )
    draw_line(page, (100, 280), (500, 170), color=colors.Color(0.2, 0.45, 0.32), width=2)
    draw_text(page, 72, 360, "This large vector block has no figure caption.", size=12)
    page.save()


def make_blank_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    page.showPage()
    page.save()


def make_formula_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Sample Formula Paper", size=18)
    draw_text(
        page,
        72,
        120,
        "The transition function is represented below.",
        size=12,
    )
    draw_text(
        page,
        220,
        166,
        "f_t : (C_current, x) -> (C_new, y),",
        size=12,
    )
    draw_text(
        page,
        72,
        214,
        "The screenshot should preserve the equation layout.",
        size=12,
    )
    page.save()


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


def test_heuristic_table_crop_excludes_neighboring_column_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "column-table.pdf"
    html_path = tmp_path / "column-reader.html"
    make_column_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Columns")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    x0, top, x1, bottom = table_asset["bbox"]
    assert x0 < 75
    assert x1 < 310
    assert top > 126
    assert bottom < 245


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


def test_heuristic_figure_crop_excludes_caption_and_neighboring_column_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "column-figure.pdf"
    html_path = tmp_path / "column-figure-reader.html"
    make_column_figure_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Column Figure")

    assert result.figure_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    figure_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "figure")
    x0, top, x1, bottom = figure_asset["bbox"]
    assert x0 < 80
    assert top < 140
    assert x1 < 305
    assert bottom < 300
    assert "Right column prose" not in figure_asset["caption"]
    assert "continues onto a second line" in figure_asset["caption"]

    paragraph_texts = [
        card["text"]
        for card in manifest["cards"]
        if card["kind"] == "paragraph"
    ]
    assert any("neighboring prose should not be included" in text for text in paragraph_texts)
    assert any("Right column prose sharing the caption baseline" in text for text in paragraph_texts)


def test_figure_caption_can_be_wider_than_graphic(tmp_path: Path) -> None:
    pdf_path = tmp_path / "narrow-figure-caption.pdf"
    html_path = tmp_path / "narrow-figure-reader.html"
    make_narrow_figure_caption_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Narrow Figure")

    assert result.figure_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    figure_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "figure")
    assert figure_asset["caption"] == (
        "Figure 1. This caption is deliberately much wider than the small graphic and should stay intact."
    )
    paragraph_texts = [
        card["text"]
        for card in manifest["cards"]
        if card["kind"] == "paragraph"
    ]
    assert any("Next paragraph should remain separate." in text for text in paragraph_texts)


def test_uncaptioned_vector_objects_do_not_become_figure_cards(tmp_path: Path) -> None:
    pdf_path = tmp_path / "uncaptioned-visual.pdf"
    html_path = tmp_path / "uncaptioned-reader.html"
    make_uncaptioned_visual_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Uncaptioned")

    assert result.figure_count == 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert not any(asset["kind"] == "figure" for asset in manifest["assets"])


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


def test_converter_warns_when_no_readable_cards_are_produced(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank.pdf"
    make_blank_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=tmp_path / "blank.html", title="Blank")

    assert result.card_count == 0
    assert any("No readable cards" in warning for warning in result.warnings)
    assert any("ocr=true" in warning for warning in result.warnings)


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


def test_char_geometry_recovers_spaces_from_character_gaps() -> None:
    chars = make_unspaced_chars(
        "2 A system is Markovian if the transition of the system to any given state depends only on the current state",
        top=735,
        size=8,
    )

    segments = split_chars_into_reading_order_segments(
        chars,
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )

    assert segments[0]["text"] == (
        "2 A system is Markovian if the transition of the system to any given state "
        "depends only on the current state"
    )
    assert "AsystemisMarkovian" not in segments[0]["text"]


def test_char_geometry_marks_bottom_small_type_as_footnote() -> None:
    chars = [
        *make_unspaced_chars(
            "Taking observations into account concerns two distinct stages.",
            top=640,
            size=10,
        ),
        *make_unspaced_chars(
            "2 A system is Markovian if the transition depends only on the current state",
            top=735,
            size=8,
        ),
        *make_unspaced_chars("and not on the previous ones.", top=746, size=8),
    ]

    blocks = [
        TextBlock(page=1, bbox=segment["bbox"], text=segment["text"], kind=segment["kind"])
        for segment in split_chars_into_reading_order_segments(
            chars,
            page_width=PAGE_WIDTH,
            page_height=PAGE_HEIGHT,
        )
    ]
    merged = merge_text_blocks(blocks)

    assert [block.kind for block in merged] == ["text", "footnote"]
    assert merged[1].text == (
        "2 A system is Markovian if the transition depends only on the current state "
        "and not on the previous ones."
    )


def test_char_geometry_splits_close_two_column_rows_and_repairs_captions() -> None:
    chars = [
        *make_unspaced_chars("left column text", x=72, top=140, size=10),
        *make_unspaced_chars("right column text", x=225, top=140, size=10),
        *make_unspaced_chars("Figure 3. In MemGPT, a fixed context LLM processor", x=72, top=180, size=9),
    ]

    segments = split_chars_into_reading_order_segments(
        chars,
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )
    segment_texts = [segment["text"] for segment in segments]
    captions = find_caption_lines_from_segments(segments, "Figure")

    assert "left column text" in segment_texts
    assert "right column text" in segment_texts
    assert captions[0]["text"] == "Figure 3. In MemGPT, a fixed context LLM processor"


def test_wrapped_hyphenation_keeps_real_short_hyphen_terms() -> None:
    assert normalize_block_lines(["The observa-", "tions work."]) == "The observations work."
    assert normalize_block_lines(["The off-", "line stage."]) == "The off-line stage."


def test_action_change_regression_repairs_fused_words_and_separates_footnote(
    tmp_path: Path,
) -> None:
    if not ACTION_CHANGE_PDF.exists():
        pytest.skip("local action-change.pdf fixture is not available")

    result = convert_pdf_to_card_html(
        ACTION_CHANGE_PDF,
        output_path=tmp_path / "action-change-reader.html",
        title="Action Change",
        max_pages=3,
        table_engine="pdfplumber",
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    all_text = " ".join(card["text"] for card in manifest["cards"])
    assert "AsystemisMarkovian" not in all_text
    assert "actionandchangewasmade" not in all_text
    assert (
        "A system is Markovian if the transition of the system to any given state "
        "depends only on the current state"
    ) in all_text
    assert any(
        card["kind"] == "footnote" and "2 A system is Markovian" in card["text"]
        for card in manifest["cards"]
    )


def test_source_and_tests_do_not_import_pymupdf() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = (
        "import " + "fitz",
        "from " + "fitz",
        "import " + "pymupdf",
        "from " + "pymupdf",
    )
    checked_paths = [
        *sorted((root / "src").rglob("*.py")),
        *sorted((root / "tests").rglob("*.py")),
    ]
    offenders = [
        str(path.relative_to(root))
        for path in checked_paths
        if any(token in path.read_text(encoding="utf-8").lower() for token in forbidden)
    ]
    assert offenders == []


def test_reader_smoothing_merges_fragment_cards_and_drops_visual_noise() -> None:
    cards = [
        Card(
            id="card-1",
            kind="paragraph",
            page=1,
            section="Abstract",
            text="The model connects",
            source_image_id="source-page-1",
            bbox=(72, 120, 260, 136),
        ),
        Card(
            id="card-2",
            kind="paragraph",
            page=1,
            section="Abstract",
            text="external tools to language models.",
            source_image_id="source-page-1",
            bbox=(72, 138, 310, 154),
        ),
        Card(
            id="card-3",
            kind="paragraph",
            page=1,
            section="Abstract",
            text="92.7 69.1",
            source_image_id="source-page-1",
            bbox=(310, 160, 380, 176),
        ),
    ]

    smoothed = smooth_reader_cards(cards, max_words_per_card=95)

    assert [card.text for card in smoothed] == [
        "The model connects external tools to language models."
    ]
    assert smoothed[0].id == "card-1"


def test_reading_order_segments_prefer_column_order_over_row_interleave() -> None:
    words = [
        {"text": "Left", "x0": 72, "x1": 95, "top": 100, "bottom": 112},
        {"text": "one", "x0": 100, "x1": 120, "top": 100, "bottom": 112},
        {"text": "Right", "x0": 330, "x1": 360, "top": 100, "bottom": 112},
        {"text": "one", "x0": 365, "x1": 385, "top": 100, "bottom": 112},
        {"text": "Left", "x0": 72, "x1": 95, "top": 122, "bottom": 134},
        {"text": "two", "x0": 100, "x1": 122, "top": 122, "bottom": 134},
        {"text": "Right", "x0": 330, "x1": 360, "top": 122, "bottom": 134},
        {"text": "two", "x0": 365, "x1": 388, "top": 122, "bottom": 134},
        {"text": "Left", "x0": 72, "x1": 95, "top": 144, "bottom": 156},
        {"text": "three", "x0": 100, "x1": 135, "top": 144, "bottom": 156},
        {"text": "Right", "x0": 330, "x1": 360, "top": 144, "bottom": 156},
        {"text": "three", "x0": 365, "x1": 402, "top": 144, "bottom": 156},
        {"text": "Left", "x0": 72, "x1": 95, "top": 166, "bottom": 178},
        {"text": "four", "x0": 100, "x1": 128, "top": 166, "bottom": 178},
        {"text": "Right", "x0": 330, "x1": 360, "top": 166, "bottom": 178},
        {"text": "four", "x0": 365, "x1": 393, "top": 166, "bottom": 178},
        {"text": "Left", "x0": 72, "x1": 95, "top": 188, "bottom": 200},
        {"text": "five", "x0": 100, "x1": 126, "top": 188, "bottom": 200},
        {"text": "Right", "x0": 330, "x1": 360, "top": 188, "bottom": 200},
        {"text": "five", "x0": 365, "x1": 391, "top": 188, "bottom": 200},
    ]

    segments = split_words_into_reading_order_segments(words, page_width=612)

    assert [segment["text"] for segment in segments] == [
        "Left one",
        "Left two",
        "Left three",
        "Left four",
        "Left five",
        "Right one",
        "Right two",
        "Right three",
        "Right four",
        "Right five",
    ]
