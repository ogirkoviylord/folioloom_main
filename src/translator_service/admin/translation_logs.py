from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
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
READER_REVIEW_MARKS_FILE = "reader_review_marks.json"
_READER_REVIEW_MARKS_VERSION = 1
_READER_REVIEW_ALLOWED_MARKS = frozenset({"needs_review", "ok", "ignore"})
GLOSSARY_RUNTIME_DIAGNOSTICS_FILE = "glossary_runtime_diagnostics.json"
_GLOSSARY_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION = (
    "glossary-runtime-archive-diagnostics-v1"
)
_GLOSSARY_RUNTIME_EVENT_TYPE = "glossary_runtime_adapter"
_GLOSSARY_CONTEXT_RE = re.compile(
    r"<glossary_context\b.*?</glossary_context>",
    re.DOTALL,
)
_SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bot_token",
    "dsn",
    "password",
    "refresh_token",
    "secret",
    "token",
)
_SECRET_DIAGNOSTIC_KEYS = frozenset(
    {
        "secret_exclusion_policy",
        "secret_material_rejected",
        "secret_redaction_count",
        "secret_redactions",
    }
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?m)^[A-Z_][A-Z0-9_]{2,}=[^\s].+$"),
)
_RAW_GLOSSARY_EVENT_KEYS = frozenset(
    {
        "bounded_source_excerpt",
        "prompt",
        "prompt_body",
        "provider_request",
        "provider_response",
        "raw_prompt",
        "raw_response",
        "raw_source",
        "raw_source_text",
        "request_body",
        "response_body",
        "source_text",
        "source_texts",
        "target_text",
        "translated_text",
        "translation_text",
    }
)


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
class TranslationRunDiagnosticFile:
    role: str
    object_kind: str
    object_key: str
    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    content: bytes


@dataclass(frozen=True)
class ReaderReviewMark:
    sequence: int
    mark: str
    source_text: str
    translated_text: str
    status: str
    source_block_ids: tuple[str, ...]
    updated_at: datetime | None


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
class TranslationProviderFailureAttempt:
    attempt_number: int
    status: str
    failure_category: str
    provider_id: str
    http_status_bucket: str | None = None
    retry_after_seconds: int | None = None
    latency_ms: float | None = None
    terminal_reason: str | None = None
    channel_fingerprint: str | None = None
    channel_health: str | None = None
    circuit_state: str | None = None


@dataclass(frozen=True)
class TranslationWorkUnitDiagnostic:
    sequence: int
    status: str
    source_block_ids: tuple[str, ...]
    attempt_count: int
    max_attempts: int
    last_error: str | None
    updated_at: datetime | None
    provider_attempts: tuple[TranslationProviderFailureAttempt, ...] = ()


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
            if path.is_file() and path.name != READER_REVIEW_MARKS_FILE:
                archive.write(path, path.relative_to(run_dir).as_posix())
    return TranslationRunArchive(file_name=archive_name, content=buffer.getvalue())


