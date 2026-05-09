from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from translator_service.admin.ai_provider_keys import AIProviderKeySummary
from translator_service.admin.bootstrap_config import (
    AdminBootstrapConfig,
    is_env_deepseek_key,
)
from translator_service.admin.integration_connections import (
    IntegrationConnectionSummary,
)
from translator_service.admin.integrations import (
    IntegrationSecretSummary,
    IntegrationSummary,
)
from translator_service.admin.provider_health import ProviderHealthSummary


@dataclass(frozen=True)
class SecretSafetyItem:
    owner_label: str
    owner_type: str
    label: str
    kind: str
    status: str
    detail: str
    href: str
    masked_value: str | None = None


@dataclass(frozen=True)
class SecretSafetyReport:
    items: tuple[SecretSafetyItem, ...]
    total_count: int
    configured_count: int
    missing_count: int
    disabled_count: int
    needs_check_count: int
    failed_count: int
    issue_count: int


def build_secret_safety_report(
    *,
    integration_summaries: Sequence[IntegrationSummary],
    integration_connections: Mapping[
        str,
        Sequence[IntegrationConnectionSummary],
    ],
    ai_provider_key_pools: Mapping[str, Sequence[AIProviderKeySummary]],
    provider_health_summaries: Sequence[ProviderHealthSummary],
    bootstrap_config: AdminBootstrapConfig | None = None,
) -> SecretSafetyReport:
    items: list[SecretSafetyItem] = []
    bootstrap = bootstrap_config or AdminBootstrapConfig()
    items.extend(
        _integration_items(integration_summaries, integration_connections, bootstrap)
    )
    items.extend(
        _ai_provider_items(
            ai_provider_key_pools,
            provider_health_summaries,
            bootstrap,
        )
    )
    ordered = tuple(
        sorted(
            items,
            key=lambda item: (
                _status_order(item.status),
                item.owner_label,
                item.label,
            ),
        )
    )
    return SecretSafetyReport(
        items=ordered,
        total_count=len(ordered),
        configured_count=_count_status(ordered, "configured"),
        missing_count=_count_status(ordered, "missing"),
        disabled_count=_count_status(ordered, "disabled"),
        needs_check_count=_count_status(ordered, "needs_check"),
        failed_count=_count_status(ordered, "failed"),
        issue_count=sum(1 for item in ordered if item.status != "configured"),
    )


def _integration_items(
    integration_summaries: Sequence[IntegrationSummary],
    integration_connections: Mapping[str, Sequence[IntegrationConnectionSummary]],
    bootstrap_config: AdminBootstrapConfig,
) -> tuple[SecretSafetyItem, ...]:
    items: list[SecretSafetyItem] = []
    for summary in integration_summaries:
        connections = integration_connections.get(summary.integration_id, ())
        if connections:
            for connection in connections:
                items.extend(
                    _secret_items(
                        connection.secret_values,
                        owner_label=f"{summary.label} / {connection.label}",
                        owner_type="Integration connection",
                        href="/admin/integrations",
                        bootstrap_config=bootstrap_config,
                        integration_id=summary.integration_id,
                    )
                )
            continue
        items.extend(
            _secret_items(
                summary.secrets,
                owner_label=summary.label,
                owner_type="Integration",
                href="/admin/integrations",
                bootstrap_config=bootstrap_config,
                integration_id=summary.integration_id,
            )
        )
    return tuple(items)


def _secret_items(
    secrets: Sequence[IntegrationSecretSummary],
    *,
    owner_label: str,
    owner_type: str,
    href: str,
    bootstrap_config: AdminBootstrapConfig,
    integration_id: str,
) -> tuple[SecretSafetyItem, ...]:
    return tuple(
        SecretSafetyItem(
            owner_label=owner_label,
            owner_type=owner_type,
            label=secret.label,
            kind=secret.kind,
            status=_secret_status(secret, integration_id, bootstrap_config),
            detail=_secret_detail(secret, integration_id, bootstrap_config),
            href=href,
            masked_value=_secret_masked_value(secret, integration_id, bootstrap_config),
        )
        for secret in secrets
    )


