from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_card_mcp.annotations import Annotation, empty_annotation_bundle, write_annotation_bundle
from pdf_card_mcp.html_renderer import render_html
from pdf_card_mcp.models import Card, ConversionManifest
from pdf_card_mcp.postprocess import load_standalone_manifest
from pdf_card_mcp.publish import publish_reader_bundle, validate_reader_annotations


def manifest_with_contents() -> ConversionManifest:
    return ConversionManifest(
        title="Publish Me",
        source_pdf=Path("/Users/example/private/paper.pdf"),
        page_count=1,
        processed_pages=1,
        cards=[
            Card(
                id="card-1",
                kind="contents",
                page=1,
                section="Contents",
                items=[
                    {
                        "label": "1 Introduction",
                        "page_label": "1",
                        "href": "#page-1",
                        "level": 0,
                    }
                ],
            ),
            Card(
                id="card-2",
                kind="paragraph",
                page=1,
                section="Document",
                text="Important source text.",
            ),
        ],
        assets=[],
    )


def write_reader(tmp_path: Path, manifest: ConversionManifest) -> Path:
    path = tmp_path / "reader.html"
    path.write_text(render_html(manifest), encoding="utf-8")
    return path


def test_publish_filters_private_annotations_and_redacts_source_path(tmp_path: Path) -> None:
    manifest = manifest_with_contents()
    reader_path = write_reader(tmp_path, manifest)
    bundle = empty_annotation_bundle(manifest).model_copy(
        update={
            "annotations": [
                Annotation(
                    id="ann-public",
                    kind="highlight",
                    card_id="card-2",
                    page=1,
                    text_quote="Important",
                    visibility="public",
                ),
                Annotation(
                    id="ann-private",
                    kind="note",
                    card_id="card-2",
                    page=1,
                    text_quote="source",
                    note="<script>alert(1)</script>",
                    visibility="private",
                ),
            ]
        }
    )
    annotations_path = tmp_path / "notes.json"
    write_annotation_bundle(bundle, annotations_path)

    result = publish_reader_bundle(
        reader_html_path=reader_path,
        annotations_path=annotations_path,
        output_path=tmp_path / "published.html",
    )
    html = result.output_path.read_text(encoding="utf-8")

    assert result.annotation_count == 1
    assert "ann-public" in html
    assert "ann-private" not in html
    assert "/Users/example/private/paper.pdf" not in html
    assert "redacted.pdf" in html


def test_publish_directory_writes_static_bundle_files(tmp_path: Path) -> None:
    manifest = manifest_with_contents()
    reader_path = write_reader(tmp_path, manifest)

    result = publish_reader_bundle(reader_path, tmp_path / "site")

    assert result.output_path == tmp_path / "site" / "index.html"
    assert result.manifest_path == tmp_path / "site" / "reader.manifest.json"
    assert result.annotations_path == tmp_path / "site" / "reader.annotations.json"
    assert result.bundle_path == tmp_path / "site" / "bundle.json"
    assert json.loads(result.bundle_path.read_text(encoding="utf-8"))["annotation_count"] == 0


def test_validate_reader_annotations_reports_rejected_anchor(tmp_path: Path) -> None:
    manifest = manifest_with_contents()
    reader_path = write_reader(tmp_path, manifest)
    bundle = empty_annotation_bundle(manifest).model_copy(
        update={
            "annotations": [
                Annotation(
                    id="ann-bad",
                    kind="highlight",
                    card_id="missing",
                    page=1,
                    text_quote="not in document",
                    visibility="public",
                )
            ]
        }
    )
    annotations_path = tmp_path / "notes.json"
    write_annotation_bundle(bundle, annotations_path)

    payload = validate_reader_annotations(reader_path, annotations_path)

    assert payload["valid"] is False
    assert payload["rejected_count"] == 1


def test_publish_rejects_unanchored_annotations(tmp_path: Path) -> None:
    manifest = manifest_with_contents()
    reader_path = write_reader(tmp_path, manifest)
    bundle = empty_annotation_bundle(manifest).model_copy(
        update={
            "annotations": [
                Annotation(
                    id="ann-bad",
                    kind="highlight",
                    card_id="missing",
                    page=1,
                    text_quote="not in document",
                    visibility="public",
                )
            ]
        }
    )
    annotations_path = tmp_path / "notes.json"
    write_annotation_bundle(bundle, annotations_path)

    with pytest.raises(ValueError, match="could not be anchored"):
        publish_reader_bundle(reader_path, tmp_path / "published.html", annotations_path=annotations_path)


def test_loading_standalone_manifest_preserves_contents_items(tmp_path: Path) -> None:
    manifest = manifest_with_contents()
    reader_path = write_reader(tmp_path, manifest)

    loaded = load_standalone_manifest(reader_path)

    assert loaded.cards[0].items == manifest.cards[0].items
