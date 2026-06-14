from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from translator_service.json_utils import read_json_file


@dataclass(frozen=True)
class SecuritySummary:
    run_count: int
    runs_with_security_events: int
    security_event_count: int
    threshold_stops: int
    cooldowns_started: int
    sandbox_failures: int
    by_event_type: dict[str, int]
    by_reason: dict[str, int]
    by_document_kind: dict[str, int]
    by_status: dict[str, int]
    recent_security_runs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_security_summary(
    root: str | Path,
    *,
    recent_limit: int = 10,
) -> SecuritySummary:
    root_path = Path(root)
    by_event_type: Counter[str] = Counter()
    by_reason: Counter[str] = Counter()
    by_document_kind: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    recent_security_runs: list[dict[str, Any]] = []
    run_count = 0
    runs_with_security_events = 0

    for run_dir in _iter_run_dirs(root_path):
        snapshot = _load_run_snapshot(run_dir)
        if snapshot is None:
            continue

        run_count += 1
        status = str(snapshot.get("status") or "unknown")
        document_kind = str(snapshot.get("document_kind") or "unknown")
        by_status[status] += 1

        run_events = _load_security_events(run_dir)
        if run_events:
            runs_with_security_events += 1

        for event in run_events:
            payload = event.get("payload") if isinstance(event, dict) else {}
            if not isinstance(payload, dict):
                payload = {}
            event_type = str(payload.get("security_event_type") or "unknown")
            by_event_type[event_type] += 1
            by_document_kind[document_kind] += 1
            reason = payload.get("reason")
            if isinstance(reason, str) and reason:
                by_reason[reason] += 1

        if run_events:
            recent_security_runs.append(
                _safe_recent_run(
                    snapshot=snapshot,
                    security_event_count=len(run_events),
                )
            )

    recent_security_runs.sort(key=lambda run: str(run["started_at"]), reverse=True)
    if recent_limit >= 0:
        recent_security_runs = recent_security_runs[:recent_limit]

    return SecuritySummary(
        run_count=run_count,
        runs_with_security_events=runs_with_security_events,
        security_event_count=sum(by_event_type.values()),
        threshold_stops=by_event_type["security_threshold_exceeded"],
        cooldowns_started=by_event_type["security_user_cooldown_started"],
        sandbox_failures=(
            by_event_type["document_sandbox_failure"]
            + by_event_type["document_sandbox_invalid_response"]
            + by_event_type["document_sandbox_output_too_large"]
            + by_event_type["document_sandbox_request_too_large"]
            + by_event_type["document_sandbox_stderr_too_large"]
            + by_event_type["document_sandbox_timeout"]
        ),
        by_event_type=dict(by_event_type),
        by_reason=dict(by_reason),
        by_document_kind=dict(by_document_kind),
        by_status=dict(by_status),
        recent_security_runs=recent_security_runs,
    )


def render_security_summary_markdown(summary: SecuritySummary) -> str:
    lines = [
        "# Security Summary",
        "",
        f"- Runs scanned: `{summary.run_count}`",
        f"- Runs with security events: `{summary.runs_with_security_events}`",
        f"- Security events: `{summary.security_event_count}`",
        f"- Threshold stops: `{summary.threshold_stops}`",
        f"- User cooldowns started: `{summary.cooldowns_started}`",
        f"- Sandbox failures: `{summary.sandbox_failures}`",
        "",
        "## Event Types",
        "",
        *_counter_lines(summary.by_event_type),
        "",
        "## Reasons",
        "",
        *_counter_lines(summary.by_reason),
        "",
        "## Document Kinds",
        "",
        *_counter_lines(summary.by_document_kind),
        "",
        "## Statuses",
        "",
        *_counter_lines(summary.by_status),
        "",
        "## Recent Security Runs",
        "",
    ]
    if not summary.recent_security_runs:
        lines.append("- none")
    for run in summary.recent_security_runs:
        lines.append(
            "- "
            f"job_id=`{run['job_id']}` "
            f"status=`{run['status']}` "
            f"document_kind=`{run['document_kind']}` "
            f"user_hash=`{run['user_hash']}` "
            f"security_events=`{run['security_event_count']}` "
            f"started_at=`{run['started_at']}`"
        )
    return "\n".join(lines) + "\n"


def _iter_run_dirs(root: Path):
    if not root.exists():
        return
    for path in sorted(root.iterdir()):
        if path.is_dir() and (path / "run.json").exists():
            yield path


def _load_run_snapshot(run_dir: Path) -> dict[str, Any] | None:
    try:
        snapshot = read_json_file(run_dir / "run.json")
    except (OSError, json.JSONDecodeError):
        return None
    return snapshot if isinstance(snapshot, dict) else None


def _load_security_events(run_dir: Path) -> list[dict[str, Any]]:
    events_path = run_dir / "events.jsonl"
    events: list[dict[str, Any]] = []
    try:
        lines = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event_type") == "security_event":
            events.append(event)
    return events


def _safe_recent_run(
    *,
    snapshot: dict[str, Any],
    security_event_count: int,
) -> dict[str, Any]:
    return {
        "job_id": str(snapshot.get("job_id") or "unknown"),
        "status": str(snapshot.get("status") or "unknown"),
        "document_kind": str(snapshot.get("document_kind") or "unknown"),
        "user_hash": _hash_label(str(snapshot.get("user_id") or "")),
        "security_event_count": security_event_count,
        "started_at": str(snapshot.get("started_at") or ""),
    }


def _counter_lines(counter: dict[str, int]) -> list[str]:
    if not counter:
        return ["- none"]
    return [
        f"- {key}: `{value}`"
        for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        if value
    ] or ["- none"]


def _hash_label(value: str) -> str:
    if not value:
        return "n/a"
    return sha256(value.encode("utf-8")).hexdigest()[:12]
