from __future__ import annotations

from pathlib import Path

from pdf_card_mcp import cli


class FakeConvertResult:
    html_path = Path("out.html")
    manifest_path = Path("out.manifest.json")

    def to_dict(self) -> dict:
        return {
            "html_path": str(self.html_path),
            "manifest_path": str(self.manifest_path),
            "page_count": 1,
            "card_count": 1,
            "table_count": 0,
            "figure_count": 0,
            "formula_count": 0,
            "warnings": [],
            "style_engine": "pdf",
        }


class FakePublishResult:
    output_path = Path("published.html")
    manifest_path = None
    annotations_path = None
    bundle_path = None

    def to_dict(self) -> dict:
        return {
            "output_path": str(self.output_path),
            "manifest_path": None,
            "annotations_path": None,
            "bundle_path": None,
            "annotation_count": 0,
            "warnings": [],
        }


def test_cli_preserves_positional_convert_flow(monkeypatch, capsys) -> None:
    called = {}

    def fake_convert_pdf_to_card_html(**kwargs):
        called.update(kwargs)
        return FakeConvertResult()

    monkeypatch.setattr(cli, "convert_pdf_to_card_html", fake_convert_pdf_to_card_html)

    exit_code = cli.main(["paper.pdf", "--output", "out.html", "--json"])

    assert exit_code == 0
    assert called["pdf_path"] == Path("paper.pdf")
    assert called["output_path"] == Path("out.html")
    assert '"html_path": "out.html"' in capsys.readouterr().out


def test_cli_publish_dispatch(monkeypatch, capsys) -> None:
    called = {}

    def fake_publish_reader_bundle(**kwargs):
        called.update(kwargs)
        return FakePublishResult()

    monkeypatch.setattr(cli, "publish_reader_bundle", fake_publish_reader_bundle)

    exit_code = cli.main(
        [
            "publish",
            "reader.html",
            "--annotations",
            "notes.json",
            "--output",
            "published.html",
            "--json",
        ]
    )

    assert exit_code == 0
    assert called["reader_html_path"] == Path("reader.html")
    assert called["annotations_path"] == Path("notes.json")
    assert called["output_path"] == Path("published.html")
    assert '"output_path": "published.html"' in capsys.readouterr().out


def test_cli_validate_annotations_uses_exit_status(monkeypatch) -> None:
    def fake_validate_reader_annotations(**_kwargs):
        return {"valid": False, "accepted_count": 0, "rejected_count": 1, "warnings": []}

    monkeypatch.setattr(cli, "validate_reader_annotations", fake_validate_reader_annotations)

    assert cli.main(["validate-annotations", "reader.html", "notes.json", "--json"]) == 1
