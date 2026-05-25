# Upload Safety Ledger Design

Status: Proposed. This document records an architecture proposal for local
malware/AV scan observability. It does not claim that upload hardening,
quarantine, malware scanning, TTL cleanup, upload-safety admin visibility or
Gate B evidence is implemented.

Issue #101 reconciles the remaining AV issues around this proposal. The
reconciliation is docs/issue-reference only: it does not approve runtime code,
database/schema/state changes, ClamAV deployment, production dependencies,
retention behavior, public scanning services or Gate B readiness claims.

Remaining AV work should treat the Upload Safety Ledger foundation as the
prerequisite architecture:

- #93 adds a local ClamAV scanner adapter only after the ledger/scan contract
  is clear and owner approval exists for dependency, deployment, config or
  runtime shape changes.
- #94 wires scanner verdicts into the upload flow only after parser and worker
  access are gated through ledger-backed accepted source decisions.
- #95 records Gate B malware/AV evidence only after implementation lands or an
  explicit owner-approved deferral exists.

All remaining AV issues must preserve metadata-only admin/log/release
artifacts, fail-closed beta behavior for scanner timeout/unavailable/error, and
no default public VirusTotal-style submission of user documents.

## Goal

Add owner-visible antivirus and upload-safety observability without weakening
the upload gate, privacy boundary or closed-beta scope.

The owner should be able to answer:

- how many uploads were scanned, accepted, blocked or failed closed;
- which users submitted blocked or suspicious files;
- why a file was blocked;
- whether a blocked or unscanned file reached parser, source storage, job
  creation or workers;
- whether the local scanner is healthy enough for free closed beta.

The system must answer these questions with metadata only. Raw document text,
extracted snippets, prompts, translations, stack traces and secrets must not
appear in logs, admin views, telemetry or release artifacts.

## Critique Of A Simple AV Logs Page

A simple "AV logs" table is not enough because it treats observability as a UI
feature instead of a safety gate.

Problems with a logs-first design:

- It can show scan results without proving that parser and worker paths enforce
  those results.
- It assumes a `job_id`, but malware scanning must happen before an accepted
  translation job exists.
- It encourages a second source of truth parallel to upload validation, user
  activity and admin audit logs.
- It can leak sensitive filenames, hashes, object keys or quarantine paths if
  the admin UI is designed before the data boundary.
- It does not define fail-closed behavior when the scanner, store or admin
  read model fails.
- It invites unsafe convenience actions such as "allow anyway" before the
  project has a reviewed break-glass process.

## Decision

Use an append-only **Upload Safety Ledger** as the canonical record for upload
safety decisions.

The ledger is not analytics. It is the source of truth for whether an uploaded
object may move from quarantine to accepted source storage.

Admin pages, security summaries, user activity rows and Gate B reports should
read from or link back to the ledger. They should not re-decide whether a file
was safe.

## Core Invariants

- Parser and worker code must consume only an `accepted_source_key`.
- An `accepted_source_key` must be created only after a clean scanner verdict
  and clean signature/container validation.
- Quarantine object keys must never be accepted as parser or worker inputs.
- Unscanned uploads must not reach parser, source storage, job creation or
  translation workers after the scan gate is enabled.
- `infected`, `suspicious_container`, `scanner_timeout`,
  `scanner_unavailable`, `scanner_error` and `unsupported` verdicts fail
  closed for beta unless the owner explicitly approves a different policy in a
  scoped issue.
- If the ledger cannot record a safety decision, the upload must fail closed.
- Admin UI must not offer "allow anyway" in the beta implementation.
- Raw quarantine inspection is out of normal admin UI scope. It requires a
  separate owner-approved operational process.

## State Machine

The ledger tracks upload safety before translation job creation.

```text
received
-> quarantined
-> scan_started
-> scan_clean | scan_blocked | scan_failed
-> container_started
-> container_clean | container_blocked | container_failed
-> accepted_source_created
```

Blocked or failed uploads follow this path:

```text
received
-> quarantined
-> scan_blocked | scan_failed | container_blocked | container_failed
-> rejected
-> quarantine_expired | quarantine_deleted
```

Allowed terminal outcomes:

- `accepted_source_created`: clean scanner verdict, clean container validation
  and safe accepted source storage are all complete.
