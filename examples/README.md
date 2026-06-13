# Examples

Generated readers should be written to `examples/out/`, which is ignored by git.

```bash
pdf-card-mcp path/to/your-document.pdf --output examples/out/your-document.html
```

Generated readers can export local notes and highlights as Markdown from the sidebar. To publish
a read-only static bundle with embedded annotations, pass a structured annotation bundle:

```bash
pdf-card-mcp publish examples/out/your-document.html \
  --annotations examples/out/your-document.annotations.json \
  --output examples/out/published/your-document
```
