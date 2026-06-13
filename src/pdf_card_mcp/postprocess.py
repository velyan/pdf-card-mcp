from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .html_renderer import render_html
from .models import BBox, Card, ConversionManifest, ImageAsset, ReaderStyle, StyleHints

TextCardKind = Literal["paragraph", "heading", "footnote", "metadata"]

TEXT_CARD_KINDS = {"paragraph", "heading", "footnote", "metadata"}
NON_TEXT_CARD_KINDS = {"table", "figure", "formula"}


class BoundaryOperation(BaseModel):
    op: Literal["merge", "extract_heading", "set_kind"] = Field(
        description="Boundary-only operation to polish reader cards."
    )
    card_ids: list[str] = Field(
        default_factory=list,
        description="Consecutive card ids to merge when op is merge.",
    )
    card_id: str | None = Field(
        default=None,
        description="Target card id when op is extract_heading or set_kind.",
    )
    exact_text: str | None = Field(
        default=None,
        description="Exact source substring to isolate as a heading.",
    )
    kind: TextCardKind | None = Field(
        default=None,
        description="Target card kind when op is set_kind.",
    )
    reason: str | None = Field(
        default=None,
        description="Short reason for auditability. Not rendered to the reader.",
    )


class BoundaryPlan(BaseModel):
    operations: list[BoundaryOperation] = Field(default_factory=list)


@dataclass(slots=True)
class BoundaryPolishResult:
    cards: list[Card]
    warnings: list[str]
    applied_operations: int


SamplingPlanner = Callable[[str], Awaitable[BoundaryPlan]]


async def polish_cards_with_sampling(
    manifest: ConversionManifest,
    planner: SamplingPlanner,
    *,
    window_size: int = 10,
    max_operations_per_window: int = 8,
) -> BoundaryPolishResult:
    """Ask the host LLM for boundary-only polish operations and validate them."""
    cards = [clone_card(card) for card in manifest.cards]
    warnings: list[str] = []
    applied = 0

    for window in iter_card_windows(cards, window_size):
        if not window_needs_boundary_polish(window):
            continue
        prompt = boundary_prompt(manifest.title, window, max_operations_per_window)
        try:
            plan = await planner(prompt)
        except Exception as error:
            warnings.append(f"Sampling post-processing failed: {error}")
            break
        result = apply_boundary_operations(cards, plan.operations)
        cards = result.cards
        warnings.extend(result.warnings)
        applied += result.applied_operations

    cards = repair_orphan_continuation_cards(cards)
    cards = renumber_cards(cards)
    return BoundaryPolishResult(cards=cards, warnings=warnings, applied_operations=applied)


def apply_boundary_operations(
    cards: list[Card],
    operations: list[BoundaryOperation],
) -> BoundaryPolishResult:
    original_fingerprint = text_fingerprint(cards)
    current = [clone_card(card) for card in cards]
    warnings: list[str] = []
    applied = 0

    for operation in operations:
        before = text_fingerprint(current)
        try:
            updated = apply_boundary_operation(current, operation)
        except ValueError as error:
            warnings.append(f"Rejected sampling operation {operation.op}: {error}")
            continue
        if text_fingerprint(updated) != before:
            warnings.append(f"Rejected sampling operation {operation.op}: text preservation failed.")
            continue
        current = updated
        applied += 1

    if text_fingerprint(current) != original_fingerprint:
        return BoundaryPolishResult(
            cards=cards,
            warnings=[*warnings, "Rejected sampling post-processing: document text changed."],
            applied_operations=0,
        )
    return BoundaryPolishResult(cards=current, warnings=warnings, applied_operations=applied)


def apply_boundary_operation(cards: list[Card], operation: BoundaryOperation) -> list[Card]:
    if operation.op == "merge":
        return apply_merge_operation(cards, operation)
    if operation.op == "extract_heading":
        return apply_extract_heading_operation(cards, operation)
    if operation.op == "set_kind":
        return apply_set_kind_operation(cards, operation)
    raise ValueError(f"unsupported operation: {operation.op}")


