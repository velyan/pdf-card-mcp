from __future__ import annotations

import json
from pathlib import Path

import pytest
from reportlab.lib import colors
from reportlab.pdfgen import canvas
import pdfplumber

from pdf_card_mcp.converter import (
    TextBlock,
    bboxes_substantially_overlap,
    convert_pdf_to_card_html,
    extract_words,
    extract_algorithm_blocks,
    extract_formula_blocks,
    find_caption_lines_from_segments,
    has_unreadable_pdf_glyphs,
    heuristic_table_bbox,
    is_formula_text_line,
    looks_like_heading,
    looks_like_reader_noise,
    merge_text_blocks,
    nearby_bbox_indexes,
    normalize_detected_visual_bbox,
    normalize_block_lines,
    normalize_pdfium_control_chars,
    normalize_text,
    region_contains_text_block,
    segment_column_side,
    slice_caption_from_segment,
    smooth_reader_cards,
    split_text_block_by_items,
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


def make_bottom_caption_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Bottom Caption Table Paper", size=18)
    draw_text(page, 150, 150, "Rank r val loss BLEU NIST METEOR", size=10)
    rows = [
        "1 1.23 68.72 8.7215 0.4565",
        "2 1.21 69.17 8.7413 0.4590",
        "4 1.18 70.38 8.8439 0.4689",
        "8 1.17 69.57 8.7457 0.4636",
        "16 1.16 69.61 8.7483 0.4629",
    ]
    for index, row in enumerate(rows):
        draw_text(page, 164, 168 + index * 18, row, size=10)
    draw_text(
        page,
        72,
        274,
        "Table 1: Validation loss and test metrics with different ranks.",
        size=11,
    )
    draw_text(
        page,
        72,
        298,
        "The explanation below the caption should not become the table crop.",
        size=12,
    )
    page.save()


def make_grouped_bottom_caption_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "3.1. Model Evaluation", size=13)
    rows = [
        (118, "Benchmark (Metric) Claude-3.5 GPT-4o DeepSeek OpenAI R1"),
        (138, "Architecture - - MoE - - MoE"),
        (156, "# Activated Params - - 37B - - 37B"),
        (174, "# Total Params - - 671B - - 671B"),
        (198, "English"),
        (216, "MMLU (Pass@1) 88.3 87.2 88.5 85.2 91.8 90.8"),
        (234, "GPQA Diamond (Pass@1) 65.0 49.9 59.1 60.0 75.7 71.5"),
        (258, "Code"),
        (276, "LiveCodeBench (Pass@1-COT) 38.9 32.9 36.2 53.8 63.4 65.9"),
        (294, "SWE Verified (Resolved) 50.8 38.8 42.0 41.6 48.9 49.2"),
    ]
    for y, row in rows:
        draw_text(page, 92, y, row, size=9)
    draw_text(
        page,
        92,
        330,
        "Table 4 Comparison between DeepSeek-R1 and other representative models.",
        size=11,
    )
    draw_text(page, 72, 378, "The discussion after the table should stay readable.", size=12)
    page.save()


def make_sectioned_bottom_caption_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "4 Hyperparameters", size=16)
    rows = [
        (122, "Dataset E2E WebNLG DART"),
        (144, "Training"),
        (164, "Optimizer AdamW AdamW AdamW"),
        (184, "Learning Rate 5e-4 5e-4 1e-3"),
        (204, "Batch Size 16 16 32"),
        (230, "Inference"),
        (250, "Beam 10 10 5"),
        (270, "Length Penalty 0.8 0.8 0.6"),
    ]
    for y, row in rows:
        x = 205 if row in {"Training", "Inference"} else 116
        draw_text(page, x, y, row, size=9)
    draw_text(
        page,
        116,
        310,
        "Table 11: Hyperparameters used for training and inference.",
        size=11,
    )
    draw_text(page, 72, 354, "The paragraph after the table should stay readable.", size=12)
    page.save()


def make_side_by_side_algorithm_and_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    left_x = 52
    right_x = 320
    draw_text(page, left_x, 74, "Algorithm 1 Locality-Aware NMS", size=10)
    algorithm_rows = [
        "1: function NMSLOCALITY(geometries)",
        "2: S <- empty, p <- empty",
        "3: for g in geometries do",
        "4: if p != empty then",
        "5: p <- WEIGHTEDMERGE(g, p)",
        "6: else",
        "7: S <- S union {p}",
        "8: end if",
        "9: return STANDARDNMS(S)",
        "10: end function",
    ]
    for index, row in enumerate(algorithm_rows):
        draw_text(page, left_x + 10, 92 + index * 13, row, size=9)

    table_bbox = (right_x, 72, 552, 124)
    for y in (72, 88, 104, 124):
        draw_line(page, (table_bbox[0], y), (table_bbox[2], y), width=0.8)
    for x in (table_bbox[0], 392, table_bbox[2]):
        draw_line(page, (x, table_bbox[1]), (x, table_bbox[3]), width=0.8)
    table_rows = [
        (78, "Network", "Description"),
        (94, "PVANET", "small and fast model"),
        (110, "VGG16", "common model"),
    ]
    for y, first, second in table_rows:
        draw_text(page, right_x + 8, y, first, size=9)
        draw_text(page, 410, y, second, size=9)
    draw_text(page, 390, 138, "Table 2. Base Models", size=9)
    draw_text(page, right_x, 168, "Right-column prose should stay readable.", size=12)
    page.save()


def make_captioned_table_before_figure_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Table Before Figure", size=18)
    draw_text(
        page,
        150,
        80,
        "Table 1: Retrieval actions classified by input and output.",
        size=11,
    )
    rows = [
        "Types Input Output Studies",
        "Text-Code Requirements API APIRetriever [Zan et al., 2022a]",
        "Text-Text Requirements Relevant Documents DocPrompting [Zhou et al., 2022]",
        "Code-Hybrid Code Snippet Code-Comment Examples CEDAR [Nashid et al., 2023]",
        "Text-Hybrid Requirements Examples LAIL [Li et al., 2023b]",
        "AceCoder [Li et al., 2023c]",
    ]
    for index, row in enumerate(rows):
        draw_text(page, 92, 116 + index * 22, row, size=9)
    draw_rect(
        page,
        (118, 300, 494, 430),
        stroke=colors.Color(0.2, 0.2, 0.2),
        fill=colors.Color(0.94, 0.97, 1.0),
    )
    draw_text(page, 145, 326, "Dense-based", size=9)
    draw_text(page, 376, 326, "Sparse-based", size=9)
    draw_text(page, 210, 370, "D1: Information retrieval and search engines", size=8)
    draw_text(page, 72, 456, "Figure 1: Retrieval method pipeline.", size=11)
    page.save()


