from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from .converter import convert_pdf_to_card_html as convert_pdf
from .models import ConversionManifest
from .postprocess import (
    BoundaryPlan,
    load_standalone_manifest,
    polish_cards_with_sampling,
    rewrite_standalone_reader,
)

try:
    from fastmcp import Context, FastMCP
except Exception:  # pragma: no cover - compatibility fallback
    from mcp.server.fastmcp import Context, FastMCP  # type: ignore


mcp = FastMCP("PDF Card Reader")


@mcp.tool()
async def convert_pdf_to_card_html(
    pdf_path: str,
    output_path: str | None = None,
    title: str | None = None,
    standalone: bool = True,
    ocr: bool = False,
    max_pages: int | None = None,
    theme: str = "soft",
    table_engine: str = "auto",
    text_engine: str = "char_geometry",
    postprocess_engine: Literal["none", "sampling"] = "none",
    model_cache_dir: str | None = None,
    offline: bool = False,
    ctx: Context | None = None,
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
        table_engine: "auto", "pdfplumber", or "gmft". Auto uses gmft when installed.
        text_engine: "char_geometry" or "pdfplumber_words". Defaults to geometry-based spacing.
        postprocess_engine: "none" or "sampling". Sampling asks the host LLM for boundary-only
            card polish operations, validates exact text preservation, and rewrites the reader.
        model_cache_dir: Optional cache directory for local ML table model weights.
        offline: Use only already-cached optional ML models.
    """
    if postprocess_engine not in {"none", "sampling"}:
        raise ValueError("postprocess_engine must be one of: none, sampling")

    result = convert_pdf(
        pdf_path=Path(pdf_path),
        output_path=Path(output_path) if output_path else None,
        title=title,
        standalone=standalone,
        ocr=ocr,
        max_pages=max_pages,
        theme=theme,
        table_engine=table_engine,
        text_engine=text_engine,
        model_cache_dir=Path(model_cache_dir) if model_cache_dir else None,
        offline=offline,
    )
    payload = result.to_dict()
    if postprocess_engine == "sampling":
        if ctx is None:
            payload["warnings"] = [
                *payload["warnings"],
                "postprocess_engine='sampling' requested, but no MCP context was available.",
            ]
            return payload
        payload = await apply_sampling_postprocess(payload, ctx)
    return payload


async def apply_sampling_postprocess(payload: dict[str, Any], ctx: Context) -> dict[str, Any]:
    html_path = Path(payload["html_path"])
    manifest_path = Path(payload["manifest_path"])
    try:
        manifest = load_standalone_manifest(html_path)
        result = await polish_cards_with_sampling(
            manifest,
            lambda prompt: request_boundary_plan(ctx, prompt),
        )
        manifest = ConversionManifest(
            title=manifest.title,
            source_pdf=manifest.source_pdf,
            page_count=manifest.page_count,
            processed_pages=manifest.processed_pages,
            cards=result.cards,
            assets=manifest.assets,
            warnings=[
                *manifest.warnings,
                *result.warnings,
                f"Sampling post-processing applied {result.applied_operations} boundary operations.",
            ],
            theme=manifest.theme,
        )
        rewrite_standalone_reader(manifest, html_path, manifest_path)
    except Exception as error:
        payload["warnings"] = [
            *payload["warnings"],
            f"postprocess_engine='sampling' requested, but sampling post-processing failed: {error}",
        ]
        return payload
    return {
        **payload,
        "card_count": manifest.card_count,
        "table_count": manifest.table_count,
        "figure_count": manifest.figure_count,
        "formula_count": manifest.formula_count,
        "warnings": manifest.warnings,
    }


async def request_boundary_plan(ctx: Context, prompt: str) -> BoundaryPlan:
    sample = await ctx.sample(
        prompt,
        system_prompt=(
            "You are a careful document-layout editor. You only return boundary operations "
            "that preserve the source text exactly. Never rewrite, summarize, translate, "
            "delete, invent, or reorder text."
        ),
        temperature=0,
        max_tokens=1400,
        result_type=BoundaryPlan,
    )
    return sample.result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
