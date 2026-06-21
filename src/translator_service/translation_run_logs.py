import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from translator_service.book_mode_output_audit import (
    BookModeAuditChunk,
    audit_book_mode_output,
)
from translator_service.security_telemetry import (
    build_security_event,
    normalize_security_event,
)


@dataclass(frozen=True)
class TranslationRunMetadata:
    job_id: str
    order_id: str | None
    user_id: str | None
    file_name: str
    document_kind: str
    source_language: str
    target_language: str
    translator_model: str | None = None
    prompt_version: str | None = None
    adapter_version: str | None = None
    interface_language: str | None = None
    detected_source_language: str | None = None
    total_fragment_count: int | None = None
    translation_policy: str | None = None
    translation_quality_route: str | None = None
    translation_stack: dict | None = None


@dataclass(frozen=True)
class TranslationFragmentLog:
    sequence: int
    source_text: str
    translated_text: str
    status: str
    elapsed_seconds: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    source_block_ids: tuple[str, ...] = ()
    block_kind: str = "plain"
    audit_metadata: tuple[tuple[str, str], ...] = ()
    prompt_tier: str | None = None
    source_text_hash: str | None = None
    retry_count: int = 0
    cache_hit: bool = False
    warnings: tuple[str, ...] = ()
    error_message: str | None = None


