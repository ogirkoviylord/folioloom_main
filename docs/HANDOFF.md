# Handoff

Last updated: 2026-07-24

## Current State

FolioLoom is being reframed from a Telegram-first translation bot into a CAT-like author/rightsholder translation workbench for authorized long documents.

Canonical strategy issue: [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813)
Canonical gate document: `docs/CAT_WORKFLOW_GATES.md`

New intended workflow:

1. Import authorized TXT/DOCX/EPUB.
2. Preserve document structure and stable segments.
3. Review/edit glossary and terminology.
4. Generate translation draft/suggestions.
5. Surface QA/glossary/structure findings.
6. Export a usable translated document.
7. Use Telegram as upload/test/delivery harness where useful.

Not current state:

- not free beta ready;
- not paid beta ready;
- not public SaaS;
- not public production;
- not ready to claim automatic glossary runtime quality or rollout success;
- not ready to claim CAT-like author workflow readiness.

## Current Focus

Immediate focus areas:

- Gate 0: product reframe / scope lock around #813.
- Gate 1: the owner-approved bounded local snapshot-lock sequence is merged through #836; next reconcile current strict-DOCX durable binding seams before proposing durable implementation. See `docs/GLOSSARY_WORKBENCH_COUNCIL_SYNTHESIS.md`.
- Gate 2: CAT-like author workflow thin slice.
- Gate 3: representative quality evidence.
- Keep old Gate B operational work as carry-forward safety infrastructure, not as the product roadmap.

## What Works

### Existing foundations

- Telegram bot runtime is implemented and remains useful as harness.
- Upload/estimate/confirm/progress/cancel/status/history-oriented flow exists.
- Rights confirmation exists.
- Preview before full translation exists.
- TXT/DOCX/EPUB support exists as current format scope.
- My Books/history foundations exist.
- Admin owner/operator surfaces exist.
- Persistent jobs/work units exist.
- Worker/scheduler loop exists.
- Local object storage exists.
- PostgreSQL scheduler store exists for server runtime.
- SQLite fallback/runtime stores exist where configured.
- Usage/cost accounting and beta safety foundations exist.
- Docker Compose deployment model exists.
- Backup/restore scripts exist.
- DeepSeek-compatible provider layer exists.
- Multiple key/channel foundations exist.
- Provider health/probe/runtime admin visibility exists.

### Glossary foundations

- Local/fake prepared-glossary prep and package validation foundations exist.
- Candidate-quality gates exist.
- Owner-only diagnostics boundaries exist.
- Scanner v2 is deferred unless fresh evidence warrants it.
- Local approval/rehearsal, a bounded Workbench shell, pure DOCX preflight and truthful local-observation fixes are merged local-prototype foundations, not durable approval/custody or runtime authority.

Blocking caveat:

- Automatic/internal glossary runtime is not release-ready.
- Recent live automatic glossary smoke was no-go.
- Do not claim live glossary quality, runtime rollout readiness, cache reuse readiness or paid/free beta readiness from current glossary evidence.

## Active Gaps

### Product / quality gaps

- Manual glossary import/editor/control path.
- Preflight glossary readiness/status.
- Post-run glossary compliance report.
- Source-target/segment review surface or equivalent CAT thin slice.
- Representative before/after evidence on real documents.
- Export from approved/edit state.

### Operational safety carry-forward

- #75 CAT real-file import/segment/glossary/export matrix.
- #76 CAT DOCX export LibreOffice visual QA.
- #81 CAT workflow cancel/resume/restart recovery.
- #82 CAT project TTL cleanup/delete behavior.
- #83 CAT Alerts owner report.
- #84 CAT Backups owner report.
- #85 approved backup export manifest verification.
- #86 restore rehearsal for CAT project state.
- #87 CAT app/server smoke evidence, bot harness optional.

Old #88 was closed as superseded by #813. Future final report should be a CAT Beta Readiness Report.

## Recent High-Signal Changes

### 2026-06-29 — CAT-like gate reframe

Owner accepted that the old Gate B/C plan no longer fits the product direction. The canonical issue is #813 and the canonical doc is `docs/CAT_WORKFLOW_GATES.md`.

Key decision:

