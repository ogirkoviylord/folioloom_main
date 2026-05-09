from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx


@dataclass(frozen=True)
class ProviderBalanceAmount:
    currency: str
    total_balance: Decimal
    granted_balance: Decimal
    topped_up_balance: Decimal


@dataclass(frozen=True)
class ProviderBalanceFetchResult:
    provider_id: str
    status: str
    is_available: bool | None
    balances: tuple[ProviderBalanceAmount, ...]
    checked_at: datetime
    error_code: str | None = None
    error_message: str | None = None


def fetch_deepseek_balance(
    provider_id: str,
    api_key: str,
    *,
    base_url: str = "https://api.deepseek.com",
    timeout_seconds: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> ProviderBalanceFetchResult:
    checked_at = datetime.now(UTC)
    if provider_id != "deepseek":
        return _failed(
            provider_id,
            checked_at,
            "unsupported_provider",
            "Unsupported provider.",
        )
    if not api_key:
        return _failed(
            provider_id,
            checked_at,
            "missing_key",
            "Provider API key is empty.",
        )
    try:
        with httpx.Client(
            timeout=max(0.1, timeout_seconds),
            transport=transport,
        ) as client:
            response = client.get(
                f"{base_url.rstrip('/')}/user/balance",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.TimeoutException:
        return _failed(
            provider_id,
            checked_at,
            "timeout",
            "Provider balance check timed out.",
        )
    except httpx.HTTPError:
        return _failed(
            provider_id,
            checked_at,
            "network_error",
            "Provider balance check failed before receiving a response.",
        )
    if response.status_code != 200:
        return _failed(
            provider_id,
            checked_at,
            f"http_{response.status_code}",
            f"Provider balance check returned HTTP {response.status_code}.",
        )
    try:
        payload = response.json()
        is_available = payload["is_available"]
        raw_balances = payload["balance_infos"]
        if not isinstance(is_available, bool) or not isinstance(raw_balances, list):
            raise ValueError("invalid balance payload")
        balances = tuple(_balance_amount(item) for item in raw_balances)
    except (KeyError, TypeError, ValueError, InvalidOperation):
        return _failed(
            provider_id,
            checked_at,
            "malformed_response",
            "Provider balance response was malformed.",
        )
    return ProviderBalanceFetchResult(
        provider_id=provider_id,
        status="ok",
        is_available=is_available,
        balances=balances,
        checked_at=checked_at,
    )


def _balance_amount(item: Any) -> ProviderBalanceAmount:
    if not isinstance(item, dict):
        raise ValueError("balance row must be an object")
    currency = str(item.get("currency", "")).strip().upper()
    if not currency:
        raise ValueError("balance currency is empty")
    return ProviderBalanceAmount(
        currency=currency,
        total_balance=_decimal(item.get("total_balance")),
        granted_balance=_decimal(item.get("granted_balance")),
        topped_up_balance=_decimal(item.get("topped_up_balance")),
    )


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _failed(
    provider_id: str,
    checked_at: datetime,
    error_code: str,
    error_message: str,
) -> ProviderBalanceFetchResult:
    return ProviderBalanceFetchResult(
        provider_id=provider_id,
        status="failed",
        is_available=None,
        balances=(),
        checked_at=checked_at,
        error_code=error_code,
        error_message=error_message,
    )
