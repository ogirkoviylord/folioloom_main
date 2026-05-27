import socket
import struct
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from translator_service.documents import DocumentFormat


class ScannerVerdict(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    SCANNER_TIMEOUT = "scanner_timeout"
    SCANNER_UNAVAILABLE = "scanner_unavailable"
    SCANNER_ERROR = "scanner_error"
    UNSUPPORTED = "unsupported"
    SUSPICIOUS_CONTAINER = "suspicious_container"


@dataclass(frozen=True)
class ScanResult:
    verdict: ScannerVerdict
    scanner_name: str
    scanner_version: str | None
    signature_database_version: str | None
    content_sha256: str
    size_bytes: int
    document_format: DocumentFormat
    safe_error_class: str | None = None

    def safe_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "verdict": self.verdict.value,
            "scanner_name": self.scanner_name,
            "scanner_version": self.scanner_version,
            "signature_database_version": self.signature_database_version,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "document_format": self.document_format.value,
        }
        if self.safe_error_class is not None:
            metadata["safe_error_class"] = self.safe_error_class
        return metadata


class DocumentScanner(Protocol):
    def scan(
        self,
        *,
        file_name: str,
        content: bytes,
        document_format: DocumentFormat,
    ) -> ScanResult:
        """Return a safe verdict for an uploaded document before parsing."""


class LimitedConcurrencyDocumentScanner:
    def __init__(
        self,
        scanner: DocumentScanner,
        *,
        max_concurrent_scans: int,
        acquire_timeout_seconds: float,
        scanner_name: str = "limited-document-scanner",
    ) -> None:
        if max_concurrent_scans <= 0:
            raise ValueError("max_concurrent_scans must be positive")
        if acquire_timeout_seconds < 0:
            raise ValueError("acquire_timeout_seconds must be non-negative")

        self._scanner = scanner
        self._semaphore = threading.BoundedSemaphore(max_concurrent_scans)
        self._acquire_timeout_seconds = acquire_timeout_seconds
        self._scanner_name = scanner_name

    def scan(
        self,
        *,
        file_name: str,
        content: bytes,
        document_format: DocumentFormat,
    ) -> ScanResult:
        acquired = self._semaphore.acquire(timeout=self._acquire_timeout_seconds)
        if not acquired:
            return ScanResult(
                verdict=ScannerVerdict.SCANNER_UNAVAILABLE,
                scanner_name=self._scanner_name,
                scanner_version=None,
                signature_database_version=None,
                content_sha256=sha256(content).hexdigest(),
                size_bytes=len(content),
                document_format=document_format,
                safe_error_class="scanner_backpressure",
            )
        try:
            return self._scanner.scan(
                file_name=file_name,
                content=content,
                document_format=document_format,
            )
        finally:
            self._semaphore.release()


class _ClamdTimeoutError(RuntimeError):
    pass


class _ClamdUnavailableError(RuntimeError):
    pass


class _ClamdMalformedResponseError(RuntimeError):
    pass


