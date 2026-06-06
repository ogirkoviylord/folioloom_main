# Admin Reader Explorer Architecture Review

## Scope

This document is the architecture-first artifact for GitHub issue #342,
`Admin Reader: turn Advanced Reader into Reader Explorer`.

The requested product direction is accepted for architecture review:
`Admin -> Advanced -> Reader` may become a `Reader Explorer` that lets the
owner navigate from safe user references to safe translation/file/run metadata,
then explicitly open the existing run-scoped owner-only Reader and related
owner-only full diagnostic surfaces.

The owner additionally clarified on 2026-06-06 that, during pre-release
development, they want full access to available diagnostic information and will
revisit that policy before release. Under that owner direction, a focused
implementation may proceed if it keeps full information behind explicit
owner-only diagnostic drilldowns, excludes secrets, and does not add release
policy, public/user-facing access, schema/state changes, runtime-data mutation
or new production dependencies.

## Routing Receipt

- Classification: risky task.
- Risk level: high.
- Primary agent role and repo-level skill: Architect Agent,
  `.agents/skills/architecture-review`.
- Supporting skills: Reviewer Agent / `.agents/skills/pr-review` after the
  docs-only diff is ready.
- Required docs read: `AGENTS.md`, `docs/PROJECT_BRIEF.md`,
  `docs/CONTEXT_MAP.md`, `docs/DECISIONS.md`, `docs/HANDOFF.md`,
  `docs/RISK_REGISTER.md`, `docs/QUALITY_GATES.md`.
- Code evidence inspected: `src/translator_service/admin/routes.py`,
  `src/translator_service/admin/views.py`, `tests/test_admin_routes.py`,
  `tests/test_internal_reader.py`.
- Human approval status: approved for architecture review by issue #342;
  approved for the focused pre-release owner-only implementation slice by the
  owner message in the current Codex thread on 2026-06-06.
- Allowed action: analysis and docs-only architecture record.
- Verification plan for this PR: docs gate review plus `git diff --check`.

## Verdict

NEEDS SPLIT. The first focused implementation slice is owner-approved if it
follows this updated pre-release diagnostic boundary.

The safe implementation shape is feasible as a small admin navigation layer if
the Explorer remains metadata-first and full information appears only after an
explicit owner action inside owner-only `no-store` diagnostic surfaces. The
implementation must not add raw-text JSON APIs, safe archive content, telemetry,
support artifacts, public/user-facing routes, release evidence, or normal admin
details.

## Confirmed Facts

- `docs/PROJECT_BRIEF.md` says raw document/translation text is available to
  the owner only through dedicated owner-only text diagnostics and must not
  appear in ordinary admin pages, logs, archives, telemetry, issues/PRs, or
  support notes.
- `docs/DECISIONS.md` records an active owner-only internal reader UI decision
  limited to approved local TXT/DOCX/EPUB files and optional JSON mappings.
- `docs/RISK_REGISTER.md` R-037 marks raw text and prompt diagnostics as high
  privacy/user-data risk and confines them to SSH-tunneled owner-only diagnostic
  surfaces.
- `docs/RISK_REGISTER.md` R-038 warns that the internal before-after reader can
  expand into raw-text admin/user access or overclaim format fidelity.
- `docs/DECISIONS.md` records an active pre-release-only decision from
  2026-06-06 allowing automatic full raw provider diagnostics capture for
  owner/operator analysis, while excluding secrets and requiring the policy to
  be revisited before release.
- `docs/RISK_REGISTER.md` R-040 tracks the same pre-release automatic full raw
  provider diagnostics risk and requires focused Architect/Reviewer review for
  implementation.
- `src/translator_service/admin/views.py` currently labels Advanced navigation
  item `reader` as `Reader` with href `/admin/internal-reader`.
- `src/translator_service/admin/routes.py` protects admin pages through
  `_protected_page(...)`, which returns `Cache-Control: no-store`.
- `/admin/internal-reader` currently renders an explicit local fixture/path
  form for approved TXT/DOCX/EPUB reader reports.
- `/admin/logs/{run_id}/reader` already renders the existing run-scoped
  owner-only Translation Reader from durable work-unit diagnostics.
- `/admin/logs/{run_id}/reader/review-mark` may persist marked source and
  translated text into run-scoped `reader_review_marks.json`; existing tests
  assert this sidecar stays out of normal details/API/download archive surfaces.
- `tests/test_admin_routes.py` already includes redaction assertions that
  normal details, normal details API, and safe downloads do not contain raw
  source/translation text while Text Diagnostics and Reader do.

## Assumptions

- The Explorer should replace the standalone Advanced `Reader` entry rather
  than change the existing run-scoped Reader route.