- Telegram is retained as harness.
- The product direction is author/rightsholder CAT-like workflow.
- Glossary/terminology control is a core quality prerequisite.
- Old Gate B items are operational-safety carry-forward.
- Paid beta is blocked until quality/workflow evidence exists.

### 2026-06-29 — Old Gate B issue cleanup/rewrite

Old operational issues #75-#87 were retitled/commented as CAT operational-safety carry-forward. Old #88 was closed as superseded by #813.

### 2026-06-18 — Scanner v2 shadow work remains deferred

Issue #692 keeps scanner v1 active and does not create a scanner-v2 shadow implementation issue from the expanded #688-#692 chain. Future scanner-v2 work requires fresh metadata-only evidence of persistent scanner-level misses after #689/#690 gates.

### 2026-06-18 — Prepared glossary candidate-quality / reducer work

Prepared glossary local/default-safe candidate-quality filtering and reducer diagnostic backfill improved local evidence, but did not prove real provider behavior, real-book translation quality, runtime rollout, cache reuse or release readiness.

### 2026-06-16 — Automatic glossary live smoke no-go

Bounded live smoke after local/provider wiring failed readiness:

- RU prep produced non-READY / needs-review package.
- UK rendered glossary context and used cache bypass, but runtime structural validation failed with block-count mismatch.

Treat as useful evidence, not successful live quality evidence.

### 2026-07-24 — Glossary Engine → Workbench Council synthesis and completed local snapshot-lock sequence

All GPT, DeepSeek, MiMo and owner-required GLM Council lanes completed. The owner approved the bounded local-only in-memory snapshot-lock contract; its local approval/rehearsal, preflight, observation and Workbench wiring sequence is merged through #836. It binds an opaque local reference to the exact snapshot signature, invalidates on selected-content or signature change and fails closed before selection/rendering/preflight. This remains local-prototype evidence only, not durable custody/authority, runtime activation, Gate 1 closure or a Gate 2 workflow claim. The next technical route is strict-DOCX durable-binding reconciliation. See `docs/GLOSSARY_WORKBENCH_COUNCIL_SYNTHESIS.md`.

## Open Owner Questions

- What exact ICP should Gate 0 target first: author, editor, rightsholder or small publisher?
- What is the minimum manual glossary control surface for Gate 1?
- Which 3-5 representative documents should be used for first before/after evidence?
- What threshold makes a translation “usable draft” for design-partner alpha?
- What is the final retention/delete/TTL policy for CAT projects?
- When should paid beta planning restart after quality/workflow evidence?

## Safe Tasks For Agents

Proceed without extra confirmation:

- local code/doc fixes for explicit owner tasks;
- local tests and compile checks;
- local inspection of outputs, `var`, diagnostics, `.env*`, secrets and raw text when relevant;
- translation QA over owner/local materials;
- docs cleanup and archive organization;
- no-code planning and issue comments that stay metadata-only and within owner instructions.

Ask first:

- deploy/server/public exposure;
- branch push or PR open/update unless the owner asked to make/publish a PR;
- merge/release/tag/direct `main` changes;
- destructive runtime data operations;
- migrations/retention/TTL/backups/restore changes;
- payment/legal/public privacy/support changes;
- meaningful live provider spend;
- external publication of raw private material.

## Next-Agent Instruction

Start with the task, not the archive.

1. Read `AGENTS.md`.
2. For strategy/release questions, read `docs/CAT_WORKFLOW_GATES.md` and #813 first.
3. For current-state/context tasks, read this handoff and `CURRENT_PROJECT_STATE.md`.
4. For implementation, read touched files and nearby tests.
5. Use `DOCUMENT_INDEX.md` and `docs/archive/README.md` for historical lookup.
6. Do not treat old Gate B/C as the active product roadmap.
7. Do not treat archived history as current instructions unless the active docs link to it or the owner asks.

## Archive Links

- Full prior handoff: `docs/archive/project-memory/HANDOFF.full-before-trim.md`
- Full prior decisions: `docs/archive/project-memory/DECISIONS.full-before-trim.md`
- Full prior roadmap: `docs/archive/project-memory/ROADMAP.full-before-trim.md`
- Full prior risk register: `docs/archive/project-memory/RISK_REGISTER.full-before-trim.md`
