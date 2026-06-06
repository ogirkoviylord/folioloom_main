# Admin Reader Explorer Architecture Review

## Scope

This document is the architecture-first artifact for GitHub issue #342,
`Admin Reader: turn Advanced Reader into Reader Explorer`.

The requested product direction is accepted for architecture review only:
`Admin -> Advanced -> Reader` may become a `Reader Explorer` that lets the
owner navigate from safe user references to safe translation/file/run metadata,
then explicitly open the existing run-scoped owner-only Reader.

Implementation remains gated by a separate owner approval after this review.

## Routing Receipt

- Classification: risky task.
- Risk level: high.
- Primary agent role and repo-level skill: Architect Agent,
  docs-only diff is ready.
  `docs/RISK_REGISTER.md`, `docs/QUALITY_GATES.md`.
- Code evidence inspected: `src/translator_service/admin/routes.py`,
  `src/translator_service/admin/views.py`, `tests/test_admin_routes.py`,
  `tests/test_internal_reader.py`.
- Human approval status: approved for architecture review by issue #342;
  missing for implementation after this review.
- Allowed action: analysis and docs-only architecture record.
- Verification plan for this PR: docs gate review plus `git diff --check`.

## Verdict

NEEDS SPLIT and NEEDS HUMAN APPROVAL before implementation.

The safe implementation shape is feasible as a small admin navigation layer if
the Explorer remains metadata-only and only links into existing raw diagnostic
surfaces. The implementation must not add new raw-text lists, JSON APIs,
archives, telemetry, support artifacts, or normal admin details.

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
  metadata, provided raw text fields are not read or rendered.
- User references may include Telegram-style ids or other existing safe admin
  identifiers already present in metadata-only admin views.

## TBD / Unknown

- TBD: the owner must explicitly approve the follow-up implementation issue
  after this architecture review.
- TBD: exact Explorer URL shape, for example `/admin/reader` versus preserving
  `/admin/internal-reader` as the entry route.
- TBD: whether the existing approved-local-fixture reader form remains on the
  same page under a secondary entry or moves to a separate `Local fixtures`
  sub-view.
- Unknown: current CI status for any future implementation PR until the PR
  checks page is inspected.

## Affected Components

- `src/translator_service/admin/routes.py`: add metadata-only Explorer routes
  or repurpose the existing `/admin/internal-reader` entry route; keep
  `_protected_page(...)` and `no-store`.
- `src/translator_service/admin/views.py`: change the Advanced nav label to
  `Reader Explorer` and add safe Explorer list views.
- `src/translator_service/admin/translation_logs.py`: read only existing safe
  summaries/details metadata for Explorer lists; do not expose raw fragment
  text or review mark contents.
- `src/translator_service/user_activity.py`: optional source for safe user
  references and event/job/run relationships.
- `tests/test_admin_routes.py`: auth/no-store, metadata-only Explorer lists,
  selected user/run link, and redaction assertions.
- `tests/test_internal_reader.py`: only if the local fixture reader route or
  form behavior changes.

## Privacy Boundary

Explorer pages are navigation and triage surfaces, not raw diagnostics.

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
- link to existing run-scoped Reader.

Forbidden in Explorer lists, normal admin JSON APIs, safe archives, telemetry,
issues/PRs, support notes, and evidence packets:

- source document text;
- translated text;
- prompt text or provider payloads;
- persisted Reader review mark text;
- stack traces;
- object-storage paths or runtime `var/` paths;
- API keys, provider internals, secrets, tokens, or passwords.

Raw source and translated text may appear only after the owner explicitly opens
the existing owner-only raw diagnostic route, such as
`/admin/logs/{run_id}/reader` or `/admin/logs/{run_id}/text-diagnostics`.

## Risks

- High privacy/user-data risk if the Explorer copies raw fields from existing
  diagnostics into list rows.
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
- Explorer redaction test seeds raw-looking source text, translated text, prompt
  text, traceback-like text, storage paths, and review marks, then asserts none
  appear in Explorer HTML, normal details, JSON API payloads, downloads,
  telemetry fixtures, or test artifacts.
- Existing dedicated Reader/Text Diagnostics tests continue to prove raw text is
  confined to owner-only `no-store` diagnostic surfaces.
- Verification commands for code PR:
  `PYTHONPATH=src python3 -m unittest tests.test_admin_routes tests.test_internal_reader`;
  `PYTHONPATH=src python3 -m compileall src`;
  targeted `python3 -m ruff check --select F,I` on changed Python files;
  `git diff --check`.

## Required Docs Updates For Follow-Up Implementation

  changes the admin navigation/Reader contract.
- Do not update release readiness, Gate B/C/D status, legal/privacy policy, or
  production readiness from this feature alone.
- If implementation adds or moves a raw diagnostic entry point, update
  `docs/RISK_REGISTER.md` only with owner approval and reviewer evidence.

## Required Approval Gates

Implementation requires explicit owner approval after this architecture review
because it touches admin raw-text diagnostics, user-data navigation, and the
R-037/R-038 boundary.

Separate approvals are required for any of the following:

- new raw-text route or API;
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
2. Keep the first implementation metadata-only and server-rendered under
   Advanced.
3. Preserve the existing run-scoped Reader and Text Diagnostics routes as the
   only raw text surfaces.
4. Rename the Advanced nav label from `Reader` to `Reader Explorer`.
5. Add Explorer empty/user/user-detail states using safe summary objects.
6. Link each selected run to `/admin/logs/{run_id}/reader`.
7. Keep the approved local fixture reader reachable, either as a secondary
   Explorer state or a clearly named local-fixture route.
8. Add focused route/view/redaction tests before implementation is considered
   PR-ready.
9. Run focused admin/reader tests, compileall, targeted ruff, and
   `git diff --check`.
    reporting before PR creation.

## Suggested Task Breakdown

- Follow-up issue A: implement metadata-only Reader Explorer navigation and
  preserve existing local fixture reader access.
- Follow-up issue B: optional Explorer filtering/search over safe metadata only,
  if the owner still needs it after the first slice.
- Follow-up issue C: optional docs-sync after implementation is verified and
  merged.

