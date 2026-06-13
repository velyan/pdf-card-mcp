# Contributing

Thanks for helping improve PDF Card MCP. This project is an early local-first PDF-to-reader
tool, so changes should preserve source text, avoid hidden network calls, and keep the generated
reader portable across devices.

## Development Setup

```bash
git clone https://github.com/velyan/pdf-card-mcp.git
cd pdf-card-mcp
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -e ".[dev]"
```

Run tests before opening a pull request:

```bash
.venv/bin/python -m pytest
```

## Contribution Guidelines

- Keep extraction and user-authored annotation data separate.
- Do not rewrite, summarize, delete, or invent PDF source text in post-processing.
- Add focused tests for new reader behavior, CLI/MCP tools, and schema changes.
- Do not commit generated corpora, copyrighted PDFs, or large local model caches.
- Document privacy or copyright implications for any feature that exports, publishes, or sends
  document-derived content outside the local process.

## Pull Requests

Describe the user-visible behavior, note any compatibility changes, and include the test command
you ran. If the change affects generated HTML, include enough detail for reviewers to reproduce
the output locally.
