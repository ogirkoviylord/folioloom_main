# Glossary Language-Policy Decision Packet

Status: metadata-only decision packet for GitHub issue #537 / #204BO.
Date: 2026-06-14.
Parent: #529 / #204BG.

Scope: evidence summary and next-step options after #530-#536 and #534. No
code implementation, no live provider calls, no runtime rollout, no cache
behavior changes, no provider config/key changes, no DB/schema/state/scheduler/
work-unit/storage/admin/retention changes and no release/privacy/legal/support
claim.

## Routing Receipt

- Classification: docs-only / risky decision preparation.
- Risk level: high, because the evidence can influence future runtime prompts,
  cache behavior, provider spend, diagnostics privacy and release claims.
- Primary role: Scribe Agent.
- Primary repo-level skill: `docs-sync`.
- Supporting skills: `architecture-review` for #535/#536 design evidence and
  `pr-review` for final docs diff review.
- Approval status: approved for #537 metadata-only decision prep by the owner
  approval recorded on #529 and #537. Final go/no-go remains owner decision.
- Allowed action: metadata-only decision packet and docs sync.
- Verification plan: docs review, redaction scan, `git diff --check` and
  repo-level `pr-review`. Code tests are not required because this issue
  changes no code.

## Child Issue Status

| Issue | PR | Status | Evidence |
| --- | --- | --- | --- |
| #530 #204BH acceptance matrix | #538 | Closed / merged | No-code language-policy package acceptance matrix. |
| #531 #204BI RU/UK package v1 | #540 | Closed / merged | Local RU/UK variant-list package fixture and tests. |
| #532 #204BJ contrast package v1 | #539 | Closed / merged | Local DE casefold contrast package fixture and tests. |
| #533 #204BK fake/dry preflight | #541 | Closed / merged | Package-aware fake/dry preflight passed for RU/UK/DE, 6 planned calls. |
| #534 #204BL live smoke | #542 | Closed / merged | 6 approved live calls completed, 8452 observed tokens, all structurally valid. |
| #535 #204BM rollout design | #543 | Closed / merged | No-code rollout state machine keeps normal/default and limited-beta rollout rejected for now. |
| #536 #204BN cache-key design | #544 | Closed / merged | No-code cache-key dimensions preserve #465 cache bypass and require Unknown/missing bypass. |
| #537 #204BO decision packet | TBD | This packet | Metadata-only summary and next owner options. |

## Confirmed Facts

- Glossary core remains language-neutral. Target-language behavior lives behind
  terminology policy/package metadata, not scattered core branches.
- RU/UK and DE contrast policy packages exist as local fixtures/tests. They are
  not a full morphology engine or broad language-quality proof.
- #533 fake/dry preflight selected paired glossary-on/off RU/UK/DE policy units
  and made no live provider calls.
- #534 ran only after the approved gates, used committed policy-package
  fixtures, stayed within 6 calls and the 60000-token cap, and recorded raw
  prompts/provider responses only inside the approved local owner-only
  diagnostics boundary.
- #534 structural validation passed for all six calls.
- #534 policy-aware compliance passed for RU/UK glossary-on, reported target
  form missing findings for RU/UK glossary-off, and passed for DE glossary-on
  and glossary-off.
- #535 keeps normal/default runtime glossary rollout and limited beta rollout
  rejected for now.
- #536 keeps #465 cache bypass active for glossary-injected enabled/test-path
  units and defines future cache-key dimensions only.

## Unknown

- Translation quality benefit remains `Unknown` until an approved owner-only
  quality review compares valid paired outputs.
- Broader real-book behavior remains `Unknown`; #534 covered selected package
  fixture units only.
- Long-run provider stability, latency and cost shape remain `Unknown` outside
  bounded smoke evidence.
- Whether provider/model identity must be a mandatory future cache dimension is
  `Unknown`.
- CI status for future PRs is `Unknown` unless inspected on those PRs.

## TBD

- Owner go/no-go for the next glossary path.
- Full RU/UK morphology beyond explicit variants and review flags.
- Future language-policy package priorities and fixture basis.
- Future glossary-aware cache reuse implementation and migration/invalidation
  policy.
- Release-version glossary/profile diagnostic consent, retention, deletion,
  support and legal/privacy policy.
- Any owner-only battle-test approval, limited beta approval or default rollout
  approval.

## Current Decision Posture

Verdict for now:

- Keep runtime glossary **shadow-only/default-off**.
- Do not enable normal/default prompt integration.
- Do not enable limited beta glossary rollout.
- Do not enable glossary-aware cache reuse.
- Do not make release/privacy/legal/support readiness or positive translation
  quality claims.

This is not a no-go for all glossary work. It means the local foundations and
bounded provider evidence are useful, but the next step still needs an explicit
owner decision.

## Owner Options

| Option | What it means | Pros | Blocks / approvals |
| --- | --- | --- | --- |
| Keep shadow-only | Stop runtime-adjacent work for now and keep package/policy foundations available. | Lowest risk; no new provider or user-data exposure. | No new quality evidence. |
| Owner-only quality review over existing outputs | Review only approved #534/#507 owner-only diagnostics and publish a metadata-only quality verdict. | Converts valid paired evidence into a clearer go/no-go signal. | Requires owner approval for any raw inspection boundary not already covered; no new provider calls. |
| Add more local package coverage | Add more synthetic/authorized language-policy package fixtures/tests. | Improves language coverage while staying local. | Needs new focused issues; no quality/provider proof by itself. |
| Run another bounded provider smoke | Add more provider-boundary evidence for approved package units or larger fixture set. | Tests provider behavior under controlled caps. | Requires fresh exact approval for inputs, targets, caps, model, diagnostics and raw boundary. |
| Design owner-only battle-test implementation | Implement a default-off real-book trial path with kill switch and cache bypass. | Moves toward controlled real-use feedback. | Requires separate issue, quality evidence, cache bypass tests, diagnostics policy and owner approval. |
| Split future cache-key implementation | Build local cache-key tests and maybe future reuse dimensions without runtime rollout. | Prepares reuse safely. | Requires separate approval; current #465 bypass remains active. |
| No-go runtime rollout for now | Explicitly pause runtime glossary rollout until broader evidence exists. | Avoids over-trusting early evidence. | Glossary remains local/shadow until reopened. |

Recommended next path:

1. Keep runtime glossary shadow-only/default-off.
2. Run an owner-only quality review over existing valid paired evidence if the
   owner wants a clearer quality signal.
3. If quality review is favorable, create a new owner-approved issue for a
   default-off owner-only battle-test implementation with cache bypass and kill
   switch.
4. Keep cache reuse as a later, separate design-to-implementation lane.

## Hard Boundaries

- No runtime rollout without a new approved issue.
- No normal/default prompt integration without owner approval.
- No glossary-aware cache reuse without a new approved implementation issue.
- No provider call without fresh exact approval.
- No DB/schema/state/scheduler/work-unit/storage/admin/retention/export/delete
  change without separate approval.
- No release/privacy/legal/support claim while release diagnostic policy is
  `TBD`.
- No raw source text, prompt bodies, translated text, provider responses, API
  keys or auth material in ordinary docs, issues, PRs, logs or support/release
  artifacts.

## Closeout Recommendation For #529

Close #529 after this packet is merged, because its requested child work is
complete. Open a new focused issue for whichever owner option is selected next.