class ClamdDocumentScanner:
    _INSTREAM_COMMAND = b"zINSTREAM\0"
    _ZERO_LENGTH_CHUNK = b"\0\0\0\0"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        timeout_seconds: float,
        chunk_size: int = 64 * 1024,
        scanner_name: str = "clamd",
        scanner_version: str | None = None,
        signature_database_version: str | None = None,
        response_limit_bytes: int = 4096,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if response_limit_bytes <= 0:
            raise ValueError("response_limit_bytes must be positive")

        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds
        self._chunk_size = chunk_size
        self._scanner_name = scanner_name
        self._scanner_version = scanner_version
        self._signature_database_version = signature_database_version
        self._response_limit_bytes = response_limit_bytes

    def scan(
        self,
        *,
        file_name: str,
        content: bytes,
        document_format: DocumentFormat,
    ) -> ScanResult:
        del file_name

        try:
            response = self._scan_instream(content)
            verdict, safe_error_class = _parse_clamd_response(response)
        except _ClamdTimeoutError:
            verdict = ScannerVerdict.SCANNER_TIMEOUT
            safe_error_class = "scanner_timeout"
        except _ClamdUnavailableError:
            verdict = ScannerVerdict.SCANNER_UNAVAILABLE
            safe_error_class = "scanner_unavailable"
        except _ClamdMalformedResponseError:
            verdict = ScannerVerdict.SCANNER_ERROR
            safe_error_class = "malformed_response"

        return ScanResult(
            verdict=verdict,
            scanner_name=self._scanner_name,
            scanner_version=self._scanner_version,
            signature_database_version=self._signature_database_version,
            content_sha256=sha256(content).hexdigest(),
            size_bytes=len(content),
            document_format=document_format,
            safe_error_class=safe_error_class,
        )

    def _scan_instream(self, content: bytes) -> bytes:
        try:
            with socket.create_connection(
                (self._host, self._port),
                timeout=self._timeout_seconds,
            ) as sock:
                sock.settimeout(self._timeout_seconds)
                sock.sendall(self._INSTREAM_COMMAND)
                for offset in range(0, len(content), self._chunk_size):
                    chunk = content[offset : offset + self._chunk_size]
                    sock.sendall(struct.pack(">I", len(chunk)))
                    sock.sendall(chunk)
                sock.sendall(self._ZERO_LENGTH_CHUNK)
                return self._read_response(sock)
        except TimeoutError as error:
            raise _ClamdTimeoutError from error
        except OSError as error:
            raise _ClamdUnavailableError from error

    def _read_response(self, sock: socket.socket) -> bytes:
        response = bytearray()
        while len(response) < self._response_limit_bytes:
            chunk = sock.recv(min(1024, self._response_limit_bytes - len(response)))
            if not chunk:
                raise _ClamdMalformedResponseError
            response.extend(chunk)
            if b"\0" in chunk:
                return bytes(response)
        raise _ClamdMalformedResponseError


def _parse_clamd_response(response: bytes) -> tuple[ScannerVerdict, str | None]:
    raw_line = response.split(b"\0", 1)[0].strip()
    if not raw_line:
        raise _ClamdMalformedResponseError

    line = raw_line.decode("utf-8", errors="replace").strip()
    normalized = line.upper()
    if normalized == "OK" or normalized.endswith(": OK"):
        return ScannerVerdict.CLEAN, None
    if normalized.endswith(" FOUND"):
        return ScannerVerdict.INFECTED, "infected"
    if "UNSUPPORTED" in normalized:
        return ScannerVerdict.UNSUPPORTED, "unsupported"
    if normalized.endswith(" ERROR") or " ERROR" in normalized:
        return ScannerVerdict.SCANNER_ERROR, "scanner_error"
    raise _ClamdMalformedResponseError


class FakeDocumentScanner:
    def __init__(
        self,
        *,
        default_verdict: ScannerVerdict = ScannerVerdict.CLEAN,
        verdicts_by_file_name: Mapping[str, ScannerVerdict] | None = None,
        scanner_name: str = "fake-document-scanner",
        scanner_version: str | None = "test",
        signature_database_version: str | None = "test-fixtures",
    ) -> None:
        self._default_verdict = default_verdict
        self._verdicts_by_file_name = dict(verdicts_by_file_name or {})
        self._scanner_name = scanner_name
        self._scanner_version = scanner_version
        self._signature_database_version = signature_database_version
        self.calls: list[tuple[str, DocumentFormat, int]] = []

    def scan(
        self,
        *,
        file_name: str,
        content: bytes,
        document_format: DocumentFormat,
    ) -> ScanResult:
        self.calls.append((file_name, document_format, len(content)))
        verdict = self._verdicts_by_file_name.get(file_name, self._default_verdict)
        safe_error_class = None if verdict is ScannerVerdict.CLEAN else verdict.value
        return ScanResult(
            verdict=verdict,
            scanner_name=self._scanner_name,
            scanner_version=self._scanner_version,
            signature_database_version=self._signature_database_version,
            content_sha256=sha256(content).hexdigest(),
            size_bytes=len(content),
            document_format=document_format,
            safe_error_class=safe_error_class,
        )
