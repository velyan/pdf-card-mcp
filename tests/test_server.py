from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

from pdf_card_mcp import server


def test_mcp_tool_signature_has_expected_inputs() -> None:
    signature = inspect.signature(server.convert_pdf_to_card_html)
    assert "pdf_path" in signature.parameters
    assert "output_path" in signature.parameters
    assert "standalone" in signature.parameters
    assert "ocr" in signature.parameters
    assert "max_pages" in signature.parameters
    assert "style_engine" in signature.parameters
    assert "table_engine" in signature.parameters
    assert "text_engine" in signature.parameters
    assert "postprocess_engine" in signature.parameters
    assert "model_cache_dir" in signature.parameters
    assert "offline" in signature.parameters

    publish_signature = inspect.signature(server.publish_reader_bundle)
    assert "reader_html_path" in publish_signature.parameters
    assert "annotations_path" in publish_signature.parameters
    assert "output_path" in publish_signature.parameters
    assert "include_private" in publish_signature.parameters
    assert "redact_source_path" in publish_signature.parameters
    assert "read_only" in publish_signature.parameters

    validate_signature = inspect.signature(server.validate_reader_annotations)
    assert "reader_html_path" in validate_signature.parameters
    assert "annotations_path" in validate_signature.parameters
    assert "include_private" in validate_signature.parameters


def test_mcp_tool_schema_hides_context_and_constrains_postprocess_engine() -> None:
    async def list_tool_parameters() -> dict:
        tools = await server.mcp.list_tools()
        tool = next(tool for tool in tools if tool.name == "convert_pdf_to_card_html")
        publish_tool = next(tool for tool in tools if tool.name == "publish_reader_bundle")
        validate_tool = next(tool for tool in tools if tool.name == "validate_reader_annotations")
        return {
            "convert": tool.parameters,
            "publish": publish_tool.parameters,
            "validate": validate_tool.parameters,
        }

    schemas = asyncio.run(list_tool_parameters())
    parameters = schemas["convert"]

    assert "ctx" not in parameters["properties"]
    assert parameters["properties"]["postprocess_engine"]["enum"] == ["none", "sampling"]
    assert parameters["properties"]["style_engine"]["enum"] == ["fixed", "pdf", "sampling"]
    assert "reader_html_path" in schemas["publish"]["properties"]
    assert "output_path" in schemas["publish"]["properties"]
    assert "include_private" in schemas["publish"]["properties"]
    assert "reader_html_path" in schemas["validate"]["properties"]
    assert "annotations_path" in schemas["validate"]["properties"]


def test_style_sampling_without_context_returns_deterministic_payload(monkeypatch, tmp_path: Path) -> None:
    html_path = tmp_path / "reader.html"
    manifest_path = tmp_path / "reader.manifest.json"

    class Result:
        def to_dict(self) -> dict:
            return {
                "html_path": str(html_path),
                "manifest_path": str(manifest_path),
                "page_count": 1,
                "card_count": 1,
                "table_count": 0,
                "figure_count": 0,
                "formula_count": 0,
                "warnings": ["deterministic style retained"],
                "style_engine": "pdf",
            }

    def fake_convert_pdf(**_kwargs):
        return Result()

    monkeypatch.setattr(server, "convert_pdf", fake_convert_pdf)

    payload = asyncio.run(
        server.convert_pdf_to_card_html(
            pdf_path="sample.pdf",
            output_path=str(html_path),
            style_engine="sampling",
            ctx=None,
        )
    )

    assert payload["style_engine"] == "pdf"
    assert payload["warnings"][-1].startswith("style_engine='sampling' requested")
