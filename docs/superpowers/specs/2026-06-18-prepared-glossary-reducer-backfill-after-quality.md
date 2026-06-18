# Prepared Glossary Reducer Backfill After Quality Drops

Date: 2026-06-18

Related issues: #688, #689, #690, #692

Historical context only: #661, #663, #664, #665, #666

## Routing Receipt

- Classification: risky task / glossary prep selection behavior change.
- Risk level: medium/high because prep selection changes can affect future
  prepared glossary packets and prompt usefulness.
- Supporting role / skill: Architect Agent / `architecture-review`.
- Supporting role / skill: Scribe Agent / `docs-sync`.
- Approval status: approved by the owner's goal-mode request for new issues
  #688-#692; old issues #661/#663-#666 remain historical and unchanged.
- Allowed action: narrowly adjust local/fake prepared prep selection after
  metadata-only evidence; no scanner rewrite or broad cap increase.
- Verification: focused candidate-quality/prep-service/audit tests, local audit
  CLI, compileall, targeted ruff, `git diff --check`, repo-level `pr-review`.

## Scope

#690 keeps the current prepared glossary cap direction and does not change
scanner v1 scoring/extraction. Instead, prepared prep now builds its local
candidate-quality input pool from reducer `retained_for_editor` plus
`diagnostic_only` candidates, then applies the candidate-quality gate with the
final `max_candidates` selection cap.

This means #689 quality drops can be backfilled by reducer diagnostic
candidates only when those candidates pass the same metadata-only quality gate.
The provider packet cap remains unchanged.

No live provider calls, Telegram operation, runtime rollout, cache reuse,
provider config/key changes, DB/schema/state/storage/admin/retention/export/
delete changes or release/privacy/legal/support claims are included.

## Metadata-Only Result After #690

Local audit command:

```bash
PYTHONPATH=src python3 tools/prepared_glossary_candidate_quality_audit.py
```

Observed metadata-only counts after #690:

- case count: 9
- prep input candidates considered by quality: 169
- prep selected candidates after quality/cap: 87
- prep dropped candidates: 50
- prep omitted by selection cap: 32
- package selected candidates: 87
- package dropped candidates: 0
- package omitted candidates: 0
- ready fake/local package cases: 9
- needs_review fake/local package cases: 0
- invalid fake/local package cases: 0
- target-metadata checked cases: 4
- expected target-backed durable candidates in checked cases: 12
- selected expected target-backed durable candidates: 12
- suspected missing target-backed durable candidates: 0
- ordinary artifact safety: passed
- unsafe metadata-key matches: 0
- secret-pattern matches: 0

## Interpretation

Confirmed facts:

- The two #688 suspected missing target-backed durable candidates are no longer
  missing in the local fake/provider-boundary audit.
- The fix did not require a scanner-v1 rewrite, scanner-v2 implementation or a
  broad prepared packet cap increase.
- The #689 low-value repeated-term quality rule still drops noisy candidates
  before fake/provider boundaries.
- Package status remains stable in the fake/local audit: 9 ready, 0
  needs_review, 0 invalid.
- Ordinary audit artifacts remain metadata-only and raw/secret checks pass.

Unknown:

- Real provider behavior remains `Unknown`.
- Real-book translation quality remains `Unknown`.
- Durable candidate coverage for cases without target metadata remains
  `Unknown`.
- Whether broader authorized fixtures expose new scanner-level misses remains
  `Unknown`.

TBD:

- #692 must record the architecture decision on scanner-v2 shadow evaluation
  after reviewing #688-#690 evidence.

## Recommendation

Do not increase the prepared glossary cap from this evidence alone. Do not
rewrite scanner v1 for this issue. Continue to #692 as a no-code architecture
decision; based on the #690 local evidence, scanner-v2 shadow work is not
warranted by this specific target-backed missing-candidate failure mode.
