from __future__ import annotations

import base64
import colorsys
import io
import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from statistics import median
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, Field

from .models import (
    Card,
    ImageAsset,
    ReaderStyle,
    StyleColorCandidate,
    StyleHints,
    soft_reader_style,
)

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
VALID_DENSITIES = {"compact", "comfortable", "spacious"}
VALID_TYPOGRAPHY = {"serif", "sans", "mixed"}
VALID_CORNER_STYLES = {"square", "soft", "rounded"}
MIN_TEXT_CONTRAST = 4.5


class StylePlan(BaseModel):
    accent_id: str | None = Field(
        default=None,
        description="ID of the palette candidate to use as the reader accent.",
    )
    secondary_id: str | None = Field(
        default=None,
        description="Optional palette candidate ID for secondary badges and content types.",
    )
    tone: Literal["neutral", "warm", "cool", "vivid"] = Field(
        default="neutral",
        description="Overall color handling. This selects bounded derivation rules, not raw CSS.",
    )
    typography: Literal["serif", "sans", "mixed"] = Field(
        default="mixed",
        description="Reader type mode chosen from the PDF font hints.",
    )
    density: Literal["compact", "comfortable", "spacious"] = Field(
        default="comfortable",
        description="Card spacing density.",
    )
    corner_style: Literal["square", "soft", "rounded"] = Field(
        default="soft",
        description="Reader corner radius style.",
    )
    reason: str | None = Field(
        default=None,
        description="Short audit reason. It is stored only in warnings, never rendered as CSS.",
    )


def extract_style_hints(
    assets: Sequence[ImageAsset],
    cards: Sequence[Card],
    *,
    font_summary: dict[str, Any] | None = None,
) -> StyleHints:
    visual_counts = Counter(asset.kind for asset in assets if asset.kind != "source_page")
    text_cards = sum(1 for card in cards if not card.image_id)
    visual_cards = sum(1 for card in cards if card.image_id)
    layout_density = infer_layout_density(len(cards), text_cards, visual_cards)
    return StyleHints(
        palette=extract_palette_candidates(assets),
        font_summary=font_summary or {},
        layout_density=layout_density,
        visual_counts={key: int(value) for key, value in visual_counts.items()},
    )


def collect_font_summary(pages: Sequence[Any]) -> dict[str, Any]:
    font_counts: Counter[str] = Counter()
    sizes: list[float] = []
    family_counts: Counter[str] = Counter()

    for page in pages:
        for char in getattr(page, "chars", []) or []:
            font_name = str(char.get("fontname", "") or "")
            if font_name:
                cleaned = clean_font_name(font_name)
                font_counts[cleaned] += 1
                family_counts[classify_font(cleaned)] += 1
            try:
                size = float(char.get("size", 0) or 0)
            except (TypeError, ValueError):
                size = 0
            if 4 <= size <= 96:
                sizes.append(size)

    dominant_family = "mixed"
    if family_counts:
        family, count = family_counts.most_common(1)[0]
        total = sum(family_counts.values())
        if count / max(total, 1) >= 0.55:
            dominant_family = family

    return {
        "dominant_font": font_counts.most_common(1)[0][0] if font_counts else "",
        "dominant_family": dominant_family,
        "median_size": round(float(median(sizes)), 2) if sizes else None,
        "font_count": len(font_counts),
    }


def extract_palette_candidates(assets: Sequence[ImageAsset]) -> list[StyleColorCandidate]:
    buckets: Counter[tuple[int, int, int]] = Counter()
    source_counts: Counter[tuple[int, int, int]] = Counter()
    selected = [
        *[asset for asset in assets if asset.kind == "source_page"][:3],
        *[asset for asset in assets if asset.kind != "source_page"][:6],
    ]

    for asset in selected:
        weight = 2 if asset.kind != "source_page" else 1
        for color, count in sample_asset_colors(asset):
            buckets[color] += count * weight
            source_counts[color] += 1

    scored: list[tuple[float, tuple[int, int, int], int]] = []
    for color, count in buckets.items():
        saturation = color_saturation(color)
        luminance = relative_luminance_rgb(color)
        if saturation < 0.18 or luminance < 0.12 or luminance > 0.9:
            continue
        score = count * (0.7 + saturation) * (1.0 - min(abs(luminance - 0.48), 0.48))
        if source_counts[color] > 1:
            score *= 1.18
        scored.append((score, color, count))

    scored.sort(reverse=True)
    candidates: list[StyleColorCandidate] = []
    for _score, color, count in scored:
        if any(color_distance(color, hex_to_rgb(candidate.hex)) < 44 for candidate in candidates):
            continue
        hex_value = rgb_to_hex(color)
        candidates.append(
            StyleColorCandidate(
                id=f"candidate-{len(candidates) + 1}",
                hex=hex_value,
                count=int(count),
                source="rendered_pdf",
                saturation=round(color_saturation(color), 3),
                luminance=round(relative_luminance_rgb(color), 3),
            )
        )
        if len(candidates) >= 6:
            break
    return candidates


