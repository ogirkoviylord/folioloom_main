#!/usr/bin/env python3
"""Post a JSON Figma spec to the owner-local bridge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib import error, request
from urllib.parse import urlsplit

DEFAULT_BRIDGE_URL = "http://127.0.0.1:47831"
MAX_JSON_BYTES = 1024 * 1024


def validate_bridge_url(url: str) -> str:
    """Return the approved owner-local bridge origin or raise ValueError."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"bridge URL must be exactly {DEFAULT_BRIDGE_URL}") from exc
    if (
        url != DEFAULT_BRIDGE_URL
        or parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port != 47831
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"bridge URL must be exactly {DEFAULT_BRIDGE_URL}")
    return DEFAULT_BRIDGE_URL


def post_json(url: str, payload: bytes) -> dict:
    bridge_url = validate_bridge_url(url)
    req = request.Request(
        bridge_url + "/spec",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=5) as response:  # noqa: S310 - owner-local loopback helper.
        body = response.read().decode("utf-8")
    return json.loads(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a bounded FolioLoom Figma JSON spec to the local bridge.")
    parser.add_argument("spec_path", type=Path, help="path to a JSON spec/fixture")
    parser.add_argument(
        "--bridge-url",
        default=DEFAULT_BRIDGE_URL,
        help=f"exact owner-local bridge origin; only {DEFAULT_BRIDGE_URL} is accepted",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        bridge_url = validate_bridge_url(args.bridge_url)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    raw = args.spec_path.read_bytes()
    if len(raw) > MAX_JSON_BYTES:
        print("error: spec exceeds 1 MiB bridge limit", file=sys.stderr)
        return 2
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    try:
        result = post_json(bridge_url, payload)
    except error.URLError as exc:
        print(f"error: bridge request failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
