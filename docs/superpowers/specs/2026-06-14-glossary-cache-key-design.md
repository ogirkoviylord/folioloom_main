# Glossary-Aware Cache-Key Design

Status: no-code architecture review for GitHub issue #536 / #204BN.
Date: 2026-06-14.
Parent: #529 / #204BG.

Scope: future glossary-aware cache-key design only. No code implementation, no
cache reuse enablement, no cache migration/state mutation, no runtime prompt
rollout, no live provider calls, no provider config/key changes, no DB/schema/
state/scheduler/work-unit/storage/admin/retention change and no release/
privacy/legal/support claim.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high, because incomplete cache dimensions can reuse stale or
  non-glossary translations after glossary/profile/policy data changes.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` for current-state docs and `pr-review` for
  final docs diff review.
- Approval status: approved for #536 design-only work by the owner approval
  recorded on #529 and #536. Future cache reuse implementation, migration,
  runtime rollout or release claim requires separate owner approval.
- Allowed action: no-code cache-key design and metadata-only docs sync.
- Verification plan: docs review, redaction scan, `git diff --check` and
  repo-level `pr-review`. Code tests are not required because this issue
  changes no code.

## Verdict

SAFE for this no-code cache-key design.

REJECT FOR NOW for enabling glossary-aware cache reuse. Current runtime posture
still preserves #465: glossary-injected enabled/test-path units bypass cache
get and cache put.

NEEDS HUMAN APPROVAL before any future cache reuse, migration/invalidation,
runtime prompt rollout, provider/model dimension change, durable cache/state
change or release/privacy/legal/support claim.

## Current Cache Evidence

Confirmed:

- `MemoryTranslationCache` keys source language, target language, prompt tier,
  normalized source texts and per-block translation policy signatures.
- `translation_policy_signature()` already includes prompt, protection and
  adapter policy versions, source/target language, target-language policy,
  source-pair policy, Russian quality track signature, entity ledger signature,
  translation context signature, text type, prompt tier and output-contract
  signature.
- Optional `TranslationPolicySignatureContext` can add compact glossary,
  profile, translation snapshot, selection, selected rule id and prompt
  contract dimensions.
- Runtime glossary adapter decisions already expose `cache_get_allowed` and
  `cache_put_allowed`. READY glossary-injected test-path decisions set both to
  `False`.
- #465 is still the active cache policy: glossary-injected enabled/test-path
  units bypass cache; compact signatures are metadata only.
- #535 keeps normal/default and limited-beta runtime glossary rollout rejected
  for now.

Unknown:

- Whether provider/model identity must be a mandatory cache dimension for
  future glossary-aware reuse is `Unknown`.
- Long-run cost/latency impact of bypassing glossary-injected units is
  `Unknown`.
- Translation quality benefit of glossary-aware runtime usage remains
  `Unknown`.

TBD:

- Future cache reuse implementation and migration/invalidation policy.
- Durable cache shape, if any.
- Release-version diagnostic consent, retention, deletion, support and
  legal/privacy policy.

## Current Policy

Current behavior must remain unchanged:

- default non-glossary cache behavior is allowed as implemented today;
- disabled or fallback glossary adapter decisions may use the default runtime
  cache only when glossary/policy context does not affect the prompt/output;
- READY glossary-injected enabled/test-path units bypass cache get and put;
- compact signatures may be emitted for planning, diagnostics and future
  design, but must not enable reuse in this issue.

## Future Cache-Key Dimensions

If the owner later approves glossary-aware cache reuse, the key must include or
force bypass for every output-affecting dimension below.

| Dimension | Why it affects output | Future key / bypass rule |
| --- | --- | --- |
| Source language | Prompt wording and provider interpretation can change. | Already keyed; missing/invalid value blocks reuse. |
| Target language | Translation output changes directly. | Already keyed; normalized target must be included. |
| Translation mode / prompt tier | Mode changes style, detail and structure. | Already keyed through prompt tier and policy signature; future quality route must be explicit if added. |
| Normalized source texts | Cache must match exact unit content after approved normalization. | Already keyed; glossary expansion must not hide source changes. |
| Prompt policy version | Prompt instructions affect output. | Already in policy signature; version bump invalidates reuse. |
| Protection policy version | Marker/protection behavior affects output. | Already in policy signature; version bump invalidates reuse. |
| Adapter policy version | Adapter behavior affects prompt and output handling. | Already in policy signature; version bump invalidates reuse. |
| Output contract / provider output format | XML/JSON/plain contract can affect response shape and validation. | Existing output contract is keyed; future provider output format must be keyed or bypassed if independent of output contract. |
| Glossary snapshot signature | Available glossary entries affect injected context. | Must be keyed when glossary context can affect output; missing/Unknown forces bypass. |
| Book profile signature | Profile-specific rules can change term priority/style. | Must be keyed when profile affects selection or prompt; missing/Unknown forces bypass. |
| Translation contract snapshot signature | Captures run-level contract and policy input set. | Must be keyed for glossary-aware reuse; stale snapshot forces bypass. |
| Per-work-unit selection signature | Selected/dropped entries affect prompt context. | Must be keyed; missing/invalid selection forces bypass. |
| Work-unit selection signature | The exact selected unit metadata and budget state affect prompt context. | Must be keyed for reuse of a glossary-injected unit or bypassed. |
| Selected rule ids | Profile/rule decisions can affect constraints. | Already supported in signature context; missing when rules were applied forces bypass. |
| Terminology policy id/version/match mode | Target form compliance and prompt metadata can change. | Must be represented through compact policy signature or explicit dimension; missing/Unknown forces bypass. |
| Language-policy package id/version | Package variants/forbidden forms can change. | Must be keyed when package data contributed target metadata or prompt context. |
| Prompt-context formatter contract | Rendering, ordering, escaping and budget rules affect prompt content. | Must be keyed through prompt contract/formatter version; missing version forces bypass. |
| Prompt-context budget/degrade state | Dropped/omitted entries change output opportunity. | Must key fallback/degrade state or bypass; degraded output must not be reused as full glossary output. |
| Glossary adapter version/config | Enabled status, max entries and work-unit targeting affect prompt planning. | Must be keyed or bypassed; invalid config forces fallback/no reuse. |
| Runtime state class | Disabled, shadow-only, owner-only test path and normal runtime must not collide. | Must be explicit; test-path cache entries cannot be reused for normal runtime. |
| Provider/model/output behavior | Different providers/models may produce different wording. | `TBD`: either key provider/model or keep bypass until owner approves the stance. |
| Entity ledger/context memory signatures | Entity/context memory can affect names and consistency. | Already in policy signature; future glossary reuse must preserve this dimension. |
| Fallback reason/status | Fallback output and full glossary output are not equivalent. | Must be keyed or fallback must bypass. |
| Structural validation and safety contract version | Accepted output semantics can change. | Must be keyed if cache stores validated provider outputs across validator versions. |

Language neutrality rule: cache-key design must depend on policy ids, package
ids, signatures and match modes, not hardcoded `ru`, `uk` or any other
language-specific branch in cache core.

## Missing / Unknown Dimension Rules

Future implementation must fail conservative:

- `Unknown`, missing, invalid, unsupported, low-confidence or over-budget
  glossary/policy dimensions force bypass for glossary-injected units.
- If glossary context was omitted and the runtime truly used the existing
  non-glossary path, existing non-glossary cache behavior may apply.
- If any glossary/profile/policy dimension affected prompt selection,
  formatter output or provider instructions, reuse is unsafe unless every
  output-affecting dimension is keyed.
- If provider usage, model identity or provider output behavior is `Unknown`
  and the approved cache design requires that dimension, bypass.
- If release diagnostic/privacy policy is `TBD`, it does not itself change the
  translation output, but it blocks beta/default rollout claims and any durable
  diagnostic/cache migration claims.

## Stale-Cache Failure Modes

| Failure mode | Impact | Mitigation |
| --- | --- | --- |
| Non-glossary result reused for glossary-injected unit | Glossary appears enabled but output ignores it. | #465 bypass now; future key must distinguish injected vs non-injected runtime states. |
| Old glossary snapshot reused after entries change | Terms or variants become stale. | Key glossary snapshot/package signatures or bypass. |
| Old profile/rule reused after profile detection changes | Style or term priority can drift. | Key profile signature and selected rule ids. |
| Selection changes but cache key does not | Dropped/added entries are ignored. | Key per-work-unit selection signature. |
| Terminology policy version changes but key does not | Compliance/prompt expectations mismatch. | Key policy id/version/match mode. |
| Formatter/escaping/budget rules change but key does not | Provider prompt changes without cache invalidation. | Key formatter/prompt contract version. |
| Degraded/fallback output reused as full glossary output | Reduced-quality output is mistaken for full success. | Key fallback/degrade state or bypass fallback outputs. |
| Test-path cache reused in normal runtime | Owner-only experimental output leaks into default behavior. | Key runtime state and prohibit test-path reuse for normal runtime. |
| Provider/model change omitted | Different wording/style reused across provider behavior. | Decide provider/model stance in future issue; key or bypass until decided. |
| Durable cache migration keeps old entries | Long-lived stale outputs survive policy changes. | Separate owner-approved migration/invalidation plan before durable reuse. |

## Future Validation Plan

For a later approved implementation issue, focused tests should prove:

- default non-glossary cache behavior is unchanged;
- READY glossary-injected enabled/test-path units bypass cache get and put;
- disabled/fallback glossary decisions do not change default cache behavior
  when no glossary context affects output;
- each output-affecting signature dimension either changes the cache key or
  forces bypass;
- missing/invalid/Unknown glossary/profile/selection/policy dimensions never
  permit glossary-aware reuse;
- fallback/degraded glossary states do not reuse full glossary entries and full
  glossary states do not reuse fallback entries;
- terminology policy id/version/match mode and language-policy package version
  are represented without language-specific cache branches;
- provider/model stance is tested according to the future approved decision;
- metadata-only cache diagnostics contain no raw source text, prompt bodies,
  provider responses, translated text, API keys or auth material;
- any future durable cache migration/invalidation has explicit versioning and
  rollback/forward-fix tests.

## Approval Gates

Separate owner approval is required before:

- enabling glossary-aware cache reuse;
- changing cache get/put behavior for glossary-injected units;
- adding durable cache storage, migration or invalidation behavior;
- changing runtime prompt integration or rollout state;
- keying or changing provider/model/config behavior;
- changing DB/schema/state/scheduler/work-unit/storage/admin/retention/export/
  delete behavior;
- making release/privacy/legal/support claims.

## Recommended Next Steps

1. Keep #465 cache bypass for all glossary-injected enabled/test-path units.
2. Use this design in #537 decision prep as the cache stance: future reuse is a
   separately approved implementation path, not a current rollout blocker fix.
3. If the owner wants cache reuse later, create a new issue that implements only
   local cache-key tests first, with no runtime rollout and no durable cache
   migration.

## Non-Goals

- No cache code change.
- No cache reuse enablement.
- No migration or state mutation.
- No runtime prompt rollout.
- No live provider calls.
- No provider config/key change.
- No database/schema/state/scheduler/work-unit/storage/admin/retention changes.
- No new production dependencies.
- No release/privacy/legal/support claims.
