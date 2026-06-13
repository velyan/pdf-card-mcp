# Release Process

PDF Card MCP releases should be reproducible from a clean checkout.

1. Update `CHANGELOG.md`.
2. Confirm versions match in `pyproject.toml`, `src/pdf_card_mcp/__init__.py`, MCP manifests,
   and `server.json`.
3. Run the test suite:

   ```bash
   .venv/bin/python -m pytest
   ```

4. Build Python artifacts and check metadata:

   ```bash
   .venv/bin/python -m pip install build twine
   .venv/bin/python -m build
   .venv/bin/python -m twine check dist/*.whl dist/*.tar.gz
   ```

5. Publish the Python package to PyPI from the checked artifacts. Use PyPI Trusted
   Publishing for tagged releases when it is configured; otherwise upload with an API token:

   ```bash
   .venv/bin/python -m twine upload dist/*.whl dist/*.tar.gz
   ```

   Verify the package from a clean environment:

   ```bash
   python -m pip install pdf-card-mcp
   pdf-card-mcp --help
   python -c "import pdf_card_mcp.server"
   ```

6. Build MCPB artifacts:

   ```bash
   .venv/bin/python scripts/build_mcpb.py --variant all
   ```

   This refreshes `server.json` with the SHA-256 of `dist/pdf-card-mcp-lite.mcpb`.
   Confirm the committed `server.json` hash matches the release asset before publishing
   to the official MCP registry.

7. Create and push a `vX.Y.Z` tag. The release workflow builds Python and MCPB artifacts and
   attaches them to the GitHub release.

8. After the GitHub release assets exist, publish `server.json` to the official registry:

   ```bash
   mcp-publisher login github
   mcp-publisher publish
   ```

9. Keep these discovery surfaces in sync for each launch:

   ```bash
   gh repo edit velyan/pdf-card-mcp \
     --add-topic mcp,model-context-protocol,pdf,documents,html,reader,accessibility,local-first,claude
   ```

   Set the GitHub repository homepage to the README, GitHub Pages docs, or the public
   registry listing after it is live. Submit or verify listings on Glama, mcp.so,
   PulseMCP, Smithery, and Awesome MCP Servers only after PyPI and the release assets work.

Do not publish generated readers or PDF fixtures unless the project has explicit redistribution
rights for the source documents.
