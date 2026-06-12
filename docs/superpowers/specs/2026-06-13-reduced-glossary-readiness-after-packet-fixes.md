# Reduced Glossary Readiness After Packet Fixes

Status: metadata-only report for GitHub issue #463 / #204AE.
Date: 2026-06-13.
Scope: local/fake reduced glossary readiness after #461 packet-budget
hardening and #462 fake failure-mode coverage. No live provider calls, no
runtime translation integration, no prompt rollout, no cache/storage/database/
scheduler/admin/retention/provider-config changes and no release/privacy/
legal/support claims.

## Verdict

Default local/fake readiness is **FAIL** for the full approved next-retry input
set.

The local structural gates improved: schema validity, evidence-ref coverage,
invalid chunk rate, blocker findings, duplicate/conflict rate, packet budget
overruns and reducer decision coverage all pass for the measured fake run.
However, the default readiness gate still fails because:

- fake outputs are intentionally low-confidence/needs-review, producing
  warning findings and `needs_review_rate=1.0`
- the full four-input set, including the approved local EPUB, has reducer
  diagnostic/drop pressure `0.967801`, above the default `0.95` threshold
- provider retry evidence is absent because #463 did not make live calls

Therefore #463 does **not** satisfy the current #464 start condition that local
reduced glossary readiness gates pass. Starting #464 now would require either
a follow-up local reducer/fake-output hardening task or an explicit owner
decision to defer/override the failed local gates.

## Inputs

Measured with the reduced-packet first-READY selection over:

- `test_samples/russian_profile_regression.en-ru.txt`
- `test_samples/ukrainian_profile_regression.en-uk.txt`
- `test_samples/sample_book.en.txt`
- `/Users/yuriimedvediev/Downloads/pg78824-images-3.epub`, target `ru`,
  rights/permissive basis previously confirmed by owner

The local EPUB file was present during the measurement. The report includes
only metadata counts and status; no source excerpts, prompts, provider
responses, translations, API keys or auth material are included.

## Commands

```bash
PYTHONPATH=src python3 tools/deepseek_chunked_glossary_editor_spike.py \
  --fake \
  --issue-449-reduced \
  --diagnostic-root /tmp/issue-463-reduced-fake \
  --metadata-report /tmp/issue-463-fake-metadata.md
```

Result summary:

| Mode | Calls | Observed fake tokens | Status |
| --- | ---: | ---: | --- |
| local/fake | 4 | 12737 | completed |

A metadata-only Python extraction then evaluated the fake validations with
`evaluate_glossary_editor_readiness(..., provider_evidence_available=False)`.
The temporary diagnostics directory was outside the repository under `/tmp`.

## Fixture Packet Shape

| Input | Target | Packets | Selected | Entries | Evidence refs | Estimated / max | Reserved / max | Split reasons | Fake validation |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `russian_profile_regression.en-ru.txt` | `ru` | 10 | 0 | 4 | 12 | 939 / 1000 | 2194 / 2500 | `entry_limit_exhausted`, `token_budget_exhausted` | valid |
| `ukrainian_profile_regression.en-uk.txt` | `uk` | 10 | 0 | 4 | 12 | 943 / 1000 | 2203 / 2500 | `entry_limit_exhausted`, `token_budget_exhausted` | valid |
| `sample_book.en.txt` | `ru` | 1 | 0 | 4 | 8 | 670 / 1000 | 1603 / 2500 | none | valid |
| `pg78824-images-3.epub` | `ru` | 14 | 0 | 3 | 9 | 952 / 1000 | 2223 / 2500 | `token_budget_exhausted` | valid |

## Local/Fake Gate Metrics

| Metric | Value | Default gate |
| --- | ---: | --- |
| total chunks | 4 | pass |
| schema validity rate | 1.0 | pass |
| evidence-ref coverage rate | 1.0 | pass |
| invalid chunk rate | 0.0 | pass |
| blocker findings | 0 | pass |
| warning findings | 4 | fail; expected `<= 0` |
| duplicate rate | 0.0 | pass |
| conflict rate | 0.0 | pass |
| packet budget overruns | 0 | pass |
| proposed entries | 4 | measured |
| needs-review rate | 1.0 | fail; expected `<= 0.25` |
| max packet budget utilization | 0.952 | measured |
| reduced packet count | 4 | measured |
| reducer context count | 4 | measured |
| reducer decision coverage rate | 1.0 | pass |
| reducer diagnostic/drop pressure | 0.967801 | fail; expected `<= 0.95` |
| fake observed tokens | 12737 / 40000 | pass as local metadata only |

## Repo-Fixture Cross-Check

The three repository fixtures without the external EPUB also validated
structurally:

- schema validity rate: `1.0`
- evidence-ref coverage rate: `1.0`
- invalid chunk rate: `0.0`
- blocker findings: `0`
- duplicate/conflict rate: `0.0`
- packet budget overruns: `0`
- reducer decision coverage rate: `1.0`
- reducer diagnostic/drop pressure: `0.311475`

That repo-only set still fails default readiness because the current fake
provider emits low-confidence needs-review outputs, causing warning findings
and `needs_review_rate=1.0`.

## Unknown

- Live provider behavior after #461/#462 is `Unknown`; #463 made no live calls.
- Provider-reported token usage, finish reasons and latency for a post-fix live
  retry are `Unknown`.
- Whether the local EPUB reduced packet would validate with the live provider
  after #461/#462 is `Unknown`.
- Semantic truth such as gender/name identity and literary correctness remains
  `Unknown`; local validators only prove structure, references and metadata
  gates.

## TBD

- Human decision on whether to add another local hardening issue before #464 is
  `TBD`.
- Human decision on whether to explicitly defer/override the failed local gates
  before #464 is `TBD`.
- Runtime translation integration remains `TBD`.
- Cache policy remains `TBD` until #465 is completed.
- Release-version diagnostics retention/deletion/consent remains `TBD`.
- RU/UK morphology strategy remains `TBD`.

## Recommendation

Do not start #464 under the current approval wording.

Recommended next step: open or approve a small local follow-up before #464 to
separate structural fake-output readiness from semantic-confidence warnings and
to reduce or explicitly re-threshold the EPUB reducer diagnostic/drop pressure.
If the owner wants to proceed to #464 despite this report, record that as an
explicit gate deferral with the failed metrics above and keep #464 bounded,
metadata-only and non-runtime.

Passing any future local/fake gate still would not approve runtime prompt
integration, cache reuse, storage/admin diagnostics, retention/export/delete,
release/privacy/legal/support claims or semantic truth claims.
