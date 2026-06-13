# Reduced Glossary Editor Post-Fix Retry Report

Status: metadata-only report for GitHub issue #464 / #204AF.
Date: 2026-06-13.
Scope: owner-approved bounded DeepSeek-compatible provider retry after #461
packet-budget hardening, #462 failure metadata hardening and #463 local/fake
readiness measurement. No runtime translation integration, no prompt rollout,
no cache/storage/database/scheduler/admin/retention/provider-config changes
and no release/privacy/legal/support claims.

## Verdict

The bounded #464 provider retry is **PASS for provider-boundary evidence** and
**NO-GO for normal runtime glossary prompt integration**.

All four approved post-fix reduced packets validated locally with provider
`finish_reason=stop`, provider-reported usage present for every call and
observed tokens within the owner-approved 40000-token cap. This is materially
better than #449, where one Russian packet returned `length` plus invalid JSON
and one Ukrainian packet timed out with usage `Unknown`.

The result is still design/rehearsal evidence only. Merge/adjudication produced
warning findings, including low-confidence semantic warnings and one duplicate
entry warning. Local code still does not prove semantic truth such as
gender/name identity or literary correctness, and runtime prompt/cache/storage/
admin/retention/release behavior remains behind separate approval gates.

## Gate Deferral

The owner explicitly approved proceeding despite the #463 failed local
readiness gates:

- warning findings: `4 > 0`
- `needs_review_rate`: `1.0 > 0.25`
- reducer diagnostic/drop pressure: `0.967801 > 0.95`

This deferral applies only to the bounded #464 retry described here.

## Approval Boundary

- Inputs:
  - `test_samples/russian_profile_regression.en-ru.txt`
  - `test_samples/ukrainian_profile_regression.en-uk.txt`
  - `test_samples/sample_book.en.txt`
  - `private_fixtures/pg78824-images-3.epub`, target `ru`,
    rights/permissive basis confirmed by owner
- Packet selection: first READY hardened/rebalanced reduced glossary-editor
  packet per approved input from the post-#461 packetizer
- Max calls: 4
- Max tokens total: 40000
- Provider/model: DeepSeek-compatible provider / `deepseek-v4-pro`
- Diagnostic storage:
  `outputs/issue-464-reduced-glossary-editor-retry/<timestamp>/`, local
  owner-only, untracked
- Raw-text capture: yes; bounded fixture/book excerpts, prompts and provider
  responses only inside the approved diagnostics directory

## Fake/Dry Preflight

| Mode | Calls | Observed fake tokens | Status |
| --- | ---: | ---: | --- |
| fake/dry | 4 | 12737 | completed |

Fake diagnostics were written under
`outputs/issue-464-reduced-glossary-editor-retry/20260613T075957Z/`.

## Live Validation Results

The live retry used four provider attempts total.

| Input | Attempt | Status | Finish reason | Validation | Provider-reported tokens | Latency seconds |
| --- | ---: | --- | --- | --- | ---: | ---: |
| `russian_profile_regression.en-ru.txt` | 1 | validated | `stop` | valid=True; issues=0 | 5561 | 12.972 |
| `ukrainian_profile_regression.en-uk.txt` | 2 | validated | `stop` | valid=True; issues=0 | 5893 | 15.538 |
| `sample_book.en.txt` | 3 | validated | `stop` | valid=True; issues=0 | 4675 | 14.326 |
| `pg78824-images-3.epub` | 4 | validated | `stop` | valid=True; issues=0 | 4924 | 13.333 |

Observed provider tokens: 21053 / 40000.
Reserved local tokens: 31764 / 40000.
Latency shape: min `12.972`, max `15.538`, avg `14.042` seconds.

Live diagnostics were written under
`outputs/issue-464-reduced-glossary-editor-retry/20260613T080035Z/`.

Execution note: the live spike command emitted a completed metadata summary.
The surrounding zsh wrapper exited non-zero after the run because a post-run
shell assignment used the read-only variable name `status`. The live calls were
not repeated, and this wrapper error is not provider evidence.

## Merge And Findings

- Proposed entries: 14
- Invalid packets: 0
- Conflict rate: 0.0714
- Has blockers: False

| Finding code | Severity | Count |
| --- | --- | ---: |
| `duplicate_entry_output` | warning | 1 |
| `low_confidence_semantics` | warning | 8 |

## Confirmed

- Exact owner approval and gate deferral were recorded before live calls.
- Fake/dry preflight ran before live calls.
- Live calls stayed within the approved call and token caps.
- Every provider response validated locally.
- Finish reasons, validation status, issue counts, latency shape and
  provider-reported usage were recorded.
- Raw prompts, bounded excerpts and provider responses stayed inside the
  approved local owner-only untracked diagnostics directory.
- Runtime translation/cache/storage/admin behavior was not changed.

## Unknown

- Semantic truth such as gender/name identity remains `Unknown`; local
  validators prove structure, evidence references and metadata only.
- Whether the same behavior holds on larger books, other genres or different
  language pairs remains `Unknown`.
- CI status for the #464 PR is `Unknown` until GitHub Actions checks are
  inspected.

## TBD

- Runtime translation integration remains `TBD`.
- Release-version diagnostics retention/deletion/consent remains `TBD`.
- RU/UK morphology strategy remains `TBD`.
- Future glossary-aware cache keys remain `TBD` and require a separate
  approved issue.

## Recommendation

Use #464 as positive provider-boundary evidence for the next disabled/default-
off runtime-adjacent design step, not as runtime readiness.

The next safe step can be #466 disabled/default-off prompt-policy adapter work
after this #464 evidence is merged and reviewed, using only metadata-only
results from this report plus the #465 cache-bypass decision. Normal runtime
prompt integration, cache reuse, storage/admin diagnostics expansion,
retention/export/delete behavior and release/privacy/legal/support claims
remain blocked behind separate issues and approvals.
