from __future__ import annotations

import asyncio
from pathlib import Path

from pdf_card_mcp.models import Card, ConversionManifest
from pdf_card_mcp.postprocess import (
    BoundaryOperation,
    BoundaryPlan,
    apply_boundary_operations,
    polish_cards_with_sampling,
)


def text_card(
    card_id: str,
    text: str,
    *,
    kind: str = "paragraph",
    section: str = "Document",
) -> Card:
    return Card(
        id=card_id,
        kind=kind,
        page=1,
        section=section,
        text=text,
        source_image_id="source-page-1",
        bbox=(72, 100, 520, 140),
    )


def test_sampling_operations_extract_heading_and_repair_continuation() -> None:
    manifest = ConversionManifest(
        title="LoRA",
        source_pdf=Path("LORA.pdf"),
        page_count=1,
        processed_pages=1,
        cards=[
            text_card(
                "card-1",
                "guarantees that we do not introduce latency. 4.2 APPLYING LORA TO "
                "TRANSFORMER In principle, we can apply LoRA to any subset of weights",
            ),
            text_card(
                "card-2",
                ", even though the output dimension is usually sliced into attention heads.",
            ),
        ],
        assets=[],
    )

    async def planner(_prompt: str) -> BoundaryPlan:
        return BoundaryPlan(
            operations=[
                BoundaryOperation(
                    op="extract_heading",
                    card_id="card-1",
                    exact_text="4.2 APPLYING LORA TO TRANSFORMER",
                )
            ]
        )

    result = asyncio.run(polish_cards_with_sampling(manifest, planner))

    assert [card.kind for card in result.cards] == ["paragraph", "heading", "paragraph"]
    assert result.cards[1].text == "4.2 APPLYING LORA TO TRANSFORMER"
    assert result.cards[2].text == (
        "In principle, we can apply LoRA to any subset of weights, even though "
        "the output dimension is usually sliced into attention heads."
    )
    assert "".join(card.text for card in result.cards).replace(" ", "") == (
        "".join(card.text for card in manifest.cards).replace(" ", "")
    )


def test_sampling_operations_can_classify_front_matter_as_metadata() -> None:
    cards = [
        text_card(
            "card-1",
            "Shanghai, China 2Department of Computer Science and Technology, Zhejiang University",
        )
    ]

    result = apply_boundary_operations(
        cards,
        [BoundaryOperation(op="set_kind", card_id="card-1", kind="metadata")],
    )

    assert result.applied_operations == 1
    assert result.cards[0].kind == "metadata"
    assert result.cards[0].section == "Front Matter"
    assert result.cards[0].text == cards[0].text


def test_sampling_operations_reject_text_changes() -> None:
    cards = [text_card("card-1", "The exact source text.")]

    result = apply_boundary_operations(
        cards,
        [
            BoundaryOperation(
                op="extract_heading",
                card_id="card-1",
                exact_text="not in source",
            )
        ],
    )

    assert result.applied_operations == 0
    assert result.cards == cards
    assert result.warnings