def make_tall_bottom_caption_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 48, "Tall Bottom Caption Table Paper", size=18)
    draw_line(page, (92, 84), (520, 84), width=1.0)
    draw_text(page, 104, 108, "Benchmark Model Small Base Large Score", size=9)
    draw_line(page, (92, 124), (520, 124), width=0.8)
    for index in range(18):
        y = 148 + index * 20
        draw_text(
            page,
            104,
            y,
            f"Task {index + 1} Method {index % 3} {70 + index}.1 {72 + index}.2 {74 + index}.3",
            size=9,
        )
        if index in {5, 11, 17}:
            draw_line(page, (92, y + 8), (520, y + 8), width=0.6)
    draw_text(
        page,
        92,
        518,
        "Table 9: Full-page benchmark results with a bottom caption.",
        size=11,
    )
    draw_text(page, 72, 572, "The paragraph after the caption should stay readable.", size=12)
    page.save()


def make_math_bottom_caption_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Math Heavy Table Paper", size=18)
    draw_text(page, 84, 88, "Methods DRAFT(x_t, M_p) Drafter Type", size=9)
    draw_text(page, 84, 106, "Parallel p1,...,pK = M_p(x | x<t) FFN Heads", size=9)
    draw_text(page, 84, 124, "Autoregressive p_i = M_p(x | x<t, x_i), i = 1,...,K Small LMs", size=9)
    draw_line(page, (72, 80), (540, 80), width=1.0)
    draw_line(page, (72, 136), (540, 136), width=1.0)
    draw_text(
        page,
        72,
        150,
        "Table 1: Summary of formulations for various drafting strategies",
        size=11,
    )
    draw_text(page, 72, 164, "that categorize these methods into two distinct groups.", size=11)
    draw_text(page, 72, 200, "The paragraph after the caption should stay readable.", size=12)
    page.save()


def make_appendix_label_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Appendix Table Paper", size=18)
    draw_line(page, (92, 84), (520, 84), width=1.0)
    draw_text(page, 104, 108, "Method Loss Memory Time Gradient Memory Time", size=9)
    draw_line(page, (92, 124), (520, 124), width=0.8)
    rows = [
        "Lower bound 0.004 MB 1,161 MB",
        "1) CCE (Ours) 245 MB 17 ms 1,163 MB 37 ms",
        "2) Baseline 10,997 MB 30 ms 7,320 MB 44 ms",
        "3) CCE-Kahan 1 MB 18 ms 2,325 MB 42 ms",
    ]
    for index, row in enumerate(rows):
        draw_text(page, 104, 148 + index * 22, row, size=9)
    draw_line(page, (92, 242), (520, 242), width=1.0)
    draw_text(
        page,
        92,
        266,
        "Table A1: Table 1 where all methods include a filter.",
        size=11,
    )
    draw_text(page, 72, 324, "The paragraph after the appendix caption should stay readable.", size=12)
    page.save()


def make_embedded_bottom_caption_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Embedded Caption Table Paper", size=18)
    draw_line(page, (100, 92), (512, 92), width=1.0)
    draw_text(page, 120, 118, "Method MNLI-100 MNLI-1k MNLI-10k MNLI-392K", size=9)
    draw_line(page, (100, 134), (512, 134), width=0.8)
    draw_text(page, 120, 158, "GPT-3 (Fine-Tune) 60.2 88.9 89.5", size=9)
    draw_text(page, 120, 180, "GPT-3 (PrefixEmbed) 37.6 79.5 88.6", size=9)
    draw_text(page, 120, 202, "GPT-3 (PrefixLayer) 48.3 82.5 85.9 89.6", size=9)
    draw_text(
        page,
        120,
        224,
        "GPT-3 (LoRA) 63.8 85.6 89.2 91.7 Table 16: Validation accuracy.",
        size=9,
    )
    draw_text(page, 72, 286, "The paragraph after the embedded caption should stay readable.", size=12)
    page.save()


def make_long_caption_above_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Long Table Paper", size=18)
    draw_text(
        page,
        300,
        90,
        "Table 3. Empirical alpha values for various target models.",
        size=9,
    )
    draw_line(page, (300, 126), (540, 126), width=1.0)
    draw_text(page, 308, 146, "Model Approx Setting Alpha", size=8)
    draw_line(page, (300, 162), (540, 162), width=0.8)
    for index in range(20):
        y = 184 + index * 16
        draw_text(
            page,
            308,
            y,
            f"T5-XXL (CNNDM) T5-{index % 5} T={index % 2} 0.{10 + index}",
            size=8,
        )
        if index in {5, 11, 17}:
            draw_line(page, (300, y + 6), (540, y + 6), width=0.6)
    draw_line(page, (300, 514), (540, 514), width=1.0)
    draw_text(page, 300, 554, "The prose after the long table should stay readable.", size=10)
    page.save()


def make_pipe_caption_visuals_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Pipe Caption Visuals", size=18)
    draw_text(page, 92, 82, "Model Accuracy F1 Rating", size=10)
    draw_text(page, 92, 102, "Base 71.0 86.7 1820", size=10)
    draw_text(page, 92, 122, "Large 74.4 83.3 1843", size=10)
    draw_line(page, (80, 72), (320, 72), width=1.0)
    draw_line(page, (80, 136), (320, 136), width=1.0)
    draw_text(page, 92, 154, "Table 1 | Compact benchmark results.", size=11)
    draw_rect(
        page,
        (110, 220, 420, 340),
        stroke=colors.Color(0.2, 0.35, 0.55),
        fill=colors.Color(0.96, 0.98, 1.0),
    )
    draw_line(page, (140, 315), (390, 245), width=2)
    draw_text(page, 230, 270, "Plot", size=14)
    draw_text(page, 110, 365, "Figure 1 | Accuracy curve during training.", size=11)
    draw_text(page, 72, 410, "Body text after the visuals should remain readable.", size=12)
    page.save()


