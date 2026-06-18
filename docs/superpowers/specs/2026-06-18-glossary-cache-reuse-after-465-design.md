# Glossary Cache Reuse After #465 Design

Status: design-only architecture review for #686.
Date: 2026-06-18.
Verdict: SAFE as docs-only design; REJECT FOR NOW for enabling cache reuse.

This is an addendum to
`docs/superpowers/specs/2026-06-14-glossary-cache-key-design.md`, not a
replacement. It keeps #465 active: glossary-injected enabled/test-path units
bypass cache get and cache put until a separate owner-approved implementation
issue changes that behavior.

## Confirmed

- `docs/DECISIONS.md` says glossary-injected enabled/test paths bypass existing
  translation cache unless a future approved cache-key issue changes this.
- `MemoryTranslationCache` keys source language, target language, prompt tier,
  normalized source text and translation policy signatures.
- `MemoryTranslationCache` can include compact
  `TranslationPolicySignatureContext` in the key.
- `TranslationPolicySignatureContext` already supports glossary, profile,
  translation snapshot, selection, selected-rule and prompt-contract
  dimensions.
- READY glossary adapter decisions currently set `cache_get_allowed=false`,
  `cache_put_allowed=false` and `cache_behavior=bypass_glossary_injected_cache`.
- Existing tests cover normal cache signature changes and current glossary
  cache bypass behavior.

## Unknown

- Whether provider/model identity must be a mandatory cache dimension is
  Unknown.
- Whether future durable cache storage will exist is Unknown.
- Whether glossary-aware reuse improves cost/latency enough to justify risk is
  Unknown.
- Translation quality benefit remains Unknown until separately approved
  evidence exists.

## TBD

- TBD: owner approval for any cache reuse implementation.
- TBD: provider/model cache-key stance.
- TBD: durable cache migration/invalidation policy.
- TBD: release-version diagnostic/cache retention and privacy policy.

## Current Policy

The default remains unchanged:

- non-glossary cache behavior stays as implemented today;
- disabled/fallback glossary decisions may use the default runtime cache only
  when glossary context did not affect prompt/output;
- READY glossary-injected enabled/test-path units bypass cache get and put;
- compact signatures are diagnostics and future design inputs only.

## Required Future Key Dimensions

A future cache reuse implementation must either key or bypass on every
output-affecting dimension below:

| Dimension | Rule |
| --- | --- |
| Source/target language | Already keyed; missing/invalid blocks reuse. |
| Prompt tier / translation mode | Must distinguish book/document/default output contracts. |
| Normalized source text | Already keyed; glossary data must not hide source changes. |
| Translation policy signature | Prompt/protection/adapter/output contract changes must invalidate reuse. |
| Glossary snapshot signature | Required when glossary entries can affect prompt/context. |
| Prepared package signature | Required when prepared package supplied target metadata. |
| Prepared package READY status | Non-READY, needs-review, target mismatch or invalid package forces bypass. |
| Book/profile signature | Required when profile detection affects selection or prompt rules. |
| Translation contract snapshot signature | Required for glossary-aware reuse. |
| Aggregate and work-unit selection signatures | Required; selection changes alter prompt context. |
| Selected rule ids | Required when profile/policy rules affect output. |
| Terminology policy id/version/match mode | Required when target variants/forbidden forms affect prompt context. |
| Language-policy package id/version | Required when package data contributed target metadata. |
| Prompt-context formatter contract | Required for rendering/ordering/escaping/budget changes. |
| Prompt-context omission/degrade state | Must be keyed or force bypass; degraded context is not full context. |
| Runtime adapter version/config/state | Disabled, shadow, owner-test and normal runtime states must not collide. |
| Cache policy behavior | Bypass/default/future glossary-aware behavior must not share entries. |
| Provider/model/output behavior | TBD: key provider/model or keep bypass until owner decides. |
| Entity ledger/context memory signatures | Must remain covered through translation policy signatures. |
| Validation/safety contract version | Must be keyed if cached outputs survive validator changes. |

