from __future__ import annotations

import json
from pathlib import Path

import pytest
from reportlab.lib import colors
from reportlab.pdfgen import canvas

from pdf_card_mcp.converter import (
    TextBlock,
    convert_pdf_to_card_html,
    extract_algorithm_blocks,
    extract_formula_blocks,
    find_caption_lines_from_segments,
    has_unreadable_pdf_glyphs,
    is_formula_text_line,
    looks_like_heading,
    looks_like_reader_noise,
    merge_text_blocks,
    normalize_block_lines,
    normalize_pdfium_control_chars,
    normalize_text,
    region_contains_text_block,
    slice_caption_from_segment,
    smooth_reader_cards,
    split_chars_into_reading_order_segments,
    split_words_into_reading_order_segments,
    strip_orphan_math_prefix,
)
from pdf_card_mcp.models import Card
from pdf_card_mcp.pdf_backend import PageRect

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


def make_visual_abstract_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Visual Abstract Paper", size=18)
    draw_text(page, 72, 108, "Ada Example", size=11)
    draw_text(page, 72, 145, "Abstract", size=13)
    draw_text(
        page,
        72,
        172,
        "The abstract should be read before the nearby figure card appears.",
        size=11,
    )
    draw_text(
        page,
        72,
        190,
        "It explains the paper without being interrupted by a visual.",
        size=11,
    )
    draw_rect(
        page,
        (330, 145, 520, 292),
        stroke=colors.Color(0.25, 0.35, 0.55),
        fill=colors.Color(0.9, 0.92, 0.98),
    )
    draw_text(page, 370, 210, "Plot", size=20)
    draw_text(page, 330, 316, "Figure 1. A visual summary.", size=10)
    draw_text(page, 72, 350, "1 Introduction", size=14)
    draw_text(page, 72, 378, "The introduction follows the abstract and visual summary.", size=11)
    page.save()


def make_wrapped_title_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "LORA: LOW-RANK ADAPTATION OF LARGE LAN-", size=18)
    draw_text(page, 72, 96, "GUAGE MODELS Edward Hu Yelong Shen", size=12)
    draw_text(page, 72, 138, "ABSTRACT", size=13)
    draw_text(page, 72, 166, "The abstract remains readable after the wrapped title.", size=11)
    page.save()


def make_visual_wrapped_title_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "LORA: LOW-RANK ADAPTATION OF LARGE LAN-", size=18)
    draw_text(page, 72, 96, "GUAGE MODELS", size=18)
    draw_text(page, 72, 124, "Edward Hu Yelong Shen", size=11)
    draw_text(page, 72, 160, "ABSTRACT", size=13)
    draw_text(page, 72, 188, "The abstract remains readable after the wrapped title.", size=11)
    page.save()


def make_masthead_title_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 28, "Published as a conference paper at ICLR 2023", size=9)
    draw_text(page, 72, 78, "REACT: SYNERGIZING REASONING AND ACTING IN", size=18)
    draw_text(page, 72, 101, "LANGUAGE MODELS", size=18)
    draw_text(page, 72, 132, "Shunyu Yao, Jeffrey Zhao, Dian Yu", size=11)
    draw_text(page, 72, 170, "ABSTRACT", size=13)
    draw_text(page, 72, 198, "The abstract should be the first substantive reader text.", size=11)
    page.showPage()
    draw_text(page, 72, 28, "Published as a conference paper at ICLR 2023", size=9)
    draw_text(page, 72, 78, "2 METHOD", size=13)
    draw_text(page, 72, 106, "The second page body should not inherit the repeated masthead.", size=11)
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


def make_multiline_formula_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Sample Multi-line Formula Paper", size=18)
    draw_text(page, 72, 120, "The optimizer maximizes the following objective:", size=12)
    draw_text(
        page,
        120,
        158,
        "J_GRPO(theta) = E[q ~ P(Q), {o_i}_{i=1}^G ~ pi_old(O|q)]",
        size=12,
    )
    draw_text(
        page,
        118,
        180,
        "1/G sum_i min(pi_theta(o_i|q)/pi_old(o_i|q) A_i, clip(...)) - beta D_KL(pi||pi_ref), (1)",
        size=12,
    )
    draw_text(
        page,
        158,
        204,
        "D_KL(pi||pi_ref) = pi_ref(o_i|q)/pi_theta(o_i|q) - log pi_ref(o_i|q)/pi_theta(o_i|q) - 1, (2)",
        size=12,
    )
    draw_text(
        page,
        72,
        246,
        "where epsilon and beta are hyper-parameters computed using a group of rewards.",
        size=12,
    )
    draw_text(
        page,
        188,
        292,
        "A_i = (r_i - mean({r_1, r_2, ..., r_G})) / std({r_1, r_2, ..., r_G}). (3)",
        size=12,
    )
    draw_text(page, 72, 340, "The discussion continues after the displayed equations.", size=12)
    page.save()


