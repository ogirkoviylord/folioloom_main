from __future__ import annotations

import argparse
import sys
from pathlib import Path

from translator_service.glossary_candidate_quality_audit import (
    audit_prepared_glossary_candidate_quality,
    default_candidate_quality_audit_cases,
    serialize_candidate_quality_audit,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a local metadata-only prepared glossary quality audit.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional metadata-only JSON report path.",
    )
    args = parser.parse_args(argv)

    report = audit_prepared_glossary_candidate_quality(
        default_candidate_quality_audit_cases()
    )
    rendered = serialize_candidate_quality_audit(report)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