class TranslationRunLogger:
    def __init__(
        self,
        *,
        run_dir: Path,
        metadata: TranslationRunMetadata,
        started_at: datetime,
    ) -> None:
        self.run_dir = run_dir
        self._metadata = metadata
        self._started_at = started_at
        self._finished_at: datetime | None = None
        self._status = "running"
        self._result_file_name: str | None = None
        self._error_message: str | None = None
        self._fragment_count = 0
        self._totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
            "elapsed_seconds": 0.0,
            "retry_count": 0,
            "cache_hits": 0,
        }
        self._security = _empty_security_totals()
        self._book_mode_audit_enabled = _is_book_mode_metadata(metadata)
        self._book_mode_audit = _empty_book_mode_audit_totals(
            enabled=self._book_mode_audit_enabled,
            target_language=metadata.target_language,
        )

    @classmethod
    def start(
        cls,
        *,
        root: str | Path,
        metadata: TranslationRunMetadata,
    ) -> "TranslationRunLogger":
        started_at = datetime.now(UTC)
        root_path = Path(root)
        run_dir = root_path / _run_dir_name(started_at, metadata)
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "fragments").mkdir()
        logger = cls(run_dir=run_dir, metadata=metadata, started_at=started_at)
        logger.record_event("run_started", {"status": "running"})
        logger._write_outputs()
        return logger

    def record_event(self, event_type: str, payload: dict | None = None) -> None:
        event = {
            "timestamp": _now_iso(),
            "event_type": event_type,
            "job_id": self._metadata.job_id,
            "payload": _safe_event_payload(payload or {}),
        }
        with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as events:
            events.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def record_security_event(
        self,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        event = normalize_security_event(
            {"event_type": event_type, "payload": payload or {}}
        )
        if event is None:
            event = build_security_event(event_type)
        self._security["events"] += 1
        counter = _security_counter_name(event["event_type"])
        self._security[counter] = self._security.get(counter, 0) + 1
        self.record_event(
            "security_event",
            {
                **event["payload"],
                "security_event_type": event["event_type"],
            },
        )
        self._write_outputs()

    def record_fragment(self, fragment: TranslationFragmentLog) -> None:
        fragment_path = self.run_dir / "fragments" / f"{fragment.sequence:04d}.json"
        fragment_record = _fragment_to_dict(fragment)
        fragment_path.write_text(
            json.dumps(fragment_record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._fragment_count += 1
        self._totals["prompt_tokens"] += fragment.prompt_tokens
        self._totals["completion_tokens"] += fragment.completion_tokens
        self._totals["total_tokens"] += fragment.total_tokens
        self._totals["prompt_cache_hit_tokens"] += fragment.prompt_cache_hit_tokens
        self._totals["prompt_cache_miss_tokens"] += fragment.prompt_cache_miss_tokens
        self._totals["elapsed_seconds"] += fragment.elapsed_seconds
        self._totals["retry_count"] += fragment.retry_count
        self._totals["cache_hits"] += 1 if fragment.cache_hit else 0
        self._record_book_mode_audit(fragment)
        self.record_event(
            "work_unit_failed" if fragment.status == "failed" else "work_unit_finished",
            {
                "sequence": fragment.sequence,
                "status": fragment.status,
                "elapsed_seconds": fragment.elapsed_seconds,
                "prompt_tokens": fragment.prompt_tokens,
                "completion_tokens": fragment.completion_tokens,
                "total_tokens": fragment.total_tokens,
                "error_message": fragment_record.get("error_message"),
            },
        )
        self._write_outputs()

    def finish(
        self,
        *,
        status: str,
        result_file_name: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._status = status
        self._result_file_name = result_file_name
        self._error_message = _safe_error_message(error_message)
        self._finished_at = datetime.now(UTC)
        event_type = {
            "cancelled": "run_cancelled",
            "failed": "run_failed",
        }.get(status, "run_finished")
        self.record_event(
            event_type,
            {
                "status": status,
                "result_file_name": result_file_name,
                "error_message": self._error_message,
            },
        )
        self._write_outputs()

    def _write_outputs(self) -> None:
        snapshot = self._snapshot()
        (self.run_dir / "run.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (self.run_dir / "summary.md").write_text(
            _render_summary(snapshot),
            encoding="utf-8",
        )

    def _snapshot(self) -> dict:
        metadata = asdict(self._metadata)
        return {
            **metadata,
            "status": self._status,
            "started_at": self._started_at.isoformat(),
            "finished_at": (
                self._finished_at.isoformat() if self._finished_at is not None else None
            ),
            "result_file_name": self._result_file_name,
            "error_message": self._error_message,
            "run_dir": str(self.run_dir),
            "fragment_count": self._fragment_count,
            "totals": dict(self._totals),
            "security": dict(self._security),
            "book_mode_audit": _book_mode_audit_snapshot(self._book_mode_audit),
        }

    def _record_book_mode_audit(self, fragment: TranslationFragmentLog) -> None:
        if not self._book_mode_audit_enabled:
            return
        _record_book_mode_audit_chunk(
            self._book_mode_audit,
            target_language=self._metadata.target_language,
            chunk_id=(
                fragment.source_block_ids[0]
                if fragment.source_block_ids
                else f"fragment:{fragment.sequence}"
            ),
            translated_text=fragment.translated_text,
            block_kind=fragment.block_kind,
            audit_metadata=fragment.audit_metadata,
        )


def finish_running_translation_runs_for_job(
    root: str | Path,
    *,
    job_id: str,
    status: str = "cancelled",
    result_file_name: str | None = None,
    error_message: str | None = None,
    current_statuses: tuple[str, ...] = ("running",),
    preserve_existing_error_message: bool = False,
) -> int:
    root_path = Path(root)
    if not job_id or not root_path.exists():
        return 0

    finished = 0
    for run_json in root_path.glob("*/run.json"):
        try:
            snapshot = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(snapshot, dict):
            continue
        if (
            snapshot.get("job_id") != job_id
            or snapshot.get("status") not in current_statuses
        ):
            continue

        snapshot["status"] = status
        snapshot["finished_at"] = _now_iso()
        if result_file_name is not None:
            snapshot["result_file_name"] = result_file_name
        safe_error_message = _safe_error_message(error_message)
        if preserve_existing_error_message and safe_error_message is None:
            previous_error = snapshot.get("error_message")
            safe_error_message = (
                previous_error if isinstance(previous_error, str) else None
            )
        snapshot["error_message"] = safe_error_message
        event_type = {
            "cancelled": "run_cancelled",
            "failed": "run_failed",
        }.get(status, "run_finished")
        _append_run_event(
            run_json.parent,
            event_type,
            job_id=job_id,
            payload={
                "status": status,
                "result_file_name": snapshot.get("result_file_name"),
                "error_message": safe_error_message,
            },
        )
        run_json.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_json.parent / "summary.md").write_text(
            _render_summary(snapshot),
            encoding="utf-8",
        )
        finished += 1
    return finished


def append_provider_io_diagnostic_for_job(
    root: str | Path | None,
    *,
    job_id: str,
    record: dict[str, object],
) -> int:
    if root is None or not job_id:
        return 0
    root_path = Path(root)
    if not root_path.exists():
        return 0

    matching: list[tuple[Path, dict]] = []
    for run_json in root_path.glob("*/run.json"):
        try:
            snapshot = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(snapshot, dict) or snapshot.get("job_id") != job_id:
            continue
        matching.append((run_json, snapshot))

    running = [item for item in matching if item[1].get("status") == "running"]
    targets = running or _latest_matching_run(matching)

    appended = 0
    for run_json, _snapshot in targets:
        run_record = {
            **record,
            "job_id": job_id,
            "run_id": run_json.parent.name,
        }
        with (run_json.parent / "provider_io_diagnostics.jsonl").open(
            "a",
            encoding="utf-8",
        ) as diagnostics:
            diagnostics.write(
                json.dumps(run_record, ensure_ascii=False, sort_keys=True) + "\n"
            )
        appended += 1
    return appended


def append_translation_run_event_for_job(
    root: str | Path | None,
    *,
    job_id: str,
    event_type: str,
    payload: dict[str, object] | None = None,
) -> int:
    if root is None or not job_id:
        return 0
    root_path = Path(root)
    if not root_path.exists():
        return 0

    matching: list[tuple[Path, dict]] = []
    for run_json in root_path.glob("*/run.json"):
        try:
            snapshot = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(snapshot, dict) or snapshot.get("job_id") != job_id:
            continue
        matching.append((run_json, snapshot))

    running = [item for item in matching if item[1].get("status") == "running"]
    targets = running or _latest_matching_run(matching)

    appended = 0
    for run_json, _snapshot in targets:
        _append_run_event(
            run_json.parent,
            event_type,
            job_id=job_id,
            payload=safe_glossary_adapter_metadata(payload or {})
            if event_type == "glossary_runtime_adapter"
            else payload,
        )
        appended += 1
    return appended


def _latest_matching_run(items: list[tuple[Path, dict]]) -> list[tuple[Path, dict]]:
    if not items:
        return []
    return [max(items, key=lambda item: item[0].parent.name)]


def record_book_mode_audit_fragment_for_job(
    root: str | Path | None,
    *,
    job_id: str,
    sequence: int,
    translated_text: str,
    source_block_ids: tuple[str, ...] = (),
    block_kind: str = "plain",
    audit_metadata: tuple[tuple[str, str], ...] = (),
) -> int:
    if root is None or not job_id:
        return 0
    root_path = Path(root)
    if not root_path.exists():
        return 0

    updated = 0
    for run_json in root_path.glob("*/run.json"):
        try:
            snapshot = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(snapshot, dict) or snapshot.get("job_id") != job_id:
            continue
        if snapshot.get("status") != "running":
            continue
        if not _is_book_mode_snapshot(snapshot):
            continue

        audit = _book_mode_audit_from_snapshot(snapshot)
        chunk_id = (
            source_block_ids[0] if source_block_ids else f"fragment:{sequence}"
        )
        _record_book_mode_audit_chunk(
            audit,
            target_language=_string_value(snapshot.get("target_language")),
            chunk_id=chunk_id,
            translated_text=translated_text,
            block_kind=block_kind,
            audit_metadata=audit_metadata,
        )
        snapshot["book_mode_audit"] = _book_mode_audit_snapshot(audit)
        run_json.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_json.parent / "summary.md").write_text(
            _render_summary(snapshot),
            encoding="utf-8",
        )
        updated += 1
    return updated


def record_book_mode_audit_gate_for_job(
    root: str | Path | None,
    *,
    job_id: str,
    gate: dict[str, object],
) -> int:
    if root is None or not job_id:
        return 0
    root_path = Path(root)
    if not root_path.exists():
        return 0

    updated = 0
    for run_json in root_path.glob("*/run.json"):
        try:
            snapshot = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(snapshot, dict) or snapshot.get("job_id") != job_id:
            continue
        if snapshot.get("status") != "running":
            continue
        if not _is_book_mode_snapshot(snapshot):
            continue

        audit = snapshot.get("book_mode_audit")
        if not isinstance(audit, dict):
            audit = _empty_book_mode_audit_totals(
                enabled=True,
                target_language=_string_value(snapshot.get("target_language")),
            )
        audit["final_surface_gate"] = _safe_gate_payload(gate)
        snapshot["book_mode_audit"] = audit
        _append_run_event(
            run_json.parent,
            "book_mode_audit_gate_failed",
            job_id=job_id,
            payload=_safe_gate_payload(gate),
        )
        run_json.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (run_json.parent / "summary.md").write_text(
            _render_summary(snapshot),
            encoding="utf-8",
        )
        updated += 1
    return updated


def _append_run_event(
    run_dir: Path,
    event_type: str,
    *,
    job_id: str,
    payload: dict | None = None,
) -> None:
    event = {
        "timestamp": _now_iso(),
        "event_type": event_type,
        "job_id": job_id,
        "payload": _safe_event_payload(payload or {}),
    }
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as events:
        events.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _fragment_to_dict(fragment: TranslationFragmentLog) -> dict:
    data = asdict(fragment)
    source_text = data.pop("source_text")
    translated_text = data.pop("translated_text")
    data.pop("audit_metadata", None)
    if data.get("error_message") is not None:
        data["error_message"] = _safe_error_message(
            data["error_message"],
            unsafe_texts=(source_text, translated_text),
            always_redact=True,
        )
    if not data.get("source_text_hash"):
        data["source_text_hash"] = _text_hash(source_text)
    data["translated_text_hash"] = _text_hash(translated_text)
    data["source_text_chars"] = len(source_text)
    data["translated_text_chars"] = len(translated_text)
    data["source_block_ids"] = list(fragment.source_block_ids)
    data["warnings"] = list(fragment.warnings)
    return data


def _text_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


_SAFE_ERROR_MESSAGES = {
    "Book cancelled by user.",
    "Book deleted by user.",
}

_SENSITIVE_ERROR_PATTERNS = (
    re.compile(r"(?is)\btraceback\b.*"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|secret_id|value)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9._-]+"),
    re.compile(r"\b[A-Za-z0-9._-]*api_keys[A-Za-z0-9._-]*\b"),
)

_SENSITIVE_PAYLOAD_KEY_MARKERS = (
    "source_text",
    "translated_text",
    "prompt",
    "plaintext",
    "api_key",
    "secret",
    "access_token",
    "refresh_token",
    "bot_token",
    "authorization",
    "stack_trace",
    "traceback",
)

_GLOSSARY_METADATA_RAW_KEYS = {
    "api_key",
    "auth",
    "auth_material",
    "authorization",
    "dsn",
    "password",
    "prompt",
    "prompt_body",
    "provider_auth",
    "provider_response",
    "provider_response_body",
    "raw",
    "raw_provider_response_body",
    "request_body",
    "response_body",
    "raw_prompt",
    "raw_response",
    "raw_source",
    "raw_source_text",
    "source_text",
    "source_texts",
    "token",
    "translated_text",
    "translation",
}

_GLOSSARY_METADATA_RAW_KEY_MARKERS = (
    ".env",
    "api_key",
    "auth_material",
    "authorization",
    "dsn",
    "password",
    "provider_auth",
    "provider_response",
    "secret",
    "token",
)
_GLOSSARY_METADATA_SECRET_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"\b(?:postgres(?:ql)?|mysql|redis|mongodb|amqp)://[^\s]+",
        re.IGNORECASE,
    ),
    re.compile(r"(?m)^[A-Z_][A-Z0-9_]{2,}=[^\s].+$"),
)