def make_algorithm_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Sample Algorithm Paper", size=18)
    draw_text(page, 72, 120, "The verifier uses the following procedure.", size=12)
    draw_text(page, 150, 162, "Algorithm 1 Draft verification", size=12)
    draw_text(page, 150, 184, "Require: draft tokens and target model", size=12)
    draw_text(page, 150, 206, "1: initialize accepted tokens", size=12)
    draw_text(page, 150, 228, "2: while token budget remains do", size=12)
    draw_text(page, 150, 250, "3: return accepted tokens", size=12)
    draw_text(page, 72, 302, "The prose resumes after the algorithm.", size=12)
    page.save()


def make_footnote_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Sample Footnote Paper", size=18)
    draw_text(page, 72, 130, "Main body text should remain in the reader.", size=12)
    draw_text(
        page,
        72,
        735,
        "1 Contact author@example.com -> footer text should not become a reader card.",
        size=8,
    )
    draw_text(page, 72, 746, "It remains available on the source page image.", size=8)
    page.save()


def make_contents_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Contents", size=16)
    draw_text(
        page,
        72,
        120,
        "1 Introduction . . . . . . . . . . . . . . . . . . . . . . . 2",
        size=12,
    )
    draw_text(
        page,
        90,
        145,
        "1.1 Scope . . . . . . . . . . . . . . . . . . . . . . . . . 2",
        size=12,
    )
    draw_text(
        page,
        72,
        170,
        "2 Details . . . . . . . . . . . . . . . . . . . . . . . . . 3",
        size=12,
    )

    page.showPage()
    page.bookmarkPage("intro")
    page.addOutlineEntry("Introduction", "intro", level=0)
    page.bookmarkPage("scope")
    page.addOutlineEntry("Scope", "scope", level=1)
    draw_text(page, 72, 72, "1 Introduction", size=18)
    draw_text(page, 72, 130, "The introduction body should remain readable.", size=12)

    page.showPage()
    page.bookmarkPage("details")
    page.addOutlineEntry("Details", "details", level=0)
    draw_text(page, 72, 72, "2 Details", size=18)
    draw_text(page, 72, 130, "The details body should remain readable.", size=12)
    page.save()


def make_two_column_text_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Two Column Reading Order Paper", size=18)
    left_lines = [
        "Left column starts with alpha context.",
        "Left column continues the setup.",
        "Left column adds supporting detail.",
        "Left column describes the contribution.",
        "Left column keeps normal flow.",
        "Left column finishes before the right side.",
    ]
    right_lines = [
        "Right column begins after the left text.",
        "Right column continues beta context.",
        "Right column gives supporting evidence.",
        "Right column stays after the left lines.",
        "Right column avoids baseline alternation.",
        "Right column finishes at the page end.",
    ]
    for index, (left, right) in enumerate(zip(left_lines, right_lines)):
        y = 130 + index * 18
        draw_text(page, 72, y, left, size=9)
        draw_text(page, 330, y, right, size=9)
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


def test_page_one_visual_does_not_precede_abstract_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "visual-abstract.pdf"
    html_path = tmp_path / "visual-abstract-reader.html"
    make_visual_abstract_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Visual Abstract")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    cards = manifest["cards"]
    figure_index = next(index for index, card in enumerate(cards) if card["kind"] == "figure")
    abstract_index = next(
        index
        for index, card in enumerate(cards)
        if "The abstract should be read before" in card["text"]
    )

    assert abstract_index < figure_index
    assert cards[0]["kind"] != "figure"


def test_wrapped_title_continuation_is_removed_from_page_one_byline(tmp_path: Path) -> None:
    pdf_path = tmp_path / "wrapped-title.pdf"
    html_path = tmp_path / "wrapped-title-reader.html"
    make_wrapped_title_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    all_text = " ".join(card["text"] for card in manifest["cards"])

    assert "GUAGE MODELS" not in all_text
    assert "Edward Hu Yelong Shen" in all_text


