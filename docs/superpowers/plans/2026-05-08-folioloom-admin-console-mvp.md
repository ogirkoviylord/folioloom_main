# FolioLoom Admin Console MVP Implementation Plan


**Goal:** Build the first browser admin console for FolioLoom with owner login, RBAC-shaped route protection, encrypted secret storage, integration/status pages, service settings, operations controls, and audit/security views.

**Architecture:** Build the shared admin backbone first, then split feature slices across agents. Use FastAPI for admin routes and server-rendered MVP HTML plus JSON endpoints. Use a `SecretStore` abstraction with encrypted SQLite storage for MVP and keep future managed secret stores behind the same interface.

**Tech Stack:** Python 3.13, FastAPI, SQLite, unittest, `cryptography` AES-GCM, existing FolioLoom persistent job store, existing DeepSeek key pool snapshots, existing security telemetry sanitizers.

---

## Agent Strategy

Do not start agents until the owner approves this plan.

Use one coordinator for Task 1, Task 2, and Task 3 because they define the admin backbone: shared domain types, encrypted secret storage, auth/session behavior, route shell, and shared page layout contracts. Do not dispatch parallel feature agents until those tasks are merged and tests pass. After the backbone is stable, split Tasks 4-6 across agents with disjoint file ownership.

Recommended agent ownership:

- **Coordinator:** Task 1, Task 2, and Task 3. Owns admin package foundations, auth, RBAC, settings, secrets, audit, route shell, and route contracts.
- **Integrations Agent:** Task 4. Owns integration registry and integration endpoints/pages after the backbone is merged.
- **Operations Agent:** Task 5. Owns operations service and job/worker endpoints/pages.
- **UI Agent:** Task 6. Owns shared HTML rendering and page layout after route contracts exist.
- **Security/Test Agent:** Task 6 review pass and final verification. Owns security regression coverage and cross-slice verification.


## File Structure

Create a focused admin package:

- `src/translator_service/admin/__init__.py`: package marker.
- `src/translator_service/admin/rbac.py`: roles, permissions, role-to-permission mapping, permission checks.
- `src/translator_service/admin/audit.py`: audit event dataclass and SQLite audit log.
- `src/translator_service/admin/settings.py`: setting definitions, apply modes, persisted values, SQLite settings store.
- `src/translator_service/admin/secrets.py`: `SecretStore` protocol, metadata dataclasses, AES-GCM SQLite implementation, masking and fingerprint helpers.
- `src/translator_service/admin/auth.py`: bootstrap owner login, signed session cookie, CSRF token validation.
- `src/translator_service/admin/integrations.py`: integration registry, categories, DeepSeek and Telegram metadata projection.
- `src/translator_service/admin/operations.py`: job/worker overview, retry and cancel eligibility, safe job summaries.
- `src/translator_service/admin/views.py`: small server-rendered HTML helpers for MVP pages.
- `src/translator_service/admin/routes.py`: FastAPI router and JSON endpoints under `/admin` and `/admin/api`.

Modify existing files:

- `src/translator_service/api.py`: include admin router and pass `Settings`.
- `src/translator_service/config.py`: add `admin_db_path`, `admin_session_secret`, `admin_owner_password`, and `admin_secret_master_key` env-backed settings.
- `src/translator_service/persistent_jobs.py`: add list helper for worker heartbeats so Operations can render worker health.
- `pyproject.toml`: add `cryptography>=42`.

Tests:

- `tests/test_admin_rbac.py`
- `tests/test_admin_audit.py`
- `tests/test_admin_settings.py`
- `tests/test_admin_secrets.py`
- `tests/test_admin_auth.py`
- `tests/test_admin_integrations.py`
- `tests/test_admin_operations.py`
- `tests/test_admin_routes.py`

---

## Centralized Backbone Gate

Tasks 1-3 must be implemented centrally before any feature agents are launched. This is the admin console backbone:

- Task 1 defines roles, permissions, audit logging, setting definitions, and admin configuration.
- Task 2 defines the encrypted `SecretStore` abstraction and MVP database-backed secret storage.
- Task 3 defines owner login, session handling, CSRF behavior, base admin routes, and shared page shell.

After Task 3 passes, feature agents may work in parallel on Task 4 and Task 5. Task 6 should run after both slices are integrated because it verifies cross-slice UI and security behavior.

## Task 1: Admin Core Domain

**Owner:** Coordinator.

**Files:**
- Create: `src/translator_service/admin/__init__.py`
- Create: `src/translator_service/admin/rbac.py`
- Create: `src/translator_service/admin/audit.py`
- Create: `src/translator_service/admin/settings.py`
- Modify: `src/translator_service/config.py`
- Test: `tests/test_admin_rbac.py`
- Test: `tests/test_admin_audit.py`
- Test: `tests/test_admin_settings.py`

- [ ] **Step 1: Write RBAC tests**

Create `tests/test_admin_rbac.py`:

```python
import unittest

from translator_service.admin.rbac import AdminPermission, AdminRole, has_permission


class AdminRbacTest(unittest.TestCase):
    def test_owner_has_all_mvp_permissions(self):
        for permission in AdminPermission:
            self.assertTrue(has_permission(AdminRole.OWNER, permission))

    def test_operator_can_view_and_operate_but_not_manage_secrets(self):
        self.assertTrue(has_permission(AdminRole.OPERATOR, AdminPermission.VIEW_OPERATIONS))
        self.assertTrue(has_permission(AdminRole.OPERATOR, AdminPermission.RETRY_JOBS))
        self.assertTrue(has_permission(AdminRole.OPERATOR, AdminPermission.CANCEL_JOBS))
        self.assertFalse(has_permission(AdminRole.OPERATOR, AdminPermission.MANAGE_INTEGRATIONS))
        self.assertFalse(has_permission(AdminRole.OPERATOR, AdminPermission.MANAGE_SERVICE_SETTINGS))

    def test_viewer_is_read_only(self):
        self.assertTrue(has_permission(AdminRole.VIEWER, AdminPermission.VIEW_OVERVIEW))
        self.assertTrue(has_permission(AdminRole.VIEWER, AdminPermission.VIEW_AUDIT_LOG))
        self.assertFalse(has_permission(AdminRole.VIEWER, AdminPermission.RETRY_JOBS))
        self.assertFalse(has_permission(AdminRole.VIEWER, AdminPermission.CANCEL_JOBS))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RBAC test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_rbac`

Expected: FAIL with `ModuleNotFoundError` for `translator_service.admin`.

- [ ] **Step 3: Implement RBAC**

Create `src/translator_service/admin/__init__.py`:

```python
"""Admin console support for FolioLoom."""
```

Create `src/translator_service/admin/rbac.py`:

```python
from enum import StrEnum


class AdminRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    VIEWER = "viewer"


class AdminPermission(StrEnum):
    VIEW_OVERVIEW = "view_overview"
    VIEW_INTEGRATIONS = "view_integrations"
    MANAGE_INTEGRATIONS = "manage_integrations"
    VIEW_SERVICE_SETTINGS = "view_service_settings"
    MANAGE_SERVICE_SETTINGS = "manage_service_settings"
    VIEW_OPERATIONS = "view_operations"
    RETRY_JOBS = "retry_jobs"
    CANCEL_JOBS = "cancel_jobs"
    VIEW_SECURITY_EVENTS = "view_security_events"
    VIEW_AUDIT_LOG = "view_audit_log"
    MANAGE_ADMINS = "manage_admins"


_OWNER_PERMISSIONS = frozenset(AdminPermission)
_OPERATOR_PERMISSIONS = frozenset(
    {
        AdminPermission.VIEW_OVERVIEW,
        AdminPermission.VIEW_INTEGRATIONS,
        AdminPermission.VIEW_SERVICE_SETTINGS,
        AdminPermission.VIEW_OPERATIONS,
        AdminPermission.RETRY_JOBS,
        AdminPermission.CANCEL_JOBS,
        AdminPermission.VIEW_SECURITY_EVENTS,
        AdminPermission.VIEW_AUDIT_LOG,
    }
)
_VIEWER_PERMISSIONS = frozenset(
    {
        AdminPermission.VIEW_OVERVIEW,
        AdminPermission.VIEW_INTEGRATIONS,
        AdminPermission.VIEW_SERVICE_SETTINGS,
        AdminPermission.VIEW_OPERATIONS,
        AdminPermission.VIEW_SECURITY_EVENTS,
        AdminPermission.VIEW_AUDIT_LOG,
    }
)

_ROLE_PERMISSIONS = {
    AdminRole.OWNER: _OWNER_PERMISSIONS,
    AdminRole.OPERATOR: _OPERATOR_PERMISSIONS,
    AdminRole.VIEWER: _VIEWER_PERMISSIONS,
}


def has_permission(role: AdminRole, permission: AdminPermission) -> bool:
    return permission in _ROLE_PERMISSIONS[role]
```

- [ ] **Step 4: Run RBAC test**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_rbac`

Expected: PASS.

- [ ] **Step 5: Write audit log tests**

Create `tests/test_admin_audit.py`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_service.admin.audit import AuditOutcome, SQLiteAdminAuditLog
from translator_service.admin.rbac import AdminRole


class AdminAuditTest(unittest.TestCase):
    def test_records_sensitive_action_without_secret_value(self):
        with TemporaryDirectory() as temp_dir:
            audit = SQLiteAdminAuditLog(Path(temp_dir) / "admin.sqlite3")
            event = audit.record(
                actor_id="bootstrap-owner",
                role=AdminRole.OWNER,
                action="secret.replaced",
                target_type="integration_secret",
                target_id="deepseek.main",
                outcome=AuditOutcome.SUCCESS,
                reason="changed api_key sk-live-secret-value",
                metadata={"secret": "sk-live-secret-value", "fingerprint": "abc123"},
            )

            events = audit.list_events(limit=10)

        self.assertEqual(events[0].id, event.id)
        self.assertEqual(events[0].action, "secret.replaced")
        self.assertNotIn("sk-live-secret-value", events[0].reason)
        self.assertNotIn("sk-live-secret-value", events[0].metadata_json)
        self.assertIn("[redacted]", events[0].reason)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: Run audit test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_audit`

