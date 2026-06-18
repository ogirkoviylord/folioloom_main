# Post-#661 Prepared Glossary Candidate-Quality Audit

Date: 2026-06-18

Related issues: #688, #689, #690, #691, #692

Historical context only: #661, #663, #664, #665, #666

## Routing Receipt

- Classification: risky task / metadata-only glossary audit evidence.
- Risk level: medium/high because audit evidence can influence prepared
  glossary candidate policy, reducer scoring, provider-package adjudication and
  future scanner-v2 decisions.
- Primary role / skill: Implementer Agent / `implementation`.
- Supporting role / skill: Scribe Agent / `docs-sync`.
- Approval status: approved by the owner's goal-mode request for new issues
  #688-#692; old issues #661/#663-#666 remain historical and unchanged.
- Allowed action: local metadata-only audit implementation and evidence report.
- Verification: focused audit tests, local audit CLI, compileall, targeted ruff,
  `git diff --check`, repo-level `pr-review`.

## Scope

This is a fresh local-only metadata-only audit after the #663 prep-input quality
gate and #664 package READY quality gate. It uses committed/authorized local
fixtures only and fake local prepared-package output. It does not call live
providers, operate Telegram, change runtime rollout, change cache reuse, change
provider config, change DB/schema/storage/admin/retention behavior, or make
release/privacy/legal/support claims.

The old #661/#663-#666 issues were not edited, reopened or retitled.

## Inputs

- `test_samples/glossary_adversarial_terms.en.txt`, targets `ru` and `uk`
- `test_samples/sample_book.en.txt`, target `ru`
- `test_samples/sample_book.en.docx`, target `ru`
- `test_samples/sample_book.en.epub`, target `ru`
- `test_samples/russian_profile_regression.en-ru.txt`, target `ru`
- `test_samples/ukrainian_profile_regression.en-uk.txt`, target `uk`
- `test_samples/gutenberg_time_machine_noimages.en.epub`, targets `ru` and
  `uk`

Target-metadata comparison was available for the adversarial TXT fixture and
the Gutenberg control EPUB fixture. The comparison uses source-term digests and
reports only counts/status/reason codes, not source terms or target strings.

The generated local report command is:

```bash
PYTHONPATH=src python3 tools/prepared_glossary_candidate_quality_audit.py --output outputs/issue-688-candidate-quality-audit/metadata_report.json
```

The generated JSON report is owner-local/untracked evidence. This committed
note records only metadata.

## Metadata-Only Result

- schema: `glossary-candidate-quality-audit-v1`
- case count: 9
- prep input candidates: 105
- prep selected candidates after #663 quality gate: 97
- prep dropped/demoted candidates: 8
- package selected candidates after #664 quality gate: 97
- package dropped candidates: 0
- alias-pruned count: 0
- ready fake/local package cases: 9
- needs_review fake/local package cases: 0
- invalid fake/local package cases: 0
- provider-called fake/local cases: 9
- measured low-value candidate rate: 0.0762
- target-metadata checked cases: 4
- target-metadata not-configured cases: 5
- expected target-backed durable candidates in checked cases: 12
- selected expected target-backed durable candidates: 10
- suspected missing target-backed durable candidates: 2
- ordinary artifact safety: passed
- unsafe metadata-key matches: 0
- secret-pattern matches: 0
- observed reason-code families:
  - `candidate_quality_low_value_source`
  - `candidate_quality_pronoun_phrase`
  - `candidate_quality_function_word_phrase`
  - `target_metadata_not_configured`
  - `target_metadata_suspected_missing_durable_candidate`

The report is metadata-only and does not include raw source text, prompt bodies,
provider responses, translated text, API keys, auth material, raw target
strings or raw candidate strings.

## Interpretation

Confirmed facts:

- The #663 gate still drops low-value prepared-prep candidates on the expanded
  committed fixture matrix.
- The #664 package gate kept every fake/local package READY after local quality
  filtering: 9 ready, 0 needs_review, 0 invalid.
- The checked target-metadata fixtures found 10 of 12 expected target-backed
  durable candidates in the selected prep/package candidate set.
- The audit detected 2 suspected missing target-backed durable candidates
  without serializing raw source terms or target strings.
- The ordinary report safety check found 0 unsafe metadata-key matches and 0
  secret-pattern matches.

Unknown:

- Real provider behavior after these gates is `Unknown`.
- Real-book translation quality after these gates is `Unknown`.
- Semantic or literary glossary quality is `Unknown`.
- Durable candidate coverage for the 5 cases without target metadata is
  `Unknown`.
- Scanner-vs-reducer attribution for the 2 suspected missing candidates is
  `Unknown`.

TBD:

- Whether reducer scoring should change under #690.
- Whether scanner-v2 shadow evaluation is warranted under #692 after #690.

## Recommendation

Primary recommendation: **run #690 reducer attribution before deciding on
scanner-v2 shadow work.**

This audit does not indicate a #689 candidate-quality policy change now: the
low-value candidates observed in the matrix were dropped locally, and package
quality did not drop additional entries.

This audit does not indicate #691 provider/package-boundary hardening now:
fake/local package status was 9 ready, 0 needs_review and 0 invalid.

The 2 suspected missing target-backed durable candidates are enough evidence to
inspect reducer decisions and caps in #690. If #690 shows the candidates never
exist before reducer selection, then #692 should consider a new shadow-only
scanner-v2 issue. If #690 attributes the gap to reducer selection, scanner-v2
should remain deferred.

## Non-Claims

- This is not live provider evidence.
- This is not Telegram operation evidence.
- This is not release, beta, privacy, legal or support readiness evidence.
- This does not approve runtime rollout, cache reuse, provider config/key
  changes, DB/schema/state/storage/admin/retention/export/delete changes, or
  scanner-v2 implementation.