def test_visual_title_merges_wrapped_title_lines(tmp_path: Path) -> None:
    pdf_path = tmp_path / "visual-wrapped-title.pdf"
    html_path = tmp_path / "visual-wrapped-title-reader.html"
    make_visual_wrapped_title_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    all_text = " ".join(card["text"] for card in manifest["cards"])

    assert manifest["title"] == "LORA: LOW-RANK ADAPTATION OF LARGE LANGUAGE MODELS"
    assert "LORA: LOW-RANK" not in all_text
    assert "GUAGE MODELS" not in all_text
    assert "Edward Hu Yelong Shen" in all_text


def test_visual_title_skips_conference_masthead(tmp_path: Path) -> None:
    pdf_path = tmp_path / "masthead-title.pdf"
    html_path = tmp_path / "masthead-title-reader.html"
    make_masthead_title_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    all_text = " ".join(card["text"] for card in manifest["cards"])

    assert manifest["title"] == "REACT: SYNERGIZING REASONING AND ACTING IN LANGUAGE MODELS"
    assert "Published as a conference paper" not in all_text
    assert "REACT: SYNERGIZING" not in all_text
    assert "LANGUAGE MODELS" not in all_text
    assert "Shunyu Yao" in all_text
    assert "second page body" in all_text


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


def test_converter_groups_multiline_display_formulas(tmp_path: Path) -> None:
    pdf_path = tmp_path / "multiline-formula.pdf"
    html_path = tmp_path / "multiline-formula-reader.html"
    make_multiline_formula_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Formula Groups")

    assert result.formula_count == 2
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    cards = manifest["cards"]
    formula_cards = [card for card in cards if card["kind"] == "formula"]
    assert len(formula_cards) == 2
    assert formula_cards[0]["bbox"][3] - formula_cards[0]["bbox"][1] > 35
    assert formula_cards[1]["bbox"][3] - formula_cards[1]["bbox"][1] < 24

    paragraph_text = " ".join(card["text"] for card in cards if card["kind"] == "paragraph")
    assert "maximizes the following objective" in paragraph_text
    assert "where epsilon and beta" in paragraph_text
    assert "discussion continues" in paragraph_text
    assert "J_GRPO" not in paragraph_text
    assert "D_KL" not in paragraph_text
    assert "A_i =" not in paragraph_text

    kinds = [card["kind"] for card in cards]
    first_formula = kinds.index("formula")
    second_formula = kinds.index("formula", first_formula + 1)
    assert first_formula < second_formula
    assert any(
        card["kind"] == "paragraph" and "where epsilon and beta" in card["text"]
        for card in cards[first_formula + 1 : second_formula]
    )


def test_extract_algorithm_blocks_groups_pseudocode_rows() -> None:
    def segment(text: str, x0: float, top: float, x1: float) -> dict[str, object]:
        return {"text": text, "bbox": (x0, top, x1, top + 12)}

    blocks = extract_algorithm_blocks(
        [
            segment("The procedure follows below.", 72, 120, 280),
            segment("Algorithm 1 Draft verification", 150, 160, 340),
            segment("Require: draft tokens and target model", 150, 182, 380),
            segment("1: initialize accepted tokens", 150, 204, 340),
            segment("2: while token budget remains do", 150, 226, 370),
            segment("3: return accepted tokens", 150, 248, 340),
            segment("The prose resumes here.", 72, 300, 260),
        ],
        page_number=1,
        page_rect=PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )

    assert len(blocks) == 1
    assert blocks[0].kind == "formula"
    assert "Algorithm 1" in blocks[0].text
    assert "while token budget remains" in blocks[0].text
    assert "prose resumes" not in blocks[0].text