- The Explorer may reuse existing translation run summaries and user activity
  metadata for navigation, while full raw diagnostic fields are rendered only
  after an explicit owner click into a dedicated diagnostic view.
- User references may include Telegram-style ids or other existing safe admin
  identifiers already present in metadata-only admin views.

## TBD / Unknown

- TBD: exact Explorer URL shape, for example `/admin/reader` versus preserving
  `/admin/internal-reader` as the entry route.
- TBD: whether the existing approved-local-fixture reader form remains on the
  same page under a secondary entry or moves to a separate `Local fixtures`
  sub-view.
- TBD: release-version raw diagnostics, retention, consent and redaction policy
  before any free beta, broader beta or public launch decision.
- Unknown: current CI status for any future implementation PR until the PR
  checks page is inspected.

## Affected Components

- `src/translator_service/admin/routes.py`: add metadata-first Explorer routes
  or repurpose the existing `/admin/internal-reader` entry route; keep
  `_protected_page(...)` and `no-store`.
- `src/translator_service/admin/views.py`: change the Advanced nav label to
  `Reader Explorer` and add safe Explorer list views.
- `src/translator_service/admin/translation_logs.py`: read existing safe
  summaries/details metadata for Explorer lists; raw fragment text, prompt
  bodies, provider payloads or review mark contents may be exposed only in
  explicit owner-only diagnostic drilldowns.
- `src/translator_service/user_activity.py`: optional source for safe user
  references and event/job/run relationships.
- `tests/test_admin_routes.py`: auth/no-store, metadata-first Explorer lists,
  selected user/run link, and redaction assertions.
- `tests/test_internal_reader.py`: only if the local fixture reader route or
  form behavior changes.

## Privacy Boundary

Explorer overview pages are navigation and triage surfaces. Full information is
allowed only in explicit owner-only diagnostic drilldowns.

Allowed in Explorer lists:

- safe user reference;
- run id and job id;
- status;
- source/target language;
- document kind / format;
- file name, bounded and HTML-escaped;
- started/updated timestamps;
- fragment/work-unit counts;
- safe error category or safe redacted error summary;
- links to existing run-scoped Reader, Text Diagnostics or future approved
  full-info diagnostic drilldowns.

Allowed in explicit pre-release owner-only full-info diagnostic drilldowns:

- source work-unit text;
- translated work-unit text;
- provider prompt bodies and user payloads;
- raw provider outputs;
- repair prompts and output-contract validation details;
- work-unit/job/run metadata and related failure state;
- persisted Reader review mark text for the selected run.

Forbidden in Explorer lists, normal admin JSON APIs, safe archives, telemetry,
issues/PRs, support notes, release evidence, legal/privacy copy and ordinary
admin details:

- source document text;
- translated text;
- prompt text or provider payloads;
- persisted Reader review mark text;
- stack traces;
- object-storage paths or runtime `var/` paths;
- API keys, provider internals, secrets, tokens, or passwords.

Secrets remain forbidden even in full-info diagnostics: API keys, auth tokens,
passwords, real `.env*` contents, provider key plaintext, DSNs and equivalent
credentials must not be persisted or displayed as raw diagnostics.

Raw source, translated text, prompt bodies and provider payloads may appear only
after the owner explicitly opens an owner-only raw diagnostic route, such as
`/admin/logs/{run_id}/reader`, `/admin/logs/{run_id}/text-diagnostics` or a
future approved full-info diagnostic drilldown.

## Risks

- High privacy/user-data risk if the Explorer copies raw fields from existing
  diagnostics into overview/list rows.
- High privacy/user-data risk if full pre-release diagnostics are mistaken for
  release-version telemetry, consent, retention or legal/privacy policy.
- High auth/security risk if a new route bypasses `_protected_page(...)` or
  drops `Cache-Control: no-store`.
- Medium workflow risk if the existing local fixture reader is removed without
  a clear replacement path for approved fixture QA.
- Medium review risk if PR descriptions, screenshots, docs, or test fixtures
  include raw excerpts from real documents. Use synthetic text only.
- Medium scope risk if this becomes a publisher/editor workspace, public reader,
  or user-facing Telegram reader. Those are explicitly out of scope.

## Required Tests For Follow-Up Implementation

- Unauthenticated requests to Explorer routes redirect to `/admin/login`.
- Authenticated Explorer routes include `Cache-Control: no-store`.
- Empty state renders without creating or mutating runtime data.
- User list renders safe user references and aggregate counts only.
- Selected user renders safe translation/file/run metadata with long filename
  overflow handled.