def build_effective_translation_run_archive(
    root: str | Path,
    run_id: str,
    *,
    details: TranslationRunDetails,
    raw_text_diagnostics: dict[str, Any] | None = None,
    raw_diagnostic_files: tuple[TranslationRunDiagnosticFile, ...] = (),
) -> TranslationRunArchive | None:
    run_dir = _resolve_run_dir(root, run_id)
    if run_dir is None:
        return None
    archive_name = f"{run_dir.name}.zip"
    effective = _effective_run_payload(details)
    work_units = _work_units_payload(details)
    glossary_runtime_diagnostics = _glossary_runtime_diagnostics_payload(
        details,
        run_dir=run_dir,
        raw_text_diagnostics_present=raw_text_diagnostics is not None,
    )
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as archive:
        written_paths: set[str] = set()
        for path in sorted(run_dir.rglob("*")):
            if path.is_file() and path.name not in {
                "summary.md",
                GLOSSARY_RUNTIME_DIAGNOSTICS_FILE,
                READER_REVIEW_MARKS_FILE,
            }:
                member_path = path.relative_to(run_dir).as_posix()
                archive.write(path, member_path)
                written_paths.add(member_path)
        archive.writestr(
            "effective_run.json",
            _json_dumps(effective),
        )
        written_paths.add("effective_run.json")
        archive.writestr(
            "work_units.json",
            _json_dumps(work_units),
        )
        written_paths.add("work_units.json")
        if raw_text_diagnostics is not None:
            archive.writestr(
                "raw_text_diagnostics.json",
                _json_dumps(raw_text_diagnostics),
            )
            written_paths.add("raw_text_diagnostics.json")
        if glossary_runtime_diagnostics is not None:
            archive.writestr(
                GLOSSARY_RUNTIME_DIAGNOSTICS_FILE,
                _json_dumps(glossary_runtime_diagnostics),
            )
            written_paths.add(GLOSSARY_RUNTIME_DIAGNOSTICS_FILE)
        diagnostic_file_entries = _write_diagnostic_files(
            archive,
            raw_diagnostic_files,
            written_paths=written_paths,
        )
        if diagnostic_file_entries:
            archive.writestr(
                "diagnostic_files/manifest.json",
                _json_dumps(_diagnostic_files_manifest(diagnostic_file_entries)),
            )
            written_paths.add("diagnostic_files/manifest.json")
        archive.writestr(
            "summary.md",
            _render_effective_summary(details, work_units=work_units),
        )
        written_paths.add("summary.md")
        archive.writestr(
            "README.md",
            "\n".join(
                [
                    "# Translation Export",
                    "",
                    "`run.json` is the sanitized lifecycle log captured during",
                    "the run.",
                    "`effective_run.json` is the authoritative export snapshot built",
                    "from the lifecycle log plus persistent scheduler/work-unit state.",
                    "`work_units.json` contains metadata-only work-unit status counts",
                    "and the work unit needing attention when one is available.",
                    "`raw_text_diagnostics.json`, when present, is an owner-only",
                    "full diagnostic snapshot that intentionally contains raw",
                    "source text, translated text, retry attempts, and safe",
                    "provider failure metadata for the run.",
                    "`provider_io_diagnostics.jsonl`, when present, is an",
                    "owner-only provider IO diagnostic log that may contain exact",
                    "provider request JSON bodies, prompt/source batch text, and",
                    "raw provider response bodies.",
                    f"`{GLOSSARY_RUNTIME_DIAGNOSTICS_FILE}`, when present, is an",
                    "owner-only glossary runtime diagnostic sidecar for",
                    "battle-test analysis. It may contain rendered glossary",
                    "prompt context extracted from provider IO, selected-entry",
                    "metadata, adapter/preflight/fallback decisions, cache policy",
                    "metadata and compliance diagnostics.",
                    "`diagnostic_files/`, when present, contains owner-only",
                    "copies of the original uploaded file and the final or partial",
                    "translated result file from object storage.",
                    "",
                    "This archive intentionally excludes provider Authorization",
                    "headers and API keys.",
                    "Treat archives with raw diagnostic files as sensitive",
                    "user-document, translated-output and provider-IO diagnostic data.",
                    "",
                ]
            ),
        )
    return TranslationRunArchive(file_name=archive_name, content=buffer.getvalue())


def load_reader_review_marks(
    root: str | Path,
    run_id: str,
) -> tuple[ReaderReviewMark, ...]:
    run_dir = _resolve_run_dir(root, run_id)
    if run_dir is None:
        return ()
    document = _read_reader_review_marks_document(
        run_dir / READER_REVIEW_MARKS_FILE
    )
    review_marks = []
    for sequence_key, record in sorted(
        document.get("marks", {}).items(),
        key=lambda item: _int(item[0]),
    ):
        review_mark = _reader_review_mark_from_record(sequence_key, record)
        if review_mark is not None:
            review_marks.append(review_mark)
    return tuple(review_marks)


def reader_review_mark_map(
    root: str | Path,
    run_id: str,
) -> dict[str, str]:
    return {
        str(mark.sequence): mark.mark
        for mark in load_reader_review_marks(root, run_id)
    }


