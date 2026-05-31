from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from translator_service.admin.bootstrap_config import AdminBootstrapConfig
from translator_service.admin.costs import BetaSafetyCostSummary
from translator_service.admin.integration_connections import (
    IntegrationConnectionSummary,
)
from translator_service.admin.integrations import IntegrationSummary
from translator_service.admin.provider_balance import ProviderBalanceSnapshot
from translator_service.admin.provider_health import _redact_sensitive_text
from translator_service.admin.provider_runtime import (
    AIProviderRuntimeReloadRequest,
    AIProviderRuntimeStatus,
)
from translator_service.admin.translation_logs import TranslationRunSummary
from translator_service.admin.translation_trace import trace_href_for_run_id

_REQUIRED_INTEGRATION_IDS = frozenset({"telegram"})
_RUNTIME_MISSING_CHANNEL_STATUSES = frozenset({"missing_keys"})
_RUNTIME_DEGRADED_STATUSES = frozenset({"degraded", "error", "failed"})
_FAILED_TRANSLATION_STATUSES = frozenset({"failed", "interrupted", "error"})
_FAILED_TRANSLATION_TRIAGE_LIMIT = 3
_HIGH_QUEUE_THRESHOLD = 10
_STALLED_QUEUE_SECONDS = 30 * 60


@dataclass(frozen=True)
class ActionItem:
    key: str
    severity: str
    title: str
    detail: str
    href: str
    affected: str = "System"
    reason: str = "Existing admin metadata raised this item."
    next_action: str = "Open"


@dataclass(frozen=True)
class ActionCenter:
    items: tuple[ActionItem, ...]


def build_action_center(
    *,
    integration_summaries: Sequence[IntegrationSummary],
    integration_connections: Mapping[
        str,
        Sequence[IntegrationConnectionSummary],
    ],
    failed_today: int,
    tokens_today: int,
    disk_percent: float | None,
    deepseek_key_count: int,
    failed_translation_runs: Sequence[TranslationRunSummary] | None = None,
    queued_translations: int = 0,
    oldest_pending_age_seconds: float | None = None,
    secret_safety_issue_count: int = 0,
    bootstrap_config: AdminBootstrapConfig | None = None,
    runtime_statuses: Sequence[AIProviderRuntimeStatus] | None = None,
    runtime_reload_states: Sequence[AIProviderRuntimeReloadRequest] | None = None,
    deepseek_balance_snapshot: ProviderBalanceSnapshot | None = None,
    deepseek_low_balance_threshold: Decimal | None = None,
    deepseek_low_balance_currency: str = "USD",
    deepseek_balance_stale_seconds: int = 300,
    beta_safety: BetaSafetyCostSummary | None = None,
    now: datetime | None = None,
) -> ActionCenter:
    items: list[ActionItem] = []
    current_time = now or datetime.now(UTC)
    effective_deepseek_key_count = _effective_deepseek_key_count(
        deepseek_key_count,
        bootstrap_config,
    )

    if _has_missing_required_integration(
        integration_summaries,
        integration_connections,
    ):
        items.append(
            ActionItem(
                key="integrations_missing",
                severity="action_needed",
                title="Required integrations need setup",
                detail="Add connection rows and required secrets before launch.",
                href="/admin/integrations",
                affected="Telegram integration",
                reason="Required integration has no healthy configured connection.",
                next_action="Open integrations",
            )
        )

    items.extend(
        _failed_translation_action_items(
            failed_today=failed_today,
            failed_translation_runs=failed_translation_runs or (),
        )
    )
    items.extend(
        _queue_action_items(
            queued_translations=queued_translations,
            oldest_pending_age_seconds=oldest_pending_age_seconds,
        )
    )

    if tokens_today >= 200_000:
        items.append(
            ActionItem(
                key="token_spend_high",
                severity="watch",
                title="Token spend is high",
                detail=f"{tokens_today:,} tokens used today.",
                href="/admin/live",
                affected="Beta cost guard",
                reason="Today's token volume crossed the overview watch threshold.",
                next_action="Open live",
            )
        )

    if disk_percent is not None and disk_percent >= 85:
        items.append(
            ActionItem(
                key="disk_high",
                severity="action_needed",
                title="Disk usage is high",
                detail=f"Server disk usage is {disk_percent:.1f}%.",
                href="/admin/live",
                affected="Server disk",
                reason="Disk usage crossed the 85% operations threshold.",
                next_action="Open live",
            )
        )

    if effective_deepseek_key_count == 0:
        items.append(
            ActionItem(
                key="ai_provider_missing",
                severity="blocked",
                title="DeepSeek keys missing",
                detail="Add at least one active DeepSeek key for translations.",
                href="/admin/ai-providers",
                affected="DeepSeek provider",
                reason="No active DeepSeek key is available for translation work.",
                next_action="Open provider",
            )
        )

    if secret_safety_issue_count > 0:
        items.append(
            ActionItem(
                key="secret_safety_issues",
                severity="action_needed",
                title="Secret safety needs review",
                detail=(
                    f"{secret_safety_issue_count} secret or key item(s) "
                    "need attention."
                ),
                href="/admin/settings",
                affected="Admin secrets and keys",
                reason="Secret safety metadata reported items needing review.",
                next_action="Open settings",
            )
        )

    if runtime_statuses is not None:
        items.extend(
            _runtime_action_items(
                deepseek_key_count=effective_deepseek_key_count,
                runtime_statuses=runtime_statuses,
                runtime_reload_states=runtime_reload_states or (),
                now=current_time,
            )
        )

    items.extend(
        _deepseek_balance_action_items(
            snapshot=deepseek_balance_snapshot,
            threshold=deepseek_low_balance_threshold,
            currency=deepseek_low_balance_currency,
            stale_seconds=deepseek_balance_stale_seconds,
            now=current_time,
        )
    )
    items.extend(_beta_safety_action_items(beta_safety))

    return ActionCenter(items=tuple(items))


