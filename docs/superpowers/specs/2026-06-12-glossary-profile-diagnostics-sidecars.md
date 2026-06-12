# Glossary/Profile Diagnostics Sidecars

Status: design-only architecture package for GitHub issue #412 / #204I.
Date: 2026-06-12.
Scope: owner-only glossary/profile diagnostics sidecar design. No code, no
provider calls, no prompt/runtime integration, no persistence/schema/storage
changes, no admin UI implementation, no retention/TTL changes and no
release/privacy/legal readiness claim.

## Routing Receipt

- Classification: risky task.
- Risk level: high.
- Primary role: Architect Agent.
- Primary repo-level skill: `architecture-review`.
- Supporting skills: `docs-sync` for handoff/roadmap/risk/release pointers and
  `pr-review` for final diff review.
- Approval status: design-only work is allowed by issue #412 and by the
  #404 architecture package. Implementation approval is missing and remains
  required for any code, storage, archive, admin UI, provider, retention or
  release/privacy behavior.
- Allowed action: analysis and docs-only design.
- Verification plan: docs review, `git diff --check`, and repo-level
  `pr-review`. Code tests are not required because this issue changes no code.

## Verdict

SAFE for this docs-only sidecar design.

NEEDS HUMAN APPROVAL before any implementation. A diagnostic sidecar may contain
raw source text, translated text, prompt bodies, provider bodies, model outputs,
glossary notes and owner review marks. That is high-risk user-data and provider
diagnostic scope even when the owner wants broad pre-release diagnostics.

NEEDS SPLIT for implementation. The sidecar should not be implemented together
with provider-backed DeepSeek Pro work, prompt integration, admin UI expansion,
retention changes or public/release privacy copy.

## Confirmed Boundaries

- FolioLoom already has owner-approved raw translation text diagnostics,
  owner-only full diagnostic downloads and run-scoped
  `provider_io_diagnostics.jsonl` for exact provider request/response bodies.
- Ordinary logs, telemetry, normal admin details, JSON APIs, support notes,
  GitHub issues, PR descriptions and release artifacts remain
  metadata-only/redacted.
- Glossary/profile diagnostics are user-data-derived. They may include raw or
  near-raw document content only inside a dedicated owner-only boundary.
- Secrets, provider `Authorization` headers, API keys, plaintext provider keys,
  passwords, tokens, DSNs and real `.env*` values must not appear in any
  diagnostic sidecar.
- Release-version retention, deletion, consent, support, export and
  legal/privacy behavior remains `TBD`.

## Design Goals

- Make glossary/profile failures obvious during pre-release tuning.
- Keep raw and near-raw evidence out of ordinary operational surfaces.
- Preserve enough structure for future validators and review tools to prove
  whether a sidecar is safe to attach to an owner-only archive.
- Let future #413 provider spikes reference diagnostics without changing the
  diagnostics boundary.
- Keep local code from presenting semantic facts such as gender, identity or
  profile truth as locally proven.

## Non-Goals

- No implementation in #412.
- No live provider calls.
- No prompt/runtime/cache integration.
- No database, scheduler, work-unit state, object-storage or retention changes.
- No public/user-facing diagnostics or glossary UI.
- No general log expansion.
- No legal/privacy/release copy.

## Sidecar File Boundary

Future implementation should use a dedicated run-scoped or fixture-scoped file
instead of adding raw fields to existing metadata logs.

Recommended file name:

- `glossary_profile_diagnostics.json`

Allowed future location, if separately approved:

- inside an existing translation run diagnostic directory; or
- inside an approved bounded fixture diagnostic directory for provider spikes.

Disallowed locations:

- `run.json`
- `effective_run.json`
- `work_units.json`
- `events.jsonl`
- `security_telemetry`
- normal admin details or trace JSON/API payloads
- release evidence, support artifacts, GitHub issues or PR descriptions

