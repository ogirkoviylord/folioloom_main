# Prepared Glossary Candidate-Quality Audit

Date: 2026-06-17

Related issues: #661, #663, #664, #665, #666

## Scope

This is a local-only metadata-only audit after the #663 prep-input quality gate
and #664 package READY quality gate. It uses committed fixtures only and fake
local prepared-package output. It does not call live providers, operate
Telegram, change runtime rollout, change cache reuse, change provider config,
change DB/schema/storage/admin/retention behavior, or make release/privacy/legal
or support claims.

## Inputs

- `test_samples/glossary_adversarial_terms.en.txt`, target `ru`
- `test_samples/sample_book.en.txt`, target `ru`
- `test_samples/gutenberg_time_machine_noimages.en.epub`, target `ru`

The generated local report is
`outputs/issue-665-candidate-quality-audit/metadata_report.json`; that file is
owner-local/untracked evidence. This committed note records only metadata.

## Metadata-Only Result

- schema: `glossary-candidate-quality-audit-v1`
- case count: 3
- prep input candidates: 20
- prep selected candidates after #663 quality gate: 18
- prep dropped candidates: 2
- package selected candidates after #664 quality gate: 18
- package dropped candidates: 0
- ready fake/local cases: 3
- provider-called fake/local cases: 3
- measured low-value candidate rate: 0.1
- observed reason-code families:
  - `candidate_quality_low_value_source`
  - `candidate_quality_function_word_phrase`

The report is metadata-only and does not include raw source text, prompt bodies,
provider responses, translated text, API keys, auth material, or raw candidate
strings. A local redaction spot-check against known raw/secret needles found no
matches.

## Interpretation

Confirmed facts:

- The #663 gate dropped low-value prepared-prep candidates on the audited
  committed fixtures.
- The #664 gate preserved package READY only for the remaining quality-selected
  fake/local entries in this audit.
- The audit report can be regenerated with
  `PYTHONPATH=src python3 tools/prepared_glossary_candidate_quality_audit.py`.

Unknown:

- Real provider behavior after these gates is `Unknown`.
- Real-book translation quality after these gates is `Unknown`.
- Whether scanner v1 plus quality gates is sufficient for broader book coverage
  is still `Unknown`.

TBD:

- #666 must decide whether to keep scanner v1 plus gates for now or create a
  future scanner-v2 shadow evaluation issue.