Expected: FAIL with missing `translator_service.admin.audit`.

- [ ] **Step 7: Implement audit log**

Create `src/translator_service/admin/audit.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from translator_service.admin.rbac import AdminRole


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True)
class AuditEvent:
    id: str
    actor_id: str
    role: AdminRole
    action: str
    target_type: str
    target_id: str
    outcome: AuditOutcome
    reason: str | None
    metadata_json: str
    created_at: datetime


class SQLiteAdminAuditLog:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def record(
        self,
        *,
        actor_id: str,
        role: AdminRole,
        action: str,
        target_type: str,
        target_id: str,
        outcome: AuditOutcome,
        reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> AuditEvent:
        now = datetime.now(UTC)
        event_id = uuid4().hex
        safe_reason = _redact_text(reason)
        safe_metadata = _redact_metadata(metadata or {})
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_audit_events (
                    id, actor_id, role, action, target_type, target_id,
                    outcome, reason, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    actor_id,
                    role.value,
                    action,
                    target_type,
                    target_id,
                    outcome.value,
                    safe_reason,
                    json.dumps(safe_metadata, sort_keys=True),
                    now.isoformat(),
                ),
            )
        return self.list_events(limit=1)[0]

    def list_events(self, *, limit: int = 50) -> list[AuditEvent]:
        rows = self._connection.execute(
            """
            SELECT * FROM admin_audit_events
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
        return [_event_from_row(row) for row in rows]

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_audit_events (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reason TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )


def _event_from_row(row: sqlite3.Row) -> AuditEvent:
    return AuditEvent(
        id=row["id"],
        actor_id=row["actor_id"],
        role=AdminRole(row["role"]),
        action=row["action"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        outcome=AuditOutcome(row["outcome"]),
        reason=row["reason"],
        metadata_json=row["metadata_json"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"sk-[a-zA-Z0-9_-]+", "[redacted]", value)
    value = re.sub(r"\b\d{6,}:[a-zA-Z0-9_-]+\b", "[redacted]", value)
    return value[:500]


def _redact_metadata(metadata: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in metadata.items():
        if "secret" in key.lower() or "token" in key.lower() or "key" in key.lower():
            safe[key] = "[redacted]"
        elif isinstance(value, str):
            safe[key] = _redact_text(value)
        elif isinstance(value, int | float | bool) or value is None:
            safe[key] = value
        else:
            safe[key] = str(value)[:200]
    return safe
```

- [ ] **Step 8: Run audit test**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_audit`

Expected: PASS.

- [ ] **Step 9: Write settings tests**

Create `tests/test_admin_settings.py`:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_service.admin.settings import (
    AdminSettingDefinition,
    SettingApplyMode,
    SettingValueType,
    SQLiteAdminSettingsStore,
)


class AdminSettingsTest(unittest.TestCase):
    def test_setting_round_trip_preserves_apply_mode_metadata(self):
        definition = AdminSettingDefinition(
            key="translation.max_parallel_units",
            label="Max parallel translation units",
            value_type=SettingValueType.INTEGER,
            apply_mode=SettingApplyMode.RESTART_REQUIRED,
            default_value="1",
            minimum=1,
            maximum=8,
        )
        with TemporaryDirectory() as temp_dir:
            store = SQLiteAdminSettingsStore(Path(temp_dir) / "admin.sqlite3")
            saved = store.set_value(definition, "4", changed_by="bootstrap-owner")
            loaded = store.get_value(definition)

        self.assertEqual(saved.value, "4")
        self.assertEqual(loaded.value, "4")
        self.assertEqual(loaded.apply_mode, SettingApplyMode.RESTART_REQUIRED)
        self.assertEqual(loaded.changed_by, "bootstrap-owner")

    def test_rejects_out_of_range_integer(self):
        definition = AdminSettingDefinition(
            key="uploads.max_mb",
            label="Max upload MB",
            value_type=SettingValueType.INTEGER,
            apply_mode=SettingApplyMode.RESTART_REQUIRED,
            default_value="50",
            minimum=1,
            maximum=100,
        )
        store = SQLiteAdminSettingsStore(":memory:")

        with self.assertRaises(ValueError):
            store.set_value(definition, "500", changed_by="bootstrap-owner")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 10: Run settings test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_settings`

Expected: FAIL with missing `translator_service.admin.settings`.

- [ ] **Step 11: Implement settings store**

Create `src/translator_service/admin/settings.py` with `SettingApplyMode`, `SettingValueType`, `AdminSettingDefinition`, `AdminSettingValue`, and `SQLiteAdminSettingsStore`. Use SQLite table `admin_settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, changed_by TEXT NOT NULL, changed_at TEXT NOT NULL)`. Validate integer bounds before saving. Return default metadata if no persisted row exists.

