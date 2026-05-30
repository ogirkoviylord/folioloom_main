from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from translator_service.admin.operations import OperationsOverview
from translator_service.admin.provider_balance import ProviderBalanceSnapshot
from translator_service.admin.provider_runtime import AIProviderRuntimeStatus
from translator_service.admin.translation_logs import (
    TranslationRunDetails,
    TranslationRunEvent,
)
from translator_service.user_activity import UserActivityEvent


@dataclass(frozen=True)
class TranslationTraceFact:
    label: str
    value: str


@dataclass(frozen=True)
class TranslationTraceTimelineItem:
    timestamp: datetime | None
    label: str
    detail: str


@dataclass(frozen=True)
class TranslationTraceProviderSignal:
    provider_id: str
    status: str
    active_channels: int
    degraded_channels: int
    safe_failure_categories: tuple[str, ...]
    balance_status: str
    has_incident_signal: bool


@dataclass(frozen=True)
class TranslationTraceLink:
    label: str
    href: str


@dataclass(frozen=True)
class TranslationTraceEvidencePacket:
    body: str
    file_name: str


@dataclass(frozen=True)
class TranslationTrace:
    run_id: str
    job_id: str
    status: str
    failure_category: str
    safe_error_summary: str
    summary_facts: tuple[TranslationTraceFact, ...]
    document_facts: tuple[TranslationTraceFact, ...]
    choice_facts: tuple[TranslationTraceFact, ...]
    job_facts: tuple[TranslationTraceFact, ...]
    provider: TranslationTraceProviderSignal | None
    timeline: tuple[TranslationTraceTimelineItem, ...]
    next_action: TranslationTraceLink
    advanced_links: tuple[TranslationTraceLink, ...]


def build_translation_trace(
    details: TranslationRunDetails,
    *,
    operations: OperationsOverview | None = None,
    activity_events: tuple[UserActivityEvent, ...] = (),
    runtime_statuses: tuple[AIProviderRuntimeStatus, ...] = (),
    balance_snapshot: ProviderBalanceSnapshot | None = None,
) -> TranslationTrace:
    summary = details.summary
    run_id = Path(details.run_dir).name
    job = _job_for_run(operations, summary.job_id)
    provider = _provider_signal(
        details,
        runtime_statuses=runtime_statuses,
        balance_snapshot=balance_snapshot,
    )
    safe_error_summary = _safe_error_summary(details, job)
    failure_category = _failure_category(details, job, provider, safe_error_summary)
    next_action = _next_action(run_id, failure_category, provider)
    return TranslationTrace(
        run_id=run_id,
        job_id=summary.job_id or "Unknown",
        status=summary.status or "Unknown",
        failure_category=failure_category,
        safe_error_summary=safe_error_summary,
        summary_facts=_summary_facts(details, run_id, failure_category, safe_error_summary),
        document_facts=_document_facts(details),
        choice_facts=_choice_facts(details),
        job_facts=_job_facts(job),
        provider=provider,
        timeline=_timeline(details.events, activity_events),
        next_action=next_action,
        advanced_links=_advanced_links(run_id, summary.job_id, summary.user_id),
    )


def trace_href_for_run_id(run_id: str) -> str:
    return f"/admin/translations/{quote(run_id, safe='')}/trace"


def evidence_href_for_run_id(run_id: str) -> str:
    return f"/admin/translations/{quote(run_id, safe='')}/evidence"


def trace_href_for_log_href(href: str | None) -> str | None:
    if not href or not href.startswith("/admin/logs/"):
        return None
    run_id = href.removeprefix("/admin/logs/").split("/", 1)[0]
    if not run_id:
        return None
    return trace_href_for_run_id(run_id)