def save_reader_review_mark(
    root: str | Path,
    run_id: str,
    *,
    sequence: int,
    mark: str,
    source_text: str,
    translated_text: str,
    status: str,
    source_block_ids: tuple[str, ...],
    now: datetime | None = None,
) -> tuple[ReaderReviewMark, ...] | None:
    run_dir = _resolve_run_dir(root, run_id)
    if run_dir is None:
        return None
    sequence = _int(sequence)
    if sequence <= 0:
        return None
    marks_path = run_dir / READER_REVIEW_MARKS_FILE
    document = _read_reader_review_marks_document(marks_path)
    marks = document.setdefault("marks", {})
    if not isinstance(marks, dict):
        marks = {}
        document["marks"] = marks
    sequence_key = str(sequence)
    if mark == "clear":
        marks.pop(sequence_key, None)
    elif mark in _READER_REVIEW_ALLOWED_MARKS:
        updated_at = _aware_utc(now or datetime.now(UTC)).isoformat()
        marks[sequence_key] = {
            "mark": mark,
            "source_text": source_text,
            "translated_text": translated_text,
            "status": _string(status, fallback="unknown"),
            "source_block_ids": [
                _string(block_id, fallback="")
                for block_id in source_block_ids
                if _string(block_id, fallback="")
            ],
            "updated_at": updated_at,
        }
    else:
        return None
    document = {
        "version": _READER_REVIEW_MARKS_VERSION,
        "contains_raw_text": True,
        "updated_at": _aware_utc(now or datetime.now(UTC)).isoformat(),
        "marks": marks,
    }
    _write_json_atomic(marks_path, document)
    return load_reader_review_marks(root, run_id)


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


def _glossary_runtime_diagnostics_payload(
    details: TranslationRunDetails,
    *,
    run_dir: Path,
    raw_text_diagnostics_present: bool,
) -> dict[str, Any] | None:
    adapter_events = tuple(
        event
        for event in details.events
        if event.event_type == _GLOSSARY_RUNTIME_EVENT_TYPE
    )
    if not adapter_events:
        return None
    rendered_contexts, rejected_contexts = _provider_io_glossary_contexts(
        run_dir / "provider_io_diagnostics.jsonl",
    )

    adapter_payloads = tuple(
        _glossary_adapter_event_payload(event) for event in adapter_events
    )
    selected_entry_ids = sorted(
        {
            entry_id
            for payload in adapter_payloads
            for entry_id in _glossary_selected_entry_ids(payload)
        }
    )
    cache_behaviors = sorted(
        {
            str(cache_policy.get("behavior"))
            for payload in adapter_payloads
            if isinstance(cache_policy := payload.get("cache_policy"), dict)
            and cache_policy.get("behavior")
        }
    )
    payload: dict[str, Any] = {
        "schema_version": _GLOSSARY_RUNTIME_DIAGNOSTICS_SCHEMA_VERSION,
        "diagnostic_scope": "owner_only_admin_download",
        "access_boundary": {
            "visibility": "owner_only",
            "ordinary_logs_allowed": False,
            "telemetry_allowed": False,
            "normal_admin_surface_allowed": False,
            "telegram_user_surface_allowed": False,
            "json_api_allowed": False,
            "github_issue_or_pr_allowed": False,
            "support_artifact_allowed": False,
            "release_artifact_allowed": False,
            "cache_control": "no-store",
        },
        "contains_raw_glossary_diagnostics": bool(rendered_contexts),
        "metadata_only": not bool(rendered_contexts),
        "secret_exclusion_policy": (
            "Provider Authorization headers, API keys, tokens, passwords, DSNs "
            "and real .env* values are forbidden in this sidecar."
        ),
        "retention_policy": "TBD",
        "export_policy": "TBD",
        "deletion_policy": "TBD",
        "job_id": details.summary.job_id,
        "run_id": Path(details.run_dir).name,
        "file_name": details.summary.file_name,
        "document_kind": details.summary.document_kind,
        "source_language": details.summary.source_language,
        "target_language": details.summary.target_language,
        "glossary_mode": _translation_policy_value(details, "glossary_mode"),
        "summary": {
            "adapter_event_count": len(adapter_payloads),
            "rendered_prompt_context_count": len(rendered_contexts),
            "rejected_prompt_context_count": len(rejected_contexts),
            "selected_entry_ids": selected_entry_ids,
            "cache_policy_behaviors": cache_behaviors,
            "related_diagnostic_files": _glossary_related_diagnostic_files(
                run_dir,
                raw_text_diagnostics_present=raw_text_diagnostics_present,
            ),
        },
        "adapter_events": list(adapter_payloads),
        "rendered_prompt_contexts": list(rendered_contexts),
        "rejected_prompt_contexts": list(rejected_contexts),
    }
    redacted_payload, redactions = _redact_secret_material(payload)
    redacted_payload["secret_material_rejected"] = bool(redactions)
    redacted_payload["secret_redaction_count"] = len(redactions)
    redacted_payload["secret_redactions"] = redactions
    return redacted_payload


