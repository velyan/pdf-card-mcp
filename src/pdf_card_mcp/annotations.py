from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import BBox, Card, ConversionManifest

ANNOTATION_SCHEMA_VERSION = "pdf-card-annotations/v1"
class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: Literal["highlight", "note"]
    card_id: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    bbox: tuple[float, float, float, float] | None = None
    text_quote: str = ""
    text_start: int | None = Field(default=None, ge=0)
    text_end: int | None = Field(default=None, ge=0)
    text_hash: str | None = None
    color: Literal["yellow", "green", "blue", "pink", "purple"] = "yellow"
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    visibility: Literal["private", "public"] = "private"
    created_at: str | None = None
    updated_at: str | None = None

    @field_validator("id", "card_id", "text_quote", "note", mode="before")
    @classmethod
    def coerce_string(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("bbox", mode="before")
    @classmethod
    def validate_bbox(cls, value: Any) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError("bbox must contain four coordinates")
        coords = tuple(float(coord) for coord in value)
        if coords[2] < coords[0] or coords[3] < coords[1]:
            raise ValueError("bbox max coordinates must be greater than min coordinates")
        return coords

    @field_validator("text_end")
    @classmethod
    def validate_text_range(cls, value: int | None, info) -> int | None:
        start = info.data.get("text_start")
        if value is not None and start is not None and value < start:
            raise ValueError("text_end must be greater than or equal to text_start")
        return value

    def public_copy(self) -> "Annotation":
        return self.model_copy(update={"visibility": "public"})


class AnnotationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = ANNOTATION_SCHEMA_VERSION
    document_id: str = Field(min_length=1)
    manifest_hash: str = Field(min_length=1)
    created_at: str
    updated_at: str
    annotations: list[Annotation] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value != ANNOTATION_SCHEMA_VERSION:
            raise ValueError(f"unsupported annotation schema_version: {value}")
        return value


@dataclass(slots=True)
class AnnotationValidationResult:
    bundle: AnnotationBundle
    warnings: list[str]
    rejected_count: int

    @property
    def accepted_count(self) -> int:
        return len(self.bundle.annotations)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest_fingerprint_payload(manifest: ConversionManifest) -> dict[str, Any]:
    return {
        "title": manifest.title,
        "page_count": manifest.page_count,
        "processed_pages": manifest.processed_pages,
        "cards": [
            {
                "id": card.id,
                "kind": card.kind,
                "page": card.page,
                "section": card.section,
                "text": card.text,
                "bbox": list(card.bbox) if card.bbox is not None else None,
                "items": card.items,
            }
            for card in manifest.cards
        ],
        "assets": [
            {
                "id": asset.id,
                "kind": asset.kind,
                "page": asset.page,
                "alt": asset.alt,
                "caption": asset.caption,
                "width": asset.width,
                "height": asset.height,
                "bbox": list(asset.bbox) if asset.bbox is not None else None,
            }
            for asset in manifest.assets
        ],
    }


def manifest_hash(manifest: ConversionManifest) -> str:
    payload = manifest_fingerprint_payload(manifest)
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def document_id_for_manifest(manifest: ConversionManifest) -> str:
    return f"pdf-card-{manifest_hash(manifest)[:16]}"


def empty_annotation_bundle(manifest: ConversionManifest) -> AnnotationBundle:
    timestamp = now_iso()
    return AnnotationBundle(
        document_id=document_id_for_manifest(manifest),
        manifest_hash=manifest_hash(manifest),
        created_at=timestamp,
        updated_at=timestamp,
        annotations=[],
    )


def load_annotation_bundle(path: Path) -> AnnotationBundle:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("annotation bundle must be a JSON object")
    return AnnotationBundle.model_validate(payload)


def write_annotation_bundle(bundle: AnnotationBundle, path: Path) -> None:
    path.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def annotation_bundle_to_client_dict(bundle: AnnotationBundle) -> dict[str, Any]:
    return bundle.model_dump(mode="json")


def validate_annotation_bundle(
    bundle: AnnotationBundle,
    manifest: ConversionManifest,
    *,
    include_private: bool = False,
) -> AnnotationValidationResult:
    expected_document_id = document_id_for_manifest(manifest)
    expected_manifest_hash = manifest_hash(manifest)
    warnings: list[str] = []
    if bundle.document_id != expected_document_id:
        warnings.append("Annotation bundle document_id does not match the reader manifest.")
    if bundle.manifest_hash != expected_manifest_hash:
        warnings.append("Annotation bundle manifest_hash does not match the reader manifest.")

    resolved: list[Annotation] = []
    rejected = 0
    for annotation in bundle.annotations:
        if annotation.visibility == "private" and not include_private:
            continue
        matched = resolve_annotation(annotation, manifest)
        if matched is None:
            rejected += 1
            warnings.append(f"Rejected annotation {annotation.id}: no matching card anchor.")
            continue
        resolved.append(matched)

    filtered = bundle.model_copy(
        update={
            "document_id": expected_document_id,
            "manifest_hash": expected_manifest_hash,
            "updated_at": now_iso(),
            "annotations": resolved,
        }
    )
    return AnnotationValidationResult(bundle=filtered, warnings=warnings, rejected_count=rejected)


def resolve_annotation(annotation: Annotation, manifest: ConversionManifest) -> Annotation | None:
    cards_by_id = {card.id: card for card in manifest.cards}
    card = cards_by_id.get(annotation.card_id)
    if card is None:
        card = find_card_for_annotation(annotation, manifest.cards)
    if card is None:
        return None

    updates: dict[str, Any] = {"card_id": card.id, "page": card.page}
    start = annotation.text_start
    end = annotation.text_end
    quote = annotation.text_quote

    if quote and start is not None and end is not None:
        if card.text[start:end] != quote:
            recovered = find_quote_range(card.text, quote)
            if recovered is None:
                return None
            start, end = recovered
    elif quote:
        recovered = find_quote_range(card.text, quote)
        if recovered is None:
            return None
        start, end = recovered
    elif annotation.text_hash:
        if annotation.text_hash != text_hash(card.text):
            return None

    if start is not None and end is not None:
        updates["text_start"] = start
        updates["text_end"] = end
        updates["text_quote"] = card.text[start:end]
        updates["text_hash"] = text_hash(card.text)

    return annotation.model_copy(update=updates)


def find_card_for_annotation(annotation: Annotation, cards: list[Card]) -> Card | None:
    candidates = [card for card in cards if annotation.page is None or card.page == annotation.page]
    if annotation.text_quote:
        for card in candidates:
            if find_quote_range(card.text, annotation.text_quote) is not None:
                return card
    if annotation.text_hash:
        for card in candidates:
            if text_hash(card.text) == annotation.text_hash:
                return card
    if annotation.bbox is not None:
        for card in candidates:
            if card.bbox is not None and bbox_overlap_ratio(annotation.bbox, card.bbox) >= 0.45:
                return card
    return None


def find_quote_range(text: str, quote: str) -> tuple[int, int] | None:
    if not quote:
        return None
    index = text.find(quote)
    if index >= 0:
        return index, index + len(quote)
    collapsed_text, text_index_map = collapse_spaces_with_index_map(text)
    collapsed_quote = " ".join(quote.split())
    if not collapsed_quote:
        return None
    collapsed_index = collapsed_text.find(collapsed_quote)
    if collapsed_index < 0:
        return None
    original_start = text_index_map[collapsed_index]
    original_end = text_index_map[collapsed_index + len(collapsed_quote) - 1] + 1
    return original_start, original_end


def collapse_spaces_with_index_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    indexes: list[int] = []
    previous_was_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if chars and not previous_was_space:
                chars.append(" ")
                indexes.append(index)
            previous_was_space = True
            continue
        chars.append(char)
        indexes.append(index)
        previous_was_space = False
    if chars and chars[-1] == " ":
        chars.pop()
        indexes.pop()
    return "".join(chars), indexes


def bbox_overlap_ratio(a: BBox, b: BBox) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1.0)
    return overlap / area
