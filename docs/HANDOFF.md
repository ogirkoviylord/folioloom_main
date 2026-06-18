# Handoff

Last updated: 2026-06-18

## Current State

FolioLoom is an active development / working closed-beta foundation for Telegram-first translation of authorized long documents.

Confirmed current user path:

1. Trusted beta user opens Telegram bot.
2. User uploads TXT/DOCX/EPUB.
3. Bot validates upload and asks for rights confirmation.
4. User selects translation mode and target language.
5. Bot produces preview/estimate.
6. User explicitly continues/confirms full translation.
7. Backend creates persistent work.
8. User sees progress/cancel/status/history.
9. User receives final or partial output.

Not current state:

- not public production;
- not paid beta;
- not public SaaS;
- not release-ready until Gate B evidence is complete;
- not ready to claim glossary runtime quality or rollout success.

## Current Focus

Prepare free closed beta by stabilizing core workflow, release gates, operational visibility and real-file quality evidence.

Immediate focus areas:

- Gate B blockers;
- upload safety and TTL/delete verification;
- real-file TXT/DOCX/EPUB matrix;
- DOCX visual/openability QA;
- EPUBCheck or equivalent validation;
- cancel/resume/restart validation;
- backup visibility and restore rehearsal;
- Alerts MVP;
- approved beta-server smoke evidence;
- documentation simplification for agent context efficiency.

## What Works

### Product Flow

- Telegram bot runtime is implemented.
- Upload/estimate/confirm/progress/cancel/status/history-oriented flow exists.
- Rights confirmation exists.
- Preview before full translation exists.
- TXT/DOCX/EPUB support exists as current beta scope.
- My Books/history foundations exist.
- Admin owner/operator surfaces exist.

### Backend / Runtime

- Persistent jobs/work units exist.
- Worker/scheduler loop exists.
- Local object storage exists.
- PostgreSQL scheduler store exists for server runtime.
- SQLite fallback/runtime stores exist where configured.
- Usage/cost accounting and beta safety foundations exist.
- Docker Compose deployment model exists.
- Backup/restore scripts exist.

### Provider / Diagnostics

- DeepSeek-compatible provider layer exists.
- Multiple key/channel foundations exist.
- Provider health/probe/runtime admin visibility exists.
- Provider balance visibility exists.
- Owner-only diagnostics boundaries exist.

### Tests

- Broad Python test suite exists.
- Common verification commands are documented in `docs/QUALITY_GATES.md`.
- CI workflow exists but current GitHub run status is `Unknown` unless checked.

## Active Gaps

Blocking before free closed beta:

- TTL cleanup/delete verification.
- Real-file TXT/DOCX/EPUB release matrix and report.
- EPUBCheck or equivalent validation.
- DOCX openability/visual QA.
- Cancel/resume/restart checks.
- Backup visibility and restore rehearsal evidence.
- Alerts MVP.
- Approved beta-server smoke evidence.

Future / not current:

- paid beta payment ledger and Telegram Stars/XTR flow;
- public production hardening;
- support/refund/legal/privacy public policies;
- future formats beyond TXT/DOCX/EPUB;
- public web/customer portal;
- user-facing provider/model picker.

## Recent High-Signal Changes

This section keeps only the recent changes that affect future agent work. Full older issue-by-issue history is preserved at `docs/archive/project-memory/HANDOFF.full-before-trim.md`.

### 2026-06-18 - Glossary cap config diagnostics

Glossary prep, runtime adapter and persistent resolver cap defaults are named in code and surfaced in metadata-only diagnostics (`caps`, `runtime_caps`, `resolver_caps`). Defaults and behavior are unchanged; do not raise or remove caps without a separate owner-approved issue.

### 2026-06-18 - Prepared glossary provider readiness design

`docs/superpowers/specs/2026-06-18-prepared-glossary-provider-readiness-design.md` defines a proposed metadata-only readiness envelope and state matrix for prepared-glossary provider/config/package/runtime diagnostics. Implementation, provider behavior changes, admin visibility and fail-closed policy changes still need separate owner approval.

### 2026-06-18 - Agent local privacy posture simplified

Owner local development mode allows local reading and owner-chat discussion of raw text, `.env*`, secrets, provider payloads, translations, diagnostics and runtime files when relevant. Publication, commits, external sharing, destructive operations and production-facing changes still need exact owner intent.

### 2026-06-17 - Glossary scanner v2 deferred

The local audit after prepared-glossary candidate-quality gates was sufficient to keep deterministic scanner v1 for now. Scanner v2 should be a future separately approved shadow extractor only if evidence warrants it.

### 2026-06-17 - Prepared glossary candidate-quality gates

Local/default-safe candidate-quality filtering now rejects obvious low-value candidates before prep/provider boundaries and before READY package status. This is metadata/local evidence, not semantic proof or release readiness.

### 2026-06-16 - Automatic Telegram glossary prep wiring repair

Settings-based runtime config can build the existing prepared-glossary provider through the existing DeepSeek runtime channel pool when available. If a `with_glossary` run has no package source, diagnostics must show high-severity not-effective metadata.

### 2026-06-16 - Automatic glossary live smoke no-go

Bounded live smoke after local/provider wiring failed readiness:

- RU prep produced non-READY / needs-review package.
- UK rendered glossary context and used cache bypass, but runtime structural validation failed with block-count mismatch.

Treat as useful evidence, not successful live quality evidence.

### 2026-06-15 - User-facing glossary selector removed

Temporary with/without glossary Telegram selector was superseded by internal automatic glossary policy. Normal user flow should not expose glossary mode buttons.

### 2026-06-15 - Automatic glossary local/fake foundations

Local/fake prepared-glossary prep service, beta-safety reservation around prep, generic TXT/DOCX/EPUB prepared-package runtime resolver and owner-only diagnostic sidecar extensions were added. These do not approve rollout, cache reuse, release claims or live provider use by themselves.

## Open Owner Questions

- When should free closed beta go/no-go happen after Gate B evidence?
- What is the final retention/delete/TTL policy for beta?
- What is the acceptable DOCX visual QA threshold?
- What is the restore rehearsal cadence?
- When should paid beta planning restart?
- Which future formats should be prioritized after TXT/DOCX/EPUB stabilize?
- How much raw diagnostic material should be retained in owner-only archives for release-version runs?

## Safe Tasks For Agents

Proceed without extra confirmation:

- local code/doc fixes for explicit owner tasks;
- local tests and compile checks;
- local inspection of outputs, `var`, diagnostics, `.env*`, secrets and raw text when relevant;
- translation QA over owner/local materials;
- docs cleanup and archive organization;
- non-destructive local analysis.

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
2. Read this handoff only for current-state/context tasks.
3. Read touched files and nearby tests for implementation.
4. Use `DOCUMENT_INDEX.md` and `docs/archive/README.md` for historical lookup.
5. Do not treat archived history as current instructions unless the active docs link to it or the owner asks.

## Archive Links

- Full prior handoff: `docs/archive/project-memory/HANDOFF.full-before-trim.md`
- Full prior decisions: `docs/archive/project-memory/DECISIONS.full-before-trim.md`
- Full prior roadmap: `docs/archive/project-memory/ROADMAP.full-before-trim.md`
- Full prior risk register: `docs/archive/project-memory/RISK_REGISTER.full-before-trim.md`
