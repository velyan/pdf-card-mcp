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


def test_mcp_tool_schema_hides_context_and_constrains_postprocess_engine() -> None:
    async def list_tool_parameters() -> dict:
        tools = await server.mcp.list_tools()
        tool = next(tool for tool in tools if tool.name == "convert_pdf_to_card_html")
        return tool.parameters

    parameters = asyncio.run(list_tool_parameters())

    assert "ctx" not in parameters["properties"]
    assert parameters["properties"]["postprocess_engine"]["enum"] == ["none", "sampling"]
    assert parameters["properties"]["style_engine"]["enum"] == ["fixed", "pdf", "sampling"]


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
