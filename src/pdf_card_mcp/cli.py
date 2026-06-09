from __future__ import annotations

import argparse
import json
from pathlib import Path

from .converter import convert_pdf_to_card_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf-card-mcp",
        description="Convert a PDF into a standalone card-based HTML reader.",
    )
    parser.add_argument("pdf_path", help="Path to the input PDF.")
    parser.add_argument("-o", "--output", help="Path to write the standalone HTML file.")
    parser.add_argument("--title", help="Override the reader title.")
    parser.add_argument("--max-pages", type=int, help="Only process the first N pages.")
    parser.add_argument("--ocr", action="store_true", help="Use optional OCR fallback for scanned pages.")
    parser.add_argument("--theme", default="soft", help="Reader theme name. Default: soft.")
    parser.add_argument("--json", action="store_true", help="Print only structured JSON output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = convert_pdf_to_card_html(
        pdf_path=Path(args.pdf_path),
        output_path=Path(args.output) if args.output else None,
        title=args.title,
        max_pages=args.max_pages,
        ocr=args.ocr,
        theme=args.theme,
    )
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Wrote {result.html_path}")
        print(f"Wrote {result.manifest_path}")
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
