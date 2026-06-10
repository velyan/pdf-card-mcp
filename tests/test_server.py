from __future__ import annotations

import asyncio
import inspect

from pdf_card_mcp import server


def test_mcp_tool_signature_has_expected_inputs() -> None:
    signature = inspect.signature(server.convert_pdf_to_card_html)
    assert "pdf_path" in signature.parameters
    assert "output_path" in signature.parameters
    assert "standalone" in signature.parameters
    assert "ocr" in signature.parameters
    assert "max_pages" in signature.parameters
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
