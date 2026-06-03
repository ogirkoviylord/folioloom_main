from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

_ACTIVE_STATUSES = {"running", "active", "translating", "processing"}
_COMPLETED_FRAGMENT_STATUSES = {
    "cached",
    "complete",
    "completed",
    "ready",
    "success",
    "succeeded",
    "translated",
}
_FAILED_FRAGMENT_STATUSES = {
    "error",
    "failed",
    "failed_retryable",
    "failed_terminal",
    "interrupted",
}


@dataclass(frozen=True)
class TranslationRunSummary:
    job_id: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    order_id: str | None
    user_id: str | None
    file_name: str
    document_kind: str
    source_language: str
    target_language: str
    translator_model: str | None
    result_file_name: str | None
    error_message: str | None
    fragment_count: int
    total_fragment_count: int
    progress_percent: float | None
    eta_seconds: float | None
    current_stage: str
    last_event_at: datetime | None
    total_tokens: int
    elapsed_seconds: float
    run_dir: str
    resource_usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TranslationRunArchive:
    file_name: str
    content: bytes


@dataclass(frozen=True)
class TranslationRunEvent:
    timestamp: datetime | None
    event_type: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class TranslationRunFragmentDetail:
    sequence: int
    status: str
    elapsed_seconds: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    retry_count: int
    cache_hit: bool
    prompt_tier: str | None
    source_text_hash: str | None
    translated_text_hash: str | None
    source_text_chars: int
    translated_text_chars: int
    source_block_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    error_message: str | None


@dataclass(frozen=True)
class TranslationWorkUnitDiagnostic:
    sequence: int
    status: str
    source_block_ids: tuple[str, ...]
    attempt_count: int
    max_attempts: int
    last_error: str | None
    updated_at: datetime | None


@dataclass(frozen=True)
class TranslationRunDetails:
    summary: TranslationRunSummary
    metadata: dict[str, Any]
    totals: dict[str, Any]
    security: dict[str, Any]
    translation_stack: dict[str, Any]
    events: tuple[TranslationRunEvent, ...]
    fragments: tuple[TranslationRunFragmentDetail, ...]
    run_dir: str
    work_unit_diagnostic: TranslationWorkUnitDiagnostic | None = None


def list_translation_run_summaries(
    root: str | Path,
    *,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> tuple[TranslationRunSummary, ...]:
    root_path = Path(root)
    if not root_path.exists():
        return ()
    wanted_status = _normalize_filter(status)
    from_date = _parse_date(date_from)
    to_date = _parse_date(date_to)
    current_time = _aware_utc(now or datetime.now(UTC))
    rows = []
    for run_json in root_path.glob("*/run.json"):
        summary = _read_run_summary(run_json, now=current_time)
        if summary is None:
            continue
        if wanted_status and summary.status != wanted_status:
            continue
        run_date = summary.started_at.date() if summary.started_at else None
        if from_date and (run_date is None or run_date < from_date):
            continue
        if to_date and (run_date is None or run_date > to_date):
            continue
        rows.append(summary)
    rows.sort(
        key=lambda row: row.started_at or datetime.min,
        reverse=True,
    )
    return tuple(rows[: max(1, int(limit))])


def get_translation_run_details(
    root: str | Path,
    run_id: str,
) -> TranslationRunDetails | None:
    run_dir = _resolve_run_dir(root, run_id)
    if run_dir is None:
        return None
    run_json = run_dir / "run.json"
    summary = _read_run_summary(run_json)
    if summary is None:
        return None
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return TranslationRunDetails(
        summary=summary,
        metadata=_run_metadata(data),
        totals=_safe_dict(data.get("totals")),
        security=_safe_dict(data.get("security")),
        translation_stack=_safe_dict(data.get("translation_stack")),
        events=_read_events(run_dir / "events.jsonl"),
        fragments=_read_fragments(run_dir / "fragments"),
        run_dir=str(run_dir),
    )


def build_translation_run_archive(
    root: str | Path,
    run_id: str,
) -> TranslationRunArchive | None:
    run_dir = _resolve_run_dir(root, run_id)
    if run_dir is None:
        return None
    archive_name = f"{run_dir.name}.zip"
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(run_dir).as_posix())
    return TranslationRunArchive(file_name=archive_name, content=buffer.getvalue())


