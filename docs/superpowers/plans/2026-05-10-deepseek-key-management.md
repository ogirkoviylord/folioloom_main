# DeepSeek Key Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a focused admin workflow for viewing, adding, editing, rotating, disabling, enabling, removing and testing DeepSeek API keys without exposing raw secrets.

**Architecture:** Reuse the existing admin provider key store, encrypted secret store, validation store, runtime reload store and audit log. Add one dedicated DeepSeek keys page, one rotate-key store method, safe redirects back to the dedicated page, and reload-pending UX after key inventory mutations.

**Tech Stack:** Python 3.13, FastAPI admin routes, SQLite admin stores, existing encrypted secret store, existing HTML string views, `unittest`/`pytest`, `ruff`.

---

## Scope

Implement:

- `GET /admin/ai-providers/deepseek/keys`;
- dedicated DeepSeek key management page;
- `POST /admin/ai-providers/deepseek/keys/rotate`;
- safe key rotation that keeps `key_id` stable;
- key mutation redirects back to the dedicated page;
- runtime reload pending marker after add/update/rotate/disable/enable/remove;
- AI Providers overview link to the dedicated page;
- tests for no raw key leakage, CSRF, auth laziness and audit safety;
- docs/runbook updates for the operator flow.

Do not implement:

- raw key viewer;
- public API;
- user-facing settings;
- new billing/payment behavior;
- new Redis/scheduler dependency;
- broad admin UI redesign outside AI Providers and DeepSeek Keys.

## Files

- Modify `src/translator_service/admin/ai_provider_keys.py`
  - add `rotate_key(...)`;
  - keep metadata and secret handling in the existing store boundary.
- Modify `src/translator_service/admin/routes.py`
  - add dedicated page route;
  - add rotate route;
  - add redirect helper for provider key routes;
  - add runtime reload pending helper after key mutations.
- Modify `src/translator_service/admin/views.py`
  - add `deepseek_keys_body(...)`;
  - add compact key summary CTA on `ai_providers_body(...)`;
  - keep raw secrets out of HTML.
- Modify `tests/test_admin_routes.py`
  - admin route, key mutation, rotate, reload pending and leakage tests.
- Optionally modify `tests/test_ai_provider_runtime.py`
  - only if a dedicated runtime-store behavior needs coverage.
- Optionally modify `tests/test_admin_provider_health.py`
  - only if provider health summary rendering changes.
- Modify `README.md`
- Modify `README.project.md`
- Modify `docs/deployment/admin-vps-runbook.md`
- Modify `DOCUMENT_INDEX.md`

## Safe Vocabulary

Use these action names consistently:

```python
"ai_provider.key.added"
"ai_provider.key.updated"
"ai_provider.key.rotated"
"ai_provider.key.disabled"
"ai_provider.key.enabled"
"ai_provider.key.removed"
"ai_provider.key.tested"
"ai_provider.keys.tested"
"ai_provider.runtime.reload_requested"
```

For mutation audit metadata, use only safe fields:

```python
{
    "provider_id": provider_id,
    "key_id": key.key_id,
    "fingerprint": key.fingerprint,
    "runtime_reload_requested": True,
}
```

Never put plaintext API keys or full `secret_id` values in audit metadata.

---

## Task 1: Dedicated DeepSeek Keys Route And Auth Laziness

**Files:**

- Modify `src/translator_service/admin/routes.py`
- Modify `src/translator_service/admin/views.py`
- Modify `tests/test_admin_routes.py`

- [x] **Step 1: Add failing unauthenticated route laziness test**

Add to `tests/test_admin_routes.py` near the existing admin auth laziness tests:

```python
def test_deepseek_keys_page_does_not_build_inventory_without_login(self):
    with patch(
        "translator_service.admin.routes._ai_provider_key_pools",
        side_effect=AssertionError("key inventory should be lazy"),
    ):
        response = self.client.get(
            "/admin/ai-providers/deepseek/keys",
            follow_redirects=False,
        )

    self.assertEqual(response.status_code, 303)
    self.assertEqual(response.headers["location"], "/admin/login")
```

- [x] **Step 2: Add failing authenticated page render test**

Add to `tests/test_admin_routes.py` near existing AI Providers tests:

```python
def test_deepseek_keys_page_renders_key_management_surface(self):
    with TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "admin.sqlite3")
        client = TestClient(
            create_app(
                settings=Settings(
                    admin_db_path=db_path,
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    admin_secret_master_key=MASTER_KEY,
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})

        response = client.get("/admin/ai-providers/deepseek/keys")

        self.assertEqual(response.status_code, 200)
        self.assertIn("DeepSeek Keys", response.text)
        self.assertIn('action="/admin/ai-providers/deepseek/keys"', response.text)
        self.assertIn("Add key", response.text)
        self.assertIn("Test all active keys", response.text)
        self.assertIn("Reload DeepSeek runtime", response.text)
```

- [x] **Step 3: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_keys_page_does_not_build_inventory_without_login \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_keys_page_renders_key_management_surface \
  -q
```

Expected: the authenticated test fails because the route does not exist.

- [x] **Step 4: Extract add-key form helper and add `deepseek_keys_body`**

In `src/translator_service/admin/views.py`, first extract the existing add-key
form markup from `_ai_provider_card(...)` into a reusable helper:

```python
def _ai_provider_key_add_form(provider_id: str, csrf_token: str) -> str:
    return f"""
      <form class="secret-form key-form" method="post"
        action="/admin/ai-providers/{escape(provider_id)}/keys">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label>
          <span>Label</span>
          <input name="label" type="text" placeholder="main" required>
        </label>
        <label>
          <span>API key</span>
          <input
            name="value"
            type="password"
            autocomplete="off"
            placeholder="Paste new value"
            required
          >
        </label>
        <label>
          <span>Weight</span>
          <input name="weight" type="number" min="1" value="1" required>
        </label>
        <label>
          <span>Max parallel</span>
          <input
            name="max_parallel_requests"
            type="number"
            min="1"
            value="1"
            required
          >
        </label>
        <button type="submit">Add key</button>
      </form>
    """
```

Then replace the inline form in `_ai_provider_card(...)` with:

```python
{_ai_provider_key_add_form(summary.integration_id, csrf_token)}
```

After that, add a new function near `ai_providers_body(...)`:

```python
def deepseek_keys_body(
    *,
    csrf_token: str,
    key_pools: dict[str, tuple[AIProviderKeySummary, ...]],
    runtime_reload_states: tuple[AIProviderRuntimeReloadRequest, ...] = (),
) -> str:
    keys = key_pools.get("deepseek", ())
    active_count = sum(
        1
        for key in keys
        if key.enabled and not key.disabled and not is_env_deepseek_key(key)
    )
    disabled_count = sum(
        1
        for key in keys
        if (not key.enabled or key.disabled) and not is_env_deepseek_key(key)
    )
    env_count = sum(1 for key in keys if is_env_deepseek_key(key))
    reload_banner = _deepseek_reload_banner(runtime_reload_states)
    rows = "\n".join(_ai_provider_key_row(key, csrf_token) for key in keys)
    if not rows:
        rows = '<p class="empty-state">No DeepSeek keys are configured.</p>'
    return f"""
    <section class="toolbar-panel">
      <div>
        <h3>DeepSeek Keys</h3>
        <p>Manage encrypted DeepSeek API keys without exposing raw secrets.</p>
      </div>
      <div class="toolbar-actions">
        <a class="secondary-action" href="/admin/ai-providers">Back to providers</a>
        {_ai_provider_test_all_keys_form(
            "deepseek",
            csrf_token=csrf_token,
            active_key_count=active_count,
        )}
        {_runtime_reload_form("deepseek", csrf_token)}
      </div>
    </section>
    {reload_banner}
    <section class="metrics">
      {_metric("Active admin keys", str(active_count))}
      {_metric("Disabled admin keys", str(disabled_count))}
      {_metric("Env keys", str(env_count))}
    </section>
    <section class="panel table-panel">
      <h3>Add key</h3>
      {_ai_provider_key_add_form("deepseek", csrf_token)}
    </section>
    <section class="panel table-panel">
      <h3>Key inventory</h3>
      <div class="key-list">{rows}</div>
    </section>
    """
```

Also add helper functions used above:

```python
def _runtime_reload_form(provider_id: str, csrf_token: str) -> str:
    return f"""
      <form class="secret-form" method="post"
        action="/admin/ai-providers/{escape(provider_id)}/runtime/reload">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <button type="submit">Reload DeepSeek runtime</button>
      </form>
    """


