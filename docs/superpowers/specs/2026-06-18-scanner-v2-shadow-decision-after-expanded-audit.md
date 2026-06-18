# Scanner v2 Shadow Decision After Expanded Candidate Audit

Date: 2026-06-18

Related issues: #688, #689, #690, #691, #692

Historical context only: #661, #663, #664, #665, #666

## Routing Receipt

- Classification: docs-only architecture review.
- Risk level: medium/high because scanner decisions can affect candidate ids,
  evidence refs, reducer signatures, prepared package matching and future
  runtime selection.
- Primary role / skill: Architect Agent / `architecture-review`.
- Supporting role / skill: Scribe Agent / `docs-sync`.
- Approval status: approved by the owner's goal-mode request for new issues
  #688-#692; old issues #661/#663-#666 remain historical and unchanged.
- Allowed action: no-code scanner-v2 decision only.
- Verification: docs diff review, `git diff --check`, repo-level `pr-review`.

## Verdict

**SAFE: do not create a scanner-v2 shadow implementation issue now.**

Scanner v1 remains the active deterministic extractor. The current safe posture
is scanner v1 plus:

- #663/#689 candidate-quality filtering before fake/provider prep boundaries;
- #664 package READY quality enforcement;
- #690 quality-approved backfill from reducer diagnostic candidates without
  increasing the prepared packet cap.

No scanner-v2 implementation, scanner-v1 rewrite or runtime switch is approved.

## Evidence Reviewed

Confirmed #688 evidence:

- expanded local fixture cases: 9
- prep input candidates: 105
- prep selected after quality: 97
- package-selected entries: 97
- package-level drops: 0
- ready fake/local package cases: 9
- target-backed durable candidates in checked cases: 12 expected, 10 selected
- suspected missing target-backed durable candidates: 2

Confirmed #690 attribution:

- The suspected missing target-backed candidates were present in scanner v1
  output.
- They were not scanner-level misses; they were lost at reducer/prep selection
  under editor-cap pressure.
- #689 reduced low-value repeated-term cap pressure.
- #690 then allowed quality-approved reducer diagnostic candidates to backfill
  after quality drops without increasing the prepared packet cap.

Confirmed #690 post-fix evidence:

- prep candidates considered by quality: 169
- prep selected after quality/cap: 87
- prep dropped: 50
- prep omitted by cap: 32
- package-selected entries: 87
- package-level drops: 0
- ready fake/local package cases: 9
- target-backed durable candidates in checked cases: 12 expected, 12 selected
- suspected missing target-backed durable candidates: 0
- ordinary artifact safety: passed, 0 unsafe metadata-key matches, 0
  secret-pattern matches.

Confirmed #691 outcome:

- Provider/package-boundary hardening is not indicated by the current fake/local
  evidence: package status remains 9 ready, 0 needs_review, 0 invalid.

## Unknown

- Real provider behavior remains `Unknown`.
- Real-book translation quality remains `Unknown`.
- Durable candidate coverage for cases without target metadata remains
  `Unknown`.
- Broader authorized fixture coverage may expose future scanner-level misses.
- Local metadata-only evidence does not prove semantic truth, morphology,
  literary quality or release readiness.

## TBD

- Future thresholds for "persistent scanner-level miss" remain `TBD` until a
  broader authorized fixture matrix exists.
- Any scanner-v2 implementation remains `TBD` and requires a separate approved
  issue.

## Future Scanner-v2 Trigger

Create a new scanner-v2 shadow implementation issue only if future
metadata-only evidence shows a scanner-level failure after #689/#690 gates, for
example:

- target-backed durable source terms are absent from scanner v1 output, not only
  omitted by reducer/prep selection;
- checked target-backed missing count persists after quality-approved backfill;
- provider/package evidence becomes weak because scanner evidence refs are not
  useful even after local gates;
- broader authorized fixture audits show repeated source-language heuristic
  growth that cannot safely stay inside candidate-quality or reducer/prep
  selection.

If created later, scanner v2 must be disabled-by-default, versioned,
shadow-only, metadata-only in ordinary artifacts, non-destructive to scanner v1
ids/signatures and isolated from live providers, runtime rollout and cache reuse
unless a later issue explicitly approves those gates.

## Non-Claims

- No scanner-v2 implementation is approved.
- No scanner v1 rewrite is approved.
- No live provider calls, Telegram operation, runtime rollout, cache reuse,
  provider config/key changes, DB/schema/state/storage/admin/retention/export/
  delete changes or release/privacy/legal/support claims are approved.
