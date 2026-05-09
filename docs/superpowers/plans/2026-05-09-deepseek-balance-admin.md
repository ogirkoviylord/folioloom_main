# DeepSeek Balance Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an owner-only DeepSeek account balance panel to the SSH-tunneled admin console.

**Architecture:** Implement a focused provider-balance module with an HTTP client, typed snapshots, SQLite persistence, and a refresh service. Wire cached snapshots into the AI Providers page, authenticated admin API, manual refresh route, audit log, and Action Center alerts without exposing secrets or creating user-facing billing.

**Tech Stack:** Python 3.13, FastAPI, httpx, SQLite, unittest, existing FolioLoom admin HTML rendering.

---

## File Structure

- Create `src/translator_service/admin/provider_balance.py`
  - DeepSeek balance dataclasses.
  - Safe DeepSeek balance HTTP fetch.
  - SQLite snapshot store.
  - Refresh service helpers.
- Modify `src/translator_service/config.py`
  - Add admin balance freshness, low-balance, currency, and top-up URL settings.
- Modify `src/translator_service/admin/routes.py`
  - Read cached snapshots for AI Providers and Action Center.
  - Add authenticated GET API and CSRF-protected POST refresh route.
  - Audit manual refresh.
- Modify `src/translator_service/admin/views.py`
  - Render DeepSeek balance panel in the provider card.
- Modify `src/translator_service/admin/action_center.py`
  - Add balance action items.
- Create `tests/test_admin_provider_balance.py`
  - Client, parser, store, and service tests.
- Modify `tests/test_admin_action_center.py`
  - Balance alert tests.
- Modify `tests/test_admin_routes.py`
  - Route and rendering tests.

## Task 1: Provider Balance Client And Types

**Files:**
- Create: `src/translator_service/admin/provider_balance.py`
- Test: `tests/test_admin_provider_balance.py`

- [ ] **Step 1: Write failing parser/client tests**

Add the initial test file:

```python
from __future__ import annotations

import unittest
from decimal import Decimal

import httpx

from translator_service.admin.provider_balance import fetch_deepseek_balance


class AdminProviderBalanceTest(unittest.TestCase):
    def test_fetches_deepseek_balance_with_bearer_auth(self):
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "is_available": True,
                    "balance_infos": [
                        {
                            "currency": "USD",
                            "total_balance": "12.34",
                            "granted_balance": "2.00",
                            "topped_up_balance": "10.34",
                        }
                    ],
                },
            )

        result = fetch_deepseek_balance(
            "deepseek",
            "sk-live-secret",
            base_url="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "ok")
        self.assertTrue(result.is_available)
        self.assertEqual(result.balances[0].currency, "USD")
        self.assertEqual(result.balances[0].total_balance, Decimal("12.34"))
        self.assertEqual(str(requests[0].url), "https://deepseek.test/user/balance")
        self.assertEqual(requests[0].headers["authorization"], "Bearer sk-live-secret")

    def test_failure_does_not_include_raw_key_or_response_body(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                json={"error": {"message": "bad key sk-live-secret"}},
            )

        result = fetch_deepseek_balance(
            "deepseek",
            "sk-live-secret",
            base_url="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "http_401")
        self.assertIn("HTTP 401", result.error_message or "")
        self.assertNotIn("sk-live-secret", result.error_message or "")
        self.assertNotIn("bad key", result.error_message or "")

    def test_malformed_response_is_safe_failure(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"is_available": True})

        result = fetch_deepseek_balance(
            "deepseek",
            "sk-live-secret",
            base_url="https://deepseek.test",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "malformed_response")
        self.assertEqual(result.balances, ())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance
```

Expected: import failure for `translator_service.admin.provider_balance`.

- [ ] **Step 3: Implement client and dataclasses**

Create `src/translator_service/admin/provider_balance.py` with:

```python
from __future__ import annotations

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
        return _failed(provider_id, checked_at, "unsupported_provider", "Unsupported provider.")
    if not api_key:
        return _failed(provider_id, checked_at, "missing_key", "Provider API key is empty.")
    try:
        with httpx.Client(timeout=max(0.1, timeout_seconds), transport=transport) as client:
            response = client.get(
                f"{base_url.rstrip('/')}/user/balance",
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.TimeoutException:
        return _failed(provider_id, checked_at, "timeout", "Provider balance check timed out.")
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
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance
```