def _deepseek_reload_banner(
    runtime_reload_states: tuple[AIProviderRuntimeReloadRequest, ...],
) -> str:
    state = next(
        (item for item in runtime_reload_states if item.provider_id == "deepseek"),
        None,
    )
    if state is None or not state.pending:
        return ""
    return """
    <section class="panel">
      <h3>DeepSeek runtime reload pending</h3>
      <p>Key changes are saved. Reload runtime so bot and worker capacity use them.</p>
    </section>
    """
```

- [x] **Step 5: Wire route**

In `src/translator_service/admin/routes.py`, import `deepseek_keys_body` from
`translator_service.admin.views`, then add the route after `/admin/ai-providers`:

```python
@router.get("/ai-providers/deepseek/keys", response_class=HTMLResponse)
async def deepseek_keys(request: Request) -> Response:
    return _protected_page(
        request,
        session_manager=session_manager,
        environment=settings.environment,
        title="DeepSeek Keys",
        active="ai-providers",
        body=lambda session: deepseek_keys_body(
            csrf_token=session.csrf_token,
            key_pools=_ai_provider_key_pools(settings),
            runtime_reload_states=_ai_provider_runtime_reload_states(settings),
        ),
    )
```

- [x] **Step 6: Run route tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_keys_page_does_not_build_inventory_without_login \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_keys_page_renders_key_management_surface \
  -q
```

Expected: PASS.

- [x] **Step 7: Commit route skeleton**

Run:

```bash
git add src/translator_service/admin/routes.py src/translator_service/admin/views.py tests/test_admin_routes.py
git commit -m "feat: add deepseek keys admin page"
```

Expected: commit succeeds.

---

## Task 2: Overview CTA And Dedicated Key Inventory UX

**Files:**

- Modify `src/translator_service/admin/views.py`
- Modify `tests/test_admin_routes.py`

- [x] **Step 1: Add failing overview CTA test**

Add to the existing `test_ai_providers_page_and_api_show_configured_providers`
or create a focused test:

```python
def test_ai_providers_overview_links_to_deepseek_key_management(self):
    self.client.post("/admin/login", data={"password": "owner-pass"})

    response = self.client.get("/admin/ai-providers")

    self.assertEqual(response.status_code, 200)
    self.assertIn('href="/admin/ai-providers/deepseek/keys"', response.text)
    self.assertIn("Manage DeepSeek keys", response.text)
```

- [x] **Step 2: Add failing no raw key render test**

Add:

```python
def test_deepseek_keys_page_shows_masked_values_without_raw_keys(self):
    with TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "admin.sqlite3")
        client = TestClient(
            create_app(
                settings=Settings(
                    admin_db_path=db_path,
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    admin_secret_master_key=MASTER_KEY,
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/ai-providers/deepseek/keys")
        response = client.post(
            "/admin/ai-providers/deepseek/keys",
            data={
                "csrf_token": _csrf_token(page.text),
                "label": "main",
                "value": "sk-raw-secret-value",
                "weight": "2",
                "max_parallel_requests": "1",
            },
            follow_redirects=False,
        )

        updated = client.get("/admin/ai-providers/deepseek/keys")

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/admin/ai-providers/deepseek/keys",
        )
        self.assertIn("<strong>main</strong>", updated.text)
        self.assertIn("sk-****alue", updated.text)
        self.assertNotIn("sk-raw-secret-value", updated.text)
        self.assertNotIn(".api_keys.", updated.text)
```

- [x] **Step 3: Run tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_ai_providers_overview_links_to_deepseek_key_management \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_keys_page_shows_masked_values_without_raw_keys \
  -q
```

Expected: failures because overview CTA and redirects are not updated.

- [x] **Step 4: Add overview CTA**

In `src/translator_service/admin/views.py`, within the DeepSeek provider card
rendered by `ai_providers_body(...)`, add a compact link:

```html
<a class="secondary-action" href="/admin/ai-providers/deepseek/keys">
  Manage DeepSeek keys
</a>
```

Place it near the existing provider health/key pool controls. Do not remove the
existing add-key form until the dedicated page is complete unless tests are
updated accordingly.

- [x] **Step 5: Redirect DeepSeek key mutations to keys page**

In `src/translator_service/admin/routes.py`, add:

```python
def _ai_provider_keys_redirect(provider_id: str) -> str:
    if provider_id == "deepseek":
        return "/admin/ai-providers/deepseek/keys"
    return "/admin/ai-providers"