def make_ruled_prompt_block_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 48, "Prompt Appendix Paper", size=18)
    draw_text(page, 250, 110, "Hotpot QA Prompts", size=9)
    draw_line(page, (108, 124), (506, 124), width=1.0)
    draw_text(page, 116, 142, "Original", size=7)
    draw_text(page, 116, 158, "Question", size=7)
    draw_text(page, 180, 158, "What is the elevation range for the eastern sector?", size=7)
    draw_text(page, 116, 176, "Answer", size=7)
    draw_text(page, 180, 176, "1,800 to 7,000 ft", size=7)
    draw_text(page, 116, 194, "Question", size=7)
    draw_text(page, 180, 194, "Who was Milhouse named after?", size=7)
    draw_text(page, 116, 212, "Answer", size=7)
    draw_text(page, 180, 212, "Richard Nixon", size=7)
    draw_line(page, (108, 236), (506, 236), width=1.0)
    draw_text(page, 116, 254, "Act", size=7)
    draw_text(page, 116, 272, "Question", size=7)
    draw_text(page, 180, 272, "What is the elevation range for the eastern sector?", size=7)
    draw_text(page, 116, 290, "Action 1", size=7)
    draw_text(page, 180, 290, "Search[Colorado orogeny]", size=7)
    draw_text(page, 116, 308, "Observation 1", size=7)
    draw_text(page, 180, 308, "The Colorado orogeny was a mountain building episode.", size=7)
    draw_text(page, 116, 326, "Action 2", size=7)
    draw_text(page, 180, 326, "Finish[1,800 to 7,000 ft]", size=7)
    draw_line(page, (108, 350), (506, 350), width=1.0)
    draw_text(page, 410, 360, "Continued on next page", size=7)
    draw_text(page, 72, 400, "Body text after the prompt block should remain readable.", size=12)
    page.save()


def make_ruled_prose_block_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 48, "Ruled Prose Paper", size=18)
    draw_line(page, (108, 124), (506, 124), width=1.0)
    draw_text(page, 116, 150, "This ruled note contains ordinary explanatory prose.", size=11)
    draw_text(page, 116, 170, "It should remain searchable reader text, not a screenshot.", size=11)
    draw_text(page, 116, 190, "The line styling alone is not enough to make a table.", size=11)
    draw_line(page, (108, 220), (506, 220), width=1.0)
    page.save()


def make_prompt_continuation_preamble_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 48, "Prompt Continuation Paper", size=18)
    draw_text(page, 220, 104, "Fever Prompts - Continued from previous page", size=10)
    draw_line(page, (104, 120), (512, 120), width=0.8)
    draw_text(page, 114, 150, "Claim", size=9)
    draw_text(page, 184, 150, "Beautiful reached number two on the Billboard Hot 100 in 2003.", size=9)
    draw_text(page, 114, 168, "Thought", size=9)
    draw_text(page, 184, 168, "The song peaked at number two, but not sure if it was in 2003.", size=9)
    draw_text(page, 114, 186, "Answer", size=9)
    draw_text(page, 184, 186, "NOT ENOUGH INFO", size=9)
    draw_line(page, (104, 206), (512, 206), width=0.8)
    draw_text(page, 114, 232, "ReAct", size=9)
    draw_text(page, 184, 232, "Determine if there is Observation that SUPPORTS or REFUTES a Claim.", size=9)
    rows = [
        ("Claim", "Nikolaj Coster-Waldau worked with the Fox Broadcasting Company."),
        ("Thought 1", "I need to search Nikolaj Coster-Waldau and find the company."),
        ("Action 1", "Search[Nikolaj Coster-Waldau]"),
        ("Observation 1", "He appeared in the 2009 Fox television film Virtuality."),
        ("Action 2", "Finish[SUPPORTS]"),
        ("Claim", "Stranger Things is set in Bloomington, Indiana."),
        ("Thought 1", "I should search for Stranger Things."),
        ("Action 1", "Search[Stranger Things]"),
        ("Observation 1", "It is set in the fictional town of Hawkins, Indiana."),
        ("Action 2", "Finish[REFUTES]"),
    ]
    for index, (label, value) in enumerate(rows):
        y = 272 + index * 24
        draw_text(page, 114, y, label, size=9)
        draw_text(page, 184, y, value, size=9)
    draw_line(page, (104, 536), (512, 536), width=0.8)
    draw_text(page, 72, 584, "Body text after the continuation should remain readable.", size=12)
    page.save()


def make_long_prompt_table_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 72, "Prompt Trajectory Table", size=18)
    draw_text(
        page,
        72,
        142,
        "Table 1: Example trajectories for a shopping task predicted by Act and ReAct.",
        size=11,
    )
    draw_text(
        page,
        90,
        164,
        "Compared to Act, ReAct uses reasoning to find products that satisfy all target attributes.",
        size=10,
    )

    rows = [
        "Instruction: get me apple cinnamon freeze dried banana chips lower than 50 dollars",
        "Act ReAct",
        "Action: search[sixteen pack apple cinnamon freeze dried banana chips] Action: search[sixteen pack]",
        "Observation: [BacktoSearch] [BacktoSearch]",
        "Page1(Totalresults: 50) Page1(Totalresults: 50)",
        "[Next] [Next]",
        "[B0061IVFZE] [B0061IVFZE]",
        "Brothers ALL Natural Fruit Crisps Strawberry Banana Pack of 100",
        "$85.0 $85.0",
        "[B092JLLYK6] [B092JLLYK6]",
        "Nature's Turn Freeze-Dried Fruit Snacks Banana Crisps Perfect For School Lunches",
        "NonGMO GlutenFree NothingArtificial 0.53oz 6-Pack",
        "$12.99 $12.99",
        "Action: click[B0061IVFZE] Action: think[B0061IVFZE is strawberry banana]",
        "Observation: B096H2P6G2 is fruit snacks, not freeze dried banana chips.",
        "[Prev] B092JLLYK6 first.",
        "flavorname[asian pear][banana][fuji apple cinnamon][strawberry banana]",
        "Action: click[B092JLLYK6]",
        "Price: $12.99 Observation:",
        "Rating: N.A.",
        "[Description] [Features] [Reviews] [BuyNow]",
        "Action: click[BuyNow]",
        "Action: think[the item has apple cinnamon and sixteen pack options]",
        "Observation: OK.",
        "Action: click[applecinnamon]",
        "Observation: You have clicked applecinnamon.",
        "Action: click[0.53 ounce pack of 16]",
        "Observation: You have clicked 0.53 ounce pack of 16.",
        "Action: click[BuyNow]",
        "Score: 0.125 Score: 1.0",
    ]
    for index, row in enumerate(rows):
        draw_text(page, 90, 196 + index * 16, row, size=8)
    draw_text(page, 302, 752, "31", size=10)
    page.save()