def safe_glossary_adapter_metadata(value):
    if isinstance(value, dict):
        safe_payload = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in _GLOSSARY_METADATA_RAW_KEYS or any(
                marker in key_lower for marker in _GLOSSARY_METADATA_RAW_KEY_MARKERS
            ):
                safe_payload[key] = "[redacted]"
                continue
            safe_payload[key] = safe_glossary_adapter_metadata(item)
        return safe_payload
    if isinstance(value, list):
        return [safe_glossary_adapter_metadata(item) for item in value]
    if isinstance(value, tuple):
        return tuple(safe_glossary_adapter_metadata(item) for item in value)
    if isinstance(value, str) and any(
        pattern.search(value)
        for pattern in _GLOSSARY_METADATA_SECRET_VALUE_PATTERNS
    ):
        return "[redacted]"
    return value


def _safe_event_payload(payload: dict) -> dict:
    safe = {}
    for key, value in payload.items():
        key_text = str(key)
        if key_text.lower() == "prompt_context":
            safe[key_text] = safe_glossary_adapter_metadata(value)
        elif any(
            marker in key_text.lower()
            for marker in _SENSITIVE_PAYLOAD_KEY_MARKERS
        ):
            safe[key_text] = "[redacted]"
        elif key_text.lower() in {"error", "error_message", "last_error"}:
            safe[key_text] = _safe_error_message(value)
        else:
            safe[key_text] = value
    return safe


