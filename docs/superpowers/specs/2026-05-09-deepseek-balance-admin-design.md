# DeepSeek Balance Admin Design

## Status

Proposed for the closed-beta stabilization phase.

This design is scoped by the active restart sources of truth:

- `CURRENT_PROJECT_STATE.md`
- `docs/restart/folioloom-restart-spec.md`
- `docs/restart/release-gates.md`
- `DOCUMENT_INDEX.md`

Historical archived plans are not used as roadmap input.

## Summary

FolioLoom will show the owner's DeepSeek account balance inside the SSH-tunneled
admin console. The feature is an owner-only operations signal for provider
availability and cost control. It is not user-facing billing, not paid beta, and
not a provider marketplace.

The admin console will call DeepSeek's official `GET /user/balance` endpoint
through backend code, cache a sanitized snapshot in the admin SQLite database,
render it in the AI Providers area, expose it through an authenticated admin API,
and feed low-balance/stale/error conditions into the Action Center.

## Product Boundaries

### In Scope

- Show DeepSeek balance in admin for the owner.
- Show one or more currency rows returned by DeepSeek.
- Show `is_available`, total balance, granted balance, topped-up balance,
  last checked time, last successful check time, and safe error state.
- Let the owner manually refresh the balance.
- Cache the latest snapshot so the admin page remains fast and robust.
- Warn in Action Center when the balance is low, stale, unavailable, or failed.
- Provide a safe outbound top-up link to DeepSeek billing/top-up.

### Out Of Scope

- User-facing provider/model selection.
- User-facing balance visibility.
- Telegram Stars, credits, ledger, refunds, or paid-job capture.
- In-app DeepSeek top-up or payment handling.
- New public admin exposure.
- Any raw API key, secret id, or raw provider response in UI or logs.

## UX Placement

The balance belongs on `/admin/ai-providers`, inside the DeepSeek provider card,
near provider health and runtime status. This matches the restart rule that
DeepSeek/provider choice is internal and admin-observable.

The `/admin/costs` page remains focused on FolioLoom-estimated token spend from
translation run logs. The `/admin/billing` page remains reserved for future
Telegram Stars/paid-beta billing and must not be repurposed for DeepSeek account
funding.

The DeepSeek provider card will include:

- Balance status badge: `available`, `unavailable`, `stale`, `not configured`,
  or `failed`.
- Metric cards for each currency: total, granted, topped-up.
- Last checked and last successful timestamps.
- Manual `Refresh balance` button with CSRF protection.
- `Open DeepSeek top-up` external link.

## Backend Design

### Client

Add `translator_service.admin.provider_balance`.

Responsibilities:

- Define typed dataclasses for balance rows, snapshots, and fetch results.
- Call `GET {deepseek_base_url}/user/balance`.
- Send `Authorization: Bearer <api_key>`.
- Parse only documented fields:
  - `is_available`
  - `balance_infos[].currency`
  - `balance_infos[].total_balance`
  - `balance_infos[].granted_balance`
  - `balance_infos[].topped_up_balance`
- Convert numeric strings to `Decimal`.
- Return safe statuses for timeout, HTTP failure, malformed response,
  unsupported provider, missing key, and secret-store unavailable.
- Never include raw response bodies, authorization headers, API keys, or secret
  ids in errors.

### Store

Add a SQLite-backed `SQLiteProviderBalanceStore` in the same module.

Table: `admin_provider_balance_snapshots`

Fields:

- `provider_id TEXT PRIMARY KEY`
- `status TEXT NOT NULL`
- `is_available INTEGER`
- `balances_json TEXT NOT NULL`
- `last_checked_at TEXT NOT NULL`
- `last_success_at TEXT`
- `error_code TEXT`
- `error_message TEXT`

The table is part of the existing admin SQLite database selected by
`settings.admin_db_path`.

### Service

The service will:

1. Resolve the active DeepSeek key from existing admin provider key storage.
2. Prefer the first enabled, non-disabled key by existing key order.
3. Fall back to environment bootstrap DeepSeek key if the admin key store has no
   usable configured key.
