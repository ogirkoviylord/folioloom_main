from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from translator_service.admin.ai_provider_keys import AIProviderKeySummary
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
) -> SecretSafetyReport:
    items: list[SecretSafetyItem] = []
    items.extend(_integration_items(integration_summaries, integration_connections))
    items.extend(_ai_provider_items(ai_provider_key_pools, provider_health_summaries))
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
                    )
                )
            continue
        items.extend(
            _secret_items(
                summary.secrets,
                owner_label=summary.label,
                owner_type="Integration",
                href="/admin/integrations",
            )
        )
    return tuple(items)


def _secret_items(
    secrets: Sequence[IntegrationSecretSummary],
    *,
    owner_label: str,
    owner_type: str,
    href: str,
) -> tuple[SecretSafetyItem, ...]:
    return tuple(
        SecretSafetyItem(
            owner_label=owner_label,
            owner_type=owner_type,
            label=secret.label,
            kind=secret.kind,
            status=_secret_status(secret),
            detail=_secret_detail(secret),
            href=href,
            masked_value=secret.masked_value,
        )
        for secret in secrets
    )


def _ai_provider_items(
    key_pools: Mapping[str, Sequence[AIProviderKeySummary]],
    provider_health_summaries: Sequence[ProviderHealthSummary],
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


def _secret_status(secret: IntegrationSecretSummary) -> str:
    if secret.disabled:
        return "disabled"
    if not secret.configured:
        return "missing"
    return "configured"


def _secret_detail(secret: IntegrationSecretSummary) -> str:
    if secret.disabled:
        return "Stored secret is disabled."
    if not secret.configured:
        if secret.required:
            return "Required secret is not configured."
        return "Optional secret is not configured."
    return "Configured and available."


def _provider_key_status(
    key: AIProviderKeySummary,
    health: ProviderHealthSummary | None,
) -> str:
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
