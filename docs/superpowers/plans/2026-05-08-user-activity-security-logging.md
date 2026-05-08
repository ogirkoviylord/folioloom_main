# User Activity and Security Logging Implementation Plan


**Goal:** Add a SQLite-backed user activity and security event store, instrument core bot/translation/admin actions, and expose the data in the browser admin console.

**Architecture:** Create one append-only event store plus one current-state user profile table. Wire event recording through small optional dependencies so logging failures do not break ordinary user flows. Add server-rendered admin pages and JSON endpoints that reuse the existing admin auth/session shell.

**Tech Stack:** Python 3.13, SQLite, FastAPI, server-rendered admin HTML, `unittest`, existing `BotTranslationService`, existing admin router/views.

---

## File Structure

- Create `src/translator_service/user_activity.py`: dataclasses, enums, SQLite store, filtering, profile upsert, redaction helpers, convenience event constructors.
- Create `tests/test_user_activity.py`: persistence, list/filter, profile upsert, redaction, failure-isolation helper tests.
- Modify `src/translator_service/bot_translation_service.py`: optional `activity_store`, record upload/estimate/confirm/start/complete/fail/cancel translation lifecycle events.
- Modify `src/translator_service/bot/runtime.py`: create activity store from `Settings.admin_db_path`, pass it into the service, and record commands/buttons/settings/upload attempts in handlers.
- Modify `src/translator_service/admin/routes.py`: add `/admin/users`, `/admin/users/{user_id}`, `/admin/activity`, `/admin/api/activity`, `/admin/api/users`, and back the existing `/admin/security/events` page with activity security events.
- Modify `src/translator_service/admin/views.py`: add user list, user detail, activity log, and security event bodies.
- Modify `src/translator_service/admin/audit.py` or `src/translator_service/admin/routes.py`: record admin page views and sensitive admin changes into user activity in addition to existing admin audit events.
- Modify `tests/test_bot_translation_service.py`, `tests/test_bot_runtime.py`, and `tests/test_admin_routes.py`: coverage for instrumentation and admin pages.

## Task 1: SQLite Activity Store

**Files:**
- Create: `src/translator_service/user_activity.py`
- Test: `tests/test_user_activity.py`

- [ ] **Step 1: Write failing tests for recording and filtering events**

Create `tests/test_user_activity.py` with tests shaped like:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEventInput,
)