def apply_merge_operation(cards: list[Card], operation: BoundaryOperation) -> list[Card]:
    if len(operation.card_ids) < 2:
        raise ValueError("merge requires at least two card_ids")
    indexes = indexes_for_card_ids(cards, operation.card_ids)
    if indexes is None:
        raise ValueError("merge card ids were not found")
    if indexes != list(range(indexes[0], indexes[-1] + 1)):
        raise ValueError("merge card ids must be consecutive")
    selected = [cards[index] for index in indexes]
    if any(not is_text_card(card) for card in selected):
        raise ValueError("merge can only target text cards")
    if len({card.page for card in selected}) != 1:
        raise ValueError("merge can only target cards from the same page")

    first = selected[0]
    merged = Card(
        id=first.id,
        kind=first.kind,
        page=first.page,
        section=first.section,
        text=join_card_texts([card.text for card in selected]),
        source_image_id=first.source_image_id,
        bbox=union_optional_bboxes([card.bbox for card in selected]),
    )
    return [*cards[: indexes[0]], merged, *cards[indexes[-1] + 1 :]]


def apply_extract_heading_operation(cards: list[Card], operation: BoundaryOperation) -> list[Card]:
    if not operation.card_id:
        raise ValueError("extract_heading requires card_id")
    if not operation.exact_text:
        raise ValueError("extract_heading requires exact_text")
    index = index_for_card_id(cards, operation.card_id)
    if index is None:
        raise ValueError("target card was not found")
    card = cards[index]
    if not is_text_card(card):
        raise ValueError("extract_heading can only target text cards")
    heading = normalize_spaces(operation.exact_text)
    text = normalize_spaces(card.text)
    if text.count(heading) != 1:
        raise ValueError("exact_text must appear exactly once in the target card")
    start = text.index(heading)
    end = start + len(heading)
    before = text[:start].strip()
    after = text[end:].strip()
    if not before and not after:
        raise ValueError("target card already contains only the heading")

    replacement: list[Card] = []
    if before:
        replacement.append(
            Card(
                id=f"{card.id}-before",
                kind=card.kind,
                page=card.page,
                section=card.section,
                text=before,
                source_image_id=card.source_image_id,
                bbox=card.bbox,
            )
        )
    replacement.append(
        Card(
            id=f"{card.id}-heading",
            kind="heading",
            page=card.page,
            section=heading,
            text=heading,
            source_image_id=card.source_image_id,
            bbox=card.bbox,
        )
    )
    if after:
        replacement.append(
            Card(
                id=f"{card.id}-after",
                kind="paragraph",
                page=card.page,
                section=heading,
                text=after,
                source_image_id=card.source_image_id,
                bbox=card.bbox,
            )
        )
    return [*cards[:index], *replacement, *cards[index + 1 :]]


def apply_set_kind_operation(cards: list[Card], operation: BoundaryOperation) -> list[Card]:
    if not operation.card_id:
        raise ValueError("set_kind requires card_id")
    if operation.kind not in TEXT_CARD_KINDS:
        raise ValueError("set_kind requires a supported text kind")
    index = index_for_card_id(cards, operation.card_id)
    if index is None:
        raise ValueError("target card was not found")
    card = cards[index]
    if not is_text_card(card):
        raise ValueError("set_kind can only target text cards")
    section = "Front Matter" if operation.kind == "metadata" else card.section
    if operation.kind == "footnote":
        section = "Footnotes"
    updated = Card(
        id=card.id,
        kind=operation.kind,
        page=card.page,
        section=section,
        text=card.text,
        image_id=card.image_id,
        source_image_id=card.source_image_id,
        bbox=card.bbox,
    )
    return [*cards[:index], updated, *cards[index + 1 :]]


