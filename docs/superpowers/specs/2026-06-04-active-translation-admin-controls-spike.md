# Active Translation Admin Controls Spike

Issue: #107
Status: architecture spike, not implementation approval
Date: 2026-06-04

## Routing Receipt

- Classification: `spike / discovery` plus `risky task`.
- Risk level: high.
- Primary role / skill: Architect Agent, `architecture-review`.
- Approval status for this note: not required; this is docs-only analysis.
- Approval status for follow-up work: approved with owner evidence in the
- Allowed action in this PR: architecture documentation only.
- Verification plan for this PR: docs gate review and `git diff --check`.

## Purpose

Issue #107 asked agents to revisit stale old work from commit
`9acefbb3a6024b3da567b3230a1f2dbc8e9de15b` without merging or cherry-picking
it. The goal is to decide which ideas remain useful and what guardrails are
required before any future active-job controls are expanded.

This note does not approve implementation work, live runtime operations,
deployment, schema changes, retention/delete behavior, public admin exposure,
payment behavior, or release readiness.

## Evidence Reviewed

Confirmed from repository evidence:

- GitHub issue #107: scope, acceptance criteria, guardrails and verification
  plan.
- Old commit `9acefbb`: touched admin operations/routes/views, bot runtime and
  messages, bot translation service, job runner, persistent stores, Postgres
  scheduler, run logs and tests.
- Current `main` at `a3b1fe5`: already contains active-job admin POST actions
  under `/admin/operations/jobs/{job_id}/{action}` for `pause`, `cancel` and
  `delete`; persistent job states include `paused`; bot-facing status includes
  admin paused/deleted messaging; run-log finishing helper exists.
- Existing tests include admin route coverage for pause/cancel/delete and bot
  messaging/service coverage for admin paused/deleted states.

Assumptions:

- The owner still wants operational visibility and intervention tools during
  closed beta.
- The safest future direction is metadata-first observation with narrowly
  approved writable actions.

## Old Ideas Classification

| Old idea from `9acefbb` | Current decision | Reason |
| --- | --- | --- |
| Admin list of active jobs/workers | Accepted / already present | `Operations` and related trace/live views already expose metadata-only job and worker state. |
| Admin `pause` action | Accepted as existing current-main behavior, but future expansion remains gated | Current stores include `paused`; future semantics need explicit confirmation scope and scheduler tests. |
| Admin `cancel` action | Accepted as existing current-main behavior, but future expansion remains gated | Cancellation is operationally sensitive and must preserve cooperative semantics and partial-result behavior. |
| Admin `delete` action | Needs separate review before expansion | Existing code has a delete action, but delete/destructive behavior is high risk and future changes require explicit owner approval, backup/retention impact review and tests. |
| User-visible admin paused/deleted status | Accepted as existing current-main behavior | Bot messages avoid raw text and give a safe status to the affected user. |
| Directly finishing running `run.json` logs from admin actions | Accepted as existing helper, but future changes must stay metadata-only | Current helper sanitizes error text; any new event payloads need redaction tests. |
| Retry/requeue/mark-failed controls | Defer to separate issues | These mutate scheduler/work-unit state and can create duplicate provider work, lost partials or misleading run-log history. |
| Bulk active-job controls | Reject for now | Bulk mutation increases blast radius and can conflict with active provider requests, cost caps and issue #30 safeguards. |
| Direct merge/cherry-pick of the old branch | Rejected | Issue #107 explicitly forbids mechanical merge/cherry-pick of stale work. |

## Action Taxonomy

| Action | Type | Risk | Approval required before new/expanded implementation | Confirmation |
| --- | --- | --- | --- | --- |
| View job, worker, queue and trace metadata | Read-only | Medium | No, if existing redaction rules remain unchanged | No |
| Copy safe evidence packet | Read-only export | Medium | No, if metadata-only and covered by redaction review | No |
| Refresh live status | Read-only | Low | No | No |
| Pause queued/translating job | Writable state change | High | Yes for any semantic expansion | Yes |
| Cancel queued/translating job | Writable state change | High | Yes for any semantic expansion | Yes |
| Delete job or related objects | Destructive state/storage operation | Critical | Yes, exact scope approval required | Yes, with explicit destructive warning |
| Retry failed work unit/job | Writable scheduler/provider action | High | Yes | Yes |
| Requeue interrupted/failed work unit | Writable scheduler/provider action | High | Yes | Yes |
| Mark failed/terminal | Writable state change | High | Yes | Yes |
| Change provider capacity while jobs are active | Provider/cost control | High | Yes | Yes |
| Bulk job action | Writable bulk operation | Critical | Yes, separate architecture review required | Yes, if ever approved |

