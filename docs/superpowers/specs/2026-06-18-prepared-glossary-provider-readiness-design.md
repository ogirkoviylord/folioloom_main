# Prepared Glossary Provider Readiness Design

Status: design-only architecture review for #685.
Date: 2026-06-18.
Verdict: NEEDS APPROVAL before implementation that changes provider/runtime
behavior.

This report designs a production-like readiness check for prepared-glossary
provider work. It does not implement runtime/provider changes, edit provider
configuration, call live providers, change cache behavior, change storage/admin
state, or claim glossary/release readiness.

## Confirmed

- `bot_runtime_config_from_settings()` can build a prepared-glossary provider
  from the existing DeepSeek channel configuration when channels are available.
- `build_translation_service()` wires a prepared glossary prep resolver only
  when a resolver or provider-backed prep service is configured.
- `BotTranslationService` already separates attachment resolver, prep resolver,
  beta-safety reservation, provider/prep attachment metadata and fail-closed
  handling for some `with_glossary` paths.
- `PreparedGlossaryPrepService` already emits metadata-only statuses for local
  planning, provider missing/failed/empty, provider usage policy, package
  validation and candidate quality.
- `DeepSeekPreparedGlossaryProvider` already returns metadata-only provider
  status/reason codes and rejects invalid JSON, unsafe raw/secret payloads and
  package-boundary mismatches.
- Prepared package validation metadata is compact and redacted: it does not
  include raw prompts, source excerpts, provider bodies, translations or keys.

## Unknown

- Whether production-like provider readiness should fail closed when no provider
  is configured for an explicit `with_glossary` run is Unknown.
- Whether owner-facing admin UI should show this readiness state beyond existing
  run/event diagnostics is Unknown.
- Whether readiness should distinguish env-backed channels from admin-key-store
  channels is Unknown. The design below treats this as optional redacted metadata
  only.
- Live provider reliability, account status and real-book glossary quality are
  Unknown unless separately approved and evidenced.

## TBD

- TBD: Owner policy for `provider_not_configured` on explicit
  `with_glossary` runs: continue with `not_effective` metadata or fail closed
  before queueing.
- TBD: Owner policy for admin surface changes. This design is compatible with
  ordinary owner-only run/event metadata and does not require admin UI changes.
- TBD: Whether any live provider smoke is later approved. This issue does not
  approve it.

## Goals

- Make provider readiness explicit before interpreting glossary quality.
- Separate provider/config availability, local prep, provider call, package
  validation and runtime injection.
- Preserve fail-safe behavior and metadata-only diagnostics.
- Keep provider keys, request bodies, response bodies, prompts and raw document
  text out of ordinary docs, issues, logs and PR artifacts.

## Non-Goals

- No provider config/key edits.
- No live provider calls.
- No Telegram operation by Codex.
- No cache reuse changes.
- No database/schema/runtime-state/storage/admin/retention changes.
- No release, beta-readiness, privacy, legal or support claims.
- No change to #465 cache-bypass behavior.

## Affected Components

- `src/translator_service/bot/runtime.py`: observes whether a provider-backed
  prep resolver can be built from existing settings/channel configuration.
- `src/translator_service/bot_translation_service.py`: decides attachment,
  prep, beta-safety reservation and fail-closed/continue behavior.
- `src/translator_service/glossary_prepared_prep_service.py`: local prep,
  provider invocation, provider usage policy and package validation metadata.
- `src/translator_service/glossary_prepared_provider.py`: DeepSeek-compatible
  provider adapter and redacted provider metadata.
- `src/translator_service/glossary_prepared_package.py`: READY/invalid package
  validation metadata.
- Runtime resolver/runner diagnostics: records whether READY package metadata
  actually becomes rendered glossary context.

## Proposed Readiness Envelope

All prepared-glossary readiness diagnostics should be metadata-only:

```json
{
  "schema_version": "prepared-glossary-readiness-v1",
  "metadata_only": true,
  "raw_payload_included": false,
  "requested": true,
  "overall_status": "provider_not_configured",
  "stage": "provider_config",
  "policy_action": "continue_without_glossary",
  "diagnostic_severity": "warning",
  "reason_codes": ["prepared_glossary_provider_not_configured"],
  "provider": {
    "configured": false,
    "provider_role_id": "deepseek-pro-glossary-prep-v1",
    "provider_model": "deepseek-v4-pro",
    "channel_status": "absent"
  },
  "package": {
    "status": "Unknown"
  },
  "runtime": {
    "glossary_effective_status": "not_effective"
  }
}
```

Allowed provider metadata:

- configured boolean;
- provider role id and model id already present in current metadata;
- redacted channel status: `absent`, `present`, `unavailable`, `Unknown`;
- optional channel count bucket: `0`, `1`, `2_plus`, `Unknown`.

Forbidden provider metadata:

- API keys, tokens, auth headers, encrypted secret payloads;
- raw provider request/response bodies;
- raw prompts or source/translated text;
- full base URLs if they include credentials or environment-specific internals;
- provider key identifiers unless a separate owner-only admin surface approves
  them.

## Readiness States

| State | Stage | Meaning | Metadata Severity | Policy Action |
| --- | --- | --- | --- | --- |
| `not_requested` | request | Glossary mode is not `with_glossary`. | info | Continue existing translation path. |
| `provider_not_configured` | provider_config | No prepared-glossary prep provider can be built from existing channel config. | warning or error | TBD: continue without glossary for optional automatic mode; fail closed for explicit `with_glossary` only if owner approves. |
| `provider_configured` | provider_config | Provider-backed prep resolver exists, but no call has started. | info | Continue to local prep/beta-safety gates. |
| `beta_safety_blocked` | beta_safety | Prep reservation/cost guard blocked prep. | warning | Preserve beta safety. Continue/fail closed according to current mode policy; do not treat as quality failure. |
| `local_prep_skipped` | local_prep | Document kind, source hash, local planning or candidate quality produced no provider packet. | warning | No provider call; mark not effective. |
| `provider_requested` | provider | Provider request started. | info | Await provider result. |
| `provider_failed` | provider | Provider exception, timeout, transport failure or empty result. | error | Fail closed for required `with_glossary`; optional automatic mode may continue with not-effective metadata. |
| `provider_invalid_response` | provider | Invalid JSON, unsafe raw/secret payload or packet-boundary mismatch. | error | Reject payload; fail closed when required. |
| `provider_usage_policy_blocked` | provider | Provider usage missing when required or token cap exceeded. | error | Reject payload; preserve beta safety accounting. |
| `package_not_ready` | package_validation | Validation returned invalid, needs-review, target mismatch or no READY entries. | error | No runtime package; fail closed when required. |
| `package_ready` | package_validation | Prepared package validates READY for target. | info | Attach package metadata and pass to runtime resolver. |
| `runtime_planned` | runtime | Runtime resolver accepted READY package and planned prompt context. | info | Continue with existing cache-bypass policy. |
| `runtime_injected` | runtime | Glossary context rendered into the provider prompt. | info | Mark `effective_observed`; this is not translation-quality proof. |
| `runtime_not_effective` | runtime | READY/prep metadata did not produce rendered context. | error | Mark not effective; preserve existing fallback/cache behavior. |

## Fail-Closed Matrix

