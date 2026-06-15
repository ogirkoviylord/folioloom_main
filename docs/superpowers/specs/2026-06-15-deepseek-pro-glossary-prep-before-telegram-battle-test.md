# DeepSeek Pro Glossary Prep Before Telegram Battle-Test

Status: no-code architecture review for GitHub issue #608.
Date: 2026-06-15.
Parent: #473.
Blocks / refines: #607.
Follows: #560, #555, #556, #557, #558, #549.

Scope: architecture only. No code implementation, no live provider calls, no
Telegram runtime operation by Codex, no provider configuration changes, no
database schema changes, no admin/storage/retention/export/delete
implementation, no default rollout, no cache reuse and no release/privacy/legal
claims.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high, because the design touches provider-backed glossary
  preparation, user-document excerpts, runtime prompt inputs, job policy
  metadata, owner-only diagnostics and future Telegram battle-test evidence.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skill: `docs-sync`, because this issue updates active glossary
  contracts and handoff context.
- Approval status: owner approved doing #608 first and clarified that
  `deepseek-v4-pro` is glossary-only. Live provider calls, Telegram operation,
  durable storage/state behavior and rollout remain `TBD` and require separate
  exact approval.
- Allowed action: no-code design and docs sync only.
- Verification plan: docs review against `AGENTS.md`, `docs/QUALITY_GATES.md`,
  `docs/RISK_REGISTER.md`, related glossary specs and `git diff --check`.

## Verdict

SAFE for no-code architecture.

NEEDS SPLIT before implementation:

1. local/fake prepared-glossary package builder and validator;
2. job-scoped compact prepared metadata handoff into the existing resolver
   path, without a DB schema change;
3. owner-only diagnostics/archive evidence for preparation plus injection;
4. bounded live Pro glossary-prep spike only after fake/dry gates pass;
5. owner-assisted #607 Telegram battle-test after #608 implementation evidence.

NEEDS HUMAN APPROVAL before any live Pro call, raw capture, Telegram runtime
operation, provider key/config handling, persistent state/storage changes,
admin/export/retention behavior, rollout or public/release/privacy claim.

REJECT FOR NOW:

- translating whole books with `deepseek-v4-pro` just because glossary mode is
  selected;
- local code inventing target-language facts such as gender, identity,
  morphology or literary role;
- default glossary rollout or glossary-aware cache reuse.

## Confirmed Facts

- #546 added a temporary Telegram selector for `with_glossary` and
  `without_glossary`.
- #549 adds `glossary_runtime_diagnostics.json` to owner-only downloaded
  archives when glossary runtime diagnostic data exists.
- #551 makes scheduled/external worker `with_glossary` jobs either use READY
  hook data or record deterministic metadata-only fallback.
- #555 recorded the real-book resolver gap: the latest real EPUB
  `with_glossary` run had no READY runtime glossary data, so provider prompts
  contained no `<glossary_context>`.
- #556 provides a compact target-metadata overlay contract.
- #557 can produce a `GlossaryRuntimeAdapterHookConfig` for explicit
  owner/test EPUB units when target metadata, source term/alias presence and
  prompt budgets pass.
- #560 designed provider-backed real-book glossary preparation, but did not
  implement it.
- The owner clarified on 2026-06-15 that `deepseek-v4-pro` is used only for
  glossary/profile/preparation/editor roles, not as the main runtime
  translation model.
- Codex is not approved to enter Telegram or control the bot for #607.

## Problem

The real Telegram `with_glossary` mode currently proves selector and fallback
plumbing, not glossary influence. For arbitrary books, the resolver needs
target-backed glossary entries before translation work units are sent to the
runtime provider. Local scanners can find source candidates and evidence, but
local code must not create target-language semantic facts.

Therefore, a Pro-backed preparation stage must produce validated target
metadata before the runtime resolver tries to inject glossary context. The
output of that stage must be compact enough for the worker/resolver and safe
enough for ordinary logs, while raw prompts/responses remain owner-only.

## Model Boundary

- DeepSeek Pro / `deepseek-v4-pro`: glossary/profile/preparation/editor roles
  only.
- Runtime book translation: existing configured runtime provider/model.
- User-facing model picker: not approved.
- Provider configuration/key changes: not approved.
- If Pro preparation is missing, invalid, over budget, unavailable or not
  READY, the job must fall back to the existing non-glossary runtime path and
  record metadata-only reason codes.

## Recommended First Implementation Slice

Choose option 1 plus a narrow part of option 3 from #608:

> Job-scoped compact prepared metadata stored in the existing translation policy
> / planning metadata shape, with raw preparation material confined to an
> owner-only diagnostics directory. No new DB schema.

Why this is the safest real-Telegram slice:

- A pure local diagnostics file is not enough for the persistent worker unless
  the runtime has a safe way to find it.
