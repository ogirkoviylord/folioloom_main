# Admin UX Glossary: Provider Keys And Processing Fields

Issue: #11
Parent idea: #6
Status: draft for owner review

## Purpose

This glossary defines owner-facing wording for admin surfaces around DeepSeek
keys, provider health, processing capacity, queue state, and beta cost safety.
It is a readability spec only. It does not approve new controls, expose new
data, or claim production readiness.

## Evidence Reviewed

Confirmed from:

- `src/translator_service/admin/views.py`
- `src/translator_service/admin/routes.py`
- `src/translator_service/admin/ai_provider_keys.py`
- `src/translator_service/admin/provider_health.py`
- `src/translator_service/admin/provider_runtime.py`
- `src/translator_service/admin/provider_balance.py`
- `src/translator_service/admin/live.py`
- `src/translator_service/admin/operations.py`
- `src/translator_service/admin/costs.py`
- `src/translator_service/admin/beta_safety_settings.py`
- `docs/superpowers/plans/2026-05-10-adaptive-provider-throttling-phase-3.md`
- `docs/superpowers/plans/2026-05-10-cost-aware-beta-safety-phase-4.md`

Assumptions:

- The owner is a technical operator, but the UI should not require knowing
  internal scheduler, key-pool, or circuit-breaker vocabulary.
- DeepSeek is the only provider with dedicated key and balance UX today.
- Future writable controls beyond existing key, reload, and beta safety actions
  remain `TBD` and require explicit human approval.

Unknown:

- Final owner preference for labels such as "key channel" versus "key".
- Which fields should be shown on mobile once admin UI layout is revisited.

## Redaction Rules

These values must never appear raw in admin glossary-driven UI:

- raw API keys, bearer tokens, provider tokens, secret values, secret IDs;
- raw document text, prompts, translations, or uploaded file contents;
- full provider request/response bodies;
- raw stack traces;
- provider internals that include account identifiers, headers, or unsafe error
  payloads.

Safe display patterns already present in code:

- masked key value and fingerprint metadata from the secret store;
- redacted validation/runtime error excerpts;
- counts, status codes, timestamps, safe labels, and token/cost totals.

## Field Groups

### Keys