def test_extract_algorithm_blocks_separates_side_by_side_algorithms_from_prose() -> None:
    def segment(text: str, x0: float, top: float, x1: float) -> dict[str, object]:
        return {"text": text, "bbox": (x0, top, x1, top + 10)}

    blocks = extract_algorithm_blocks(
        [
            segment("Algorithm 1 Autoregressive Decoding", 70, 70, 240),
            segment("Algorithm 2 Speculative Decoding", 306, 70, 470),
            segment("Require: Language model q", 70, 88, 170),
            segment("Require: Target language model q", 306, 88, 430),
            segment("1: initialize n", 74, 108, 145),
            segment("length T, drafting strategy DRAFT", 321, 108, 524),
            segment("2: while n < T do", 74, 118, 145),
            segment("VERIFY, and correction strategy CORRECT", 321, 118, 480),
            segment("3:", 74, 128, 82),
            segment("Set q n+1", 100, 128, 208),
            segment("1: initialize n", 310, 128, 380),
            segment("4:", 74, 138, 82),
            segment("Sample x n+1", 100, 138, 178),
            segment("2: while n < T do", 310, 138, 381),
            segment("5:", 74, 148, 82),
            segment("n <- n + 1", 100, 148, 141),
            segment("// Drafting: obtain distributions", 335, 148, 469),
            segment("6: end while", 74, 158, 123),
            segment("3:", 310, 158, 317),
            segment("Set p DRAFT(x)", 335, 158, 475),
            segment("3.2 Pioneering Draft-then-Verify Efforts", 70, 198, 262),
            segment("5:", 310, 198, 317),
            segment("Set q(x), i = 1,..., K + 1", 335, 198, 512),
            segment("To mitigate the above issue, an intuitive way in-", 70, 218, 291),
            segment("6:", 310, 218, 317),
            segment("for i = 1 : K do", 335, 218, 397),
            segment("volves leveraging idle computational resources to", 70, 232, 289),
            segment("7:", 310, 228, 317),
            segment("if VERIFY (xi, pi, qi) then", 348, 228, 445),
            segment("15: end while", 306, 318, 359),
        ],
        page_number=3,
        page_rect=PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )

    assert len(blocks) == 2
    assert "Algorithm 1" in blocks[0].text
    assert "6: end while" in blocks[0].text
    assert "Pioneering Draft" not in blocks[0].text
    assert "Algorithm 2" in blocks[1].text
    assert "for i = 1 : K do" in blocks[1].text
    assert "volves leveraging idle" not in blocks[1].text


def test_extract_algorithm_blocks_handles_unnumbered_algorithm_body() -> None:
    def segment(text: str, x0: float, top: float, x1: float) -> dict[str, object]:
        return {"text": text, "bbox": (x0, top, x1, top + 10)}

    blocks = extract_algorithm_blocks(
        [
            segment("Algorithm 1 satisfies Equation (1).", 306, 205, 500),
            segment("Some prose continues in this paragraph.", 306, 220, 520),
            segment("Algorithm 1 SpeculativeDecodingStep", 55, 374, 212),
            segment("Inputs: Mp, Mq, prefix.", 65, 388, 169),
            segment("p q", 109, 392, 132),
            segment(". Sample guesses x from M autoregressively.", 65, 400, 281),
            segment("1,..., q", 152, 404, 211),
            segment("for i = 1 to do", 65, 412, 134),
            segment("q(x) <- M(prefix + [x])", 75, 424, 233),
            segment("end for", 65, 448, 96),
            segment(". Run M in parallel.", 65, 459, 152),
            segment(". Determine the number of accepted guesses n.", 65, 495, 255),
            segment("if n < gamma then", 65, 558, 121),
            segment("Definition 3.2. A neighboring prose column.", 307, 570, 542),
        ],
        page_number=3,
        page_rect=PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )

    assert len(blocks) == 1
    assert "Algorithm 1 SpeculativeDecodingStep" in blocks[0].text
    assert "Algorithm 1 satisfies" not in blocks[0].text
    assert "Definition 3.2" not in blocks[0].text
    assert ". Run M in parallel" in blocks[0].text


def test_converter_crops_algorithm_without_pseudocode_paragraph_cards(tmp_path: Path) -> None:
    pdf_path = tmp_path / "algorithm.pdf"
    html_path = tmp_path / "algorithm-reader.html"
    make_algorithm_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Algorithm Sample")

    assert result.formula_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    cards = manifest["cards"]
    formula_cards = [card for card in cards if card["kind"] == "formula"]
    assert any("Algorithm 1 Draft verification" in card["text"] for card in formula_cards)

    paragraph_text = " ".join(card["text"] for card in cards if card["kind"] == "paragraph")
    assert "The verifier uses the following procedure" in paragraph_text
    assert "The prose resumes after the algorithm" in paragraph_text
    assert "Algorithm 1" not in paragraph_text
    assert "while token budget remains" not in paragraph_text
    assert "return accepted tokens" not in paragraph_text


def test_numbered_section_heading_is_reader_boundary() -> None:
    assert looks_like_heading("2.3.2 External Action")
    assert not looks_like_heading("(3) Updating Agent Code")

    blocks = merge_text_blocks(
        [
            TextBlock(
                page=10,
                bbox=(72, 320, 286, 340),
                text="The previous subsection ends with this sentence.",
            ),
            TextBlock(page=10, bbox=(72, 395, 220, 414), text="2.3.2 External Action"),
            TextBlock(
                page=10,
                bbox=(72, 430, 286, 452),
                text="External tools let agents interact with the environment.",
            ),
        ]
    )

    assert [block.text for block in blocks] == [
        "The previous subsection ends with this sentence.",
        "2.3.2 External Action",
        "External tools let agents interact with the environment.",
    ]


