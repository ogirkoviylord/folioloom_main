"""Shared JSON helpers used across the translator service."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class DuplicateJsonKeyError(ValueError):
    """Raised when a JSON object contains duplicate keys."""


def json_object_without_duplicate_keys(
    pairs: Sequence[tuple[str, Any]],
) -> dict[str, Any]:
    """``object_pairs_hook`` for :func:`json.loads` that rejects duplicate keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(key)
        result[key] = value
    return result


def read_json_file(path: Path) -> Any:
    """Read and parse a UTF-8 JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    """Atomically write *document* as pretty-printed JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