class UserActivityStoreTest(unittest.TestCase):
    def test_records_event_and_upserts_user_profile(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(store.close)

            event = store.record_event(
                UserActivityEventInput(
                    actor_type=ActivityActorType.USER,
                    actor_id="telegram:42",
                    channel="telegram",
                    channel_user_id="42",
                    surface=ActivitySurface.BOT,
                    event_type="bot.button.clicked",
                    action="clicked",
                    target_type="button",
                    target_id="translate_book",
                    outcome=ActivityOutcome.SUCCESS,
                    metadata={"button_text": "Translate"},
                )
            )

            profile = store.get_user_profile("telegram:42")
            events = store.list_events(actor_id="telegram:42")

            self.assertEqual(event.event_type, "bot.button.clicked")
            self.assertEqual(profile.channel_user_id, "42")
            self.assertEqual(profile.security_state, "normal")
            self.assertEqual(events[0].target_id, "translate_book")

    def test_filters_events_by_surface_outcome_and_job(self):
        with TemporaryDirectory() as temp_dir:
            store = SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3")
            self.addCleanup(store.close)
            store.record_event(
                UserActivityEventInput(
                    actor_type=ActivityActorType.USER,
                    actor_id="telegram:42",
                    channel="telegram",
                    channel_user_id="42",
                    surface=ActivitySurface.BOT,
                    event_type="translation.completed",
                    action="completed",
                    target_type="translation_job",
                    target_id="job-1",
                    outcome=ActivityOutcome.SUCCESS,
                    job_id="job-1",
                    metadata={"total_tokens": 100},
                )
            )
            store.record_event(
                UserActivityEventInput(
                    actor_type=ActivityActorType.USER,
                    actor_id="telegram:42",
                    channel="telegram",
                    channel_user_id="42",
                    surface=ActivitySurface.SECURITY,
                    event_type="security.suspicious_input_detected",
                    action="detected",
                    target_type="message",
                    target_id="message",
                    outcome=ActivityOutcome.BLOCKED,
                    metadata={"text_length": 20},
                )
            )

            security = store.list_events(surface="security")
            blocked = store.list_events(outcome="blocked")
            job = store.list_events(job_id="job-1")

            self.assertEqual(len(security), 1)
            self.assertEqual(blocked[0].event_type, "security.suspicious_input_detected")
            self.assertEqual(job[0].event_type, "translation.completed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_user_activity`

Expected: FAIL because `translator_service.user_activity` does not exist.

- [ ] **Step 3: Implement store and schema**

Create `src/translator_service/user_activity.py` with:

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


class ActivityActorType(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    WORKER = "worker"


class ActivitySurface(StrEnum):
    BOT = "bot"
    ADMIN = "admin"
    WORKER = "worker"
    SECURITY = "security"


class ActivityOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKED = "blocked"
    IGNORED = "ignored"


@dataclass(frozen=True)
class UserActivityEventInput:
    actor_type: ActivityActorType
    actor_id: str
    surface: ActivitySurface
    event_type: str
    action: str
    outcome: ActivityOutcome
    channel: str | None = None
    channel_user_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    job_id: str | None = None
    order_id: str | None = None
    translation_run_dir: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class UserActivityEvent:
    id: str
    created_at: datetime
    actor_type: ActivityActorType
    actor_id: str
    channel: str | None
    channel_user_id: str | None
    surface: ActivitySurface
    event_type: str
    action: str
    target_type: str | None
    target_id: str | None
    outcome: ActivityOutcome
    job_id: str | None
    order_id: str | None
    translation_run_dir: str | None
    metadata_json: str


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    channel: str
    channel_user_id: str
    interface_language: str | None
    progress_preview_enabled: bool | None
    default_source_language: str | None
    last_target_language: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    security_state: str
    metadata_json: str
```

Implement `SQLiteUserActivityStore.record_event`, `list_events`,
`get_user_profile`, `list_user_profiles`, and `update_user_profile`. Use schema
from the design doc. Redact metadata keys containing `secret`, `token`,
`password`, or `key`; truncate string metadata to 500 chars.

- [ ] **Step 4: Run store tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_user_activity`

Expected: PASS.

## Task 2: Translation Lifecycle Instrumentation

**Files:**
- Modify: `src/translator_service/bot_translation_service.py`
- Test: `tests/test_bot_translation_service.py`

- [ ] **Step 1: Write failing service instrumentation test**

Add a test that constructs `BotTranslationService(activity_store=store)`,
prepares a TXT document, confirms translation, then asserts events:

```python
events = store.list_events(actor_id="telegram:42")
event_types = [event.event_type for event in events]
self.assertIn("document.estimated", event_types)
self.assertIn("translation.confirmed", event_types)
self.assertIn("translation.started", event_types)
self.assertIn("translation.completed", event_types)
completed = next(event for event in events if event.event_type == "translation.completed")
self.assertEqual(completed.job_id, job.id)
self.assertEqual(completed.channel_user_id, "42")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service`

Expected: FAIL because `BotTranslationService` does not accept or record
`activity_store`.

- [ ] **Step 3: Add optional activity store to service**

Add constructor argument:

```python
activity_store: SQLiteUserActivityStore | None = None
```

Store it as `self._activity_store`. Add private helpers:

```python
def _record_user_activity(self, pending_or_user_id, *, event_type, action, outcome, ...):
    if self._activity_store is None:
        return
    try:
        self._activity_store.record_event(...)
    except Exception:
        logger.warning("Failed to record user activity", exc_info=True)
```

Record:

- `document.estimated` in `prepare_document`;
- `translation.target_language.selected` in `prepare_pending_upload`;
- `translation.confirmed` after pending is popped;
- `translation.started` after job id is known;
- `translation.completed`, `translation.failed`, or `translation.cancelled` before returning.

- [ ] **Step 4: Run service tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_bot_translation_service`

Expected: PASS.

## Task 3: Telegram Runtime Instrumentation

**Files:**
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_runtime.py`

- [ ] **Step 1: Write failing runtime wiring test**

Add a test proving `build_translation_service(BotRuntimeConfig(admin_db_path=...))`
creates an activity store and records at least `document.estimated` through the
service path. If `BotRuntimeConfig` already has admin paths, reuse them.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3 -m unittest tests.test_bot_runtime`

Expected: FAIL because runtime does not create/pass an activity store.

- [ ] **Step 3: Wire activity store and command helpers**

Add `admin_db_path` to `BotRuntimeConfig`. In `build_translation_service`, create:

```python
activity_store=SQLiteUserActivityStore(config.admin_db_path)
```

Pass it to `BotTranslationService`.

Add small helpers in runtime:

```python
def _telegram_actor_id(user_id: int) -> str:
    return f"telegram:{user_id}"

def _record_runtime_activity(service, user_id, *, event_type, action, target_type=None, target_id=None, metadata=None):
    service.record_activity(...)
```

If exposing `service.record_activity` is too noisy, keep runtime instrumentation
for a later slice and complete this task with service-level runtime wiring only.

- [ ] **Step 4: Run runtime tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_bot_runtime`

Expected: PASS.

## Task 4: Admin Activity And User Pages

**Files:**
- Modify: `src/translator_service/admin/routes.py`
- Modify: `src/translator_service/admin/views.py`
- Test: `tests/test_admin_routes.py`

- [ ] **Step 1: Write failing admin route tests**

Add tests that log in, seed `SQLiteUserActivityStore(settings.admin_db_path)`,
then open:

```python
response = client.get("/admin/activity")
self.assertEqual(response.status_code, 200)
self.assertIn("bot.button.clicked", response.text)

users = client.get("/admin/users")
self.assertIn("telegram:42", users.text)

detail = client.get("/admin/users/telegram:42")
self.assertIn("Translation", detail.text)
```

Add API checks for `/admin/api/activity` and `/admin/api/users`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`

Expected: FAIL because routes/pages do not exist.

- [ ] **Step 3: Add view renderers**

In `admin/views.py`, add:

- `activity_body(events, filters)`;
- `users_body(profiles)`;
- `user_detail_body(profile, events)`;
- `security_events_body(events, profiles)`.

Keep UI dense and operational: tables, filters, status pills, links to
`/admin/logs` where `translation_run_dir` exists. Do not display full document
or message text.

- [ ] **Step 4: Add routes and APIs**

In `admin/routes.py`, add protected pages:

- `GET /admin/activity`;
- `GET /admin/users`;
- `GET /admin/users/{user_id}`;
- update `GET /admin/security/events` to show security activity instead of a
  static section page.

Add APIs:

- `GET /admin/api/activity`;
- `GET /admin/api/users`.

Record `admin.activity.viewed`, `admin.user.viewed`, and
`admin.translation_log.viewed` using the same activity store.

- [ ] **Step 5: Run admin route tests**

Run: `PYTHONPATH=src python3 -m unittest tests.test_admin_routes`

Expected: PASS.

## Task 5: Security Event Integration

**Files:**
- Modify: existing security telemetry modules discovered by `rg -n "security|suspicious|cooldown|unsafe" src/translator_service`
- Test: matching existing security tests

- [ ] **Step 1: Locate security emitters**

Run:

```bash
rg -n "suspicious|unsafe|cooldown|blocked|security" src/translator_service tests
```

Use the modules that already decide suspicious input, unsafe output, cooldown,
or block state. Do not invent duplicate security checks.

- [ ] **Step 2: Write failing security activity test**

In the relevant existing test file, assert that a suspicious or unsafe decision
records `security.suspicious_input_detected` or
`security.unsafe_model_output_detected` into `SQLiteUserActivityStore`.

- [ ] **Step 3: Implement minimal security event recording**

Thread `activity_store` into the security decision point or expose a helper
that callers invoke when security telemetry is emitted. Set `surface="security"`
and `outcome="blocked"` for blocked actions.

- [ ] **Step 4: Run security tests**

Run the focused security test module found in Step 1.

Expected: PASS.

## Task 6: Verification

**Files:**
- All changed files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_user_activity \
  tests.test_bot_translation_service \
  tests.test_bot_runtime \
  tests.test_admin_routes
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: PASS, except for any pre-existing failures explicitly documented in
the current branch before this plan begins.

- [ ] **Step 3: Compile source**

Run:

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: PASS.

- [ ] **Step 4: Manual admin smoke**

Start the app with a temp or dev `ADMIN_DB_PATH`, log in to `/admin`, perform a
test translation, and verify:

- `/admin/users` shows the Telegram user;
- `/admin/users/{user_id}` shows timeline events;
- `/admin/activity` filters by event type and outcome;
- `/admin/security/events` shows security events only;
- translation completion rows include `job_id` and `translation_run_dir`.

## Self-Review

- Spec coverage: store, profile state, translation linkage, admin pages,
  filtering, privacy, and failure isolation are all covered.
- Scope: this is one implementation slice for support/security logging. Broad
  product analytics, warehouse export, and production redacted text policy are
  excluded from this first implementation.
- Red-flag scan: no unresolved implementation blanks remain.