def _safe_error_message(
    value: object,
    *,
    unsafe_texts: tuple[str, ...] = (),
    always_redact: bool = False,
) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if text in _SAFE_ERROR_MESSAGES:
        return text
    if always_redact:
        return "[redacted]"
    for unsafe_text in unsafe_texts:
        unsafe = " ".join(str(unsafe_text).split())
        if len(unsafe) >= 8:
            text = text.replace(unsafe, "[redacted]")
    for pattern in _SENSITIVE_ERROR_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text or "[redacted]"


def _render_summary(snapshot: dict) -> str:
    lines = [
        "# Translation Run",
        "",
        f"- Job: `{snapshot['job_id']}`",
        f"- Order: `{snapshot.get('order_id') or 'n/a'}`",
        f"- User: `{snapshot.get('user_id') or 'n/a'}`",
        f"- File: `{snapshot['file_name']}`",
        f"- Format: `{snapshot['document_kind']}`",
        (
            f"- Direction: `{snapshot['source_language']}` -> "
            f"`{snapshot['target_language']}`"
        ),
        f"- Status: `{snapshot['status']}`",
        f"- Started: `{snapshot['started_at']}`",
        f"- Finished: `{snapshot.get('finished_at') or 'n/a'}`",
        f"- Result: `{snapshot.get('result_file_name') or 'n/a'}`",
        "",
        "## Translator",
        "",
        f"- Model: `{snapshot.get('translator_model') or 'n/a'}`",
        f"- Prompt version: `{snapshot.get('prompt_version') or 'n/a'}`",
        f"- Adapter version: `{snapshot.get('adapter_version') or 'n/a'}`",
        "",
        *_render_translation_stack(snapshot.get("translation_stack")),
        "",
        "## Totals",
        "",
    ]
    totals = snapshot["totals"]
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
        "elapsed_seconds",
        "retry_count",
        "cache_hits",
    ):
        lines.append(f"- {key}: `{totals[key]}`")
    if snapshot.get("error_message"):
        lines.extend(["", "## Error", "", snapshot["error_message"]])
    security = snapshot.get("security") or {}
    if security.get("events"):
        lines.extend(["", "## Security", ""])
        for key in sorted(security):
            value = security[key]
            if value:
                lines.append(f"- {key}: `{value}`")
    audit = snapshot.get("book_mode_audit") or {}
    if audit.get("enabled"):
        lines.extend(["", "## Book Mode Audit", ""])
        lines.append(f"- chunks_audited: `{audit.get('chunks_audited') or 0}`")
        lines.append(
            f"- chunks_with_findings: `{audit.get('chunks_with_findings') or 0}`"
        )
        lines.append(f"- total_findings: `{audit.get('total_findings') or 0}`")
        lines.append(
            "- counts_by_code: "
            f"`{json.dumps(audit.get('counts_by_code') or {}, sort_keys=True)}`"
        )
    return "\n".join(lines) + "\n"


