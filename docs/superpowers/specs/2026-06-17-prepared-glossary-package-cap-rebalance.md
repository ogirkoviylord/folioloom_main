# Prepared Glossary Package Cap Rebalance

Date: 2026-06-17

Related issues: #671, #672, #673, #674, #675

## Scope

Issue #674 rebalances the local prepared-glossary prep-service defaults after
the #671 metadata-only runtime effectiveness audit.

This changes only local prepared-package candidate selection bounds and compact
metadata. It does not rewrite scanner v1, call live providers, operate
Telegram, change runtime translation provider/model, change cache reuse,
provider config/keys, DB/schema/state/storage/admin/retention behavior,
deployment, or release/privacy/legal/support posture.

## Evidence Basis

The #671 audit showed:

- cap 8 looked too narrow for useful committed-fixture coverage;
- cap 24 created more context opportunities but carried higher noise/pressure
  risk;
- cap 12 or 16 was the recommended conservative search space;
- real provider behavior and real translation quality remained `Unknown`.

Issue #672 then fixed prepared-package runtime applicability so source
canonical / safe alias presence is the primary applicability signal. Issue #673
added high-severity `not_effective` diagnostics when a READY attached package
still renders zero contexts.

## Contract

`PreparedGlossaryPrepServiceConfig` now defaults to:

- `max_candidates: 16`
- `max_estimated_editor_tokens: 4800`

The package validator's broad structural maximum remains separate and unchanged.
The rebalance affects the prep packet before fake/provider boundaries, not the
runtime resolver itself.

Prep-service metadata now exposes compact cap fields:

- `max_candidates`
- `max_estimated_editor_tokens`

Existing metadata still carries selected-candidate count, candidate-quality
counts/reason codes, validation counts and package signatures when validation
runs.

## Boundaries

The #663/#664 candidate-quality gates remain required. Pronoun, function-word,
common-phrase and boilerplate candidates must not become READY entries because
of the larger default cap.

Glossary core remains language-neutral. This does not add target-language
morphology or scanner-v2 behavior.

Ordinary artifacts stay metadata-only/redacted. Raw source text, prompt bodies,
provider responses, translated text, API keys and auth material must not appear
in ordinary logs, GitHub issues, PR descriptions, docs, support artifacts,
release artifacts or normal user/admin surfaces.

## Verification

Focused tests cover:

- default prep cap keeps 16 bounded durable candidates on a synthetic local
  fixture;
- cap 8 vs cap 16 changes candidate-selector and prepared-package signatures
  deterministically;
- existing low-value prep-service and package-quality gates still block noisy
  candidates;
- metadata remains raw/secret safe.

## Unknown / TBD

- Real provider behavior after #674 remains `Unknown` until #675.
- Real translation quality impact remains `Unknown`.
- Future cap changes beyond 16 remain `TBD` and should be evidence-driven.
- Release-version glossary diagnostics privacy/legal/support policy remains
  `TBD`.