- A new durable table/schema would create avoidable storage, migration,
  retention and backup risk.
- Existing job policy/planning metadata already carries safe compact fields
  such as `glossary_mode`; adding a compact prepared-package reference/payload
  can be reviewed as a focused no-schema state change.
- Raw candidate excerpts, prompts and provider responses can remain out of
  ordinary job state and live only in owner-only diagnostics.

This is still a high-risk implementation because it changes persistent job
metadata behavior. It needs a separate approved issue before code.

## Placement In The Telegram Flow

Preparation must not happen before the user has passed the normal gates.

Recommended order:

1. Upload validation and upload safety gates pass.
2. User confirms rights/permissive basis.
3. User selects target language.
4. User selects temporary glossary mode.
5. Existing estimate/confirmation flow runs.
6. User explicitly presses Continue.
7. Persistent job and work units are created/planned.
8. If `glossary_mode != with_glossary`, no preparation is attempted.
9. If `glossary_mode == with_glossary`, local candidate/profile/reducer/selector
   planning produces a bounded preparation packet.
10. Fake/dry validation runs locally.
11. If and only if a future exact approval permits it, bounded live Pro
    preparation runs.
12. Provider output is locally validated into compact target metadata.
13. READY compact metadata is attached to the job-scoped policy/planning
    metadata and/or a compact package id that the worker can resolve.
14. Work-unit translation begins with the existing runtime provider/model.
15. #557 resolver injects bounded glossary prompt context only for eligible
    units; other units fall back with metadata-only reasons.

For #607 owner-assisted testing, Codex must not operate Telegram. The owner
runs the two bot jobs manually and provides downloaded archives for review.

## Prepared Package Contract

The compact prepared package should be versioned and metadata-first:

- `schema_version`;
- `package_id`;
- `source_document_fingerprint` or equivalent safe non-raw fingerprint;
- `target_language`;
- `glossary_mode`;
- `provider_role_id`;
- `provider_model` for the glossary-prep role;
- `provider_run_id` or diagnostics directory id;
- `candidate_selector_signature`;
- `language_policy_package_id` and version, if present;
- `entries[]`.

Per entry:

- source entry id;
- source canonical and aliases only if they are already allowed inside the
  existing glossary prompt/diagnostic boundary;
- evidence refs and source unit/block refs, not raw excerpts;
- target canonical;
- target variants;
- forbidden variants;
- strategy / policy metadata;
- confidence;
- `needs_review`;
- issue/reason codes.

Ordinary job metadata must not include:

- raw source passages;
- prompt bodies;
- provider responses;
- translated text;
- API keys, Authorization headers, tokens, passwords, DSNs or real `.env*`
  values.

## Local Validation

Local validators may prove:

- JSON/schema validity;
- enum values and version support;
- evidence-ref existence against selected candidates;
- target-language match;
- entry count and prompt-budget caps;
- confidence range and review flags;
- duplicate/conflict structure;
- raw/secret field absence;
- compatibility with #556 target-metadata overlay shape;
- resolver readiness for #557.

Local validators must not claim to prove:

- target-language grammatical correctness;
- gender/name identity;
- character identity;
- literary role correctness;
- final translation quality.

## State Machine

| State | Meaning | Runtime behavior |
| --- | --- | --- |
| `not_requested` | `without_glossary` or no glossary mode | Existing path. |
| `requested_pending_prep` | `with_glossary` selected after Continue | Do not send glossary context yet. |
| `local_packet_ready` | bounded local prep packet validates | Eligible for approved fake/live prep. |
| `prep_approval_missing` | live Pro prep is not approved | Existing path with metadata reason. |
| `provider_prep_running` | bounded approved Pro prep in progress | No runtime translation call until complete or failed. |
| `provider_prep_failed` | provider timeout, cap breach or unavailable | Existing path with metadata reason. |
| `provider_output_invalid` | JSON/schema/evidence validation failed | Existing path with metadata reason. |
| `prepared_needs_review` | low confidence/conflicts/review flags | Existing path unless future owner policy approves use. |
| `prepared_ready` | compact target metadata passes gates | Resolver may inject per eligible unit. |
| `injection_ready` | per-unit source/alias and budget gates pass | Inject context and bypass cache. |
| `injection_omitted` | per-unit gates fail | Existing path with metadata reason. |

## Fallback Reason Codes

Add or reserve these metadata-only reason codes for future implementation:

- `glossary_preparation_not_requested`;
- `glossary_preparation_approval_missing`;
- `glossary_preparation_packet_invalid`;
- `glossary_preparation_provider_failed`;
- `glossary_preparation_token_cap_exceeded`;
- `glossary_preparation_usage_unknown`;
- `glossary_preparation_output_invalid`;
- `glossary_preparation_evidence_missing`;
- `glossary_preparation_target_missing`;
- `glossary_preparation_needs_review`;
- `glossary_preparation_package_unavailable`;
- `glossary_preparation_package_invalid`;
- `glossary_preparation_ready`;
- `glossary_context_over_budget`;
- `runtime_glossary_data_unavailable`.