Expected: tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/translator_service/admin/provider_balance.py tests/test_admin_provider_balance.py
git commit -m "feat: add DeepSeek balance client"
```

## Task 2: SQLite Snapshot Store

**Files:**
- Modify: `src/translator_service/admin/provider_balance.py`
- Modify: `tests/test_admin_provider_balance.py`

- [ ] **Step 1: Add failing store tests**

Append to `AdminProviderBalanceTest`:

```python
    def test_store_round_trips_balance_snapshot(self):
        from datetime import UTC, datetime
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from translator_service.admin.provider_balance import (
            ProviderBalanceSnapshot,
            SQLiteProviderBalanceStore,
        )

        checked_at = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteProviderBalanceStore(db_path) as store:
                store.save_snapshot(
                    ProviderBalanceSnapshot(
                        provider_id="deepseek",
                        status="ok",
                        is_available=True,
                        balances=(
                            store.amount_type(
                                currency="USD",
                                total_balance=Decimal("12.34"),
                                granted_balance=Decimal("2.00"),
                                topped_up_balance=Decimal("10.34"),
                            ),
                        ),
                        last_checked_at=checked_at,
                        last_success_at=checked_at,
                    )
                )
                loaded = store.get_snapshot("deepseek")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.status, "ok")
        self.assertEqual(loaded.balances[0].total_balance, Decimal("12.34"))

    def test_failed_snapshot_preserves_previous_success_time(self):
        from datetime import UTC, datetime
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from translator_service.admin.provider_balance import (
            ProviderBalanceSnapshot,
            SQLiteProviderBalanceStore,
        )

        success_at = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        failed_at = datetime(2026, 5, 9, 12, 5, tzinfo=UTC)
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteProviderBalanceStore(db_path) as store:
                store.save_snapshot(
                    ProviderBalanceSnapshot(
                        provider_id="deepseek",
                        status="ok",
                        is_available=True,
                        balances=(),
                        last_checked_at=success_at,
                        last_success_at=success_at,
                    )
                )
                store.save_snapshot(
                    ProviderBalanceSnapshot(
                        provider_id="deepseek",
                        status="failed",
                        is_available=None,
                        balances=(),
                        last_checked_at=failed_at,
                        error_code="timeout",
                        error_message="Provider balance check timed out.",
                    )
                )
                loaded = store.get_snapshot("deepseek")

        self.assertEqual(loaded.status, "failed")
        self.assertEqual(loaded.last_success_at, success_at)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance
```

Expected: `ProviderBalanceSnapshot` or `SQLiteProviderBalanceStore` missing.

- [ ] **Step 3: Add snapshot store**

Extend `provider_balance.py`:

```python
import json


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
    amount_type = ProviderBalanceAmount

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
            "SELECT * FROM admin_provider_balance_snapshots WHERE provider_id = ?",
            (provider_id,),
        ).fetchone()
        if row is None:
            return None
        return _snapshot_from_row(row)

    def save_snapshot(self, snapshot: ProviderBalanceSnapshot) -> ProviderBalanceSnapshot:
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
                    None if snapshot.is_available is None else int(snapshot.is_available),
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