def _render_translation_stack(stack: dict | None) -> list[str]:
    if not isinstance(stack, dict):
        return []
    adapter = stack.get("adapter") if isinstance(stack.get("adapter"), dict) else {}
    prompt = stack.get("prompt") if isinstance(stack.get("prompt"), dict) else {}
    profiles = (
        stack.get("language_profiles")
        if isinstance(stack.get("language_profiles"), dict)
        else {}
    )
    target_profile = (
        profiles.get("target_language")
        if isinstance(profiles.get("target_language"), dict)
        else {}
    )
    source_pair = (
        profiles.get("source_pair")
        if isinstance(profiles.get("source_pair"), dict)
        else {}
    )
    quality_track = (
        profiles.get("quality_track")
        if isinstance(profiles.get("quality_track"), dict)
        else {}
    )
    text = stack.get("text") if isinstance(stack.get("text"), dict) else {}
    return [
        "## Translation Stack",
        "",
        f"- Stack schema: `{stack.get('schema_version') or 'n/a'}`",
        (
            f"- Adapter: `{adapter.get('name') or 'n/a'}` "
            f"(`{adapter.get('version') or 'n/a'}`)"
        ),
        f"- Document kind: `{adapter.get('document_kind') or 'n/a'}`",
        f"- Run prompt version: `{prompt.get('run_prompt_version') or 'n/a'}`",
        f"- Prompt policy: `{prompt.get('prompt_policy_version') or 'n/a'}`",
        f"- Protection policy: `{prompt.get('protection_policy_version') or 'n/a'}`",
        f"- Generic adapter policy: `{prompt.get('adapter_policy_version') or 'n/a'}`",
        f"- Output contract: `{prompt.get('output_contract') or 'n/a'}`",
        f"- Target language profile: `{target_profile.get('signature') or 'n/a'}`",
        f"- Source-pair profile: `{source_pair.get('signature') or 'n/a'}`",
        f"- Quality track: `{quality_track.get('signature') or 'n/a'}`",
        f"- Text type: `{text.get('text_type') or 'n/a'}`",
        f"- Prompt tier: `{text.get('prompt_tier') or 'n/a'}`",
        "",
    ]