| Current field | Owner label | Meaning | Source | Access | Healthy / unhealthy | Owner action | Redaction risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Label` | Key name | Human label for one stored provider key. | `admin_ai_provider_keys.label` via `AIProviderKeySummary`. | Writable for admin keys; read-only for env keys. | Healthy when recognizable and unique enough for operations. Unhealthy when labels are ambiguous. | Rename to a clear role, for example `primary` or `backup`. | Low if label is operator-authored. Do not put secrets in labels. |
| `API key` / `New key value` | API key value | Secret value pasted when adding or rotating a key. | Form only, stored through encrypted secret store. | Writable. | Healthy when accepted and later validation passes. | Paste only into password field, then test key and reload runtime. | High. Never echo value after submit. |
| masked key value | Masked key | Safe partial display of stored key. | `SecretMetadata.masked_value`. | Read-only. | Healthy when present. Unhealthy when `missing`. | Rotate or remove if missing. | Medium. Must stay masked. |
| enabled / disabled | Key status | Whether admin has enabled this key and the secret is usable. | `enabled` plus secret `disabled`. | Writable through Enable/Disable. | Healthy when at least one active key exists. Unhealthy if all keys are disabled. | Enable a known-good key or add a new one. | Low. |
| `Active admin keys` | Active managed keys | Count of enabled, non-env DeepSeek keys managed in admin. | Key summaries filtered by env/admin source. | Read-only. | Healthy when at least one exists. Unhealthy at zero if no env key exists. | Add or enable a key. | Low. |
| `Disabled admin keys` | Disabled managed keys | Count of admin-managed keys that cannot currently be used. | Key summaries. | Read-only. | Healthy when intentionally disabled. Unhealthy if all keys are disabled. | Review, enable, rotate, or remove. | Low. |
| `Env keys` | Server env keys | Keys loaded from server environment, not editable in admin. | Bootstrap config merged into key pool. | Read-only. | Healthy when expected by deployment. Unhealthy if owner expects admin-managed keys only. | Change server env or add admin-managed keys. | Medium. Show only masked value, never env variable value. |
| `Weight` | Traffic share | Relative share used when selecting among active keys. | `admin_ai_provider_keys.weight`. | Writable for admin keys. | Healthy when higher-capacity keys have higher weight. Unhealthy if accidental high weight overloads one key. | Lower weight or spread keys evenly. | Low. |
| `Max parallel` / `parallel` | Per-key parallel limit | Maximum simultaneous provider requests allowed for this key in one runtime. | `max_parallel_requests`. | Writable for admin keys. | Healthy when aligned with provider limits. Unhealthy if too high causes 429/timeout. | Reduce after rate limits; increase only after stable operation. | Low. |
| `Last validation` | Last key test | Latest explicit key test result. | `admin_ai_provider_validations`. | Read-only; generated by Test key/Test all. | Healthy when passed. Unhealthy on failed/error/cooldown. | Test all active keys, rotate failing keys, then reload runtime. | Medium. Error must remain redacted. |
| `Checked` | Last tested at | Time of latest key validation after current key update. | Validation store. | Read-only. | Healthy when recent enough for a manual change. Unhealthy if never checked after adding/rotating. | Run Test key or Test all active keys. | Low. |
| `Last error` | Last safe key error | Redacted validation error for owner triage. | Validation store with redaction. | Read-only. | Healthy as `n/a`. Unhealthy when non-empty. | Rotate key, check account/billing, or retry after cooldown depending on text. | Medium. Keep excerpt redacted and short. |

Recommended hidden/collapsed by default:

- raw key IDs and secret IDs: keep hidden;
- removed key history: keep hidden unless there is an audit screen;
- key fingerprint/version: collapsed or support-only unless needed for rotation
  confirmation.

### Provider Health

| Current field | Owner label | Meaning | Source | Access | Healthy / unhealthy | Owner action | Redaction risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Provider card status | Provider status | Combined status from active keys, latest validation, and runtime degradation. | `build_provider_health`. | Read-only. | Healthy: `healthy`. Unhealthy: `missing keys` or `degraded`. | Add/test keys, inspect runtime, refresh balance, reload runtime. | Low. |
| `Active keys` | Usable keys | Count of keys eligible for provider calls. | Key pool. | Read-only. | Healthy: at least one. Unhealthy: zero. | Add or enable a key. | Low. |
| `Disabled keys` | Unusable keys | Count of configured keys not eligible for provider calls. | Key pool. | Read-only. | Healthy if intentional. Unhealthy if all keys are disabled. | Enable or rotate keys. | Low. |
| `Runtime status` | Runtime state | Last reported provider runtime state from bot/worker. | `admin_ai_provider_runtime_status.status`. | Read-only. | Healthy: `ok`. Unhealthy: `missing_keys`, `error`, or stale/non-reporting. | Reload runtime, check worker/bot process, inspect provider errors. | Medium if error text is included. |
| `Runtime source` | Reporting process | Runtime process that wrote the provider snapshot. | `source`. | Read-only. | Healthy when expected process is reporting. Unhealthy when unknown/not reporting. | Check bot/worker service and shared admin DB path. | Low. |
| `Reload interval` | Runtime refresh interval | How often runtime is expected to refresh key/provider state. | `reload_interval_seconds`. | Read-only. | Healthy when freshness remains fresh. | Unknown if value is surprising; confirm env defaults. | Low. |
| `Last reload` | Last runtime refresh | Timestamp of last runtime provider snapshot. | `last_reloaded_at`. | Read-only. | Healthy when recent. Unhealthy when stale. | Check runtime process or reload. | Low. |
| `Freshness` | Runtime freshness | Derived fresh/stale indicator based on last reload age. | UI helper, stale after max of 120s or 3x interval. | Read-only. | Healthy: fresh. Unhealthy: stale/not reporting. | Check running services and DB sharing. | Low. |
| `Runtime error` | Safe runtime error | Redacted runtime-level error excerpt. | Runtime status error. | Read-only. | Healthy: `n/a`. Unhealthy when non-empty. | Use the safe reason to decide key/account/service action. | Medium. Must stay redacted. |
| `Reload requested` | Reload request | Whether an admin change is waiting for runtime consumption. | `admin_ai_provider_runtime_reload_requests`. | Read-only plus Reload action. | Healthy: no pending reload after changes are consumed. Unhealthy if pending for a long time. | Click reload or restart/check worker if it never consumes. | Low. |
| `DeepSeek account balance` status | Account balance status | Cached result of DeepSeek balance check. | `admin_provider_balance_snapshots`. | Read-only; Refresh balance is writable action. | Healthy: available/fresh. Unhealthy: stale, unavailable, not configured, error. | Refresh, top up, or inspect active keys. | Medium. Error must stay safe. |
| Currency total/granted/top-up | Provider balance | Balance amounts returned by DeepSeek. | DeepSeek `/user/balance` response cached safely. | Read-only. | Healthy when enough for beta usage. Unhealthy when low/zero or unavailable. | Top up or pause beta translations. | Medium. Reveals account balance, but not secrets. |

Recommended hidden/collapsed by default:

- full runtime error payloads and provider response bodies: never show;
- internal provider IDs: keep as support detail unless multiple providers exist;
- last success/failure counters by provider: show only when troubleshooting.

### Processing Capacity

| Current field | Owner label | Meaning | Source | Access | Healthy / unhealthy | Owner action | Redaction risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Adaptive throttle` | Automatic capacity control | Whether runtime is auto-adjusting provider concurrency. | `provider_state.adaptive_enabled`. | Read-only. | Healthy: enabled in beta. Unhealthy if disabled unexpectedly. | Confirm env/config before changing behavior. | Low. |
| `limit current/max` | Current provider limit | Current provider-wide request limit versus configured max capacity. | Runtime provider state. | Read-only. | Healthy when it ramps under success and decreases under failures. Unhealthy if stuck at zero/one while queue grows. | Check rate limits, account status, keys, and runtime errors. | Low. |
| `active` | Active provider requests | Provider requests currently in flight. | Runtime provider state or channel active counts. | Read-only. | Healthy when below or equal to limit. Unhealthy if high while progress stalls. | Wait briefly, then inspect failures and worker health. | Low. |
| `available` / `Available provider slots` | Available provider slots | Provider starts currently allowed by adaptive throttle. | Runtime provider state. | Read-only. | Healthy above zero when queue exists. Unhealthy zero with queued work unless circuit/cooldown explains it. | Inspect circuit, cooldowns, account/billing errors. | Low. |
| `circuit` / `Provider circuit` | Provider safety circuit | Circuit breaker state: closed, open, or half-open. | Runtime provider state. | Read-only. | Healthy: closed. Unhealthy: open/half-open. | Wait reset window, check auth/billing/rate-limit errors, then test keys. | Low. |
| `reason` | Last capacity reason | Safe reason for last throttle/circuit change. | Runtime provider state `last_reason`, redacted. | Read-only. | Healthy: `n/a` or expected recent event. Unhealthy: repeated auth/billing/rate-limit reasons. | Match owner action to reason. | Medium. Keep reason safe and short. |
| `open for` | Circuit reset wait | Remaining time before open circuit can try again. | Runtime provider state. | Read-only. | Healthy when counting down after provider trouble. Unhealthy if repeatedly reopens. | Wait, then test keys/account if it reopens. | Low. |
| `ramp/decrease/open` | Capacity adjustment counts | Counters for adaptive ramp-ups, decreases, and circuit opens. | Runtime provider state. | Read-only. | Healthy: occasional changes. Unhealthy: frequent decreases/opens. | Review limits, key health, account balance, provider incidents. | Low. |
| channel `health` | Key channel health | Per-key runtime health: healthy, cooling down, degraded. | Runtime channel snapshot. | Read-only. | Healthy: healthy. Unhealthy: cooling down/degraded. | Reduce parallelism, wait cooldown, or rotate/test key. | Low. |
| `cooldown` | Key cooldown | Remaining wait before a key channel can be used again. | Runtime channel snapshot. | Read-only. | Healthy: 0s. Unhealthy when many channels cooling down. | Wait, reduce per-key parallel, inspect 429/503/timeout. | Low. |
| `latency` | Provider latency | Last latency if available, otherwise average latency. | Runtime channel snapshot. | Read-only. | Healthy: stable for workload. Unhealthy: rising latency with queue growth. | Lower concurrency or inspect provider/network health. | Low. |
| `started/ok/temp/perm` | Request outcome counts | Per-channel started, successful, temporary failure, permanent failure counts. | Runtime channel counters. | Read-only. | Healthy: successes dominate. Unhealthy: temp/perm failures rising. | Troubleshoot by failure type. | Low. |
| `429/503/timeout/auth/billing` | Failure type counts | Per-channel failure categories. | Runtime channel counters. | Read-only. | Healthy: zeros or rare. Unhealthy: repeated 429, timeout, auth, billing. | 429: reduce parallelism. Timeout/503: wait/retry. Auth: rotate key. Billing: top up or pause. | Low. |

