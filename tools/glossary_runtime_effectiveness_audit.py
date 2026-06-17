from __future__ import annotations

import argparse
import sys
from pathlib import Path

from translator_service.glossary_runtime_effectiveness_audit import (
    audit_glossary_runtime_effectiveness,
    serialize_runtime_effectiveness_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a local metadata-only glossary runtime effectiveness audit.",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        help="Optional owner-only diagnostic archive to summarize without raw output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional metadata-only JSON report path.",
    )
    args = parser.parse_args(argv)

    report = audit_glossary_runtime_effectiveness(archive_dir=args.archive_dir)
    rendered = serialize_runtime_effectiveness_audit(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