def make_adjacent_bottom_tables_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Adjacent Bottom Caption Tables", size=18)
    left_rows = [
        "Method Pick Clean Heat Cool Look Pick2 All",
        "Act 88 42 74 67 72 41 45",
        "ReAct 65 39 83 76 55 24 57",
        "ReAct best 92 58 96 86 78 41 71",
        "BUTLER best 46 39 74 22 24 37",
    ]
    right_rows = [
        "Method Score SR",
        "Act 62.3 30.1",
        "ReAct 66.6 40.0",
        "IL 59.9 29.1",
        "IL+RL 62.4 28.7",
    ]
    for index, row in enumerate(left_rows):
        draw_text(page, 92, 96 + index * 16, row, size=8)
    for index, row in enumerate(right_rows):
        draw_text(page, 398, 96 + index * 16, row, size=8)
    draw_text(page, 398, 178, "Table 2: Score and success rate.", size=9)
    draw_text(
        page,
        92,
        190,
        "Table 1: Left task-specific success rates and neighboring caption continuation.",
        size=9,
    )
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


def make_multiline_figure_caption_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Multiline Figure Caption", size=18)
    draw_rect(
        page,
        (92, 82, 520, 170),
        stroke=colors.Color(0.35, 0.35, 0.45),
        fill=colors.Color(0.94, 0.96, 1.0),
    )
    draw_text(page, 170, 128, "Timeline diagram", size=16)
    draw_text(
        page,
        72,
        196,
        "Figure 2: Timeline illustrating the evolution of speculative decoding was",
        size=10,
    )
    draw_text(
        page,
        72,
        210,
        "formally introduced as a general decoding paradigm for efficient inference.",
        size=10,
    )
    draw_text(page, 72, 250, "The body paragraph begins after the caption.", size=12)
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


def make_running_header_footer_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    bodies = [
        [
            "First page body discusses the introduction in careful detail.",
            "The narrative continues across several sentences so the reader",
            "clearly recognises this region as ordinary flowing prose text.",
        ],
        [
            "Second page body explores the proposed method very carefully.",
            "Additional explanatory sentences keep the column reading like",
            "natural prose rather than any sort of tabular or gridded layout.",
        ],
        [
            "Third page body reports the experimental results quite clearly.",
            "The closing discussion spans multiple lines of continuous text",
            "to ensure the converter treats the page as a readable paragraph.",
        ],
    ]
    for index, lines in enumerate(bodies):
        draw_text(page, 72, 30, "Internal review copy do not distribute", size=9)
        if index == 0:
            draw_text(page, 72, 72, "A Study Of Running Headers And Footers", size=18)
        for offset, body in enumerate(lines):
            draw_text(page, 72, 150 + offset * 22, body, size=12)
        draw_text(page, 72, 760, f"Confidential draft page {index + 1}", size=9)
        page.showPage()
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


def make_tall_labeled_figure_pdf(path: Path) -> None:
    page = canvas.Canvas(str(path), pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
    draw_text(page, 72, 40, "Tall Labeled Figure Paper", size=18)
    draw_text(page, 250, 78, "Token-based Input", size=9)
    draw_text(page, 330, 98, "Ahmed et al. (2024), Al-Kaswan et al. (2023)", size=7)
    draw_text(page, 170, 104, "Textual Input", size=9)
    draw_text(page, 252, 122, "Tree/graph-based Input", size=9)
    draw_rect(
        page,
        (140, 150, 470, 520),
        stroke=colors.Color(0.2, 0.35, 0.55),
        fill=colors.Color(0.96, 0.98, 1.0),
    )
    draw_rect(
        page,
        (170, 192, 265, 242),
        stroke=colors.Color(0.2, 0.45, 0.32),
        fill=colors.Color(0.90, 0.95, 0.90),
    )
    draw_rect(
        page,
        (345, 192, 440, 242),
        stroke=colors.Color(0.65, 0.42, 0.25),
        fill=colors.Color(0.98, 0.92, 0.85),
    )
    draw_line(page, (265, 217), (345, 217), width=2)
    draw_text(page, 192, 222, "Memory", size=10)
    draw_text(page, 365, 222, "Action", size=10)
    draw_text(page, 72, 604, "Figure 1: Taxonomy of labeled components.", size=11)
    draw_text(page, 72, 650, "Body text below the figure should remain a paragraph.", size=12)
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


def test_bottom_caption_table_crop_uses_rows_above_caption(tmp_path: Path) -> None:
    pdf_path = tmp_path / "bottom-caption-table.pdf"
    html_path = tmp_path / "bottom-caption-reader.html"
    make_bottom_caption_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Bottom Caption")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    x0, top, x1, bottom = table_asset["bbox"]
    assert top < 150
    assert bottom < 270
    assert "Table 1: Validation loss" in table_asset["caption"]
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "explanation below the caption" in paragraph_text
    assert "1 1.23 68.72" not in paragraph_text


def test_grouped_bottom_caption_table_absorbs_category_rows_without_heading(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "grouped-bottom-caption-table.pdf"
    html_path = tmp_path / "grouped-bottom-caption-reader.html"
    make_grouped_bottom_caption_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Grouped Table")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert 96 < top < 124
    assert bottom > 300
    non_table_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] != "table"
    )
    assert "3.1. Model Evaluation" in non_table_text
    assert "The discussion after the table" in non_table_text
    assert "English" not in non_table_text
    assert "Code" not in non_table_text
    assert "LiveCodeBench" not in non_table_text
    assert "Architecture - - MoE" not in non_table_text


def test_sectioned_bottom_caption_table_keeps_internal_heading_labels_in_crop(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "sectioned-bottom-caption-table.pdf"
    html_path = tmp_path / "sectioned-bottom-caption-reader.html"
    make_sectioned_bottom_caption_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Sectioned Table")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert top < 124
    assert bottom > 274
    non_table_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] != "table"
    )
    assert "4 Hyperparameters" in non_table_text
    assert "The paragraph after the table" in non_table_text
    assert "Dataset E2E WebNLG DART" not in non_table_text
    assert "Training" not in non_table_text
    assert "Inference" not in non_table_text
    assert "Learning Rate" not in non_table_text