def reader_style_from_hints(hints: StyleHints | None) -> ReaderStyle:
    if not hints or not hints.palette:
        return soft_reader_style()
    accent = hints.palette[0].hex
    secondary = hints.palette[1].hex if len(hints.palette) > 1 else None
    typography = str(hints.font_summary.get("dominant_family", "mixed"))
    return derive_reader_style(
        accent,
        secondary=secondary,
        density=hints.layout_density,
        typography=typography,
        corner_style="soft",
    )


def reader_style_from_plan(hints: StyleHints | None, plan: StylePlan) -> tuple[ReaderStyle, list[str]]:
    warnings: list[str] = []
    candidate_map = {candidate.id: candidate.hex for candidate in hints.palette} if hints else {}
    accent = candidate_map.get(plan.accent_id or "")
    secondary = candidate_map.get(plan.secondary_id or "")

    if plan.accent_id and accent is None:
        warnings.append(f"Style sampling ignored unknown accent candidate: {plan.accent_id}.")
    if plan.secondary_id and secondary is None:
        warnings.append(f"Style sampling ignored unknown secondary candidate: {plan.secondary_id}.")

    if accent is None:
        if hints and hints.palette:
            accent = hints.palette[0].hex
            warnings.append("Style sampling did not choose a valid accent; used top PDF palette color.")
        else:
            warnings.append("Style sampling had no usable PDF palette; used the default soft style.")
            return soft_reader_style(), warnings

    typography = plan.typography
    if hints and typography == "mixed":
        typography = str(hints.font_summary.get("dominant_family", "mixed"))

    style = derive_reader_style(
        accent,
        secondary=secondary,
        density=plan.density,
        typography=typography,
        corner_style=plan.corner_style,
        vivid=plan.tone == "vivid",
    )
    if plan.reason:
        warnings.append(f"Style sampling applied: {plan.reason[:160]}")
    return safe_reader_style(style), warnings