```

Replace key route redirects:

```python
return RedirectResponse(
    _ai_provider_keys_redirect(provider_id),
    status_code=HTTPStatus.SEE_OTHER,
)
```

For the DeepSeek balance refresh route, keep redirecting to `/admin/ai-providers`
because balance belongs to provider overview.

- [x] **Step 6: Run CTA and render tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_ai_providers_overview_links_to_deepseek_key_management \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_keys_page_shows_masked_values_without_raw_keys \
  -q
```

Expected: PASS.

- [x] **Step 7: Commit overview UX**

Run:

```bash
git add src/translator_service/admin/routes.py src/translator_service/admin/views.py tests/test_admin_routes.py
git commit -m "feat: improve deepseek key inventory UX"
```

Expected: commit succeeds.

---

## Task 3: Rotate Key Secret

**Files:**

- Modify `src/translator_service/admin/ai_provider_keys.py`
- Modify `src/translator_service/admin/routes.py`
- Modify `src/translator_service/admin/views.py`
- Modify `tests/test_admin_routes.py`

- [x] **Step 1: Add failing rotate test**

Add to `tests/test_admin_routes.py` near existing key update tests:

```python
def test_owner_can_rotate_ai_provider_key_without_changing_key_id(self):
    with TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "admin.sqlite3")
        client = TestClient(
            create_app(
                settings=Settings(
                    admin_db_path=db_path,
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    admin_secret_master_key=MASTER_KEY,
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/ai-providers/deepseek/keys")
        client.post(
            "/admin/ai-providers/deepseek/keys",
            data={
                "csrf_token": _csrf_token(page.text),
                "label": "main",
                "value": "sk-old-secret-value",
                "weight": "1",
                "max_parallel_requests": "1",
            },
        )
        updated = client.get("/admin/ai-providers/deepseek/keys")
        key_id = re.search(r'name="key_id" value="([^"]+)"', updated.text)
        self.assertIsNotNone(key_id)

        rotate = client.post(
            "/admin/ai-providers/deepseek/keys/rotate",
            data={
                "csrf_token": _csrf_token(updated.text),
                "key_id": key_id.group(1),
                "value": "sk-new-secret-value",
            },
            follow_redirects=False,
        )
        after_rotate = client.get("/admin/ai-providers/deepseek/keys")

        self.assertEqual(rotate.status_code, 303)
        self.assertEqual(
            rotate.headers["location"],
            "/admin/ai-providers/deepseek/keys",
        )
        self.assertIn(f'name="key_id" value="{key_id.group(1)}"', after_rotate.text)
        self.assertIn("sk-****alue", after_rotate.text)
        self.assertNotIn("sk-old-secret-value", after_rotate.text)
        self.assertNotIn("sk-new-secret-value", after_rotate.text)
        with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
            self.assertEqual(
                secrets.get_secret_value(f"deepseek.api_keys.{key_id.group(1)}"),
                "sk-new-secret-value",
            )
        with SQLiteAdminAuditLog(db_path) as audit:
            events = audit.list_events(limit=10)
        serialized_events = "\n".join(
            f"{event.action} {event.target_id} {event.metadata_json}"
            for event in events
        )
        self.assertIn("ai_provider.key.rotated", serialized_events)
        self.assertNotIn("sk-old-secret-value", serialized_events)
        self.assertNotIn("sk-new-secret-value", serialized_events)
        self.assertNotIn(".api_keys.", serialized_events)
```

- [x] **Step 2: Add failing empty rotate value test**

Add:

```python
def test_rotate_ai_provider_key_requires_non_empty_secret_value(self):
    with TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "admin.sqlite3")
        client = TestClient(
            create_app(
                settings=Settings(
                    admin_db_path=db_path,
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    admin_secret_master_key=MASTER_KEY,
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/ai-providers/deepseek/keys")

        response = client.post(
            "/admin/ai-providers/deepseek/keys/rotate",
            data={
                "csrf_token": _csrf_token(page.text),
                "key_id": "missing",
                "value": "   ",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Key value is required", response.text)
```

- [x] **Step 3: Run rotate tests and verify failure**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_owner_can_rotate_ai_provider_key_without_changing_key_id \
  tests/test_admin_routes.py::AdminRoutesTest::test_rotate_ai_provider_key_requires_non_empty_secret_value \
  -q