def _failed_translation_action_items(
    *,
    failed_today: int,
    failed_translation_runs: Sequence[TranslationRunSummary],
) -> tuple[ActionItem, ...]:
    if failed_today <= 0:
        return ()
    traceable_runs = tuple(
        run
        for run in failed_translation_runs
        if run.status in _FAILED_TRANSLATION_STATUSES and _run_id(run)
    )
    if traceable_runs:
        return tuple(
            _failed_translation_action_item(run)
            for run in traceable_runs[:_FAILED_TRANSLATION_TRIAGE_LIMIT]
        )
    return (
        ActionItem(
            key="failed_translations",
            severity="investigate",
            title="Failed translations today",
            detail=f"{failed_today} translation run(s) need review.",
            href="/admin/logs?status=failed",
            affected=f"{failed_today} failed run(s)",
            reason="Live translation metadata counted failed runs today.",
            next_action="Open failed logs",
        ),
    )


def _failed_translation_action_item(run: TranslationRunSummary) -> ActionItem:
    run_id = _run_id(run)
    return ActionItem(
        key=f"failed_translation:{run_id}",
        severity="investigate",
        title="Translation failed",
        detail="Open the trace to inspect safe failure metadata and evidence.",
        href=trace_href_for_run_id(run_id),
        affected=f"{run.file_name or 'Unknown file'} · job {run.job_id or 'Unknown'}",
        reason="This run failed today and has a safe trace page.",
        next_action="Open trace",
    )


def _run_id(run: TranslationRunSummary) -> str:
    if not run.run_dir:
        return ""
    return Path(run.run_dir).name


def _queue_action_items(
    *,
    queued_translations: int,
    oldest_pending_age_seconds: float | None,
) -> tuple[ActionItem, ...]:
    queue_count = max(0, int(queued_translations))
    if (
        oldest_pending_age_seconds is not None
        and oldest_pending_age_seconds >= _STALLED_QUEUE_SECONDS
    ):
        age = _age_minutes_label(oldest_pending_age_seconds)
        return (
            ActionItem(
                key="translation_queue_stalled",
                severity="investigate",
                title="Translation queue may be stalled",
                detail=f"Oldest pending work has waited about {age}.",
                href="/admin/operations/jobs",
                affected=f"{queue_count} queued translations",
                reason=f"Oldest pending work unit age is about {age}.",
                next_action="Open operations",
            ),
        )
    if queue_count >= _HIGH_QUEUE_THRESHOLD:
        return (
            ActionItem(
                key="translation_queue_high",
                severity="watch",
                title="Translation queue is elevated",
                detail=f"{queue_count} translations are queued.",
                href="/admin/operations/jobs",
                affected=f"{queue_count} queued translations",
                reason="Queue depth crossed the overview watch threshold.",
                next_action="Open operations",
            ),
        )
    return ()


def _age_minutes_label(seconds: float) -> str:
    return f"{max(1, round(seconds / 60))}m"


def _effective_deepseek_key_count(
    deepseek_key_count: int,
    bootstrap_config: AdminBootstrapConfig | None,
) -> int:
    if deepseek_key_count > 0:
        return deepseek_key_count
    if bootstrap_config is None:
        return 0
    return bootstrap_config.deepseek_key_count


