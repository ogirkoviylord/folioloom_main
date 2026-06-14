# Glossary Runtime Rollout Design

Status: no-code architecture review for GitHub issue #535 / #204BM.
Date: 2026-06-14.
Parent: #529 / #204BG.

Scope: rollout design only for future glossary runtime usage after
language-policy packages and provider-boundary evidence. No code
implementation, no live provider calls, no runtime rollout, no normal/default
prompt integration, no cache reuse behavior change, no provider config/key
change, no DB/schema/state/scheduler/work-unit/storage/admin/retention change
and no release/privacy/legal/support claim.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high, because runtime glossary usage can affect translation
  output, prompt safety, provider cost, cache correctness, diagnostics privacy
  and future release claims.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` for current-state docs and `pr-review` for
  final docs diff review.
- Approval status: approved for #535 design-only work by the owner approval
  recorded on #529. Future rollout, provider calls, cache reuse, storage/admin/
  retention behavior and release/privacy/legal/support claims require separate
  owner approval.
- Allowed action: no-code rollout design and metadata-only docs sync.
- Verification plan: docs review, redaction scan, `git diff --check` and
  repo-level `pr-review`. Code tests are not required because this issue
  changes no code.

## Verdict

SAFE for this no-code rollout design.

REJECT FOR NOW for normal/default runtime glossary rollout and limited beta
rollout. Current evidence proves local contracts and bounded provider behavior
for selected units, but translation quality remains `Unknown`, release-version
diagnostic policy remains `TBD`, and cache reuse remains unapproved.

NEEDS HUMAN APPROVAL before any owner-only battle-test implementation, limited
beta candidate, default prompt integration, cache reuse, live provider rerun,
diagnostic retention/export/delete behavior, provider config change or release
claim.

NEEDS SPLIT for future implementation. Runtime rollout, quality review,
provider evidence expansion, cache-key implementation and release diagnostic
policy must remain separate issues and PRs.

## Evidence Reviewed

| Evidence | Current outcome |
| --- | --- |
| #465 cache policy | Glossary-injected enabled/test-path units bypass cache; compact signatures remain metadata only. |
| #466 prompt-policy adapter | Disabled-by-default adapter decision keeps normal prompts unchanged and falls back for unready glossary metadata. |
| #474 runtime hook | Default-off hook can attach compact glossary adapter decisions for explicitly enabled test paths. |
| #475 prompt formatter | Local bounded formatter provides deterministic ordering, escaping and budget omissions. |
| #476 fake runtime rehearsal | Disabled/test-only path proves hook, formatter, cache bypass and fallback with fake/local provider stubs. |
| #477 runtime provider smoke | TXT calls validated, but approved EPUB calls failed with provider `length` and local validation failures. |
| #487-#490 EPUB pressure/fallback/rehearsal | Local-only pressure profiling, degrade policy, budget tuning and fake paired rehearsal reduced EPUB risk but made no quality claim. |
| #491/#492 paired EPUB evidence/review | Live EPUB paired smoke failed validation; quality/rollout verdict was `FAIL` for that evidence set. |
| #501 useful gate | Owner-only test path injects bounded glossary context only for READY units where source term/alias is present and target metadata exists. |
| #503 pressure-safe selector | Local EPUB selector chooses only glossary-useful, pressure-safe units or emits metadata-only skip/fallback reasons. |
| #505 target metadata overlay | Local approved target-metadata fixture path rejects raw/prompt/provider/key material and preserves fallback. |
| #507 control EPUB smoke | Bounded control EPUB paired smoke validated structurally for the selected unit, but translation quality remains `Unknown`. |
| #517-#522 terminology policy foundation | Glossary core remains language-neutral; policy registry, RU/UK variants, policy-aware compliance and prompt metadata are local/test-path only. |
| #530 acceptance matrix | Real language-policy packages require evidence levels, raw-boundary rules and core-neutrality proof. |
| #531/#532 packages | RU/UK variant-list and DE contrast casefold packages exist as local fixtures/tests. |
| #533 fake/dry preflight | Package-aware RU/UK/DE paired preflight passed and selected #534 units. |
| #534 live provider evidence | Six approved live calls completed; all structurally validated; RU/UK glossary-on compliance passed; RU/UK glossary-off had target-form-missing findings; DE on/off passed. |

Confirmed: normal/default runtime behavior remains unchanged, and current
glossary runtime work is still default-off, owner-only or test-path bounded.

Unknown: translation quality benefit, longer-book behavior, broader language
coverage, long-run cost/latency and provider stability outside the bounded
fixtures.

TBD: owner go/no-go, release-version diagnostic consent/retention/delete/
support/legal policy, full RU/UK morphology, future language packages and any
cache reuse implementation.

## Rollout State Machine

| State | Meaning | Allowed now | Entry gates | Exit / promotion gates | Hard stop / fallback |
| --- | --- | --- | --- | --- | --- |
| `off` | No glossary runtime planning or prompt injection. Existing translation path only. | Yes, default safe state. | Default runtime configuration and no explicit owner-only test path. | Owner approves shadow/local issue with focused tests. | Stay here when evidence is missing, policy data invalid, diagnostics boundary unavailable or owner approval absent. |
| `shadow_only` | Compute compact metadata or rehearsal plans without changing provider prompts or user-visible output. | Yes for approved local/test issues only. | Clear issue, local fixtures, metadata-only outputs, default behavior unchanged, no live provider calls. | Local/fake structural, budget, fallback, redaction and cache-bypass tests pass. | Drop glossary metadata and use existing translation path when data is invalid/missing/over budget. |
| `owner_only_local_smoke` | Explicit local/fake or bounded owner-only test-path rehearsal, still not user-visible. | Yes only under issue-specific approval. | Shadow gates pass; approved inputs/rights; no ordinary raw artifacts; diagnostics boundary defined. | Fake/dry preflight passes; selected units are glossary-useful, pressure-safe and have target metadata. | Metadata-only skip/fallback if unit is unsafe, over budget or not glossary-useful. |
| `owner_only_provider_smoke` | Exact owner-approved bounded live calls for selected units. | Only with fresh exact approval. | Local/fake preflight passes; max calls/tokens/model/diagnostics/raw boundary approved; key/config handling approved. | Structural validation passes; policy compliance summaries complete; observed usage stays within caps; raw diagnostics stay owner-only. | Stop on missing approval, token cap breach, provider failure, validation failure or diagnostics boundary violation. |
| `owner_only_quality_review` | Owner-only inspection or review of approved bounded outputs. | Not automatic; separate approval or issue. | Valid paired outputs exist; raw inspection stays inside owner-only diagnostics; ordinary report is metadata-only. | Review records quality benefit/risk, language-specific findings and go/no-go options. | No positive quality claim when review is absent, inconclusive or raw boundary cannot be maintained. |
| `owner_only_battle_test_candidate` | Default-off real-book trial candidate controlled by owner, not beta/default. | Not approved now. | Provider smoke and quality review support the path; fallback/kill switch exists; cache bypass preserved; diagnostics policy for trial approved. | Multiple approved inputs/targets pass structural, compliance, quality and cost gates; owner accepts residual risks. | Disable glossary path and fall back to existing non-glossary translation on any gate failure. |
| `limited_beta_candidate` | Allowlisted beta users can hit glossary-influenced runtime path. | Rejected for now. | Battle-test evidence passes; Gate B-relevant release checks addressed or owner-deferred; privacy/legal/support policy approved. | Owner signs explicit beta rollout decision. | No beta rollout while release diagnostic policy, quality evidence, cache policy or Gate B blockers are unresolved. |
| `normal_default_candidate` | Glossary runtime behavior becomes default for normal translation. | Rejected for now. | Limited beta evidence, cache strategy, release policy, support/legal/privacy readiness and rollback evidence all approved. | Owner signs release/default decision after release-readiness review. | Any missing dimension, Unknown quality or unapproved policy keeps runtime in off/shadow/owner-only states. |
| `no_go` | Explicit decision to stop or pause runtime glossary rollout. | Always available. | Owner decision, or repeated blocker evidence. | New evidence and new approved issue reopen the path. | Keep local language-policy/package foundations for future use without runtime rollout. |

## Entry Gates By Evidence Type

### Structural Validation

- Provider output must pass local structural validation before any quality or
  compliance signal is interpreted as useful.
- Fake/dry output remains rehearsal evidence only. It cannot prove live
  provider behavior.
- Live evidence is scoped to approved inputs, targets, model and caps only.

### Policy Compliance

- Compliance summaries must remain separate from structural validation.
- Policy-aware compliance can count configured canonical/variant/forbidden
  forms and reason codes.
- Local code must not claim semantic truth, name identity, gender correctness,
  full morphology or literary quality.
- Missing target metadata, absent source terms or unsupported policies must
  produce metadata-only skip/fallback/review outcomes, not pass claims.

### Quality Review

- Translation quality remains `Unknown` until approved owner-only review
  compares valid paired outputs.
- A positive quality claim requires at least:
  - same-unit glossary-on/off valid outputs;
  - metadata-only review summary;
  - language-specific findings separated from core correctness;
  - explicit owner decision on whether evidence is enough for the next state.
- RU/UK full morphology remains `TBD`; configured variants can support local
  compliance, but not full morphology proof.

### Provider Stability And Cost

- Live calls require fresh exact owner approval for inputs, targets, selection,
  max calls, max tokens, model/provider, diagnostics, raw capture and stop
  conditions.
- Observed usage must remain within approved caps or block promotion.
- Provider `length`, validation failures, timeouts, missing usage or unstable
  latency must block rollout promotion until a follow-up issue resolves them.

### Privacy And Diagnostics

- Ordinary logs, docs, GitHub issues, PR descriptions, support artifacts,
  release artifacts and user/admin surfaces must stay metadata-only/redacted.
- Raw source excerpts, prompt bodies, provider responses and translated text
  may exist only inside the issue-approved local owner-only diagnostics
  boundary.
- API keys, provider auth material and real `.env*` content are never approved
  in diagnostics.
- Release-version consent, retention, deletion, export, support and
  legal/privacy policy remains `TBD` and blocks beta/default rollout.

## Cache And Fallback Policy

Current cache stance from #465 remains active:

- glossary-injected enabled/test-path units bypass cache get and cache put;
- existing non-glossary cache behavior remains unchanged;
- compact glossary/profile/snapshot/selection and policy signatures may be
  emitted only as metadata for planning, diagnostics and future cache-key
  design;
- missing, invalid or `Unknown` cache dimensions force bypass or fallback, not
  reuse.

Runtime fallback order for future implementations:

1. If the feature is not explicitly enabled for an owner-only/test path, use
   the existing non-glossary translation path.
2. If glossary data is invalid, missing, unsupported, over budget or not useful
   for the unit, omit glossary prompt context and use existing translation path
   metadata.
3. If provider output fails structural validation, treat the call as failed
   evidence; do not score quality or compliance as success.
4. If diagnostics boundary is unavailable, omit raw diagnostics and keep only
   compact metadata or stop the diagnostic run.
5. If owner disables the glossary path, do not inject glossary context and do
   not reuse glossary-injected cache entries.

## Kill Switch Requirements For Future Implementation

This design does not implement a kill switch, but any owner-only battle-test
implementation must define one before code is approved:

- default-off switch at the runtime adapter boundary;
- explicit owner-only/test-path enablement, not normal/default enablement;
- fail-closed behavior for missing approval, missing policy package, invalid
  target metadata, over-budget context or diagnostics boundary errors;
- immediate fallback to existing non-glossary translation path;
- metadata-only reason code such as `glossary_runtime_disabled`,
  `glossary_context_omitted`, `policy_data_invalid`, `target_metadata_missing`
  or `cache_bypass_required`.

## Approval Points

Separate owner approval is required for:

- any code implementation beyond design docs;
- any live provider call or provider rerun;
- any owner-only raw output/quality inspection beyond an already approved
  diagnostics directory;
- any real-book battle-test path;
- any beta, public or default rollout;
- any glossary-aware cache reuse or cache migration;
- any DB/schema/state/scheduler/work-unit/storage/admin/retention/export/delete
  behavior;
- any provider config/key change;
- any release/privacy/legal/support claim.

## Recommended Next Steps

1. Complete #536 cache-key design while preserving #465 bypass.
2. Complete #537 metadata-only decision packet using #534, #535 and #536.
3. If the owner wants more evidence, create a separate owner-approved
   quality-review issue over existing #534/#507 outputs or a fresh bounded
   provider smoke for a larger package set.
4. Only after quality review and cache design are accepted, consider a new
   owner-only battle-test implementation issue with a default-off kill switch,
   cache bypass, redaction tests and no beta/default rollout.

## Non-Goals

- No runtime rollout.
- No normal/default prompt integration.
- No glossary-aware cache reuse.
- No provider config/key changes.
- No live provider calls.
- No database/schema/state/scheduler/work-unit/storage/admin/retention changes.
- No new production dependencies.
- No release/privacy/legal/support claims.
- No raw source text, prompt bodies, provider responses, translated text, API
  keys or auth material in ordinary artifacts.