def test_formula_detector_rejects_urls_code_and_table_rows() -> None:
    def segment(text: str, x0: float, top: float, x1: float) -> dict[str, object]:
        return {"text": text, "bbox": (x0, top, x1, top + 12)}

    blocks = extract_formula_blocks(
        [
            segment("Website: https://llama.meta.com/", 72, 120, 260),
            segment("8https://github.com/openai/evals", 72, 150, 250),
            segment("6 def f(ctx: str, last_jobs: List[Job]) -> List[Job]:", 72, 180, 350),
            segment(
                "General MMLU-Pro (0-shot, CoT) 48.3 - 36.9 66.4 56.3 49.2 73.3",
                72,
                210,
                430,
            ),
            segment("job_manifest = JobManifest(", 72, 230, 260),
            segment('race = input("Enter your race (white/black/asian/latino): ")', 72, 240, 420),
            segment("<MODEL EXPLANATION (t=0.3, n=1) SAMPLED HERE>", 72, 260, 430),
            segment(r"\dbname=postgres sslmode=disable", 72, 270, 300),
            segment("The next row is the only displayed equation.", 72, 250, 340),
            segment("Var(mu_hat) = Var(s)/n = (Var(x) + E[sigma^2])/n", 150, 292, 462),
            segment("The prose resumes below the equation.", 72, 340, 320),
        ],
        page_number=1,
        page_rect=PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )

    assert len(blocks) == 1
    assert blocks[0].kind == "formula"
    assert "Var(mu_hat)" in blocks[0].text
    assert "https://llama.meta.com" not in blocks[0].text
    assert "github.com/openai/evals" not in blocks[0].text
    assert "def f(ctx" not in blocks[0].text
    assert "General MMLU-Pro" not in blocks[0].text
    assert "job_manifest" not in blocks[0].text
    assert "MODEL EXPLANATION" not in blocks[0].text


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


def test_converter_skips_footnote_cards_but_keeps_source_page(tmp_path: Path) -> None:
    pdf_path = tmp_path / "footnote.pdf"
    html_path = tmp_path / "footnote-reader.html"
    make_footnote_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Footnote")

    assert result.card_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    card_text = " ".join(card["text"] for card in manifest["cards"])
    assert "Main body text should remain" in card_text
    assert "Contact author@example.com" not in card_text
    assert "source page image" not in card_text
    assert result.formula_count == 0
    assert not any(card["kind"] == "footnote" for card in manifest["cards"])
    assert any(asset["kind"] == "source_page" for asset in manifest["assets"])


def test_converter_renders_contents_pages_as_structured_links(tmp_path: Path) -> None:
    pdf_path = tmp_path / "contents.pdf"
    html_path = tmp_path / "contents-reader.html"
    make_contents_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Contents")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    contents_cards = [card for card in manifest["cards"] if card["kind"] == "contents"]
    assert len(contents_cards) == 1
    contents = contents_cards[0]
    assert contents["section"] == "Contents"
    assert [item["label"] for item in contents["items"]] == [
        "1 Introduction",
        "1.1 Scope",
        "2 Details",
    ]
    assert [item["href"] for item in contents["items"]] == ["#page-2", "#page-2", "#page-3"]
    assert "Introduction . . ." not in " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )

    html = html_path.read_text(encoding="utf-8")
    assert '"kind": "contents"' in html
    assert "toc-list" in html
    assert "#page-2" in html


def test_converter_preserves_two_column_reading_order(tmp_path: Path) -> None:
    pdf_path = tmp_path / "two-column.pdf"
    html_path = tmp_path / "two-column-reader.html"
    make_two_column_text_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Two Columns")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    text = " ".join(card["text"] for card in manifest["cards"] if card["kind"] == "paragraph")
    assert text.index("Left column starts") < text.index("Left column finishes")
    assert text.index("Left column finishes") < text.index("Right column begins")
    assert text.index("Right column begins") < text.index("Right column finishes")


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


def test_char_geometry_repairs_misdecoded_pdf_ligature_glyphs() -> None:
    chars = make_unspaced_chars(
        'Arti!cial intelligence is insu"cient without e#ective work$ows and brie$y aligned o%ine support.',
        top=140,
        size=10,
    )

    segments = split_chars_into_reading_order_segments(
        chars,
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )

    assert segments[0]["text"] == (
        "Artificial intelligence is insufficient without effective workflows and "
        "briefly aligned offline support."
    )