def test_right_column_bottom_caption_table_does_not_suppress_left_algorithm(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "side-by-side-algorithm-table.pdf"
    html_path = tmp_path / "side-by-side-algorithm-table-reader.html"
    make_side_by_side_algorithm_and_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Side by Side")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    x0, _, x1, _ = table_asset["bbox"]
    assert x0 > PAGE_WIDTH * 0.45
    assert x1 > PAGE_WIDTH * 0.80
    non_table_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] != "table"
    )
    assert "Algorithm 1 Locality-Aware NMS" in non_table_text
    assert "STANDARDNMS" in non_table_text
    assert "Right-column prose should stay readable" in non_table_text


def test_top_caption_table_crop_stops_before_following_figure(tmp_path: Path) -> None:
    pdf_path = tmp_path / "captioned-table-before-figure.pdf"
    html_path = tmp_path / "captioned-table-before-figure-reader.html"
    make_captioned_table_before_figure_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Table Figure")

    assert result.table_count >= 1
    assert result.figure_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    figure_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "figure")
    assert table_asset["bbox"][3] < 286
    assert figure_asset["bbox"][1] > table_asset["bbox"][3] + 4
    assert not bboxes_substantially_overlap(
        tuple(table_asset["bbox"]),
        tuple(figure_asset["bbox"]),
        threshold=0.20,
    )


def test_tall_bottom_caption_table_crop_reaches_page_top_rows(tmp_path: Path) -> None:
    pdf_path = tmp_path / "tall-bottom-caption-table.pdf"
    html_path = tmp_path / "tall-bottom-caption-reader.html"
    make_tall_bottom_caption_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Tall Table")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert top < 100
    assert bottom > 490
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "Benchmark Model Small" not in paragraph_text
    assert "The paragraph after the caption" in paragraph_text


def test_bottom_caption_table_crop_keeps_compact_math_rows(tmp_path: Path) -> None:
    pdf_path = tmp_path / "math-bottom-caption-table.pdf"
    html_path = tmp_path / "math-bottom-caption-reader.html"
    make_math_bottom_caption_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Math Table")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert top < 84
    assert bottom > 132
    assert "Table 1: Summary of formulations" in table_asset["caption"]
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "Methods DRAFT" not in paragraph_text
    assert "p1,...,pK" not in paragraph_text
    assert "two distinct groups" not in paragraph_text
    assert "paragraph after the caption" in paragraph_text


def test_appendix_label_table_caption_is_detected_and_suppressed(tmp_path: Path) -> None:
    pdf_path = tmp_path / "appendix-label-table.pdf"
    html_path = tmp_path / "appendix-label-reader.html"
    make_appendix_label_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Appendix Table")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert top < 100
    assert bottom > 235
    assert "Table A1: Table 1" in table_asset["caption"]
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "CCE (Ours) 245 MB" not in paragraph_text
    assert "paragraph after the appendix caption" in paragraph_text


def test_embedded_bottom_caption_table_is_detected_and_suppressed(tmp_path: Path) -> None:
    pdf_path = tmp_path / "embedded-bottom-caption-table.pdf"
    html_path = tmp_path / "embedded-bottom-caption-reader.html"
    make_embedded_bottom_caption_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Embedded Caption")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert top < 105
    assert bottom > 220
    assert "Table 16: Validation accuracy" in table_asset["caption"]
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "GPT-3 (LoRA)" not in paragraph_text
    assert "91.7 Table 16" not in paragraph_text
    assert "paragraph after the embedded caption" in paragraph_text


def test_caption_above_long_table_scans_past_default_depth(tmp_path: Path) -> None:
    pdf_path = tmp_path / "long-caption-above-table.pdf"
    html_path = tmp_path / "long-caption-above-reader.html"
    make_long_caption_above_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Long Table")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert top >= 118
    assert bottom > 505
    assert bottom < 540
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "T5-XXL (CNNDM)" not in paragraph_text
    assert "prose after the long table" in paragraph_text


def test_pipe_caption_tables_and_figures_are_detected(tmp_path: Path) -> None:
    pdf_path = tmp_path / "pipe-caption-visuals.pdf"
    html_path = tmp_path / "pipe-caption-reader.html"
    make_pipe_caption_visuals_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Pipe Captions")

    assert result.table_count >= 1
    assert result.figure_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    figure_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "figure")
    assert "Table 1 | Compact benchmark" in table_asset["caption"]
    assert "Figure 1 | Accuracy curve" in figure_asset["caption"]
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "Model Accuracy F1" not in paragraph_text
    assert "Plot" not in paragraph_text
    assert "Body text after the visuals" in paragraph_text


