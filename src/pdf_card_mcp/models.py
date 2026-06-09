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
        return data


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
            "warnings": self.warnings,
            "cards": [card.to_dict() for card in self.cards],
            "assets": [asset.to_dict(include_data=include_data) for asset in self.assets],
        }
