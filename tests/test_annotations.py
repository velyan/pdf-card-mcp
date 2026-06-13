from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pdf_card_mcp.annotations import (
    Annotation,
    AnnotationBundle,
    document_id_for_manifest,
    empty_annotation_bundle,
    manifest_hash,
    validate_annotation_bundle,
)
from pdf_card_mcp.models import Card, ConversionManifest


def sample_manifest() -> ConversionManifest:
    return ConversionManifest(
        title="Notes",
        source_pdf=Path("/tmp/source.pdf"),
        page_count=1,
        processed_pages=1,
        cards=[
            Card(
                id="card-1",
                kind="paragraph",
                page=1,
                section="Document",
                text="Alpha beta gamma.",
                bbox=(10, 20, 200, 50),
            )
        ],
        assets=[],
    )


def test_annotation_bundle_validates_and_resolves_quote_anchor() -> None:
    manifest = sample_manifest()
    bundle = empty_annotation_bundle(manifest).model_copy(
        update={
            "annotations": [
                Annotation(
                    id="ann-1",
                    kind="highlight",
                    card_id="missing",
                    page=1,
                    text_quote="beta",
                    color="yellow",
                    visibility="public",
                )
            ]
        }
    )

    result = validate_annotation_bundle(bundle, manifest)

    assert result.accepted_count == 1
    assert result.rejected_count == 0
    assert result.bundle.annotations[0].card_id == "card-1"
    assert result.bundle.annotations[0].text_start == 6
    assert result.bundle.annotations[0].text_end == 10


def test_annotation_bundle_filters_private_by_default() -> None:
    manifest = sample_manifest()
    bundle = empty_annotation_bundle(manifest).model_copy(
        update={
            "annotations": [
                Annotation(
                    id="ann-private",
                    kind="note",
                    card_id="card-1",
                    page=1,
                    text_quote="Alpha",
                    note="Private note",
                    visibility="private",
                ),
                Annotation(
                    id="ann-public",
                    kind="highlight",
                    card_id="card-1",
                    page=1,
                    text_quote="gamma",
                    visibility="public",
                ),
            ]
        }
    )

    result = validate_annotation_bundle(bundle, manifest, include_private=False)

    assert [annotation.id for annotation in result.bundle.annotations] == ["ann-public"]


def test_annotation_bundle_recovers_collapsed_whitespace_quote() -> None:
    manifest = sample_manifest()
    manifest.cards[0].text = "Alpha   beta\ngamma."
    bundle = empty_annotation_bundle(manifest).model_copy(
        update={
            "annotations": [
                Annotation(
                    id="ann-space",
                    kind="highlight",
                    card_id="card-1",
                    page=1,
                    text_quote="Alpha beta gamma.",
                    visibility="public",
                )
            ]
        }
    )

    result = validate_annotation_bundle(bundle, manifest)

    assert result.accepted_count == 1
    assert result.bundle.annotations[0].text_quote == "Alpha   beta\ngamma."


def test_annotation_bundle_rejects_unknown_schema_version() -> None:
    with pytest.raises(ValidationError):
        AnnotationBundle(
            schema_version="old",
            document_id="doc",
            manifest_hash="hash",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
            annotations=[],
        )


def test_manifest_identity_ignores_absolute_source_path() -> None:
    first = sample_manifest()
    second = sample_manifest()
    second.source_pdf = Path("/different/source.pdf")

    assert document_id_for_manifest(first) == document_id_for_manifest(second)
    assert manifest_hash(first) == manifest_hash(second)
