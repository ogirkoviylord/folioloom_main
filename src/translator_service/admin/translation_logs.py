from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


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
