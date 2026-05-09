# Prompt For ChatGPT Pro: FolioLoom Restart

You are helping restart the FolioLoom project.

FolioLoom is a Telegram-first document translation service for books,
chapters, manuscripts, and authorized long-form documents. The current stack is
Python 3.13, aiogram, FastAPI, Docker Compose, PostgreSQL/SQLite scheduler
storage, local object storage, and DeepSeek-compatible translation APIs.

Your task is to read the attached project documents and produce a new,
edited, practical technical specification and roadmap.

Important context:

- The project has moved beyond the early README prototype description.
- The current repository state is a working closed-beta foundation, not a paid
  public production service.
- The main goal now is to decide the next correct direction, remove outdated
  plans, and produce one coherent restart specification.

Please produce:

1. A concise product definition: what FolioLoom is and is not.
2. A cleaned-up technical specification for the next phase.
3. A realistic roadmap split into:
   - immediate stabilization,
   - closed beta,
   - paid beta,
   - public production.
4. A must-fix blocker list.
5. A "do not build yet" list.
6. A release-gate checklist for each stage.
7. A recommended architecture decision: free closed beta first vs paid beta
   first.
8. A documentation cleanup plan: which old docs should be kept, merged,
   archived, or rewritten.
9. A concrete next 2-week engineering plan.

Please be strict and practical. Avoid adding new ideas unless they directly
help reach a stable beta. Compare all documents against the real current
state summarized in `CURRENT_PROJECT_STATE.md`.

Recommended reading order:

1. `CURRENT_PROJECT_STATE.md`
2. `README.project.md`
3. `docs/superpowers/specs/2026-05-03-deepseek-document-telegram-bot-design.md`
4. `docs/superpowers/specs/2026-05-08-folioloom-admin-console-design.md`
5. `docs/superpowers/specs/2026-05-09-folioloom-pricing-v0.md`
6. `docs/superpowers/plans/2026-05-09-admin-server-diagnostics-fix-plan.md`
7. `docs/superpowers/plans/2026-05-09-admin-practical-ops-roadmap.md`
8. `docs/deployment/admin-vps-runbook.md`
9. `docs/deployment/restore-runbook.md`
10. `DOCUMENT_INDEX.md`
