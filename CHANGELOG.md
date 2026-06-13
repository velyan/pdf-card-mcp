# Changelog

All notable changes to PDF Card MCP will be documented here.

## Unreleased

Nothing yet.

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
