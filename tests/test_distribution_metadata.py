from __future__ import annotations

import json
import tomllib
from pathlib import Path

from scripts.build_mcpb import ignore_bundle_paths


ROOT = Path(__file__).resolve().parents[1]


def load_json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_server_json_is_registry_safe() -> None:
    data = load_json("server.json")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    assert data["name"] == "io.github.velyan/pdf-card-mcp"
    assert len(data["description"]) <= 100
    assert data["version"] == version
    assert data["repository"] == {
        "url": "https://github.com/velyan/pdf-card-mcp",
        "source": "github",
    }
    assert data["websiteUrl"].startswith("https://github.com/velyan/pdf-card-mcp")

    package = data["packages"][0]
    assert package["registryType"] == "mcpb"
    assert package["identifier"].endswith(f"/v{version}/pdf-card-mcp-lite.mcpb")
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


def test_mcpb_manifest_declares_smithery_compatible_runtime() -> None:
    for manifest_name in ("manifest.json", "manifest.full.json"):
        manifest = load_json(manifest_name)

        assert manifest["server"]["type"] == "python"
        assert {tool["name"] for tool in manifest["tools"]} == {
            "convert_pdf_to_card_html",
            "validate_reader_annotations",
            "publish_reader_bundle",
        }


def test_glama_maintainer_metadata_exists() -> None:
    data = load_json("glama.json")

    assert data["$schema"] == "https://glama.ai/mcp/schemas/server.json"
    assert data["maintainers"] == ["velyan"]


def test_mcpb_builder_ignores_local_environments_and_build_outputs() -> None:
    names = [
        ".venv",
        ".venv-verify",
        ".venv-release",
        ".coverage",
        ".DS_Store",
        "dist",
        "build",
        "pdf_card_mcp.egg-info",
        "src",
        "pyproject.toml",
        "uv.lock",
    ]

    ignored = ignore_bundle_paths("/repo", names)

    assert ".venv" in ignored
    assert ".venv-verify" in ignored
    assert ".venv-release" in ignored
    assert ".coverage" in ignored
    assert ".DS_Store" in ignored
    assert "dist" in ignored
    assert "build" in ignored
    assert "pdf_card_mcp.egg-info" in ignored
    assert "src" not in ignored
    assert "pyproject.toml" not in ignored
    assert "uv.lock" not in ignored


def test_mcpb_builder_ignores_docs_assets() -> None:
    ignored = ignore_bundle_paths("/repo/docs", ["assets", "how-it-works.html"])

    assert "assets" in ignored
    assert "how-it-works.html" not in ignored