def test_uncaptioned_ruled_prompt_block_becomes_single_table_card(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ruled-prompt-block.pdf"
    html_path = tmp_path / "ruled-prompt-reader.html"
    make_ruled_prompt_block_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Prompt Block")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_cards = [card for card in manifest["cards"] if card["kind"] == "table"]
    assert len(table_cards) == 1
    assert "Hotpot" in table_cards[0]["text"]
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "Question What is the elevation range" not in paragraph_text
    assert "Action 1 Search" not in paragraph_text
    assert "Continued on next page" not in paragraph_text
    assert "Body text after the prompt block" in paragraph_text


def test_prompt_continuation_preamble_is_absorbed_into_table_card(tmp_path: Path) -> None:
    pdf_path = tmp_path / "prompt-continuation-preamble.pdf"
    html_path = tmp_path / "prompt-continuation-reader.html"
    make_prompt_continuation_preamble_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Prompt Continuation")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_cards = [card for card in manifest["cards"] if card["kind"] == "table"]
    assert len(table_cards) == 1
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert top < 125
    assert bottom > 530
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "NOT ENOUGH INFO" not in paragraph_text
    assert "Search[Nikolaj" not in paragraph_text
    assert "Body text after the continuation" in paragraph_text


def test_uncaptioned_ruled_prose_block_stays_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ruled-prose-block.pdf"
    html_path = tmp_path / "ruled-prose-reader.html"
    make_ruled_prose_block_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Ruled Prose")

    assert result.table_count == 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "ordinary explanatory prose" in paragraph_text
    assert "line styling alone" in paragraph_text


def test_prompt_table_crop_extends_to_late_trajectory_rows_without_footer(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "long-prompt-table.pdf"
    html_path = tmp_path / "long-prompt-reader.html"
    make_long_prompt_table_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Prompt Table")

    assert result.table_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    table_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "table")
    _, top, _, bottom = table_asset["bbox"]
    assert top < 205
    assert bottom > 660
    assert bottom < 735
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "Action: click[BuyNow]" not in paragraph_text
    assert "Score: 0.125 Score: 1.0" not in paragraph_text


def test_wide_bottom_caption_crop_uses_matching_side_of_adjacent_table(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "adjacent-bottom-tables.pdf"
    make_adjacent_bottom_tables_pdf(pdf_path)

    with pdfplumber.open(str(pdf_path)) as document:
        page = document.pages[0]
        words = extract_words(page)
        bbox = heuristic_table_bbox(
            (92.0, 184.0, 500.0, 198.0),
            page,
            words,
            caption_text="Table 1: Left task-specific success rates and neighboring caption continuation.",
        )

    assert bbox is not None
    x0, top, x1, bottom = bbox
    assert x0 < 100
    assert x1 < 395
    assert top < 110
    assert bottom < 186


def test_table_caption_matching_stays_in_column() -> None:
    captions = [
        (50.0, 278.0, 286.0, 287.0),
        (309.0, 165.0, 545.0, 174.0),
    ]
    left_table = (62.0, 300.0, 276.0, 428.0)
    right_table = (312.0, 172.0, 553.0, 204.0)

    assert nearby_bbox_indexes(0, captions, [left_table, right_table]) == [0]
    assert nearby_bbox_indexes(1, captions, [left_table, right_table]) == [1]

    adjacent_bottom_captions = [
        (110.0, 432.0, 226.0, 442.0),
        (105.0, 607.0, 232.0, 617.0),
    ]
    lower_table = (62.0, 447.0, 274.0, 597.0)
    assert nearby_bbox_indexes(0, adjacent_bottom_captions, [lower_table]) == []
    assert nearby_bbox_indexes(1, adjacent_bottom_captions, [lower_table]) == [0]


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


def test_multiline_figure_caption_stays_with_figure_card(tmp_path: Path) -> None:
    pdf_path = tmp_path / "multiline-figure-caption.pdf"
    html_path = tmp_path / "multiline-figure-caption-reader.html"
    make_multiline_figure_caption_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Figure Caption")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    figure_card = next(card for card in manifest["cards"] if card["kind"] == "figure")
    assert "formally introduced as a general decoding paradigm" in figure_card["text"]
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "formally introduced as a general decoding paradigm" not in paragraph_text
    assert "The body paragraph begins after the caption" in paragraph_text


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


def test_repeating_headers_and_footers_are_skipped(tmp_path: Path) -> None:
    pdf_path = tmp_path / "running-header-footer.pdf"
    html_path = tmp_path / "running-header-footer-reader.html"
    make_running_header_footer_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Running")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    all_text = " ".join(card["text"] for card in manifest["cards"])

    assert "Internal review copy" not in all_text
    assert "Confidential draft" not in all_text
    assert "First page body" in all_text
    assert "Second page body" in all_text
    assert "Third page body" in all_text
    assert "A Study Of Running Headers And Footers" in all_text


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


def test_captioned_large_figure_crop_absorbs_internal_labels(tmp_path: Path) -> None:
    pdf_path = tmp_path / "tall-labeled-figure.pdf"
    html_path = tmp_path / "tall-labeled-figure-reader.html"
    make_tall_labeled_figure_pdf(pdf_path)

    result = convert_pdf_to_card_html(pdf_path, output_path=html_path, title="Tall Figure")

    assert result.figure_count >= 1
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    figure_asset = next(asset for asset in manifest["assets"] if asset["kind"] == "figure")
    _, top, _, bottom = figure_asset["bbox"]
    assert top < 86
    assert bottom > 510
    paragraph_text = " ".join(
        card["text"] for card in manifest["cards"] if card["kind"] == "paragraph"
    )
    assert "Token-based Input" not in paragraph_text
    assert "Ahmed et al." not in paragraph_text
    assert "Body text below the figure" in paragraph_text


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
    assert looks_like_heading("3.1. DeepSeek-R1 Evaluation")
    assert looks_like_heading("↵ 4.2. Empirical Values")
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

    assert not is_formula_text_line(
        (318, 529, 504, 536),
        PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        "Nature’s Turn Freeze-Dried Fruit Snacks - Banana Crisps - Perfect",
    )
    assert not is_formula_text_line(
        (108, 249, 505, 259),
        PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        "trained with 1,012 human annotated trajectories, and a imitation + reinforcement learning (IL + RL)",
    )
    assert not is_formula_text_line(
        (307, 157, 541, 167),
        PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        "s are i.i.d., and denote ↵ = E(), then the number of",
    )
    assert not is_formula_text_line(
        (303, 281, 546, 299),
        PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        "(temp=0). We observe speedups of 2.6X (temp=1) and 3.4X",
    )
    assert not is_formula_text_line(
        (380, 664, 482, 676),
        PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        "[r (x, y)] = 0 for all x.",
    )
    assert not is_formula_text_line(
        (108, 285, 389, 295),
        PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        "holds for any reward function), we have f(r; π , β)(x, y) = β log r",
    )
    assert not is_formula_text_line(
        (321, 513, 413, 531),
        PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        "V (a) = V (g)+V (p)",
    )
    assert not is_formula_text_line(
        (104, 410, 383, 428),
        PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
        "composition W + W = W + BA, where B ⇥ ⇥",
    )

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


def test_orphan_formula_fragments_are_reader_noise() -> None:
    assert looks_like_reader_noise("ref")
    assert looks_like_reader_noise(") r(x, y),")
    assert strip_orphan_math_prefix(") r(x, y) . Note that the partition function remains.") == (
        "Note that the partition function remains."
    )


def test_formula_extraction_absorbs_short_math_bridge_fragments() -> None:
    def segment(text: str, x0: float, top: float, x1: float) -> dict[str, object]:
        return {"text": text, "bbox": (x0, top, x1, top + 10)}

    blocks = extract_formula_blocks(
        [
            segment("We now have:", 72, 180, 150),
            segment("max r(x, y) - beta D_KL(pi(y|x) || pi_ref(y|x))", 175, 214, 438),
            segment("[ log", 280, 244, 306),
            segment("pi(y|x)", 340, 258, 386),
            segment("ref", 438, 264, 452),
            segment("\uf8ee \uf8f0log", 280, 286, 306),
            segment("= min E log pi(y|x) - log Z(x) (12)", 188, 300, 504),
            segment("where we have partition function:", 72, 352, 240),
        ],
        page_number=1,
        page_rect=PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )

    assert len(blocks) == 1
    assert "[ log" in blocks[0].text
    assert "ref" in blocks[0].text
    assert "where we have" not in blocks[0].text


def test_formula_extraction_keeps_same_baseline_other_column_prose_out() -> None:
    def segment(text: str, x0: float, top: float, x1: float) -> dict[str, object]:
        return {"text": text, "bbox": (x0, top, x1, top + 12)}

    blocks = extract_formula_blocks(
        [
            segment("of various sampling methods. These approaches", 72, 210, 280),
            segment("q_{t+1} = M(x_t)", 330, 210, 470),
            segment("(1)", 500, 210, 520),
        ],
        page_number=1,
        page_rect=PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )

    assert len(blocks) == 1
    assert "q_{t+1}" in blocks[0].text
    assert "sampling methods" not in blocks[0].text


def test_formula_extraction_merges_gutter_split_equation_fragments() -> None:
    def segment(text: str, x0: float, top: float, x1: float) -> dict[str, object]:
        return {"text": text, "bbox": (x0, top, x1, top + 12)}

    blocks = extract_formula_blocks(
        [
            segment("J_GRPO(theta) = E[q ~ P(Q), {o_i}]", 92, 210, 312),
            segment("pi_theta(o_i|q) / pi_old(o_i|q) - beta D_KL", 292, 224, 530),
            segment("D_KL(pi_theta || pi_ref) =", 110, 252, 324),
            segment("pi_ref(o_i|q) / pi_theta(o_i|q) - log pi_ref(o_i|q)", 304, 266, 530),
        ],
        page_number=1,
        page_rect=PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )

    assert len(blocks) == 1
    assert "J_GRPO" in blocks[0].text
    assert "D_KL" in blocks[0].text
    assert blocks[0].bbox[0] < 100
    assert blocks[0].bbox[2] > 520


def test_formula_extraction_does_not_merge_across_full_width_prose() -> None:
    def segment(text: str, x0: float, top: float, x1: float) -> dict[str, object]:
        return {"text": text, "bbox": (x0, top, x1, top + 12)}

    blocks = extract_formula_blocks(
        [
            segment("J(theta) = E[x ~ p(x)] + beta", 206, 100, 406),
            segment(
                "where alpha and beta are hyperparameters, and A is the value",
                72,
                116,
                540,
            ),
            segment("A_i = r_i / std(r)", 226, 128, 386),
            segment("(3)", 520, 128, 536),
        ],
        page_number=1,
        page_rect=PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT),
    )

    assert len(blocks) == 2
    assert "J(theta)" in blocks[0].text
    assert "where alpha" not in " ".join(block.text for block in blocks)
    assert "A_i" in blocks[1].text


def test_segment_column_side_uses_center_for_gutter_math() -> None:
    assert segment_column_side((300.0, 120.0, 360.0, 132.0), PAGE_WIDTH) == "right"


def test_split_text_block_by_items_preserves_chunk_bboxes() -> None:
    items = []
    text_parts = []
    for index in range(8):
        text = (
            f"Line {index} keeps enough words to force a chunked paragraph while preserving "
            "its own source geometry."
        )
        top = 80.0 + index * 14.0
        if index < 3:
            bbox = (72.0, top, 290.0, top + 10.0)
        else:
            bbox = (330.0, top - 42.0, 540.0, top - 32.0)
        items.append({"text": text, "bbox": bbox})
        text_parts.append(text)

    block = TextBlock(
        page=1,
        bbox=(72.0, 80.0, 290.0, 188.0),
        text=" ".join(text_parts),
        items=items,
    )

    chunks = split_text_block_by_items(block, max_words=35, page_width=PAGE_WIDTH)

    assert len(chunks) > 1
    assert chunks[0][1] != block.bbox
    assert chunks[1][1] != block.bbox
    assert any(bbox is None for _, bbox, _ in chunks)
    assert any(bbox is not None and bbox[2] <= 300 for _, bbox, _ in chunks)
    assert any(bbox is not None and bbox[0] >= 300 for _, bbox, _ in chunks)
    assert all(items for _, _, items in chunks)


def test_split_text_block_by_items_uses_distinct_same_column_chunk_bboxes() -> None:
    items = []
    text_parts = []
    for index in range(10):
        text = (
            f"Line {index} keeps enough words to force chunking while preserving "
            "same-column source geometry."
        )
        top = 80.0 + index * 16.0
        bbox = (72.0, top, 290.0, top + 10.0)
        items.append({"text": text, "bbox": bbox})
        text_parts.append(text)

    block = TextBlock(
        page=1,
        bbox=(72.0, 80.0, 290.0, 234.0),
        text=" ".join(text_parts),
        items=items,
    )

    chunks = split_text_block_by_items(block, max_words=35, page_width=PAGE_WIDTH)

    bboxes = [bbox for _, bbox, _ in chunks]
    assert len(chunks) > 1
    assert all(bbox is not None for bbox in bboxes)
    assert all(bbox != block.bbox for bbox in bboxes)
    assert bboxes[0][3] < bboxes[-1][1]


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


def test_merge_text_blocks_does_not_continue_from_right_column_to_left() -> None:
    blocks = [
        TextBlock(
            page=1,
            bbox=(307.0, 593.0, 545.0, 603.0),
            text="a single neural network. By incorporating proper loss func-",
        ),
        TextBlock(
            page=1,
            bbox=(50.0, 631.0, 286.0, 641.0),
            text="through 500 test images from the ICDAR dataset at",
        ),
    ]

    merged = merge_text_blocks(blocks)

    assert len(merged) == 2


def test_merge_text_blocks_does_not_continue_lower_left_into_mid_right() -> None:
    blocks = [
        TextBlock(
            page=1,
            bbox=(50.0, 703.0, 286.0, 713.0),
            text="cludes thresholding and NMS, while others should refer to",
        ),
        TextBlock(
            page=1,
            bbox=(308.0, 605.0, 545.0, 615.0),
            text="tions, the detector can predict either rotated rectangles or",
        ),
    ]

    merged = merge_text_blocks(blocks)

    assert len(merged) == 2


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


def test_normalize_text_repairs_residual_pdf_ligature_words() -> None:
    assert normalize_text("where X and Y are hyper-parflameters%, and Z") == (
        "where X and Y are hyper-parameters, and Z"
    )
    assert normalize_text("TPable 5 shows values fPor different values wPhen M is T5") == (
        "Table 5 shows values for different values when M is T5"
    )


def test_normalize_text_repairs_formula_label_collisions() -> None:
    assert normalize_text("P 2 LPemma 3.3. D(p, q)") == "P 2 Lemma 3.3. D(p, q)"


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


def test_char_geometry_footnotes_do_not_break_two_column_ordering() -> None:
    chars = []
    for index, top in enumerate([100, 122, 144, 620, 642], start=1):
        chars.extend(
            make_unspaced_chars(
                f"Left column reading order line {index}",
                x=72,
                top=top,
                size=10,
            )
        )
    for index, top in enumerate([100, 122, 144, 166, 188], start=1):
        chars.extend(
            make_unspaced_chars(
                f"Right column reading order line {index}",
                x=330,
                top=top,
                size=10,
            )
        )
    chars.extend(make_unspaced_chars("2 This is a bottom footnote.", x=330, top=590, size=7))

    segments = split_chars_into_reading_order_segments(
        chars,
        page_width=PAGE_WIDTH,
        page_height=PAGE_HEIGHT,
    )

    texts = [segment["text"] for segment in segments]
    assert texts.index("Left column reading order line 5") < texts.index(
        "Right column reading order line 1"
    )
    assert texts[-1] == "2 This is a bottom footnote."
    assert segments[-1]["kind"] == "footnote"


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
                "text": "Algorithm 1 satisfies Equation (1). See Figure 2.",
                "bbox": (307.0, 205.2, 501.1, 215.1),
            },
            "Figure",
            allow_embedded=True,
        )
        is None
    )

    assert (
        slice_caption_from_segment(
            {
                "text": "The result is discussed in Table 5.",
                "bbox": (108.0, 637.8, 504.0, 651.0),
            },
            "Table",
            allow_embedded=True,
        )
        is None
    )

    appendix_caption = slice_caption_from_segment(
        {
            "text": "Table A3: Memory usage and time for additional models.",
            "bbox": (108.0, 637.8, 504.0, 651.0),
        },
        "Table",
    )
    assert appendix_caption is not None
    assert appendix_caption["text"].startswith("Table A3")

    embedded_table_caption = slice_caption_from_segment(
        {
            "text": "GPT-3 (LoRA) 63.8 85.6 89.2 91.7 Table 16: Validation accuracy.",
            "bbox": (120.0, 585.3, 504.0, 596.1),
        },
        "Table",
        allow_embedded=True,
    )
    assert embedded_table_caption is not None
    assert embedded_table_caption["text"].startswith("Table 16")
    assert embedded_table_caption["embedded_prefix"].endswith("91.7")

    missing_separator = slice_caption_from_segment(
        {
            "text": "Figure 2 AIME accuracy of DeepSeek-R1-Zero during training.",
            "bbox": (71.0, 468.7, 524.2, 479.6),
        },
        "Figure",
    )
    assert missing_separator is not None
    assert missing_separator["text"].startswith("Figure 2 AIME accuracy")

    assert (
        slice_caption_from_segment(
            {
                "text": "Figure 2 shows consistent improvement.",
                "bbox": (108.0, 637.8, 504.0, 651.0),
            },
            "Figure",
        )
        is None
    )