def boundary_prompt(
    title: str,
    cards: list[Card],
    max_operations: int,
) -> str:
    payload = [
        {
            "id": card.id,
            "kind": card.kind,
            "page": card.page,
            "section": card.section,
            "text": card.text,
        }
        for card in cards
        if is_text_card(card)
    ]
    return (
        "You are polishing a PDF-to-card reader. Return boundary operations only.\n"
        "Do not rewrite, summarize, delete, invent, or reorder source text.\n"
        "Prefer no operation when uncertain.\n"
        "Allowed operations:\n"
        "- merge: merge consecutive text cards that are one paragraph split badly.\n"
        "- extract_heading: isolate an exact heading substring already present in a card.\n"
        "- set_kind: set kind to paragraph, heading, footnote, or metadata for front matter.\n"
        "Use exact card ids and exact source substrings. Maximum operations: "
        f"{max_operations}.\n\n"
        f"Document title: {title}\n"
        "Cards JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def iter_card_windows(cards: list[Card], window_size: int) -> list[list[Card]]:
    text_indexes = [index for index, card in enumerate(cards) if is_text_card(card)]
    windows: list[list[Card]] = []
    step = max(1, window_size)
    for start in range(0, len(text_indexes), step):
        indexes = text_indexes[start : start + window_size]
        if len(indexes) < 2:
            continue
        windows.append([cards[index] for index in indexes])
    return windows


def window_needs_boundary_polish(cards: list[Card]) -> bool:
    for card in cards:
        text = normalize_spaces(card.text)
        if card.kind == "paragraph" and embedded_section_heading(text):
            return True
        if starts_with_orphan_continuation(text):
            return True
        if card.kind == "paragraph" and looks_like_front_matter_fragment(text):
            return True
    return False


def embedded_section_heading(text: str) -> str | None:
    match = re.search(
        r"\b(?:\d+(?:\.\d+)+\.?|[A-Z])\s+[A-Z][A-Z0-9 ,:/()&-]{6,80}\b",
        normalize_spaces(text),
    )
    if not match:
        return None
    heading = match.group(0).strip()
    if len(heading.split()) > 10:
        return None
    return heading


def starts_with_orphan_continuation(text: str) -> bool:
    cleaned = normalize_spaces(text)
    return bool(cleaned) and (
        cleaned[0] in ",;:)]}"
        or bool(re.match(r"^(?:and|or|but|which|that|because|while|although)\b", cleaned, re.I))
    )


def looks_like_front_matter_fragment(text: str) -> bool:
    cleaned = normalize_spaces(text)
    if len(cleaned.split()) > 32:
        return False
    return bool(
        re.search(r"\b(University|Institute|Laboratory|Lab|Shanghai|Correspondence|@)\b", cleaned)
    )


def join_card_texts(texts: list[str]) -> str:
    result = ""
    for text in texts:
        cleaned = normalize_spaces(text)
        if not cleaned:
            continue
        if not result:
            result = cleaned
        elif cleaned[0] in ",.;:!?)]}%":
            result += cleaned
        else:
            result += " " + cleaned
    return normalize_spaces(result)


def repair_orphan_continuation_cards(cards: list[Card]) -> list[Card]:
    repaired: list[Card] = []
    for card in cards:
        if (
            repaired
            and should_merge_orphan_continuation(repaired[-1], card)
        ):
            first = repaired[-1]
            repaired[-1] = Card(
                id=first.id,
                kind=first.kind,
                page=first.page,
                section=first.section,
                text=join_card_texts([first.text, card.text]),
                source_image_id=first.source_image_id or card.source_image_id,
                bbox=union_optional_bboxes([first.bbox, card.bbox]),
            )
            continue
        repaired.append(card)
    if text_fingerprint(repaired) != text_fingerprint(cards):
        return cards
    return repaired


def should_merge_orphan_continuation(first: Card, second: Card) -> bool:
    if first.kind != "paragraph" or second.kind != "paragraph":
        return False
    if first.image_id or second.image_id:
        return False
    if first.page != second.page:
        return False
    text = normalize_spaces(second.text)
    if not text or text[0] not in ",;:)]}":
        return False
    return len(first.text.split()) + len(second.text.split()) <= 180


def text_fingerprint(cards: list[Card]) -> str:
    text = "".join(card.text for card in cards if is_text_card(card))
    return re.sub(r"\s+", "", text)


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_text_card(card: Card) -> bool:
    return card.kind in TEXT_CARD_KINDS and not card.image_id


def clone_card(card: Card) -> Card:
    return Card(
        id=card.id,
        kind=card.kind,
        page=card.page,
        section=card.section,
        text=card.text,
        image_id=card.image_id,
        source_image_id=card.source_image_id,
        bbox=card.bbox,
    )


def renumber_cards(cards: list[Card]) -> list[Card]:
    return [
        Card(
            id=f"card-{index}",
            kind=card.kind,
            page=card.page,
            section=card.section,
            text=card.text,
            image_id=card.image_id,
            source_image_id=card.source_image_id,
            bbox=card.bbox,
        )
        for index, card in enumerate(cards, start=1)
    ]


def index_for_card_id(cards: list[Card], card_id: str) -> int | None:
    for index, card in enumerate(cards):
        if card.id == card_id:
            return index
    return None


def indexes_for_card_ids(cards: list[Card], card_ids: list[str]) -> list[int] | None:
    indexes: list[int] = []
    for card_id in card_ids:
        index = index_for_card_id(cards, card_id)
        if index is None:
            return None
        indexes.append(index)
    return indexes


def union_optional_bboxes(boxes: list[BBox | None]) -> BBox | None:
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    return (
        min(box[0] for box in present),
        min(box[1] for box in present),
        max(box[2] for box in present),
        max(box[3] for box in present),
    )


def load_standalone_manifest(html_path: Path) -> ConversionManifest:
    html = html_path.read_text(encoding="utf-8")
    match = re.search(r"const payload = (.*?);\nconst assetMap =", html, re.S)
    if match is None:
        raise ValueError(f"Could not find embedded reader payload in {html_path}")
    payload = json.loads(match.group(1))
    return manifest_from_payload(payload)


def manifest_from_payload(payload: dict) -> ConversionManifest:
    return ConversionManifest(
        title=str(payload["title"]),
        source_pdf=Path(payload["source_pdf"]),
        page_count=int(payload["page_count"]),
        processed_pages=int(payload["processed_pages"]),
        cards=[card_from_payload(card) for card in payload.get("cards", [])],
        assets=[asset_from_payload(asset) for asset in payload.get("assets", [])],
        warnings=list(payload.get("warnings", [])),
        theme=str(payload.get("theme", "soft")),
        style_engine=str(payload.get("style_engine", "fixed")),
        style_hints=StyleHints.from_dict(payload.get("style_hints")),
        style=ReaderStyle.from_dict(payload.get("style")),
    )


def card_from_payload(payload: dict) -> Card:
    bbox = payload.get("bbox")
    return Card(
        id=str(payload["id"]),
        kind=str(payload["kind"]),
        page=int(payload["page"]),
        section=str(payload.get("section", "Document")),
        text=str(payload.get("text", "")),
        image_id=payload.get("image_id"),
        source_image_id=payload.get("source_image_id"),
        bbox=tuple(float(value) for value in bbox) if bbox is not None else None,
        items=[dict(item) for item in payload.get("items", []) if isinstance(item, dict)],
    )


def asset_from_payload(payload: dict) -> ImageAsset:
    bbox = payload.get("bbox")
    return ImageAsset(
        id=str(payload["id"]),
        kind=str(payload["kind"]),
        page=int(payload["page"]),
        alt=str(payload.get("alt", "")),
        caption=str(payload.get("caption", "")),
        data_uri=str(payload.get("data_uri", "")),
        width=int(payload.get("width", 0)),
        height=int(payload.get("height", 0)),
        bbox=tuple(float(value) for value in bbox) if bbox is not None else None,
    )


def rewrite_standalone_reader(
    manifest: ConversionManifest,
    html_path: Path,
    manifest_path: Path,
) -> None:
    html_path.write_text(render_html(manifest), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(manifest.to_dict(include_data=False), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
