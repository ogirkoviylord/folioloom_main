# Quality Gates

## 1. Назначение

Этот документ нужен Implementer Agent и Reviewer Agent, чтобы одинаково понимать, когда задача, PR, релиз или отдельное изменение считается достаточно качественным.

Задача не считается готовой, пока не выполнены relevant gates для ее типа и зоны риска. Если gate невозможно выполнить, агент обязан явно объяснить почему, указать риск и предложить follow-up или решение для человека.

Этот файл дополняет `AGENTS.md`, `docs/PROJECT_BRIEF.md`, `docs/DECISIONS.md`, `docs/CONTEXT_MAP.md` и `docs/restart/release-gates.md`. Он не заменяет release go/no-go владельца.

## 2. Общие правила качества

- Маленький focused diff.
- Нет изменений вне scope задачи.
- Нет silent behavior changes: любое изменение поведения должно быть явно описано.
- Тесты добавлены или причина отсутствия тестов объяснена.
- Docs обновлены, если изменилось поведение, контракт, запуск, эксплуатация или риск.
- High-risk зоны не изменяются без explicit human approval.
- Secrets, `.env*`, реальные ключи и runtime user data не трогаются.
- Production dependencies не добавляются без explicit human approval.
- Deployment, payments, pricing, auth, security, legal/privacy, user data handling и database migrations не меняются без explicit human approval.
- Проект нельзя называть public production-ready без подтвержденного Gate D и human owner approval.

## 3. Gate для любой задачи

- [ ] Задача соответствует acceptance criteria.
- [ ] Diff минимальный и понятный.
- [ ] Нет изменений вне scope.
- [ ] Нет изменений secrets/env/deployment без approve.
- [ ] Нет изменений auth/security/privacy/legal/payments без approve.
- [ ] Tests run указаны.
- [ ] Риски перечислены.
- [ ] Follow-up tasks указаны.

## 4. Gate для code changes

Confirmed: репозиторий является Python 3.13 проектом с `pyproject.toml`, пакет лежит в `src/translator_service/`, тесты лежат в `tests/`. Найдено 93 файла `tests/test_*.py`. `.github/workflows/checks.yml` exists and runs compile plus unit tests on pull requests and pushes to `main`. Owner decision on 2026-05-17: GitHub Actions Python checks are advisory for now, local gates remain required for PR-ready work, and current GitHub run/pass status is Unknown unless checked on the PR/checks page.

### Python

Commands found:

- Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests`
- Targeted unit tests: `PYTHONPATH=src python3 -m unittest tests.test_<module>`
- Compile check: `PYTHONPATH=src python3 -m compileall src`
- Current predeploy gate: `scripts/predeploy_check.sh`
- Targeted lint inside predeploy: `python3 -m ruff check <focused files>`
- Repo-wide ruff debt check, not a release blocker now: `python3 -m ruff check --no-cache src tests scripts`

Recommended:

- Для маленького code change: запустить targeted tests для touched зоны и `PYTHONPATH=src python3 -m compileall src`.
- Для изменения shared behavior, worker/scheduler, admin, provider layer, bot flow, storage, safety или file adapters: дополнительно запустить `PYTHONPATH=src python3 -m unittest discover -s tests`.
- Для release/predeploy-related change: запустить `scripts/predeploy_check.sh`.
- Если touched зона попадает в targeted ruff scope, запустить `python3 -m ruff check` на измененных файлах.

Unit tests:

- Gate: focused tests для измененной зоны должны проходить.
- Gate для broad/shared изменений: полный `unittest discover` должен проходить или failure должен быть объяснен как unrelated/known с evidence.

Integration tests:

- Commands found: dedicated integration suite не найден.
- Recommended: использовать relevant higher-level tests from `tests/` и `scripts/predeploy_check.sh`; для server/runtime behavior использовать `scripts/server_smoke_check.sh` только на approved environment.
- TBD: определить отдельный integration test command, если владелец хочет formal integration gate.

Lint:

- Commands found: targeted `ruff check` внутри `scripts/predeploy_check.sh`; repo-wide `ruff check --no-cache src tests scripts` документирован как не release blocker.
- Recommended: targeted ruff для измененных Python-файлов; repo-wide ruff использовать как debt signal, а не blocker для free closed beta.

Typecheck:

- Commands found: No dedicated mypy/pyright/pytype command found.
- Recommended: TBD. Возможный future gate: добавить approved typecheck tool и documented command только после human decision.

Formatting:

- Commands found: No dedicated formatting command found.
- Recommended: TBD. Возможный future gate: `python3 -m ruff format --check src tests scripts`, если владелец утвердит formatter policy.

Smoke test:

- Commands found: `scripts/predeploy_check.sh`; server smoke script `scripts/server_smoke_check.sh`.
- Recommended: локально запускать `scripts/predeploy_check.sh` перед predeploy/release changes; server smoke выполнять только при approved server access.

### Docker / infrastructure

Commands found:

- Compose config validation inside predeploy: `docker compose --env-file .env.server.example config`
- Current predeploy gate: `scripts/predeploy_check.sh`
- Server smoke: `scripts/server_smoke_check.sh`
- Server status helper: `scripts/server_status.sh`
- Backup export verification: `python3 scripts/verify_backup_export.py --help` is checked by predeploy; release Gate B requires backup export verification.

Recommended:

- Для Docker/deployment/script changes требуется explicit human approval before changing files.
- Before deploy-related handoff: run `scripts/predeploy_check.sh`.
- On target server, only with approved environment access: run `scripts/server_smoke_check.sh` and record output summary.
- Production deployment itself requires explicit human approval and must not be performed as a routine verification step.

## 5. Gate для documentation changes

- [ ] Документ не выдумывает факты.
- [ ] Unknown/TBD отмечены явно.
- [ ] Есть ссылки на связанные документы.
- [ ] Не противоречит `docs/DECISIONS.md`.
- [ ] Не обещает production-ready без подтверждения.
- [ ] Понятно, кто должен использовать документ.
- [ ] Confirmed facts отделены от assumptions.
- [ ] Safety, legal, privacy, security, payment и deployment guardrails не ослаблены.

## 6. Gate для risky changes

Любая risky change требует explicit human approval до изменения файлов или выполнения операций. Если approval не получен, агент должен остановиться на анализе и предложить безопасный план.

| Зона | Почему risky | Required approval | Required tests/checks | Rollback requirement | Documentation requirement |
| --- | --- | --- | --- | --- | --- |
| Database migrations | Может изменить durable job/work-unit state, scheduler correctness, SQLite/Postgres compatibility и recoverability. | Human owner approval до schema/state changes. | Targeted DB tests, scheduler/job tests, backup/restore impact check, compileall, relevant full suite. | План отката данных или forward-fix, backup before migration, restore rehearsal для release. | Обновить decisions/runbooks/context docs; указать compatibility и data handling. |
| Production deployment | Затрагивает VPS, availability, secrets, runtime data, admin exposure и user impact. | Human owner approval перед deploy. | `scripts/predeploy_check.sh`; на сервере `scripts/server_smoke_check.sh`; проверить health/admin tunnel only. | Rollback version/command, backup status, owner contact path. | Deployment notes/runbook update, release evidence. |
| Secrets | Утечка ключей Telegram/DeepSeek/admin/Postgres может скомпрометировать сервис и пользователей. | Human owner approval; real secrets не читать и не выводить. | Secret redaction checks, admin secrets tests, no real secrets in diff/logs. | Rotation plan for touched/possibly exposed secret. | Документировать только безопасные placeholders и masking rules. |
| Auth/security | Может ослабить admin access, RBAC, sessions, audit, telemetry или safety boundaries. | Human owner approval and Reviewer pass. | Relevant admin/auth/security tests, negative tests, `scripts/predeploy_check.sh` for release-adjacent changes. | Disable/revert plan, session/key invalidation if needed. | Update `docs/DECISIONS.md` only after approval; preserve SSH-tunnel-only admin rule. |
| Privacy/legal | Пользователь загружает documents with rights-sensitive content; неверный текст создает legal/privacy risk. | Human owner approval; legal/privacy claims need owner/counsel decision. | Docs review, no raw document text in logs/admin, redaction checks. | Remove/replace unapproved claims before release. | Use `TBD` for human legal decisions; do not invent policies. |
| Payments/pricing | Paid beta blocked; payment errors affect money, refunds, support and compliance. | Human owner approval before any payment/pricing changes. | Payment ledger/idempotency/refund/support tests if implemented; Gate C requirements. | Refund/reconciliation rollback path, disable paid path. | Pricing/payment docs marked draft until Gate C approval. |
| External API providers | Telegram/DeepSeek failures affect user flow, cost, provider keys and safe diagnostics. | Human owner approval for provider contract/user-facing changes or key handling. | Provider runtime/key pool/probe tests, safe error messaging tests, no key/raw text leakage. | Provider disable/circuit breaker or config rollback path. | Document safe metadata only; provider picker remains non-user-facing. |
| Upload malware/AV scanning | Scanner contract, ClamAV/local daemon integration, quarantine status, scanner errors and any public scanning service can affect privacy, user data, deployment, dependencies and release readiness. | Human owner approval before production dependency, Docker/deployment, external scanning, retention or runtime data changes. | Scanner verdict tests for clean/infected/error/timeout/unavailable; EICAR or equivalent safe AV fixture; upload flow tests proving unscanned/infected files never reach parser/workers; redaction tests; compileall. | Disable scanner gate only by explicit owner-approved beta deferral; retain quarantine state and safe rejection path; rollback scanner adapter/config without exposing files. | Update upload-safety docs, release gates, risk register and handoff; do not claim malware scanning implemented without evidence. |
| Admin provider controls and diagnostics | Key testing, key weight/max parallel, runtime reload, beta safety, queue controls and provider capacity can affect cost, reliability, scheduler behavior and secrets/admin safety. | Human owner approval for new or expanded writable/provider behavior. | Admin rendering/route tests, provider runtime/key-pool/probe tests when behavior changes, redaction tests, scheduler/worker tests for capacity/state changes, compileall. | Restore previous setting/control value, runtime reload when applicable, monitor provider/cost/queue state. | Preserve issue #30 guard: bulk key tests pause during active translations/provider requests; do not claim production monitoring or paid billing readiness. |
| User data | Runtime files, object storage, documents, logs and retention affect privacy and recoverability. | Human owner approval before changing retention, delete, storage or backup behavior. | File storage tests, retention/delete tests, backup/restore checks, no raw text leakage. | Backup before destructive changes; restore or recovery plan. | Update retention/upload-safety docs; mark Unknown/TBD where evidence is missing. |
| Destructive operations | Can delete source/final/partial/quarantine files, DB rows, backups or git work. | Explicit human approval for each destructive action. | Dry run where possible, target path verification, backup status check. | Restore plan before execution. | Record what was deleted, why, approval, and recovery path. |
| Public API contracts | Contract changes can break bot/admin/worker integrations and future clients. | Human approval for public/user-visible or cross-component contract changes. | Contract tests, affected caller tests, backward compatibility check. | Compatibility shim or rollback path. | Update relevant docs and acceptance criteria. |
| New dependencies | Adds maintenance, security, licensing, deploy and reproducibility risk. | Human approval before adding production dependencies. | Dependency import tests, lock/install verification if applicable, security/license review if required. | Remove dependency or pin rollback plan. | Update `pyproject.toml` rationale and docs only after approval. |

## 7. Gate для Pull Request

- [ ] Issue/task указана.
- [ ] Scope понятен.
- [ ] Acceptance criteria выполнены.
- [ ] Tests run указаны.
- [ ] Reviewer Agent проверил diff.
- [ ] CI status reviewed; если CI absent/Unknown/not visible, local verification
  evidence recorded. GitHub Actions Python checks are advisory for now.
- [ ] Docs updated if needed.
- [ ] No direct push to main.
- [ ] Human approval obtained if required.
- [ ] GitHub Actions status учтен: если run status Unknown/not visible, минимальный gate - local verification commands и reviewer evidence.

## 8. Gate для Release

- [ ] All critical tests pass.
- [ ] Known issues reviewed.
- [ ] Risk register reviewed.
- [ ] Release checklist completed.
- [ ] Rollback plan exists.
- [ ] Human owner approved release.
- [ ] `scripts/predeploy_check.sh` passed.
- [ ] `scripts/server_smoke_check.sh` passed on target server or missing server condition recorded.
- [ ] Relevant Gate A/B/C/D checklist in `docs/restart/release-gates.md` is completed or explicitly deferred in a signed go/no-go note.

## 9. Reviewer Agent instructions

Reviewer Agent должен читать этот файл перед review, определить applicable gates по типу изменения и проверить diff against scope, tests, docs, high-risk approvals and release readiness. Review должен начинаться с blockers/risks, затем перечислять missing evidence, tests not run и required human decisions.

Если CI status отсутствует, Unknown или not visible, Reviewer Agent не должен писать "CI passed". Нужно писать, что CI status Unknown/not visible, и оценивать local verification evidence.

## 10. Implementer Agent instructions

Implementer Agent должен читать этот файл перед изменениями, выбрать минимальный gate для задачи и не трогать high-risk зоны без explicit human approval. Для каждого изменения нужно заранее понимать expected tests/checks, а после работы указать tests run, risks, follow-up tasks и любые gates, которые не удалось выполнить.

Для docs-only changes code tests можно не запускать, если документ не меняет behavior or release readiness claims; это нужно явно указать в финальном отчете.
