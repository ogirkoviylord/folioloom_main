# DeepSeek Key Management Admin Design

## Purpose

FolioLoom already has encrypted admin-managed AI provider keys, DeepSeek runtime
reload requests, provider validation, provider balance checks and audit logs.
The current operator experience is still too cramped: key forms sit inside the
general AI Providers overview and day-to-day actions such as rotating a key,
testing a failing key or reloading runtime capacity are not visually centered.

This feature turns DeepSeek API key operations into a focused admin workflow:
admins can view, add, edit, rotate, disable, enable, remove and test DeepSeek
keys without seeing raw secrets, while understanding when worker/bot runtime
reload is needed.

## Product Placement

Primary page:

- `/admin/ai-providers/deepseek/keys`
- Navigation label: `DeepSeek Keys`
- Entry point from `/admin/ai-providers`: `Manage DeepSeek keys`

The existing `/admin/ai-providers` page remains the provider overview for
health, balance, runtime and high-level key counts. It should not become a
dense key editor.

## Existing Building Blocks

The implementation must reuse these existing components:

- `SQLiteAIProviderKeyStore` for admin-managed key metadata.
- `SQLiteEncryptedSecretStore` for encrypted secret values.
- `SQLiteAIProviderValidationStore` for key test results.
- `SQLiteAIProviderRuntimeStore` for reload requests/state.
- `load_ai_provider_runtime_keys(...)` and existing runtime reload behavior.
- `build_provider_health(...)`, runtime status and balance summaries.
- Existing audit log redaction and CSRF protection.

The design should not introduce Redis, a new scheduler dependency or raw API key
storage outside the encrypted secret store.

## UX Requirements

The dedicated keys page must show:

- env-provided DeepSeek keys as read-only rows;
- active admin-managed keys;
- disabled admin-managed keys;
- optionally removed keys in a collapsed or secondary section;
- label;
- masked key value;
- fingerprint when available;
- enabled/disabled/missing-secret state;
- weight;
- max parallel requests;
- last validation status and safe error excerpt;
- runtime reload pending state;
- safe runtime/channel hints when available.

The page must support these actions:

- add key;
- edit metadata: label, weight, max parallel requests;
- rotate key secret value;
- disable key;
- enable key;
- remove key;
- test one key;
- test all active keys;
- request DeepSeek runtime reload.

Plaintext keys must only appear in write-only form inputs. After submit, the UI,
JSON responses, audit events and logs must not expose the submitted key.

## Proposed UI Shape

`/admin/ai-providers`:

- keep provider summary cards;
- keep DeepSeek balance panel;
- keep provider runtime panel;
- replace the dense key editor with a compact key inventory summary:
  - active admin keys;
  - disabled admin keys;
  - env keys;
  - problem keys;
  - last validation status;
  - link/button to `/admin/ai-providers/deepseek/keys`.

`/admin/ai-providers/deepseek/keys`:

- top toolbar:
  - `DeepSeek Keys`;
  - link back to AI Providers;
  - `Test all active keys`;
  - `Reload DeepSeek runtime`;
- warning banner when reload is pending;
- add key form;
- key table grouped by source/state:
  - `Environment keys` read-only;
  - `Active admin keys`;
  - `Disabled admin keys`;
  - `Removed keys` only if explicitly included in the view;
- each admin key row has compact actions:
  - save metadata;
  - rotate secret;
  - disable/enable;
  - test;
  - remove.

## Data Model Changes

`admin_ai_provider_keys` remains the metadata table. It already has:

- `provider_id`
- `key_id`
- `secret_id`
- `label`
- `enabled`
- `removed`
- `weight`
- `max_parallel_requests`
- timestamps and actor

Add a store method, not a new table:

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
    """Replace the encrypted value for an existing admin-managed key."""
```

The method keeps `key_id`, `secret_id`, label, weight and max parallel requests.
It writes a new encrypted secret value to the same secret id and updates the key
row timestamp. If the secret had been disabled because the key is disabled, the
rotated key can remain disabled at the key metadata layer; rotation must not
implicitly enable it.

## Routing

Add:

- `GET /admin/ai-providers/deepseek/keys`
- `POST /admin/ai-providers/deepseek/keys/rotate`

Update existing key mutation routes to redirect back to the dedicated keys page
when `provider_id == "deepseek"`:

- add;
- update;
- remove;
- enable;
- disable;
- test;
- test-all.

Existing generic routes can remain provider-parametric. The new dedicated page
is DeepSeek-specific because DeepSeek is the only production provider in the
current beta.

## Runtime Reload Behavior

Any key inventory mutation should mark DeepSeek runtime reload as pending:

- add key;
- edit metadata;
- rotate key;
- disable key;
- enable key;
- remove key.

The mutation audit event should include safe metadata:

```json
{
  "provider_id": "deepseek",
  "key_id": "<safe-key-id>",
  "runtime_reload_requested": true
}
```

The explicit `Reload DeepSeek runtime` action remains available and audited as
`ai_provider.runtime.reload_requested`.

## Security And Privacy

The feature must preserve these invariants:

- no raw API keys in HTML after submit;
- no raw API keys in JSON payloads;
- no raw API keys in audit metadata or reason fields;
- no raw document text, prompts or translations in key management pages;
- secret ids such as `deepseek.api_keys.<id>` should not be shown in UI or audit
  payloads unless existing redaction already masks them;
- env keys are read-only and cannot be disabled, removed or rotated from admin;
- CSRF is required for every mutating route;
- unauthenticated requests must not build key inventory, balance or runtime
  snapshots.

## Error Handling

User-facing errors stay safe and short:

- unknown provider/key: `Not found`;
- missing or unavailable secret store: `Key secret is unavailable`;
- invalid numeric settings: `Invalid key settings`;
- empty rotate value: `Key value is required`;
- no active keys to test: existing `No active keys to test`.

Provider validation errors can be shown only as safe, redacted excerpts using the
existing validation/provider redaction helpers.

## Testing Strategy

Add or update admin route tests for:

- unauthenticated dedicated page redirects without building key inventory;
- dedicated page renders env keys as read-only;
- dedicated page renders active and disabled admin keys without raw values;
- add key redirects to dedicated page and marks runtime reload pending;
- metadata update redirects to dedicated page and marks reload pending;
- rotate key replaces encrypted secret value, preserves key id, keeps plaintext
  out of page/audit, and marks reload pending;
- disable/enable/remove redirect to dedicated page and mark reload pending;
- test/test-all are visible on the dedicated page and keep validation output
  redacted;
- AI Providers overview links to `Manage DeepSeek keys` and stays a summary;
- raw API key strings, `deepseek.api_keys.` secret ids and raw document text do
  not appear in HTML, JSON or audit assertions.

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_admin_routes.py \
  tests/test_admin_provider_health.py tests/test_ai_provider_runtime.py -q
python3 -m ruff check src/translator_service/admin/routes.py \
  src/translator_service/admin/views.py \
  src/translator_service/admin/ai_provider_keys.py tests/test_admin_routes.py
bash scripts/predeploy_check.sh
```

## Non-Goals

- No public API key management.
- No user-facing key management.
- No paid billing ledger changes.
- No provider abstraction redesign.
- No Redis dependency.
- No raw key viewer.
- No automatic balance top-up.

## Rollout Notes

This can ship before pushing the Phase 1-4 work to GitHub. It is an admin-only
operator UX improvement over already existing storage/runtime primitives. The
main implementation risk is accidental secret leakage in HTML/audit/tests, so
tests should aggressively assert that submitted raw keys and `deepseek.api_keys.`
do not appear in rendered/admin outputs.
