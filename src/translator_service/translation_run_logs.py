from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re

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
    translation_policy: str | None = None
    translation_quality_route: str | None = None


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
            "payload": payload or {},
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
        fragment_path.write_text(
            json.dumps(_fragment_to_dict(fragment), ensure_ascii=False, indent=2)
            + "\n",
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
        self.record_event(
            "work_unit_failed" if fragment.status == "failed" else "work_unit_finished",
            {
                "sequence": fragment.sequence,
                "status": fragment.status,
                "elapsed_seconds": fragment.elapsed_seconds,
                "prompt_tokens": fragment.prompt_tokens,
                "completion_tokens": fragment.completion_tokens,
                "total_tokens": fragment.total_tokens,
                "error_message": fragment.error_message,
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
        self._error_message = error_message
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
                "error_message": error_message,
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
        }


def _fragment_to_dict(fragment: TranslationFragmentLog) -> dict:
    data = asdict(fragment)
    source_text = data.pop("source_text")
    translated_text = data.pop("translated_text")
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


def _render_summary(snapshot: dict) -> str:
    lines = [
        "# Translation Run",
        "",
        f"- Job: `{snapshot['job_id']}`",
        f"- Order: `{snapshot.get('order_id') or 'n/a'}`",
        f"- User: `{snapshot.get('user_id') or 'n/a'}`",
        f"- File: `{snapshot['file_name']}`",
        f"- Format: `{snapshot['document_kind']}`",
        f"- Direction: `{snapshot['source_language']}` -> `{snapshot['target_language']}`",
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
    return "\n".join(lines) + "\n"


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