def build_effective_translation_run_archive(
    root: str | Path,
    run_id: str,
    *,
    details: TranslationRunDetails,
) -> TranslationRunArchive | None:
    run_dir = _resolve_run_dir(root, run_id)
    if run_dir is None:
        return None
    archive_name = f"{run_dir.name}.zip"
    effective = _effective_run_payload(details)
    work_units = _work_units_payload(details)
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file() and path.name != "summary.md":
                archive.write(path, path.relative_to(run_dir).as_posix())
        archive.writestr(
            "effective_run.json",
            _json_dumps(effective),
        )
        archive.writestr(
            "work_units.json",
            _json_dumps(work_units),
        )
        archive.writestr(
            "summary.md",
            _render_effective_summary(details, work_units=work_units),
        )
        archive.writestr(
            "README.md",
            "\n".join(
                [
                    "# Translation Export",
                    "",
                    "`run.json` is the sanitized lifecycle log captured during the run.",
                    "`effective_run.json` is the authoritative export snapshot built",
                    "from the lifecycle log plus persistent scheduler/work-unit state.",
                    "`work_units.json` contains metadata-only work-unit status counts",
                    "and the work unit needing attention when one is available.",
                    "",
                    "This archive intentionally excludes raw source text, translated",
                    "text, provider prompts, API keys, and provider internals.",
                    "",
                ]
            ),
        )
    return TranslationRunArchive(file_name=archive_name, content=buffer.getvalue())


def _resolve_run_dir(root: str | Path, run_id: str) -> Path | None:
    if not run_id or "/" in run_id or "\\" in run_id:
        return None
    root_path = Path(root).resolve()
    candidate = (root_path / run_id).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError:
        return None
    if not candidate.is_dir() or not (candidate / "run.json").is_file():
        return None
    return candidate


def _effective_run_payload(details: TranslationRunDetails) -> dict[str, Any]:
    return {
        "schema_version": "translation-effective-run-v1",
        "summary": _json_safe(details.summary),
        "metadata": _json_safe(details.metadata),
        "totals": _json_safe(details.totals),
        "security": _json_safe(details.security),
        "translation_stack": _json_safe(details.translation_stack),
        "work_unit_diagnostic": _json_safe(details.work_unit_diagnostic),
    }


def _work_units_payload(details: TranslationRunDetails) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for fragment in details.fragments:
        counts[fragment.status] = counts.get(fragment.status, 0) + 1
    return {
        "schema_version": "translation-work-units-v1",
        "counts_by_status": counts,
        "total_units": len(details.fragments),
        "completed_units": sum(
            count
            for status, count in counts.items()
            if status in _COMPLETED_FRAGMENT_STATUSES
        ),
        "failed_units": sum(
            count
            for status, count in counts.items()
            if status in _FAILED_FRAGMENT_STATUSES
        ),
        "attention_unit": _json_safe(details.work_unit_diagnostic),
        "units": tuple(_json_safe(fragment) for fragment in details.fragments),
    }


def _render_effective_summary(
    details: TranslationRunDetails,
    *,
    work_units: dict[str, Any],
) -> str:
    summary = details.summary
    diagnostic = details.work_unit_diagnostic
    lines = [
        "# Translation Run",
        "",
        f"- Job: `{summary.job_id}`",
        f"- File: `{summary.file_name}`",
        f"- Format: `{summary.document_kind}`",
        f"- Direction: `{summary.source_language}` -> `{summary.target_language}`",
        f"- Status: `{summary.status}`",
        f"- Progress: `{summary.fragment_count}/{summary.total_fragment_count}`",
        f"- Tokens: `{summary.total_tokens}`",
        "",
        "## Effective Scheduler Snapshot",
        "",
        f"- total_units: `{work_units['total_units']}`",
        f"- completed_units: `{work_units['completed_units']}`",
        f"- failed_units: `{work_units['failed_units']}`",
        f"- counts_by_status: `{json.dumps(work_units['counts_by_status'], sort_keys=True)}`",
    ]
    if diagnostic is not None:
        lines.extend(
            [
                "",
                "## Work Unit Needing Attention",
                "",
                f"- sequence: `{diagnostic.sequence}`",
                f"- status: `{diagnostic.status}`",
                f"- attempts: `{diagnostic.attempt_count}/{diagnostic.max_attempts}`",
                f"- last_error: `{diagnostic.last_error or 'n/a'}`",
            ]
        )
    if summary.error_message:
        lines.extend(["", "## Error", "", summary.error_message])
    lines.append("")
    return "\n".join(lines)