def _snapshot_from_row(row: sqlite3.Row) -> ProviderBalanceSnapshot:
    raw_balances = json.loads(row["balances_json"])
    return ProviderBalanceSnapshot(
        provider_id=row["provider_id"],
        status=row["status"],
        is_available=None if row["is_available"] is None else bool(row["is_available"]),
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
```

- [ ] **Step 4: Run tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance
```

Expected: provider balance tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/translator_service/admin/provider_balance.py tests/test_admin_provider_balance.py
git commit -m "feat: store provider balance snapshots"
```

## Task 3: Settings And Refresh Service

**Files:**
- Modify: `src/translator_service/config.py`
- Modify: `src/translator_service/admin/provider_balance.py`
- Modify: `tests/test_admin_provider_balance.py`

- [ ] **Step 1: Add failing service test**

Append:

```python
    def test_refresh_service_uses_first_enabled_key_and_saves_snapshot(self):
        from base64 import urlsafe_b64encode
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
        from translator_service.admin.provider_balance import (
            SQLiteProviderBalanceStore,
            refresh_deepseek_balance,
        )
        from translator_service.admin.secrets import SQLiteEncryptedSecretStore
        from translator_service.config import Settings

        master_key = urlsafe_b64encode(b"4" * 32).decode("ascii")
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "is_available": True,
                    "balance_infos": [
                        {
                            "currency": "USD",
                            "total_balance": "8.50",
                            "granted_balance": "0",
                            "topped_up_balance": "8.50",
                        }
                    ],
                },
            )

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=master_key,
                deepseek_base_url="https://deepseek.test",
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=master_key) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="main",
                        plaintext="sk-main-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )
            snapshot = refresh_deepseek_balance(
                settings,
                transport=httpx.MockTransport(handler),
            )
            with SQLiteProviderBalanceStore(db_path) as store:
                loaded = store.get_snapshot("deepseek")

        self.assertEqual(snapshot.status, "ok")
        self.assertEqual(loaded.status, "ok")
        self.assertEqual(requests[0].headers["authorization"], "Bearer sk-main-secret")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance
```

Expected: missing `refresh_deepseek_balance`.

- [ ] **Step 3: Add settings**

In `src/translator_service/config.py`, add fields after provider probe/runtime settings:

```python
    admin_deepseek_balance_stale_seconds: int = field(
        default_factory=lambda: max(
            1,
            int(os.getenv("ADMIN_DEEPSEEK_BALANCE_STALE_SECONDS", "300")),
        )
    )
    admin_deepseek_low_balance_threshold: str = field(
        default_factory=lambda: os.getenv("ADMIN_DEEPSEEK_LOW_BALANCE_THRESHOLD", "5.00")
    )
    admin_deepseek_low_balance_currency: str = field(
        default_factory=lambda: os.getenv("ADMIN_DEEPSEEK_LOW_BALANCE_CURRENCY", "USD")
    )
    admin_deepseek_top_up_url: str = field(
        default_factory=lambda: os.getenv(
            "ADMIN_DEEPSEEK_TOP_UP_URL",
            "https://platform.deepseek.com/usage",
        )
    )
```

- [ ] **Step 4: Add refresh service**

Extend `provider_balance.py`:

```python
import os

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.secrets import (
    SecretNotFound,
    SecretStoreUnavailable,
    SQLiteEncryptedSecretStore,
)
from translator_service.config import Settings


def refresh_deepseek_balance(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
) -> ProviderBalanceSnapshot:
    api_key = _resolve_deepseek_api_key(settings)
    if api_key is None:
        snapshot = ProviderBalanceSnapshot(
            provider_id="deepseek",
            status="not_configured",
            is_available=None,
            balances=(),
            last_checked_at=datetime.now(UTC),
            error_code="missing_key",
            error_message="No active DeepSeek key is configured.",
        )
    else:
        result = fetch_deepseek_balance(
            "deepseek",
            api_key,
            base_url=settings.deepseek_base_url,
            timeout_seconds=settings.admin_provider_probe_timeout_seconds,
            transport=transport,
        )
        snapshot = ProviderBalanceSnapshot(
            provider_id=result.provider_id,
            status=("available" if result.is_available else "unavailable")
            if result.status == "ok"
            else result.status,
            is_available=result.is_available,
            balances=result.balances,
            last_checked_at=result.checked_at,
            last_success_at=result.checked_at if result.status == "ok" else None,
            error_code=result.error_code,
            error_message=result.error_message,
        )
    with SQLiteProviderBalanceStore(settings.admin_db_path) as store:
        return store.save_snapshot(snapshot)


def get_cached_deepseek_balance(settings: Settings) -> ProviderBalanceSnapshot | None:
    with SQLiteProviderBalanceStore(settings.admin_db_path) as store:
        return store.get_snapshot("deepseek")


