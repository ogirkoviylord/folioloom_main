# Prepared Glossary Candidate-Quality Tuning

Date: 2026-06-18

Related issues: #688, #689, #690, #692

Historical context only: #661, #663, #664, #665, #666

## Routing Receipt

- Classification: risky task / local glossary quality-gate behavior change.
- Risk level: medium/high because candidate-quality rules can change prepared
  glossary packets and future runtime prompt usefulness.
- Primary role / skill: Implementer Agent / `implementation`.
- Supporting role / skill: Scribe Agent / `docs-sync`.
- Approval status: approved by the owner's goal-mode request for new issues
  #688-#692; old issues #661/#663-#666 remain historical and unchanged.
- Allowed action: narrowly tune local/default-safe candidate-quality filtering.
- Verification: focused candidate-quality/prepared-package/prep-service/audit
  tests, local audit CLI, compileall, targeted ruff, `git diff --check`,
  repo-level `pr-review`.

## Scope

Issue #689 adds a narrow source-side quality rule for low-value two-token
repeated-term phrase shapes that were consuming the prepared prep candidate cap
in the post-#688/#690 attribution. The rule emits
`candidate_quality_low_value_repeated_term_phrase` and keeps ordinary metadata
raw-free.

This does not rewrite scanner v1, implement scanner v2, change reducer scoring,
make live provider calls, operate Telegram, change runtime rollout, change cache
reuse, change provider config/keys, change DB/schema/state/storage/admin/
retention/export/delete behavior, or make release/privacy/legal/support claims.

## Metadata-Only Result After #689

Local audit command:

```bash
PYTHONPATH=src python3 tools/prepared_glossary_candidate_quality_audit.py
```

Observed metadata-only counts after #689:

- case count: 9
- prep input candidates: 105
- prep selected candidates after quality: 71
- prep dropped/demoted candidates: 34
- package selected candidates: 71
- package dropped candidates: 0
- alias-pruned count: 0
- ready fake/local package cases: 9
- needs_review fake/local package cases: 0
- invalid fake/local package cases: 0
- target-metadata checked cases: 4
- expected target-backed durable candidates in checked cases: 12
- selected expected target-backed durable candidates: 10
- suspected missing target-backed durable candidates: 2
- ordinary artifact safety: passed
- unsafe metadata-key matches: 0
- secret-pattern matches: 0
- observed reason-code families include
  `candidate_quality_low_value_repeated_term_phrase`.

## Interpretation

Confirmed facts:

- #689 removes a larger class of low-value repeated-term phrase shapes from the
  prepared prep packet before fake/provider boundaries.
- Existing package READY quality remains stable in the fake/local audit: 9
  ready, 0 needs_review, 0 invalid.
- Focused tests prove that representative durable source terms still pass the
  candidate-quality gate when evidence supports them.
- The report remains metadata-only and raw/secret safety checks pass.

Unknown:

- Real provider behavior is `Unknown`.
- Real-book translation quality is `Unknown`.
- Durable candidate coverage for cases without target metadata is `Unknown`.

TBD:

- #690 must still decide whether prep selection should backfill after #689
  quality drops or otherwise adjust reducer/prep selection.
- #692 must wait until #690 determines whether scanner-v2 shadow evaluation is
  still warranted.

## Recommendation

#689 is necessary but not sufficient for the two suspected missing target-backed
durable candidates from #688. The quality gate now drops more low-value cap
pressure, but it runs after reducer editor-cap selection and does not backfill
from diagnostic/reducer candidates by itself.

Next safe step: continue #690 with the #689 policy in place, and prefer a
focused prep/reducer selection fix over a broad cap increase if metadata-only
tests prove it restores target-backed durable candidates without admitting
low-value noise.
