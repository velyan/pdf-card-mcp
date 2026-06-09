from __future__ import annotations

from pathlib import Path

from pdf_card_mcp.html_renderer import render_html
from pdf_card_mcp.models import Card, ConversionManifest, ImageAsset


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