## State-Machine Impact

Persistent jobs:

- `queued` and `translating` can be observed safely.
- `paused`, `cancelled`, `interrupted`, `failed`, `partial` and `ready` need
  clear owner-facing meanings and must not be conflated.
- Future writable controls must state whether they affect only job status or
  also work-unit rows, run logs, user-visible My Books state and provider
  capacity.

Work units:

- In-flight `translating` units carry worker, claim-token and lease state.
- Changing a job while a unit is in flight must either leave the unit to finish
  cooperatively or release it through a documented lease-safe transition.
- Retry/requeue must preserve attempt history and bounded retry policy.

Scheduler leases:

- Lease ownership remains authoritative for active work.
- Admin actions must not create split-brain ownership by clearing worker/claim
  fields while a provider request is still running unless the transition is
  explicitly designed and tested.
- Expired leases should continue through existing lease-expiry handling unless
  a separate issue changes that contract.

Bot delivery:

- User-visible messages must stay neutral and safe: no raw document text,
  prompts, translations, stack traces, provider internals or blame language.
- Cancel/pause/delete controls must preserve My Books/history behavior where
  existing results or partials are still intended to be available.

Translation run logs:

- Admin/action events should be metadata-only.
- `run.json`, summaries and archives must not include raw source text,
  translated text, prompts, provider payloads, API keys or stack traces outside
  approved owner-only diagnostic surfaces.
- Any new status/event payload requires redaction-focused tests.

Provider capacity:

- Admin job controls must not bypass beta cost caps, kill switch, adaptive
  provider throttling or the issue #30 guard that bulk key tests pause during
  active translations/provider requests.
- Retry/requeue controls can generate new provider traffic, so they need
  explicit capacity and cost-safety rules before implementation.

## Redaction And Privacy Rules

Every new admin/log/user-visible surface for this area must be metadata-only by
default. Allowed examples:

- job id, order id, run id and safe user reference;
- document kind, sanitized filename, language direction and translation mode;
- status, timestamps, unit counts, retry counts and safe failure category;
- safe provider category, redacted channel fingerprint and aggregate usage.

Disallowed outside approved owner-only diagnostic surfaces:

- raw document text, translated text, prompt bodies or provider responses;
- API keys, secret ids, tokens, headers or unmasked provider account data;
- stack traces, object-storage keys, backup artifacts or runtime file paths;
- copied raw excerpts in issues, PRs, docs, logs or support notes.

## Owner Approval Evidence

The owner approved work on GitHub issues #282, #283, #284, #285 and #81 in the
Those issues remain separate source-of-truth tasks and should each produce
focused PR-sized work rather than being folded into this #107 spike PR.

## Required Future Issues

The remaining implementation scope is larger than one safe PR. Follow-up
issues are now split as GitHub source-of-truth tasks:

1. GitHub issue #282, architecture approval for current active-job controls:
   confirm owner intent for existing pause/cancel/delete semantics, including
   whether destructive delete should remain available or be narrowed.
2. GitHub issue #283, safe resume/retry/requeue design:
   define exact state transitions, retry limits, provider-capacity behavior,
   user-visible outcomes and tests.
3. GitHub issue #284, destructive job deletion review:
   define data classes affected, storage deletion behavior, retention/TTL
   impact, backup/restore considerations and confirmation UX.
4. GitHub issue #285, redaction regression planning:
   prove admin pages, activity, audit, run logs and archive exports stay
   metadata-only after each new control.
5. Existing GitHub issue #81, Gate B operational evidence:
   validate cancel/resume/restart behavior using approved synthetic or
   disposable data only.

## Required Tests For Later Implementation

- Focused admin route/rendering tests for every new control and confirmation
  path.
- Persistent job/store tests for state transitions.
- Postgres scheduler tests for lease, claim-token and work-unit transitions.
- Bot/service tests for user-visible paused, cancelled, partial, retry or
  deleted outcomes.
- Translation run-log tests for safe status/event updates.
- Redaction tests proving no raw document text, prompts, translations,
  provider internals, API keys, object keys or stack traces appear.
- `PYTHONPATH=src python3 -m compileall src`.
- Full `PYTHONPATH=src python3 -m unittest discover -s tests` for shared
  admin/bot/scheduler/worker changes.

## Verdict

NEEDS SPLIT for implementation. Owner approval exists for follow-up work on
#282, #283, #284, #285 and #81, but each issue still needs its own scoped
implementation/review/verification pass.

The safe next step is not to merge old work. The safe next step is to use this
taxonomy through the small owner-approved follow-up issues without merging or
cherry-picking the stale old branch.