def _run_dir_name(started_at: datetime, metadata: TranslationRunMetadata) -> str:
    timestamp = started_at.strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    return "_".join(
        part
        for part in (
            timestamp,
            _safe_slug(metadata.job_id),
            _safe_slug(metadata.file_name),
            _safe_slug(metadata.target_language),
        )
        if part
    )


def _safe_slug(value: str | None) -> str:
    if not value:
        return ""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    safe = re.sub(r"_+", "_", safe).strip("._")
    return safe or "item"


def _empty_security_totals() -> dict[str, int]:
    return {
        "events": 0,
        "unsafe_model_outputs": 0,
        "model_output_repair_retries": 0,
        "model_output_repair_failures": 0,
        "translation_batch_rejections": 0,
        "document_sandbox_timeouts": 0,
        "document_sandbox_failures": 0,
        "document_assembly_failures": 0,
        "security_threshold_exceeded": 0,
        "security_user_cooldowns": 0,
        "other_security_events": 0,
    }


_BOOK_MODE_TRANSLATION_MODE = "book_manuscript"
_BOOK_MODE_PROFILE = "book-manuscript-v1"
_BOOK_MODE_AUDIT_CODE_ALIASES = {
    "english_navigation_heading_residue": "english_navigation_residue",
    "provider_commentary_wrapper": "provider_commentary",
    "suspicious_all_english_chunk": "untranslated_source_residue",
}
_BOOK_MODE_AUDIT_CODES = {
    "untranslated_source_residue",
    "english_navigation_residue",
    "gutenberg_legal_backmatter_residue",
    "language_metadata_mismatch",
    "provider_commentary",
}


