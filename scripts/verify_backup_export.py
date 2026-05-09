#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from backup_server_data import verify_backup_manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a FolioLoom backup manifest and referenced artifacts."
    )
    parser.add_argument("manifest", help="Path to folioloom-backup-*.manifest.json")
    parser.add_argument(
        "--allow-empty-database",
        action="store_true",
        help="Allow backups where object storage has files but translation_jobs is empty.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        verify_backup_manifest(
            Path(args.manifest),
            allow_empty_database=args.allow_empty_database,
        )
    except Exception as error:
        print(f"Backup verification failed: {error}", file=sys.stderr)
        return 1
    print("Backup verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