def test_wrapped_hyphenation_keeps_real_short_hyphen_terms() -> None:
    assert normalize_block_lines(["The observa-", "tions work."]) == "The observations work."
    assert normalize_block_lines(["The off-", "line stage."]) == "The off-line stage."


def test_private_use_pdf_glyphs_are_removed_from_normalized_text() -> None:
    assert "\uf8ff" not in normalize_text("reject the \uf8ff sample")
    assert "\uf8ee" not in normalize_text("left \uf8ee bracket \uf8fb")
    assert looks_like_reader_noise("(cid:52)(cid:72)(cid:86)(cid:87)")


def test_detected_visual_bbox_rejects_mostly_off_page_image() -> None:
    page_rect = PageRect(0, 0, PAGE_WIDTH, PAGE_HEIGHT)

    assert normalize_detected_visual_bbox((-620.0, 300.0, 1300.0, 620.0), page_rect) is None
    assert normalize_detected_visual_bbox((80.0, 120.0, 420.0, 330.0), page_rect) == (
        80.0,
        120.0,
        420.0,
        330.0,
    )


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


def test_reader_smoothing_does_not_merge_right_column_into_lower_left() -> None:
    cards = [
        Card(
            id="card-1",
            kind="paragraph",
            page=1,
            section="Document",
            text="a single neural network. By incorporating proper loss func-",
            bbox=(308.0, 593.0, 545.0, 603.0),
        ),
        Card(
            id="card-2",
            kind="paragraph",
            page=1,
            section="Document",
            text="through 500 test images from the ICDAR dataset at",
            bbox=(50.0, 631.0, 286.0, 641.0),
        ),
    ]

    smoothed = smooth_reader_cards(cards, max_words_per_card=95)

    assert len(smoothed) == 2


