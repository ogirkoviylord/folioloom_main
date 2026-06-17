# Prepared Glossary Runtime Applicability Fix

Date: 2026-06-17

Related issues: #671, #672, #673, #674, #675

## Scope

Issue #672 changes only the prepared-package runtime applicability path for
#610 READY packages. It is a local/runtime-adjacent bugfix so prepared packages
that are already attached to a job can render bounded glossary context when the
current work unit contains the source canonical term or a safe alias.

This does not call live providers, operate Telegram, change provider config or
keys, change DB/schema/state/storage/admin/retention behavior, deploy anything,
enable glossary-aware cache reuse, add a RU/UK morphology engine, or make
release/privacy/legal/support claims.

## Contract

Prepared package applicability now uses this order:

1. validate the #610 package and target language;
2. require target metadata on the prepared entry;
3. use source canonical / safe alias presence as the primary per-unit
   applicability signal;
4. treat `source_unit_refs` and `source_block_refs` as confidence and
   diagnostics metadata, not a universal hard blocker for repeated book-level
   terms;
5. skip ambiguous alias-only matches when the matched alias is locally risky;
6. render bounded prompt context only if the selected useful entries fit the
   existing prompt-context budget.

Source-size pressure is no longer an automatic prepared-package resolver veto.
The translation-runner preflight records source block/character pressure as
metadata, but can still render glossary context when useful entries and bounded
context fit.

## Metadata

`prepared_package_runtime_bridge` metadata remains ordinary-artifact safe:

- `metadata_only: true`
- `raw_payload_included: false`
- entry/applicability counts
- target-metadata missing count
- source ref absent/match/mismatch counts
- canonical/safe-alias/risky-alias-only counts
- `prepared_package_runtime_bridge_risky_alias_only` reason code when a
  risky alias-only match was skipped
- flags indicating that refs are diagnostic and source presence is primary

It must not include raw source text, prompt bodies, provider responses,
translated text, API keys or auth material.

`battle_test_preflight` now records:

- `source_block_limit_exceeded`
- `source_character_limit_exceeded`
- `source_size_gate_status`
- `source_size_gate_reason_codes`

Those fields are metadata-only and do not by themselves trigger cache bypass.

## Cache

#465 remains unchanged:

- glossary-injected units bypass cache only when glossary context actually
  renders;
- fallback/no-context units keep `default_runtime_cache`;
- no glossary-aware cache reuse is approved.

## Verification

Focused tests cover:

- source present with ref mismatch still renders and exposes ref-mismatch
  diagnostics;
- source absent fallback;
- target metadata missing fallback;
- risky alias-only fallback;
- oversized source with small applicable context can render;
- context over-budget fallback;
- worker-level policy-attached prepared package with ref mismatch reaches the
  provider prompt path and uses cache bypass only when context renders;
- ordinary event/archive metadata stays redacted.

## Unknown / TBD

- Real provider behavior after this fix remains `Unknown` until #675.
- Real translation quality impact remains `Unknown`.
- Final package cap defaults remain `TBD` for #674.
- Broader release/privacy/legal/support readiness remains `TBD`.
