# Real-Book Runtime Glossary Resolver Contract

Status: no-code architecture review for GitHub issue #555.
Date: 2026-06-14.
Parent: #473 / #204AI.

Scope: contract only for turning explicitly selected real-book
`with_glossary` persistent EPUB jobs into per-work-unit glossary runtime
decisions. No code implementation, no live provider calls, no runtime rollout,
no cache reuse, no DB/schema/state/scheduler/work-unit/storage/admin/retention
mutation, no provider config change and no release/privacy/legal/support claim.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high, because this path touches worker/scheduler runtime
  behavior, provider prompts, cache correctness, glossary diagnostics and
  user-document-adjacent metadata.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` for current-state docs and `pr-review` for
  final docs diff review.
- Approval status: #555 does not require implementation approval because it is
  no-code. Issues #556, #557, #558 and #560 have owner approval recorded in
  GitHub comments. #559 has bounded live-provider approval only after #556-#558
  are merged/reviewed and fake/local gates pass.
- Allowed action: no-code contract and metadata-only docs sync.
- Verification plan: docs review against `AGENTS.md`, `docs/QUALITY_GATES.md`,
  `docs/RISK_REGISTER.md` and `docs/DECISIONS.md`, `git diff --check`, and
  repo-level `pr-review`.

## Verdict

SAFE for this no-code contract.

NEEDS SPLIT for implementation. The real-book path must stay split across:

1. approved compact target-metadata overlay contract (#556);
2. worker-side persistent EPUB runtime resolver (#557);
3. fake/local bot-worker rehearsal and archive evidence (#558);
4. bounded live provider battle-test only after prerequisites (#559);
5. provider-backed arbitrary-book glossary preparation design (#560).

NEEDS HUMAN APPROVAL before any runtime code, live provider call,
storage/state/admin/retention change, cache reuse, default rollout or
release/privacy/legal/support claim.

REJECT FOR NOW for normal/default glossary rollout, limited beta rollout,
glossary-aware cache reuse and arbitrary provider-backed glossary preparation
implementation.

## Confirmed Root Cause

The owner-downloaded diagnostic archive for `pg78864-images-3.epub` showed:

- `glossary_mode=with_glossary`;
- 36 glossary adapter events;
- every event had `status=fallback`;
- fallback reason was `runtime_glossary_data_unavailable`;
- `selected_entry_ids=[]`;
- rendered glossary prompt context count was 0;
- provider IO contained no `<glossary_context>`.

Confirmed interpretation: the temporary selector and #551 evidence path worked,
but the real persistent EPUB job had no READY runtime glossary data to resolve
per work unit. This was not proof of glossary quality, because glossary context
was not injected.

## Resolver Boundary

Future implementation should use an adapter-style boundary, referred to here as
`RuntimeGlossaryPlanProvider` without requiring that exact class name.

The boundary answers one question for a claimed persistent work unit:

> Given this job, target language, document kind, work unit and approved compact
> glossary inputs, should this unit receive bounded glossary prompt context, or
> should it fall back to the existing non-glossary path?

Inputs:

- persistent job metadata and translation policy, including `glossary_mode`;
- document kind and target language;
- accepted source object identity or already planned work-unit data;
- claimed `PersistentWorkUnit` sequence/source block ids/source text;
- existing local glossary scanner/profile/reducer/selector results when
  available or safely derived;
- approved compact target metadata from #556, or future prepared metadata from
  a separately approved provider-backed preparation stage;
- prompt-context formatter config and budget limits;
- terminology policy/package metadata where available.

Outputs:

- `None` for disabled or `without_glossary` behavior;
- a READY `GlossaryRuntimeAdapterHookConfig` for eligible units;
- a fallback `GlossaryRuntimeAdapterHookConfig` with metadata-only reason codes
  when glossary context must be omitted.

The resolver must be default-off and owner/test-path only. It must not make
normal/default translation prompts glossary-aware.

## READY Unit Requirements

A work unit may be READY only when all conditions hold:

- the job explicitly selected `with_glossary`;
- the path is owner/test enabled, not default rollout;
- document kind is supported by the approved issue scope;
- local glossary data validates structurally;
- source term or alias is present in the unit;
- selected entry has approved target metadata for the requested target
  language;
- formatter and selection budgets pass;
- terminology policy metadata is valid or safely omitted according to existing
  compact metadata rules;
- owner-only diagnostic boundary is available for raw-capable diagnostic
  material when the run requests raw capture;
- cache behavior preserves #465: glossary-injected units bypass cache get and
  cache put.

READY hook payloads should include compact metadata only in ordinary events:

- status and schema version;
- work-unit sequence and selection signature;
- selected entry ids;
- target metadata counts/signatures;
- formatter/prompt-context contract version;
- budget/count metadata;
- cache policy behavior;
- omission/fallback reasons for entries that were not rendered.

## Target Metadata Sources

Target metadata is required because local code must not invent semantic facts
such as name identity, gender, literary role or correct target-language forms.

Allowed sources:

1. Owner-approved local overlay for battle tests (#556).
   - Compact metadata only.
   - No raw passages, prompt bodies, provider responses, translated text,
     API keys, auth material, real `.env*` values, passwords, tokens or DSNs.
   - Match only onto retained source entries by source term/alias and target
     language.
2. Future provider-backed glossary preparation stage (#560 design, later
   implementation TBD).
   - Requires separate approval for fake/dry/live bounds, provider/model, raw
     diagnostics, validation gates and any storage/state behavior.
3. Existing validated fixture/control metadata from prior approved smoke paths.
   - Scope remains limited to the issue that approved it.

TBD:

- durable storage shape for prepared target metadata;
- retention/export/delete policy for release-version glossary diagnostics;
- whether provider/model identity must become a future cache dimension;
- broad arbitrary-book provider preparation implementation.

Unknown:

- translation-quality benefit for this real EPUB until valid paired outputs are
  produced and reviewed;
- long-run cost/latency for real-book preparation and injection.

## Fallback Matrix

| Condition | Required behavior | Reason code |
| --- | --- | --- |
| No explicit `with_glossary` mode | Use existing path; no glossary hook. | `glossary_runtime_not_selected` |
| Explicit `without_glossary` mode | Block glossary hook even if provided. | `glossary_runtime_disabled_by_mode` |
| Resolver unavailable | Existing #551 fallback hook. | `runtime_glossary_data_unavailable` |
| Unsupported document kind | Omit glossary context. | `document_kind_unsupported` |
| Missing or invalid source glossary data | Omit glossary context. | `source_glossary_unavailable` / `source_glossary_invalid` |
| No retained source candidate for unit | Omit glossary context. | `no_unit_source_match` |
| Missing target metadata | Omit glossary context. | `target_metadata_missing` |
| Target-language mismatch | Omit glossary context. | `target_metadata_language_mismatch` |
| Overlay/provider metadata invalid | Omit glossary context. | `target_metadata_invalid` |
| Formatter or selection over budget | Omit glossary context. | `glossary_context_over_budget` |
| Terminology policy unsupported | Omit policy metadata or fallback. | `terminology_policy_unsupported` |
| Resolver error | Fail closed to existing path and record metadata-only event. | `glossary_resolver_failed` |
| Diagnostics boundary unavailable for raw-capable run | Stop raw capture or fall back to metadata-only. | `diagnostics_boundary_unavailable` |

Fallback must use the existing non-glossary translation/cache path when
glossary prompt context is omitted. It must not create a positive glossary
quality signal.

## Diagnostics Boundary

Ordinary artifacts must remain metadata-only/redacted:

- logs;
- telemetry;
- normal admin pages and APIs;
- Telegram/user surfaces;
- GitHub issues and PR descriptions;
- docs;
- support and release artifacts.

Raw-capable material may appear only inside already approved owner-only
diagnostic boundaries:

- downloaded full diagnostic archive sidecars;
- approved untracked `outputs/issue-.../<timestamp>/` directories for bounded
  smoke runs.

Never include provider Authorization headers, API keys, tokens, passwords,
DSNs, real `.env*` values or other auth material.

## Cache Boundary

#465 remains active:

- glossary-injected enabled/test-path units bypass cache get and put;
- fallback/non-glossary units keep existing cache behavior only when no
  glossary context affects the prompt/output;
- compact signatures may be emitted as metadata but must not enable reuse;
- future glossary-aware cache reuse requires a separate approved issue.

## Provider Boundary

This contract does not approve live provider calls.

Any live provider run requires:

- exact issue approval;
- approved input rights/permissive basis;
- target language(s);
- selection rule;
- max calls and token cap;
- provider/model;
- temporary process-env key/config policy;
- diagnostic storage path;
- raw capture boundary;
- fake/dry preflight first;
- structural validation and glossary compliance summaries;
- metadata-only ordinary report.

#559 currently has such approval only after #556-#558 are merged/reviewed and
fake/local gates pass, for a paired RU on/off run on the approved EPUB input.

## Implementation Sequence

1. #556: local-only target metadata overlay contract and validator.
2. #557: worker-side persistent EPUB resolver that uses the overlay/validated
   metadata and existing formatter/selector/preflight gates.
3. #558: fake/local bot-worker rehearsal proving injection, fallback, cache
   bypass and owner-only archive evidence.
4. #559: bounded live paired RU provider battle-test only after prerequisites.
5. #560: no-code design for provider-backed arbitrary-book preparation.

Subagents may work only on independent lanes. They must not edit the same files
concurrently, and the main agent must coordinate dependency order.

## Required Tests For Future Code Issues

For #556:

- accepted compact metadata;
- raw/secret material rejection;
- source term/alias matching;
- target-language mismatch fallback;
- metadata-only serialization.

For #557:

- default/no-mode unchanged;
- `without_glossary` blocks resolver;
- `with_glossary` READY injected EPUB unit;
- missing/invalid/over-budget fallback;
- cache bypass only for injected units;
- ordinary metadata redaction.

For #558:

- fake/local EPUB bot-worker path reaches injected unit;
- prompt/request body contains `<glossary_context>` only for injected units;
- owner-only archive records selected entries/context/counts/cache behavior;
- fallback and `without_glossary` archive behavior.

All code issues must run focused tests, `PYTHONPATH=src python3 -m compileall
src`, targeted ruff for touched Python files if applicable, `git diff --check`,
docs-sync if contracts/behavior/risks change, and repo-level `pr-review`.

## Non-Goals

- Default glossary rollout.
- Limited beta glossary rollout.
- Glossary-aware cache reuse.
- New provider calls outside #559 or a separately approved issue.
- Provider config/key changes.
- DB/schema/state/storage/admin/retention/export/delete implementation.
- Release/privacy/legal/support claims.
- Local semantic proof of target terms, gender/name identity or literary
  correctness.
