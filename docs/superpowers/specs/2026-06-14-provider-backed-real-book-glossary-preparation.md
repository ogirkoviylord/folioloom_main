# Provider-Backed Real-Book Glossary Preparation Design

Status: no-code architecture review for GitHub issue #560.
Date: 2026-06-14.
Parent: #473 / #555.

Scope: design only. No implementation, no live provider calls, no provider
configuration changes, no DB/schema/state/storage/admin/retention/export/delete
implementation, no runtime rollout, no glossary-aware cache reuse and no
release/privacy/legal/support claims.

## Routing Receipt

- Classification: risky task / docs-only architecture review.
- Risk level: high, because provider-backed glossary preparation touches
  user-document excerpts, provider prompts, target-language terminology,
  runtime prompt inputs, diagnostics and future storage/retention policy.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` and `pr-review`.
- Approval status: owner approval for no-code #560 is recorded in GitHub issue
  comments. Provider calls, storage/state implementation and rollout remain
  `TBD` and require separate approval.
- Allowed action: no-code design and docs sync only.
- Verification plan: docs review against `AGENTS.md`,
  `docs/QUALITY_GATES.md`, glossary/editor readiness gates, runtime rollout
  gates, `git diff --check` and repo-level `pr-review`.

## Verdict

SAFE for no-code design.

NEEDS SPLIT before implementation:

1. fake/dry provider-preparation harness and validator;
2. bounded live provider-preparation spike;
3. persistence/retention decision, if any durable metadata is needed;
4. resolver integration using prepared metadata;
5. rollout decision after paired provider evidence and owner QA.

NEEDS HUMAN APPROVAL before any provider call, raw capture, durable storage,
admin/export/delete behavior, cache-key behavior, rollout or public claim.

REJECT FOR NOW for local semantic inference of target names, gender, identity,
literary role or morphology correctness.

## Why This Stage Exists

The #556 overlay and #557 resolver can inject glossary context only when target
metadata already exists. Arbitrary books do not have approved target metadata.
Local scanner/reducer logic can find source candidates and evidence anchors,
but it must not invent target-language forms or semantic facts. A provider-backed
preparation stage is therefore the future boundary that can propose target
metadata, while local code validates structure, evidence links, budgets and
review flags only.

Confirmed facts:

- #556 provides a compact target-metadata overlay contract.
- #557 can turn approved target metadata into runtime hook data.
- #558 proves local fake `with_glossary` injection and archive evidence.

Unknown:

- provider quality for arbitrary real-book target metadata;
- cost/latency for full-book preparation;
- retention/export/delete requirements for prepared metadata.

## Preparation State Machine

| State | Entry condition | Exit condition | Notes |
| --- | --- | --- | --- |
| `not_requested` | Default or `without_glossary` job | Existing translation path | No glossary preparation. |
| `requested_pending_approval` | User/owner selected `with_glossary`, but provider prep is not approved | fallback / wait | Future UX/owner policy is `TBD`. |
| `local_candidates_ready` | Upload/rights/estimate/Continue gates passed and local scanner/reducer selected bounded candidates | fake/dry packet ready | Metadata-only candidate list; no target facts. |
| `fake_dry_preflight_ready` | Provider packet validates locally with bounded excerpts and output schema | live approval packet | No provider call. |
| `provider_preparation_running` | Fresh owner approval includes inputs, caps, model/provider, raw boundary | provider output received or failure | Bounded calls only. |
| `provider_output_validating` | Provider output captured in owner-only diagnostics | accepted / needs_review / failed | Local validators check schema/evidence/caps, not semantic truth. |
| `prepared_metadata_ready` | Required entries have target metadata and pass readiness gates | feeds #556/#557 shape | Runtime injection may proceed only on explicit owner/test path. |
| `prepared_metadata_needs_review` | Output has low confidence, conflicts or missing metadata | fallback or owner review | No positive quality claim. |
| `preparation_failed` | Timeout, invalid JSON, over-budget, missing evidence or unsafe fields | existing non-glossary path | Metadata-only reason codes. |

Placement:

- After upload safety, rights confirmation, estimate and explicit Continue.
- Before provider translation calls for work units that requested
  `with_glossary`.
- After adapter planning/local candidate reduction, because provider prep must
  receive bounded candidate packets, not raw full books.
- Before #557 runtime resolver, because the resolver needs target metadata.

## Inputs

Allowed provider-preparation inputs:

- source language and target language;
- document kind and adapter/version metadata;
- bounded selected source candidates from scanner/reducer;
- evidence ids, source block ids, unit sequence and compact occurrence counts;
- bounded source excerpts only inside an approved owner-only diagnostic/run
  boundary and only when the future issue explicitly approves raw capture;
- book profile and language-policy package ids/versions;
- glossary role/output schema version and validation thresholds;
- token/call/cost caps from the approval packet.

Not allowed in ordinary artifacts:

- raw source passages;
- prompt bodies;
- provider responses;
- translated text;
- API keys, Authorization headers, tokens, passwords, DSNs or real `.env*`
  values.

## Provider Role Output Contract

Future provider output should be validated as a versioned JSON object:

- `schema_version`;
- `provider_role_id`;
- `source_language`;
- `target_language`;
- `entries[]`;
- per entry: source entry id, source canonical, aliases, evidence refs,
  target canonical, target variants, forbidden variants, strategy, confidence,
  needs-review flag, issue codes and optional compact policy metadata;
- no raw source excerpts in accepted ordinary payloads;
- no provider prompt/response bodies in ordinary payloads;
- no secrets/auth material anywhere.

Local validation may verify:

- JSON/schema validity;
- enum values;
- evidence-ref existence;
- duplicate/conflict structure;
- confidence range and `needs_review`;
- target metadata presence/completeness;
- budget/count caps;
- raw/secret field absence.

Local validation must not claim to prove:

- gender/name identity;
- literary role correctness;
- target-language morphology correctness;
- final translation quality.

## Readiness Gates

Provider-prepared metadata may feed #556/#557 only when all gates pass:

- local candidate packet is bounded and deterministic;
- fake/dry preflight passes;
- live run, if any, stays within approved call/token caps;
- every response validates structurally;
- evidence refs point to selected source candidates;
- required target metadata exists for selected entries;
- conflict/duplicate rules are resolved or marked `needs_review`;
- low-confidence entries are excluded from READY runtime prompt context unless
  a future owner-approved policy says otherwise;
- prepared metadata serializes to the #556 compact overlay shape or successor
  contract;
- #557 resolver still performs source term/alias presence and prompt-context
  budget checks per work unit;
- #465 cache bypass remains active for glossary-injected enabled/test-path
  units.

## Fallback Matrix

| Condition | Runtime behavior | Reason code |
| --- | --- | --- |
| Preparation not approved | Existing non-glossary path | `glossary_preparation_not_approved` |
| Fake/dry preflight fails | Existing non-glossary path | `glossary_preparation_preflight_failed` |
| Provider call over cap or unavailable | Existing non-glossary path | `glossary_preparation_provider_failed` |
| Invalid JSON/schema | Existing non-glossary path | `glossary_preparation_output_invalid` |
| Missing evidence refs | Existing non-glossary path | `glossary_preparation_evidence_missing` |
| Missing target metadata | Existing non-glossary path | `glossary_preparation_target_missing` |
| Needs review / low confidence | Existing non-glossary path or owner review | `glossary_preparation_needs_review` |
| Prompt context over budget | Existing non-glossary path | `glossary_context_over_budget` |
| Diagnostics boundary unavailable | Metadata-only fallback | `diagnostics_boundary_unavailable` |

Fallback must not produce a positive glossary-quality signal.

## Privacy, Storage And Retention

Ephemeral by default:

- raw candidate packets, prompts and provider responses should live only in the
  approved owner-only untracked diagnostics directory for the bounded issue.

Durable storage is `TBD`:

- DB schema/state for prepared metadata;
- retention/export/delete policy;
- admin visibility;
- user consent and support/legal/privacy copy;
- replay/rebuild policy when provider/model/policy versions change.

No release-version privacy/retention/delete/support/legal readiness is claimed.

## Cache Boundary

#465 remains unchanged:

- glossary-injected enabled/test-path units bypass cache get and cache put;
- prepared glossary/profile/snapshot/selection/provider signatures may be
  emitted as metadata only;
- glossary-aware cache reuse requires a separate approved cache-key issue after
  provider evidence and disabled-adapter tests.

## Future Approval Packet

A future fake/dry/live implementation issue must include:

- approved inputs and rights/permissive basis;
- target languages;
- provider/model;
- max calls and max tokens;
- max candidate count and max excerpt size;
- raw capture policy and diagnostics directory;
- whether raw prompts/provider responses may be stored locally;
- validation thresholds and stop conditions;
- whether any prepared metadata may persist beyond the diagnostics directory;
- metadata-only ordinary report path;
- explicit out-of-scope list: no rollout, no cache reuse, no provider config/key
  changes, no DB/schema/storage/admin/retention implementation unless separately
  approved.

## Recommended Next Split

1. Build fake/dry provider-preparation packet generator and validator.
2. Add a bounded live provider-preparation spike only after fake/dry gates pass
   and fresh approval is posted.
3. Review owner-only raw diagnostics and metadata-only summaries.
4. Decide whether prepared metadata stays ephemeral or needs approved durable
   storage.
5. Only then design runtime rollout or cache-key follow-ups.