Owner-only full diagnostic archive inclusion may be allowed later, but the
archive README must label the sidecar as sensitive user-document/provider
diagnostic data. Archive inclusion itself is implementation work and requires
explicit approval.

## Top-Level Schema

Proposed `sidecar_schema_version`: `glossary-profile-diagnostics-sidecar-v1`.

Required top-level fields:

| Field | Class | Notes |
| --- | --- | --- |
| `sidecar_schema_version` | compact | Exact schema id. |
| `diagnostic_scope` | compact | Must be `owner_only_glossary_profile_diagnostics`. |
| `access_boundary` | compact | Explicit owner-only/admin-only constraints. |
| `run_or_fixture_ref` | compact | Run id, job id or fixture id; no raw document text. |
| `created_at` | compact | UTC timestamp. |
| `source_language` | compact | Normalized source language or `Unknown`. |
| `target_language` | compact | Normalized target language or `Unknown`. |
| `translation_mode` | compact | Translation mode or `Unknown`. |
| `translation_snapshot_ref` | compact | Snapshot id/signature when available. |
| `glossary_signature` | compact | Compact glossary snapshot signature or `Unknown`. |
| `profile_signature` | compact | Compact profile signature or `Unknown`. |
| `raw_text_field_manifest` | manifest | Lists every raw-capable path in this sidecar. |
| `secret_exclusion_policy` | compact | Must state forbidden secret/auth material. |
| `retention_policy` | TBD | Must remain `TBD` until a release/privacy task decides it. |
| `export_policy` | TBD | Must remain `TBD` unless owner approves exact export behavior. |
| `deletion_policy` | TBD | Must remain `TBD` unless owner approves exact deletion behavior. |
| `sections` | object | Structured diagnostic sections listed below. |

Optional top-level fields:

- `provider_policy_signature`
- `pro_role_policy_signature`
- `selection_policy_version`
- `quality_route`
- `sidecar_integrity`
- `source_artifact_refs`
- `related_diagnostic_files`

`sidecar_integrity` should include only compact values such as schema id,
section counts, byte counts and hashes. It must not duplicate raw content.

## Access Boundary

Required `access_boundary` fields:

| Field | Required value |
| --- | --- |
| `visibility` | `owner_only` |
| `admin_boundary` | `ssh_tunneled_admin_session_required` |
| `ordinary_logs_allowed` | `false` |
| `telemetry_allowed` | `false` |
| `json_api_allowed` | `false` |
| `support_artifact_allowed` | `false` |
| `release_artifact_allowed` | `false` |
| `github_issue_or_pr_allowed` | `false` |
| `cache_control` | `no-store` if rendered in a future admin page |

If a future implementation cannot prove this boundary for a raw-capable
sidecar, it must write compact/reference-only diagnostics or skip the sidecar.

## Raw Field Manifest

The sidecar must declare every raw-capable field path before the field can be
written. A manifest entry should use this shape:

```json
{
  "path": "sections.candidate_records[].raw_candidate_text",
  "classification": "raw_source_text",
  "required_boundary": "owner_only",
  "source": "deterministic_candidate_scanner",
  "allowed_in_archive": "TBD",
  "redaction": "none_inside_owner_only_sidecar",
  "ordinary_surface_policy": "forbidden"
}
```

Allowed `classification` values:

- `raw_source_text`
- `raw_translated_text`
- `near_raw_candidate_text`
- `prompt_body`
- `provider_request_body`
- `provider_response_body`
- `model_output_body`
- `owner_note`
- `diagnostic_error_detail`

Forbidden in all sidecars:

- provider `Authorization` headers
- API keys
- plaintext provider keys
- passwords
- auth/session tokens
- DSNs
- real `.env*` contents
- unrelated runtime data

## Compact Fields

Compact/reference-only fields may appear in the sidecar and in future
metadata-only summaries, subject to normal review:

- ids and refs: `run_id`, `job_id`, `work_unit_id`, `entry_id`, `evidence_id`,
  `role_id`, `snapshot_id`, `selection_signature`;
- signatures and hashes;
- counts, sizes, elapsed time and token counts;
- enum values and reason codes;
- confidence values and uncertainty markers;
- source block ids, work-unit sequence, surface category and offset buckets;
- validation issue codes and paths;
- provider failure categories and HTTP status buckets;
- `Unknown` when evidence is missing.

Compact fields must not embed raw excerpts, prompt text, provider bodies or
translated text.

## Diagnostic Sections

### `candidate_records`

Purpose: explain what deterministic/local/pro roles considered as glossary
candidates.

Compact fields:

- `candidate_id`
- `entry_id`
- `category`
- `layer`
- `status`
- `confidence`
- `evidence_refs`
- `source_block_ids`
- `first_seen_unit_sequence`
- `last_seen_unit_sequence`
- `occurrence_count`
- `filter_decision`
- `filter_reason`

Raw-capable fields:

- `raw_candidate_text`
- `raw_alias_texts`
- `raw_rejected_candidate_text`

### `evidence_packets`

Purpose: show why candidates/profile decisions exist.

Compact fields:

- `evidence_id`
- `evidence_type`
- `unit_sequence`
- `source_block_id`
- `source_scope`
- `surface`
- `offset_bucket`
- `occurrence_count`
- `confidence_reason_code`

Raw-capable fields:

- `raw_source_excerpt`
- `raw_translated_excerpt`
- `near_raw_context_window`

### `profile_decisions`

Purpose: explain book translation profile detection and profile-specific rules.

Compact fields:

- `profile_id`
- `profile_schema_version`
- `detector_version`
- `primary_profile`
- `secondary_profiles`
- `document_type`
- `fictionality`
- `dialogue_density`
- `register`
- `terminology_strictness`
- `paraphrase_allowance`
- `named_entity_policy`
- `confidence`
- `evidence_refs`
- `uncertainty_notes`
- `selected_rule_ids`

Raw-capable fields:

- `raw_profile_evidence_excerpt`
- `raw_mixed_section_note`

Notes:

- Profile correctness is not locally proven. Low confidence, mixed evidence and
  missing evidence must remain visible as `Unknown`, `mixed`, low confidence or
  review flags.

### `role_traces`

Purpose: connect fake-output validators and future approved provider roles to
their accepted/rejected outputs.

Compact fields:

- `role_id`
- `role_version`
- `input_snapshot_ids`
- `output_schema_version`
- `status`
- `diagnostics_ref`
- `provider_model`
- `provider_params_signature`
- `latency_ms`
- `prompt_tokens`
- `completion_tokens`
- `validation_error_codes`
- `disagreement_refs`
- `fallback_used`

Raw-capable fields:

- `raw_prompt_body`
- `raw_provider_request_body`
- `raw_provider_response_body`
- `raw_model_output_body`
- `raw_repair_prompt_body`

Notes:

- Provider role output remains untrusted until local validation accepts or
  downgrades it.
- Future #413 may populate provider-backed role traces only after exact
  approval for fixtures, max calls/tokens, provider/model, diagnostic storage
  and raw capture.

### `validation_failures`

Purpose: make local validator failures diagnosable without rewriting them into
success.

Compact fields:

- `validator_id`
- `schema_version`
- `issue_code`
- `path`
- `severity`
- `affected_ids`
- `fallback_action`

Raw-capable fields:

- `raw_invalid_value`
- `raw_invalid_payload_excerpt`

### `conflict_reports`

Purpose: capture role disagreement, contradictory evidence and unsafe promotion
attempts.

Compact fields:

- `conflict_id`
- `conflict_type`
- `affected_entry_ids`
- `affected_evidence_ids`
- `role_ids`
- `severity`
- `decision`
- `fallback_action`

Raw-capable fields:

- `raw_conflicting_claim`
- `raw_conflicting_output_excerpt`

### `work_unit_selections`

Purpose: explain per-work-unit selected/dropped glossary entries and prompt
budget decisions.

Compact fields:

- `work_unit_id`
- `work_unit_sequence`
- `source_block_ids`
- `selection_signature`
- `prompt_budget_tokens`
- `estimated_prompt_tokens`
- `selected_entry_ids`
- `dropped_entry_ids`
- `drop_reasons`
- `profile_rule_ids`

Raw-capable fields:

- none by default.

Selection diagnostics should stay compact. If a future reviewer needs raw
source text around a selection, it belongs in `evidence_packets` and must be
listed in the raw field manifest.

### `provider_failures`

Purpose: connect glossary/profile role failures to existing provider failure
diagnostics without leaking provider internals to ordinary surfaces.

Compact fields:

- `provider_id`
- `failure_category`
- `http_status_bucket`
- `latency_ms`
- `attempt_number`
- `retry_after_seconds`
- `terminal_reason`
- `channel_fingerprint`
- `circuit_state`
- `provider_io_ref`

Raw-capable fields:

- none by default.

Exact provider request/response bodies should remain in the approved
`provider_io_diagnostics.jsonl` boundary. The glossary/profile sidecar may
reference that file by compact `provider_io_ref` if a future implementation is
approved.

### `qa_findings`

Purpose: record post-translation glossary/profile drift findings and repair
candidates without silently mutating translation output.

Compact fields:

- `finding_id`
- `finding_type`
- `severity`
- `work_unit_sequence`
- `source_block_ids`
- `entry_ids`
- `expected_strategy`
- `observed_strategy`
- `decision`
- `repair_candidate_ref`

Raw-capable fields:

- `raw_source_excerpt`
- `raw_translated_excerpt`
- `raw_observed_variant`

RU/UK morphology findings remain diagnostics unless future evidence/tests
support implementation. Use `Unknown` for missing evidence and keep morphology
strategy `TBD`.

### `owner_review_marks`

Purpose: connect owner review decisions/pins/rejections to glossary/profile
diagnostics.

Compact fields:

- `mark_id`
- `mark_type`
- `entry_id`
- `work_unit_sequence`
- `source_block_ids`
- `updated_at`
- `pin_reason_code`

Raw-capable fields:

- `raw_owner_note`
- `raw_source_excerpt`
- `raw_translated_excerpt`

Owner review marks are owner-only raw diagnostics. They must not become support
artifacts or release evidence without a later approved policy.

## Existing Surface Alignment

`run.json`:

- May record compact references such as sidecar presence, schema version,
  section counts and hashes only if separately approved.
- Must not contain raw glossary/profile snippets.

`events.jsonl`:

- May record safe event names and compact reason codes only.
- Must not contain raw sidecar fields or prompt/provider bodies.

`raw_text_diagnostics.json`:

- Existing owner-only archive sidecar for source/translated work-unit text.
- The glossary/profile sidecar may reference it by work-unit sequence or
  source block id in a future implementation, but should not require
  duplication.

`provider_io_diagnostics.jsonl`:

- Existing owner-only provider IO diagnostic log.
- The glossary/profile sidecar should reference provider IO records by compact
  ids/hashes when possible.
- It must still exclude provider `Authorization` headers and API keys.

Admin Translation Trace:

- Must remain metadata-only unless a later owner-approved owner-only page is
  explicitly built.
- It may link to an owner-only full diagnostic archive or sidecar page only
  after access-control/no-store tests exist.

Security telemetry:

- Must remain safe-payload-only.
- Sidecar raw fields are forbidden.

GitHub issues, PR descriptions and docs:

- Must not include raw document snippets, prompt bodies, provider bodies,
  translated text or raw sidecar contents.

## Retention, Export And Deletion

Current status:

