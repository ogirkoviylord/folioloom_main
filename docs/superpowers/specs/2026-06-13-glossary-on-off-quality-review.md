# Glossary On/Off Quality Review

## Routing Receipt
- Classification: spike / discovery, review work
- Risk level: high
- Primary skill: translation-quality-review
- Supporting skill: docs-sync; pr-review before PR-ready docs
- Approval status: approved in issue #478 comment for owner-only local review
- Allowed action: review/report only
- Verification: metadata-only report, redaction scan and `git diff --check`

## Verdict
NEEDS REVIEW.

This review does not establish that glossary-on output is better than
glossary-off output. The approved #477 live smoke produced three validated TXT
runtime outputs and two invalid EPUB runtime outputs, but no paired
non-glossary comparison outputs were available in the approved local artifacts.

Recommended next step: keep glossary runtime shadow-only, iterate the runtime
prompt/selection budget for EPUB units, then rerun a bounded smoke with paired
glossary-on/off comparison outputs before any rollout decision.

## Review Scope
- Source language: English
- Target languages: Russian and Ukrainian
- Document profile: book-manuscript / pipeline-regression sample
- Formats: TXT and EPUB
- Depth: pipeline-regression metadata review
- Raw review boundary: `outputs/issue-478-glossary-quality-review/`, local
  owner-only, untracked
- Raw excerpts copied into the #478 review artifact: no
- Non-glossary comparison outputs found: no

## Findings
| Severity | Location | Problem | Why it matters | Likely cause | Fix type | Recommended action | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Critical | pg78824 EPUB RU/UK smoke units | Provider outputs did not validate. | Invalid EPUB smoke output cannot be quality-reviewed or used as rollout evidence. | Runtime prompt/context plus EPUB unit shape exceeded the effective completion budget. | pipeline bug / prompt-budget iteration | Shrink or rebalance EPUB runtime prompt/context before another live smoke. | #477 finish reason `length`; issue codes `truncated_output`, `external_text`. |
| Major | All reviewed inputs | No paired glossary-off comparison output was available. | The review cannot prove glossary-on improves names, terms, voice or consistency over the existing path. | #477 was designed as provider-boundary smoke, not a paired quality evaluation. | evaluation design | Next bounded run should generate same-unit glossary-on/off pairs or reuse approved existing baselines if available. | #478 local metadata review found `non_glossary_comparison_outputs_found=false`. |
| Major | Validated TXT smoke units | Three TXT calls passed structural validation, but quality improvement remains Unknown. | Structure-valid output is not enough to claim reader quality, semantic fidelity or glossary benefit. | Smoke gate validates response shape, not comparative literary quality. | human review / terminology pass | Use owner-only paired review after a comparison baseline exists. | #477 validated Russian TXT regression, Ukrainian TXT regression and sample-book Russian TXT. |

## Overall Quality Notes
- Confirmed: #477 produced 3 structurally valid TXT glossary-injected runtime
  outputs within the approved live call/token bounds.
- Confirmed: #477 produced 2 invalid EPUB glossary-injected runtime outputs.
- Unknown: glossary-on vs glossary-off quality delta, terminology consistency
  improvement, name/entity consistency improvement, style/voice impact and
  RU/UK morphology impact.
- TBD: exact quality threshold for a future controlled battle test.

## Format And Structure Notes
- TXT provider-boundary structure passed for the three validated calls.
- EPUB provider-boundary structure failed for both approved pg78824 targets.
- No format fidelity or full-book assembly quality is proven by this review.

## Terminology And Name Consistency Notes
- Glossary benefit remains Unknown because no paired baseline was available.
- Local code still must not claim semantic truth such as gender/name identity.
- RU/UK morphology remains TBD.

## Recommendation
Keep shadow-only. Do not proceed to runtime glossary rollout, limited beta
plan, cache reuse or release/privacy/legal/support claims from #477/#478.

Open or use a follow-up issue for EPUB runtime prompt/selection budget
iteration, then rerun a bounded live smoke with paired glossary-on/off outputs
for the same units before another quality review.

## Verification
- Reviewed #477 metadata manifest and #478 local metadata artifact.
- Local #478 artifact:
  `outputs/issue-478-glossary-quality-review/20260613T130355Z/metadata-review.json`
- No code tests required; no code changed.
- `git diff --check` and metadata redaction scans are required before PR.

## TBD / Unknown
- TBD: future battle-test quality threshold.
- TBD: release-version glossary/profile diagnostics consent, retention,
  deletion, support and legal/privacy policy.
- Unknown: comparative glossary quality benefit.
- Unknown: valid EPUB glossary runtime behavior after prompt/selection changes.
