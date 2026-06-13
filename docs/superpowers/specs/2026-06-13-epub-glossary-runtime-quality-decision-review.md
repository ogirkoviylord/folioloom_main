# EPUB Glossary Runtime Quality Decision Review

## Routing Receipt

- Issue: #492 / #204AU.
- Classification: spike / risky task, review work.
- Risk level: high.
- Primary skill: translation-quality-review.
- Supporting skills: docs-sync and pr-review.
- Approval status: approved in issue #492 for metadata-only decision
  preparation after #491.
- Allowed action: metadata-only review/report only.
- Verification: metadata-only report, redaction scan, `git diff --check`, and
  repo-level pr-review.

## Verdict

FAIL for runtime glossary rollout readiness, limited-beta readiness,
owner-only battle-test candidacy, and comparative glossary-on/off quality
claims from the current EPUB evidence.

NEEDS REVIEW for the next local implementation path.

Final owner go/no-go decision: TBD.

## Review Scope

- Evidence source: #491 metadata-only bounded paired EPUB runtime smoke report.
- Raw output inspection: no.
- Source language: English.
- Target languages: Russian and Ukrainian.
- Document profile: book-manuscript / pipeline-regression.
- Format: EPUB.
- Depth: pipeline-regression metadata review.
- Quality target: owner decision preparation, not reader-ready or
  publication-ready quality.
- Assumption: #491 metadata report accurately summarizes the approved local
  owner-only diagnostics. Raw source text, prompt bodies, provider response
  bodies and translated bodies were not copied into this report.

## Findings

| Severity | Location | Problem | Why it matters | Likely cause | Fix type | Recommended action | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Critical | #491 paired EPUB live smoke, `ru` and `uk` | All four paired live calls failed validation. | Invalid outputs cannot support semantic quality review, glossary benefit claims, runtime rollout, or battle-test candidacy. | EPUB unit/output-completion pressure remains unresolved. | pipeline bug / format repair | Keep runtime glossary shadow-only and create a focused local issue for smaller EPUB runtime unit selection and output-budget reduction. | #491 records finish reason `length` plus issue codes `truncated_output` and `external_text` for glossary-on and glossary-off calls. |
| Critical | #491 paired EPUB live smoke, glossary-off baseline | The non-glossary baseline side also failed. | The evidence cannot show whether glossary context helps or hurts quality, because the baseline did not produce a valid comparable output. | Shared EPUB unit/output-completion pressure, not a glossary-only failure. | pipeline bug / evaluation design | Do not rerun live smoke until local/fake gates prove a smaller paired unit can fit the response contract. | #491 records the same validation issue codes for glossary-on and glossary-off calls. |
| Major | #491 glossary-on calls | Glossary-on calls omitted glossary prompt context under pressure policy and still failed. | This suggests the current failure is not solved merely by dropping glossary context; the EPUB unit itself is too large or poorly shaped for the current smoke contract. | Completion budget and EPUB block grouping pressure. | pipeline bug | Add local metadata gates for first smaller eligible/degraded EPUB unit, expected output size, and max block count before the next provider approval request. | #491 records pressure fallback `omit_glossary_prompt_context` for glossary-on and provider `length` failures. |
| Major | #491 fake preflight vs live smoke | Fake preflight validated but live provider output failed. | Local/fake rehearsal is useful for packaging and boundary checks, but does not prove live provider compliance or translation quality. | Provider completion behavior differs from deterministic fake output. | evaluation design | Keep fake preflight required, but add a stricter local size/readiness gate before live smoke. | #491 fake preflight validated both targets; live calls failed. |
| Note | #491 cache metadata | Cache behavior metadata matched the intended boundary. | This preserves the cache safety decision but is not quality or readiness evidence. | Expected disabled/test-path adapter behavior. | accept as-is | Keep first-adapter glossary-injected test units on cache bypass; do not enable glossary-aware cache reuse. | #491 records glossary-on cache bypass and glossary-off default cache metadata. |

## Overall Quality Notes

- Translation quality is Unknown because no #491 EPUB live output validated.
- Semantic fidelity, literary fluency, terminology consistency, name/entity
  consistency, and RU/UK morphology behavior are Unknown.
- The paired run is valid enough for decision preparation: it shows the current
  EPUB paired runtime smoke is not ready to support quality comparison or
  rollout discussion.
- The paired run is not valid enough for any positive quality claim.

## Format And Structure Notes

