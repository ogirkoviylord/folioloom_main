# Book Glossary Architecture Package

Status: no-code architecture package for GitHub issue #404 / #204A.
Date: 2026-06-12.
Scope: book/manuscript glossary architecture only. No code, no provider calls,
no runtime integration, no persistence/schema/storage changes, no UI, no
release/privacy/legal readiness claim.

## Routing Receipt

- Classification: risky task.
- Risk level: high.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` for this docs package, `pr-review` for the
  final diff review.
- Approval status: approved with evidence for this no-code architecture step by
  the owner request in the current thread and by issue #404. Implementation,
  provider calls, cache/runtime behavior, persistence, diagnostics expansion,
  admin/UI, retention and release/privacy policy changes still require the
  issue-specific gates below.
- Allowed action: analysis and docs-only architecture package.
- Verification plan: docs review, `git diff --check`, and repo-level
  `pr-review` on the final docs diff. Code tests are not required because this
  issue does not change code.

## Verdict

SAFE for this docs-only architecture package.

NEEDS SPLIT for implementation. The glossary system must stay split across
#405-#413 or later focused issues. A single implementation PR would be too
risky because glossary facts can steer an entire book, diagnostics are
user-data-derived, and provider roles can create cost, privacy and fallback
risks.

NEEDS HUMAN APPROVAL before any work that touches provider calls, prompt/runtime
integration, cache behavior, persistence/schema/storage, raw diagnostic
surfaces, admin/UI, user-facing glossary controls, retention/deletion,
deployment, payment, legal/privacy text, or release readiness.

## Confirmed Decisions

- Glossary is the default architecture concept for every book/manuscript run.
  Depth can vary by file size, language pair, quality route, profile confidence
  and available evidence.
- Document/form adaptation is future work. The first architecture target is
  books/manuscripts.
- `book_translation_profile` is a first-class accuracy input, not decorative
  metadata.
- DeepSeek Pro cost is not a blocker for the design direction, but actual
  token use, latency, role failures and provider interactions must be measured
  before runtime integration.
- Local code must not pretend to prove semantic facts such as character gender,
  alias identity, correct transliteration or literary intent. It validates
  structure, evidence references, enum values, confidence bounds, prompt-safety
  flags and deterministic signatures.
- Pre-release diagnostics may be broad and raw only inside approved owner-only
  diagnostic boundaries. Secrets, provider `Authorization` headers, API keys
  and real `.env*` values remain excluded.
- Release-version glossary/profile diagnostics, consent, retention, deletion,
  support and legal/privacy copy remain `TBD`.

## Assumptions

- Existing TXT/DOCX/EPUB extraction and work-unit planning remain the source of
  document locations for the first implementation slices.
- The first local schema can be independent of database/state storage.
- The first provider-backed spike, if later approved, uses bounded fixtures and
  diagnostic storage, not normal runtime translation jobs.

## Unknown / TBD

- `TBD`: exact release-version retention/deletion/consent/support/legal policy
  for glossary/profile diagnostics.
- `TBD`: RU/UK morphology strategy beyond evidence capture, optional fields and
  diagnostics.
- `TBD`: whether mid-run glossary updates are ever allowed. Default v1
  architecture uses one stable `translation_snapshot` per run.
- `TBD`: exact Pro role budgets, quality routes and default caps.
- `TBD`: cache migration/stale-cache behavior once glossary/profile signatures
  affect reuse.
- `Unknown`: live provider validity, cost, latency and quality impact until an
  approved #413-style spike exists.

## Layer Model

### Hard Layer

Purpose: strict constraints that protect correctness and safety.

Examples:
- URLs, placeholders, protected markers, file paths, code/API identifiers.
- Official/legal names and owner-pinned glossary forms.
- Terms that must not be translated or must preserve an exact target form.

Behavior:
- Eligible for prompt injection when relevant.
- Eligible for strict post-translation checks.
- Must carry evidence or owner pin metadata.
- Can block or downgrade a snapshot if invalid.

### Soft Layer

Purpose: consistency guidance for literary/editorial choices without flattening
intentional variation.

Examples:
- People, aliases, titles, invented terms, forms of address, register hints,
  contextual variants and profile-specific strategies.

Behavior:
- Included only when relevant and within budget.
- Produces consistency warnings rather than automatic hard failures unless
  promoted by owner pin or strong local rule.
- Keeps confidence, uncertainty and evidence references visible.

### Diagnostic Layer

Purpose: make uncertainty, conflicts, rejected candidates and QA findings
reviewable.

Examples:
- Ambiguous aliases, low-confidence gender hints, rejected candidates, model
  disagreements, prompt-injection-like glossary text, dropped entries, profile
  conflicts and post-translation drift findings.

Behavior:
- Not injected into normal translation prompts by default.
- May be stored in owner-only diagnostic sidecars when approved.
- Must not leak into ordinary logs, telemetry, GitHub issues, PR descriptions,
  support artifacts or release evidence.

## End-To-End Role Graph

The arrows below define data flow. Roles may be implemented over multiple
issues, but they must not mutate each other implicitly.

```text
format_adapter_blocks
  -> deterministic_candidate_scanner
  -> evidence_packet_builder
  -> book_translation_profile_detector
  -> pro_book_profile_advisor (optional/gated)
  -> profile_specific_glossary_rule_builder
  -> pro_glossary_editor_normalizer
  -> pro_entity_resolution_adjudicator (optional/gated)
  -> glossary_contract_validator
  -> contradiction_and_disagreement_checker
  -> translation_strategy_memo_builder
  -> prompt_policy_reviewer
  -> translation_snapshot_builder
  -> per_work_unit_glossary_selector
  -> cache_policy_signature_builder
  -> translation_prompt_integration (future, gated)
  -> post_translation_glossary_qa (future, diagnostics-first)
  -> repair_planner_or_next_revision_candidate (future, gated)
