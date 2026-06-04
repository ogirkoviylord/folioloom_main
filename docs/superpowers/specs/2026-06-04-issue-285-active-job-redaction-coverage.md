# Issue #285 Active-Job Control Redaction Coverage

Issue: #285
Status: architecture spike; not implementation approval
Date: 2026-06-04

## Routing Receipt

- Classification: `spike / discovery` plus `risky task`.
- Risk level: high.
- Primary role / skill: Architect Agent, `architecture-review`.
  `docs/RISK_REGISTER.md`, `docs/QUALITY_GATES.md`,
  `docs/superpowers/specs/2026-06-04-active-translation-admin-controls-spike.md`.
- Approval status for this PR: not required for docs-only redaction planning.
- Approval status for implementation/runtime operations: missing; any writable
  active-job control implementation still needs a separate owner-approved issue.
- Allowed action in this PR: architecture documentation only.
- Verification plan for this PR: docs gate review and `git diff --check`.

## Boundary

Normal admin pages, logs, APIs, activity, audit and archive exports must remain
metadata-only. The only raw-text exception is the already approved owner-only
diagnostic surface for raw translation text and prompt diagnostics. This issue
does not broaden that exception and does not approve raw text, prompt bodies or
runtime data in issues, PRs, docs, logs, screenshots, safe archives or normal
admin views.

## Forbidden Data Everywhere

The following data is forbidden on normal active-job control surfaces:

- raw document text;
- translated text;
- prompt bodies;
- provider payloads or provider responses;
- API keys, tokens, secret ids or provider account internals;
- stack traces;
- object-storage keys;
- backup artifacts or restored files;
- runtime file paths;
- raw `.env*` values;
- raw user document excerpts in issues, PRs, docs or support notes.

## Surface Coverage Matrix

| Surface | Safe metadata fields | Regression assertions |
| --- | --- | --- |
| Admin operations page | job id, order id, safe user reference, sanitized filename, document kind, language direction, status, timestamps, unit counts, retry counts, safe failure category, redacted provider/channel fingerprint, action eligibility | Page contains only safe fields; no raw text, prompts, provider payloads, object keys, runtime paths or stack traces. |
| Translation trace/details | job id, run id, order id, status, timeline event types, safe failure category, retry-after seconds, attempt/max-attempt counts, unit counts, provider category, redacted channel fingerprint, aggregate usage | Trace/details remain metadata-only; owner-only raw diagnostics are linked or separated, never embedded in normal trace/details/API payloads. |
| Activity store | actor type, safe actor id, surface, event type, action, outcome, channel, safe channel user id, target type/id, job id, order id, safe metadata fields, timestamp | Activity metadata for pause/cancel/delete/requeue contains no raw text, prompt, object key, stack trace, provider payload or secret. |
| Audit log | actor id, role, action, target type/id, outcome, safe reason, redacted metadata, timestamp, confirmation version when applicable | Audit record redacts sensitive values and retains tombstone metadata without leaking raw/user/provider/runtime data. |
| `run.json` | run id, job id, order id, sanitized filename, document kind, language direction, status, timestamps, safe error/status message, aggregate counts, policy/profile ids | Run snapshot for admin actions remains sanitized and does not add raw fragments, prompts, provider responses, object keys or stack traces. |
| `events.jsonl` | event type, timestamp, job id, work-unit id, safe reason/category, retry-after seconds, terminal reason, metadata-only action payload | Events for active-job controls are metadata-only; security/provider events use safe categories and redacted excerpts only. |
| Summaries | run id, job id, status, counts, safe failure category, retry/capacity metadata, aggregate usage, timestamps | Summary text and JSON omit raw source/translation, prompts, provider internals, object keys, backup artifacts and runtime paths. |
| Archive exports | sanitized `run.json`, sanitized `events.jsonl`, `effective_run.json`, `work_units.json`, metadata-only `summary.md`, export README | Archive inspection with synthetic fixtures proves forbidden data is absent from every file in the zip. |
| Normal admin APIs | same safe fields as the corresponding page/API read model | JSON payloads remain metadata-only and do not expose owner-only raw diagnostics by default. |
| Owner-only diagnostic surfaces | raw text/prompt fields only inside the approved owner-only diagnostic boundary | Tests prove this exception stays out of normal details, trace, APIs, archives, activity and audit. |