def _runtime_action_items(
    *,
    deepseek_key_count: int,
    runtime_statuses: Sequence[AIProviderRuntimeStatus],
    runtime_reload_states: Sequence[AIProviderRuntimeReloadRequest],
    now: datetime,
) -> tuple[ActionItem, ...]:
    if deepseek_key_count == 0:
        return ()
    runtime = _runtime_status(runtime_statuses, "deepseek")
    reload_state = _runtime_reload_state(runtime_reload_states, "deepseek")
    items: list[ActionItem] = []

    if runtime is None:
        items.append(
            ActionItem(
                key="ai_provider_runtime_not_reporting",
                severity="investigate",
                title="DeepSeek runtime is not reporting",
                detail="Bot or worker has not reported its live key pool yet.",
                href="/admin/ai-providers",
                affected="DeepSeek runtime",
                reason="Keys exist, but bot or worker has no live provider report.",
                next_action="Open provider",
            )
        )
    else:
        if _runtime_is_stale(runtime, now):
            items.append(
                ActionItem(
                    key="ai_provider_runtime_stale",
                    severity="watch",
                    title="DeepSeek runtime status is stale",
                    detail="Runtime has not refreshed its provider status recently.",
                    href="/admin/ai-providers",
                    affected="DeepSeek runtime",
                    reason="Runtime provider metadata has not refreshed recently.",
                    next_action="Open provider",
                )
            )
        if (
            not runtime.active_channels
            or runtime.status in _RUNTIME_MISSING_CHANNEL_STATUSES
        ):
            items.append(
                ActionItem(
                    key="ai_provider_runtime_missing_channels",
                    severity="blocked",
                    title="DeepSeek runtime has no active channels",
                    detail="Runtime cannot use an active DeepSeek channel right now.",
                    href="/admin/ai-providers",
                    affected="DeepSeek runtime",
                    reason="Runtime cannot use an active DeepSeek channel right now.",
                    next_action="Open provider",
                )
            )
        elif runtime.status in _RUNTIME_DEGRADED_STATUSES:
            items.append(
                ActionItem(
                    key="ai_provider_runtime_degraded",
                    severity="investigate",
                    title="DeepSeek runtime is degraded",
                    detail=(
                        "Runtime still reports active DeepSeek channels; review "
                        "provider/channel warning categories."
                    ),
                    href="/admin/ai-providers",
                    affected="DeepSeek provider",
                    reason=(
                        "Runtime still has active channels, but provider/channel "
                        "warnings are present."
                    ),
                    next_action="Open provider",
                )
            )

    if reload_state is not None and reload_state.pending:
        age_seconds = (now - reload_state.requested_at.astimezone(UTC)).total_seconds()
        if age_seconds >= _reload_pending_threshold(runtime):
            items.append(
                ActionItem(
                    key="ai_provider_runtime_reload_pending",
                    severity="watch",
                    title="DeepSeek reload is still pending",
                    detail="Runtime has not consumed the latest reload request yet.",
                    href="/admin/ai-providers",
                    affected="DeepSeek runtime",
                    reason=(
                        "A provider reload request is older than the runtime "
                        "threshold."
                    ),
                    next_action="Open provider",
                )
            )

    return tuple(items)


def _deepseek_balance_action_items(
    *,
    snapshot: ProviderBalanceSnapshot | None,
    threshold: Decimal | None,
    currency: str,
    stale_seconds: int,
    now: datetime,
) -> tuple[ActionItem, ...]:
    if snapshot is None:
        return ()
    items: list[ActionItem] = []
    href = "/admin/ai-providers"
    if snapshot.status == "not_configured":
        items.append(
            ActionItem(
                key="deepseek_balance_not_configured",
                severity="watch",
                title="DeepSeek balance is not configured",
                detail="Add an active DeepSeek key before relying on balance checks.",
                href=href,
                affected="DeepSeek balance",
                reason="Balance metadata cannot be checked without an active key.",
                next_action="Open provider",
            )
        )
    if snapshot.status == "failed":
        items.append(
            ActionItem(
                key="deepseek_balance_fetch_failed",
                severity="investigate",
                title="DeepSeek balance check failed",
                detail=_safe_balance_error_detail(snapshot.error_message),
                href=href,
                affected="DeepSeek balance",
                reason=(
                    "The latest cached balance refresh ended in a safe "
                    "failure state."
                ),
                next_action="Open provider",
            )
        )
    if snapshot.is_available is False:
        items.append(
            ActionItem(
                key="deepseek_balance_unavailable",
                severity="blocked",
                title="DeepSeek account is unavailable",
                detail="DeepSeek reports this account is not available for API use.",
                href=href,
                affected="DeepSeek account",
                reason="Provider balance metadata says the account is unavailable.",
                next_action="Open provider",
            )
        )
    age_seconds = (now - snapshot.last_checked_at.astimezone(UTC)).total_seconds()
    if age_seconds > max(1, stale_seconds):
        items.append(
            ActionItem(
                key="deepseek_balance_stale",
                severity="watch",
                title="DeepSeek balance is stale",
                detail="Refresh the provider account balance before beta use.",
                href=href,
                affected="DeepSeek balance",
                reason="Cached balance metadata is older than the stale threshold.",
                next_action="Open provider",
            )
        )
    if threshold is not None:
        wanted = currency.strip().upper()
        amount = next(
            (row for row in snapshot.balances if row.currency == wanted),
            None,
        )
        if amount is not None and amount.total_balance < threshold:
            items.append(
                ActionItem(
                    key="deepseek_balance_low",
                    severity="watch",
                    title="DeepSeek balance is low",
                    detail=f"{wanted} balance is {amount.total_balance}.",
                    href=href,
                    affected="DeepSeek balance",
                    reason=(
                        "Cached balance is below the configured low-balance "
                        "threshold."
                    ),
                    next_action="Open provider",
                )
            )
    return tuple(items)


