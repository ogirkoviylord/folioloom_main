#!/usr/bin/env python3
"""Read latest spec metadata and render ack from the owner-local bridge."""

from __future__ import annotations

import argparse
import json
import sys
from urllib import error, request
from urllib.parse import urlsplit

DEFAULT_BRIDGE_URL = "http://127.0.0.1:47831"


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


def get_json(url: str) -> dict:
    bridge_url = validate_bridge_url(url)
    with request.urlopen(bridge_url + "/latest", timeout=5) as response:  # noqa: S310 - owner-local loopback helper.
        body = response.read().decode("utf-8")
    return json.loads(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show latest local Figma bridge spec status and render ack.")
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
    try:
        result = get_json(bridge_url)
    except error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        return 1
    except error.URLError as exc:
        print(f"error: bridge request failed: {exc}", file=sys.stderr)
        return 1
    latest = result.get("latest") or {}
    summary = {
        "item_id": latest.get("item_id"),
        "version": latest.get("version"),
        "received_at": latest.get("received_at"),
        "spec_id": latest.get("spec_id"),
        "title": latest.get("title"),
        "latest_ack": result.get("latest_ack"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
