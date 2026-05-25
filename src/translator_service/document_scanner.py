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
