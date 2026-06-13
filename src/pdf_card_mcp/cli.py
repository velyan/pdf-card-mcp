from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .converter import convert_pdf_to_card_html
from .publish import publish_reader_bundle, validate_reader_annotations


def build_convert_parser(prog: str = "pdf-card-mcp") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Convert a local PDF into a portable, source-linked HTML reader with embedded "
            "page previews and detected table, figure, and formula crops."
        ),
    )
    parser.add_argument("pdf_path", help="Path to the input PDF.")
    parser.add_argument("-o", "--output", help="Path to write the standalone HTML file.")
    parser.add_argument("--title", help="Override the reader title.")
    parser.add_argument("--max-pages", type=int, help="Only process the first N pages.")
    parser.add_argument("--ocr", action="store_true", help="Use optional OCR fallback for scanned pages.")
    parser.add_argument("--theme", default="soft", help="Reader theme name. Default: soft.")
    parser.add_argument(
        "--style-engine",
        choices=["fixed", "pdf"],
        default="pdf",
        help="Reader style engine. Default: pdf.",
    )
    parser.add_argument(
        "--table-engine",
        choices=["auto", "pdfplumber", "gmft"],
        default="auto",
        help="Table detector to use. Default: auto.",
    )
    parser.add_argument(
        "--text-engine",
        choices=["char_geometry", "pdfplumber_words"],
        default="char_geometry",
        help="Text extractor to use for prose cards. Default: char_geometry.",
    )
    parser.add_argument("--model-cache-dir", help="Cache directory for optional local ML table models.")
    parser.add_argument("--offline", action="store_true", help="Use only already-cached optional ML models.")
    parser.add_argument("--json", action="store_true", help="Print only structured JSON output.")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-card-mcp",
        description=(
            "Local-first PDF reader toolkit: convert PDFs into source-linked HTML readers, "
            "validate notes/highlights, and publish static annotated bundles."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    convert_parser = subparsers.add_parser(
        "convert",
        help="Convert a PDF into a standalone card reader.",
        parents=[build_convert_parser("pdf-card-mcp convert")],
        add_help=False,
    )
    convert_parser.set_defaults(command="convert")

    publish_parser = subparsers.add_parser(
        "publish",
        help="Publish an existing reader with public notes and highlights.",
    )
    publish_parser.add_argument("reader_html", help="Path to a generated standalone reader HTML file.")
    publish_parser.add_argument(
        "--annotations",
        help="Optional annotation sidecar JSON. Private annotations are excluded by default.",
    )
    publish_parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Output .html path or directory for a static bundle.",
    )
    publish_parser.add_argument(
        "--include-private",
        action="store_true",
        help="Include private annotations in the published output and mark them public.",
    )
    publish_parser.add_argument(
        "--redact-source-path",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Redact source_pdf from the published reader payload. Default: true.",
    )
    publish_parser.add_argument(
        "--read-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Render published annotations read-only. Default: true.",
    )
    publish_parser.add_argument("--json", action="store_true", help="Print only structured JSON output.")

    validate_parser = subparsers.add_parser(
        "validate-annotations",
        help="Validate an annotation sidecar against a generated reader.",
    )
    validate_parser.add_argument("reader_html", help="Path to a generated standalone reader HTML file.")
    validate_parser.add_argument("annotations", help="Path to an annotation sidecar JSON file.")
    validate_parser.add_argument(
        "--include-private",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Validate private annotations too. Default: true.",
    )
    validate_parser.add_argument("--json", action="store_true", help="Print only structured JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] not in {"convert", "publish", "validate-annotations", "-h", "--help"}:
        return run_convert(build_convert_parser().parse_args(args_list))

    args = build_parser().parse_args(args_list)
    if args.command == "convert":
        return run_convert(args)
    if args.command == "publish":
        return run_publish(args)
    if args.command == "validate-annotations":
        return run_validate_annotations(args)
    build_parser().print_help()
    return 0


def run_convert(args: argparse.Namespace) -> int:
    result = convert_pdf_to_card_html(
        pdf_path=Path(args.pdf_path),
        output_path=Path(args.output) if args.output else None,
        title=args.title,
        max_pages=args.max_pages,
        ocr=args.ocr,
        theme=args.theme,
        style_engine=args.style_engine,
        table_engine=args.table_engine,
        text_engine=args.text_engine,
        model_cache_dir=Path(args.model_cache_dir) if args.model_cache_dir else None,
        offline=args.offline,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {result.html_path}")
        print(f"Wrote {result.manifest_path}")
        print(json.dumps(payload, indent=2))
    return 0


def run_publish(args: argparse.Namespace) -> int:
    result = publish_reader_bundle(
        reader_html_path=Path(args.reader_html),
        output_path=Path(args.output),
        annotations_path=Path(args.annotations) if args.annotations else None,
        include_private=args.include_private,
        redact_source_path=args.redact_source_path,
        read_only=args.read_only,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {result.output_path}")
        if result.manifest_path:
            print(f"Wrote {result.manifest_path}")
        if result.annotations_path:
            print(f"Wrote {result.annotations_path}")
        if result.bundle_path:
            print(f"Wrote {result.bundle_path}")
        print(json.dumps(payload, indent=2))
    return 0


def run_validate_annotations(args: argparse.Namespace) -> int:
    payload = validate_reader_annotations(
        reader_html_path=Path(args.reader_html),
        annotations_path=Path(args.annotations),
        include_private=args.include_private,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload, indent=2))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