4. Fetch balance through the client.
5. Persist a sanitized snapshot.
6. Return the saved snapshot to routes/views.

If no usable key exists, the service saves or returns a `not_configured`
snapshot. If DeepSeek cannot be reached or returns an error, it saves a failed
snapshot while preserving the previous `last_success_at` where available.

## Admin API And Routes

Add authenticated endpoints:

- `GET /admin/api/ai-providers/deepseek/balance`
- `POST /admin/ai-providers/deepseek/balance/refresh`

The GET endpoint returns the latest cached snapshot and does not perform
network I/O. The POST endpoint verifies session and CSRF, performs a manual
refresh, writes an audit event, then redirects back to `/admin/ai-providers`.

Audit event:

- action: `ai_provider.balance.refreshed`
- target type: `ai_provider`
- target id: `deepseek`
- metadata: `status`, `is_available`, `currency_count`, `error_code`

Audit metadata must not include API keys, secret ids, raw response bodies, or
raw account identifiers beyond provider id.

## Freshness And Thresholds

Add settings:

- `ADMIN_DEEPSEEK_BALANCE_STALE_SECONDS`, default `300`
- `ADMIN_DEEPSEEK_LOW_BALANCE_THRESHOLD`, default `5.00`
- `ADMIN_DEEPSEEK_LOW_BALANCE_CURRENCY`, default `USD`
- `ADMIN_DEEPSEEK_TOP_UP_URL`, default DeepSeek platform/billing URL

Freshness is computed from `last_checked_at`. If the snapshot is older than the
stale threshold, the UI marks it stale and Action Center shows a warning.

Low-balance checks use the configured currency. If the configured currency is
not present, no low-balance warning is emitted; the UI still shows returned
currencies.

## Action Center Integration

Action Center receives the balance snapshot and emits:

- `deepseek_balance_not_configured` warning when no usable key exists.
- `deepseek_balance_low` warning when configured currency total is below the
  threshold.
- `deepseek_balance_unavailable` critical when DeepSeek says the account is not
  available.
- `deepseek_balance_stale` warning when the cached snapshot is stale.
- `deepseek_balance_fetch_failed` warning when the last refresh failed.

These alerts complement, but do not replace, global cost cap and kill switch
work required by Gate B.

## Security And Privacy

- All routes require the existing owner/admin session.
- POST refresh requires CSRF.
- No new public admin exposure.
- API keys stay in encrypted secret storage or environment bootstrap.
- UI shows only balance amounts and safe status metadata.
- Logs and audit records never store raw response bodies or API keys.
- Error strings are short, normalized, and redacted.
- Admin pages keep `Cache-Control: no-store`.

## Realtime Behavior

The first implementation will use cached snapshots plus manual refresh. Optional
browser polling can be added later against the authenticated GET endpoint, but
the backend will not call DeepSeek on every page render.

This gives the owner near-realtime visibility without coupling admin page loads
to provider availability or creating unnecessary external API traffic.

## Testing Requirements

Unit tests:

- Parse a successful DeepSeek balance response.
- Parse multiple currency rows.
- Reject malformed responses safely.
- Convert timeouts, HTTP 401/429/5xx, and network errors into safe statuses.
- Store and retrieve balance snapshots.
- Preserve previous `last_success_at` after a failed refresh.
- Confirm serialized snapshots do not expose raw keys or secret ids.
- Confirm Action Center emits low/stale/unavailable/failure items.

Route tests:

- GET balance API requires login.
- POST refresh requires login and CSRF.
- Manual refresh calls the service, redirects, and records audit metadata.
- AI Providers page renders balance panel without raw secrets.

Verification commands:

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_balance
PYTHONPATH=src python3 -m unittest tests.test_admin_action_center tests.test_admin_routes
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

## Release Gate Impact

This feature supports Gate B operational readiness by improving provider
diagnostics, cost visibility, and alerting. It does not satisfy paid-beta
payment blockers and must not be presented as paid billing readiness.