def _resolve_deepseek_api_key(settings: Settings) -> str | None:
    if settings.admin_secret_master_key:
        try:
            with SQLiteEncryptedSecretStore(
                settings.admin_db_path,
                master_key=settings.admin_secret_master_key,
            ) as secrets:
                with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                    for key in keys.list_keys(
                        "deepseek",
                        secret_describer=secrets.describe_secret,
                    ):
                        if key.enabled and not key.disabled:
                            return secrets.get_secret_value(key.secret_id)
        except (SecretNotFound, SecretStoreUnavailable, ValueError, KeyError):
            return None
    key_list = os.getenv("DEEPSEEK_API_KEYS", "")
    for value in key_list.split(","):
        if value.strip():
            return value.strip()
    single_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if single_key:
        return single_key
    return None
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/translator_service/config.py src/translator_service/admin/provider_balance.py tests/test_admin_provider_balance.py
git commit -m "feat: refresh DeepSeek balance snapshots"
```

## Task 4: Admin Routes And Audit

**Files:**
- Modify: `src/translator_service/admin/routes.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Add failing route tests**

Add route tests near existing admin API tests:

```python
    def test_admin_balance_api_requires_login(self):
        with patch(
            "translator_service.admin.routes._deepseek_balance_snapshot",
            side_effect=AssertionError("balance snapshot should be lazy"),
        ) as snapshot:
            response = self.client.get("/admin/api/ai-providers/deepseek/balance")

        self.assertEqual(response.status_code, 401)
        snapshot.assert_not_called()

    def test_owner_can_read_cached_deepseek_balance(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        with patch(
            "translator_service.admin.routes._deepseek_balance_payload",
            return_value={"provider_id": "deepseek", "status": "not_configured"},
        ):
            response = self.client.get("/admin/api/ai-providers/deepseek/balance")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"]["status"], "not_configured")

    def test_refresh_deepseek_balance_requires_csrf(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        response = self.client.post(
            "/admin/ai-providers/deepseek/balance/refresh",
            data={"csrf_token": "bad"},
        )

        self.assertEqual(response.status_code, 403)

    def test_owner_can_refresh_deepseek_balance(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        page = self.client.get("/admin/ai-providers")
        csrf = _csrf_token(page.text)

        with patch(
            "translator_service.admin.routes.refresh_deepseek_balance",
        ) as refresh:
            refresh.return_value = SimpleNamespace(
                provider_id="deepseek",
                status="available",
                is_available=True,
                balances=(SimpleNamespace(currency="USD"),),
                last_checked_at=datetime(2026, 5, 9, tzinfo=UTC),
                last_success_at=datetime(2026, 5, 9, tzinfo=UTC),
                error_code=None,
                error_message=None,
            )
            response = self.client.post(
                "/admin/ai-providers/deepseek/balance/refresh",
                data={"csrf_token": csrf},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/ai-providers")
        refresh.assert_called_once()
```

- [ ] **Step 2: Run route tests to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_routes
```

Expected: missing routes/helpers.

- [ ] **Step 3: Import provider balance helpers**

In `routes.py`, add:

```python
from translator_service.admin.provider_balance import (
    ProviderBalanceSnapshot,
    get_cached_deepseek_balance,
    refresh_deepseek_balance,
)
```

- [ ] **Step 4: Pass balance snapshot into AI Providers body**

Change the `/admin/ai-providers` body call:

```python
                balance_snapshot=_deepseek_balance_snapshot(settings),
                balance_stale_seconds=settings.admin_deepseek_balance_stale_seconds,
                top_up_url=settings.admin_deepseek_top_up_url,
