# Changelog

All notable changes to PDF Card MCP will be documented here.

## Unreleased

Nothing yet.

## 0.1.3 - 2026-06-25

- Skip repeating page headers and footers during text extraction, so running headers and footers
  no longer become reader cards. Detection requires the text to repeat in the top/bottom margins
  across pages, preserving one-off content such as titles and section headings.
- Add a one-click Claude Desktop bundle (`pdf-card-mcp-desktop.mcpb`, built from
  `manifest.uv.json` with `server.type = "uv"`). Claude Desktop manages the Python runtime and
  dependencies itself, so non-technical users can double-click to install with no user-managed
  `uv` or Python. The registry/Smithery bundles (`pdf-card-mcp-lite.mcpb`,
  `pdf-card-mcp.mcpb`) keep `server.type = "python"` for directory compatibility.
- Add one-click install buttons (Cursor, VS Code) and a clear `uv` prerequisite note to the README.

## 0.1.2 - 2026-06-14

- Add real README screenshots comparing generated readers with the source PDF.
- Keep docs-only screenshot assets out of MCPB release bundles.

## 0.1.1 - 2026-06-13

- Declare MCPB bundles as Python runtime while continuing to execute through `uv`, improving
  compatibility with registries that do not recognize `server.type = "uv"`.

## 0.1.0 - 2026-06-13

- Initial alpha converter, CLI, MCP server, and MCPB packaging.
- Standalone HTML reader with embedded source pages, table crops, figure crops, formula crops,
  search, section navigation, keyboard navigation, font sizing, and source previews.
- Local reader annotations for notes and highlights.
- Annotation sidecar validation.
- Static publishing for annotated readers as single HTML files or directory bundles.
- MCP tools for validating annotation sidecars and publishing static reader bundles.
- Public install, privacy, publishing, contribution, security, and distribution documentation.