def _glossary_adapter_event_payload(event: TranslationRunEvent) -> dict[str, Any]:
    payload, raw_event_redactions = _redact_glossary_event_raw_fields(
        dict(event.payload),
    )
    return {
        "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        "event_type": event.event_type,
        "status": payload.get("status", "Unknown"),
        "fallback_reason": payload.get("fallback_reason", "Unknown"),
        "work_unit_sequence": payload.get("work_unit_sequence"),
        "selected_entry_ids": _string_sequence(payload.get("selected_entry_ids")),
        "cache_policy": _safe_dict(payload.get("cache_policy")),
        "battle_test_preflight": _safe_dict(payload.get("battle_test_preflight")),
        "prompt_context": payload.get("prompt_context"),
        "policy_signature_context": _safe_dict(payload.get("policy_signature_context")),
        "work_unit_selection_signature": payload.get("work_unit_selection_signature"),
        "raw_event_redactions": raw_event_redactions,
        "payload": payload,
    }


def _glossary_selected_entry_ids(payload: dict[str, Any]) -> tuple[str, ...]:
    selected = list(_string_sequence(payload.get("selected_entry_ids")))
    preflight = payload.get("battle_test_preflight")
    if isinstance(preflight, dict):
        selected.extend(_string_sequence(preflight.get("useful_entry_ids")))
    prompt_context = payload.get("prompt_context")
    if isinstance(prompt_context, dict):
        selected.extend(_string_sequence(prompt_context.get("included_entry_ids")))
    return tuple(dict.fromkeys(selected))