def style_sampling_prompt(title: str, hints: StyleHints | None) -> str:
    payload = {
        "title": title,
        "palette_candidates": [
            candidate.to_dict() for candidate in (hints.palette if hints else [])
        ],
        "font_summary": hints.font_summary if hints else {},
        "layout_density": hints.layout_density if hints else "comfortable",
        "visual_counts": hints.visual_counts if hints else {},
        "allowed": {
            "tone": ["neutral", "warm", "cool", "vivid"],
            "typography": ["serif", "sans", "mixed"],
            "density": ["compact", "comfortable", "spacious"],
            "corner_style": ["square", "soft", "rounded"],
        },
    }
    return (
        "Choose bounded reader style tokens for a PDF-derived HTML reader.\n"
        "Use only palette candidate IDs for accent_id and secondary_id. Do not output CSS, "
        "hex colors, source text edits, or prose outside the structured result.\n"
        "Prefer a style that is inspired by the PDF but remains readable and calm.\n\n"
        f"Style hints JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )


def safe_reader_style(style: ReaderStyle | None) -> ReaderStyle:
    if style is None or not reader_style_is_safe(style):
        return soft_reader_style()
    return style


def reader_style_css_variables(style: ReaderStyle | None) -> dict[str, str]:
    safe = safe_reader_style(style)
    radius = {"square": "10px", "soft": "18px", "rounded": "24px"}.get(
        safe.corner_style,
        "18px",
    )
    gap = {"compact": "14px", "comfortable": "18px", "spacious": "22px"}.get(
        safe.density,
        "18px",
    )
    card_padding = {
        "compact": "12px 20px 20px",
        "comfortable": "16px 26px 24px",
        "spacious": "18px 30px 28px",
    }.get(safe.density, "16px 26px 24px")
    font_ui, font_text, font_heading = font_stacks(safe.typography)
    variables = {
        "--bg": safe.bg,
        "--paper": safe.paper,
        "--paper-soft": safe.paper_soft,
        "--ink": safe.ink,
        "--muted": safe.muted,
        "--line": safe.line,
        "--accent": safe.accent,
        "--accent-soft": safe.accent_soft,
        "--accent-strong": mix_hex(safe.accent, "#ffffff", 0.34),
        "--accent-strong-rgb": rgb_channels(mix_hex(safe.accent, "#ffffff", 0.34)),
        "--plum": safe.plum,
        "--plum-soft": safe.plum_soft,
        "--plum-strong": mix_hex(safe.plum, "#ffffff", 0.36),
        "--plum-strong-rgb": rgb_channels(mix_hex(safe.plum, "#ffffff", 0.36)),
        "--clay": safe.clay,
        "--clay-soft": safe.clay_soft,
        "--gold": safe.gold,
        "--bg-rgb": rgb_channels(safe.bg),
        "--paper-rgb": rgb_channels(safe.paper),
        "--paper-soft-rgb": rgb_channels(safe.paper_soft),
        "--ink-rgb": rgb_channels(safe.ink),
        "--muted-rgb": rgb_channels(safe.muted),
        "--line-rgb": rgb_channels(safe.line),
        "--accent-rgb": rgb_channels(safe.accent),
        "--plum-rgb": rgb_channels(safe.plum),
        "--clay-rgb": rgb_channels(safe.clay),
        "--gold-rgb": rgb_channels(safe.gold),
        "--shadow": safe.shadow,
        "--radius": radius,
        "--card-gap": gap,
        "--card-body-padding": card_padding,
        "--font-ui": font_ui,
        "--font-text": font_text,
        "--font-heading": font_heading,
        "--mark-bg": mix_hex("#f7e6a8", safe.accent, 0.12),
        "--modal-bg": mix_hex("#efebe7", safe.accent, 0.05),
        "--meter-bg": mix_hex(safe.line, safe.paper_soft, 0.45),
    }
    return variables


def derive_reader_style(
    accent_hex: str,
    *,
    secondary: str | None = None,
    density: str = "comfortable",
    typography: str = "mixed",
    corner_style: str = "soft",
    vivid: bool = False,
) -> ReaderStyle:
    soft = soft_reader_style()
    accent = normalize_hex(accent_hex) or soft.accent
    accent = ensure_contrast(accent, "#fffdf8", 3.0)
    secondary_hex = normalize_hex(secondary or "") or soft.plum
    clay = soft.clay
    gold = soft.gold

    if vivid:
        accent_soft_ratio = 0.2
        line_ratio = 0.24
    else:
        accent_soft_ratio = 0.14
        line_ratio = 0.18

    return ReaderStyle(
        bg=mix_hex("#f5f2eb", accent, 0.08),
        paper=mix_hex("#fffdf8", accent, 0.025),
        paper_soft=mix_hex("#f7f2e9", accent, 0.075),
        ink=soft.ink,
        muted=mix_hex(soft.muted, accent, 0.08),
        line=mix_hex(soft.line, accent, line_ratio),
        accent=accent,
        accent_soft=mix_hex("#ffffff", accent, accent_soft_ratio),
        plum=ensure_contrast(secondary_hex, "#fffdf8", 3.0),
        plum_soft=mix_hex("#ffffff", secondary_hex, 0.13),
        clay=clay,
        clay_soft=soft.clay_soft,
        gold=gold,
        density=density if density in VALID_DENSITIES else "comfortable",
        typography=typography if typography in VALID_TYPOGRAPHY else "mixed",
        corner_style=corner_style if corner_style in VALID_CORNER_STYLES else "soft",
        shadow=soft.shadow,
    )


def reader_style_is_safe(style: ReaderStyle) -> bool:
    color_fields = (
        style.bg,
        style.paper,
        style.paper_soft,
        style.ink,
        style.muted,
        style.line,
        style.accent,
        style.accent_soft,
        style.plum,
        style.plum_soft,
        style.clay,
        style.clay_soft,
        style.gold,
    )
    if any(normalize_hex(value) is None for value in color_fields):
        return False
    if style.density not in VALID_DENSITIES:
        return False
    if style.typography not in VALID_TYPOGRAPHY:
        return False
    if style.corner_style not in VALID_CORNER_STYLES:
        return False
    if contrast_ratio(style.ink, style.paper) < MIN_TEXT_CONTRAST:
        return False
    if contrast_ratio(style.ink, style.bg) < MIN_TEXT_CONTRAST:
        return False
    if contrast_ratio(style.muted, style.paper) < 3.0:
        return False
    return True


def sample_asset_colors(asset: ImageAsset) -> list[tuple[tuple[int, int, int], int]]:
    try:
        image_bytes = base64.b64decode(asset.data_uri.split(",", 1)[1])
    except Exception:
        return []
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
            image.thumbnail((180, 180))
            pixel_data = getattr(image, "get_flattened_data", None)
            pixels = list(pixel_data() if pixel_data else image.getdata())
    except Exception:
        return []

    step = max(1, len(pixels) // 18000)
    buckets: Counter[tuple[int, int, int]] = Counter()
    for red, green, blue in pixels[::step]:
        color = bucket_rgb((red, green, blue))
        luminance = relative_luminance_rgb(color)
        saturation = color_saturation(color)
        if luminance > 0.92 or luminance < 0.08 or saturation < 0.1:
            continue
        buckets[color] += 1
    return buckets.most_common(32)


def infer_layout_density(total_cards: int, text_cards: int, visual_cards: int) -> str:
    if total_cards >= 55 and visual_cards < max(4, text_cards // 5):
        return "compact"
    if visual_cards >= max(3, text_cards // 3):
        return "spacious"
    return "comfortable"


def clean_font_name(font_name: str) -> str:
    cleaned = font_name.split("+")[-1]
    return cleaned.replace("-", " ").replace("_", " ").strip()


def classify_font(font_name: str) -> str:
    upper = font_name.upper()
    if any(token in upper for token in ("MONO", "CODE", "TYPEWRITER", "COURIER")):
        return "sans"
    if any(token in upper for token in ("TIMES", "GARAMOND", "GEORGIA", "SERIF", "MINION")):
        return "serif"
    if any(token in upper for token in ("HELVETICA", "ARIAL", "ROBOTO", "SANS", "CALIBRI")):
        return "sans"
    return "mixed"


def font_stacks(typography: str) -> tuple[str, str, str]:
    ui = 'ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    serif = 'ui-serif, Georgia, "Times New Roman", serif'
    if typography == "sans":
        return ui, ui, ui
    if typography == "serif":
        return ui, serif, serif
    return ui, serif, serif


def normalize_hex(value: str) -> str | None:
    if not HEX_COLOR_RE.fullmatch(str(value)):
        return None
    return str(value).lower()


def bucket_rgb(color: tuple[int, int, int], bucket_size: int = 24) -> tuple[int, int, int]:
    return tuple(
        max(0, min(255, int(round(channel / bucket_size) * bucket_size)))
        for channel in color
    )


def rgb_to_hex(color: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(channel))):02x}" for channel in color)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = normalize_hex(value) or "#000000"
    return (
        int(normalized[1:3], 16),
        int(normalized[3:5], 16),
        int(normalized[5:7], 16),
    )


def rgb_channels(value: str) -> str:
    return " ".join(str(channel) for channel in hex_to_rgb(value))


def color_saturation(color: tuple[int, int, int]) -> float:
    red, green, blue = [channel / 255 for channel in color]
    _hue, saturation, _value = colorsys.rgb_to_hsv(red, green, blue)
    return float(saturation)


def relative_luminance_rgb(color: tuple[int, int, int]) -> float:
    channels = []
    for channel in color:
        value = channel / 255
        if value <= 0.03928:
            channels.append(value / 12.92)
        else:
            channels.append(((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def relative_luminance_hex(value: str) -> float:
    return relative_luminance_rgb(hex_to_rgb(value))


def contrast_ratio(first: str, second: str) -> float:
    first_luminance = relative_luminance_hex(first)
    second_luminance = relative_luminance_hex(second)
    light = max(first_luminance, second_luminance)
    dark = min(first_luminance, second_luminance)
    return (light + 0.05) / (dark + 0.05)


def ensure_contrast(foreground: str, background: str, target: float) -> str:
    color = normalize_hex(foreground) or soft_reader_style().accent
    if contrast_ratio(color, background) >= target:
        return color
    for ratio in (0.12, 0.2, 0.28, 0.36, 0.44, 0.52, 0.6):
        candidate = mix_hex(color, "#000000", ratio)
        if contrast_ratio(candidate, background) >= target:
            return candidate
    return color


def mix_hex(first: str, second: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, float(ratio)))
    first_rgb = hex_to_rgb(first)
    second_rgb = hex_to_rgb(second)
    return rgb_to_hex(
        tuple(
            int(round((first_rgb[index] * (1.0 - ratio)) + (second_rgb[index] * ratio)))
            for index in range(3)
        )
    )


def color_distance(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    return math.sqrt(sum((first[index] - second[index]) ** 2 for index in range(3)))