```

- [ ] **Step 5: Add routes**

Inside `create_admin_router`, add before generic provider POST routes:

```python
    @router.get("/api/ai-providers/deepseek/balance")
    async def deepseek_balance_api(request: Request) -> JSONResponse:
        if _session_or_none(request, session_manager) is None:
            return _json({"error": "unauthorized"}, status_code=HTTPStatus.UNAUTHORIZED)
        return _json({"balance": _deepseek_balance_payload(settings)})

    @router.post("/ai-providers/deepseek/balance/refresh")
    async def refresh_deepseek_balance_route(request: Request) -> Response:
        session = _session_or_none(request, session_manager)
        if session is None:
            return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
        form = await _urlencoded_form(request)
        if not session_manager.verify_csrf(session, form.get("csrf_token")):
            return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
        snapshot = refresh_deepseek_balance(settings)
        with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
            audit.record(
                actor_id=session.actor_id,
                role=session.role,
                action="ai_provider.balance.refreshed",
                target_type="ai_provider",
                target_id="deepseek",
                outcome=(
                    AuditOutcome.SUCCESS
                    if snapshot.status in {"available", "unavailable"}
                    else AuditOutcome.FAILURE
                ),
                metadata={
                    "provider_id": "deepseek",
                    "status": snapshot.status,
                    "is_available": snapshot.is_available,
                    "currency_count": len(snapshot.balances),
                    "error_code": snapshot.error_code,
                },
            )
        return RedirectResponse("/admin/ai-providers", status_code=HTTPStatus.SEE_OTHER)
```

- [ ] **Step 6: Add route helpers**

Add below runtime payload helpers:

```python
def _deepseek_balance_snapshot(settings: Settings) -> ProviderBalanceSnapshot | None:
    return get_cached_deepseek_balance(settings)


def _deepseek_balance_payload(settings: Settings):
    snapshot = _deepseek_balance_snapshot(settings)
    if snapshot is None:
        return {"provider_id": "deepseek", "status": "not_checked"}
    return {
        "provider_id": snapshot.provider_id,
        "status": snapshot.status,
        "is_available": snapshot.is_available,
        "balances": [
            {
                "currency": amount.currency,
                "total_balance": str(amount.total_balance),
                "granted_balance": str(amount.granted_balance),
                "topped_up_balance": str(amount.topped_up_balance),
            }
            for amount in snapshot.balances
        ],
        "last_checked_at": snapshot.last_checked_at.isoformat(),
        "last_success_at": (
            snapshot.last_success_at.isoformat()
            if snapshot.last_success_at is not None
            else None
        ),
        "error_code": snapshot.error_code,
        "error_message": snapshot.error_message,
    }
```

- [ ] **Step 7: Run route tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_routes
```

Expected: route tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/translator_service/admin/routes.py tests/test_admin_routes.py
git commit -m "feat: expose DeepSeek balance admin routes"
```

## Task 5: Admin UI Panel

**Files:**
- Modify: `src/translator_service/admin/views.py`
- Modify: `tests/test_admin_routes.py`

- [ ] **Step 1: Add failing render test**

Add to `tests/test_admin_routes.py`:

```python
    def test_ai_providers_page_renders_deepseek_balance_panel(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})

        with patch(
            "translator_service.admin.routes._deepseek_balance_snapshot",
        ) as snapshot:
            snapshot.return_value = SimpleNamespace(
                provider_id="deepseek",
                status="available",
                is_available=True,
                balances=(
                    SimpleNamespace(
                        currency="USD",
                        total_balance=Decimal("8.50"),
                        granted_balance=Decimal("0"),
                        topped_up_balance=Decimal("8.50"),
                    ),
                ),
                last_checked_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                last_success_at=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                error_code=None,
                error_message=None,
            )
            response = self.client.get("/admin/ai-providers")

        self.assertEqual(response.status_code, 200)
        self.assertIn("DeepSeek account balance", response.text)
        self.assertIn("8.50", response.text)
        self.assertIn("Refresh balance", response.text)
        self.assertNotIn("sk-", response.text)
```

Add this import near the top of `tests/test_admin_routes.py`:

```python
from decimal import Decimal
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_routes
```

Expected: balance panel text missing.

- [ ] **Step 3: Update view signature**

In `views.py`, import `ProviderBalanceSnapshot`:

```python
from translator_service.admin.provider_balance import ProviderBalanceSnapshot
```

Update `ai_providers_body` signature:

```python
    balance_snapshot: ProviderBalanceSnapshot | None = None,
    balance_stale_seconds: int = 300,
    top_up_url: str = "https://platform.deepseek.com/usage",
