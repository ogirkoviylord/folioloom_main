# Roadmap

This roadmap is the active work queue. Historical phase narratives and old backlog candidates are archived at `docs/archive/project-memory/ROADMAP.full-before-trim.md`.

## Current Milestone

Free closed beta.

Goal: trusted users can translate authorized TXT/DOCX/EPUB documents through Telegram with safe limits, visible operations, recoverable runtime state and enough real-file quality evidence.

## Roadmap Principles

- Keep scope tight until closed beta works.
- Prefer small focused issues over broad rewrites.
- Do not treat historical plans as active work unless re-linked here.
- Do not expand formats/channels/payment/public surfaces without owner approval.
- Release readiness depends on evidence, not docs optimism.

## Immediate Priorities

### Gate B closure

- TTL cleanup/delete verification.
- Real-file TXT/DOCX/EPUB release matrix and report.
- EPUBCheck or equivalent validation.
- DOCX openability/visual QA.
- Cancel/resume/restart validation.
- Backup visibility and restore rehearsal evidence.
- Alerts MVP.
- Approved beta-server smoke evidence.

### Agent/documentation efficiency

- Keep owner-local mode.
- Reduce mandatory context reads.
- Archive long history without deleting it.
- Update repo-level skills so routine implementation does not load heavy docs by default.
- Add `.aiignore` or tool-equivalent exclusions for generated/runtime/archive-heavy paths if supported.

### Glossary readiness

- Keep scanner v1 plus candidate-quality gates.
- Treat latest automatic live smoke as no-go.
- Use local/fake/provider-boundary evidence as planning evidence only.
- Require new reviewed evidence before runtime glossary quality/rollout claims.

## Next Priorities

### Core workflow hardening

- Validate cancellation and partial output behavior on representative files.
- Validate restart/recovery flows.
- Review Telegram UX for confusing or failure-prone states.
- Ensure admin visibility shows enough to operate closed beta safely.

### Real-file quality

- Run representative real-file TXT/DOCX/EPUB matrix.
- Record pass/fail evidence without overclaiming quality.
- Separate structural validity, semantic quality and release readiness.
- Keep raw QA evidence owner-local unless explicitly published.

### Operations

- Make backup status visible enough for beta operation.
- Rehearse restore flow and record evidence.
- Confirm server smoke procedure and target environment approval requirements.
- Keep admin SSH-tunnel-only.

## Later / Deferred

- Paid beta.
- Public production.
- Public website/customer portal.
- WhatsApp/Discord/public API channels.
- User-facing provider/model picker.
- Batch ZIP or arbitrary file parser.
- Future formats beyond TXT/DOCX/EPUB.
- Advanced BI or large product expansion.
- Public admin exposure.

## Backlog Candidates

Keep candidates small and promote only when owner accepts priority.

- Alerts MVP.
- Backups visibility page.
- Better owner-only diagnostic archive navigation.
- Improved real-file QA reporting.
- Future glossary quality review workflow.
- Future scanner v2 shadow extractor if evidence warrants it.
- Future format architecture reviews.
- Payment support/refund policy draft after free beta evidence.

## How Agents Should Use This Roadmap

- For small implementation, do not read old roadmap history.
- For planning, start here and then open archive only for older rationale.
- For future formats/payment/public launch, route through idea intake and architecture/release review.
- If an item is not here, do not assume an old plan makes it active.