Recommended hidden/collapsed by default:

- `ramp/decrease/open` counters;
- per-channel detailed failure counters;
- internal `error_kind` and last error excerpt unless provider status is degraded;
- exact channel labels if they become too close to secret IDs. Current labels
  are safe only when owner-authored labels stay non-secret.

### Queue State

| Current field | Owner label | Meaning | Source | Access | Healthy / unhealthy | Owner action | Redaction risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Active translations` | Running translations | Count of active logged runs and running jobs. | Live run logs plus operations overview. | Read-only. | Healthy when matched to expected user activity. Unhealthy if stuck high without progress. | Inspect recent runs and operations. | Low. |
| `Queued` | Waiting translations | Count of queued jobs waiting for processing. | Operations overview job states. | Read-only. | Healthy when drains over time. Unhealthy if growing while capacity is available. | Check workers, provider slots, beta pause, and queue depth. | Low. |
| `Failed today` | Failed today | Count of failed/interrupted/error runs started today. | Translation run logs. | Read-only. | Healthy: zero or explainable. Unhealthy when rising. | Inspect logs and recent errors. | Low. |
| `Queue depth` | Waiting work units | Total queued/pending work depth. | Operations overview queue depths or pending units. | Read-only. | Healthy when proportional to active workload. Unhealthy if rising for long periods. | Check workers and provider capacity. | Low. |
| `Oldest pending` | Longest wait | Age of oldest pending work unit. | Operations overview. | Read-only. | Healthy when short. Unhealthy when increasing. | Check stalled workers, provider circuit, or beta pause. | Low. |
| Job `State` | Job state | Normalized job status for owner scanning. | Persistent job state. | Read-only. | Healthy: queued/running/succeeded. Unhealthy: failed/unknown. | Pause/cancel/delete when appropriate, inspect logs. | Low. |
| Job id | Job ID | Internal job identifier for support and logs. | Persistent job store. | Read-only. | Healthy when linkable to logs. | Use for support/debugging only. | Low, but avoid exposing to users unless needed. |
| Order id | Order ID | User/order correlation ID if present. | Persistent job store. | Read-only. | Unknown, depends on future billing/order model. | TBD. | Medium if it becomes payment-related. |
| Started/updated | Job timing | Created/started and last updated timestamps. | Persistent job store. | Read-only. | Healthy when updates move during active work. Unhealthy if stale while running. | Check worker heartbeat and logs. | Low. |
| Fragments / Progress | Translation progress | Completed units out of total units, with percent when known. | Work units or translation summaries. | Read-only. | Healthy when increasing. Unhealthy when stuck. | Inspect recent errors, worker status, provider capacity. | Low. |
| ETA | Estimated time left | Estimated remaining time from progress and elapsed time. | Live monitor derived value. | Read-only. | Healthy when present for active progress. Unknown early in a run. | No action unless stuck. | Low. |
| Resources | Provider resources | Summary of active provider requests, capacity, active key channels, available slots. | Runtime snapshot attached to live run rows. | Read-only. | Healthy when active requests fit capacity and slots recover. Unhealthy if 0 slots with queue. | Inspect capacity/circuit/key health. | Low. |
| Worker ids | Active workers | Worker IDs currently associated with a job. | Work-unit metadata. | Read-only. | Healthy when running jobs have workers. Unhealthy if queued forever or worker stale. | Check worker service. | Low to medium. Keep internal-only. |
| Error | Safe job error | Redacted/truncated job or unit error excerpt. | Operations summary redaction. | Read-only. | Healthy when empty. Unhealthy when non-empty. | Inspect logs; fix input/provider/runtime issue. | Medium. Never show raw stack traces or text. |

Recommended hidden/collapsed by default:

- worker IDs and work-unit IDs: collapsed support details;
- raw status values when a normalized owner label exists;
- order IDs until payment/order model is finalized;
- error details beyond short redacted excerpt.

### Cost And Safety Guardrails

| Current field | Owner label | Meaning | Source | Access | Healthy / unhealthy | Owner action | Redaction risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Tokens today` | Tokens used today | Total tokens from runs started today. | Translation run logs. | Read-only. | Healthy within expected beta usage. Unhealthy if spike is unexpected. | Check top runs/users and beta caps. | Low. |
| `Tokens last hour` | Tokens used last hour | Recent token usage. | Translation run logs. | Read-only. | Healthy when proportional to active runs. Unhealthy if spike during suspected abuse. | Pause beta or tighten caps. | Low. |
| Cost today/7 days/month | Estimated provider cost | Estimated USD cost from token counts and configured rates. | Cost analytics over run logs. | Read-only. | Healthy under caps. Unhealthy near or over budget. | Pause beta, lower caps, inspect top users/runs. | Low to medium. Reveals spend. |
| Top runs | Highest-cost runs | Runs sorted by estimated cost. | Cost analytics over run logs. | Read-only. | Healthy when expected. Unhealthy when one run dominates. | Inspect logs and user. | Medium. File names/user IDs may be sensitive. |
| Top users | Highest-usage users | Users sorted by token/cost usage. | Cost analytics over run logs. | Read-only. | Healthy when expected beta testers. Unhealthy if one user dominates. | Adjust allowlist/caps. | Medium. User IDs are operational identifiers. |
| `Pause all beta translations` | Pause beta translations | Kill switch for new beta translation work. | Admin settings store, loaded by beta safety guard. | Writable. | Healthy off during normal beta, on during incidents. | Turn on during budget/provider incidents; turn off after resolution. | Low. |
| Global daily/monthly cost cap | Global spend cap | Overall beta budget limits. | Admin settings store. | Writable. | Healthy when set to owner-approved amounts. Unhealthy if missing or too high for beta. | Set conservative caps. | Low. |
| Per-user daily/monthly cost cap | Per-user spend cap | Budget limit per beta user. | Admin settings store. | Writable. | Healthy when prevents one-user spend spikes. | Lower if abuse/testing risk rises. | Low. |
| Per-user daily job limit | Per-user job cap | Max jobs per user per day. | Admin settings store. | Writable. | Healthy when matches beta policy. | Lower during abuse or provider incidents. | Low. |
| Max estimated cost per job | Per-job estimate cap | Rejects a job whose estimated cost is too high. | Admin settings store. | Writable. | Healthy when protects beta from large documents. | Lower for safety, raise only after review. | Low. |
| Budget warning fraction | Budget warning threshold | Fraction of cap where admin warning appears. | Admin settings store. | Writable. | Healthy around 0.80 unless owner chooses otherwise. | Adjust if warnings are too early/late. | Low. |
| Daily/monthly reserved | Reserved budget | Cost reserved for accepted jobs not fully consumed/released. | Beta safety store summary. | Read-only. | Healthy when it clears as jobs finish/cancel. Unhealthy if stuck high. | Inspect active/stuck jobs. | Low. |
| Daily/monthly consumed | Consumed budget | Actual recorded usage from completed work units. | Beta safety store summary. | Read-only. | Healthy under caps. Unhealthy near cap. | Pause beta or adjust caps. | Low. |
| Daily/monthly remaining | Remaining budget | Cap minus reserved/consumed total. | Derived beta safety summary. | Read-only. | Healthy positive. Unhealthy near zero or negative. | Pause beta, top up, or wait for period reset. | Low. |