def test_reader_smoothing_does_not_merge_lower_left_into_mid_right() -> None:
    cards = [
        Card(
            id="card-1",
            kind="paragraph",
            page=1,
            section="Document",
            text="through 500 test images from the ICDAR dataset at their original resolution.",
            bbox=(50.0, 631.0, 286.0, 713.0),
        ),
        Card(
            id="card-2",
            kind="paragraph",
            page=1,
            section="Document",
            text="tions, the detector can predict either rotated rectangles or quadrangles.",
            bbox=(308.0, 605.0, 545.0, 713.0),
        ),
    ]

    smoothed = smooth_reader_cards(cards, max_words_per_card=95)

    assert len(smoothed) == 2


def test_region_suppression_requires_meaningful_horizontal_overlap() -> None:
    left_column_text = (50.0, 210.0, 285.0, 224.0)
    right_column_visual = (202.0, 180.0, 545.0, 376.0)
    figure_label = (330.0, 210.0, 510.0, 230.0)

    assert not region_contains_text_block(left_column_text, right_column_visual)
    assert region_contains_text_block(figure_label, right_column_visual)


def test_symmetric_overlap_catches_contained_visual_duplicates() -> None:
    small_visual = (462.0, 246.0, 528.0, 329.0)
    broad_captioned_crop = (252.0, 233.0, 541.0, 454.0)

    assert bboxes_substantially_overlap(small_visual, broad_captioned_crop, threshold=0.65)
    assert bboxes_substantially_overlap(broad_captioned_crop, small_visual, threshold=0.65)


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