Implementation skeleton:

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
import sqlite3


class SettingApplyMode(StrEnum):
    LIVE = "live"
    RESTART_REQUIRED = "restart_required"
    BOOTSTRAP_ONLY = "bootstrap_only"


class SettingValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class AdminSettingDefinition:
    key: str
    label: str
    value_type: SettingValueType
    apply_mode: SettingApplyMode
    default_value: str
    minimum: int | float | None = None
    maximum: int | float | None = None
    sensitive: bool = False


@dataclass(frozen=True)
class AdminSettingValue:
    key: str
    label: str
    value: str
    value_type: SettingValueType
    apply_mode: SettingApplyMode
    changed_by: str | None
    changed_at: datetime | None
    sensitive: bool


class SQLiteAdminSettingsStore:
    def __init__(self, db_path: str | Path) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(db_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        self._connection.close()

    def get_value(self, definition: AdminSettingDefinition) -> AdminSettingValue:
        row = self._connection.execute(
            "SELECT * FROM admin_settings WHERE key = ?",
            (definition.key,),
        ).fetchone()
        if row is None:
            return AdminSettingValue(
                key=definition.key,
                label=definition.label,
                value=definition.default_value,
                value_type=definition.value_type,
                apply_mode=definition.apply_mode,
                changed_by=None,
                changed_at=None,
                sensitive=definition.sensitive,
            )
        return AdminSettingValue(
            key=definition.key,
            label=definition.label,
            value=row["value"],
            value_type=definition.value_type,
            apply_mode=definition.apply_mode,
            changed_by=row["changed_by"],
            changed_at=datetime.fromisoformat(row["changed_at"]),
            sensitive=definition.sensitive,
        )

    def set_value(
        self,
        definition: AdminSettingDefinition,
        value: str,
        *,
        changed_by: str,
    ) -> AdminSettingValue:
        _validate_value(definition, value)
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO admin_settings (key, value, changed_by, changed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    changed_by = excluded.changed_by,
                    changed_at = excluded.changed_at
                """,
                (definition.key, value, changed_by, now.isoformat()),
            )
        return self.get_value(definition)

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    changed_by TEXT NOT NULL,
                    changed_at TEXT NOT NULL
                )
                """
            )


def _validate_value(definition: AdminSettingDefinition, value: str) -> None:
    if definition.value_type is SettingValueType.INTEGER:
        parsed = int(value)
    elif definition.value_type is SettingValueType.FLOAT:
        parsed = float(value)
    elif definition.value_type is SettingValueType.BOOLEAN:
        if value not in {"true", "false"}:
            raise ValueError(f"Invalid boolean for {definition.key}: {value}")
        return
    else:
        if not value:
            raise ValueError(f"Setting cannot be empty: {definition.key}")
        return

    if definition.minimum is not None and parsed < definition.minimum:
        raise ValueError(f"Setting below minimum: {definition.key}")
    if definition.maximum is not None and parsed > definition.maximum:
        raise ValueError(f"Setting above maximum: {definition.key}")
```

- [ ] **Step 12: Add admin settings to `Settings`**

Modify `src/translator_service/config.py` to add:

```python
    admin_db_path: str = field(
        default_factory=lambda: os.getenv("ADMIN_DB_PATH", "var/admin.sqlite3")
    )
    admin_session_secret: str = field(
        default_factory=lambda: os.getenv("ADMIN_SESSION_SECRET", "")
    )
    admin_owner_password: str = field(
        default_factory=lambda: os.getenv("ADMIN_OWNER_PASSWORD", "")
    )
    admin_secret_master_key: str = field(
        default_factory=lambda: os.getenv("ADMIN_SECRET_MASTER_KEY", "")
    )
```

Add or update `tests/test_config.py` with expectations for defaults if that file already asserts complete settings behavior.

- [ ] **Step 13: Run Task 1 tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_rbac \
  tests.test_admin_audit \
  tests.test_admin_settings \
  tests.test_config
```

Expected: PASS.

- [ ] **Step 14: Commit Task 1**

```bash
git add src/translator_service/admin/__init__.py \
  src/translator_service/admin/rbac.py \
  src/translator_service/admin/audit.py \
  src/translator_service/admin/settings.py \
  src/translator_service/config.py \
  tests/test_admin_rbac.py \
  tests/test_admin_audit.py \
  tests/test_admin_settings.py \
  tests/test_config.py
git commit -m "feat: add admin core domain"
```

---

## Task 2: Encrypted SecretStore MVP

**Owner:** Coordinator.

**Files:**
- Create: `src/translator_service/admin/secrets.py`
- Modify: `pyproject.toml`
- Test: `tests/test_admin_secrets.py`

- [ ] **Step 1: Add crypto dependency**

Modify `pyproject.toml` project dependencies:

```toml
    "cryptography>=42",
```

- [ ] **Step 2: Write secret store tests**

Create `tests/test_admin_secrets.py`:

```python
import base64
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_service.admin.secrets import (
    SecretStoreUnavailable,
    SQLiteEncryptedSecretStore,
)


MASTER_KEY = base64.urlsafe_b64encode(b"1" * 32).decode("ascii")


class AdminSecretsTest(unittest.TestCase):
    def test_stores_encrypted_secret_and_returns_metadata(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            store = SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY)
            metadata = store.put_secret(
                secret_id="deepseek.main",
                label="DeepSeek main",
                kind="api_key",
                plaintext="sk-secret-value",
                actor_id="bootstrap-owner",
            )
            loaded = store.describe_secret("deepseek.main")
            plaintext = store.get_secret_value("deepseek.main")
            raw_db = db_path.read_bytes()

        self.assertEqual(metadata.secret_id, "deepseek.main")
        self.assertEqual(loaded.masked_value, "sk-****alue")
        self.assertEqual(plaintext, "sk-secret-value")
        self.assertNotIn(b"sk-secret-value", raw_db)

    def test_replacement_increments_version(self):
        store = SQLiteEncryptedSecretStore(":memory:", master_key=MASTER_KEY)
        first = store.put_secret(
            secret_id="telegram.prod",
            label="Telegram production",
            kind="bot_token",
            plaintext="123456:old-token",
            actor_id="bootstrap-owner",
        )
        second = store.put_secret(
            secret_id="telegram.prod",
            label="Telegram production",
            kind="bot_token",
            plaintext="123456:new-token",
            actor_id="bootstrap-owner",
        )

        self.assertEqual(first.version, 1)
        self.assertEqual(second.version, 2)
        self.assertEqual(store.get_secret_value("telegram.prod"), "123456:new-token")

    def test_missing_master_key_fails_closed(self):
        with self.assertRaises(SecretStoreUnavailable):
            SQLiteEncryptedSecretStore(":memory:", master_key="")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run secret tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_secrets`

Expected: FAIL with missing `translator_service.admin.secrets` or missing `cryptography` if dependencies are not installed.

- [ ] **Step 4: Implement encrypted secret store**

Create `src/translator_service/admin/secrets.py` using AES-GCM. Do not return plaintext from metadata methods.

Use this public shape:

```python
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import sqlite3
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretStoreUnavailable(RuntimeError):
    pass


class SecretNotFound(KeyError):
    pass


@dataclass(frozen=True)
class SecretMetadata:
    secret_id: str
    label: str
    kind: str
    fingerprint: str
    masked_value: str
    version: int
    disabled: bool
    created_at: datetime
    updated_at: datetime


class SecretStore(Protocol):
    def put_secret(
        self,
        *,
        secret_id: str,
        label: str,
        kind: str,
        plaintext: str,
        actor_id: str,
    ) -> SecretMetadata:
        pass

    def describe_secret(self, secret_id: str) -> SecretMetadata:
        pass

    def get_secret_value(self, secret_id: str) -> str:
        pass
```

Complete implementation requirements:

- table `admin_secrets` with `secret_id`, `label`, `kind`, `fingerprint`, `masked_value`, `version`, `disabled`, `algorithm`, `nonce`, `ciphertext`, `created_at`, `updated_at`, `updated_by`;
- master key decoded from urlsafe base64 and exactly 32 bytes;
- `AESGCM.encrypt(nonce, plaintext.encode("utf-8"), secret_id.encode("utf-8"))`;
- nonce from `os.urandom(12)`;
- fingerprint `sha256(plaintext.encode("utf-8")).hexdigest()[:16]`;
- masking returns first 3 and last 4 characters when length allows, otherwise `****`;
- `get_secret_value` raises `SecretNotFound` for missing or disabled secrets.

- [ ] **Step 5: Run secret tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_secrets`

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add pyproject.toml src/translator_service/admin/secrets.py tests/test_admin_secrets.py
git commit -m "feat: add encrypted admin secret store"
```

---

## Task 3: Admin Auth And FastAPI Route Shell

**Owner:** Coordinator, then UI Agent can extend pages after this lands.

**Files:**
- Create: `src/translator_service/admin/auth.py`
- Create: `src/translator_service/admin/views.py`
- Create: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/api.py`
- Test: `tests/test_admin_auth.py`
- Test: `tests/test_admin_routes.py`

- [ ] **Step 1: Write auth tests**

Create `tests/test_admin_auth.py` with tests for successful login, wrong password rejection, signed session parsing, and CSRF validation.

Essential assertions:

```python
self.assertEqual(session.actor_id, "bootstrap-owner")
self.assertEqual(session.role, AdminRole.OWNER)
self.assertTrue(manager.verify_csrf(session, session.csrf_token))
self.assertFalse(manager.verify_csrf(session, "wrong-token"))
```

- [ ] **Step 2: Implement auth manager**

Create `src/translator_service/admin/auth.py`:

- `AdminSession(actor_id, role, expires_at, csrf_token)`;
- `AdminSessionManager(owner_password, session_secret, ttl_seconds=28800)`;
- `login(password)` returns signed cookie value and session;
- `load(cookie_value)` verifies HMAC signature and expiry;
- `verify_csrf(session, token)`;
- use `hmac.compare_digest`;
- raise `AdminAuthError` for invalid login or invalid session.

- [ ] **Step 3: Write route tests**

Create `tests/test_admin_routes.py`:

```python
import unittest

from fastapi.testclient import TestClient

from translator_service.api import create_app
from translator_service.config import Settings


class AdminRoutesTest(unittest.TestCase):
    def test_admin_requires_login(self):
        app = create_app(
            Settings(
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
                admin_secret_master_key="not-used-for-this-test",
            )
        )
        client = TestClient(app)

        response = client.get("/admin/overview")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_owner_can_login_and_view_overview(self):
        app = create_app(
            Settings(
                admin_owner_password="owner-pass",
                admin_session_secret="session-secret",
                admin_secret_master_key="not-used-for-this-test",
            )
        )
        client = TestClient(app)

        login = client.post("/admin/login", data={"password": "owner-pass"})
        overview = client.get("/admin/overview")

        self.assertEqual(login.status_code, 303)
        self.assertEqual(overview.status_code, 200)
        self.assertIn("FolioLoom Admin", overview.text)
```

- [ ] **Step 4: Run route tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`

Expected: FAIL because `create_app` does not accept settings and admin routes do not exist.

- [ ] **Step 5: Implement views and routes**

Create `src/translator_service/admin/views.py`:

```python
from html import escape


def admin_page(title: str, body: str) -> str:
    safe_title = escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="cache-control" content="no-store">
  <title>{safe_title} · FolioLoom Admin</title>
  <style>
    body {{ margin:0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f7f8f5; color:#17211d; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    nav {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
    a, button {{ color:#17211d; }}
    .card {{ background:#fff; border:1px solid #dfe5dd; border-radius:8px; padding:16px; margin-bottom:12px; }}
    .muted {{ color:#607068; }}
  </style>
</head>
<body><main><h1>FolioLoom Admin</h1>{body}</main></body></html>"""
```

Create `src/translator_service/admin/routes.py` with `create_admin_router(settings: Settings) -> APIRouter`. Include:

- `GET /admin/login`;
- `POST /admin/login`;
- `POST /admin/logout`;
- `GET /admin/overview`;
- `GET /admin/integrations`;
- `GET /admin/settings`;
- `GET /admin/operations/jobs`;
- `GET /admin/security/events`;
- `GET /admin/audit`.

Modify `src/translator_service/api.py`:

```python
def create_app(settings: Settings | None = None):
    from fastapi import FastAPI
    from translator_service.admin.routes import create_admin_router

    active_settings = settings or Settings()
    app = FastAPI(title=active_settings.service_name)
    app.include_router(create_admin_router(active_settings))
    ...
```

Keep `/health` behavior unchanged.

- [ ] **Step 6: Run admin auth and route tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_auth \
  tests.test_admin_routes \
  tests.test_api
```

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add src/translator_service/admin/auth.py \
  src/translator_service/admin/views.py \
  src/translator_service/admin/routes.py \
  src/translator_service/api.py \
  tests/test_admin_auth.py \
  tests/test_admin_routes.py \
  tests/test_api.py
git commit -m "feat: add admin auth and route shell"
```

---

## Task 4: Integrations Slice

**Owner:** Integrations Agent.

**Files:**
- Create: `src/translator_service/admin/integrations.py`
- Modify: `src/translator_service/admin/routes.py`
- Test: `tests/test_admin_integrations.py`
- Test: `tests/test_admin_routes.py`

- [ ] **Step 1: Write integration registry tests**

Create `tests/test_admin_integrations.py`:

```python
import unittest

from translator_service.admin.integrations import (
    IntegrationCategory,
    build_mvp_integration_registry,
)


class AdminIntegrationsTest(unittest.TestCase):
    def test_registry_contains_mvp_and_reserved_categories(self):
        registry = build_mvp_integration_registry()
        categories = {item.category for item in registry}
        ids = {item.integration_id for item in registry}

        self.assertIn("telegram", ids)
        self.assertIn("deepseek", ids)
        self.assertIn(IntegrationCategory.CHANNEL, categories)
        self.assertIn(IntegrationCategory.PAYMENT, categories)
        self.assertIn(IntegrationCategory.STORAGE, categories)

    def test_registry_marks_non_mvp_categories_as_reserved(self):
        registry = build_mvp_integration_registry()
        stripe = next(item for item in registry if item.integration_id == "stripe")

        self.assertFalse(stripe.enabled)
        self.assertEqual(stripe.status, "reserved")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement integration registry**

Create `src/translator_service/admin/integrations.py`:

- `IntegrationCategory` enum with categories from the spec;
- `IntegrationSummary` dataclass with `integration_id`, `name`, `category`, `provider`, `enabled`, `status`, `environment`, `safe_details`;
- `build_mvp_integration_registry()` returning active Telegram and DeepSeek summaries plus reserved Stripe/payment, storage, analytics, CRM, observability, automation, and social/marketing summaries.

- [ ] **Step 3: Add integration endpoints**

Modify `src/translator_service/admin/routes.py`:

- `GET /admin/api/integrations` returns JSON list of `IntegrationSummary`;
- `GET /admin/integrations` renders cards from the registry;
- page must not show raw env values or raw secrets.

- [ ] **Step 4: Run integration tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_integrations \
  tests.test_admin_routes
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add src/translator_service/admin/integrations.py \
  src/translator_service/admin/routes.py \
  tests/test_admin_integrations.py \
  tests/test_admin_routes.py
git commit -m "feat: add admin integrations registry"
```

---

## Task 5: Operations Slice

**Owner:** Operations Agent.

**Files:**
- Create: `src/translator_service/admin/operations.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/persistent_jobs.py`
- Test: `tests/test_admin_operations.py`
- Test: `tests/test_persistent_jobs.py`

- [ ] **Step 1: Write operations tests**

Create `tests/test_admin_operations.py`:

```python
import unittest

from translator_service.admin.operations import AdminOperationsService
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)


class AdminOperationsTest(unittest.TestCase):
    def test_lists_safe_job_summaries(self):
        store = SQLiteTranslationJobStore(":memory:")
        job = store.create_job(
            order_id="order-1",
            user_id="customer-1",
            file_id="file-1",
            file_name="book.docx",
            document_kind="docx",
            source_language="auto",
            target_language="ru",
            adapter_version="docx-v1",
            prompt_version="prompt-v1",
            pricing_snapshot_id="pricing-1",
        )
        service = AdminOperationsService(store)

        summaries = service.list_jobs(limit=10)

        self.assertEqual(summaries[0].job_id, job.id)
        self.assertEqual(summaries[0].file_name, "book.docx")
        self.assertEqual(summaries[0].status, PersistentTranslationJobStatus.QUEUED)

    def test_retry_interrupted_job_resumes_job(self):
        store = SQLiteTranslationJobStore(":memory:")
        job = store.create_job(
            order_id="order-1",
            user_id="customer-1",
            file_id="file-1",
            file_name="book.txt",
            document_kind="txt",
            source_language="auto",
            target_language="uk",
            adapter_version="txt-v1",
            prompt_version="prompt-v1",
            pricing_snapshot_id="pricing-1",
        )
        store.add_work_units(
            job.id,
            [WorkUnitPlan(sequence=1, source_block_ids=("b1",), source_text_hash="h1", prompt_tier="plain", source_language="en", target_language="uk")],
        )
        store.fail_work_unit(f"{job.id}:unit-1", error_message="provider failed", retry_count=1)
        service = AdminOperationsService(store)

        retried = service.retry_job(job.id, actor_id="bootstrap-owner")

        self.assertEqual(retried.status, PersistentTranslationJobStatus.QUEUED)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Implement operations service**

Create `src/translator_service/admin/operations.py`:

- `AdminJobSummary` dataclass;
- `AdminWorkerSummary` dataclass;
- `AdminOperationsService`;
- `list_jobs(limit=50)` gathers jobs by status using existing `list_jobs_by_status`;
- `retry_job(job_id, actor_id)` allows `INTERRUPTED`, `FAILED`, and `CANCELLED` only if existing store `resume_job` can safely requeue it;
- `cancel_job(job_id, actor_id)` allows `QUEUED`, `TRANSLATING`, and `CANCEL_REQUESTED`.

Do not include document text or translated text in summaries.

- [ ] **Step 3: Add worker heartbeat listing**

Add this method to `SQLiteTranslationJobStore` so the operations page can render worker health:

```python
def list_worker_heartbeats(self, *, limit: int = 50) -> list[PersistentWorkerHeartbeat]:
    rows = self._connection.execute(
        """
        SELECT * FROM worker_heartbeats
        ORDER BY datetime(last_seen_at) DESC, worker_id
        LIMIT ?
        """,
        (max(1, limit),),
    ).fetchall()
    return [_worker_heartbeat_from_row(row) for row in rows]
```

Add this focused test to `tests/test_persistent_jobs.py`:

```python
    def test_lists_worker_heartbeats_newest_first(self):
        store = self._memory_store()
        store.record_worker_heartbeat(
            worker_id="worker-a",
            worker_kind="translator",
            status="idle",
            active_job_id=None,
            active_work_unit_id=None,
        )
        store.record_worker_heartbeat(
            worker_id="worker-b",
            worker_kind="translator",
            status="busy",
            active_job_id="job-1",
            active_work_unit_id="job-1:unit-1",
        )

        heartbeats = store.list_worker_heartbeats(limit=10)

        self.assertEqual([heartbeat.worker_id for heartbeat in heartbeats], ["worker-b", "worker-a"])
        self.assertEqual(heartbeats[0].status, "busy")
        self.assertEqual(heartbeats[0].active_job_id, "job-1")
```

- [ ] **Step 4: Add operation endpoints**

Modify `src/translator_service/admin/routes.py`:

- `GET /admin/api/operations/jobs`;
- `POST /admin/api/operations/jobs/{job_id}/retry`;
- `POST /admin/api/operations/jobs/{job_id}/cancel`;
- `GET /admin/operations/jobs`.

Mutating routes require owner or operator permission and CSRF token.

- [ ] **Step 5: Run operations tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_operations \
  tests.test_persistent_jobs \
  tests.test_admin_routes
```

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add src/translator_service/admin/operations.py \
  src/translator_service/admin/routes.py \
  src/translator_service/persistent_jobs.py \
  tests/test_admin_operations.py \
  tests/test_persistent_jobs.py \
  tests/test_admin_routes.py
git commit -m "feat: add admin operations controls"
```

---

## Task 6: UI Pass And Security Regression Coverage

**Owner:** UI Agent and Security/Test Agent in sequence. UI Agent goes first; Security/Test Agent reviews and extends tests after UI endpoints exist.

**Files:**
- Modify: `src/translator_service/admin/views.py`
- Modify: `src/translator_service/admin/routes.py`
- Modify: `tests/test_admin_routes.py`
- Create: `tests/test_admin_security_regressions.py`

- [ ] **Step 1: Improve admin page layout**

Modify `admin_page()` in `src/translator_service/admin/views.py` to include:

- left/top navigation links for Overview, Integrations, Service Settings, Operations, Security, Audit;
- mobile-friendly stacked layout under `@media (max-width: 760px)`;
- `no-store` meta already present;
- no decorative hero sections.

- [ ] **Step 2: Add route tests for page content**

Extend `tests/test_admin_routes.py` to assert:

```python
self.assertIn("Integrations", overview.text)
self.assertIn("Service Settings", overview.text)
self.assertIn("Operations", overview.text)
self.assertNotIn("DEEPSEEK_API_KEY", integrations.text)
self.assertNotIn("ADMIN_OWNER_PASSWORD", settings.text)
```

- [ ] **Step 3: Write security regression tests**

Create `tests/test_admin_security_regressions.py`:

```python
import unittest

from fastapi.testclient import TestClient

from translator_service.api import create_app
from translator_service.config import Settings


class AdminSecurityRegressionTest(unittest.TestCase):
    def test_admin_pages_are_no_store(self):
        client = _logged_in_client()
        response = client.get("/admin/overview")

        self.assertIn("no-store", response.headers.get("cache-control", ""))

    def test_mutating_route_rejects_missing_csrf(self):
        client = _logged_in_client()
        response = client.post("/admin/api/operations/jobs/job-1/cancel")

        self.assertIn(response.status_code, {400, 403, 404})
        self.assertNotEqual(response.status_code, 200)


def _logged_in_client() -> TestClient:
    app = create_app(
        Settings(
            admin_owner_password="owner-pass",
            admin_session_secret="session-secret",
            admin_secret_master_key="not-used-for-this-test",
        )
    )
    client = TestClient(app)
    client.post("/admin/login", data={"password": "owner-pass"})
    return client


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run UI and security tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_routes \
  tests.test_admin_security_regressions
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```bash
git add src/translator_service/admin/views.py \
  src/translator_service/admin/routes.py \
  tests/test_admin_routes.py \
  tests/test_admin_security_regressions.py
git commit -m "feat: polish admin console MVP UI"
```

---

## Final Verification

- [ ] **Step 1: Run admin-focused suite**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_rbac \
  tests.test_admin_audit \
  tests.test_admin_settings \
  tests.test_admin_secrets \
  tests.test_admin_auth \
  tests.test_admin_integrations \
  tests.test_admin_operations \
  tests.test_admin_routes \
  tests.test_admin_security_regressions
```

Expected: PASS.

- [ ] **Step 2: Run affected existing tests**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_api \
  tests.test_config \
  tests.test_bot_runtime \
  tests.test_persistent_jobs \
  tests.test_security_telemetry
```

Expected: PASS.

- [ ] **Step 3: Compile source**

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: exit code 0.

- [ ] **Step 4: Manual browser check**

Run the app after dependencies are installed:

```bash
ADMIN_OWNER_PASSWORD='owner-pass' \
ADMIN_SESSION_SECRET='dev-session-secret' \
ADMIN_SECRET_MASTER_KEY='base64-url-encoded-32-byte-key' \
PYTHONPATH=src \
uvicorn translator_service.api:create_app --factory --reload
```

Open `http://127.0.0.1:8000/admin/login`, log in, and verify:

- Overview loads.
- Integrations page shows Telegram and DeepSeek without raw secrets.
- Settings page shows apply modes.
- Operations page loads without document text.
- Mutating actions require confirmation and CSRF.

---

## Coverage Notes

This plan intentionally does not implement:

- real Stripe checkout or payment provider integration;
- billing transaction dashboard;
- WhatsApp, Instagram, Discord, or other channel adapters;
- public customer website;
- multi-admin invitation flow;
- mobile-first dedicated admin UI.

The plan does implement the interfaces and navigation shape that keep those paths open.