```

Expected: FAIL because rotate route/store method do not exist.

- [x] **Step 4: Add `rotate_key` store method**

In `src/translator_service/admin/ai_provider_keys.py`, add to
`SQLiteAIProviderKeyStore` after `update_key(...)`:

```python
def rotate_key(
    self,
    *,
    provider_id: str,
    key_id: str,
    plaintext: str,
    actor_id: str,
    secret_store: SecretStore,
) -> AIProviderKeySummary:
    row = self._editable_key_row(provider_id, key_id)
    clean_plaintext = plaintext.strip()
    if not clean_plaintext:
        raise ValueError("Key value is required")
    secret = secret_store.put_secret(
        secret_id=row["secret_id"],
        label=row["label"],
        kind="api_key",
        plaintext=clean_plaintext,
        actor_id=actor_id,
    )
    now = datetime.now(UTC)
    with self._connection:
        self._connection.execute(
            """
            UPDATE admin_ai_provider_keys
            SET updated_at = ?, updated_by = ?
            WHERE provider_id = ? AND key_id = ?
            """,
            (now.isoformat(), actor_id, provider_id, key_id),
        )
    return _summary_from_row(self._key_row(provider_id, key_id), secret)
```

- [x] **Step 5: Add rotate form to key rows**

In `src/translator_service/admin/views.py`, inside `_ai_provider_key_row(...)`
for non-env keys, add after metadata update form:

```html
<form method="post" action="/admin/ai-providers/{escape(key.provider_id)}/keys/rotate">
  <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
  <input type="hidden" name="key_id" value="{escape(key.key_id)}">
  <label>
    <span>New key value</span>
    <input name="value" type="password" autocomplete="new-password">
  </label>
  <button type="submit">Rotate</button>
</form>
```

Because this is inside a Python f-string, build `rotate_action` first:

```python
rotate_action = f"/admin/ai-providers/{escape(key.provider_id)}/keys/rotate"
```

- [x] **Step 6: Add rotate route**

In `src/translator_service/admin/routes.py`, first add this helper near the
runtime helper functions:

```python
def _request_ai_provider_runtime_reload(
    settings: Settings,
    *,
    provider_id: str,
    actor_id: str,
) -> None:
    with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as runtime:
        runtime.request_reload(provider_id=provider_id, actor_id=actor_id)
```

Then add the route after the update route:

```python
@router.post("/ai-providers/{provider_id}/keys/rotate")
async def rotate_ai_provider_key(provider_id: str, request: Request) -> Response:
    session = _session_or_none(request, session_manager)
    if session is None:
        return RedirectResponse("/admin/login", status_code=HTTPStatus.SEE_OTHER)
    form = await _urlencoded_form(request)
    if not session_manager.verify_csrf(session, form.get("csrf_token")):
        return _html("Forbidden", status_code=HTTPStatus.FORBIDDEN)
    try:
        DEFAULT_AI_PROVIDER_REGISTRY.get_definition(provider_id)
    except KeyError:
        return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
    try:
        with SQLiteEncryptedSecretStore(
            settings.admin_db_path,
            master_key=settings.admin_secret_master_key,
        ) as secrets:
            with SQLiteAIProviderKeyStore(settings.admin_db_path) as keys:
                rotated = keys.rotate_key(
                    provider_id=provider_id,
                    key_id=form.get("key_id", ""),
                    plaintext=form.get("value", ""),
                    actor_id=session.actor_id,
                    secret_store=secrets,
                )
    except ValueError as error:
        return _html(str(error), status_code=HTTPStatus.BAD_REQUEST)
    except (KeyError, SecretStoreUnavailable):
        return _html("Not found", status_code=HTTPStatus.NOT_FOUND)
    _request_ai_provider_runtime_reload(
        settings,
        provider_id=provider_id,
        actor_id=session.actor_id,
    )
    with SQLiteAdminAuditLog(settings.admin_db_path) as audit:
        audit.record(
            actor_id=session.actor_id,
            role=session.role,
            action="ai_provider.key.rotated",
            target_type="ai_provider_key",
            target_id=rotated.key_id,
            outcome=AuditOutcome.SUCCESS,
            metadata={
                "provider_id": provider_id,
                "key_id": rotated.key_id,
                "fingerprint": rotated.fingerprint,
                "runtime_reload_requested": True,
            },
        )
    return RedirectResponse(
        _ai_provider_keys_redirect(provider_id),
        status_code=HTTPStatus.SEE_OTHER,
    )
```

- [x] **Step 7: Run rotate tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_owner_can_rotate_ai_provider_key_without_changing_key_id \
  tests/test_admin_routes.py::AdminRoutesTest::test_rotate_ai_provider_key_requires_non_empty_secret_value \
  -q
```

