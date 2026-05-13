from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
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

_REQUIRED_INTEGRATION_IDS = frozenset({"telegram"})
_RUNTIME_DEGRADED_STATUSES = frozenset({"degraded", "error", "failed", "missing_keys"})


@dataclass(frozen=True)
class ActionItem:
    key: str
    severity: str
    title: str
    detail: str
    href: str


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
                severity="warning",
                title="Required integrations need setup",
                detail="Add connection rows and required secrets before launch.",
                href="/admin/integrations",
            )
        )

    if failed_today > 0:
        items.append(
            ActionItem(
                key="failed_translations",
                severity="critical",
                title="Failed translations today",
                detail=f"{failed_today} translation run(s) need review.",
                href="/admin/logs?status=failed",
            )
        )

    if tokens_today >= 200_000:
        items.append(
            ActionItem(
                key="token_spend_high",
                severity="warning",
                title="Token spend is high",
                detail=f"{tokens_today:,} tokens used today.",
                href="/admin/live",
            )
        )

    if disk_percent is not None and disk_percent >= 85:
        items.append(
            ActionItem(
                key="disk_high",
                severity="critical",
                title="Disk usage is high",
                detail=f"Server disk usage is {disk_percent:.1f}%.",
                href="/admin/live",
            )
        )

    if effective_deepseek_key_count == 0:
        items.append(
            ActionItem(
                key="ai_provider_missing",
                severity="critical",
                title="DeepSeek keys missing",
                detail="Add at least one active DeepSeek key for translations.",
                href="/admin/ai-providers",
            )
        )

    if secret_safety_issue_count > 0:
        items.append(
            ActionItem(
                key="secret_safety_issues",
                severity="warning",
                title="Secret safety needs review",
                detail=(
                    f"{secret_safety_issue_count} secret or key item(s) "
                    "need attention."
                ),
                href="/admin/settings",
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
                severity="warning",
                title="DeepSeek runtime is not reporting",
                detail="Bot or worker has not reported its live key pool yet.",
                href="/admin/ai-providers",
            )
        )
    else:
        if _runtime_is_stale(runtime, now):
            items.append(
                ActionItem(
                    key="ai_provider_runtime_stale",
                    severity="warning",
                    title="DeepSeek runtime status is stale",
                    detail="Runtime has not refreshed its provider status recently.",
                    href="/admin/live",
                )
            )
        if not runtime.active_channels or runtime.status in _RUNTIME_DEGRADED_STATUSES:
            items.append(
                ActionItem(
                    key="ai_provider_runtime_missing_channels",
                    severity="critical",
                    title="DeepSeek runtime has no active channels",
                    detail="Runtime cannot use an active DeepSeek channel right now.",
                    href="/admin/ai-providers",
                )
            )

    if reload_state is not None and reload_state.pending:
        age_seconds = (now - reload_state.requested_at.astimezone(UTC)).total_seconds()
        if age_seconds >= _reload_pending_threshold(runtime):
            items.append(
                ActionItem(
                    key="ai_provider_runtime_reload_pending",
                    severity="warning",
                    title="DeepSeek reload is still pending",
                    detail="Runtime has not consumed the latest reload request yet.",
                    href="/admin/ai-providers",
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
                severity="warning",
                title="DeepSeek balance is not configured",
                detail="Add an active DeepSeek key before relying on balance checks.",
                href=href,
            )
        )
    if snapshot.status == "failed":
        items.append(
            ActionItem(
                key="deepseek_balance_fetch_failed",
                severity="warning",
                title="DeepSeek balance check failed",
                detail=_safe_balance_error_detail(snapshot.error_message),
                href=href,
            )
        )
    if snapshot.is_available is False:
        items.append(
            ActionItem(
                key="deepseek_balance_unavailable",
                severity="critical",
                title="DeepSeek account is unavailable",
                detail="DeepSeek reports this account is not available for API use.",
                href=href,
            )
        )
    age_seconds = (now - snapshot.last_checked_at.astimezone(UTC)).total_seconds()
    if age_seconds > max(1, stale_seconds):
        items.append(
            ActionItem(
                key="deepseek_balance_stale",
                severity="warning",
                title="DeepSeek balance is stale",
                detail="Refresh the provider account balance before beta use.",
                href=href,
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
                    severity="warning",
                    title="DeepSeek balance is low",
                    detail=f"{wanted} balance is {amount.total_balance}.",
                    href=href,
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
                severity="critical",
                title="Beta translations are paused",
                detail="New beta translation starts are blocked by live settings.",
                href="/admin/settings",
            ),
        )
    return (
        ActionItem(
            key="beta_safety_budget_warning",
            severity="warning",
            title="Beta safety budget is near its cap",
            detail="Reserved and consumed beta spend is close to a global cap.",
            href="/admin/costs",
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
