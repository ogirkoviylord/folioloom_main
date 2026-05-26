from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class UploadSafetyState(StrEnum):
    RECEIVED = "received"
    QUARANTINED = "quarantined"
    SCAN_STARTED = "scan_started"
    SCAN_CLEAN = "scan_clean"
    SCAN_BLOCKED = "scan_blocked"
    SCAN_FAILED = "scan_failed"
    CONTAINER_STARTED = "container_started"
    CONTAINER_CLEAN = "container_clean"
    CONTAINER_BLOCKED = "container_blocked"
    CONTAINER_FAILED = "container_failed"
    ACCEPTED_SOURCE_CREATED = "accepted_source_created"
    REJECTED = "rejected"
    QUARANTINE_EXPIRED = "quarantine_expired"
    QUARANTINE_DELETED = "quarantine_deleted"


class UploadScanVerdict(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    SCANNER_TIMEOUT = "scanner_timeout"
    SCANNER_UNAVAILABLE = "scanner_unavailable"
    SCANNER_ERROR = "scanner_error"
    UNSUPPORTED = "unsupported"


class UploadContainerVerdict(StrEnum):
    CLEAN = "clean"
    SUSPICIOUS = "suspicious_container"
    FAILED = "container_failed"


class UploadSafetyLedgerError(RuntimeError):
    pass


class UploadSafetyTransitionError(UploadSafetyLedgerError):
    pass


class UploadSafetyLedgerWriteError(UploadSafetyLedgerError):
    pass


@dataclass(frozen=True)
class UploadSafetyMetadata:
    upload_id: str
    user_id: str
    quarantine_object_key: str
    original_file_name: str
    document_format: str
    size_bytes: int
    sha256: str
    scanner_name: str | None = None
    scanner_version: str | None = None
    signature_database_version: str | None = None
    safe_error_class: str | None = None


@dataclass(frozen=True)
class UploadSafetyRecord:
    metadata: UploadSafetyMetadata
    state: UploadSafetyState
    scan_verdict: UploadScanVerdict | None = None
    container_verdict: UploadContainerVerdict | None = None
    accepted_source_object_key: str | None = None

    @property
    def upload_id(self) -> str:
        return self.metadata.upload_id


@dataclass(frozen=True)
class UploadSafetyAccessDecision:
    allowed: bool
    reason: str
    accepted_source_object_key: str | None = None


class InMemoryUploadSafetyLedger:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self._records_by_upload_id: dict[str, list[UploadSafetyRecord]] = {}
        self._fail_writes = fail_writes

    def create_received(self, metadata: UploadSafetyMetadata) -> UploadSafetyRecord:
        if metadata.upload_id in self._records_by_upload_id:
            raise UploadSafetyTransitionError(
                f"Upload safety ledger already exists: {metadata.upload_id}"
            )
        record = UploadSafetyRecord(
            metadata=metadata,
            state=UploadSafetyState.RECEIVED,
        )
        self._append(record)
        return record

    def transition(
        self,
        upload_id: str,
        state: UploadSafetyState,
        *,
        scan_verdict: UploadScanVerdict | None = None,
        container_verdict: UploadContainerVerdict | None = None,
        safe_error_class: str | None = None,
    ) -> UploadSafetyRecord:
        latest = self.latest(upload_id)
        _validate_transition(latest.state, state)
        record = UploadSafetyRecord(
            metadata=_metadata_with_safe_error(latest.metadata, safe_error_class),
            state=state,
            scan_verdict=scan_verdict or _scan_verdict_for_state(state),
            container_verdict=container_verdict or _container_verdict_for_state(state),
            accepted_source_object_key=latest.accepted_source_object_key,
        )
        self._append(record)
        return record

    def create_accepted_source(
        self,
        upload_id: str,
        *,
        accepted_source_object_key: str,
    ) -> UploadSafetyRecord:
        latest = self.latest(upload_id)
        _validate_transition(latest.state, UploadSafetyState.ACCEPTED_SOURCE_CREATED)
        if not accepted_source_object_key:
            raise UploadSafetyTransitionError(
                "Accepted source object key is required for parser access"
            )
        record = UploadSafetyRecord(
            metadata=latest.metadata,
            state=UploadSafetyState.ACCEPTED_SOURCE_CREATED,
            accepted_source_object_key=accepted_source_object_key,
        )
        self._append(record)
        return record

    def latest(self, upload_id: str) -> UploadSafetyRecord:
        records = self._records_by_upload_id.get(upload_id)
        if not records:
            raise UploadSafetyTransitionError(
                f"Upload safety ledger is missing: {upload_id}"
            )
        return records[-1]

    def history(self, upload_id: str) -> tuple[UploadSafetyRecord, ...]:
        return tuple(self._records_by_upload_id.get(upload_id, ()))

    def histories(self) -> tuple[tuple[UploadSafetyRecord, ...], ...]:
        return tuple(tuple(records) for records in self._records_by_upload_id.values())

    def parser_access_decision(self, upload_id: str) -> UploadSafetyAccessDecision:
        return self._accepted_source_decision(upload_id)

    def worker_access_decision(self, upload_id: str) -> UploadSafetyAccessDecision:
        return self._accepted_source_decision(upload_id)

    def upload_id_for_accepted_source(
        self,
        accepted_source_object_key: str,
    ) -> str | None:
        for upload_id, records in self._records_by_upload_id.items():
            if not records:
                continue
            latest = records[-1]
            if (
                latest.state == UploadSafetyState.ACCEPTED_SOURCE_CREATED
                and latest.accepted_source_object_key == accepted_source_object_key
            ):
                return upload_id
        return None

    def _accepted_source_decision(self, upload_id: str) -> UploadSafetyAccessDecision:
        records = self._records_by_upload_id.get(upload_id)
        if not records:
            return UploadSafetyAccessDecision(
                allowed=False,
                reason="ledger_missing",
            )
        latest = records[-1]
        if latest.state != UploadSafetyState.ACCEPTED_SOURCE_CREATED:
            return UploadSafetyAccessDecision(
                allowed=False,
                reason=f"state_{latest.state.value}",
            )
        if not latest.accepted_source_object_key:
            return UploadSafetyAccessDecision(
                allowed=False,
                reason="accepted_source_missing",
            )
        return UploadSafetyAccessDecision(
            allowed=True,
            reason="accepted_source_created",
            accepted_source_object_key=latest.accepted_source_object_key,
        )

    def _append(self, record: UploadSafetyRecord) -> None:
        if self._fail_writes:
            raise UploadSafetyLedgerWriteError(
                "Upload safety ledger write failed; fail closed"
            )
        self._records_by_upload_id.setdefault(record.upload_id, []).append(record)

_VALID_TRANSITIONS: dict[UploadSafetyState, frozenset[UploadSafetyState]] = {
    UploadSafetyState.RECEIVED: frozenset(
        {
            UploadSafetyState.QUARANTINED,
            UploadSafetyState.REJECTED,
        }
    ),
    UploadSafetyState.QUARANTINED: frozenset(
        {
            UploadSafetyState.SCAN_STARTED,
            UploadSafetyState.REJECTED,
            UploadSafetyState.QUARANTINE_EXPIRED,
        }
    ),
    UploadSafetyState.SCAN_STARTED: frozenset(
        {
            UploadSafetyState.SCAN_CLEAN,
            UploadSafetyState.SCAN_BLOCKED,
            UploadSafetyState.SCAN_FAILED,
        }
    ),
    UploadSafetyState.SCAN_CLEAN: frozenset(
        {
            UploadSafetyState.CONTAINER_STARTED,
            UploadSafetyState.REJECTED,
        }
    ),
    UploadSafetyState.CONTAINER_STARTED: frozenset(
        {
            UploadSafetyState.CONTAINER_CLEAN,
            UploadSafetyState.CONTAINER_BLOCKED,
            UploadSafetyState.CONTAINER_FAILED,
        }
    ),
    UploadSafetyState.CONTAINER_CLEAN: frozenset(
        {
            UploadSafetyState.ACCEPTED_SOURCE_CREATED,
            UploadSafetyState.REJECTED,
        }
    ),
    UploadSafetyState.SCAN_BLOCKED: frozenset(
        {
            UploadSafetyState.REJECTED,
            UploadSafetyState.QUARANTINE_EXPIRED,
        }
    ),
    UploadSafetyState.SCAN_FAILED: frozenset(
        {
            UploadSafetyState.REJECTED,
            UploadSafetyState.QUARANTINE_EXPIRED,
        }
    ),
    UploadSafetyState.CONTAINER_BLOCKED: frozenset(
        {
            UploadSafetyState.REJECTED,
            UploadSafetyState.QUARANTINE_EXPIRED,
        }
    ),
    UploadSafetyState.CONTAINER_FAILED: frozenset(
        {
            UploadSafetyState.REJECTED,
            UploadSafetyState.QUARANTINE_EXPIRED,
        }
    ),
    UploadSafetyState.REJECTED: frozenset({UploadSafetyState.QUARANTINE_EXPIRED}),
    UploadSafetyState.QUARANTINE_EXPIRED: frozenset(
        {UploadSafetyState.QUARANTINE_DELETED}
    ),
    UploadSafetyState.QUARANTINE_DELETED: frozenset(),
    UploadSafetyState.ACCEPTED_SOURCE_CREATED: frozenset(),
}


def _validate_transition(
    current_state: UploadSafetyState,
    next_state: UploadSafetyState,
) -> None:
    if next_state not in _VALID_TRANSITIONS[current_state]:
        raise UploadSafetyTransitionError(
            f"Invalid upload safety transition: "
            f"{current_state.value} -> {next_state.value}"
        )


def _scan_verdict_for_state(state: UploadSafetyState) -> UploadScanVerdict | None:
    if state == UploadSafetyState.SCAN_CLEAN:
        return UploadScanVerdict.CLEAN
    if state == UploadSafetyState.SCAN_BLOCKED:
        return UploadScanVerdict.INFECTED
    if state == UploadSafetyState.SCAN_FAILED:
        return UploadScanVerdict.SCANNER_ERROR
    return None


def _container_verdict_for_state(
    state: UploadSafetyState,
) -> UploadContainerVerdict | None:
    if state == UploadSafetyState.CONTAINER_CLEAN:
        return UploadContainerVerdict.CLEAN
    if state == UploadSafetyState.CONTAINER_BLOCKED:
        return UploadContainerVerdict.SUSPICIOUS
    if state == UploadSafetyState.CONTAINER_FAILED:
        return UploadContainerVerdict.FAILED
    return None


def _metadata_with_safe_error(
    metadata: UploadSafetyMetadata,
    safe_error_class: str | None,
) -> UploadSafetyMetadata:
    if safe_error_class is None:
        return metadata
    return replace(metadata, safe_error_class=safe_error_class)
