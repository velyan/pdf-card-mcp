from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BBox = tuple[float, float, float, float]


@dataclass(slots=True)
class ImageAsset:
    id: str
    kind: str
    page: int
    alt: str
    caption: str
    data_uri: str
    width: int
    height: int
    bbox: BBox | None = None

    def to_dict(self, include_data: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "page": self.page,
            "alt": self.alt,
            "caption": self.caption,
            "width": self.width,
            "height": self.height,
        }
        if self.bbox is not None:
            data["bbox"] = list(self.bbox)
        if include_data:
            data["data_uri"] = self.data_uri
        return data


@dataclass(slots=True)
class Card:
    id: str
    kind: str
    page: int
    section: str
    text: str = ""
    image_id: str | None = None
    source_image_id: str | None = None
    bbox: BBox | None = None
    items: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "page": self.page,
            "section": self.section,
            "text": self.text,
        }
        if self.image_id:
            data["image_id"] = self.image_id
        if self.source_image_id:
            data["source_image_id"] = self.source_image_id
        if self.bbox is not None:
            data["bbox"] = list(self.bbox)
        if self.items:
            data["items"] = self.items
        return data


@dataclass(slots=True)
class StyleColorCandidate:
    id: str
    hex: str
    count: int
    source: str
    saturation: float
    luminance: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "hex": self.hex,
            "count": self.count,
            "source": self.source,
            "saturation": self.saturation,
            "luminance": self.luminance,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StyleColorCandidate":
        return cls(
            id=str(payload["id"]),
            hex=str(payload["hex"]),
            count=int(payload.get("count", 0)),
            source=str(payload.get("source", "unknown")),
            saturation=float(payload.get("saturation", 0.0)),
            luminance=float(payload.get("luminance", 0.0)),
        )


@dataclass(slots=True)
class StyleHints:
    palette: list[StyleColorCandidate] = field(default_factory=list)
    font_summary: dict[str, Any] = field(default_factory=dict)
    layout_density: str = "comfortable"
    visual_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "palette": [candidate.to_dict() for candidate in self.palette],
            "font_summary": self.font_summary,
            "layout_density": self.layout_density,
            "visual_counts": self.visual_counts,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "StyleHints | None":
        if not payload:
            return None
        return cls(
            palette=[
                StyleColorCandidate.from_dict(candidate)
                for candidate in payload.get("palette", [])
                if isinstance(candidate, dict)
            ],
            font_summary=dict(payload.get("font_summary", {})),
            layout_density=str(payload.get("layout_density", "comfortable")),
            visual_counts={
                str(key): int(value)
                for key, value in dict(payload.get("visual_counts", {})).items()
            },
        )


@dataclass(slots=True)
class ReaderStyle:
    bg: str
    paper: str
    paper_soft: str
    ink: str
    muted: str
    line: str
    accent: str
    accent_soft: str
    plum: str
    plum_soft: str
    clay: str
    clay_soft: str
    gold: str
    density: str = "comfortable"
    typography: str = "mixed"
    corner_style: str = "soft"
    shadow: str = "0 12px 30px rgba(59, 51, 43, 0.09)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bg": self.bg,
            "paper": self.paper,
            "paper_soft": self.paper_soft,
            "ink": self.ink,
            "muted": self.muted,
            "line": self.line,
            "accent": self.accent,
            "accent_soft": self.accent_soft,
            "plum": self.plum,
            "plum_soft": self.plum_soft,
            "clay": self.clay,
            "clay_soft": self.clay_soft,
            "gold": self.gold,
            "density": self.density,
            "typography": self.typography,
            "corner_style": self.corner_style,
            "shadow": self.shadow,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ReaderStyle | None":
        if not payload:
            return None
        soft = soft_reader_style()
        values = {**soft.to_dict(), **payload}
        return cls(
            bg=str(values["bg"]),
            paper=str(values["paper"]),
            paper_soft=str(values["paper_soft"]),
            ink=str(values["ink"]),
            muted=str(values["muted"]),
            line=str(values["line"]),
            accent=str(values["accent"]),
            accent_soft=str(values["accent_soft"]),
            plum=str(values["plum"]),
            plum_soft=str(values["plum_soft"]),
            clay=str(values["clay"]),
            clay_soft=str(values["clay_soft"]),
            gold=str(values["gold"]),
            density=str(values.get("density", "comfortable")),
            typography=str(values.get("typography", "mixed")),
            corner_style=str(values.get("corner_style", "soft")),
            shadow=str(values.get("shadow", soft.shadow)),
        )


def soft_reader_style() -> ReaderStyle:
    return ReaderStyle(
        bg="#f5f2eb",
        paper="#fffdf8",
        paper_soft="#f7f2e9",
        ink="#282522",
        muted="#746f67",
        line="#d9d1c7",
        accent="#6f836e",
        accent_soft="#e7eee3",
        plum="#766374",
        plum_soft="#eee8ec",
        clay="#a98677",
        clay_soft="#f0e4de",
        gold="#a9834d",
    )


@dataclass(slots=True)
class ConversionManifest:
    title: str
    source_pdf: Path
    page_count: int
    processed_pages: int
    cards: list[Card]
    assets: list[ImageAsset]
    warnings: list[str] = field(default_factory=list)
    theme: str = "soft"
    style_engine: str = "fixed"
    style_hints: StyleHints | None = None
    style: ReaderStyle | None = None

    @property
    def table_count(self) -> int:
        return sum(1 for asset in self.assets if asset.kind == "table")

    @property
    def figure_count(self) -> int:
        return sum(1 for asset in self.assets if asset.kind == "figure")

    @property
    def formula_count(self) -> int:
        return sum(1 for asset in self.assets if asset.kind == "formula")

    @property
    def card_count(self) -> int:
        return len(self.cards)

    def to_dict(self, include_data: bool = False) -> dict[str, Any]:
        return {
            "title": self.title,
            "source_pdf": str(self.source_pdf),
            "page_count": self.page_count,
            "processed_pages": self.processed_pages,
            "card_count": self.card_count,
            "table_count": self.table_count,
            "figure_count": self.figure_count,
            "formula_count": self.formula_count,
            "theme": self.theme,
            "style_engine": self.style_engine,
            "warnings": self.warnings,
            "cards": [card.to_dict() for card in self.cards],
            "assets": [asset.to_dict(include_data=include_data) for asset in self.assets],
            "style_hints": self.style_hints.to_dict() if self.style_hints else None,
            "style": self.style.to_dict() if self.style else None,
        }