def _json_dumps(payload: Any) -> str:
    return json.dumps(
        _json_safe(payload),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _read_run_summary(
    run_json: Path,
    *,
    now: datetime | None = None,
) -> TranslationRunSummary | None:
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    totals = data.get("totals")
    if not isinstance(totals, dict):
        totals = {}
    completed_fragments = _int(data.get("fragment_count"))
    events_path = run_json.parent / "events.jsonl"
    total_fragments = _total_fragment_count(
        data,
        completed_fragments=completed_fragments,
        events_path=events_path,
    )
    last_event_at, current_stage = _latest_event_state(events_path)
    elapsed_seconds = _float(totals.get("elapsed_seconds"))
    status = _string(data.get("status"), fallback="unknown").lower()
    started_at = _parse_datetime(data.get("started_at"))
    return TranslationRunSummary(
        job_id=_string(data.get("job_id"), fallback=run_json.parent.name),
        status=status,
        started_at=started_at,
        finished_at=_parse_datetime(data.get("finished_at")),
        order_id=_optional_string(data.get("order_id")),
        user_id=_optional_string(data.get("user_id")),
        file_name=_string(data.get("file_name"), fallback="unknown"),
        document_kind=_string(data.get("document_kind"), fallback="unknown"),
        source_language=_string(data.get("source_language"), fallback="unknown"),
        target_language=_string(data.get("target_language"), fallback="unknown"),
        translator_model=_optional_string(data.get("translator_model")),
        result_file_name=_optional_string(data.get("result_file_name")),
        error_message=_truncate(_optional_string(data.get("error_message"))),
        fragment_count=completed_fragments,
        total_fragment_count=total_fragments,
        progress_percent=_progress_percent(completed_fragments, total_fragments),
        eta_seconds=_eta_seconds(
            status=status,
            completed_fragments=completed_fragments,
            total_fragments=total_fragments,
            elapsed_seconds=elapsed_seconds,
            started_at=started_at,
            now=now,
        ),
        current_stage=current_stage or status,
        last_event_at=last_event_at,
        total_tokens=_int(totals.get("total_tokens")),
        elapsed_seconds=elapsed_seconds,
        run_dir=str(run_json.parent),
    )


def _run_metadata(data: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "job_id",
        "order_id",
        "user_id",
        "file_name",
        "document_kind",
        "source_language",
        "target_language",
        "detected_source_language",
        "interface_language",
        "total_fragment_count",
        "translator_model",
        "prompt_version",
        "adapter_version",
        "translation_policy",
        "translation_quality_route",
        "result_file_name",
        "error_message",
        "started_at",
        "finished_at",
    )
    return {key: _safe_value(data.get(key)) for key in keys if key in data}


def _read_events(events_path: Path) -> tuple[TranslationRunEvent, ...]:
    if not events_path.exists():
        return ()
    events: list[TranslationRunEvent] = []
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        events.append(
            TranslationRunEvent(
                timestamp=_parse_datetime(data.get("timestamp")),
                event_type=_string(data.get("event_type"), fallback="unknown"),
                payload=_safe_dict(data.get("payload")),
            )
        )
    return tuple(events)


def _total_fragment_count(
    data: dict[str, Any],
    *,
    completed_fragments: int,
    events_path: Path,
) -> int:
    explicit_total = _int(data.get("total_fragment_count"))
    event_total = _event_fragment_count(events_path)
    return max(completed_fragments, explicit_total, event_total)


def _event_fragment_count(events_path: Path) -> int:
    if not events_path.exists():
        return 0
    total = 0
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        payload = data.get("payload")
        if not isinstance(payload, dict):
            continue
        total = max(
            total,
            _int(payload.get("fragment_count")),
            _int(payload.get("total_fragments")),
            _int(payload.get("total_units")),
        )
    return total


def _latest_event_state(events_path: Path) -> tuple[datetime | None, str | None]:
    if not events_path.exists():
        return None, None
    latest_at: datetime | None = None
    latest_type: str | None = None
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        event_at = _parse_datetime(data.get("timestamp"))
        event_type = _optional_string(data.get("event_type"))
        if event_type is None:
            continue
        if event_at is None or latest_at is None or event_at >= latest_at:
            latest_at = event_at
            latest_type = event_type
    return latest_at, latest_type


def _progress_percent(
    completed_fragments: int,
    total_fragments: int,
) -> float | None:
    if total_fragments <= 0:
        return None
    return round(min(100.0, completed_fragments / total_fragments * 100), 1)


def _eta_seconds(
    *,
    status: str,
    completed_fragments: int,
    total_fragments: int,
    elapsed_seconds: float,
    started_at: datetime | None,
    now: datetime | None,
) -> float | None:
    if total_fragments <= 0:
        return None
    if completed_fragments >= total_fragments:
        return 0.0
    if status not in _ACTIVE_STATUSES:
        return None
    if completed_fragments <= 0:
        return None
    elapsed_for_eta = elapsed_seconds
    if started_at is not None:
        current_time = _aware_utc(now or datetime.now(UTC))
        elapsed_for_eta = max(
            elapsed_for_eta,
            (_aware_utc(current_time) - _aware_utc(started_at)).total_seconds(),
        )
    if elapsed_for_eta <= 0:
        return None
    average_seconds = elapsed_for_eta / completed_fragments
    return round(average_seconds * (total_fragments - completed_fragments), 1)


def _read_fragments(fragments_dir: Path) -> tuple[TranslationRunFragmentDetail, ...]:
    return tuple(
        _fragment_detail(data)
        for data in _read_fragment_records(fragments_dir)
    )


def _read_fragment_records(fragments_dir: Path) -> tuple[dict[str, Any], ...]:
    if not fragments_dir.exists():
        return ()
    fragments: list[dict[str, Any]] = []
    for path in sorted(fragments_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        fragments.append(data)
    return tuple(fragments)


def _fragment_detail(data: dict[str, Any]) -> TranslationRunFragmentDetail:
    return TranslationRunFragmentDetail(
        sequence=_int(data.get("sequence")),
        status=_string(data.get("status"), fallback="unknown"),
        elapsed_seconds=_float(data.get("elapsed_seconds")),
        prompt_tokens=_int(data.get("prompt_tokens")),
        completion_tokens=_int(data.get("completion_tokens")),
        total_tokens=_int(data.get("total_tokens")),
        prompt_cache_hit_tokens=_int(data.get("prompt_cache_hit_tokens")),
        prompt_cache_miss_tokens=_int(data.get("prompt_cache_miss_tokens")),
        retry_count=_int(data.get("retry_count")),
        cache_hit=bool(data.get("cache_hit")),
        prompt_tier=_optional_string(data.get("prompt_tier")),
        source_text_hash=_optional_string(data.get("source_text_hash")),
        translated_text_hash=_optional_string(data.get("translated_text_hash")),
        source_text_chars=_int(data.get("source_text_chars")),
        translated_text_chars=_int(data.get("translated_text_chars")),
        source_block_ids=tuple(
            str(item)
            for item in data.get("source_block_ids", ())
            if str(item).strip()
        ),
        warnings=tuple(str(item) for item in data.get("warnings", ()) if str(item)),
        error_message=_safe_error_text(data.get("error_message")),
    )


def _safe_error_text(value: Any) -> str | None:
    text = _optional_string(value)
    if text is None:
        return None
    return "[redacted]"


def _safe_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        safe[key_text] = _safe_value(item, key=key_text)
    return safe


def _safe_value(value: Any, *, key: str = "") -> Any:
    lowered = key.lower()
    if any(
        marker in lowered
        for marker in (
            "source_text",
            "translated_text",
            "plaintext",
            "api_key",
            "secret",
            "access_token",
            "refresh_token",
            "bot_token",
            "authorization",
        )
    ):
        return "[redacted]"
    if lowered in {"error", "error_message", "last_error", "last_error_excerpt"}:
        return _safe_error_text(value)
    if isinstance(value, dict):
        return {
            str(child_key): _safe_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_safe_value(item) for item in value)
    return value


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _normalize_filter(value: str | None) -> str | None:
    if value in {None, "", "all"}:
        return None
    return value.strip().lower()


def _string(value: Any, *, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _truncate(value: str | None, *, limit: int = 180) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return f"{value[: limit - 1]}..."