| Scenario | Current Evidence | Recommended Behavior |
| --- | --- | --- |
| `without_glossary` | Current code returns disabled/not requested. | Continue unchanged. |
| Existing attachment resolver returns READY package | Current tests cover attachment and context injection. | Continue unchanged; record readiness `package_ready`. |
| No resolver and no prep provider | Current settings path returns no prep resolver when channels are absent. | TBD owner policy: either continue with `provider_not_configured` or fail closed for explicit `with_glossary`. |
| Prep resolver exists but returns missing/disabled/not READY | Current prep path can fail closed when not ready. | Preserve fail-closed for explicit `with_glossary`; optional automatic mode requires separate policy. |
| Beta safety reservation denied | Current code skips prep and records beta-safety metadata. | Preserve safety gate; do not call provider. |
| Provider call fails or returns empty/invalid/unsafe payload | Current provider/prep metadata records safe reason codes. | Reject payload; fail closed when `with_glossary` is required. |
| READY package attaches but runtime does not render context | Current diagnostics can mark not effective. | Continue existing translation fallback/cache behavior; mark error-level not effective. |

## Diagnostic Rules

- Do not call the provider just to probe readiness.
- Observe provider configured/not configured only through existing settings and
  runtime builder inputs.
- Readiness status must not say READY until package validation returns READY.
- Runtime status must not say effective until glossary context is rendered.
- Provider failures must remain reason-code based and redacted.
- Beta-safety blocks are safety/cost states, not glossary-quality states.
- Local/fake/provider-boundary evidence is not release readiness.

## Test Plan For Follow-Up Implementation

- `tests/test_bot_runtime.py`: settings with no DeepSeek channels reports
  `provider_not_configured` without secrets or provider calls.
- `tests/test_bot_runtime.py`: settings with fake/admin/env channel config builds
  provider-backed prep and reports `provider_configured` using only redacted
  metadata.
- `tests/test_glossary_prepared_prep_service.py`: fake provider READY package
  reports `package_ready`, selected candidate counts and usage metadata.
- `tests/test_glossary_prepared_prep_service.py`: missing provider, provider
  exception, empty provider, invalid JSON, unsafe package and token-cap states
  map to explicit readiness states.
- `tests/test_bot_translation_service.py`: explicit `with_glossary` not-ready
  behavior follows the owner-approved fail-closed/continue policy.
- `tests/test_bot_translation_service.py`: READY package that later produces no
  rendered context records `runtime_not_effective`.
- `tests/test_glossary_prepared_provider.py`: provider adapter metadata never
  includes prompt body, request body, response body, source text or key material.
- Required implementation gates: focused unit tests, `PYTHONPATH=src python3 -m
  compileall src`, targeted ruff, `git diff --check`, repo-level `pr-review`.

## Recommended Follow-Up Tasks

1. Implement metadata-only readiness envelope.
   - Scope: helper/envelope mapping around existing attachment/prep/provider
     metadata, no behavior change.
   - Files: `bot_translation_service.py`,
     `glossary_prepared_prep_service.py`,
     `glossary_prepared_provider.py`, tests.

2. Add provider-config observation without secret exposure.
   - Scope: record `provider_configured` / `provider_not_configured` from the
     existing runtime builder path.
   - Files: `bot/runtime.py`, `tests/test_bot_runtime.py`.
   - Out of scope: editing keys, env files, admin settings, live provider calls.

3. Decide and implement fail-closed policy for `provider_not_configured`.
   - Scope: only after owner answers the TBD policy above.
   - Files: `bot_translation_service.py`, tests.
   - Out of scope: runtime/provider config changes, admin UI, release claims.

4. Optional admin visibility follow-up.
   - Scope: only if owner wants owner-only admin UI/readout beyond existing
     event/run metadata.
   - Approval required: admin surface/security review.

## Architecture Review Output

- Verdict: NEEDS APPROVAL for behavior changes; SAFE as docs-only design.
- Primary risk: provider/readiness state changes can alter user-visible
  translation outcomes and beta cost behavior.
- Required approval: provider behavior, fail-closed policy, live provider calls,
  admin UI, storage/state/retention or provider config changes.
- Recommended shape: first add metadata-only envelope with fake-provider tests,
  then make any fail-closed behavior change in a separate PR after owner policy
  approval.
