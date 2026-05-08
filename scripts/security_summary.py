#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from translator_service.security_summary import (
    build_security_summary,
    render_security_summary_markdown,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a privacy-safe security summary from translation run logs."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default="var/translation-runs",
        help="Translation run log root directory.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format.",
    )
    parser.add_argument(
        "--recent-limit",
        type=int,
        default=10,
        help="Maximum recent security runs to include.",
    )
    args = parser.parse_args()

    summary = build_security_summary(args.root, recent_limit=args.recent_limit)
    if args.format == "json":
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(render_security_summary_markdown(summary), end="")


if __name__ == "__main__":
    main()
