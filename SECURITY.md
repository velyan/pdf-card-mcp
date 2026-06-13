# Security Policy

## Supported Versions

PDF Card MCP is currently pre-1.0. Security fixes are handled on the `main` branch until tagged
release maintenance branches exist.

## Reporting A Vulnerability

Please report suspected vulnerabilities privately through GitHub security advisories when the
repository is public. If advisories are unavailable, open an issue with minimal detail and ask
for a private contact path.

Do not include private PDFs, generated readers containing private source text, or annotation
sidecars with sensitive notes in public issues.

## Security Expectations

- Default conversion should stay local and should not call external APIs.
- Optional MCP sampling may disclose bounded style hints or source-text snippets to the host
  model provider; this must remain explicit in docs and tool descriptions.
- Published readers can contain source text, rendered page images, visual crops, notes, and
  highlights. Users are responsible for sharing only content they have rights to publish.
- Notes and imported annotation JSON must be rendered as escaped text, not raw HTML.
