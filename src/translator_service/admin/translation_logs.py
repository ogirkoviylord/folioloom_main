from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile


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
    total_tokens: int
    elapsed_seconds: float
    run_dir: str


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
class TranslationRunDetails:
    summary: TranslationRunSummary
    metadata: dict[str, Any]
    totals: dict[str, Any]
    security: dict[str, Any]
    translation_stack: dict[str, Any]
    events: tuple[TranslationRunEvent, ...]
    fragments: tuple[TranslationRunFragmentDetail, ...]
    run_dir: str


def list_translation_run_summaries(
    root: str | Path,
    *,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> tuple[TranslationRunSummary, ...]:
    root_path = Path(root)
    if not root_path.exists():
        return ()
    wanted_status = _normalize_filter(status)
    from_date = _parse_date(date_from)
    to_date = _parse_date(date_to)
    rows = []
    for run_json in root_path.glob("*/run.json"):
        summary = _read_run_summary(run_json)
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


def _read_run_summary(run_json: Path) -> TranslationRunSummary | None:
    try:
        data = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    totals = data.get("totals")
    if not isinstance(totals, dict):
        totals = {}
    return TranslationRunSummary(
        job_id=_string(data.get("job_id"), fallback=run_json.parent.name),
        status=_string(data.get("status"), fallback="unknown").lower(),
        started_at=_parse_datetime(data.get("started_at")),
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
        fragment_count=_int(data.get("fragment_count")),
        total_tokens=_int(totals.get("total_tokens")),
        elapsed_seconds=_float(totals.get("elapsed_seconds")),
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


def _read_fragments(fragments_dir: Path) -> tuple[TranslationRunFragmentDetail, ...]:
    if not fragments_dir.exists():
        return ()
    fragments: list[TranslationRunFragmentDetail] = []
    for path in sorted(fragments_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        fragments.append(_fragment_detail(data))
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
        error_message=_truncate(_optional_string(data.get("error_message"))),
    )


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