def _safe_balance_error_detail(value: str | None) -> str:
    if value is None:
        return "The latest balance refresh failed."
    redacted = _redact_sensitive_text(value)
    return redacted or "The latest balance refresh failed."


def _beta_safety_action_items(
    beta_safety: BetaSafetyCostSummary | None,
) -> tuple[ActionItem, ...]:
    if beta_safety is None or not beta_safety.warning:
        return ()
    if beta_safety.translations_paused:
        return (
            ActionItem(
                key="beta_safety_paused",
                severity="blocked",
                title="Beta translations are paused",
                detail="New beta translation starts are blocked by live settings.",
                href="/admin/settings",
                affected="Beta controls",
                reason="Live beta settings currently block new translation starts.",
                next_action="Open settings",
            ),
        )
    return (
        ActionItem(
            key="beta_safety_budget_warning",
            severity="action_needed",
            title="Beta safety budget is near its cap",
            detail="Reserved and consumed beta spend is close to a global cap.",
            href="/admin/costs",
            affected="Beta cost guard",
            reason="Reserved and consumed beta spend is near a configured cap.",
            next_action="Open costs",
        ),
    )


def _runtime_status(
    statuses: Sequence[AIProviderRuntimeStatus],
    provider_id: str,
) -> AIProviderRuntimeStatus | None:
    return next(
        (status for status in statuses if status.provider_id == provider_id),
        None,
    )


def _runtime_reload_state(
    states: Sequence[AIProviderRuntimeReloadRequest],
    provider_id: str,
) -> AIProviderRuntimeReloadRequest | None:
    return next(
        (state for state in states if state.provider_id == provider_id),
        None,
    )


def _runtime_is_stale(runtime: AIProviderRuntimeStatus, now: datetime) -> bool:
    age_seconds = (now - runtime.last_reloaded_at.astimezone(UTC)).total_seconds()
    return age_seconds > max(120.0, runtime.reload_interval_seconds * 3)


def _reload_pending_threshold(runtime: AIProviderRuntimeStatus | None) -> float:
    if runtime is None:
        return 120.0
    return max(60.0, runtime.reload_interval_seconds * 2)


def _has_missing_required_integration(
    integration_summaries: Sequence[IntegrationSummary],
    integration_connections: Mapping[str, Sequence[IntegrationConnectionSummary]],
) -> bool:
    for summary in integration_summaries:
        if not _is_required_integration(summary):
            continue
        connections = integration_connections.get(summary.integration_id, ())
        if connections:
            has_healthy_connection = any(
                _is_healthy_connection(connection) for connection in connections
            )
            if not has_healthy_connection:
                return True
            continue
        if _has_missing_required_secret(summary):
            return True
    return False


def _is_required_integration(summary: IntegrationSummary) -> bool:
    return summary.integration_id in _REQUIRED_INTEGRATION_IDS


def _is_healthy_connection(connection: IntegrationConnectionSummary) -> bool:
    if not connection.enabled:
        return False
    required_secrets = tuple(
        secret for secret in connection.secret_values if secret.required
    )
    return bool(required_secrets) and all(
        secret.configured and not secret.disabled for secret in required_secrets
    )


def _has_missing_required_secret(summary: IntegrationSummary) -> bool:
    return any(
        secret.required and _is_missing_secret(secret)
        for secret in summary.secrets
    )


def _requires_connection(summary: IntegrationSummary) -> bool:
    return any(secret.required for secret in summary.secrets)


def _is_missing_secret(secret: Any) -> bool:
    status = getattr(secret, "status", None)
    if status == "missing":
        return True
    return bool(getattr(secret, "disabled", False)) or not bool(
        getattr(secret, "configured", False)
    )
