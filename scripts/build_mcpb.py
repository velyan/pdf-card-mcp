from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VARIANTS = {
    "lite": ("manifest.json", "pdf-card-mcp-lite.mcpb"),
    "full": ("manifest.full.json", "pdf-card-mcp.mcpb"),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PDF Card MCPB release artifacts.")
    parser.add_argument("--variant", choices=[*VARIANTS, "all"], default="all")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--no-update-server-json",
        action="store_true",
        help="Do not refresh server.json with the lite artifact SHA-256.",
    )
    args = parser.parse_args()

    variants = VARIANTS.keys() if args.variant == "all" else [args.variant]
    args.dist.mkdir(parents=True, exist_ok=True)
    for variant in variants:
        manifest_name, output_name = VARIANTS[variant]
        build_variant(variant, ROOT / manifest_name, args.dist / output_name)
    if "lite" in variants and not args.no_update_server_json:
        update_server_json_hash(args.dist / VARIANTS["lite"][1])
    return 0


def build_variant(variant: str, manifest_path: Path, output_path: Path) -> None:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest for {variant}: {manifest_path}")
    with tempfile.TemporaryDirectory(prefix=f"pdf-card-mcp-{variant}-") as tmp:
        bundle_root = Path(tmp) / "bundle"
        shutil.copytree(ROOT, bundle_root, ignore=ignore_bundle_paths)
        shutil.copy2(manifest_path, bundle_root / "manifest.json")
        subprocess.run(["mcpb", "validate", str(bundle_root)], check=True)
        subprocess.run(["mcpb", "pack", str(bundle_root), str(output_path)], check=True)
    sha_path = output_path.with_suffix(output_path.suffix + ".sha256")
    sha_path.write_text(f"{sha256(output_path)}  {output_path.name}\n", encoding="utf-8")


def ignore_bundle_paths(_directory: str, names: list[str]) -> set[str]:
    ignored = {
        ".coverage",
        ".DS_Store",
        ".git",
        ".github",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "examples",
        "server.json",
        "tests",
    }
    ignored_names = {
        name
        for name in names
        if name in ignored or name.startswith(".venv") or name.endswith(".egg-info")
    }
    directory = Path(_directory)
    if directory.name == "docs":
        ignored_names.update(name for name in names if name == "assets")
    return ignored_names


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_server_json_hash(artifact_path: Path) -> None:
    server_path = ROOT / "server.json"
    if not server_path.exists():
        return
    artifact_hash = sha256(artifact_path)
    data = json.loads(server_path.read_text(encoding="utf-8"))
    for package in data.get("packages", []):
        if str(package.get("identifier", "")).endswith(f"/{artifact_path.name}"):
            package["fileSha256"] = artifact_hash
            break
    server_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
