#!/usr/bin/env python3
"""Tiny owner-local HTTP bridge for the FolioLoom Figma development plugin.

The server intentionally binds only to 127.0.0.1 and keeps state in memory.
It is local design/prototyping infrastructure, not a production service.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

HOST = "127.0.0.1"
DEFAULT_PORT = 47831
MAX_JSON_BYTES = 1024 * 1024
BODY_ERROR = object()
ALLOWED_FIGMA_ORIGINS = frozenset({"null", "https://www.figma.com"})


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "spec_id": spec.get("spec_id") if isinstance(spec.get("spec_id"), str) else None,
        "title": spec.get("title") if isinstance(spec.get("title"), str) else None,
    }


class BridgeState:
    def __init__(self) -> None:
        self.latest: dict[str, Any] | None = None
        self.latest_ack: dict[str, Any] | None = None
        self.next_item_id = 1
        self.next_ack_id = 1

    def store_spec(self, spec: dict[str, Any]) -> dict[str, Any]:
        metadata = compact_metadata(spec)
        item = {
            "item_id": self.next_item_id,
            "version": self.next_item_id,
            "received_at": utc_now(),
            "spec_id": metadata["spec_id"],
            "title": metadata["title"],
            "spec": spec,
        }
        self.next_item_id += 1
        self.latest = item
        self.latest_ack = None
        return item

    def store_ack(self, ack: dict[str, Any]) -> dict[str, Any]:
        item = {
            "ack_id": self.next_ack_id,
            "received_at": utc_now(),
            "ack": ack,
        }
        self.next_ack_id += 1
        self.latest_ack = item
        return item


STATE = BridgeState()


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "FolioLoomFigmaBridge/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - BaseHTTPRequestHandler API name.
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def do_OPTIONS(self) -> None:
        origin = self.allowed_cors_origin()
        if self.headers.get("Origin") and origin is None:
            self.send_response(HTTPStatus.FORBIDDEN)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        if origin is not None:
            self.send_cors_headers(origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        if self.reject_disallowed_origin():
            return
        path = urlparse(self.path).path
        if path == "/health":
            self.write_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "status": "ready",
                    "host": HOST,
                    "port": int(getattr(self.server, "server_port", DEFAULT_PORT)),
                    "has_latest": STATE.latest is not None,
                    "latest": self.latest_metadata(),
                    "latest_ack": STATE.latest_ack,
                },
            )
            return
        if path == "/latest":
            if STATE.latest is None:
                self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "no spec has been posted"})
            else:
                self.write_json(HTTPStatus.OK, {"ok": True, "latest": STATE.latest, "latest_ack": STATE.latest_ack})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown endpoint"})

    def do_POST(self) -> None:
        if self.reject_disallowed_origin():
            return
        path = urlparse(self.path).path
        if path == "/spec":
            payload = self.read_json_body()
            if payload is BODY_ERROR:
                return
            if not isinstance(payload, dict):
                self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "JSON body must be an object"})
                return
            item = STATE.store_spec(payload)
            self.write_json(HTTPStatus.OK, {"ok": True, "latest": {key: item[key] for key in ("item_id", "version", "received_at", "spec_id", "title")}})
            return
        if path == "/render-ack":
            payload = self.read_json_body()
            if payload is BODY_ERROR:
                return
            if not isinstance(payload, dict):
                self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "JSON body must be an object"})
                return
            ack = STATE.store_ack(payload)
            self.write_json(HTTPStatus.OK, {"ok": True, "latest_ack": ack})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "unknown endpoint"})

    def read_json_body(self) -> Any:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError:
            self.write_json(HTTPStatus.LENGTH_REQUIRED, {"ok": False, "error": "invalid Content-Length"})
            return BODY_ERROR
        if length <= 0:
            self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "empty JSON body"})
            return BODY_ERROR
        if length > MAX_JSON_BYTES:
            self.write_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False, "error": "JSON body exceeds 1 MiB"})
            return BODY_ERROR
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self.write_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"invalid JSON: {error}"})
            return BODY_ERROR

    def latest_metadata(self) -> dict[str, Any] | None:
        if STATE.latest is None:
            return None
        return {key: STATE.latest[key] for key in ("item_id", "version", "received_at", "spec_id", "title")}

    def allowed_cors_origin(self) -> str | None:
        origin = self.headers.get("Origin")
        if origin in ALLOWED_FIGMA_ORIGINS:
            return origin
        return None

    def reject_disallowed_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_FIGMA_ORIGINS:
            self.write_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Origin is not allowed for this local bridge"})
            return True
        return False

    def send_cors_headers(self, origin: str) -> None:
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")

    def write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        origin = self.allowed_cors_origin()
        if origin is not None:
            self.send_cors_headers(origin)
        self.end_headers()
        self.wfile.write(body)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the owner-local FolioLoom Figma bridge on 127.0.0.1 only.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"loopback port (default: {DEFAULT_PORT})")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not (1 <= args.port <= 65535):
        print("error: --port must be between 1 and 65535", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer((HOST, args.port), BridgeHandler)
    print(f"FolioLoom Figma bridge listening on http://{HOST}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping bridge.", file=sys.stderr)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
