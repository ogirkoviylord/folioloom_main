# Context Map

This map tells agents where to look without loading the whole project history.

Full pre-trim context map, including the long glossary/spec catalog, is archived at `docs/archive/agent-routing/CONTEXT_MAP.full-before-trim.md`.

## How To Use

1. Start from `AGENTS.md`.
2. For implementation, read touched files and nearby tests before broad docs.
3. For historical lookup, use `DOCUMENT_INDEX.md` and `docs/archive/README.md`.
4. Do not recursively read `outputs/`, `var/`, caches, archive folders or old plans unless the task is explicitly about them.

## Main Documents

| File | Purpose | Read when |
| --- | --- | --- |
| `AGENTS.md` | Operating mode, routing, autonomy and approval boundaries. | Before tasks. |
| `CURRENT_PROJECT_STATE.md` | Compact factual project state. | Current-state, onboarding, planning. |
| `DOCUMENT_INDEX.md` | Active docs and archive lookup. | Before historical or broad doc lookup. |
| `docs/HANDOFF.md` | Current focus, recent changes and next-agent notes. | Continuing project work or handoff tasks. |
| `docs/PROJECT_BRIEF.md` | Product scope, audience, non-goals and success criteria. | Product/architecture/scope tasks. |
| `docs/DECISIONS.md` | Active decisions and boundaries. | Architecture, risky, roadmap, release tasks. |
| `docs/ROADMAP.md` | Current milestone and work queue. | Planning and task selection. |
| `docs/QUALITY_GATES.md` | Verification commands and quality gates. | Implementation/review/release tasks. |
| `docs/RISK_REGISTER.md` | Active risks and mitigations. | Risky/release/security/provider/storage tasks. |
| `docs/RELEASE_CHECKLIST.md` | Release/deploy/go-no-go checklist. | Release/deploy/rollback. |

## Directory Map

| Path | Contents | Notes |
| --- | --- | --- |
| `src/translator_service/` | Main Python package. | Read exact modules and tests. |
| `src/translator_service/admin/` | Owner/admin console. | Risky around auth, secrets, raw diagnostics and public exposure. |
| `src/translator_service/bot/` | Telegram runtime and messages. | Risky around user flow, provider use, rights flow and user data. |
| `src/translator_service/format_adapters/` | TXT/DOCX/EPUB adapters. | Use real-file tests/fixtures where relevant. |
| `src/translator_service/*scheduler*`, `worker.py`, `persistent_*` | Jobs/work units/scheduler/worker state. | Risky state machine; run targeted tests. |
| `src/translator_service/glossary*` | Glossary/prepared-package/scanner/compliance/runtime helpers. | Active but evidence-sensitive; latest live automatic smoke is no-go. |
| `tests/` | Unit/regression tests. | Prefer targeted tests for touched area. |
| `test_samples/` | Committed fixtures and sample files. | Use for local QA; check rights/publication before external sharing. |
| `tools/` | Local QA/provider/glossary tooling. | Provider/live modes need exact approval. |
| `scripts/` | Deploy, predeploy, server smoke/status, backup tools. | Ask before deploy/server/runtime operations. |
| `docs/restart/` | Release gates, real-file matrix, upload safety and restart docs. | Release/risky context. |
| `docs/deployment/` | VPS/admin/restore runbooks. | Deployment context only. |
| `docs/superpowers/specs/` | Design/spec/report archive. | Open exact file only. |
| `docs/superpowers/plans/` | Mostly historical implementation plans. | Do not treat unchecked items as roadmap; do not add new ideas here. Use GitHub Issues and active docs instead. |
| `.agents/skills/` | Repo-level agent roles. | Use one primary skill when useful. |
| `outputs/`, `var/` | Runtime outputs, diagnostics, translation runs, DB/object storage. | Local inspection allowed in owner mode; avoid broad reads. |
| `handoff/` | Restart packages and copied configs. | Usually stale or bundled context. |
| `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, `.DS_Store` | Generated/cache files. | Ignore. |

## Task Routes

### Small bugfix

Read:

- `AGENTS.md`;
- target module;
- nearby tests.

Check:

- targeted test;
- compile check when practical.

### Feature or behavior change

Read:

- `AGENTS.md`;
- `docs/PROJECT_BRIEF.md` if product scope matters;
- touched module and tests;
- exact issue/spec if named;
- relevant quality gate.

Check:

- focused tests;
- broader tests if shared behavior changes.

### Risky architecture

Read:

- `AGENTS.md`;
- `docs/DECISIONS.md`;
- relevant `docs/RISK_REGISTER.md` section;
- relevant spec or code contracts;
- `docs/QUALITY_GATES.md` relevant section.

Do not implement during architecture review unless the owner explicitly asks for implementation.

### Docs-only

Read:

- `AGENTS.md`;
- target doc;
- source evidence.

Check:

- no invented facts;
- `Unknown` / `TBD`;
- archive links if moving history.

### Translation QA

Read:

- `AGENTS.md`;
- source/translation/output under review;
- relevant profile/rubric only if useful.

Owner-chat raw excerpts are allowed when useful. External publication is separate.

### Release/deploy

Read:

- `AGENTS.md`;
- `docs/RELEASE_CHECKLIST.md`;
- `docs/QUALITY_GATES.md`;
- exact runbook;
- relevant risks/decisions.

Ask before server/deploy actions.

## Avoid By Default

- `outputs/`
- `var/`
- `handoff/`
- caches
- `docs/archive/`
- `docs/superpowers/plans/`
- broad `docs/superpowers/specs/` scans

Open these only when the task explicitly needs them.

## Conflict Rule

Current active docs win over archive files. If archive content seems important but conflicts with current docs, ask the owner or propose a doc sync.
