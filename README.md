# PDF Card MCP

PDF Card MCP is a local-first MCP tool that converts dense PDFs into soft, minimal,
card-based HTML readers. It preserves source text, renders source pages, crops detected
tables and figures as images, and writes a standalone HTML file that can be moved across
devices without losing assets.

The default reader is designed for comfortable reading: large type, small cards, search,
section navigation, next/previous controls, keyboard navigation, and source-page previews.

## Status

This is an early open-source implementation. It is useful for text-layer PDFs now, with
best-effort table detection via `pdfplumber` and raster crops via PyMuPDF. Scanned PDFs
need optional OCR support.

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

## CLI Usage

```bash
pdf-card-mcp path/to/document.pdf --output examples/out/document.html
```

The command writes:

- `document.html`: standalone reader with embedded CSS, JavaScript, table crops, figure crops,
  and source-page images.
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

Run the server locally:

```bash
python -m pdf_card_mcp.server
```

## MCPB Packaging

This repo is arranged so the root can be packed directly:

```bash
mcpb validate .
mcpb pack . dist/pdf-card-mcp-0.1.0.mcpb
```

The MCPB manifest uses `server.type = "uv"`, so hosts that support UV runtime can install
dependencies from `pyproject.toml` instead of relying on a user-managed Python setup.

## Privacy

PDF processing is local. The tool does not upload document contents or call external APIs.
Optional OCR runs locally when the user has installed OCR dependencies.

## How Tables Are Handled

All detected tables are rendered as image cards. The converter uses `pdfplumber` to find table
regions, then uses PyMuPDF to rasterize the source region into PNG. Captions are preserved as
reader text and alt text, but the table itself remains an image so layout and numeric alignment
survive conversion.

If a document mentions tables but no reliable table regions are found, the manifest includes a
warning so callers can decide whether to inspect the source pages.

## License

MIT