Expected: PASS.

- [x] **Step 8: Commit rotate support**

Run:

```bash
git add src/translator_service/admin/ai_provider_keys.py src/translator_service/admin/routes.py src/translator_service/admin/views.py tests/test_admin_routes.py
git commit -m "feat: support deepseek key rotation"
```

Expected: commit succeeds.

---

## Task 4: Runtime Reload Pending After Key Mutations

**Files:**

- Modify `src/translator_service/admin/routes.py`
- Modify `src/translator_service/admin/views.py`
- Modify `tests/test_admin_routes.py`

- [ ] **Step 1: Add failing reload pending test**

Add:

```python
def test_deepseek_key_mutations_mark_runtime_reload_pending(self):
    with TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "admin.sqlite3")
        client = TestClient(
            create_app(
                settings=Settings(
                    admin_db_path=db_path,
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    admin_secret_master_key=MASTER_KEY,
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/ai-providers/deepseek/keys")
        client.post(
            "/admin/ai-providers/deepseek/keys",
            data={
                "csrf_token": _csrf_token(page.text),
                "label": "main",
                "value": "sk-reload-secret",
                "weight": "1",
                "max_parallel_requests": "1",
            },
        )

        after_add = client.get("/admin/ai-providers/deepseek/keys")
        runtime_api = client.get("/admin/api/ai-providers/runtime")

        self.assertIn("DeepSeek runtime reload pending", after_add.text)
        payload = runtime_api.json()
        deepseek = next(
            item for item in payload["providers"] if item["provider_id"] == "deepseek"
        )
        self.assertTrue(deepseek["reload_pending"])
        self.assertIsNotNone(deepseek["reload_requested_at"])
```

- [ ] **Step 2: Verify reload helper exists**

Task 3 adds `_request_ai_provider_runtime_reload(...)`. If Task 3 was skipped
or implemented differently, add this helper near the runtime helper functions:

```python
def _request_ai_provider_runtime_reload(
    settings: Settings,
    *,
    provider_id: str,
    actor_id: str,
) -> None:
    with SQLiteAIProviderRuntimeStore(settings.admin_db_path) as runtime:
        runtime.request_reload(provider_id=provider_id, actor_id=actor_id)
```

- [ ] **Step 3: Call helper after mutations**

In these routes, after successful store mutation and before audit:

- `add_ai_provider_key`;
- `remove_ai_provider_key`;
- `update_ai_provider_key`;
- `_set_ai_provider_key_enabled`;
- `rotate_ai_provider_key`.

Add:

```python
_request_ai_provider_runtime_reload(
    settings,
    provider_id=provider_id,
    actor_id=session.actor_id,
)
```

Update each audit metadata dict to include:

```python
"runtime_reload_requested": True,
```

- [ ] **Step 4: Ensure banner renders pending state**

If Task 1's `_deepseek_reload_banner(...)` only checks state presence, tighten it
to pending only:

```python
if state is None or not state.pending:
    return ""
```

`AIProviderRuntimeReloadRequest` already exposes `pending`, and
`/admin/api/ai-providers/runtime` already exposes `reload_pending`.

- [ ] **Step 5: Run reload pending tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_key_mutations_mark_runtime_reload_pending \
  tests/test_admin_routes.py::AdminRoutesTest::test_owner_can_add_and_remove_ai_provider_key_rows \
  tests/test_admin_routes.py::AdminRoutesTest::test_owner_can_update_disable_and_enable_ai_provider_key \
  -q
