# Glossary Effectiveness Smoke Report

Related issues: #671, #672, #673, #674, #675

Date: 2026-06-17

## Scope

This is a metadata-only report for the owner-approved #675 bounded glossary
effectiveness smoke. The run used the committed Project Gutenberg control EPUB
fixture:

- input: `test_samples/gutenberg_time_machine_noimages.en.epub`
- target: `ru`
- glossary prep/provider evidence model: `deepseek-v4-pro`
- runtime translation provider/model: unchanged configured runtime provider/model
- diagnostics root:
  `outputs/issue-675-glossary-effectiveness-smoke/20260617T170414Z/`

Raw fixture excerpts, prompts and provider responses are confined to the
owner-only untracked diagnostics directory above. This document intentionally
contains only metadata, counts, statuses and reason codes.

## Result

Verdict: `pass` for the bounded provider-boundary smoke.

Confirmed metadata:

- fake/dry preflight selected a glossary-useful pressure-safe EPUB unit.
- live run completed within the approved cap:
  - live provider calls: 2
  - provider-reported tokens total: 23164
  - max approved live calls: 4
  - max approved provider-reported tokens total: 60000
- prepared package validation status: `ready`
- prepared package ready entries: 15
- selected runtime unit sequence: 9
- selected unit source blocks: 7
- selected unit source characters: 906
- rendered glossary context: yes
- included glossary entries in rendered context: 1
- #465 cache behavior: `bypass_glossary_injected_cache`
- runtime structural validation: `pass`
- translated block count: 7 / 7
- glossary compliance summary: `pass`
- target-form-present count: 1 / 1
- secret-pattern findings in ordinary metadata report: none observed

## Evidence Boundary

The ordinary report is:

`outputs/issue-675-glossary-effectiveness-smoke/20260617T170414Z/metadata_report.json`

The ordinary report is metadata-only and does not contain raw source text,
prompt bodies, provider response bodies, translated text, API keys or provider
auth material. The raw-capable files remain local owner-only diagnostics and
are untracked.

## Interpretation

This is the first successful bounded smoke in this chain showing the current
prepared-glossary path can, for one approved control EPUB and target:

1. produce a #610 READY compact prepared package through DeepSeek Pro prep;
2. select a pressure-safe glossary-useful runtime unit;
3. render bounded glossary prompt context;
4. preserve #465 cache bypass for the injected unit;
5. obtain structurally valid runtime provider output;
6. produce a metadata-only glossary compliance pass for the included entry.

This does not prove broad real-book quality, morphology coverage, full
language-policy readiness, cache reuse readiness, release readiness or
production readiness. RU morphology remains `TBD`; broader provider stability,
quality impact across books and user-facing rollout confidence remain
`Unknown` until additional approved evidence exists.

## Verification

Local verification run for the #675 tooling:

- `PYTHONPATH=src python3 -m unittest tests.test_glossary_effectiveness_smoke`
- `PYTHONPATH=src python3 -m unittest tests.test_glossary_effectiveness_smoke tests.test_glossary_prepared_prep_service tests.test_glossary_prepared_package tests.test_glossary_prepared_provider tests.test_glossary_persistent_runtime_resolver`
- `PYTHONPATH=src python3 -m compileall src`
- `python3 -m ruff check tools/glossary_effectiveness_smoke.py tests/test_glossary_effectiveness_smoke.py`
- `git diff --check`

Live smoke command used the approved temporary process environment key only;
no provider config, key files or secrets were edited.
