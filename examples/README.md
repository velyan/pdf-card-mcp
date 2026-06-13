# Examples

Generated readers should be written to `examples/out/`, which is ignored by git.

```bash
pdf-card-mcp path/to/your-document.pdf --output examples/out/your-document.html
```

To publish a reader with public notes and highlights:

```bash
pdf-card-mcp publish examples/out/your-document.html \
  --annotations examples/out/your-document.annotations.json \
  --output examples/out/published/your-document
```
