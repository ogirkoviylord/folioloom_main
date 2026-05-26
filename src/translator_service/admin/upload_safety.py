from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from translator_service.upload_safety_ledger import (
    InMemoryUploadSafetyLedger,
    UploadSafetyRecord,
    UploadSafetyState,
)
from translator_service.user_activity import UserActivityEvent

UPLOAD_SAFETY_ACTIVITY_EVENT_TYPE = "security.upload_safety.summary"


@dataclass(frozen=True)
class UploadSafetyTimelineEvent:
    timestamp: datetime | None
    state: str
    reason_code: str | None = None


@dataclass(frozen=True)
class UploadSafetyAdminRecord:
    upload_id: str
    created_at: datetime
    updated_at: datetime
    channel_user_id: str
    declared_format: str
    detected_format: str
    size_bytes: int
    av_verdict: str
    container_verdict: str
    final_action: str
    reason_code: str
    parser_access_granted: bool
    worker_access_granted: bool
    timeline: tuple[UploadSafetyTimelineEvent, ...]
    scanner_health: str = "unknown"
    scanner_name: str | None = None
    scanner_version: str | None = None
    signature_database_version: str | None = None
    signature_database_age_seconds: int | None = None
    sanitized_original_filename: str | None = None
    short_hash: str | None = None
    job_id: str | None = None


@dataclass(frozen=True)
class UploadSafetyFilters:
    date_from: str | None = None
    date_to: str | None = None
    final_action: str | None = None
    av_verdict: str | None = None
    container_verdict: str | None = None
    reason_code: str | None = None
    channel_user_id: str | None = None
    declared_format: str | None = None


@dataclass(frozen=True)
class UploadSafetySummary:
    scanner_health: str
    signature_database_age_seconds: int | None
    scanned_count: int
    accepted_count: int
    blocked_count: int
    failed_closed_count: int
    access_violation_count: int
    top_reason_codes: tuple[tuple[str, int], ...]


class UploadSafetyAdminReadModel:
    def __init__(
        self,
        records: tuple[UploadSafetyAdminRecord, ...] = (),
    ) -> None:
        self._records = tuple(
            sorted(records, key=lambda record: record.created_at, reverse=True)
        )

    def list_records(
        self,
        filters: UploadSafetyFilters | None = None,
    ) -> tuple[UploadSafetyAdminRecord, ...]:
        filters = filters or UploadSafetyFilters()
        return tuple(
            record for record in self._records if _matches_filters(record, filters)
        )

    def get_record(self, upload_id: str) -> UploadSafetyAdminRecord | None:
        for record in self._records:
            if record.upload_id == upload_id:
                return record
        return None

    def summarize(
        self,
        filters: UploadSafetyFilters | None = None,
    ) -> UploadSafetySummary:
        records = self.list_records(filters)
        top_reason_codes = Counter(
            record.reason_code for record in records if record.reason_code
        ).most_common(5)
        return UploadSafetySummary(
            scanner_health=_scanner_health(records),
            signature_database_age_seconds=_signature_database_age_seconds(records),
            scanned_count=sum(
                1 for record in records if record.av_verdict not in {"", "not_checked"}
            ),
            accepted_count=sum(
                1 for record in records if record.final_action == "accepted"
            ),
            blocked_count=sum(
                1 for record in records if record.final_action == "blocked"
            ),
            failed_closed_count=sum(
                1 for record in records if record.final_action == "failed_closed"
            ),
            access_violation_count=sum(
                1
                for record in records
                if record.parser_access_granted
                and record.final_action != "accepted"
                or record.worker_access_granted
                and record.final_action != "accepted"
            ),
            top_reason_codes=tuple(top_reason_codes),
        )


