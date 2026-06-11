from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfgen import canvas

from pdf_card_mcp.converter import convert_pdf_to_card_html
from pdf_card_mcp.models import ImageAsset, ReaderStyle, StyleColorCandidate, StyleHints
from pdf_card_mcp.style import (
    StylePlan,
    extract_palette_candidates,
    reader_style_from_plan,
    reader_style_is_safe,
)


def make_colored_pdf(path: Path, accent: colors.Color) -> None:
    page = canvas.Canvas(str(path), pagesize=(360, 260))
    page.setFillColor(accent)
    page.rect(24, 178, 312, 46, stroke=0, fill=1)
    page.setFillColor(colors.white)
    page.setFont("Helvetica-Bold", 18)
    page.drawString(38, 194, "Styled PDF")
    page.setFillColor(accent)
    page.setLineWidth(2)
    page.line(24, 155, 336, 155)
    page.setFillColor(colors.black)
    page.setFont("Times-Roman", 12)
    page.drawString(24, 122, "This body text gives the converter a readable card.")
    page.save()


def test_pdf_style_engine_persists_different_pdf_inspired_accents(tmp_path: Path) -> None:
    blue_pdf = tmp_path / "blue.pdf"
    green_pdf = tmp_path / "green.pdf"
    make_colored_pdf(blue_pdf, colors.Color(0.05, 0.32, 0.62))
    make_colored_pdf(green_pdf, colors.Color(0.1, 0.48, 0.28))

    blue_result = convert_pdf_to_card_html(blue_pdf, output_path=tmp_path / "blue.html")
    green_result = convert_pdf_to_card_html(green_pdf, output_path=tmp_path / "green.html")

    blue_manifest = json.loads(blue_result.manifest_path.read_text(encoding="utf-8"))
    green_manifest = json.loads(green_result.manifest_path.read_text(encoding="utf-8"))

    assert blue_manifest["style_engine"] == "pdf"
    assert green_manifest["style_engine"] == "pdf"
    assert blue_manifest["style_hints"]["palette"]
    assert green_manifest["style_hints"]["palette"]
    assert blue_manifest["style"]["accent"] != green_manifest["style"]["accent"]
    assert reader_style_is_safe(ReaderStyle.from_dict(blue_manifest["style"]))


def test_palette_extraction_filters_black_and_white_noise() -> None:
    asset = ImageAsset(
        id="source-page-1",
        kind="source_page",
        page=1,
        alt="Source page",
        caption="",
        data_uri=(
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mP4"
            "/58BAAT/Af9jgNErAAAAAElFTkSuQmCC"
        ),
        width=1,
        height=1,
    )

    assert extract_palette_candidates([asset]) == []


def test_style_plan_accepts_valid_candidate_and_rejects_unknown_candidate() -> None:
    hints = StyleHints(
        palette=[
            StyleColorCandidate(
                id="candidate-1",
                hex="#1f5f8f",
                count=10,
                source="test",
                saturation=0.6,
                luminance=0.25,
            )
        ]
    )

    style, warnings = reader_style_from_plan(
        hints,
        StylePlan(accent_id="candidate-1", density="compact", corner_style="square"),
    )

    assert style.accent == "#1f5f8f"
    assert style.density == "compact"
    assert style.corner_style == "square"
    assert warnings == []

    fallback_style, warnings = reader_style_from_plan(hints, StylePlan(accent_id="missing"))

    assert fallback_style.accent == "#1f5f8f"
    assert warnings
