from __future__ import annotations

import inspect

from pdf_card_mcp import server


def test_mcp_tool_signature_has_expected_inputs() -> None:
    signature = inspect.signature(server.convert_pdf_to_card_html)
    assert "pdf_path" in signature.parameters
    assert "output_path" in signature.parameters
    assert "standalone" in signature.parameters
    assert "ocr" in signature.parameters
    assert "max_pages" in signature.parameters
