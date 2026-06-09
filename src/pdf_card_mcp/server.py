from __future__ import annotations

from pathlib import Path
from typing import Any

from .converter import convert_pdf_to_card_html as convert_pdf

try:
    from fastmcp import FastMCP
except Exception:  # pragma: no cover - compatibility fallback
    from mcp.server.fastmcp import FastMCP  # type: ignore


mcp = FastMCP("PDF Card Reader")


@mcp.tool()
def convert_pdf_to_card_html(
    pdf_path: str,
    output_path: str | None = None,
    title: str | None = None,
    standalone: bool = True,
    ocr: bool = False,
    max_pages: int | None = None,
    theme: str = "soft",
) -> dict[str, Any]:
    """Convert a local PDF into a standalone card-based HTML reader.

    Args:
        pdf_path: Absolute or relative path to the input PDF.
        output_path: Optional path for the generated HTML file.
        title: Optional reader title override.
        standalone: Keep true to embed images, CSS, and JavaScript in one HTML file.
        ocr: Try optional OCR fallback for image-only PDFs.
        max_pages: Optional limit for very large PDFs.
        theme: Reader theme name. The default soft theme is calm and minimal.
    """
    result = convert_pdf(
        pdf_path=Path(pdf_path),
        output_path=Path(output_path) if output_path else None,
        title=title,
        standalone=standalone,
        ocr=ocr,
        max_pages=max_pages,
        theme=theme,
    )
    return result.to_dict()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