Recommended hidden/collapsed by default:

- raw reservation rows and work-unit usage events;
- internal reason codes unless a warning/action needs them;
- rate settings (`BETA_COST_INPUT_USD_PER_MILLION`,
  `BETA_COST_OUTPUT_USD_PER_MILLION`) because they are restart-only and should
  be changed deliberately.

## Label Recommendations

Use these owner-facing replacements first:

| Internal or current wording | Preferred wording |
| --- | --- |
| Max parallel | Per-key parallel limit |
| Adaptive limit | Current provider limit |
| Provider circuit | Provider safety circuit |
| Available provider slots | Available provider slots |
| Degraded channels | Keys with provider trouble |
| 429 count | Rate-limit count |
| Timeout count | Timeout count |
| Runtime source | Reporting process |
| Freshness | Runtime freshness |
| Queue depth | Waiting work units |
| Oldest pending | Longest wait |
| Resources | Provider resources |
| Budget warning fraction | Budget warning threshold |

## First Implementation Issue Recommendation

Recommended next issue: read-only copy/readability pass for AI Providers and
Live Monitor.

Scope:

- Rename labels using the table above.
- Add short help text/tooltips for provider capacity, safety circuit, and
  per-key parallel limit.
- Collapse detailed per-channel counters behind a troubleshooting section.
- Keep all existing controls and behavior unchanged.
- Add/adjust view tests only for visible text and redaction expectations.

Out of scope for that next issue:

- New controls.
- Scheduler/runtime behavior changes.
- Secret handling changes.
- Production readiness claims.