Language neutrality rule: cache core must depend on signatures, policy ids and
package versions, not hardcoded `ru`, `uk` or other target-language branches.

## Missing / Unknown Rules

- Any missing, `Unknown`, invalid, low-confidence, over-budget or unsupported
  output-affecting dimension forces bypass for glossary-injected units.
- If glossary context was not rendered and the runtime truly used the existing
  non-glossary prompt path, existing non-glossary cache behavior may apply.
- If prepared package metadata is READY but runtime injection is
  `not_effective`, do not store or reuse it as a glossary-effective result.
- If provider/model stance is still TBD, glossary-aware reuse remains disabled.
- If cache diagnostics would need raw text, prompt body, provider response,
  translated text or key material, the diagnostic design is rejected.

## Stale-Cache Risks

| Risk | Why it matters | Required mitigation |
| --- | --- | --- |
| Non-glossary output reused for glossary prompt | Glossary appears active but output ignores it. | Keep #465 bypass until exact-key reuse is approved. |
| Old prepared package reused after target metadata changes | Target forms or forbidden variants can become stale. | Key package signature and policy package version. |
| Selection changes without key change | Added/dropped entries are invisible. | Key aggregate and work-unit selection signatures. |
| Formatter or budget changes without key change | Prompt context changes but cache hit masks it. | Key prompt-context contract and omission/degrade state. |
| Fallback result reused as full glossary result | Reduced behavior looks successful. | Key status/fallback/degrade state or bypass fallback results. |
| Test-path entry reused in normal runtime | Owner/test output can leak into default behavior. | Key runtime state and prohibit test-path reuse for normal runtime. |
| Durable cache keeps old entries after policy change | Stale outputs survive process restart. | Separate migration/invalidation issue before durable reuse. |

## Future Implementation Gates

Before any implementation changes cache behavior:

- owner approval must identify whether the first implementation is
  metadata-only key computation or actual reuse;
- a default-off flag or equivalent guard must preserve #465 bypass by default;
- focused tests must prove non-glossary cache behavior is unchanged;
- focused tests must prove READY glossary-injected units only reuse cache under
  approved exact-key conditions;
- missing/Unknown/invalid dimensions must force bypass;
- metadata must remain redacted and compact;
- durable cache/state/schema/migration work must be separate.

## Future Test Plan

- `tests/test_translation_cache.py`: every required signature dimension changes
  the key or forces bypass.
- `tests/test_translation_policy.py`: READY glossary adapter decisions keep
  current bypass by default.
- `tests/test_translation_runner.py`: glossary-injected units do not call cache
  get/put until the default-off reuse guard is explicitly enabled in tests.
- `tests/test_translation_runner.py`: disabled/fallback decisions preserve
  default non-glossary cache behavior when no glossary context affects output.
- `tests/test_bot_translation_service.py`: prepared package READY +
  runtime-injected and runtime-not-effective states do not collide.
- Redaction checks: cache diagnostics contain no raw source text, prompt bodies,
  provider bodies, translations, API keys or auth material.

## Follow-Up Task Drafts

1. Metadata-only cache-key readiness helper.
   - No cache get/put behavior change.
   - Computes whether all required dimensions are present.
   - Emits `cache_reuse_readiness=ready|bypass_required|Unknown`.

2. Default-off local cache reuse experiment.
   - Requires owner approval.
   - In-memory only; no durable cache migration.
   - Tests exact-key reuse and every missing-dimension bypass path.

3. Durable cache/migration design.
   - Separate architecture review only if owner wants persistent glossary-aware
     reuse.
   - Includes invalidation, versioning, rollback and retention policy.

No GitHub follow-up issues are opened by this design PR because cache reuse
approval remains TBD.

## Architecture Review Output

- Verdict: SAFE for docs-only design; REJECT FOR NOW for enabling reuse.
- Primary risk: stale cache hits can hide glossary/profile/policy changes.
- Required approvals: cache behavior change, durable cache/state/migration,
  runtime prompt rollout, provider/model stance and release/privacy claims.
- Recommended shape: first implement metadata-only readiness checks, then only
  consider default-off in-memory reuse after owner approval.