def _provider_io_glossary_contexts(
    provider_io_path: Path,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    if not provider_io_path.exists():
        return (), ()
    rendered: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    try:
        lines = provider_io_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return (), ()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        request_text = _provider_io_request_text(record)
        if request_text is None:
            continue
        for string_path, text in _provider_request_strings(request_text):
            for context_index, context_text in enumerate(
                _extract_glossary_contexts(text),
                start=1,
            ):
                if _contains_secret_material(context_text):
                    rejected.append(
                        {
                            "source_file": "provider_io_diagnostics.jsonl",
                            "line_number": line_number,
                            "string_path": string_path,
                            "context_index": context_index,
                            "reason": "secret_material_detected",
                        }
                    )
                    continue
                rendered.append(
                    {
                        "source_file": "provider_io_diagnostics.jsonl",
                        "line_number": line_number,
                        "string_path": string_path,
                        "context_index": context_index,
                        "character_count": len(context_text),
                        "text": context_text,
                    }
                )
    return tuple(rendered), tuple(rejected)


def _provider_io_request_text(record: dict[str, Any]) -> str | None:
    request_body = record.get("request_body")
    if not isinstance(request_body, dict):
        return None
    text = request_body.get("text")
    return text if isinstance(text, str) and text else None


def _provider_request_strings(request_text: str) -> tuple[tuple[str, str], ...]:
    try:
        parsed = json.loads(request_text)
    except json.JSONDecodeError:
        return (("$.request_body.text", request_text),)
    strings = tuple(_iter_json_strings(parsed, "$.request_body.json"))
    return strings or (("$.request_body.text", request_text),)


def _iter_json_strings(value: Any, path: str) -> tuple[tuple[str, str], ...]:
    if isinstance(value, str):
        return ((path, value),)
    if isinstance(value, dict):
        strings: list[tuple[str, str]] = []
        for key, item in value.items():
            strings.extend(_iter_json_strings(item, f"{path}.{key}"))
        return tuple(strings)
    if isinstance(value, list):
        strings = []
        for index, item in enumerate(value):
            strings.extend(_iter_json_strings(item, f"{path}[{index}]"))
        return tuple(strings)
    return ()


def _extract_glossary_contexts(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _GLOSSARY_CONTEXT_RE.finditer(text))


def _glossary_related_diagnostic_files(
    run_dir: Path,
    *,
    raw_text_diagnostics_present: bool,
) -> list[str]:
    related: list[str] = []
    if raw_text_diagnostics_present:
        related.append("raw_text_diagnostics.json")
    if (run_dir / "provider_io_diagnostics.jsonl").exists():
        related.append("provider_io_diagnostics.jsonl")
    return related


def _translation_policy_value(
    details: TranslationRunDetails,
    key: str,
) -> str:
    policy = details.metadata.get("translation_policy")
    if not isinstance(policy, str):
        return "Unknown"
    try:
        payload = json.loads(policy)
    except json.JSONDecodeError:
        return "Unknown"
    if not isinstance(payload, dict):
        return "Unknown"
    value = payload.get(key)
    return str(value) if value else "Unknown"


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item))


def _redact_secret_material(
    value: Any,
    *,
    path: str = "$",
) -> tuple[Any, list[dict[str, str]]]:
    if isinstance(value, dict):
        redactions: list[dict[str, str]] = []
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if _is_secret_key(key_text):
                safe[key_text] = "[redacted]"
                redactions.append(
                    {"path": child_path, "reason": "secret_key_rejected"}
                )
                continue
            child, child_redactions = _redact_secret_material(
                item,
                path=child_path,
            )
            safe[key_text] = child
            redactions.extend(child_redactions)
        return safe, redactions
    if isinstance(value, list):
        redactions = []
        safe_list = []
        for index, item in enumerate(value):
            child, child_redactions = _redact_secret_material(
                item,
                path=f"{path}[{index}]",
            )
            safe_list.append(child)
            redactions.extend(child_redactions)
        return safe_list, redactions
    if isinstance(value, tuple):
        safe, redactions = _redact_secret_material(list(value), path=path)
        return safe, redactions
    if isinstance(value, str) and _contains_secret_material(value):
        return "[redacted]", [{"path": path, "reason": "secret_value_rejected"}]
    return value, []


def _redact_glossary_event_raw_fields(
    value: Any,
    *,
    path: str = "$",
) -> tuple[Any, list[dict[str, str]]]:
    if isinstance(value, dict):
        redactions: list[dict[str, str]] = []
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}"
            if key_text.lower() in _RAW_GLOSSARY_EVENT_KEYS:
                safe[key_text] = "[redacted]"
                redactions.append(
                    {"path": child_path, "reason": "raw_event_field_rejected"}
                )
                continue
            child, child_redactions = _redact_glossary_event_raw_fields(
                item,
                path=child_path,
            )
            safe[key_text] = child
            redactions.extend(child_redactions)
        return safe, redactions
    if isinstance(value, list):
        redactions = []
        safe_list = []
        for index, item in enumerate(value):
            child, child_redactions = _redact_glossary_event_raw_fields(
                item,
                path=f"{path}[{index}]",
            )
            safe_list.append(child)
            redactions.extend(child_redactions)
        return safe_list, redactions
    if isinstance(value, tuple):
        safe, redactions = _redact_glossary_event_raw_fields(list(value), path=path)
        return safe, redactions
    return value, []


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _SECRET_DIAGNOSTIC_KEYS:
        return False
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def _contains_secret_material(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_VALUE_PATTERNS)


