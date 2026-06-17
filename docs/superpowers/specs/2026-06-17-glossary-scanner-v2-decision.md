# Glossary Scanner v2 Decision After Candidate-Quality Evidence

Date: 2026-06-17

Related issues: #661, #663, #664, #665, #666

## Routing Receipt

- Classification: docs-only architecture review.
- Risk level: medium/high because scanner decisions affect future glossary
  prep packets, prepared package READY status, prompt usefulness, diagnostics
  and possible runtime behavior.
- Primary role / skill: Architect Agent / `architecture-review`.
- Approval status: approved for #666 analysis/design under the #661 owner
  approval boundary; scanner-v2 implementation or runtime switch still needs a
  separate explicit approval.
- Allowed action: no-code architecture decision only.
- Verification: docs diff review, `git diff --check`, repo-level `pr-review`.

## Verdict

**SAFE: keep scanner v1 plus #663/#664 quality gates for now.**

Do not rewrite the deterministic scanner in-place for #661. Do not start
scanner v2 implementation from this evidence alone. The next safe posture is:

- keep scanner v1 as the active deterministic extractor;
- keep #663 prep-input quality filtering before fake/provider boundaries;
- keep #664 package READY quality enforcement;
- use #665 metadata-only audit as the local evidence baseline;
- revisit scanner v2 only as a separately approved, versioned, shadow-only
  extractor if future audits or reviewed battle-test evidence show v1+gates are
  still insufficient.

No scanner-v2 implementation issue is created from #666 because the current
metadata-only evidence does not justify a rewrite now.

## Evidence Reviewed

Confirmed local evidence from #665:

- committed fixture cases: 3
- prep input candidates: 20
- prep selected candidates after #663: 18
- prep dropped candidates after #663: 2
- package selected candidates after #664: 18
- package dropped candidates after #664: 0
- ready fake/local cases: 3
- low-value candidate rate: 0.1
- observed reason-code families:
  - `candidate_quality_low_value_source`
  - `candidate_quality_function_word_phrase`

Confirmed implementation boundaries from #663/#664/#665:

- low-value pronoun/function-word/common-phrase candidates can be dropped before
  prepared prep packets cross fake/provider boundaries;
- schema-valid all-low-value prepared packages cannot become READY;
- audit reports are metadata-only and do not include raw source text, raw
  candidate strings, prompts, translations, provider responses, API keys or auth
  material.

Unknown:

- real provider behavior after these gates is `Unknown`;
- real-book translation quality after these gates is `Unknown`;
- long-tail scanner coverage across more books/languages is `Unknown`;
- whether v1 misses important subtle terminology is `Unknown`.

## Why Not Rewrite Scanner Now

Scanner v1 is not perfect: it can emit capitalized phrase noise such as
function-word/pronoun phrases. But the observed failure mode is now addressed at
two safer boundaries:

- #663 blocks bad prep inputs before provider/fake-provider calls;
- #664 prevents structurally valid but low-value prepared packages from becoming
  READY.

An in-place scanner rewrite would touch candidate ids, evidence refs, reducer
behavior, prepared packet signatures, package matching, diagnostics and future
runtime selection. That is much higher blast radius than the current evidence
supports.

## Future Scanner-v2 Trigger

Create a separate scanner-v2 shadow issue only if one of these happens in a
metadata-only local audit, bounded fake/live prep run, or owner-reviewed
battle-test:

- low-value candidate rate remains materially high after #663/#664 gates;
- valid durable names/places/terms are consistently missing from prepared
  candidates;
- package READY quality remains poor even after #664;
- provider prep repeatedly needs review because scanner evidence is not useful;
- reviewer evidence shows #663 rules are becoming a growing list of brittle
  source-language exceptions.

Thresholds for "materially high" and "consistently missing" remain `TBD` until
the owner approves a broader fixture/audit matrix.

## Metrics For Any Future v2 Comparison

A scanner-v2 shadow evaluation must compare v1 and v2 with metadata-only
outputs:

- prep input candidate count;
- prep selected candidate count;
- dropped/demoted candidate count;
- low-value candidate rate;
- alias-pruning count;
- evidence-ref coverage;
- source-unit/source-block coverage;
- package READY / needs_review / invalid status distribution;
- package-level quality drop count;
- runtime useful-entry count where applicable;
- structural validation status;
- raw/secret leak checks;
- deterministic signature stability.

Local code must not claim semantic truth, name identity, gender, morphology or
literary quality.

## Required Shape For Future Scanner v2

If approved later, scanner v2 must be:

- versioned separately from scanner v1;
- shadow-only and disabled by default;
- metadata-only in ordinary artifacts;
- non-destructive to scanner v1 ids/signatures until explicitly switched;
- evaluated against v1 on the same authorized fixtures;
- isolated from live providers, runtime rollout and cache reuse unless a later
  issue explicitly approves those gates.

## Affected Components

- `src/translator_service/glossary_scanner.py`: remains scanner v1.
- `src/translator_service/glossary_candidate_quality.py`: current source-side
  quality gate after scanner/reducer selection.
- `src/translator_service/glossary_prepared_prep_service.py`: applies #663
  before prepared prep packets.
- `src/translator_service/glossary_prepared_package.py`: applies #664 before
  READY status.
- `src/translator_service/glossary_candidate_quality_audit.py` and
  `tools/prepared_glossary_candidate_quality_audit.py`: current #665
  metadata-only audit surface.

## Risks

- Over-filtering can hide legitimate names/places/terms.
- Under-filtering can keep provider prep dominated by low-value phrases.
- Scanner-v2 in-place rewrites can destabilize candidate ids, evidence refs,
  reducer signatures, prepared package matching and future runtime selection.
- The current audit matrix is small; broader real-book coverage remains
  `Unknown`.

## Required Tests And Gates

For the current no-code #666 decision:

- docs diff review;
- `git diff --check`;
- repo-level `pr-review`.

For any future scanner-v2 shadow implementation:

- focused v1/v2 fixture comparison tests;
- metadata-only report/redaction tests;
- signature stability tests;
- focused prepared prep/package tests proving v1 remains unaffected;
- `PYTHONPATH=src python3 -m compileall src`;
- targeted ruff for touched Python files;
- docs-sync and repo-level `pr-review`.

## Required Approval Gates

Separate owner approval remains required for:

- scanner-v2 implementation;
- any switch from scanner v1 to scanner v2;
- live provider calls;
- runtime prompt rollout;
- glossary-aware cache reuse;
- provider config/key changes;
- DB/schema/state/storage/admin/retention changes;
- deployment or release/privacy/legal/support claims.

## Suggested Future Task Breakdown

No follow-up scanner-v2 implementation issue is created now. If future evidence
triggers scanner-v2 exploration, split it as:

1. No-code fixture/audit matrix and acceptance thresholds.
2. Local-only shadow scanner-v2 extractor with versioned signatures.
3. Metadata-only v1/v2 comparison audit.
4. Architecture go/no-go review before any runtime or provider-adjacent use.

## Decision

Current decision: **defer scanner v2 implementation and keep v1 + gates**.

Future owner decision needed: `TBD` for whether to create a scanner-v2 shadow
evaluation issue after more audit/live evidence.