def _matches_filters(
    record: UploadSafetyAdminRecord,
    filters: UploadSafetyFilters,
) -> bool:
    if filters.date_from and record.created_at.date().isoformat() < filters.date_from:
        return False
    if filters.date_to and record.created_at.date().isoformat() > filters.date_to:
        return False
    if filters.final_action and record.final_action != filters.final_action:
        return False
    if filters.av_verdict and record.av_verdict != filters.av_verdict:
        return False
    if (
        filters.container_verdict
        and record.container_verdict != filters.container_verdict
    ):
        return False
    if filters.reason_code and record.reason_code != filters.reason_code:
        return False
    if filters.channel_user_id and record.channel_user_id != filters.channel_user_id:
        return False
    if filters.declared_format and record.declared_format != filters.declared_format:
        return False
    return True


def _scanner_health(records: tuple[UploadSafetyAdminRecord, ...]) -> str:
    for record in records:
        if record.scanner_health and record.scanner_health != "unknown":
            return record.scanner_health
    return "unknown"


def _signature_database_age_seconds(
    records: tuple[UploadSafetyAdminRecord, ...],
) -> int | None:
    ages = [
        record.signature_database_age_seconds
        for record in records
        if record.signature_database_age_seconds is not None
    ]
    if not ages:
        return None
    return min(ages)


def empty_upload_safety_read_model() -> UploadSafetyAdminReadModel:
    return UploadSafetyAdminReadModel(())


def upload_safety_read_model_from_ledger(
    ledger: InMemoryUploadSafetyLedger,
    *,
    observed_at: datetime,
) -> UploadSafetyAdminReadModel:
    records = tuple(
        _admin_record_from_ledger_history(history, observed_at=observed_at)
        for history in ledger.histories()
        if history
    )
    return UploadSafetyAdminReadModel(records)


def upload_safety_read_model_from_activity_events(
    events: tuple[UserActivityEvent, ...],
) -> UploadSafetyAdminReadModel:
    records = tuple(
        record
        for record in (
            _admin_record_from_activity_event(event)
            for event in events
            if event.event_type == UPLOAD_SAFETY_ACTIVITY_EVENT_TYPE
        )
        if record is not None
    )
    return UploadSafetyAdminReadModel(records)


def _admin_record_from_activity_event(
    event: UserActivityEvent,
) -> UploadSafetyAdminRecord | None:
    metadata = event.metadata
    upload_id = _string(metadata, "upload_id") or event.target_id
    if not upload_id:
        return None
    timeline = tuple(
        _timeline_event_from_metadata(item, fallback_timestamp=event.created_at)
        for item in _list(metadata, "timeline")
    )
    return UploadSafetyAdminRecord(
        upload_id=upload_id,
        created_at=event.created_at,
        updated_at=event.created_at,
        channel_user_id=event.actor_id or event.channel_user_id or "unknown",
        declared_format=_string(metadata, "declared_format") or "unknown",
        detected_format=_string(metadata, "detected_format") or "unknown",
        size_bytes=_int(metadata, "size_bytes"),
        av_verdict=_string(metadata, "av_verdict") or "not_checked",
        container_verdict=_string(metadata, "container_verdict") or "not_checked",
        final_action=_string(metadata, "final_action") or event.action,
        reason_code=_string(metadata, "reason_code") or event.action,
        parser_access_granted=_bool(metadata, "parser_access_granted"),
        worker_access_granted=_bool(metadata, "worker_access_granted"),
        timeline=timeline,
        scanner_health=_string(metadata, "scanner_health") or "unknown",
        scanner_name=_string(metadata, "scanner_name"),
        scanner_version=_string(metadata, "scanner_version"),
        signature_database_version=_string(metadata, "signature_database_version"),
        signature_database_age_seconds=_optional_int(
            metadata,
            "signature_database_age_seconds",
        ),
        sanitized_original_filename=_string(metadata, "sanitized_original_filename"),
        short_hash=_string(metadata, "short_hash"),
        job_id=event.job_id,
    )


def _timeline_event_from_metadata(
    value: object,
    *,
    fallback_timestamp: datetime,
) -> UploadSafetyTimelineEvent:
    if not isinstance(value, dict):
        return UploadSafetyTimelineEvent(fallback_timestamp, "unknown")
    return UploadSafetyTimelineEvent(
        fallback_timestamp,
        _string(value, "state") or "unknown",
        _string(value, "reason_code"),
    )