def test_normalize_text_keeps_ordinary_punctuation_around_spaces() -> None:
    assert normalize_text('Hello! This keeps C# code, "$5", and 100% intact.') == (
        'Hello! This keeps C# code, "$5", and 100% intact.'
    )


def test_normalize_text_does_not_repair_legitimate_inline_punctuation() -> None:
    text = 'Keep Hello!World, A#B, n%m, A$B, and foo"bar unchanged.'
    assert normalize_text(text) == text


def test_unreadable_pdf_glyph_detection_and_pdfium_control_cleanup() -> None:
    assert has_unreadable_pdf_glyphs("(cid:80) exp(v)")
    assert has_unreadable_pdf_glyphs("bad\x10text")
    assert not has_unreadable_pdf_glyphs("ordinary readable text")
    assert normalize_text("softmax (cid:80) exp(v)") == "softmax ∑ exp(v)"
    assert normalize_text("(cid:2)Back(cid:3)") == "[Back]"
    assert normalize_text("(cid:0) C⊤E (cid:1)") == "( C⊤E )"
    assert normalize_text("g = (cid:40) RBOX") == "g = { RBOX"
    assert normalize_text("| {(cid:122) }") == "| {z }"
    assert normalize_pdfium_control_chars("geome\x02try \x02Back\x03") == "geometry [Back]"
    assert strip_orphan_math_prefix("(cid:33) In the special case") == "In the special case"


def test_formula_detection_does_not_promote_author_byline() -> None:
    assert not is_formula_text_line(
        (170.0, 140.0, 440.0, 160.0),
        PageRect(0.0, 0.0, PAGE_WIDTH, PAGE_HEIGHT),
        "Yaniv Leviathan * 1 Matan Kalman * 1 Yossi Matias 1",
    )


def test_reader_noise_drops_encoded_gibberish() -> None:
    assert looks_like_reader_noise("2EV] &RXOGQRWILQG]&LUTXHGX]6ROHLOVKRZ]0\\VWHUH LLO> LGOLO")


def test_normalize_text_repairs_fused_leading_fi_word() -> None:
    assert normalize_text("There are!ve distinct eras.") == "There are five distinct eras."


def test_normalize_text_repairs_contextual_ligature_punctuation() -> None:
    assert normalize_text("user pro!le trade-o!s o!set cuto!s communication e”ciency") == (
        "user profile trade-offs offset cutoffs communication efficiency"
    )


def test_char_geometry_does_not_turn_sentence_punctuation_into_ligature() -> None:
    chars = make_unspaced_chars("Hello!World remains readable.", top=140, size=10)

    segments = split_chars_into_reading_order_segments(
        chars,
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )

    assert segments[0]["text"] == "Hello!World remains readable."


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


def test_embedded_caption_segment_is_sliced_from_midline() -> None:
    caption = slice_caption_from_segment(
        {
            "text": "body prose continues here Figure 1: Our reparametrization",
            "bbox": (108.0, 637.8, 504.0, 651.0),
        },
        "Figure",
        allow_embedded=True,
    )

    assert caption is not None
    assert caption["text"] == "Figure 1: Our reparametrization"
    assert caption["bbox"][0] > 250

    assert (
        slice_caption_from_segment(
            {
                "text": "The result is discussed in Table 5.",
                "bbox": (108.0, 637.8, 504.0, 651.0),
            },
            "Table",
        )
        is None
    )


def test_wrapped_hyphenation_keeps_real_short_hyphen_terms() -> None:
    assert normalize_block_lines(["The observa-", "tions work."]) == "The observations work."
    assert normalize_block_lines(["The off-", "line stage."]) == "The off-line stage."


def test_action_change_regression_repairs_fused_words_and_skips_footnote(
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
    assert "2 A system is Markovian" not in all_text
    assert not any(card["kind"] == "footnote" for card in manifest["cards"])


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


def test_region_suppression_requires_meaningful_horizontal_overlap() -> None:
    left_column_text = (50.0, 210.0, 285.0, 224.0)
    right_column_visual = (202.0, 180.0, 545.0, 376.0)
    figure_label = (330.0, 210.0, 510.0, 230.0)

    assert not region_contains_text_block(left_column_text, right_column_visual)
    assert region_contains_text_block(figure_label, right_column_visual)


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