## Control-Specific Safe Fields

### Pause

Safe fields:

- action `pause`;
- previous status and new status;
- job id and order id;
- sanitized filename;
- document kind and language direction;
- unit counts by status;
- actor id/role;
- confirmation version;
- safe notification message.

Forbidden additions:

- current fragment text;
- pending source block text;
- translated partial text;
- provider request/response body;
- object-storage key for any pending source object.

### Cancel

Safe fields:

- action `cancel`;
- previous status and new status;
- whether a partial result exists as a boolean;
- result class such as `partial` or `none`, not object key;
- unit counts by status;
- safe cancellation reason/category;
- actor id/role and confirmation version.

Forbidden additions:

- partial result content;
- final result content;
- source text around the cancellation point;
- provider payload or stack trace.

### Delete

Safe fields:

- action `delete`;
- previous status;
- affected data classes as labels;
- object classes affected, not object keys;
- deleted-row counts in synthetic tests only;
- actor id/role and confirmation version;
- safe tombstone metadata.

Forbidden additions:

- object-storage keys;
- backup archive names/paths;
- runtime filesystem paths;
- raw source or translated output;
- deletion stack traces.

### Retry/Requeue

Safe fields:

- action `retry` or `requeue`;
- previous and new job/work-unit status;
- work-unit id;
- attempt count and max attempts;
- retry-after seconds;
- safe failure category;
- terminal reason;
- provider category and redacted channel fingerprint;
- cap/kill-switch decision code.

Forbidden additions:

- prompt body for the retried unit;
- source or translated fragment;
- provider request/response payload;
- full provider key id or account detail.

## Test Plan For Later Implementation

Later implementation must use synthetic fixtures only unless the owner approves
an exact disposable environment or runtime copy.

Required focused tests:

- Admin operations route/rendering test for each touched control, asserting
  safe fields are present and forbidden markers are absent.
- Translation trace/details page and API tests for each touched control.
- Activity store tests inspecting recorded metadata for control events.
- Audit log tests inspecting redacted metadata and safe reason fields.
- `run.json` tests for admin action status/error payloads.
- `events.jsonl` tests for action and scheduler events.
- Summary rendering tests for safe fields only.
- Archive export inspection that opens the generated zip and scans every file
  for forbidden synthetic sentinels.
- Owner-only diagnostic boundary tests proving raw diagnostics remain excluded
  from normal pages, APIs and safe archives.

Required synthetic sentinel set:

- source text sentinel;
- translated text sentinel;
- prompt sentinel;
- provider payload sentinel;
- API-key-like sentinel;
- secret-id sentinel;
- stack-trace sentinel;
- object-storage-key sentinel;
- backup artifact/path sentinel;
- runtime path sentinel.

Required commands for later implementation:

- focused tests for each touched surface;
- `PYTHONPATH=src python3 -m compileall src`;
- full `PYTHONPATH=src python3 -m unittest discover -s tests` for shared
  admin/log/archive/API changes.

## Review Checklist

Reviewer must verify:

- no normal admin/log/archive/API surface includes forbidden data;
- owner-only raw diagnostic routes remain isolated and are not linked into safe
  archives or JSON APIs as raw payloads;
- activity and audit retain metadata-only evidence for state-changing controls;
- archive exports are inspected file-by-file using synthetic sentinels;
- no live runtime `var/` data, raw user document, backup artifact, real `.env*`
  file, deployment, schema/state migration, payment behavior or release claim
  is introduced.

## Implementation Split

This issue defines coverage only. Any code changes must be split into the
specific owner-approved implementation issue that introduces or narrows the
control surface:

- #282 for pause/cancel/delete narrowing;
- #283 for retry/requeue;
- #284 for destructive delete;
- #81 for Gate B operational evidence.

Do not combine redaction implementation with writable control implementation
unless the owner explicitly scopes that combined PR.

