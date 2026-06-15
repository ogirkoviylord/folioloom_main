# Prepared Glossary Pro Prep Retry Ready Report

Status: metadata-only provider-boundary report for GitHub issue #624.
Date: 2026-06-15.
Parent: #608.
Blocks / informs: #607.
Follows: #614, #622, #626, #628, #630.

Scope: bounded live DeepSeek Pro glossary-prep retry only. No Telegram
changes, no database/schema/state/storage/admin/retention/export/delete
changes, no default glossary rollout, no cache reuse and no
release/privacy/legal/support claims.

## Routing Receipt

- Classification: risky task / provider-boundary spike.
- Risk level: high, because the task sends bounded approved fixture excerpts
  and a glossary-prep prompt to a live provider and records owner-only raw
  diagnostics.
- Primary repo-level skill: `implementation`.
- Supporting skill: `docs-sync`.
- Approval status: owner approved the bounded #614/#624 retry path in the
  caps, diagnostics boundary and raw-capture policy.
- Allowed action: fake/dry preflight, bounded live Pro glossary-prep call,
  local validation, metadata-only ordinary report and docs sync.
- Verification plan: focused tests, compileall, targeted ruff, fake/dry run,
  live metadata report, secret-pattern scan, `git diff --check` and repo-level
  PR review for code/docs changes.

## Approved Input And Bounds

- Input: `test_samples/gutenberg_time_machine_noimages.en.epub`.
- Source basis: committed Project Gutenberg public-domain/permissive control
  fixture.
- Target: `ru`.
- Selection: first bounded prepared-glossary packet from fake/dry preflight.
- Candidate bound: max 8 selected candidates.
- Excerpt bound: max 1200 chars per candidate.
- Prepared package bound: max 1.
- Live cap: max 6 calls per approved run.
- Token cap: max 60000 provider-reported tokens total per approved run.
- Provider/model for glossary prep: DeepSeek-compatible provider /
  `deepseek-v4-pro`.
- Runtime translation model/provider: unchanged configured runtime path.
- Diagnostics root:
  `outputs/glossary-battle-test/issue-624-pro-prep-retry/<timestamp>/`.

## Follow-Up Hardening

The first #614 live run failed because required top-level package fields were
omitted. The bounded #624 retry path required several local-only hardening
steps before a READY package was produced:

- #622 applies a deterministic local envelope for locally owned package
  metadata while preserving provider-supplied target metadata.
- #626 unwraps the exact single-key `output_package_skeleton` provider shape.
- #628 treats placeholder/`Unknown` local metadata as missing and forces the
  deterministic local envelope.
- #630 enriches compact provider entries from the approved packet for
  source-side fields only, while preserving provider-supplied target metadata
  and stripping provider-only extra entry fields from the final package.

These steps do not let local code invent target-language facts.

## Evidence

Fake/dry preflight before the final live retry:

- Timestamp: `20260615T193000Z`.
- Status: `ready`.
- Validation status: `ready`.
- Selected candidates: 8.
- Live provider calls: 0.
- Provider tokens: 0.
- Metadata report:
  `outputs/glossary-battle-test/issue-624-pro-prep-retry/20260615T193000Z/metadata_report.json`.

Final live retry after #630:

- Timestamp: `20260615T193500Z`.
- Calls made: 1.
- HTTP status: 200.
- Finish reason: `stop`.
- Latency shape: one call, 12.48 seconds.
- Provider-reported usage: prompt 8142, completion 1634, total 9776 tokens.
- Selected candidates: 8.
- Adjudication mode: `local_envelope_applied`.
- Adjudication reason codes:
  `provider_package_unwrapped_output_skeleton`,
  `provider_package_local_metadata_placeholder`,
  `provider_package_missing_local_envelope_fields`.
- Local prepared-package validation status: `ready`.
- Entry count: 8.
- Ready entry count: 8.
- Needs-review entry count: 0.
- Package id: `prepared:issue-624:ru:fa1300b7c9b9d935`.
- Package signature: `prepared-glossary-package:v1:d44289d055a4105a`.
- Metadata report:
  `outputs/glossary-battle-test/issue-624-pro-prep-retry/20260615T193500Z/metadata_report.json`.
- Diagnostics secret scan findings: none for the checked provider
  auth/key/env marker set.

## Verdict

GO for the next owner-assisted #607 Telegram battle-test preparation step,
assuming the existing #607 approval boundaries still apply.

This is not a glossary quality proof, rollout approval, cache reuse approval or
release/privacy/legal/support readiness claim. It only proves that the bounded
Pro-prep path can produce a #610 READY compact prepared package for the
approved committed control EPUB and target.

## Confirmed Facts

- The live call stayed inside the approved call and token caps.
- Raw prompts, bounded excerpts and provider response material were kept inside
  the owner-only untracked diagnostics directory.
- Ordinary docs and reports contain metadata only.
- Runtime translation model/provider was not changed.
- No default rollout, cache reuse, provider config/key, DB/schema/state,
  storage/admin/retention/export/delete, release/privacy/legal/support change
  was made.

## Unknown / TBD

- Real Telegram battle-test translation quality with this prepared package is
  `Unknown`.
- Whether this result generalizes beyond the approved committed control EPUB is
  `Unknown`.
- Release-version retention/export/delete/privacy/legal/support policy for
  glossary diagnostics remains `TBD`.
  to enter Telegram.

## Follow-Up

- Run the owner-assisted #607 Telegram battle-test only within the approved
  boundaries.
- Review downloaded owner-only diagnostic archives with
  `translation-quality-review` before any rollout, cache or release decision.