def _admin_record_from_ledger_history(
    history: tuple[UploadSafetyRecord, ...],
    *,
    observed_at: datetime,
) -> UploadSafetyAdminRecord:
    latest = history[-1]
    scan_verdict = _latest_value(history, "scan_verdict") or "not_checked"
    container_verdict = _latest_value(history, "container_verdict") or "not_checked"
    parser_access = latest.state == UploadSafetyState.ACCEPTED_SOURCE_CREATED
    worker_access = latest.state == UploadSafetyState.ACCEPTED_SOURCE_CREATED
    final_action = _final_action(history)
    return UploadSafetyAdminRecord(
        upload_id=latest.upload_id,
        created_at=observed_at,
        updated_at=observed_at,
        channel_user_id=latest.metadata.user_id,
        declared_format=latest.metadata.document_format,
        detected_format=latest.metadata.document_format,
        size_bytes=latest.metadata.size_bytes,
        av_verdict=scan_verdict,
        container_verdict=container_verdict,
        final_action=final_action,
        reason_code=_reason_code(history, latest),
        parser_access_granted=parser_access,
        worker_access_granted=worker_access,
        timeline=tuple(
            UploadSafetyTimelineEvent(
                timestamp=observed_at,
                state=record.state.value,
                reason_code=record.metadata.safe_error_class,
            )
            for record in history
        ),
        scanner_name=latest.metadata.scanner_name,
        scanner_version=latest.metadata.scanner_version,
        signature_database_version=latest.metadata.signature_database_version,
        short_hash=_short_hash(latest.metadata.sha256),
    )


def _latest_value(
    history: tuple[UploadSafetyRecord, ...],
    field_name: str,
) -> str | None:
    for record in reversed(history):
        value = getattr(record, field_name)
        if value is not None:
            return value.value
    return None


def _final_action(history: tuple[UploadSafetyRecord, ...]) -> str:
    states = tuple(record.state for record in history)
    latest = states[-1]
    if latest == UploadSafetyState.ACCEPTED_SOURCE_CREATED:
        return "accepted"
    if any(
        state in {
            UploadSafetyState.SCAN_FAILED,
            UploadSafetyState.CONTAINER_FAILED,
        }
        for state in states
    ):
        return "failed_closed"
    if any(
        state in {
            UploadSafetyState.SCAN_BLOCKED,
            UploadSafetyState.CONTAINER_BLOCKED,
        }
        for state in states
    ):
        return "blocked"
    if latest in {
        UploadSafetyState.QUARANTINE_EXPIRED,
        UploadSafetyState.QUARANTINE_DELETED,
    }:
        return "deleted_by_ttl"
    if latest == UploadSafetyState.REJECTED:
        return "rejected"
    return "quarantined"


def _reason_code(
    history: tuple[UploadSafetyRecord, ...],
    latest: UploadSafetyRecord,
) -> str:
    if latest.metadata.safe_error_class:
        return latest.metadata.safe_error_class
    for state in reversed(tuple(record.state for record in history)):
        if state in {
            UploadSafetyState.SCAN_FAILED,
            UploadSafetyState.CONTAINER_FAILED,
            UploadSafetyState.SCAN_BLOCKED,
            UploadSafetyState.CONTAINER_BLOCKED,
        }:
            return state.value
    return latest.state.value


def _short_hash(value: str) -> str:
    return value[:8] if len(value) >= 8 else "n/a"


def _string(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None


def _list(metadata: dict[str, object], key: str) -> tuple[object, ...]:
    value = metadata.get(key)
    return tuple(value) if isinstance(value, list) else ()


def _bool(metadata: dict[str, object], key: str) -> bool:
    return metadata.get(key) is True


def _int(metadata: dict[str, object], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _optional_int(metadata: dict[str, object], key: str) -> int | None:
    value = metadata.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
