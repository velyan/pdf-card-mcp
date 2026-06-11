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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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


if __name__ == "__main__":
    raise SystemExit(main())
