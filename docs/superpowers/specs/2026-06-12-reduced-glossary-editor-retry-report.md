# Reduced Glossary Editor Retry Report

Status: metadata-only report for GitHub issue #449 / #204Z.
Date: 2026-06-12.
Scope: owner-approved bounded DeepSeek-compatible provider retry on reduced
glossary-editor packets. No runtime translation integration, no prompt rollout,
no cache/storage/database/scheduler/admin/retention/provider-config changes and
no release/privacy/legal/support claims.

## Confirmed

- local reduced-packet tooling was rebased on current `main` after #450/#451
- fake/dry preflight completed before live calls
- approved inputs were packetized with the first READY reduced packet rule
- raw prompts/provider outputs stayed inside the approved local untracked
  diagnostics directories
- runtime translation/cache/storage/admin behavior was not changed
- at least one reduced glossary-editor provider output passed validation
- merge/adjudication contract was run on validated continuation outputs

## Unknown

- provider-reported token usage for one timed-out Ukrainian packet attempt is
  `Unknown`
- the timed-out Ukrainian packet has no validated provider body
- semantic truth such as gender/name identity remains evidence/review-driven

## TBD

- runtime translation integration remains `TBD`
- cache stale/migration policy remains `TBD`
- release-version diagnostics retention/deletion/consent remains `TBD`
- RU/UK morphology strategy remains `TBD`

## Approval Boundary

- Inputs:
  - `test_samples/russian_profile_regression.en-ru.txt`
  - `test_samples/ukrainian_profile_regression.en-uk.txt`
  - `test_samples/sample_book.en.txt`
  - `/Users/yuriimedvediev/Downloads/pg78824-images-3.epub`, target `ru`,
    rights/permissive basis confirmed by owner
- Packet selection: first READY reduced glossary-editor packet per approved
  input
- Max calls: 4
- Max tokens total: 40000
- Provider/model: DeepSeek-compatible provider / `deepseek-v4-pro`
- Diagnostic storage:
  `outputs/issue-449-reduced-glossary-editor-retry/<timestamp>/`, local
  owner-only, untracked
- Raw-text capture: yes; bounded fixture/book excerpts, prompts and provider
  responses only inside the approved diagnostics directory

## Local/Fake Preflight

| Mode | Calls | Observed tokens | Status |
| --- | ---: | ---: | --- |
| fake/dry | 4 | 15109 | completed |

## Live Validation Results

The live retry used four provider attempts total. The first run completed the
Russian packet and then timed out while reading the next provider response. The
continuation run used the remaining approved call budget for `sample_book` and
the approved EPUB input.

| Input | Attempt | Status | Finish reason | Validation | Provider-reported tokens |
| --- | ---: | --- | --- | --- | ---: |
| `russian_profile_regression.en-ru.txt` | 1 | failed | `length` | valid=False; issues=1; `invalid_json` | 7551 |
| `ukrainian_profile_regression.en-uk.txt` | 2 | failed | `Unknown` | valid=False; timeout before validated body | Unknown |
| `sample_book.en.txt` | 3 | validated | `stop` | valid=True; issues=0 | 4270 |
| `pg78824-images-3.epub` | 4 | validated | `stop` | valid=True; issues=0 | 6450 |

Known observed provider tokens: 18271.

Provider token-cap evidence is incomplete because the timed-out Ukrainian
attempt did not return provider usage metadata. The call cap was respected:
four live attempts total.

## Continuation Merge And Findings

The completed continuation report covered `sample_book.en.txt` and
`pg78824-images-3.epub`.

- Proposed entries: 9
- Invalid packets: 0
- Conflict rate: 0.0
- Has blockers: False

| Finding code | Severity | Count |
| --- | --- | ---: |
| `low_confidence_semantics` | warning | 4 |

## Failure Modes

- Russian reduced packet still hit provider `finish_reason=length` and invalid
  JSON.
- Ukrainian reduced packet timed out while reading the provider response; local
  timeout handling was then hardened so future timeouts become metadata
  failures instead of tracebacks.
- Sample TXT and the approved EPUB packet validated successfully, which is
  useful evidence for the reduced path but not enough for runtime integration.

## Recommendation

NO-GO for normal runtime glossary prompt integration.

The reduced packet path is improved enough to keep iterating, and the approved
EPUB packet is a useful success signal. However, one RU regression packet still
failed with `length`/`invalid_json`, one UK regression packet timed out, and
provider token usage for that timeout is `Unknown`. Runtime prompt integration,
cache behavior, storage/admin diagnostics, retention/delete/export behavior and
release/privacy/legal/support claims remain blocked behind separate owner
approval and follow-up evidence.
