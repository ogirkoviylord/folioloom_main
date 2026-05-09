from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class AIProviderProbeResult:
    status: str
    error: str | None = None


def validate_ai_provider_key(
    provider_id: str,
    api_key: str,
    *,
    base_url: str = "https://api.deepseek.com",
    timeout_seconds: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> AIProviderProbeResult:
    if provider_id != "deepseek":
        return AIProviderProbeResult(
            status="failed",
            error=f"Unsupported provider: {provider_id}",
        )
    if not api_key:
        return AIProviderProbeResult(
            status="failed",
            error="Provider API key is empty.",
        )
    try:
        with httpx.Client(
            timeout=max(0.1, timeout_seconds),
            transport=transport,
        ) as client:
            response = client.get(
                f"{base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.TimeoutException:
        return AIProviderProbeResult(
            status="cooldown",
            error="Provider health check timed out.",
        )
    except httpx.HTTPError:
        return AIProviderProbeResult(
            status="failed",
            error="Provider health check failed before receiving a response.",
        )
    if response.status_code == 200:
        return AIProviderProbeResult(status="provider_check_passed")
    if response.status_code == 429:
        return AIProviderProbeResult(
            status="cooldown",
            error="Provider health check returned HTTP 429.",
        )
    return AIProviderProbeResult(
        status="failed",
        error=f"Provider health check returned HTTP {response.status_code}.",
    )
