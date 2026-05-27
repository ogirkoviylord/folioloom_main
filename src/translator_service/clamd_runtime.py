import argparse
import json
import socket
import sys
from dataclasses import dataclass

from translator_service.document_scanner import ClamdDocumentScanner, ScannerVerdict
from translator_service.documents import DocumentFormat

EICAR_TEST_FILE_BYTES = (
    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}"
    b"$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
)


class ClamdRuntimeCheckError(RuntimeError):
    pass


@dataclass(frozen=True)
class ClamdRuntimeStatus:
    status: str
    scanner_name: str
    host: str
    port: int
    scanner_version: str | None = None
    signature_database_version: str | None = None
    eicar_verdict: str | None = None

    def safe_metadata(self) -> dict[str, object]:
        return {
            "status": self.status,
            "scanner_name": self.scanner_name,
            "host": self.host,
            "port": self.port,
            "scanner_version": self.scanner_version,
            "signature_database_version": self.signature_database_version,
            "eicar_verdict": self.eicar_verdict,
        }


def check_clamd_runtime(
    *,
    host: str,
    port: int,
    timeout_seconds: float,
    response_limit_bytes: int = 4096,
    scan_eicar: bool = False,
) -> ClamdRuntimeStatus:
    pong = _send_clamd_command(
        host=host,
        port=port,
        timeout_seconds=timeout_seconds,
        response_limit_bytes=response_limit_bytes,
        command=b"zPING\0",
    )
    if pong.strip() != "PONG":
        raise ClamdRuntimeCheckError("clamd did not respond to PING")

    version = _send_clamd_command(
        host=host,
        port=port,
        timeout_seconds=timeout_seconds,
        response_limit_bytes=response_limit_bytes,
        command=b"zVERSION\0",
    )
    scanner_version, signature_database_version = _parse_version(version)
    eicar_verdict = None
    if scan_eicar:
        eicar_verdict = _check_eicar_detection(
            host=host,
            port=port,
            timeout_seconds=timeout_seconds,
            response_limit_bytes=response_limit_bytes,
        )
    return ClamdRuntimeStatus(
        status="ok",
        scanner_name="clamd",
        host=host,
        port=port,
        scanner_version=scanner_version,
        signature_database_version=signature_database_version,
        eicar_verdict=eicar_verdict,
    )


def _check_eicar_detection(
    *,
    host: str,
    port: int,
    timeout_seconds: float,
    response_limit_bytes: int,
) -> str:
    scanner = ClamdDocumentScanner(
        host=host,
        port=port,
        timeout_seconds=timeout_seconds,
        response_limit_bytes=response_limit_bytes,
    )
    result = scanner.scan(
        file_name="eicar.txt",
        content=EICAR_TEST_FILE_BYTES,
        document_format=DocumentFormat.TXT,
    )
    if result.verdict is not ScannerVerdict.INFECTED:
        raise ClamdRuntimeCheckError("clamd did not detect EICAR test signature")
    return result.verdict.value


def _send_clamd_command(
    *,
    host: str,
    port: int,
    timeout_seconds: float,
    response_limit_bytes: int,
    command: bytes,
) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as sock:
            sock.settimeout(timeout_seconds)
            sock.sendall(command)
            response = bytearray()
            while len(response) < response_limit_bytes:
                chunk = sock.recv(min(1024, response_limit_bytes - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
                if b"\0" in chunk or b"\n" in chunk:
                    break
    except TimeoutError as error:
        raise ClamdRuntimeCheckError("clamd check timed out") from error
    except OSError as error:
        raise ClamdRuntimeCheckError("clamd is unavailable") from error

    if not response:
        raise ClamdRuntimeCheckError("clamd returned an empty response")
    raw_line = bytes(response).split(b"\0", 1)[0].split(b"\n", 1)[0]
    return _sanitize_metadata_text(raw_line.decode("utf-8", errors="replace"))


def _parse_version(version: str) -> tuple[str | None, str | None]:
    parts = version.split("/")
    scanner_version = _sanitize_metadata_text(parts[0]) if parts else None
    signature_database_version = (
        _sanitize_metadata_text(parts[1]) if len(parts) > 1 else None
    )
    return scanner_version or None, signature_database_version or None


def _sanitize_metadata_text(value: str, *, limit: int = 160) -> str:
    safe = "".join(character for character in value if character.isprintable()).strip()
    return safe[:limit]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check internal clamd runtime availability with safe metadata."
    )
    parser.add_argument("--host", default="clamd")
    parser.add_argument("--port", type=int, default=3310)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--response-limit-bytes", type=int, default=4096)
    parser.add_argument(
        "--scan-eicar",
        action="store_true",
        help="Verify the safe EICAR test signature is detected via INSTREAM.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        status = check_clamd_runtime(
            host=args.host,
            port=args.port,
            timeout_seconds=args.timeout,
            response_limit_bytes=args.response_limit_bytes,
            scan_eicar=args.scan_eicar,
        )
    except Exception as error:
        print(f"clamd runtime check failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(status.safe_metadata(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