def build_translation_trace_evidence_packet(
    trace: TranslationTrace,
) -> TranslationTraceEvidencePacket:
    incident = _fact_map(trace.summary_facts)
    document = _fact_map(trace.document_facts)
    choices = _fact_map(trace.choice_facts)
    job = _fact_map(trace.job_facts)
    provider = _provider_fact_map(trace.provider)
    links = {
        "Trace": trace_href_for_run_id(trace.run_id),
        **{link.label: link.href for link in trace.advanced_links},
    }
    body = "\n".join(
        (
            "# FolioLoom Translation Evidence Packet",
            "",
            "Metadata only: yes",
            "Format version: 1",
            "",
            "## Incident",
            f"- Run id: {_packet_value(trace.run_id)}",
            f"- Job id: {_packet_value(trace.job_id)}",
            f"- User: {_packet_value(incident.get('User'))}",
            f"- Order: {_packet_value(incident.get('Order'))}",
            f"- Status: {_packet_value(trace.status)}",
            f"- Failure category: {_packet_value(trace.failure_category)}",
            f"- Safe error summary: {_packet_value(trace.safe_error_summary)}",
            f"- Started at: {_packet_value(incident.get('Started at'))}",
            f"- Finished at: {_packet_value(incident.get('Finished at'))}",
            f"- Last event at: {_packet_value(incident.get('Last event at'))}",
            "",
            "## Document",
            f"- File: {_packet_value(document.get('File'))}",
            f"- Document kind: {_packet_value(document.get('Document kind'))}",
            f"- Fragments: {_packet_value(document.get('Fragments'))}",
            f"- Tokens: {_packet_value(document.get('Tokens'))}",
            "",
            "## Choices",
            f"- Source language: {_packet_value(choices.get('Source language'))}",
            f"- Target language: {_packet_value(choices.get('Target language'))}",
            f"- Detected source: {_packet_value(choices.get('Detected source'))}",
            f"- Translation policy: {_packet_value(choices.get('Translation policy'))}",
            f"- Quality route: {_packet_value(choices.get('Quality route'))}",
            "",
            "## Job",
            f"- Job state: {_packet_value(job.get('Job state'))}",
            f"- Work units: {_packet_value(job.get('Work units'))}",
            f"- Failed units: {_packet_value(job.get('Failed units'))}",
            f"- Active workers: {_packet_value(job.get('Active workers'))}",
            "",
            "## Provider",
            f"- Provider: {_packet_value(provider.get('Provider'))}",
            f"- Runtime status: {_packet_value(provider.get('Runtime status'))}",
            f"- Active channels: {_packet_value(provider.get('Active channels'))}",
            f"- Degraded channels: {_packet_value(provider.get('Degraded channels'))}",
            f"- Failure categories: {_packet_value(provider.get('Failure categories'))}",
            f"- Balance status: {_packet_value(provider.get('Balance status'))}",
            "",
            "## Links",
            *(
                f"- {label}: {href}"
                for label, href in links.items()
            ),
            "",
        )
    )
    return TranslationTraceEvidencePacket(
        body=body,
        file_name=f"{_safe_evidence_file_stem(trace.run_id)}-evidence.md",
    )


def _summary_facts(
    details: TranslationRunDetails,
    run_id: str,
    failure_category: str,
    safe_error_summary: str,
) -> tuple[TranslationTraceFact, ...]:
    summary = details.summary
    return (
        TranslationTraceFact("Run id", run_id),
        TranslationTraceFact("Job id", summary.job_id or "Unknown"),
        TranslationTraceFact("User", summary.user_id or "Unknown"),
        TranslationTraceFact("Order", summary.order_id or "Unknown"),
        TranslationTraceFact("Status", summary.status or "Unknown"),
        TranslationTraceFact("Failure category", failure_category),
        TranslationTraceFact("Safe error", safe_error_summary),
        TranslationTraceFact("Started at", _datetime_value(summary.started_at)),
        TranslationTraceFact("Finished at", _datetime_value(summary.finished_at)),
        TranslationTraceFact("Last event at", _datetime_value(summary.last_event_at)),
    )


def _document_facts(details: TranslationRunDetails) -> tuple[TranslationTraceFact, ...]:
    summary = details.summary
    return (
        TranslationTraceFact("File", summary.file_name or "Unknown"),
        TranslationTraceFact("Document kind", summary.document_kind or "Unknown"),
        TranslationTraceFact("Result file", summary.result_file_name or "Unknown"),
        TranslationTraceFact("Fragments", _fragment_label(details)),
        TranslationTraceFact("Tokens", str(summary.total_tokens)),
    )


def _choice_facts(details: TranslationRunDetails) -> tuple[TranslationTraceFact, ...]:
    summary = details.summary
    metadata = details.metadata
    return (
        TranslationTraceFact("Source language", summary.source_language or "Unknown"),
        TranslationTraceFact("Target language", summary.target_language or "Unknown"),
        TranslationTraceFact(
            "Detected source",
            _string(metadata.get("detected_source_language")) or "Unknown",
        ),
        TranslationTraceFact(
            "Translation policy",
            _string(metadata.get("translation_policy")) or "Unknown",
        ),
        TranslationTraceFact(
            "Quality route",
            _string(metadata.get("translation_quality_route")) or "Unknown",
        ),
    )


def _job_facts(job: Any | None) -> tuple[TranslationTraceFact, ...]:
    if job is None:
        return (
            TranslationTraceFact("Job state", "Unknown"),
            TranslationTraceFact("Work units", "Unknown"),
            TranslationTraceFact("Failed units", "Unknown"),
            TranslationTraceFact("Active workers", "Unknown"),
        )
    return (
        TranslationTraceFact("Job state", _string(getattr(job, "state", None)) or "Unknown"),
        TranslationTraceFact(
            "Work units",
            f"{getattr(job, 'completed_units', 0)}/{getattr(job, 'total_units', 0)}",
        ),
        TranslationTraceFact("Failed units", str(getattr(job, "failed_units", 0))),
        TranslationTraceFact(
            "Retryable",
            "yes" if bool(getattr(job, "retryable", False)) else "no",
        ),
        TranslationTraceFact(
            "Active workers",
            ", ".join(getattr(job, "active_worker_ids", ()) or ()) or "none",
        ),
    )


