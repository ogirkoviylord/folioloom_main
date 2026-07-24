# FolioLoom Current Project State

Date: 2026-07-24

## Summary

FolioLoom is being reframed from a Telegram-first translation bot into a CAT-like author/rightsholder translation workbench for authorized long documents.

Current product thesis:

1. import authorized TXT/DOCX/EPUB;
2. preserve document structure and stable segments;
3. let the author/operator review and edit glossary/terminology;
4. generate translation draft/suggestions;
5. surface QA/glossary/structure findings;
6. export a usable translated document;
7. keep Telegram as a convenient upload/test/delivery harness, not the defining product surface.

Canonical strategy issue: [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813)
Canonical gate document: `docs/CAT_WORKFLOW_GATES.md`

The project is not free beta ready, paid beta ready or public production ready.

## Workbench Visual Direction (owner decision)

- The current visual/product baseline is **Premium Author Studio**, selected after a local Figma comparison. It is a design reference for later Workbench work, not an implementation approval.
- The primary Workbench should be a calm author-centred product room, not the existing Admin, Telegram harness, a generic AI dashboard, CAT/TMS cockpit, spreadsheet-like glossary table, or a text-editor-first shell.
- The prior Reader-First exploration is not the default product surface. A future distraction-free editor/focus mode may hide surrounding chrome while retaining editor capability; a separate warm, low-strain comfort-reading mode is also a deferred possibility. Its control belongs in later interface settings/exploration rather than the main Workbench screen.
- No code, interaction contract, storage/auth model, Figma implementation packet, or release/readiness claim follows from this visual choice.

## Stack

- Python 3.13.
- aiogram Telegram runtime, now treated as harness/auxiliary channel.
- FastAPI API/admin app.
- Docker Compose services: `api`, `bot`, `worker`, `postgres`, `redis`.
- PostgreSQL scheduler storage for server runtime.
- SQLite fallback/runtime stores where explicitly configured.
- Local object storage under host `./var`.
- DeepSeek-compatible provider layer.
- TXT/DOCX/EPUB planners, adapters and assembly.

## Implemented Foundations

### Bot and User Flow

- Telegram upload/estimate/confirm/progress/cancel/status/history-oriented flow exists.
- Rights confirmation exists.
- Preview before full translation exists.
- Partial/final output handling exists.
- My Books/history foundations exist.

These foundations remain useful for testing and delivery, but Telegram is no longer the primary product definition.

### Translation Core

- TXT, DOCX and EPUB extraction/planning/assembly exist.
- Persistent planners and persistent assembly exist for final and partial outputs.
- Format adapters have structure preservation foundations.
- Output contract checks and repair paths exist.
- Russian/Ukrainian quality/profile foundations exist.

### Glossary / Terminology

- Local/fake prepared-glossary foundations exist.
- Candidate-quality gates exist.
- Owner-only diagnostics boundaries exist for glossary runtime sidecars.
- Scanner v2 is deferred unless fresh evidence warrants it.
- Local approval/rehearsal, bounded Workbench controls, pure DOCX preflight and truthful local-observation behavior are merged local-prototype foundations. They do not establish durable document authority, runtime activation or a Gate 2 workflow.

Blocking caveat:

- Automatic/internal glossary runtime is not release-ready.
- Recent live automatic glossary evidence was no-go: RU prep did not produce a READY package; UK rendered glossary context but runtime structural validation failed.
- Do not claim glossary runtime quality, rollout readiness, cache reuse readiness or release readiness without new reviewed evidence.

### Backend, Persistence and Worker

- Local object storage for source, intermediate, partial and final files.
- SQLite local/fallback job/work-unit storage where configured.
- PostgreSQL scheduler store for server runtime.
- Scheduler runner and worker loop.
- Work-unit leases, retries, usage accounting, worker heartbeats and output keys.
- Beta-safe concurrency and provider-capacity foundations.
- Beta safety guard: kill switch, cost caps, reservation/accounting and admin visibility.

### Provider / Diagnostics

- DeepSeek-compatible chat completion client.
- Multiple internal API channel/key support.
- Key selection/failover/cooldown foundations.
- Adaptive throttling and provider circuit behavior.
- Admin-visible provider health/runtime/probe/balance surfaces.

### Admin / Operations

- Owner/admin login/session foundation.
- Settings, beta allowlist, provider keys/health, operations, live monitor, costs, security/audit surfaces.
- SSH-tunnel-only admin posture for owner/trusted operation.
- Docker Compose stack and deployment/restore scripts.
- Backup/restore tooling and runbooks.

## Current Main Gaps

### Product / quality gaps before design-partner alpha

- The owner-approved local-only snapshot-lock sequence is merged through #836; next reconcile current strict-DOCX durable binding seams before proposing any durable implementation. This remains local-prototype evidence only; see `docs/GLOSSARY_WORKBENCH_COUNCIL_SYNTHESIS.md`.
- Glossary preflight status and post-run compliance report.
- CAT-like source-target/segment review workflow.
- Representative before/after quality evidence with glossary controls.
- Export from current approved/edit state.

### Operational safety carry-forward

Old Gate B items remain useful but are not the product release compass by themselves:

- CAT real-file import/segment/glossary/export matrix (#75).
- CAT DOCX export LibreOffice visual QA (#76).
- CAT workflow cancel/resume/restart recovery (#81).
- CAT project TTL cleanup/delete behavior (#82).
- CAT Alerts owner report (#83).
- CAT Backups owner report (#84).
- Approved backup export manifest verification (#85).
- Restore rehearsal for CAT project state (#86).
- CAT app/server smoke evidence, bot harness optional (#87).

## Current Gates

Active gate model lives in `docs/CAT_WORKFLOW_GATES.md`.

Immediate gates:

- Gate 0: product reframe / scope lock.
- Gate 1: glossary / terminology control prototype.
- Gate 2: CAT-like author workflow thin slice.
- Gate 3: quality evidence gate.

Later gates:

- design partner free alpha;
- operational safety gate;
- paid pilot;
- self-serve paid beta;
- public production.

## Common Verification

- Full unit suite: `PYTHONPATH=src python3 -m unittest discover -s tests`
- Targeted unit tests: `PYTHONPATH=src python3 -m unittest tests.test_<module>`
- Compile: `PYTHONPATH=src python3 -m compileall src`
- Local predeploy: `scripts/predeploy_check.sh`
- Server smoke: `scripts/server_smoke_check.sh` only with owner-approved environment access.

## Historical Detail

The longer pre-trim state snapshot is archived at `docs/archive/project-memory/CURRENT_PROJECT_STATE.full-before-trim.md`.