- Retention policy: `TBD`
- Export policy: `TBD`
- Deletion policy: `TBD`
- Release-version consent/legal/privacy/support policy: `TBD`

Issue #436 / #204T update:

- Release-version glossary/profile diagnostic privacy, consent, retention,
  deletion, support and legal/privacy behavior remains `TBD`/blocking.
- Pre-release owner-only diagnostics may remain allowed only for explicitly
  approved bounded local diagnostics or dedicated owner-only diagnostic
  surfaces.
- This sidecar design and the later #434 foundation do not approve retention,
  export, deletion, support artifacts, public/legal copy, release telemetry or
  release/privacy readiness.

This design does not change current retention/TTL behavior. Future
implementation must not claim release privacy readiness unless Release
Readiness reviews and the owner approves the release-version policy.

## Failure Modes And Required Behavior

| Failure | Required behavior |
| --- | --- |
| Owner-only boundary is unavailable | Do not write raw-capable fields; write compact diagnostics only or skip sidecar. |
| Sidecar schema validation fails | Do not attach sidecar to archive/UI; record only compact failure metadata. |
| Secret-like content is detected in a raw field | Drop or redact the field; record compact `secret_excluded` metadata. |
| Provider role output is invalid | Keep raw output only in approved owner-only diagnostics; local validators still reject/downgrade it. |
| Role outputs conflict | Record disagreement; prevent unsupported hard promotion. |
| Sidecar grows beyond approved bounds | Stop writing raw append data and record compact `diagnostic_size_limit_reached`; exact size caps remain `TBD`. |
| Archive inclusion is unapproved | Keep sidecar out of archive; do not expose through ordinary logs/admin/API. |
| Release policy is requested | Stop at Release Readiness; consent, retention, deletion and support/legal copy remain `TBD`. |

## Implementation Follow-Up Split

Implementation is not approved by #412. If the owner approves later work, split
it into focused issues:

1. Schema-only dataclasses/validators and raw field manifest tests. No storage
   or admin UI.
2. Run-scoped sidecar writer for compact diagnostics only. No raw fields.
3. Owner-approved raw-capable sidecar writer with secret exclusion tests.
4. Owner-only archive inclusion with README warnings and no ordinary
   log/API/trace leakage.
5. Optional owner-only `no-store` admin sidecar viewer with route/auth tests.
6. Provider-backed role trace population only as part of #413 or a later exact
   approved provider issue.
7. Release/privacy/retention/deletion policy issue coordinated with #207 and
   Release Readiness.

## Required Tests For Future Implementation

- Schema validator accepts compact valid sidecars and rejects missing
  manifest entries for raw-capable paths.
- Raw fields never appear in `run.json`, `effective_run.json`,
  `work_units.json`, `events.jsonl`, security telemetry, normal admin details,
  Translation Trace, JSON APIs, GitHub-facing docs or support artifacts.
- Owner-only full diagnostic archive includes the sidecar only when explicitly
  approved and labels it as sensitive in README.
- Secret-like fields, provider auth headers and API-key-like values are
  excluded.
- Sidecar references to `provider_io_diagnostics.jsonl` and
  `raw_text_diagnostics.json` remain compact unless the approved owner-only
  raw sidecar explicitly contains raw fields.
- Admin viewer, if implemented, requires existing admin auth, remains
  SSH-tunnel-only and sends `Cache-Control: no-store`.
- Retention/delete/export behavior remains `TBD` in tests/docs unless a later
  approved policy changes it.

## Suggested Implementer Prompt For Future Schema-Only Work

Implement only the approved glossary/profile diagnostics sidecar schema and
validator slice. Add no provider calls, no prompt/runtime integration, no
storage, no admin UI, no archive inclusion, no retention/TTL changes and no
release/privacy claims. Validate the raw field manifest, forbid secrets and
prove raw-capable fields cannot be serialized without explicit manifest
entries. Use `TBD` for retention/export/deletion policy and `Unknown` for
missing evidence.
