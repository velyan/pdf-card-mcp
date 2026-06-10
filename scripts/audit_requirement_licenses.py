from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


FORBIDDEN_PATTERN = re.compile(
    r"agpl|lgpl|gpl|gnu affero|gnu general public|gnu lesser general public|copyleft",
    re.IGNORECASE,
)
REQUIREMENT_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+*-]+)")


@dataclass(frozen=True, slots=True)
class Requirement:
    name: str
    version: str

    @property
    def normalized_name(self) -> str:
        return re.sub(r"[-_.]+", "-", self.name).lower()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail if exported pinned requirements advertise copyleft licenses."
    )
    parser.add_argument("requirements", nargs="+", type=Path)
    args = parser.parse_args()

    requirements = dedupe_requirements(
        requirement
        for path in args.requirements
        for requirement in parse_requirements(path)
    )
    failures: list[str] = []
    for requirement in requirements:
        metadata = fetch_pypi_metadata(requirement)
        license_text = "\n".join(
            value
            for value in [
                metadata.get("license_expression") or "",
                license_summary(str(metadata.get("license") or "")),
                *metadata.get("classifiers", []),
            ]
            if value
        )
        if FORBIDDEN_PATTERN.search(license_text):
            failures.append(f"{requirement.name}=={requirement.version}: {license_text}")

    if failures:
        print("Forbidden license indicators found:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(f"Checked {len(requirements)} pinned packages for copyleft license indicators.")
    return 0


def parse_requirements(path: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = REQUIREMENT_PATTERN.match(line)
        if match:
            requirements.append(Requirement(match.group(1), match.group(2)))
    return requirements


def dedupe_requirements(requirements: list[Requirement]) -> list[Requirement]:
    seen: set[tuple[str, str]] = set()
    deduped: list[Requirement] = []
    for requirement in sorted(
        requirements,
        key=lambda item: (item.normalized_name, item.version),
    ):
        key = (requirement.normalized_name, requirement.version)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(requirement)
    return deduped


def fetch_pypi_metadata(requirement: Requirement) -> dict[str, object]:
    url = f"https://pypi.org/pypi/{requirement.normalized_name}/{requirement.version}/json"
    try:
        with urlopen(url, timeout=15, context=ssl_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f"Could not fetch PyPI metadata for {requirement.name}") from error
    return payload.get("info", {})


def license_summary(license_text: str, max_lines: int = 8) -> str:
    lines = [line.strip() for line in license_text.splitlines() if line.strip()]
    return "\n".join(lines[:max_lines])


def ssl_context() -> ssl.SSLContext:
    try:
        import certifi
    except Exception:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


if __name__ == "__main__":
    raise SystemExit(main())