def _timeline(
    events: tuple[TranslationRunEvent, ...],
    activity_events: tuple[UserActivityEvent, ...],
) -> tuple[TranslationTraceTimelineItem, ...]:
    items: list[TranslationTraceTimelineItem] = []
    for event in events[-20:]:
        items.append(
            TranslationTraceTimelineItem(
                timestamp=event.timestamp,
                label=event.event_type or "unknown",
                detail=_event_detail(event.payload),
            )
        )
    for event in activity_events[:8]:
        detail = _activity_detail(event)
        items.append(
            TranslationTraceTimelineItem(
                timestamp=event.created_at,
                label=f"activity: {event.action}",
                detail=detail,
            )
        )
    items.sort(key=lambda item: item.timestamp.timestamp() if item.timestamp else 0.0)
    return tuple(items)


def _provider_signal(
    details: TranslationRunDetails,
    *,
    runtime_statuses: tuple[AIProviderRuntimeStatus, ...],
    balance_snapshot: ProviderBalanceSnapshot | None,
) -> TranslationTraceProviderSignal | None:
    provider_id = _provider_id(details)
    runtime = next(
        (status for status in runtime_statuses if status.provider_id == provider_id),
        None,
    )
    if runtime is None and provider_id != "deepseek":
        runtime = next(
            (status for status in runtime_statuses if status.provider_id == "deepseek"),
            None,
        )
    if runtime is None:
        return None

    categories = _provider_failure_categories(runtime)
    degraded_channels = sum(
        1
        for channel in runtime.active_channels
        if (channel.health or "").lower() not in {"healthy", "ok", "ready"}
        or bool(channel.error_kind)
        or bool(channel.last_error_excerpt)
    )
    has_incident_signal = (
        runtime.status.lower() not in {"ok", "healthy"}
        or degraded_channels > 0
        or bool(categories)
    )
    return TranslationTraceProviderSignal(
        provider_id=runtime.provider_id,
        status=runtime.status,
        active_channels=len(runtime.active_channels),
        degraded_channels=degraded_channels,
        safe_failure_categories=categories or ("none",),
        balance_status=(
            balance_snapshot.status
            if balance_snapshot is not None and balance_snapshot.provider_id == "deepseek"
            else "Unknown"
        ),
        has_incident_signal=has_incident_signal,
    )


def _failure_category(
    details: TranslationRunDetails,
    job: Any | None,
    provider: TranslationTraceProviderSignal | None,
    safe_error_summary: str,
) -> str:
    status = (details.summary.status or "").lower()
    security = details.security
    if status in {"cancelled", "canceled"}:
        return "Cancelled"
    if _positive_any(
        security,
        "unsafe_model_outputs",
        "model_output_repair_failures",
        "translation_batch_rejections",
        "security_threshold_exceeded",
    ):
        return "Model output safety"
    if _positive_any(
        security,
        "document_sandbox_timeouts",
        "document_sandbox_failures",
        "document_assembly_failures",
    ):
        return "Document processing"
    if provider is not None and provider.has_incident_signal and status == "failed":
        return "Provider"
    if _looks_provider_related(safe_error_summary) and status == "failed":
        return "Provider"
    if job is not None and getattr(job, "state", "") == "failed":
        return "Unknown"
    if status == "failed":
        return "Unknown"
    return "Not failed"


def _safe_error_summary(details: TranslationRunDetails, job: Any | None) -> str:
    candidates = [
        details.metadata.get("error_message"),
        getattr(job, "error_excerpt", None) if job is not None else None,
        *(fragment.error_message for fragment in details.fragments),
    ]
    for candidate in candidates:
        text = _safe_text(candidate)
        if text:
            return text
    return "Unknown"


def _event_detail(payload: dict[str, Any]) -> str:
    allowed = {
        "status",
        "sequence",
        "fragment_count",
        "total_fragments",
        "total_units",
        "elapsed_seconds",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "retry_count",
        "cache_hit",
        "security_event_type",
    }
    parts = []
    for key in sorted(allowed):
        if key in payload and payload[key] not in (None, "", {}, ()):
            parts.append(f"{key}={payload[key]}")
    return ", ".join(parts) or "Safe metadata only"


def _activity_detail(event: UserActivityEvent) -> str:
    parts = [
        f"outcome={event.outcome}",
        f"surface={event.surface}",
    ]
    if event.target_type:
        parts.append(f"target={event.target_type}")
    if event.target_id:
        parts.append(f"target_id={event.target_id}")
    if event.job_id:
        parts.append(f"job_id={event.job_id}")
    return ", ".join(parts)


