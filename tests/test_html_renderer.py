from __future__ import annotations

from pathlib import Path

from pdf_card_mcp.annotations import Annotation, empty_annotation_bundle
from pdf_card_mcp.html_renderer import render_html
from pdf_card_mcp.models import Card, ConversionManifest, ImageAsset, ReaderStyle, soft_reader_style


def test_renderer_outputs_standalone_data_uri() -> None:
    manifest = ConversionManifest(
        title="Soft Reader",
        source_pdf=Path("paper.pdf"),
        page_count=1,
        processed_pages=1,
        cards=[
            Card(
                id="card-1",
                kind="table",
                page=1,
                section="Document",
                text="Table 1. Results",
                image_id="table-1-1",
                source_image_id="source-page-1",
            )
        ],
        assets=[
            ImageAsset(
                id="source-page-1",
                kind="source_page",
                page=1,
                alt="Source page 1",
                caption="",
                data_uri="data:image/png;base64,AAA=",
                width=100,
                height=100,
            ),
            ImageAsset(
                id="table-1-1",
                kind="table",
                page=1,
                alt="Table 1. Results",
                caption="Table 1. Results",
                data_uri="data:image/png;base64,BBB=",
                width=80,
                height=40,
            ),
        ],
    )

    html = render_html(manifest)

    assert "data:image/png;base64,BBB=" in html
    assert "PDF" not in html[:15]
    assert "warm paper" not in html
    assert "Search the document" in html
    assert ">Text<" not in html
    assert 'id="fontSize"' in html
    assert "--reader-font-size" in html
    assert "pdf-card-reader-font-size" in html
    assert "totalFormulas" in html
    assert "width: fit-content" in html


def test_renderer_uses_manifest_style_variables() -> None:
    style = ReaderStyle(
        **{
            **soft_reader_style().to_dict(),
            "bg": "#eef5fb",
            "paper": "#ffffff",
            "paper_soft": "#eef3f8",
            "accent": "#1f5f8f",
            "accent_soft": "#e2eef6",
        }
    )
    manifest = ConversionManifest(
        title="Styled Reader",
        source_pdf=Path("paper.pdf"),
        page_count=1,
        processed_pages=1,
        cards=[Card(id="card-1", kind="paragraph", page=1, section="Document", text="Body")],
        assets=[],
        style_engine="pdf",
        style=style,
    )

    html = render_html(manifest)

    assert "--accent: #1f5f8f;" in html
    assert "--bg: #eef5fb;" in html
    assert '"style_engine": "pdf"' in html
    assert '"accent": "#1f5f8f"' in html


def test_renderer_falls_back_for_unsafe_style() -> None:
    unsafe = ReaderStyle(
        **{
            **soft_reader_style().to_dict(),
            "paper": "#ffffff",
            "ink": "#ffffff",
            "accent": "not-a-color",
        }
    )
    manifest = ConversionManifest(
        title="Unsafe Styled Reader",
        source_pdf=Path("paper.pdf"),
        page_count=1,
        processed_pages=1,
        cards=[Card(id="card-1", kind="paragraph", page=1, section="Document", text="Body")],
        assets=[],
        style=unsafe,
    )

    html = render_html(manifest)

    assert "--accent: #6f836e;" in html
    assert "--ink: #282522;" in html


def test_renderer_embeds_annotation_bundle_in_read_only_mode() -> None:
    manifest = ConversionManifest(
        title="Annotated Reader",
        source_pdf=Path("paper.pdf"),
        page_count=1,
        processed_pages=1,
        cards=[
            Card(
                id="card-1",
                kind="paragraph",
                page=1,
                section="Document",
                text="Source text with a note.",
            )
        ],
        assets=[],
    )
    bundle = empty_annotation_bundle(manifest).model_copy(
        update={
            "annotations": [
                Annotation(
                    id="ann-1",
                    kind="note",
                    card_id="card-1",
                    page=1,
                    text_quote="Source",
                    note="<b>escaped</b>",
                    visibility="public",
                )
            ]
        }
    )

    html = render_html(manifest, annotation_bundle=bundle, annotation_read_only=True)

    assert '"read_only": true' in html
    assert '"ann-1"' in html
    assert "annotation-mark" in html
    assert "pdf-card-reader:" in html
    assert "data-annotatable" in html