- The blocker is format/runtime-unit level evidence: both targets and both
  sides failed with provider `length` plus local output validation failures.
- #488/#489 pressure policies reduced or omitted glossary context for the
  glossary-on side, but the provider still did not produce a valid output.
- The next local iteration should optimize for smaller EPUB runtime units and
  completion budget first, before terminology/glossary quality is judged.

## Terminology And Name Consistency Notes

- Glossary benefit remains Unknown.
- Local code must not claim semantic facts such as gender, name identity,
  entity identity or literary correctness.
- RU/UK morphology remains TBD unless future evidence and tests support a
  specific implementation.

## Owner Decision Options

| Option | Status | Why | Recommendation |
| --- | --- | --- | --- |
| Keep shadow-only | Available now | Safest path; no new runtime, cache, storage, provider or release risk. | Recommended current state. |
| Iterate locally | Available after a new focused issue | Directly addresses the observed EPUB unit/output-completion pressure without live provider calls. | Recommended next action. |
| Rerun bounded smoke | Blocked for now | Current evidence would likely repeat the same failure until local smaller-unit gates exist. | Do only after local/fake gates pass and fresh exact owner approval is recorded. |
| Owner-only battle-test candidate | Blocked | No valid EPUB paired outputs and no quality delta evidence. | Reject for now. |
| No-go | Available as owner decision | Stops runtime glossary work while preserving local foundations for later. | Valid owner choice, but not required by the current evidence. |

## Recommended Next Step

Keep runtime glossary shadow-only and open a focused local implementation issue
for smaller EPUB runtime unit selection and output-budget reduction for the
disabled/test-only glossary path.

Acceptance for that follow-up should require:

- no live provider calls;
- no default runtime prompt rollout;
- unchanged default runtime behavior;
- no cache reuse for glossary-injected units;
- no durable cache/database/scheduler/work-unit/storage/admin/retention
  mutation;
- metadata-only ordinary artifacts;
- tests proving smaller/degraded EPUB units can be selected without raw source
  or prompt leakage.

After that local issue passes, request a fresh bounded paired provider approval
before any further live smoke.

## Files Inspected

- `docs/QUALITY_GATES.md`
- `docs/RISK_REGISTER.md`
- `docs/DECISIONS.md`
- `docs/ROADMAP.md`
- `docs/RELEASE_CHECKLIST.md`
- `docs/superpowers/specs/2026-06-13-bounded-paired-epub-glossary-runtime-smoke-report.md`
- `docs/superpowers/specs/2026-06-13-glossary-on-off-quality-review.md`
- `docs/superpowers/specs/2026-06-13-controlled-glossary-runtime-decision-prep.md`

## Tools Or Tests Run

- No code tests required; no code changed.
- `git diff --check`: passed.
- Added-line and report redaction scan: passed for high-confidence secret,
  prompt-envelope and raw provider/body markers.
- Repo-level pr-review: APPROVE, no blockers.

## Confirmed Facts

- #491 ran within the approved bounded provider boundary and produced a
  metadata-only report.
- #491 fake paired preflight validated both approved EPUB targets.
- #491 live smoke made four approved calls and stayed under the approved token
  cap.
- All four #491 live calls failed validation with provider `length` plus local
  `truncated_output` and `external_text` issue codes.
- Glossary-on calls used the expected cache-bypass metadata.
- Glossary-off calls used default runtime cache metadata.

## TBD / Unknown

- TBD: final owner go/no-go decision.
- TBD: runtime glossary rollout.
- TBD: future glossary-aware cache reuse.
- TBD: release-version glossary/profile diagnostic consent, retention,
  deletion, support and legal/privacy policy.
- TBD: RU/UK morphology strategy.
- Unknown: translation quality for #491 EPUB outputs.
- Unknown: glossary-on vs glossary-off quality delta.
- Unknown: whether smaller EPUB runtime units will validate live.

## Risks Or Follow-Up Tasks

- Risk: future agents may overinterpret fake preflight or metadata-only
  provider-boundary evidence as runtime readiness.
- Risk: copying raw source text, prompt bodies, provider response bodies or
  translated bodies into ordinary artifacts would violate the approved
  diagnostic boundary.
- Follow-up: create a separate local-only issue for smaller EPUB runtime unit
  selection and output-budget reduction before another live paired smoke.
- Follow-up: any new provider smoke needs fresh exact owner approval for inputs,
  targets, selection, call/token caps, model/provider, diagnostics directory and
  raw-capture boundary.