```

Pass these into `_ai_provider_card`.

- [ ] **Step 4: Render balance panel for DeepSeek**

Add to `_ai_provider_card`:

```python
    balance_panel = ""
    if summary.integration_id == "deepseek":
        balance_panel = _provider_balance_panel(
            balance_snapshot,
            csrf_token=csrf_token,
            stale_seconds=balance_stale_seconds,
            top_up_url=top_up_url,
        )
```

Place `{balance_panel}` after `{runtime_panel}`.

Add helper:

```python
def _provider_balance_panel(
    snapshot: ProviderBalanceSnapshot | None,
    *,
    csrf_token: str,
    stale_seconds: int,
    top_up_url: str,
) -> str:
    if snapshot is None:
        status = "not checked"
        rows = '<p class="empty-state">No DeepSeek balance snapshot yet.</p>'
        checked = "n/a"
        success = "n/a"
        error = "n/a"
    else:
        status = snapshot.status.replace("_", " ")
        rows = "\n".join(_balance_metric_row(amount) for amount in snapshot.balances)
        if not rows:
            rows = '<p class="empty-state">No currency balances reported.</p>'
        checked = snapshot.last_checked_at.isoformat(timespec="seconds")
        success = (
            snapshot.last_success_at.isoformat(timespec="seconds")
            if snapshot.last_success_at is not None
            else "n/a"
        )
        error = snapshot.error_message or "n/a"
    safe_top_up = _safe_external_href(top_up_url)
    return f"""
      <div class="provider-health">
        <div>
          <h4>DeepSeek account balance</h4>
          <span class="status">{escape(status)}</span>
        </div>
        <div class="metric-grid">
          {rows}
          <div class="metric-card">
            <span>Last checked</span>
            <strong>{escape(checked)}</strong>
          </div>
          <div class="metric-card">
            <span>Last success</span>
            <strong>{escape(success)}</strong>
          </div>
          <div class="metric-card">
            <span>Error</span>
            <strong>{escape(error)}</strong>
          </div>
        </div>
        <form class="secret-form" method="post"
          action="/admin/ai-providers/deepseek/balance/refresh">
          <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
          <button type="submit">Refresh balance</button>
          <a class="table-action" href="{escape(safe_top_up)}" rel="noreferrer">
            Open DeepSeek top-up
          </a>
        </form>
      </div>
    """


def _balance_metric_row(amount) -> str:
    return f"""
      <div class="metric-card">
        <span>{escape(amount.currency)} total</span>
        <strong>{escape(str(amount.total_balance))}</strong>
        <span>granted {escape(str(amount.granted_balance))} · top-up {escape(str(amount.topped_up_balance))}</span>
      </div>
    """


def _safe_external_href(value: str) -> str:
    if value.startswith("https://"):
        return value
    return "https://platform.deepseek.com/usage"
```

- [ ] **Step 5: Run route/render tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_routes
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/translator_service/admin/views.py tests/test_admin_routes.py
git commit -m "feat: render DeepSeek balance in admin"
```

## Task 6: Action Center Alerts