def _ai_provider_items(
    key_pools: Mapping[str, Sequence[AIProviderKeySummary]],
    provider_health_summaries: Sequence[ProviderHealthSummary],
    bootstrap_config: AdminBootstrapConfig,
) -> tuple[SecretSafetyItem, ...]:
    health_by_provider = {
        health.provider_id: health for health in provider_health_summaries
    }
    items: list[SecretSafetyItem] = []
    seen_provider_ids: set[str] = set()
    for provider_id, keys in key_pools.items():
        seen_provider_ids.add(provider_id)
        health = health_by_provider.get(provider_id)
        owner_label = health.label if health else provider_id
        if not keys:
            if provider_id == "deepseek" and bootstrap_config.has_deepseek_keys:
                items.append(_deepseek_env_fallback_item(owner_label, bootstrap_config))
                continue
            items.append(
                SecretSafetyItem(
                    owner_label=owner_label,
                    owner_type="AI provider",
                    label="API key pool",
                    kind="api_key",
                    status="missing",
                    detail="No provider keys are configured.",
                    href="/admin/ai-providers",
                )
            )
            continue
        for key in keys:
            status = _provider_key_status(key, health)
            items.append(
                SecretSafetyItem(
                    owner_label=owner_label,
                    owner_type="AI provider key",
                    label=key.label,
                    kind="api_key",
                    status=status,
                    detail=_provider_key_detail(status, health),
                    href="/admin/ai-providers",
                    masked_value=key.masked_value,
                )
            )
    for provider_id, health in health_by_provider.items():
        if provider_id in seen_provider_ids:
            continue
        if provider_id == "deepseek" and bootstrap_config.has_deepseek_keys:
            items.append(_deepseek_env_fallback_item(health.label, bootstrap_config))
            continue
        items.append(
            SecretSafetyItem(
                owner_label=health.label,
                owner_type="AI provider",
                label="API key pool",
                kind="api_key",
                status="missing",
                detail="No provider keys are configured.",
                href="/admin/ai-providers",
            )
        )
    return tuple(items)


def _secret_status(
    secret: IntegrationSecretSummary,
    integration_id: str,
    bootstrap_config: AdminBootstrapConfig,
) -> str:
    if secret.disabled:
        return "disabled"
    if _is_telegram_env_fallback(secret, integration_id, bootstrap_config):
        return "configured"
    if not secret.configured:
        return "missing"
    return "configured"


def _secret_detail(
    secret: IntegrationSecretSummary,
    integration_id: str,
    bootstrap_config: AdminBootstrapConfig,
) -> str:
    if secret.disabled:
        return "Stored secret is disabled."
    if _is_telegram_env_fallback(secret, integration_id, bootstrap_config):
        return "Configured from env fallback."
    if not secret.configured:
        if secret.required:
            return "Required secret is not configured."
        return "Optional secret is not configured."
    return "Configured and available."


def _secret_masked_value(
    secret: IntegrationSecretSummary,
    integration_id: str,
    bootstrap_config: AdminBootstrapConfig,
) -> str | None:
    if _is_telegram_env_fallback(secret, integration_id, bootstrap_config):
        return "env fallback"
    return secret.masked_value


def _is_telegram_env_fallback(
    secret: IntegrationSecretSummary,
    integration_id: str,
    bootstrap_config: AdminBootstrapConfig,
) -> bool:
    return (
        integration_id == "telegram"
        and secret.secret_id == "telegram.bot_token"
        and not secret.configured
        and bootstrap_config.telegram_configured
    )


def _deepseek_env_fallback_item(
    owner_label: str,
    bootstrap_config: AdminBootstrapConfig,
) -> SecretSafetyItem:
    key_count = bootstrap_config.deepseek_key_count
    key_label = "key" if key_count == 1 else "keys"
    return SecretSafetyItem(
        owner_label=owner_label,
        owner_type="AI provider",
        label="API key pool",
        kind="api_key",
        status="configured",
        detail=f"{key_count} DeepSeek {key_label} configured from env fallback.",
        href="/admin/ai-providers",
        masked_value=f"env fallback ({key_count} {key_label})",
    )


def _provider_key_status(
    key: AIProviderKeySummary,
    health: ProviderHealthSummary | None,
) -> str:
    if is_env_deepseek_key(key):
        return "configured"
    if not key.enabled or key.disabled:
        return "disabled"
    if health is None or health.last_validation_status == "not checked":
        return "needs_check"
    if health.status == "degraded" or health.last_validation_status.lower() in {
        "failed",
        "failure",
        "error",
        "cooldown",
    }:
        return "failed"
    return "configured"


def _provider_key_detail(
    status: str,
    health: ProviderHealthSummary | None,
) -> str:
    if status == "disabled":
        return "Provider key is disabled or unavailable."
    if status == "needs_check":
        return "Run a local key test from AI Providers."
    if status == "failed":
        if health and health.last_error_excerpt != "n/a":
            return f"Last validation failed: {health.last_error_excerpt}"
        return "Last validation failed."
    return "Latest validation is healthy."


def _count_status(items: Sequence[SecretSafetyItem], status: str) -> int:
    return sum(1 for item in items if item.status == status)


def _status_order(status: str) -> int:
    return {
        "failed": 0,
        "disabled": 1,
        "missing": 2,
        "needs_check": 3,
        "configured": 4,
    }.get(status, 5)