def _provider_failure_categories(
    runtime: AIProviderRuntimeStatus,
) -> tuple[str, ...]:
    counters = {
        "rate_limit": sum(channel.total_rate_limit_failures for channel in runtime.active_channels),
        "auth": sum(channel.total_auth_failures for channel in runtime.active_channels),
        "billing": sum(channel.total_billing_failures for channel in runtime.active_channels),
        "timeout": sum(channel.total_timeout_failures for channel in runtime.active_channels),
        "unavailable": sum(channel.total_unavailable_failures for channel in runtime.active_channels),
        "malformed": sum(channel.total_malformed_response_failures for channel in runtime.active_channels),
        "unsafe_model_output": sum(channel.total_unsafe_model_output_failures for channel in runtime.active_channels),
        "other_provider": sum(channel.total_other_provider_failures for channel in runtime.active_channels),
    }
    return tuple(key for key, value in counters.items() if value > 0)


def _advanced_links(
    run_id: str,
    job_id: str | None,
    user_id: str | None,
) -> tuple[TranslationTraceLink, ...]:
    links = [
        TranslationTraceLink("Advanced log detail", f"/admin/logs/{quote(run_id, safe='')}"),
        TranslationTraceLink("Operations", "/admin/operations/jobs"),
    ]
    if job_id:
        links.append(
            TranslationTraceLink(
                "Activity for job",
                f"/admin/activity?job_id={quote(job_id, safe='')}",
            )
        )
    if user_id:
        links.append(
            TranslationTraceLink(
                "User profile",
                f"/admin/users/{quote(user_id, safe='')}",
            )
        )
    return tuple(links)


def _next_action(
    run_id: str,
    failure_category: str,
    provider: TranslationTraceProviderSignal | None,
) -> TranslationTraceLink:
    if failure_category == "Provider" or (
        provider is not None and provider.has_incident_signal
    ):
        return TranslationTraceLink("Open provider", "/admin/ai-providers")
    return TranslationTraceLink(
        "Review advanced log",
        f"/admin/logs/{quote(run_id, safe='')}",
    )


def _job_for_run(operations: OperationsOverview | None, job_id: str) -> Any | None:
    if operations is None:
        return None
    return next((job for job in operations.jobs if job.id == job_id), None)


def _fragment_label(details: TranslationRunDetails) -> str:
    summary = details.summary
    total = summary.total_fragment_count
    if total > 0:
        return f"{summary.fragment_count}/{total}"
    return f"{summary.fragment_count}/Unknown"


def _provider_id(details: TranslationRunDetails) -> str:
    model = (details.summary.translator_model or "").lower()
    if "deepseek" in model:
        return "deepseek"
    return "deepseek"


def _positive_any(values: dict[str, Any], *keys: str) -> bool:
    return any(_int(values.get(key)) > 0 for key in keys)


def _looks_provider_related(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in (
            "provider",
            "deepseek",
            "rate limit",
            "timeout",
            "billing",
            "auth",
            "unavailable",
            "malformed",
            "invalid translation batch",
        )
    )


_SENSITIVE_PATTERNS = (
    re.compile(r"(?is)\btraceback\b.*"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|secret_id|value)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9._-]+"),
    re.compile(r"\b[A-Za-z0-9._-]*api_keys[A-Za-z0-9._-]*\b"),
)


def _safe_text(value: Any) -> str | None:
    text = _string(value)
    if text is None:
        return None
    text = " ".join(text.split())
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text or None


def _fact_map(facts: tuple[TranslationTraceFact, ...]) -> dict[str, str]:
    return {fact.label: fact.value for fact in facts}


def _provider_fact_map(
    provider: TranslationTraceProviderSignal | None,
) -> dict[str, str]:
    if provider is None:
        return {
            "Provider": "Unknown",
            "Runtime status": "Unknown",
            "Active channels": "Unknown",
            "Degraded channels": "Unknown",
            "Failure categories": "Unknown",
            "Balance status": "Unknown",
        }
    return {
        "Provider": provider.provider_id,
        "Runtime status": provider.status,
        "Active channels": str(provider.active_channels),
        "Degraded channels": str(provider.degraded_channels),
        "Failure categories": ", ".join(provider.safe_failure_categories),
        "Balance status": provider.balance_status,
    }


def _packet_value(value: str | None) -> str:
    if value is None or value == "":
        return "Unknown"
    text = " ".join(str(value).split())
    return text or "Unknown"


def _datetime_value(value: datetime | None) -> str:
    if value is None:
        return "Unknown"
    return value.isoformat(timespec="seconds")


def _safe_evidence_file_stem(run_id: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", run_id).strip(".-")
    if not stem:
        return "translation"
    return stem[:120].rstrip(".-") or "translation"


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
