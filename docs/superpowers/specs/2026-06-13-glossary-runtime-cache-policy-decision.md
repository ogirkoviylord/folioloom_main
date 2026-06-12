# Glossary Runtime Cache Policy Decision

Status: owner-approved design-only decision for GitHub issue #465 / #204AG.
Date: 2026-06-13.
Scope: first runtime-adjacent glossary prompt adapter cache policy. No code, no
runtime prompt injection, no live provider calls, no cache mutation/migration,
no database/schema/state changes, no storage/admin/retention changes and no
release/privacy/legal/support claims.

## Routing Receipt

- Classification: risky task / docs-only architecture decision.
- Risk level: high, because glossary/profile context can affect translation
  output and stale cache reuse can preserve incorrect non-glossary translations.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` and `pr-review`.
- Approval status: approved with evidence. Owner approved the #465 cache policy
  in GitHub issue #465 on 2026-06-12.
- Allowed action: architecture/design docs only.
- Verification plan: docs review, `git diff --check`, redaction scan and
  repo-level `pr-review`.

## Decision

For the first runtime-adjacent glossary prompt adapter, use **cache bypass** for
any glossary-injected enabled/test-path translation unit.

Default runtime behavior and existing non-glossary cache behavior must remain
unchanged.

Compact glossary/profile/snapshot/selection signatures may be emitted as
metadata for planning, diagnostics and future cache-key design, but they must
not enable cache reuse for glossary-injected units in the first adapter.

Future glossary-aware cache keys require a separate approved issue after
provider evidence and disabled-adapter tests.

## Current Evidence

- Existing `MemoryTranslationCache` can include optional
  `TranslationPolicySignatureContext` in its cache key.
- Existing `TranslationPolicySignatureContext` is compact and validates
  glossary/profile/snapshot/selection signatures plus selected rule ids.
- Existing glossary selection and translation contract snapshot modules already
  emit compact signatures/metadata that can identify planning inputs.
- #451 recorded normal runtime glossary prompt integration as NO-GO and cache
  behavior as unresolved.
- #463 records post-#461/#462 local/fake structural improvement, but default
  local readiness still fails. Therefore post-fix provider evidence remains
  `Unknown` and #464 should not start under the current approval wording.

These facts are enough to decide the first adapter's cache boundary, but not
enough to approve runtime prompt rollout or cache reuse for glossary-injected
units.

## Options Compared

| Option | Correctness | Stale-cache risk | Cost/latency | Rollback | Testing implications | Decision |
| --- | --- | --- | --- | --- | --- | --- |
| Glossary-aware cache keys now | Potentially correct if every output-affecting glossary/profile/snapshot/selection input is included. | Medium/high: missing one signature dimension can reuse stale translations. | Lower provider cost and latency on repeat units. | Harder; wrong cache entries may persist in memory or future durable caches. | Requires disabled-adapter tests plus provider evidence proving output-affecting dimensions are complete. | Not approved for first adapter. |
| Cache bypass for glossary-injected enabled/test-path units | Most conservative: avoids stale reuse while prompt behavior is experimental. | Low for glossary-injected units because they are not reused from cache. | Higher provider cost and latency for enabled/test-path units. | Simple: disable the adapter and existing non-glossary cache path remains unchanged. | Tests must prove bypass is used only for glossary-injected enabled/test-path units and default runtime cache behavior is unchanged. | Approved. |
| Shadow-only defer | Safest if no prompt injection happens at all. | None for runtime because glossary metadata does not affect output. | No provider cost change. | Simple. | Useful for planning, but does not exercise prompt-policy behavior. | Still allowed where adapter remains disabled/shadow-only. |
| Hybrid: signatures plus conditional bypass | Possible future policy after evidence. | Depends on exact cache-key completeness and invalidation behavior. | Balanced cost/latency if correct. | More complex. | Needs a dedicated approved issue with provider evidence, disabled-adapter tests and cache-key review. | Future only. |

## Implementation Gates For Future #466-Style Adapter

Before any code uses this decision:

- the adapter must be disabled by default
- default runtime translation behavior must remain unchanged when disabled
- existing non-glossary cache behavior must remain unchanged
- glossary-injected enabled/test-path units must bypass cache get and put
- compact glossary/profile/snapshot/selection signatures may be attached only
  as metadata/planning diagnostics, not as a reuse key
- invalid, missing, low-confidence or over-budget glossary data must fall back
  to the existing translation path metadata
- tests must prove raw source text, prompts, provider responses, translated
  bodies, API keys and auth material are absent from shadow/policy payloads
- no live provider calls, DB/schema/state migration, storage/admin/retention
  change or provider-config change is allowed by this decision

## Rollback / Fallback

- Disable the default-off adapter/test hook.
- Continue existing non-glossary cache behavior unchanged.
- Treat glossary signatures as diagnostic metadata only.
- If glossary metadata is invalid, missing, low-confidence or over budget, fall
  back to the existing translation path metadata and do not cache a
  glossary-injected result.

## Unknown

- Provider behavior for a post-#461/#462 bounded retry is `Unknown`; #464 is
  blocked by the #463 local gate result unless the owner records a follow-up
  gate fix or explicit deferral.
- Whether glossary-aware cache keys are complete enough for safe reuse is
  `Unknown`.
- Long-term cost/latency impact of bypassing cache for glossary-injected units
  is `Unknown`.
- Release-version diagnostic/cache/privacy behavior remains `Unknown` until a
  future release-readiness decision.

## TBD

- Future glossary-aware cache-key design is `TBD` and requires a separate
  approved issue.
- Durable cache migration/invalidation behavior is `TBD`.
- Runtime prompt rollout remains `TBD`.
- Release-version glossary/profile diagnostic consent, retention, deletion,
  export, support and legal/privacy policy remains `TBD`.

## Non-Goals

- No runtime prompt integration.
- No cache code change or cache migration.
- No database/schema/state change.
- No scheduler/work-unit mutation.
- No storage/admin/retention change.
- No provider config change or live provider call.
- No release/privacy/legal/support claim.