**Files:**
- Modify: `src/translator_service/admin/action_center.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `tests/test_admin_action_center.py`

- [ ] **Step 1: Add failing Action Center tests**

In `tests/test_admin_action_center.py`, import `Decimal`, `ProviderBalanceAmount`,
and `ProviderBalanceSnapshot`, then add:

```python
    def test_low_deepseek_balance_creates_action(self):
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            deepseek_balance_snapshot=ProviderBalanceSnapshot(
                provider_id="deepseek",
                status="available",
                is_available=True,
                balances=(
                    ProviderBalanceAmount(
                        currency="USD",
                        total_balance=Decimal("1.25"),
                        granted_balance=Decimal("0"),
                        topped_up_balance=Decimal("1.25"),
                    ),
                ),
                last_checked_at=now,
                last_success_at=now,
            ),
            deepseek_low_balance_threshold=Decimal("5.00"),
            deepseek_low_balance_currency="USD",
            deepseek_balance_stale_seconds=300,
            now=now,
        )

        self.assertIn("deepseek_balance_low", [item.key for item in center.items])

    def test_unavailable_and_stale_deepseek_balance_create_actions(self):
        now = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)
        center = build_action_center(
            integration_summaries=(),
            integration_connections={},
            failed_today=0,
            tokens_today=0,
            disk_percent=10.0,
            deepseek_key_count=1,
            deepseek_balance_snapshot=ProviderBalanceSnapshot(
                provider_id="deepseek",
                status="unavailable",
                is_available=False,
                balances=(),
                last_checked_at=now - timedelta(minutes=10),
                last_success_at=now - timedelta(minutes=10),
            ),
            deepseek_low_balance_threshold=Decimal("5.00"),
            deepseek_low_balance_currency="USD",
            deepseek_balance_stale_seconds=300,
            now=now,
        )

        keys = [item.key for item in center.items]
        self.assertIn("deepseek_balance_unavailable", keys)
        self.assertIn("deepseek_balance_stale", keys)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_action_center
```

Expected: `build_action_center` does not accept balance arguments.

- [ ] **Step 3: Extend Action Center**

In `action_center.py`, import `Decimal` and `ProviderBalanceSnapshot`. Extend
`build_action_center` with:

```python
    deepseek_balance_snapshot: ProviderBalanceSnapshot | None = None,
    deepseek_low_balance_threshold: Decimal | None = None,
    deepseek_low_balance_currency: str = "USD",
    deepseek_balance_stale_seconds: int = 300,
```

Before return:

```python
    items.extend(
        _deepseek_balance_action_items(
            snapshot=deepseek_balance_snapshot,
            threshold=deepseek_low_balance_threshold,
            currency=deepseek_low_balance_currency,
            stale_seconds=deepseek_balance_stale_seconds,
            now=current_time,
        )
    )
```

Add helper:

```python
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
                detail=snapshot.error_message or "The latest balance refresh failed.",
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
        amount = next((row for row in snapshot.balances if row.currency == wanted), None)
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
```

- [ ] **Step 4: Pass balance into Action Center from routes**

In `_overview_action_center`, add:

```python
        deepseek_balance_snapshot=_deepseek_balance_snapshot(settings),
        deepseek_low_balance_threshold=_decimal_setting(
            settings.admin_deepseek_low_balance_threshold
        ),
        deepseek_low_balance_currency=settings.admin_deepseek_low_balance_currency,
        deepseek_balance_stale_seconds=settings.admin_deepseek_balance_stale_seconds,
```

Add helper:

```python
def _decimal_setting(value: str):
    try:
        return Decimal(str(value))
    except Exception:
        return None
```

Import `Decimal`.

- [ ] **Step 5: Run Action Center tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_action_center
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/translator_service/admin/action_center.py src/translator_service/admin/routes.py tests/test_admin_action_center.py
git commit -m "feat: alert on DeepSeek balance status"
```

## Task 7: Final Verification

**Files:**
- Review all modified files.

- [ ] **Step 1: Run focused balance tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance tests.test_admin_action_center tests.test_admin_routes
```

Expected: all tests pass.

- [ ] **Step 2: Run full unittest suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: full suite passes.

- [ ] **Step 3: Compile source**

Run:

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: compile succeeds.

- [ ] **Step 4: Run predeploy gate**

Run:

```bash
scripts/predeploy_check.sh
```

Expected: predeploy check passes.

- [ ] **Step 5: Confirm security invariants**

Run:

```bash
rg -n "sk-live-secret|sk-main-secret|Authorization|response.text|response.content" src/translator_service/admin tests/test_admin_provider_balance.py
```

Expected:

- Test fixture keys may appear only in tests.
- `Authorization` appears only where request headers are built or asserted.
- Provider balance code does not log `response.text` or `response.content`.

- [ ] **Step 6: Commit final fixes if needed**

```bash
git add src/translator_service/admin tests/test_admin_provider_balance.py tests/test_admin_action_center.py tests/test_admin_routes.py
git commit -m "test: verify DeepSeek balance admin workflow"
```

Only make this commit if verification required additional fixes.
