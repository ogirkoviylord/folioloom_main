from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
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


@dataclass(frozen=True)
class ProviderBalanceSnapshot:
    provider_id: str
    status: str
    is_available: bool | None
    balances: tuple[ProviderBalanceAmount, ...]
    last_checked_at: datetime
    last_success_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None


class SQLiteProviderBalanceStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SQLiteProviderBalanceStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def get_snapshot(self, provider_id: str) -> ProviderBalanceSnapshot | None:
        row = self._connection.execute(
            """
            SELECT *
            FROM admin_provider_balance_snapshots
            WHERE provider_id = ?
            """,
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        return _snapshot_from_row(row)

    def save_snapshot(
        self,
        snapshot: ProviderBalanceSnapshot,
    ) -> ProviderBalanceSnapshot:
        previous = self.get_snapshot(snapshot.provider_id)
        last_success_at = snapshot.last_success_at
        if last_success_at is None and previous is not None:
            last_success_at = previous.last_success_at
        balances_json = json.dumps(
            [
                {
                    "currency": amount.currency,
                    "total_balance": str(amount.total_balance),
                    "granted_balance": str(amount.granted_balance),
                    "topped_up_balance": str(amount.topped_up_balance),
                }
                for amount in snapshot.balances
            ],
            sort_keys=True,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_provider_balance_snapshots (
                    provider_id, status, is_available, balances_json,
                    last_checked_at, last_success_at, error_code, error_message
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_id) DO UPDATE SET
                    status = excluded.status,
                    is_available = excluded.is_available,
                    balances_json = excluded.balances_json,
                    last_checked_at = excluded.last_checked_at,
                    last_success_at = excluded.last_success_at,
                    error_code = excluded.error_code,
                    error_message = excluded.error_message
                """,
                (
                    snapshot.provider_id,
                    snapshot.status,
                    (
                        None
                        if snapshot.is_available is None
                        else int(snapshot.is_available)
                    ),
                    balances_json,
                    snapshot.last_checked_at.isoformat(),
                    last_success_at.isoformat() if last_success_at else None,
                    snapshot.error_code,
                    snapshot.error_message,
                ),
            )
        saved = self.get_snapshot(snapshot.provider_id)
        if saved is None:
            raise RuntimeError("Provider balance snapshot was not saved")
        return saved

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_provider_balance_snapshots (
                    provider_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    is_available INTEGER,
                    balances_json TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL,
                    last_success_at TEXT,
                    error_code TEXT,
                    error_message TEXT
                )
                """
            )


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


def _snapshot_from_row(row: sqlite3.Row) -> ProviderBalanceSnapshot:
    raw_balances = json.loads(row["balances_json"])
    return ProviderBalanceSnapshot(
        provider_id=row["provider_id"],
        status=row["status"],
        is_available=(
            None if row["is_available"] is None else bool(row["is_available"])
        ),
        balances=tuple(_balance_amount(item) for item in raw_balances),
        last_checked_at=datetime.fromisoformat(row["last_checked_at"]),
        last_success_at=(
            datetime.fromisoformat(row["last_success_at"])
            if row["last_success_at"] is not None
            else None
        ),
        error_code=row["error_code"],
        error_message=row["error_message"],
    )


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
