# DeepSeek Pro Prepared Glossary Live Spike Report

Status: metadata-only provider-boundary report for GitHub issue #614.
Date: 2026-06-15.
Parent: #608.
Blocks / informs: #607.
Follows: #610, #611, #612, #613, #619.

Scope: bounded live DeepSeek Pro glossary-prep spike only. No Telegram
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
  target, candidate/excerpt bounds, call/token caps, diagnostics boundary and
  raw-capture policy.
- Allowed action: fake/dry preflight, bounded live Pro glossary-prep call,
  local validation, metadata-only ordinary report and docs sync.
- Verification plan: focused tests, compileall, targeted ruff, fake/dry run,
  live metadata report, secret-pattern scan, `git diff --check` and repo-level
  PR review.

## Approved Input And Bounds

- Input: `test_samples/gutenberg_time_machine_noimages.en.epub`.
- Source basis: committed Project Gutenberg public-domain/permissive control
  fixture.
- Target: `ru`.
- Selection: first bounded prepared-glossary packet from fake/dry preflight.
- Candidate bound: max 8 selected candidates.
- Excerpt bound: max 1200 chars per candidate.
- Prepared package bound: max 1.
- Live cap: max 6 calls.
- Token cap: max 60000 provider-reported tokens total.
- Provider/model for glossary prep: DeepSeek-compatible provider /
  `deepseek-v4-pro`.
- Runtime translation model/provider: unchanged configured runtime path.
- Diagnostics root:
  `outputs/glossary-battle-test/issue-614-pro-prep/<timestamp>/`.

## Evidence

Fake/dry preflight:

- Timestamp: `20260615T160000Z`.
- Status: `ready`.
- Validation status: `ready`.
- Selected candidates: 8.
- Live provider calls: 0.
- Provider tokens: 0.
- Metadata report:
  `outputs/glossary-battle-test/issue-614-pro-prep/20260615T160000Z/metadata_report.json`.
- Metadata report secret/raw scan findings: none for the checked marker set.

Live run:

- Timestamp: `20260615T160500Z`.
- Calls made: 1.
- HTTP status: 200.
- Finish reason: `stop`.
- Latency shape: one call, 17.851 seconds.
- Provider-reported usage: prompt 7955, completion 1640, total 9595 tokens.
- Selected candidates: 8.
- Local prepared-package validation status: `invalid`.
- Result status: `failed`.
- Metadata report:
  `outputs/glossary-battle-test/issue-614-pro-prep/20260615T160500Z/metadata_report.json`.
- Diagnostics secret scan findings: none for provider auth/key/env marker set.

## Validation Findings

The provider returned a JSON object with the expected schema version, source
language, target language and 8 entries, but it omitted required top-level
prepared-package fields.

Reason codes:

- `prepared_glossary_package_owner_approval_missing`;
- `prepared_glossary_package_id_missing`;
- `prepared_glossary_package_provider_role_missing`;
- `prepared_glossary_package_provider_model_missing`;
- `prepared_glossary_package_selector_signature_missing`.

Observed returned top-level keys:

- `schema_version`;
- `source_language`;
- `target_language`;
- `entries`.

This is a schema-contract failure, not a runtime translation failure. No
runtime translation call was made.

## Verdict

NO-GO for #607 Telegram glossary battle-test based on this #614 run.

The local wiring and fake/dry package path remain available, but the first live
Pro-prep response did not satisfy the #610 prepared-package contract. The next
step should tighten the provider prompt/response contract or add a local
metadata wrapper/adjudication step in a separate approved issue before any
fresh live retry.

## Confirmed Facts

- #619 fake/dry preflight passed before the live call.
- The live call stayed inside the approved call and token caps.
- Raw prompts, bounded excerpts and provider response material were kept inside
  the owner-only untracked diagnostics directory.
- Ordinary docs and reports contain metadata only.
- Runtime translation model/provider was not changed.
- No default rollout, cache reuse, provider config/key, DB/schema/state,
  storage/admin/retention/export/delete, release/privacy/legal/support change
  was made.

## Unknown / TBD

- Translation quality with a READY live prepared package remains `Unknown`.
- Whether a stricter prompt, response skeleton or local wrapper would make
  `deepseek-v4-pro` return a READY package is `Unknown`.
- Release-version retention/export/delete/privacy/legal/support policy for
  glossary diagnostics remains `TBD`.
- Any fresh live retry requires owner approval if the next issue changes bounds
  or if the approval gate requires a new exact packet.

## Follow-Up

- Create a focused issue to harden the #614 live Pro-prep prompt/contract after
  the observed top-level-field omission.
- Keep #607 owner-assisted Telegram glossary battle-test blocked until a live
  prepared package validates as READY and can be handed into the existing
  resolver path.
