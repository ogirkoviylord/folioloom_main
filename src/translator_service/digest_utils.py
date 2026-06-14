"""Shared content-digest helpers used across the translator service."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def payload_digest(
    payload: Any,
    *,
    length: int | None = 24,
    compact: bool = True,
) -> str:
    """Return a truncated SHA-256 hex digest of a canonically-encoded JSON payload.

    *compact=True* uses minimal separators (``","``, ``":"``).
    *compact=False* uses the default Python separators (``", "``, ``": "``).
    *length=None* returns the full 64-char hex digest.
    """
    if compact:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    else:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    hexdigest = hashlib.sha256(encoded).hexdigest()
    return hexdigest if length is None else hexdigest[:length]


def text_digest(value: str, *, length: int | None = 24) -> str:
    """Return a truncated SHA-256 hex digest of a UTF-8 string.

    *length=None* returns the full 64-char hex digest.
    """
    hexdigest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return hexdigest if length is None else hexdigest[:length]