```

Expected: PASS.

- [ ] **Step 6: Commit reload pending UX**

Run:

```bash
git add src/translator_service/admin/routes.py src/translator_service/admin/views.py tests/test_admin_routes.py
git commit -m "feat: mark provider runtime reload after key changes"
```

Expected: commit succeeds.

---

## Task 5: Validation Status And Safe Error Visibility

**Files:**

- Modify `src/translator_service/admin/views.py`
- Modify `tests/test_admin_routes.py`

- [ ] **Step 1: Add failing validation visibility test**

Add a focused test that seeds a failed validation result and verifies safe
rendering:

```python
def test_deepseek_keys_page_shows_safe_validation_status(self):
    with TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "admin.sqlite3")
        client = TestClient(
            create_app(
                settings=Settings(
                    admin_db_path=db_path,
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    admin_secret_master_key=MASTER_KEY,
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/ai-providers/deepseek/keys")
        client.post(
            "/admin/ai-providers/deepseek/keys",
            data={
                "csrf_token": _csrf_token(page.text),
                "label": "main",
                "value": "sk-validation-secret",
                "weight": "1",
                "max_parallel_requests": "1",
            },
        )
        updated = client.get("/admin/ai-providers/deepseek/keys")
        key_id = re.search(r'name="key_id" value="([^"]+)"', updated.text)
        self.assertIsNotNone(key_id)
        with SQLiteAIProviderValidationStore(db_path) as validations:
            validations.record_result(
                provider_id="deepseek",
                key_id=key_id.group(1),
                status="auth_failed",
                error="auth failed for sk-validation-secret",
                actor_id="owner",
            )

        response = client.get("/admin/ai-providers/deepseek/keys")

        self.assertIn("auth failed", response.text)
        self.assertNotIn("sk-validation-secret", response.text)
```

- [ ] **Step 2: Extend key row rendering**

In `src/translator_service/admin/views.py`, include validation status already
present on `ProviderHealthSummary` or available key validation summaries. If
the current view does not receive per-key validation rows, update the route body
call to pass the existing provider health summaries or a new dict built from
`SQLiteAIProviderValidationStore`.

Prefer a small view model:

```python
@dataclass(frozen=True)
class AIProviderKeyValidationView:
    status: str
    error: str
    checked_at: str
```

If adding a dataclass would bloat `views.py`, place it in
`src/translator_service/admin/provider_validation.py` and import it.

- [ ] **Step 3: Keep redaction at source**

Use existing safe error helpers from provider validation/provider health. If no
public helper exists, add a small local redaction in `provider_validation.py`,
not in the HTML renderer:

```python
def safe_validation_error(value: str | None) -> str:
    if not value:
        return "n/a"
    return _redact_provider_validation_text(value)
```

Use the existing regex redaction patterns in that module.

- [ ] **Step 4: Run validation visibility test**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_keys_page_shows_safe_validation_status \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit validation visibility**

Run:

```bash
git add src/translator_service/admin/views.py src/translator_service/admin/provider_validation.py src/translator_service/admin/routes.py tests/test_admin_routes.py
git commit -m "feat: show safe deepseek key validation status"
```

Expected: commit succeeds. If `provider_validation.py` or `routes.py` was not
changed, omit it from `git add`.

---

## Task 6: Security Regression Coverage

**Files:**

- Modify `tests/test_admin_routes.py`

- [ ] **Step 1: Add no raw secret leakage regression**

Add:

```python
def test_deepseek_key_management_never_exposes_raw_secret_or_secret_id(self):
    raw_secret = "sk-never-show-this-secret"
    with TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "admin.sqlite3")
        client = TestClient(
            create_app(
                settings=Settings(
                    admin_db_path=db_path,
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    admin_secret_master_key=MASTER_KEY,
                )
            )
        )
        client.post("/admin/login", data={"password": "owner-pass"})
        page = client.get("/admin/ai-providers/deepseek/keys")
        client.post(
            "/admin/ai-providers/deepseek/keys",
            data={
                "csrf_token": _csrf_token(page.text),
                "label": "main",
                "value": raw_secret,
                "weight": "1",
                "max_parallel_requests": "1",
            },
        )

        outputs = [
            client.get("/admin/ai-providers").text,
            client.get("/admin/ai-providers/deepseek/keys").text,
            json.dumps(client.get("/admin/api/ai-providers").json(), sort_keys=True),
            json.dumps(
                client.get("/admin/api/ai-providers/runtime").json(),
                sort_keys=True,
            ),
        ]
        with SQLiteAdminAuditLog(db_path) as audit:
            outputs.extend(
                f"{event.action} {event.target_id} {event.metadata_json}"
                for event in audit.list_events(limit=20)
            )

        serialized = "\n".join(outputs)
        self.assertNotIn(raw_secret, serialized)
        self.assertNotIn("deepseek.api_keys.", serialized)
        self.assertNotIn("source_text", serialized)
        self.assertNotIn("translated_text", serialized)
```

- [ ] **Step 2: Run security regression**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py::AdminRoutesTest::test_deepseek_key_management_never_exposes_raw_secret_or_secret_id \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run all admin route tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_admin_routes.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit security regression**

Run:

```bash
git add tests/test_admin_routes.py
git commit -m "test: cover deepseek key management redaction"
```

Expected: commit succeeds.

---

## Task 7: Documentation And Runbook

**Files:**

- Modify `README.md`
- Modify `README.project.md`
- Modify `docs/deployment/admin-vps-runbook.md`
- Modify `DOCUMENT_INDEX.md`

- [ ] **Step 1: Update README key management section**

In both `README.md` and `README.project.md`, extend the existing DeepSeek admin
key paragraph with:

```markdown
Admin -> AI Providers -> DeepSeek Keys is the operator surface for key rotation
and capacity changes. Add or rotate a key there, test it, then request DeepSeek
runtime reload so bot and worker processes pick up the new key pool. Env keys
remain read-only fallbacks; admin-managed keys are stored encrypted and only
masked values are shown.
```

- [ ] **Step 2: Update VPS runbook**

In `docs/deployment/admin-vps-runbook.md`, add a `DeepSeek key operations`
subsection near the existing DeepSeek balance section:

```markdown
### DeepSeek key operations

Use Admin -> AI Providers -> DeepSeek Keys to manage admin-stored provider keys.

Recommended operator flow:

1. Add or rotate the key.
2. Test the changed key.
3. Check Admin -> AI Providers for balance and provider health.
4. Click Reload DeepSeek runtime.
5. Watch Admin -> Live for channel cooldowns, circuit state and available slots.

Never paste raw keys into issue trackers, logs or chat. The admin UI stores
admin-managed keys encrypted and renders only masked values. Env keys remain
read-only and must be changed on the server.
```

- [ ] **Step 3: Update document index**

In `DOCUMENT_INDEX.md`, add:

```markdown
- `docs/superpowers/specs/2026-05-10-deepseek-key-management-design.md` -
  design for the dedicated admin DeepSeek key management workflow: safe viewing,
  add/edit/rotate/remove/test actions and runtime reload UX.
- `docs/superpowers/plans/2026-05-10-deepseek-key-management.md` -
  implementation plan for the dedicated DeepSeek Keys admin page.
```

- [ ] **Step 4: Run docs sanity**

Run:

```bash
git diff --check -- README.md README.project.md docs/deployment/admin-vps-runbook.md DOCUMENT_INDEX.md
rg -n "DeepSeek Keys|rotate|runtime reload|masked values|read-only" README.md README.project.md docs/deployment/admin-vps-runbook.md DOCUMENT_INDEX.md
```

Expected: no whitespace errors; `rg` shows the new docs references.

- [ ] **Step 5: Commit docs**

Run:

```bash
git add README.md README.project.md docs/deployment/admin-vps-runbook.md DOCUMENT_INDEX.md
git commit -m "docs: document deepseek key operations"
```

Expected: commit succeeds.

---

## Task 8: Final Verification

**Files:**

- No implementation files unless verification finds a concrete bug.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest \
  tests/test_admin_routes.py \
  tests/test_admin_provider_health.py \
  tests/test_ai_provider_runtime.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run lint on touched files**

Run:

```bash
python3 -m ruff check \
  src/translator_service/admin/ai_provider_keys.py \
  src/translator_service/admin/routes.py \
  src/translator_service/admin/views.py \
  tests/test_admin_routes.py
```

Expected: PASS.

- [ ] **Step 3: Run compile check**

Run:

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: PASS.

- [ ] **Step 4: Run predeploy check**

Run:

```bash
bash scripts/predeploy_check.sh
```

Expected: PASS.

- [ ] **Step 5: Inspect git status**

Run:

```bash
git status --short
```

Expected: no uncommitted changes.

---

## Implementation Notes

- Keep the dedicated page DeepSeek-specific. The current beta has only one
  production provider and DeepSeek-specific balance/runtime context is useful.
- Keep all secrets write-only. Password inputs can accept raw values, but
  rendered pages, JSON and audit metadata must show only masked/fingerprint
  metadata.
- Env keys are read-only. Do not add enable/disable/remove/rotate forms for
  `is_env_deepseek_key(key)`.
- Existing provider key routes are provider-parametric. Reuse them where useful,
  but redirect DeepSeek key actions to `/admin/ai-providers/deepseek/keys`.
- Do not remove existing balance and runtime views from `/admin/ai-providers`.
- If a key has missing secret metadata, show `missing` and allow remove; enabling
  should continue to fail safely via existing `SecretNotFound` behavior.
- Runtime reload pending is an operational marker. It does not reload the worker
  by itself; the running runtime must observe the reload request as already
  implemented by the provider runtime layer.
