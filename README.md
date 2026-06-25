# PDF Card MCP

<!-- mcp-name: io.github.velyan/pdf-card-mcp -->

[![CI](https://github.com/velyan/pdf-card-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/velyan/pdf-card-mcp/actions/workflows/ci.yml)
[![Source Install](https://img.shields.io/badge/package-source%20install-blue.svg)](#install)
[![Python 3.11-3.13](https://img.shields.io/badge/python-3.11--3.13-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![MCP Registry](https://img.shields.io/badge/MCP-registry-blue)](https://registry.modelcontextprotocol.io)

PDF Card MCP is a local-first MCP server and CLI for turning dense local PDFs into
portable, source-linked HTML readers. An MCP host can ask it to convert a PDF path, validate
notes/highlights, or publish a static annotated reader bundle. The converter preserves source
text, renders source pages for verification, crops detected tables, figures, and display
formulas as images, derives safe reader styling from the original PDF palette, and writes a
standalone HTML file that can be moved across devices without losing assets.

Default conversion runs locally and does not require a hosted service. Optional MCP sampling
is deliberately bounded: the host model may choose validated style tokens or suggest
card-boundary polish operations, but raw CSS and source-text rewrites are rejected.

The default reader is designed for comfortable reading: large type, small cards, search,
section navigation, next/previous controls, keyboard navigation, a font-size slider, and
source-page previews.

PDF Card MCP is meant for PDFs you actually need to read, cite, or inspect. It turns long
documents into smaller source-linked cards, keeps tables/figures/formulas as faithful image
crops, and lets you export your own notes and highlights as Markdown.

## Quick Install (one-click)

PDF Card MCP is a Python server, so it needs a runtime. The one thing to install first is
[`uv`](https://docs.astral.sh/uv/) — it manages Python for you, so you do not have to. This is
the only prerequisite for every install path below:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then add the server with one click. The buttons run the published
[`pdf-card-mcp`](https://pypi.org/project/pdf-card-mcp/) package through `uv`:

[![Add to Cursor](https://img.shields.io/badge/Add_to_Cursor-black?style=for-the-badge&logo=cursor&logoColor=white)](cursor://anysphere.cursor-deeplink/mcp/install?name=pdf-card&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJwZGYtY2FyZC1tY3AiLCJwZGYtY2FyZC1tY3Atc2VydmVyIl19)
[![Add to VS Code](https://img.shields.io/badge/Add_to_VS_Code-007ACC?style=for-the-badge&logo=visual-studio-code&logoColor=white)](vscode:mcp/install?%7B%22name%22%3A%22pdf-card%22%2C%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22pdf-card-mcp%22%2C%22pdf-card-mcp-server%22%5D%7D)

**Claude Code** (terminal):

```bash
claude mcp add pdf-card -- uvx --from pdf-card-mcp pdf-card-mcp-server
```

**Claude Desktop** (no terminal, no prerequisites): download `pdf-card-mcp-desktop.mcpb` from the
[latest release](https://github.com/velyan/pdf-card-mcp/releases/latest) and double-click it to
install as an extension. This bundle declares the `uv` runtime, so Claude Desktop installs Python
and dependencies for you — you do not need the `uv` step above for this path.

After installing, restart (or reload MCP servers in) your client so it picks up the new server.

## Real Screenshots

These screenshots are from a generated reader for *Agents in Software Engineering* and the
same source PDF opened side by side for comparison.

| Generated reader | Original PDF |
| --- | --- |
| <img src="https://raw.githubusercontent.com/velyan/pdf-card-mcp/main/docs/assets/reader-annotations-real.png" alt="Generated PDF Card MCP reader showing annotations, highlighted text, typed notes, source buttons, and section navigation" width="100%"> | <img src="https://raw.githubusercontent.com/velyan/pdf-card-mcp/main/docs/assets/source-pdf-page-1-real.png" alt="Original PDF page 1 in Preview for source comparison" width="100%"> |
| <img src="https://raw.githubusercontent.com/velyan/pdf-card-mcp/main/docs/assets/reader-figure-real.png" alt="Generated PDF Card MCP reader showing a preserved figure card and document navigation" width="100%"> | <img src="https://raw.githubusercontent.com/velyan/pdf-card-mcp/main/docs/assets/source-pdf-page-4-real.png" alt="Original PDF page in Preview showing the same figure and surrounding paper text" width="100%"> |

## Quick Examples

Convert a local PDF into one portable HTML reader:

```bash
pdf-card-mcp ./paper.pdf --output ./out/paper-reader.html
```

Use the explicit subcommand form with PDF-derived styling:

```bash
pdf-card-mcp convert ./paper.pdf \
  --output ./out/paper-reader.html \
  --style-engine pdf
```

Run the MCP server so a compatible host can generate readers from local PDF paths:

```bash
python -m pdf_card_mcp.server
```

Publish a read-only static reader with selected public annotations:

```bash
pdf-card-mcp publish ./out/paper-reader.html \
  --annotations ./paper.annotations.json \
  --output ./published/paper-reader.html
```

## Output At A Glance

| Output | What it contains |
| --- | --- |
| `paper-reader.html` | Standalone reader with embedded CSS, JavaScript, page images, and detected crops. |
| `paper.manifest.json` | Structured metadata for cards, pages, warnings, and source anchors. |
| Markdown export | User-authored notes and highlights from the reader UI. |
| Published bundle | Read-only static HTML or a directory bundle for sharing public annotations. |

## Status

This is an early open-source implementation. It is useful for text-layer PDFs now, with
best-effort table detection via `pdfplumber`, permissive raster rendering via `pypdfium2`,
and optional richer local table detection via `gmft`. Scanned PDFs need optional OCR support.

## Install

Most people should use the [one-click install](#quick-install-one-click) above. To install the
package directly instead, from PyPI:

```bash
python -m pip install pdf-card-mcp
```

Or install the latest unreleased changes directly from the repository:

```bash
python -m pip install "pdf-card-mcp @ git+https://github.com/velyan/pdf-card-mcp.git"
```

For local development:

```bash
git clone https://github.com/velyan/pdf-card-mcp.git
cd pdf-card-mcp
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
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

## Use In An MCP Client

Add it to Claude Code or another CLI-compatible MCP client with `uvx` (requires
[`uv`](https://docs.astral.sh/uv/)):

```bash
claude mcp add pdf-card -- uvx --from pdf-card-mcp pdf-card-mcp-server
```

Generic MCP host configuration:

```json
{
  "mcpServers": {
    "pdf-card": {
      "command": "uvx",
      "args": ["--from", "pdf-card-mcp", "pdf-card-mcp-server"]
    }
  }
}
```

For local development before the PyPI release, point the client at this checkout:

```json
{
  "mcpServers": {
    "pdf-card-local": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/pdf-card-mcp",
        "run",
        "python",
        "-m",
        "pdf_card_mcp.server"
      ]
    }
  }
}
```

Claude Desktop can also install the `.mcpb` bundle from the latest GitHub release.

### Docker / Registry Scanners

The repository includes a minimal `Dockerfile` so registries such as Glama can build the
server, start it over stdio, and inspect its MCP tool schemas. The server still works on local
file paths, so container users must mount any PDFs and output directories they want the tool to
read or write:

```bash
docker build -t pdf-card-mcp .
docker run --rm -i \
  -v "$PWD/examples:/docs" \
  pdf-card-mcp
```

## CLI Usage

```bash
pdf-card-mcp path/to/document.pdf --output examples/out/document.html
```

The command writes:

- `document.html`: standalone reader with embedded CSS, JavaScript, table crops, figure crops,
  formula crops, and source-page images.
- `document.manifest.json`: structured metadata without embedded image payloads.

The explicit subcommand form is also supported:

```bash
pdf-card-mcp convert path/to/document.pdf --output examples/out/document.html
```

## Notes, Highlights, And Static Publishing

Generated readers include a local annotation overlay:

- A highlight is selected source text.
- A note is selected source text plus your own typed note text.

Select text in a text card, choose `Highlight` or `Note`, and use `Export Markdown` to download
a readable `.annotations.md` file. Import is intentionally not exposed in the reader UI yet.
Notes and highlights are user-authored data and are kept separate from the source-derived
`document.manifest.json`.

The lower-level CLI and MCP publishing tools still accept a structured annotation bundle when
you need to build a read-only static reader with embedded annotations. Validate that bundle
against a reader:

```bash
pdf-card-mcp validate-annotations examples/out/document.html document.annotations.json
```

Publish a shareable static reader with public annotations:

```bash
pdf-card-mcp publish examples/out/document.html \
  --annotations document.annotations.json \
  --output published/document-reader.html
```

If `--output` is a directory instead of an `.html` file, the command writes a static bundle:

- `index.html`
- `reader.manifest.json`
- `reader.annotations.json`
- `bundle.json`

Publishing includes only `visibility: public` annotations by default, redacts the local
`source_pdf` path by default, and renders the published reader read-only by default. Use
`--include-private` only when you intentionally want private local notes included in the
published output. Publishing fails if any included annotation cannot be anchored to the reader;
run `validate-annotations` to inspect mismatches before publishing.

## MCP Tool

The MCP server is the automation layer around the same local converter. It accepts local
file paths from an MCP client and returns generated reader paths, manifest metadata,
warnings, and publishing/validation results.

The server exposes three tools:

```text
convert_pdf_to_card_html
validate_reader_annotations
publish_reader_bundle
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

`validate_reader_annotations` checks a notes/highlights sidecar against a generated reader.
`publish_reader_bundle` writes a publish-ready static HTML file or directory bundle from an
existing generated reader and an optional annotation sidecar.

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

This builds three bundles:

- `dist/pdf-card-mcp-lite.mcpb` and `dist/pdf-card-mcp.mcpb` declare `server.type = "python"`
  for MCP registry and Smithery directory compatibility. The full bundle additionally installs the
  `table-ml` extra. These execute through `uv`, so the host (or user) must provide `uv`.
- `dist/pdf-card-mcp-desktop.mcpb` declares `server.type = "uv"` (from `manifest.uv.json`). Claude
  Desktop manages Python and dependencies itself, so end users can double-click to install with no
  prerequisites. This is the bundle linked from the one-click install section above.

No bundle vendors ML model weights; `gmft` downloads and caches them locally on first use unless
`offline=true` is set with a prewarmed cache.

## Privacy

Default PDF processing is local. The deterministic converter does not upload document contents
or call external APIs. Optional OCR runs locally when the user has installed OCR dependencies.

When `style_engine=sampling` or `postprocess_engine=sampling` is enabled through MCP, the host
LLM may receive bounded style hints or card text snippets so it can return validated style-token
or boundary-operation plans. Use deterministic `fixed`/`pdf` style and `postprocess_engine=none`
when no document-derived text should leave the local process.

Published readers may contain extracted PDF text, source-page images, table/figure/formula crops,
and any included public notes or highlights. Only publish generated readers when you have the
rights to share the source document content and your annotations.

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