def _write_diagnostic_files(
    archive: ZipFile,
    files: tuple[TranslationRunDiagnosticFile, ...],
    *,
    written_paths: set[str],
) -> tuple[dict[str, Any], ...]:
    entries: list[dict[str, Any]] = []
    for file in files:
        member_path = _unique_archive_path(
            _diagnostic_file_archive_path(file),
            written_paths=written_paths,
        )
        archive.writestr(member_path, file.content)
        written_paths.add(member_path)
        entries.append(
            {
                "role": file.role,
                "object_kind": file.object_kind,
                "object_key": file.object_key,
                "file_name": file.file_name,
                "archive_path": member_path,
                "content_type": file.content_type,
                "size_bytes": file.size_bytes,
                "sha256": file.sha256,
            }
        )
    return tuple(entries)


def _diagnostic_files_manifest(
    entries: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    return {
        "schema_version": "translation-diagnostic-files-v1",
        "contains_raw_file_bytes": True,
        "diagnostic_scope": "owner_only_admin_download",
        "files": entries,
    }


def _diagnostic_file_archive_path(file: TranslationRunDiagnosticFile) -> str:
    role = _safe_archive_segment(file.role, fallback="file")
    file_name = _safe_archive_file_name(file.file_name, fallback=role)
    return f"diagnostic_files/{role}/{file_name}"


def _unique_archive_path(path: str, *, written_paths: set[str]) -> str:
    if path not in written_paths:
        return path
    pure_path = PurePosixPath(path)
    parent = pure_path.parent.as_posix()
    suffix = pure_path.suffix
    stem = pure_path.name[: -len(suffix)] if suffix else pure_path.name
    counter = 2
    while True:
        candidate_name = f"{stem}-{counter}{suffix}"
        candidate = f"{parent}/{candidate_name}" if parent != "." else candidate_name
        if candidate not in written_paths:
            return candidate
        counter += 1


def _safe_archive_segment(value: str, *, fallback: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    return segment or fallback


def _safe_archive_file_name(value: str, *, fallback: str) -> str:
    raw_name = PurePosixPath(str(value or "").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    return name or f"{fallback}.bin"


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
        "- counts_by_status: "
        f"`{json.dumps(work_units['counts_by_status'], sort_keys=True)}`",
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
        for attempt in diagnostic.provider_attempts:
            lines.append(
                "- provider_attempt: "
                f"`#{attempt.attempt_number} {attempt.failure_category}`"
                f" status=`{attempt.status}`"
                f" retry_after=`{attempt.retry_after_seconds or 0}`"
                f" terminal_reason=`{attempt.terminal_reason or 'n/a'}`"
                f" circuit=`{attempt.circuit_state or 'Unknown'}`"
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


def _read_reader_review_marks_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": _READER_REVIEW_MARKS_VERSION, "marks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": _READER_REVIEW_MARKS_VERSION, "marks": {}}
    if not isinstance(data, dict):
        return {"version": _READER_REVIEW_MARKS_VERSION, "marks": {}}
    marks = data.get("marks")
    if not isinstance(marks, dict):
        data["marks"] = {}
    return data


def _reader_review_mark_from_record(
    sequence_key: str,
    record: object,
) -> ReaderReviewMark | None:
    sequence = _int(sequence_key)
    if sequence <= 0 or not isinstance(record, dict):
        return None
    mark = _string(record.get("mark"), fallback="")
    if mark not in _READER_REVIEW_ALLOWED_MARKS:
        return None
    return ReaderReviewMark(
        sequence=sequence,
        mark=mark,
        source_text=_string(record.get("source_text"), fallback=""),
        translated_text=_string(record.get("translated_text"), fallback=""),
        status=_string(record.get("status"), fallback="unknown"),
        source_block_ids=tuple(
            _string(block_id, fallback="")
            for block_id in _safe_list(record.get("source_block_ids"))
            if _string(block_id, fallback="")
        ),
        updated_at=_parse_datetime(record.get("updated_at")),
    )


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


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


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


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