def _is_book_mode_metadata(metadata: TranslationRunMetadata) -> bool:
    policy = _json_object(metadata.translation_policy)
    if _is_book_mode_policy(policy):
        return True
    stack = (
        metadata.translation_stack
        if isinstance(metadata.translation_stack, dict)
        else {}
    )
    return _has_book_mode_marker(stack)


def _is_book_mode_snapshot(snapshot: dict) -> bool:
    policy = _json_object(
        _optional_string_value(snapshot.get("translation_policy"))
    )
    if _is_book_mode_policy(policy):
        return True
    stack = snapshot.get("translation_stack")
    return _has_book_mode_marker(stack if isinstance(stack, dict) else {})


def _is_book_mode_policy(policy: dict) -> bool:
    return (
        policy.get("translation_mode") == _BOOK_MODE_TRANSLATION_MODE
        or policy.get("translation_mode_profile") == _BOOK_MODE_PROFILE
    )


def _has_book_mode_marker(value: object) -> bool:
    if isinstance(value, dict):
        if _is_book_mode_policy(value):
            return True
        return any(_has_book_mode_marker(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_book_mode_marker(item) for item in value)
    return value in {_BOOK_MODE_TRANSLATION_MODE, _BOOK_MODE_PROFILE}


def _json_object(value: str | None) -> dict:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _empty_book_mode_audit_totals(
    *,
    enabled: bool,
    target_language: str,
) -> dict:
    return {
        "schema_version": "book-mode-audit-run-v1",
        "enabled": enabled,
        "target_language": _language_root(target_language),
        "chunks_audited": 0,
        "chunks_with_findings": 0,
        "total_findings": 0,
        "codes": [],
        "counts_by_code": {},
        "counts_by_category": {},
        "counts_by_severity": {},
    }


def _book_mode_audit_from_snapshot(snapshot: dict) -> dict:
    target_language = _string_value(snapshot.get("target_language"))
    audit = _empty_book_mode_audit_totals(
        enabled=True,
        target_language=target_language,
    )
    existing = snapshot.get("book_mode_audit")
    if not isinstance(existing, dict):
        return audit
    for key in ("chunks_audited", "chunks_with_findings", "total_findings"):
        audit[key] = max(0, _int_value(existing.get(key)))
    for key in ("counts_by_code", "counts_by_category", "counts_by_severity"):
        value = existing.get(key)
        audit[key] = _int_counter(value) if isinstance(value, dict) else {}
    return audit


def _record_book_mode_audit_chunk(
    audit: dict,
    *,
    target_language: str,
    chunk_id: str,
    translated_text: str,
    block_kind: str,
    audit_metadata: tuple[tuple[str, str], ...],
) -> None:
    audit["chunks_audited"] += 1
    result = audit_book_mode_output(
        chunks=(
            BookModeAuditChunk(
                block_id=chunk_id,
                translated_text=translated_text,
                block_kind=block_kind,
                metadata=audit_metadata,
            ),
        ),
        target_language=target_language,
    )
    if not result.findings:
        return
    audit["chunks_with_findings"] += 1
    for finding in result.findings:
        _record_book_mode_audit_finding(audit, finding)


def _record_book_mode_audit_finding(audit: dict, finding) -> None:
    code = _book_mode_audit_code(finding.code)
    category = _book_mode_audit_category(finding.category)
    severity = _book_mode_audit_severity(finding.severity)
    audit["total_findings"] += 1
    _increment_counter(audit["counts_by_code"], code)
    _increment_counter(audit["counts_by_category"], category)
    _increment_counter(audit["counts_by_severity"], severity)


def _book_mode_audit_snapshot(audit: dict) -> dict:
    snapshot = {
        key: value
        for key, value in audit.items()
        if key
        not in {
            "codes",
            "counts_by_code",
            "counts_by_category",
            "counts_by_severity",
        }
    }
    counts_by_code = _sorted_counter(audit["counts_by_code"])
    snapshot["codes"] = list(counts_by_code)
    snapshot["counts_by_code"] = counts_by_code
    snapshot["counts_by_category"] = _sorted_counter(audit["counts_by_category"])
    snapshot["counts_by_severity"] = _sorted_counter(audit["counts_by_severity"])
    return snapshot


def _book_mode_audit_code(code: str) -> str:
    normalized = code.strip().lower() or "unknown"
    normalized = _BOOK_MODE_AUDIT_CODE_ALIASES.get(normalized, normalized)
    return normalized if normalized in _BOOK_MODE_AUDIT_CODES else "other"


def _book_mode_audit_category(category: str) -> str:
    return category.strip().lower() or "unknown"


def _book_mode_audit_severity(severity: str) -> str:
    return severity.strip().lower() or "unknown"


def _increment_counter(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _sorted_counter(counter: dict[str, int]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _safe_gate_payload(gate: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in gate.items():
        key_text = str(key)
        if any(marker in key_text.lower() for marker in _SENSITIVE_PAYLOAD_KEY_MARKERS):
            safe[key_text] = "[redacted]"
        elif isinstance(value, dict):
            safe[key_text] = _int_counter(value)
        elif isinstance(value, (list, tuple)):
            safe[key_text] = [str(item) for item in value]
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key_text] = value
        else:
            safe[key_text] = str(value)
    return safe


def _int_counter(value: dict) -> dict[str, int]:
    return {
        str(key): count
        for key, raw_count in value.items()
        if (count := _int_value(raw_count)) > 0
    }


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _string_value(value: object) -> str:
    return str(value) if value is not None else ""


def _optional_string_value(value: object) -> str | None:
    return str(value) if value is not None else None


def _language_root(language_code: str) -> str:
    normalized = language_code.strip().lower().replace("_", "-")
    return normalized.split("-", 1)[0] if normalized else ""


def _security_counter_name(event_type: str) -> str:
    return {
        "unsafe_model_output": "unsafe_model_outputs",
        "model_output_repair_retry": "model_output_repair_retries",
        "model_output_repair_failed": "model_output_repair_failures",
        "translation_batch_rejected": "translation_batch_rejections",
        "document_sandbox_timeout": "document_sandbox_timeouts",
        "document_sandbox_failure": "document_sandbox_failures",
        "document_sandbox_invalid_response": "document_sandbox_failures",
        "document_sandbox_output_too_large": "document_sandbox_failures",
        "document_sandbox_request_too_large": "document_sandbox_failures",
        "document_sandbox_stderr_too_large": "document_sandbox_failures",
        "document_assembly_failed": "document_assembly_failures",
        "security_threshold_exceeded": "security_threshold_exceeded",
        "security_user_cooldown_started": "security_user_cooldowns",
    }.get(event_type, "other_security_events")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
