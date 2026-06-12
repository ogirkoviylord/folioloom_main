# DeepSeek Pro Glossary/Profile Spike Report

Status: bounded provider-backed spike report for GitHub issue #413 / #204J.
Date: 2026-06-12.
Scope: approved fixtures only, no runtime translation integration, no provider
runtime changes, no cache changes, no database/schema/storage changes, no
retention/privacy/legal/release readiness claim.

## Routing Receipt

- Classification: spike / discovery.
- Risk level: high.
- Primary role: Implementer Agent after prior architecture review.
- Primary repo-level skill: `implementation`.
- Supporting skills: `docs-sync` for this metadata-only report and handoff
  pointers, `pr-review` for final diff review.
- Approval status: approved with evidence in the current owner thread for:
  three exact fixtures, max 6 calls, max 60000 total tokens,
  DeepSeek-compatible provider / `deepseek-v4-pro`, diagnostic storage under
  `outputs/issue-413-deepseek-pro-spike/<timestamp>/`, and raw text capture
  only in that owner-only local untracked diagnostics directory.
- Allowed action: bounded provider spike and metadata-only report.
- Verification plan: fake-provider dry run, live provider run within approved
  call scope, local #408 validators, secret-leak scan, focused tests,
  compileall, targeted ruff, `git diff --check`, and repo-level `pr-review`.

## Approved Fixtures

- `test_samples/russian_profile_regression.en-ru.txt`
- `test_samples/ukrainian_profile_regression.en-uk.txt`
- `test_samples/sample_book.en.txt`

These are test fixtures, not runtime `var/` user uploads.

## Diagnostic Boundary

Raw prompts, bounded source excerpts and raw provider responses were captured
only in:

- `outputs/issue-413-deepseek-pro-spike/20260612T073000Z/`

That directory is local, owner-only and untracked. This report does not include
raw source excerpts, prompt bodies, provider request bodies, provider response
bodies or API keys.

## Confirmed

- The runner processed only the three approved fixtures.
- The run made exactly 6 provider calls.
- The provider/model used was `deepseek-v4-pro` through the approved
  DeepSeek-compatible chat-completions boundary.
- All HTTP calls returned `200`.
- `pro_book_profile_advisor` returned validator-accepted JSON for all three
  fixtures.
- `pro_glossary_editor_normalizer` returned validator-accepted JSON for the
  small `sample_book.en.txt` fixture.
- Cross-role validation passed for `sample_book.en.txt`, the only fixture where
  both role outputs were individually valid.
- No runtime translation behavior, cache behavior, provider runtime behavior,
  database/schema/state, deployment, legal/privacy copy or release gate was
  changed.
- The committed tool now uses a conservative token reservation multiplier and
  checks already observed provider token usage before later calls.

## Observed Results

| Fixture | Role | HTTP | Finish | Validation |
| --- | --- | --- | --- | --- |
| `russian_profile_regression.en-ru.txt` | `pro_book_profile_advisor` | 200 | `stop` | valid |
| `russian_profile_regression.en-ru.txt` | `pro_glossary_editor_normalizer` | 200 | `length` | invalid JSON |
| `ukrainian_profile_regression.en-uk.txt` | `pro_book_profile_advisor` | 200 | `stop` | valid |
| `ukrainian_profile_regression.en-uk.txt` | `pro_glossary_editor_normalizer` | 200 | `length` | invalid JSON |
| `sample_book.en.txt` | `pro_book_profile_advisor` | 200 | `stop` | valid |
| `sample_book.en.txt` | `pro_glossary_editor_normalizer` | 200 | `stop` | valid |

Token shape:

- Reserved by the initial local estimator: 51121.
- Observed provider usage: 62974.
- Approved cap: 60000.
- Overrun: 2974 observed provider tokens.

The overrun happened because the first runner version reserved budget from a
local character-based estimate that undercounted provider-reported prompt
tokens. No additional live calls were made after this was discovered. The
runner was then changed to reserve prompt tokens more conservatively and to use
already observed provider usage before allowing later calls.

## Unknown

- Whether `pro_glossary_editor_normalizer` would validate on the two larger
  fixtures with a smaller candidate/evidence payload, a higher completion cap,
  streamed continuation strategy or a split role design is Unknown.
- Exact provider cost is Unknown from repository evidence unless the owner
  checks the provider account dashboard.
- CI status for this branch is Unknown until a PR/checks page is inspected.

## TBD

- Runtime integration remains `TBD`.
- Prompt rollout to normal translation jobs remains `TBD`.
- Release-version glossary/profile diagnostic retention, deletion, consent,
  support and legal/privacy behavior remains `TBD`.
- RU/UK morphology strategy remains `TBD`; this spike does not prove
  grammatical gender/name identity semantics.

## Recommendation

Do not integrate DeepSeek Pro glossary/profile roles into runtime translation
yet.

Proceed only to a next design/review slice that reduces glossary editor payload
size or splits the editor role before any further live provider spike. The
large-fixture glossary editor failures should be treated as real failures, not
manual successes, because the local #408 validators rejected the outputs.

Any further live provider work requires a fresh exact approval package with
fixtures, max calls, max tokens, provider/model, diagnostic storage and
raw-text capture policy.