```

Diagnostics are side-channel outputs from every role:

```text
role inputs/outputs/errors
  -> glossary_profile_diagnostics_sidecar
  -> owner-only diagnostic surfaces / downloads only when approved
```

## Role Contracts

### `format_adapter_blocks`

- Type: existing local foundation.
- Inputs: authorized TXT/DOCX/EPUB source processed through existing adapter
  contracts.
- Outputs: block ids, text, kind, group/file metadata, work-unit sequence and
  safe document structure metadata.
- May affect `translation_snapshot`: indirectly, as source locations and block
  ids for evidence.
- Boundary: no new format support in #404-#413.

### `deterministic_candidate_scanner`

- Type: local deterministic role.
- First issue: #406.
- Inputs: adapter blocks, language hints, existing safe text analysis helpers.
- Outputs: candidate ids, candidate category guesses, occurrence counts,
  bounded context references, uncertainty flags and rejected/noise candidates.
- May affect `translation_snapshot`: no direct effect. It provides candidate
  evidence.
- Validation: deterministic ordering, bounded evidence windows, no semantic
  certainty claims.
- Failure fallback: empty or degraded candidate set with `Unknown`/diagnostic
  status, not a fabricated glossary.

### `evidence_packet_builder`

- Type: local deterministic role.
- First issue: #406.
- Inputs: scanner candidates, adapter block ids, work-unit sequence, section
  hints and occurrence metadata.
- Outputs: compact evidence packet ids and metadata-only location references.
- May affect `translation_snapshot`: indirectly through validated evidence
  references.
- Validation: evidence ids must be resolvable; raw excerpts are excluded from
  compact packets unless an approved owner-only diagnostic artifact needs them.
- Failure fallback: candidate is downgraded or rejected when required evidence
  is missing.

### `book_translation_profile_detector`

- Type: local deterministic role first; Pro-assisted role later only if
  approved.
- First issue: #407.
- Inputs: document metadata, candidate categories, headings, dialogue density,
  domain markers, source/target language, translation mode and evidence refs.
- Outputs: `book_translation_profile` with primary/secondary profile,
  fictionality, register, domain hints, terminology strictness, paraphrase
  allowance, named-entity policy, confidence and mixed-section overrides.
- May affect `translation_snapshot`: yes, after validation.
- Validation: enum values, confidence range and evidence refs only. Profile
  correctness remains model/evidence/owner judgment.
- Failure fallback: `primary_profile="unknown"` or `mixed` with conservative
  glossary rules and low-confidence diagnostic notes.

### `profile_specific_glossary_rule_builder`

- Type: local deterministic data role.
- First issue: #407.
- Inputs: validated profile, glossary categories and target-language policy.
- Outputs: rule ids for profile-specific strategy, strictness, allowed variants,
  forbidden variants and fallback strategy.
- May affect `translation_snapshot`: yes, as selected rule ids.
- Validation: rules are data with ids and scopes, not ad hoc prompt prose.
- Failure fallback: no profile-specific override; use base glossary rules.

### `pro_book_profile_advisor`

- Type: DeepSeek Pro role, fake-output validation first.
- First validation issue: #408. First live spike, if approved: #413.
- Inputs: bounded evidence packets, profile detector output, selected samples
  only when approved.
- Outputs: profile advice, low-confidence warnings and mixed-section notes.
- May affect `translation_snapshot`: only after local validation and explicit
  promotion by the snapshot builder.
- Validation: schema, enums, confidence, evidence ids, unsafe-output checks.
- Failure fallback: local profile detector output remains authoritative for v1;
  Pro advice is diagnostic-only.

### `pro_glossary_editor_normalizer`

- Type: DeepSeek Pro role, fake-output validation first.
- First validation issue: #408. First live spike, if approved: #413.
- Inputs: bounded candidate/evidence packets, validated profile context,
  target language and glossary schema version.
- Outputs: normalized entries, aliases, target strategy, variants, rejected
  candidates, confidence and evidence references.
- May affect `translation_snapshot`: yes, after local validation.
- Validation: no unsupported entries, no missing evidence refs, no invalid
  enums, no overlarge payloads, no unsafe candidate-as-instruction behavior.
- Failure fallback: deterministic-only glossary or degraded/diagnostic
  snapshot. Invalid Pro output is not hand-corrected into success.

### `pro_entity_resolution_adjudicator`

- Type: DeepSeek Pro role, optional/future unless #408/#413 include it.
- Inputs: candidate clusters, possible aliases, do-not-merge evidence and
  profile context.
- Outputs: same/different/unknown relationship proposals with evidence refs.
- May affect `translation_snapshot`: only soft/diagnostic by default.
- Validation: relationship enum, evidence refs, confidence and no unsupported
  hard promotion.
- Failure fallback: keep candidates separate or mark `possibly_same_as` as
  diagnostic.

### `contradiction_and_disagreement_checker`

- Type: local deterministic checker with optional DeepSeek Pro help.
- First validation issue: #408.
- Inputs: normalized glossary, profile rules, hard/soft/diagnostic layers and
  role outputs.
- Outputs: contradiction findings, disagreement groups and downgrade requests.
- May affect `translation_snapshot`: yes, by blocking hard promotion or
  downgrading to soft/diagnostic.
- Validation: structured findings with role ids, entry ids and evidence refs.
- Failure fallback: local deterministic contradiction checks remain active;
  unresolved disagreement becomes diagnostic and cannot become hard truth.

### `translation_strategy_memo_builder`

- Type: local deterministic summary first; optional Pro-assisted role later.
- Inputs: validated profile, glossary summary, risk findings and strategy
  rules.
- Outputs: compact internal strategy memo id and structured policy fields for
  tone, precision, terminology, quote/citation handling and style risks.
- May affect `translation_snapshot`: yes, as versioned policy metadata.
- Validation: must be structured and bounded; not a free-form prompt blob.
- Failure fallback: omit memo and use base translation policy.

### `prompt_policy_reviewer`

- Type: deterministic first; optional Pro role later.
- Inputs: planned prompt policy, selected hard/soft rules, profile rules,
  glossary subset and safety instructions.
- Outputs: prompt-bloat warnings, hard/soft confusion findings, unsafe
  document-instruction findings and block/downgrade recommendations.
- May affect `translation_snapshot`: yes, by blocking unsafe prompt bundle or
  forcing simpler policy.
- Validation: findings reference rule ids and prompt sections, not raw text in
  ordinary logs.
- Failure fallback: use simpler prompt bundle or block the high-quality route,
  depending on severity.

### `glossary_contract_validator`

- Type: local deterministic role.
- First issue: #405.
- Inputs: candidate, normalized, rejected and diagnostic glossary data.
- Outputs: accepted/downgraded/rejected entries plus structured validation
  errors.
- May affect `translation_snapshot`: yes.
- Validation responsibilities: schema, required fields, enum vocabulary,
  confidence bounds, evidence refs, duplicate ids, layer/status compatibility,
  prompt-safety flags and deterministic compact signatures.
- Explicit non-responsibility: proving gender, identity, transliteration or
  profile truth.
- Failure fallback: reject invalid entries, downgrade uncertain entries, keep
  validation errors in diagnostics.

### `translation_snapshot_builder`

- Type: local deterministic role.
- First issue: #409.
- Inputs: validated glossary signature, profile signature, selected rule ids,
  provider/prompt policy ids, uncertainty markers and diagnostic policy id.
- Outputs: compact `translation_snapshot` used by the run.
- May affect `translation_snapshot`: this role creates it.
- Validation: deterministic serialization, no raw source text by default,
  explicit schema/profile/prompt/provider/diagnostic policy versions.
- Failure fallback: no stable snapshot means no prompt integration or cache
  integration for glossary/profile data.

### `per_work_unit_glossary_selector`

- Type: local deterministic role.
- First issue: #410.
- Inputs: work-unit anchors/text references, validated global glossary, hard
  constraints, profile rules and budget limits.
- Outputs: selected entry ids, dropped entry ids with reasons, compact prompt
  payload metadata and selection signature.
- May affect `translation_snapshot`: no global mutation; it creates a
  per-work-unit selection derived from the snapshot.
- Validation: prompt budget caps, deterministic ordering, hard-first behavior,
  no unbounded raw text in selection metadata.
- Failure fallback: include hard entries only, or no glossary soft hints, with
  diagnostic reason.

### `cache_policy_signature_builder`

- Type: local deterministic role.
- First issue: #411 after explicit approval.
- Inputs: translation policy, profile signature, glossary signature, selected
  rule ids, selection signature and prompt-contract version.
- Outputs: deterministic cache/policy signatures.
- May affect `translation_snapshot`: no. It consumes stable snapshot data.
- Validation: signatures vary with glossary/profile/selection changes, stay
  stable across ordering-only noise and omit raw source text.
- Failure fallback: treat cache reuse as unsafe or `TBD`; do not mutate/delete
  existing runtime data.

### `translation_prompt_integration`

- Type: future gated runtime role.
- First issue: not #404-#413 unless a later issue explicitly approves prompt
  integration.
- Inputs: stable `translation_snapshot`, per-work-unit selected glossary ids,
  profile rules, prompt policy version and safety instructions.
- Outputs: bounded provider prompt sections or prompt-policy data for a work
  unit.
- May affect `translation_snapshot`: no, but it can affect translation output.
- Validation: must use only stable snapshot data, selected entries and
  prompt-safe fields; must preserve hard/soft/diagnostic distinction.
- Boundary: no live prompt/runtime integration is approved by #404, #405,
  #406, #407, #408, #409 or #410.
- Failure fallback: no glossary prompt injection; diagnostics record why the
  glossary was not injected.

### `post_translation_glossary_qa`

- Type: local diagnostics-first role, future implementation after #410.
- Inputs: translation output, selected glossary subset, hard/soft rules and
  work-unit metadata.
- Outputs: drift findings, hard violations, soft warnings, gender/formality
  warnings and preserved-identifier checks.
- May affect `translation_snapshot`: no for v1. Findings feed diagnostics or a
  next revision candidate.
- Validation: findings are metadata/ids by default. Raw excerpts stay in
  owner-only diagnostics only if approved.
- Failure fallback: QA unavailable means no automatic repair claim.

### `pro_post_translation_qa_judge`

- Type: optional DeepSeek Pro role, future/live only after approval.
- Inputs: sampled or flagged output and bounded evidence selected by local QA.
- Outputs: structured QA judgments, confidence and repair hints.
- May affect `translation_snapshot`: no for the active run by default.
- Validation: fake-output validators first, then approved bounded spike.
- Failure fallback: local QA findings remain; no automatic repair.

### `repair_planner_or_next_revision_candidate`

- Type: future role, local or Pro-assisted.
- Inputs: QA findings, disagreements, owner marks and snapshot metadata.
- Outputs: next-revision proposal or repair plan.
- May affect `translation_snapshot`: not the active snapshot unless a future
  issue explicitly approves repair workflow/versioning.
- Validation: repair plans are proposals with evidence, not silent mutation.
- Failure fallback: record diagnostics only.

### `glossary_profile_diagnostics_sidecar`

- Type: owner-only diagnostic boundary.
- First design issue: #412.
- Inputs: role inputs/outputs/errors, candidates, evidence, validation errors,
  selected/dropped entries, profile decisions, provider metadata and QA
  findings.
- Outputs: dedicated sidecar schema with raw-capable fields explicitly marked.
- May affect `translation_snapshot`: no.
- Boundary: ordinary logs, telemetry, JSON APIs, support notes, GitHub issues,
  PR descriptions and release artifacts remain redacted/metadata-only.
- Failure fallback: if the owner-only boundary is not approved, diagnostics stay
  compact/reference-only and raw fields remain absent.

## Compact Schema Sketches

These are contract sketches for implementation issues. #405 should encode the
local data model and validators more precisely.

### `GlossaryEntry`

Required:
- `entry_id`
- `schema_version`
- `category`
- `layer`: `hard`, `soft` or `diagnostic`
- `review_status`
- `source_canonical`
- `evidence_refs`
- `confidence`

Optional:
- `aliases`
- `target_canonical`
- `target_variants`
- `forbidden_variants`
- `discouraged_variants`
- `strategy`
- `profile_specific_rules`
- `scope`
- `relationships`
- `grammatical_gender`
- `animacy`
- `formality`
- `morphology_notes`
- `uncertainty_notes`
- `prompt_safety_flags`

Validation:
- Enum values must be known.
- `confidence` is bounded, for example 0.0 through 1.0.
- Required evidence refs must resolve.
- Hard entries require strong local evidence or owner pin metadata.
- `Unknown` is a valid value where evidence is missing.
- Morphology fields do not imply local semantic proof.

### `EvidenceRef`

Required:
- `evidence_id`
- `evidence_type`
- `source_scope`
- `unit_sequence`
- `source_block_id`

Optional:
- `chapter_or_section_hint`
- `surface`: `body`, `nav`, `toc`, `metadata`, `footnote`, `heading`, `unknown`
- `offset_bucket`: `early`, `middle`, `late`, `unknown`
- `occurrence_count`
- `confidence_reason_code`
- `raw_excerpt_ref`

Validation:
- Compact evidence refs are metadata-only by default.
- `raw_excerpt_ref` is allowed only for approved owner-only diagnostics.
- Missing evidence downgrades or rejects the dependent claim.

### `BookTranslationProfile`

Required:
- `profile_schema_version`
- `primary_profile`
- `source_language`
- `target_language`
- `confidence`
- `evidence_refs`

Optional:
- `secondary_profiles`
- `fictionality`
- `register`
- `domain_hints`
- `dialogue_density`
- `terminology_strictness`
- `paraphrase_allowed`
- `named_entity_policy`
- `mixed_section_overrides`
- `profile_specific_rule_ids`
- `unknown_fields`

Validation:
- Weak evidence uses `unknown`, `mixed` or low confidence.
- Profile-specific rules are data records with ids and scopes.
- Profile correctness is not locally proven.

### `RoleOutputEnvelope`

Required:
- `role_id`
- `role_version`
- `input_snapshot_ids`
- `output_schema_version`
- `status`
- `diagnostics_ref`

Optional:
- `provider_model`
- `provider_params_signature`
- `latency_ms`
- `prompt_tokens`
- `completion_tokens`
- `validation_errors`
- `disagreement_refs`
- `fallback_used`

Validation:
- Provider outputs are untrusted until local validators accept them.
- `status` must distinguish accepted, low-confidence, diagnostic-only,
  downgraded, rejected and failed states.

### `TranslationSnapshot`

Required:
- `snapshot_id`
- `snapshot_schema_version`
- `translation_mode`
- `source_language`
- `target_language`
- `glossary_schema_version`
- `glossary_signature`
- `profile_schema_version`
- `profile_signature`
- `selected_rule_ids`
- `prompt_policy_version`
- `diagnostics_policy_id`
- `uncertainty_markers`

Optional:
- `provider_policy_signature`
- `pro_role_policy_signature`
- `selection_policy_version`
- `quality_route`
- `cache_policy_signature`
- `raw_diagnostic_sidecar_ref`

Validation:
- Deterministic serialization is required.
- Compact snapshot excludes raw source text by default.
- Snapshot is not a public artifact, support artifact or release evidence.

### `DiagnosticsSidecar`

Required:
- `sidecar_schema_version`
- `run_or_fixture_ref`
- `access_boundary`
- `raw_text_field_manifest`
- `role_trace_refs`
- `validation_summary`

Optional:
- `candidate_records`
- `evidence_packets`
- `role_outputs`
- `selected_and_dropped_entries`
- `profile_decisions`
- `prompt_budget_reasons`
- `provider_io_refs`
- `qa_findings`
- `owner_review_marks`

Validation:
- Raw-capable fields are labeled explicitly.
- Secrets and provider auth material are forbidden.
- Retention/deletion/export policy remains `TBD` unless separately approved.

## Failure Modes And Fallbacks

| Failure | Required behavior |
| --- | --- |
| Invalid JSON from a Pro role | Reject as structured failure, keep raw output only in approved owner-only diagnostics, do not accept manually as success. |
| Missing or unknown enum value | Reject or downgrade affected entry/profile/role output. |
| Missing evidence reference | Reject hard claim; downgrade soft claim to diagnostic. |
| Contradictory evidence | Create disagreement finding; prevent promotion to `hard` unless owner pin or strong local rule resolves it. |
| Pro roles disagree | Record `role_disagreement`; downgrade to soft/diagnostic or keep previous stable snapshot. |
| Low profile confidence | Use `unknown` or `mixed`; apply conservative profile-specific rules and record uncertainty. |
| Glossary too large for budget | Include relevant hard entries first; select soft entries deterministically; drop diagnostic entries from prompt payload; record dropped ids/reasons. |
| Prompt-injection-like candidate text | Mark as diagnostic-only or redacted-for-prompt; never inject as ordinary instruction text. |
| Provider unavailable during a future Pro role | Optional roles degrade to diagnostics; required pre-run role blocks the selected quality route or falls back to deterministic-only route if approved. |
| Snapshot cannot be built deterministically | Do not integrate glossary/profile into prompts/cache; surface validation failure. |
| Cache signature missing glossary/profile inputs | Treat cache reuse as unsafe; migration/stale-cache policy remains `TBD`. |
| Diagnostics boundary unavailable or unapproved | Produce compact metadata-only diagnostics; raw fields remain absent. |
| RU/UK morphology is uncertain | Preserve `Unknown`, confidence and review flags; do not invent deterministic morphology proof. |

## Snapshot Boundary

- The active run uses one stable `translation_snapshot` by default.
- `translation_snapshot` contains compact contract data: glossary/profile
  signatures, schema versions, selected rule ids, prompt/provider policy ids,
  uncertainty markers and diagnostics policy id.
- Compact snapshots exclude raw source text by default.
- Preview may use a smaller preview snapshot; full translation may use a fuller
  snapshot. This distinction must be explicit in signatures and diagnostics.
- Resume/retry should reuse the same snapshot unless a future approved issue
  defines a new translation policy version.
- Mid-run mutation is not allowed in v1. If later approved, it needs versioning,
  affected-unit tracking, cache invalidation, restart/resume rules and
  diagnostics.
- Snapshot persistence/storage/schema is not approved by #404. #409 may build a
  local snapshot object without persistence/schema changes.

## Diagnostics Boundary

- Dedicated owner-only diagnostics may be comprehensive during pre-release
  development.
- Ordinary logs, telemetry, API responses, GitHub issues, PR descriptions,
  support notes and release evidence remain redacted/metadata-only.
- Raw source text, translated text, prompt bodies, provider request/response
  bodies, glossary notes and evidence snippets are sensitive user-data-derived
  diagnostics.
- Diagnostics must exclude secrets, provider `Authorization` headers, API keys,
  plaintext provider keys, tokens, passwords, DSNs and real `.env*` values.
- Diagnostic sidecars must label raw-capable fields explicitly.
- Release-version diagnostics, consent, retention, deletion, support and
  legal/privacy copy remain `TBD` and require Release Readiness review before
  launch claims.

## Provider Boundary

- #404 approves no provider calls.
- #408 may validate fake DeepSeek Pro role JSON only.
- #413 may run live provider calls only after #405-#408 and #412 are complete
  and the owner approves exact fixtures, max calls/tokens, provider/model,
  diagnostic storage location and raw-text capture policy.
- DeepSeek Pro role output is untrusted model output until local validators
  accept, reject or downgrade it.
- Provider/model parameters that affect glossary/profile decisions must be
  included in signatures before runtime use.
- Provider details remain internal. No user-facing provider/model picker is
  introduced by this architecture.

## Approval Gates By Issue

| Issue | Gate |
| --- | --- |
| #405 | May implement local schemas/validators/signatures after #404 is accepted. No provider, prompt, storage, runtime or raw diagnostics. |
| #406 | May implement deterministic scanner on synthetic/authorized fixtures. No real user files, runtime integration, provider calls or retention/logging changes. |
| #407 | May implement local profile detector/rule contract. No prompt/runtime/cache behavior. |
| #408 | May implement fake-output JSON validators. No live provider calls, prompt changes, runtime provider changes or diagnostic retention changes. |
| #409 | May implement local snapshot builder. No cache behavior, provider calls, persistence/schema/work-unit state changes or raw diagnostics. |
| #410 | May implement per-work-unit selector with budget tests. No live prompt/runtime integration or raw log expansion. |
| #411 | Must pause for explicit owner approval. Even signatures-only work affects cache/policy behavior. No runtime data mutation or deletion. |
| #412 | Design-only unless explicit implementation approval exists. Implementation would affect user-data/raw diagnostic/admin boundaries. |
| #413 | Must not start until #405-#408 and #412 are complete, plus exact owner approval for fixtures, calls/tokens, model/provider, diagnostic storage and raw capture. |

## Required Tests For Future Implementation

- #405: glossary contract validation/signature unit tests plus compileall.
- #406: deterministic scanner fixture tests plus compileall.
- #407: profile/rule contract fixture tests plus compileall.
- #408: fake role JSON validator tests for valid, invalid, contradictory,
  oversized, missing-evidence and unsupported-enum outputs plus compileall.
- #409: snapshot serialization/signature tests proving no raw source text in
  compact snapshots plus compileall.
- #410: prompt-budget selector tests for small, medium, large, no-glossary,
  conflicting and multi-work-unit fixtures plus compileall.
- #411: cache/policy signature tests after approval plus compileall.
- #412: if later implemented, owner-only boundary/redaction tests.
- #413: fake-output dry run before provider calls, then validator-backed spike
  report after exact owner approval.

## Recommended Implementation Plan

1. Treat this #404 package as the architecture boundary for the #405-#413
   sequence.
2. Implement #405 first so every later issue shares the same local vocabulary
   for layers, statuses, evidence refs and compact signatures.
3. Implement #406 and #407 as local fixture prototypes. They may run in either
   order after #405 but must coordinate on evidence/profile refs.
4. Implement #408 fake-output role validators after #405 and after this role
   graph is accepted.
5. Implement #409 snapshot builder after #405/#407 so profile/glossary
   signatures are stable.
6. Implement #410 selector after #405/#406 and before prompt integration.
7. Pause before #411 for explicit approval, then implement signatures only.
8. Complete #412 as design-only unless the owner approves implementation.
9. Start #413 only after the local contracts and diagnostics boundary exist and
   exact provider-spike approval is recorded.

## Suggested Implementer Prompt For #405

Implement GitHub issue #405 only. Use the #404 architecture package as the
contract source. Add local glossary contract dataclasses/enums/validators and
deterministic compact signature helpers. Cover hard, soft and diagnostic
layers; valid/invalid evidence refs; confidence bounds; `Unknown` handling;
schema/status enum rejection; deterministic ordering; and absence of raw source
text in compact signatures. Do not call providers, change prompts, change
runtime translation behavior, change storage/schema/cache/admin/UI, or expand
raw diagnostics/logging. Run focused glossary tests and
`PYTHONPATH=src python3 -m compileall src`.
