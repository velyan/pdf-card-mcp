# PDF Card MCP

<!-- mcp-name: io.github.velyan/pdf-card-mcp -->

PDF Card MCP is a local-first MCP tool that converts dense PDFs into minimal,
card-based HTML readers inspired by the source document. It preserves source text, renders
source pages, crops detected tables, figures, and display formulas as images, derives a
safe reader style from the original PDF palette, and writes a standalone HTML file that can
be moved across devices without losing assets.

The default reader is designed for comfortable reading: large type, small cards, search,
section navigation, next/previous controls, keyboard navigation, a font-size slider, and
source-page previews.

## Status

This is an early open-source implementation. It is useful for text-layer PDFs now, with
best-effort table detection via `pdfplumber`, permissive raster rendering via `pypdfium2`,
and optional richer local table detection via `gmft`. Scanned PDFs need optional OCR support.

## Install For Development

```bash
cd /Users/vel/Projects/pdf-card-mcp
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

`uv` is recommended for MCPB packaging:

```bash
uv sync
uv run pdf-card-mcp path/to/document.pdf --output out/document.html
```

Install the optional local ML table detector when you want stronger table crops:

```bash
uv sync --extra table-ml
uv run --extra table-ml pdf-card-mcp path/to/document.pdf --table-engine gmft
```

## CLI Usage

```bash
pdf-card-mcp path/to/document.pdf --output examples/out/document.html
```

The command writes:

- `document.html`: standalone reader with embedded CSS, JavaScript, table crops, figure crops,
  formula crops, and source-page images.
- `document.manifest.json`: structured metadata without embedded image payloads.

## MCP Tool

The server exposes one primary tool:

```text
convert_pdf_to_card_html
```

Inputs:

- `pdf_path`: local PDF path.
- `output_path`: optional HTML output path.
- `title`: optional title override.
- `standalone`: defaults to `true`; asset-folder output is reserved for a later release.
- `ocr`: optional OCR fallback if `pytesseract` is installed.
- `max_pages`: optional processing limit.
- `theme`: defaults to `soft`.
- `style_engine`: `fixed`, `pdf`, or `sampling`; defaults to `pdf`. `fixed` preserves the
  original soft palette, `pdf` derives bounded colors and typography hints locally from the
  source PDF, and `sampling` asks the host LLM to choose validated style tokens from those
  local hints.
- `table_engine`: `auto`, `pdfplumber`, or `gmft`; `auto` uses `gmft` when installed.
- `text_engine`: `char_geometry` or `pdfplumber_words`; defaults to `char_geometry` so
  missing spaces are repaired from PDF character positions instead of trusting fused words.
- `postprocess_engine`: `none` or `sampling`; defaults to `none`. When set to `sampling`,
  the MCP server asks the host LLM for boundary-only card polish operations, validates exact
  source-text preservation, and rewrites the generated reader. If the MCP client does not
  support sampling, deterministic output is returned with a warning.
- `model_cache_dir`: optional cache directory for local ML table model weights.
- `offline`: use only already-cached optional ML models.

Sampling post-processing is intentionally narrow. For card boundaries, the host LLM may
suggest merges, heading extraction, or front-matter/footnote classification, but Python
validation rejects any operation that rewrites, deletes, invents, or reorders source text.
For `style_engine=sampling`, the host LLM may only choose bounded style tokens and palette
candidate IDs; it cannot return raw CSS, JavaScript, or arbitrary colors. If sampling is
unavailable, the reader keeps deterministic PDF-derived styling and returns a warning.

Run the server locally:

```bash
python -m pdf_card_mcp.server
```

## MCPB Packaging

This repo is arranged so the root can be packed directly:

```bash
python scripts/build_mcpb.py --variant all
```

The slim bundle writes `dist/pdf-card-mcp-lite.mcpb`. The full-quality UV bundle writes
`dist/pdf-card-mcp.mcpb` and installs the `table-ml` extra. Neither bundle vendors ML model
weights; `gmft` downloads and caches them locally on first use unless `offline=true` is set
with a prewarmed cache.

The MCPB manifests use `server.type = "uv"`, so hosts that support UV runtime can install
dependencies from `pyproject.toml` instead of relying on a user-managed Python setup.

## Privacy

PDF processing is local. The tool does not upload document contents or call external APIs.
Optional OCR runs locally when the user has installed OCR dependencies.

## How It Works

See [`docs/how-it-works.html`](docs/how-it-works.html) for a self-contained visual explainer
of the conversion pipeline, including page rendering, table/figure crops, overlap suppression,
text-card merging, and standalone HTML output.

## How Tables Are Handled

All detected tables are rendered as image cards. The converter uses `pdfplumber` to find table
regions and can optionally use `gmft`/Table Transformer for stronger local detection. It then
uses `pypdfium2` to rasterize only the source table region into PNG. Captions are preserved as
reader text and alt text, but the table itself remains an image so layout and numeric alignment
survive conversion.

If a document mentions tables but no reliable table regions are found, the manifest includes a
warning so callers can decide whether to inspect the source pages.

## How Formulas Are Handled

Display formulas are treated as image cards when the PDF exposes them as centered, formula-like
text blocks. The extracted formula string is retained for alt/search metadata, but the reader
shows the source crop so subscripts, superscripts, arrows, and math spacing remain faithful.

## License

MIT