- `rejected`: upload is not allowed to proceed.
- `quarantine_expired`: quarantine TTL removed the quarantined object.
- `quarantine_deleted`: approved cleanup removed the quarantined object.

State transition rules:

- `received` to `quarantined` happens before scanning or parsing.
- `scan_clean` is required before container validation can accept the file.
- `scan_blocked` and `scan_failed` can only lead to `rejected` or later
  quarantine TTL states.
- `container_blocked` and `container_failed` can only lead to `rejected` or
  later quarantine TTL states.
- `accepted_source_created` is the only state that can link to job creation.

## Ledger Data Model

Proposed fields:

- `scan_id`: stable internal event id.
- `upload_id`: stable id created when the upload enters the backend.
- `created_at`, `updated_at`, `terminal_at`.
- `actor_id`, `channel`, `channel_user_id`.
- `job_id`, nullable; set only after the upload is accepted and a job exists.
- `order_id`, nullable.
- `declared_format`, `detected_format`.
- `size_bytes`.
- `sanitized_original_filename`, stored only after filename sanitization.
- `content_sha256`, internal only; admin list should show at most a short
  prefix if needed for support.
- `quarantine_object_key`, internal only.
- `accepted_source_key`, nullable and internal only.
- `scanner_name`, `scanner_version`, `signature_db_version`,
  `signature_db_age_seconds`.
- `scanner_started_at`, `scanner_finished_at`, `scanner_duration_ms`.
- `av_verdict`: `clean`, `infected`, `scanner_timeout`,
  `scanner_unavailable`, `scanner_error` or `unsupported`.
- `container_verdict`: `clean`, `suspicious_container`,
  `content_extension_mismatch`, `corrupt_container`, `zip_traversal`,
  `zip_bomb_like`, `oversize`, `unsupported_format` or `not_checked`.
- `final_action`: `accepted`, `rejected`, `quarantined`, `deleted_by_ttl`.
- `reason_code`: stable safe reason.
- `safe_error_class`: safe error category, not raw exception text.
- `parser_access_granted`: boolean, default false.
- `worker_access_granted`: boolean, default false.

The field list is intentionally metadata-only. Full document content, extracted
text snippets, provider prompts, provider responses and raw exception traces are
out of scope.

## Relationship To Existing Stores

The ledger should be canonical for upload safety decisions.

Existing stores can receive safe derived events:

- `SQLiteUserActivityStore`: records user-facing and security activity such as
  `security.upload_scan_blocked`, `security.upload_scan_failed`,
  `security.upload_scan_clean` and `document.upload_rejected`.
- `security_telemetry`: records safe scan and container security events where
  thresholding or security summaries need them.
- `SQLiteAdminAuditLog`: records admin actions, such as viewing a blocked
  upload detail page or requesting a future rescan. It should not be the source
  of upload verdict truth.
- Translation run logs: link to the ledger only after accepted job creation.
  Rejected pre-job uploads should not create translation run logs.

## Admin Experience

The admin UI should be read-only for beta.

### Overview

Show:

- scanner health status;
- last successful scanner check;
- scanner name/version;
- signature database version and age;
- uploads scanned today, 7 days and 30 days;
- clean, blocked and failed-closed counts;
- top safe reason codes;
- quarantine objects present, expired and deleted;
- blocked uploads with any parser or worker access; the expected count is zero.

Do not show raw quarantine paths, raw object paths or raw document text.

### Event List

Filters:

- date range;
- final action;
- AV verdict;
- container verdict;
- reason code;
- channel user id;
- declared/detected format.

Default columns:

- created time;
- channel user id or internal user id;
- format;
- size;
- verdict;
- reason code;
- final action;
- parser access granted;
- worker access granted.

Do not show original filename in the default list. It can be shown in the
detail page only after sanitization.

### Detail Page

Show a timeline:

```text
received -> quarantined -> scan_started -> scan_blocked -> rejected
```

Show safe metadata:

- sanitized original filename;
- size;
- declared and detected format;
- short digest prefix if needed;
- scanner version and signature database version;
- verdicts and reason code;
- linked job id if one exists;
- parser/worker access flags.

The detail page must make it obvious when a file was blocked before parser or
worker access.