Fallback must never be counted as positive glossary-quality evidence.

## Diagnostics Boundary

Owner-only diagnostics may include, only after exact approval:

- bounded source excerpts used for preparation;
- Pro glossary-prep prompts;
- raw Pro provider responses;
- local validation findings;
- compact prepared package;
- rendered runtime `<glossary_context>`;
- links between preparation run id, job id and work-unit ids.

Ordinary logs, telemetry, GitHub issues, PR descriptions, docs, support notes,
release artifacts, normal admin pages and JSON APIs must remain
metadata-only/redacted. Provider auth material must be rejected, not merely
hidden.

Downloaded full diagnostic archives may include a dedicated glossary-prep
section only when the job used `with_glossary` and preparation/injection
diagnostics exist. `without_glossary` archives must omit glossary prep raw
sidecars.

Retention/export/delete policy for release-version glossary diagnostics remains
`TBD`.

## Cache Boundary

#465 remains active:

- glossary-injected enabled/test-path units bypass cache get and put;
- non-glossary and fallback units preserve existing cache behavior;
- prepared glossary/profile/snapshot/selection/provider/policy signatures may
  be emitted as metadata;
- glossary-aware cache reuse requires a separate approved cache-key issue.

## Required Future Approval Packet

A future implementation/live-prep issue must include:

- issue number and scope;
- approved inputs and rights/permissive basis;
- target languages;
- owner-assisted vs Codex-operated boundary; Telegram operation by Codex is not
  approved unless explicitly stated;
- provider/model for glossary prep: DeepSeek-compatible provider /
  `deepseek-v4-pro`;
- confirmation that runtime translation uses the existing configured runtime
  provider/model;
- max Pro prep calls;
- max provider-reported tokens;
- max selected candidates and max excerpt size;
- diagnostics directory;
- raw capture policy for bounded excerpts, prompts and provider responses;
- whether compact prepared metadata may be stored in existing job policy/state;
- stop conditions for invalid JSON, evidence failures, token cap breach, usage
  `Unknown`, timeout or secret-pattern findings;
- out-of-scope list: no default rollout, no cache reuse, no provider config/key
  changes, no DB schema migration, no retention/export/delete implementation,
  no release/privacy/legal/support claims.

## Required Tests For Future Implementation

- Prepared-package schema validation: valid, invalid, unsupported version,
  target mismatch, raw field, secret field, missing evidence, missing target
  metadata and `needs_review`.
- Fake/dry Pro-prep preflight for a bounded authorized fixture.
- Default/`without_glossary` behavior unchanged.
- `with_glossary` fallback when prep package is missing/invalid/not READY.
- `with_glossary` injection only when compact prepared target metadata is READY
  and source term/alias is present in the unit.
- #465 cache bypass only for glossary-injected units.
- Archive diagnostics include prep/injection metadata for `with_glossary` and
  omit it for `without_glossary`.
- Secret-pattern rejection for prep packages and archives.
- `PYTHONPATH=src python3 -m compileall src` for code changes.
- `git diff --check`.
- Repo-level `pr-review` before PR ready/merge.

## Recommended Issue Split

1. Local prepared-package schema/validator and fake fixture tests.
2. No-schema job-scoped prepared-package handoff into existing worker resolver.
3. Owner-only archive diagnostics for preparation plus injection linkage.
4. Fake/dry end-to-end rehearsal: `with_glossary` produces one injected unit,
   `without_glossary` omits glossary, no live calls.
5. Bounded live Pro glossary-prep spike for one approved control book/target.
6. Owner-assisted #607 Telegram on/off battle-test using downloaded archives.

## Suggested Implementer Prompt For First Slice

`[$implementation](/Users/yuriimedvediev/Documents/New project 2/.agents/skills/implementation/SKILL.md) Implement the first #608 child issue only: local-only prepared glossary package schema/validator and fake fixtures. Preserve DeepSeek Pro as glossary-prep only and runtime translation as the configured runtime provider/model. No live provider calls, no Telegram operation, no provider config/key changes, no DB schema/state/storage/admin/retention changes, no rollout, no cache reuse and no release/privacy claims. Reject raw source passages, prompt bodies, provider responses, translated text, API keys/auth material and real .env values from ordinary payloads. Add focused tests for valid/invalid packages, target mismatch, missing evidence, needs_review, raw/secret rejection and #556 overlay compatibility. Run focused tests, compileall, git diff --check, docs-sync if contracts changed, then pr-review.`