- Selected run link points to the existing `/admin/logs/{run_id}/reader` route.
- Explicit full-info diagnostic route, if added, remains authenticated,
  `no-store`, run-scoped and excludes secrets.
- Explorer redaction test seeds raw-looking source text, translated text, prompt
  text, traceback-like text, storage paths, and review marks, then asserts none
  appear in Explorer HTML, normal details, JSON API payloads, downloads,
  telemetry fixtures, or test artifacts.
- Existing dedicated Reader/Text Diagnostics/full-info tests continue to prove
  raw text is confined to owner-only `no-store` diagnostic surfaces.
- Verification commands for code PR:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes tests.test_internal_reader`;
  `PYTHONPATH=src python3 -m compileall src`;
  targeted `python3 -m ruff check --select F,I` on changed Python files;
  `git diff --check`.

## Required Docs Updates For Follow-Up Implementation

- Update this review or `docs/HANDOFF.md` only after verified implementation
  changes the admin navigation/Reader contract.
- Do not update release readiness, Gate B/C/D status, legal/privacy policy, or
  production readiness from this feature alone.
- If implementation adds a new raw diagnostic entry point beyond existing Reader
  or Text Diagnostics, update relevant docs only with owner approval and
  reviewer evidence.

## Implementation Slice Contract

The approved first implementation slice changes `/admin/internal-reader` into a
metadata-first `Reader Explorer` entry in Advanced navigation while preserving
the existing local fixture reader form on the same page.

This slice may list safe user references and safe run metadata, then link to
the existing `/admin/logs/{run_id}/reader` and
`/admin/logs/{run_id}/text-diagnostics` owner-only diagnostic surfaces. It does
not add a new raw-text route, JSON API, archive payload, telemetry path,
schema/state change, runtime-data mutation, production dependency,
public/user-facing reader, publisher/editor workspace or release-policy claim.

## Required Approval Gates

The focused implementation described here has owner approval for pre-release
owner-only diagnostics. It still touches admin raw-text diagnostics, user-data
navigation and the R-037/R-038/R-040 boundary, so it requires a strict Reviewer
pass before PR-ready status.

Separate approvals are required for any of the following:

- public/user-facing raw-text route or any raw-text JSON API;
- new persisted raw-text sidecar beyond the existing Reader review marks;
- auth/RBAC/session changes;
- runtime `var/` browsing or mutation outside existing approved diagnostic
  paths;
- database schema/state changes;
- new production dependencies;
- public/user-facing reader or publisher/editor workspace;
- legal/privacy/support copy.

## Recommended Implementation Plan

1. Add a focused implementation issue that explicitly references this review.
2. Keep the first implementation metadata-first and server-rendered under
   Advanced.
3. Preserve the existing run-scoped Reader and Text Diagnostics routes as
   explicit owner-only raw text surfaces; add a new full-info drilldown only if
   it stays inside the same owner-only, no-store diagnostic boundary.
4. Rename the Advanced nav label from `Reader` to `Reader Explorer`.
5. Add Explorer empty/user/user-detail states using safe summary objects.
6. Link each selected run to `/admin/logs/{run_id}/reader` and the relevant
   owner-only diagnostic route.
7. Keep the approved local fixture reader reachable, either as a secondary
   Explorer state or a clearly named local-fixture route.
8. Add focused route/view/redaction tests before implementation is considered
   PR-ready.
9. Run focused admin/reader tests, compileall, targeted ruff, and
   `git diff --check`.
10. Have Reviewer Agent verify privacy boundary, scope, tests, and CI status
    reporting before PR creation.

## Suggested Task Breakdown

- Follow-up issue A: implement metadata-first Reader Explorer navigation,
  explicit owner-only full-info drilldowns and preserved local fixture reader
  access.
- Follow-up issue B: optional Explorer filtering/search over safe metadata only,
  if the owner still needs it after the first slice.
- Follow-up issue C: optional docs-sync after implementation is verified and
  merged.

## Suggested Implementer Prompt

Implement the approved #342 follow-up slice using
`docs/admin-reader-explorer-architecture-review.md` as the safety contract.
Keep the Advanced `Reader Explorer` overview metadata-first; preserve
login/session and `Cache-Control: no-store`; put full raw diagnostic information
only behind explicit owner-only diagnostic drilldowns; exclude secrets; do not
add raw-text JSON APIs, archive content, telemetry, support artifacts, release
evidence, legal/privacy copy, public routes, or normal admin details. Reuse the
existing `/admin/logs/{run_id}/reader` and Text Diagnostics routes where
possible. Add focused auth/no-store, empty state, user list, selected user/run
link, long filename, full-info drilldown, secret-exclusion, and redaction tests.