Do not include a raw download button for quarantine objects.

## Failure Handling

Closed beta default is fail closed.

Failure cases:

- scanner timeout: reject and keep quarantine metadata;
- scanner unavailable: reject and raise scanner health signal;
- scanner error: reject with safe error class;
- ledger write failure before decision: reject and do not create accepted
  source storage;
- quarantine write failure: reject before scan;
- accepted source write failure after clean verdict: fail the upload safely and
  do not create a job;
- admin read failure: admin page shows unavailable metadata, not raw fallback
  logs.

Future `rescan` behavior may be useful for scanner outages, but it is out of
scope for the beta read-only admin UI. It requires a separate issue, audit
events and owner approval.

## Privacy And Redaction Rules

Allowed in admin and release artifacts:

- user id / channel user id;
- upload id / scan id;
- job id when present;
- format;
- byte size;
- verdict;
- reason code;
- scanner name/version;
- signature database version or age;
- safe timestamps and durations.

Sensitive or internal-only:

- original filename, even sanitized; detail page only;
- full content hash;
- quarantine object key;
- accepted source key;
- raw object path;
- raw scanner output;
- raw exception details.

Forbidden:

- raw document text;
- extracted snippets;
- provider prompts;
- translations;
- API keys or secrets;
- stack traces in user/admin-visible fields.

## Required Approval Gates

Human approval is required before:

- changing runtime user-data handling;
- adding or changing retention/TTL behavior;
- adding production dependencies;
- changing Docker, deployment, scanner sidecars or scanner service config;
- adding external/public malware scanning;
- changing admin auth/RBAC/security behavior;
- adding raw quarantine inspection or download flows;
- changing database/schema/state in production-like stores.

## Required Tests

Focused tests for implementation slices:

- clean scan proceeds to container validation and accepted source creation;
- infected scan is rejected and never reaches parser or worker;
- scanner timeout/unavailable/error fails closed;
- suspicious container is rejected after clean scan;
- unscanned object cannot be parsed or translated;
- ledger write failure fails closed;
- user activity and security events contain metadata only;
- admin overview/list/detail render metadata only;
- sanitized filename does not appear in default event list;
- full content hash and object keys do not appear in admin HTML;
- EICAR or equivalent safe AV fixture is detected by the local scanner adapter
  in the ClamAV slice;
- compile check passes.

For shared upload/admin/storage changes, run the relevant focused tests,
`PYTHONPATH=src python3 -m compileall src`, and the full unittest suite unless
a scoped issue explicitly narrows verification with reviewer approval.

## Implementation Split

Suggested PR-sized issues:

1. Design and approve the Upload Safety Ledger contract.
2. Reconcile remaining AV issues and docs so #93, #94 and #95 depend on the
   ledger foundation before ClamAV, upload-flow wiring and Gate B evidence.
3. Implement ledger store and pure state transition tests without ClamAV or
   deployment changes.
4. Implement scanner contract and fake scanner adapter tests.
5. Wire upload flow so only accepted source objects reach parser and job
   creation.
6. Add read-only admin Upload Safety pages backed by ledger read models.
7. Add local ClamAV adapter after dependency/deployment approval.
8. Produce Gate B metadata-only evidence for EICAR, scanner failure,
   suspicious containers, parser/worker blocking and admin redaction.

## Out Of Scope

- Public production AV policy.
- Paid beta or payment-related decisions.
- Public admin exposure.
- PDF/OCR/MOBI/FB2 or arbitrary archive scanning.
- Raw quarantine inspection in normal admin UI.
- Public VirusTotal-style user-file submission by default.
- "Allow anyway" overrides.
- SIEM, warehouse, broad BI analytics or complex alerting beyond Gate B owner
  visibility.

## Open Human Decisions

- TBD: exact storage backend for the ledger in the first implementation slice.
- TBD: whether sanitized filenames are allowed in admin detail views during
  beta, or whether they should be hidden behind an explicit reveal action.
- TBD: quarantine retention behavior for infected files after Gate B.
- TBD: scanner implementation details and resource limits.
- TBD: whether a future owner-only rescan action belongs in beta or later.
- TBD: any raw quarantine inspection process outside normal admin UI.
