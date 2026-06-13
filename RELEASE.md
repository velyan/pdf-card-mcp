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

5. Build MCPB artifacts:

   ```bash
   .venv/bin/python scripts/build_mcpb.py --variant all
   ```

6. Create and push a `vX.Y.Z` tag. The release workflow builds Python and MCPB artifacts and
   attaches them to the GitHub release.

Do not publish generated readers or PDF fixtures unless the project has explicit redistribution
rights for the source documents.
