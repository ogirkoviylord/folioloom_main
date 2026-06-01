#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from translator_service.internal_reader import (
    generate_docx_reader_html_from_path,
    generate_epub_reader_html_from_path,
    generate_txt_reader_html_from_path,
    load_translation_mapping,
    reject_runtime_var_path,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate an internal/dev before-after HTML report.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Explicit local TXT, DOCX or EPUB input path.",
    )
    parser.add_argument(
        "--format",
        choices=("txt", "docx", "epub"),
        default="txt",
        help="Source format. Defaults to txt.",
    )
    parser.add_argument(
        "--translations",
        type=Path,
        help="Optional JSON object mapping source_block_id to translated text.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output HTML path.",
    )
    parser.add_argument(
        "--max-fragment-chars",
        type=int,
        default=5_000,
        help="Adapter planning limit. Defaults to 5000.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reject_runtime_var_path(args.out)
    translations = (
        load_translation_mapping(args.translations)
        if args.translations is not None
        else None
    )
    if args.format == "epub":
        html = generate_epub_reader_html_from_path(
            source_path=args.source,
            translated_by_block_id=translations,
            max_fragment_chars=args.max_fragment_chars,
        )
    elif args.format == "docx":
        html = generate_docx_reader_html_from_path(
            source_path=args.source,
            translated_by_block_id=translations,
            max_fragment_chars=args.max_fragment_chars,
        )
    else:
        html = generate_txt_reader_html_from_path(
            source_path=args.source,
            translated_by_block_id=translations,
            max_fragment_chars=args.max_fragment_chars,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote internal reader report: {args.out}")


if __name__ == "__main__":
    main()
