from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_server_json_is_registry_safe() -> None:
    data = load_json("server.json")

    assert data["name"] == "io.github.velyan/pdf-card-mcp"
    assert len(data["description"]) <= 100
    assert data["repository"] == {
        "url": "https://github.com/velyan/pdf-card-mcp",
        "source": "github",
    }
    assert data["websiteUrl"].startswith("https://github.com/velyan/pdf-card-mcp")

    package = data["packages"][0]
    assert package["registryType"] == "mcpb"
    assert package["identifier"].endswith("/v0.1.0/pdf-card-mcp-lite.mcpb")
    assert len(package["fileSha256"]) == 64
    assert set(package["fileSha256"]) <= set("0123456789abcdef")


def test_distribution_keywords_are_consistent() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_keywords = set(pyproject["project"]["keywords"])
    manifest_keywords = set(load_json("manifest.json")["keywords"])
    full_manifest_keywords = set(load_json("manifest.full.json")["keywords"])

    required = {
        "mcp",
        "model-context-protocol",
        "pdf",
        "documents",
        "html",
        "reader",
        "accessibility",
        "local-first",
        "annotations",
        "claude",
    }
    assert required <= project_keywords
    assert required <= manifest_keywords
    assert required <= full_manifest_keywords


def test_glama_maintainer_metadata_exists() -> None:
    data = load_json("glama.json")

    assert data["$schema"] == "https://glama.ai/mcp/schemas/server.json"
    assert data["maintainers"] == ["velyan"]
