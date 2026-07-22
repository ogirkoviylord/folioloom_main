# Project Brief

## 1. Краткое описание проекта

FolioLoom — это CAT-like author/rightsholder translation workbench для авторизованных длинных документов. Проект помогает импортировать TXT/DOCX/EPUB, сохранить структуру документа, управлять глоссарием/терминологией, получать AI-assisted translation draft, видеть QA/glossary/structure findings и экспортировать usable translated document.

Telegram-бот сохраняется как удобный upload/test/delivery harness, но больше не является определяющей продуктовой поверхностью. Старый Telegram-first Gate B/C план больше не считается главным release compass.

Canonical strategy issue: [#813](https://github.com/ogirkoviylord/folioloom_main/issues/813)
Canonical gate document: `docs/CAT_WORKFLOW_GATES.md`

Проект пока не является free beta, paid beta, public production или публичным SaaS.

## 2. Целевая аудитория

### Авторы / правообладатели / редакторы / small publishers

- Кто это: люди или команды, у которых есть права на длинный документ и которым нужен контролируемый translation draft.
- Зачем им продукт: управлять терминологией/именами, получать структурно сохранённый перевод, видеть QA/compliance findings и экспортировать результат для дальнейшей редакторской работы.
- Ограничения и ожидания: должны понимать, что это AI-assisted draft workflow, а не обещание human/publisher-ready перевода без review.

### Владелец/оператор сервиса

- Кто это: owner/admin проекта.
- Зачем им продукт: тестировать, управлять качеством, лимитами, provider diagnostics, workflow evidence, beta/design-partner cohorts и operational safety.
- Ограничения и ожидания: admin должен оставаться SSH-tunnel-only; raw text/secrets не должны попадать в обычные admin pages, логи, archives, telemetry, GitHub issues/PRs/docs или публичные/support artifacts.

### Trusted design partners

- Кто это: небольшая high-touch группа авторов/редакторов/правообладателей.
- Зачем им продукт: проверить, помогает ли controlled glossary + review workflow получить useful draft.
- Ограничения и ожидания: это research/design-partner alpha, не self-serve paid beta.

### Будущие платные пользователи

- Кто это: TBD после design-partner evidence.
- Зачем им продукт: платить не за “бот перевёл книгу”, а за controlled terminology, structure-preserving draft, QA evidence, editable/retryable workflow and usable export.
- Ограничения и ожидания: paid beta blocked until quality/workflow/safety evidence and payment/support/refund/reconciliation gates pass.

## 3. Главная ценность продукта

Новая проверяемая ценность FolioLoom:

> помочь автору/правообладателю получить терминологически контролируемый, структурно полный, reviewable translation draft лучше сырого generic machine translation.

Ключевые функции для доказательства ценности:

- TXT/DOCX/EPUB import and structure preservation.
- Stable document/chapter/segment state.
- Manual/author-approved glossary controls.
- Automatic glossary candidates as suggestions only until stronger evidence exists.
- Translation draft/suggestions.
- Glossary compliance and QA reports.
- Export to usable document formats.
- Telegram harness for convenient upload/delivery/testing.

## 4. Текущая стадия проекта

Стадия: active development / CAT-like workflow reframe.

Уже реализованы важные foundations:

- Telegram bot runtime на aiogram с upload/estimate/confirm/progress/cancel/status/history-oriented flows.
- TXT/DOCX/EPUB adapters, planners, assembly and structure-preservation foundations.
- Persistent job/work-unit stores, PostgreSQL scheduler store, local object storage, worker loop.
- FastAPI admin console with owner auth, settings, allowlist, provider keys/health, operations, live monitor, costs, audit/security surfaces.
- Docker Compose services: `api`, `bot`, `worker`, `postgres`, `redis`.
- Backup/restore scripts and deployment runbooks.
- Local/fake prepared-glossary foundations and candidate-quality gates.

Still not ready:

- manual/author-approved glossary control surface;
- CAT-like source-target/segment review workflow;
- representative before/after quality evidence;
- automatic glossary runtime readiness;
- CAT project retention/delete policy and evidence;
- design-partner alpha readiness;
- paid beta/payment readiness.

## 5. Основные пользовательские сценарии

### Сценарий: CAT-like author workflow

- Пользователь: автор/редактор/правообладатель или owner/operator.
- Шаги: import TXT/DOCX/EPUB, review/edit glossary, translate selected slice/document, inspect QA findings, export result.
- Ожидаемый результат: usable AI-assisted translation draft with terminology control and review evidence.
- Текущая готовность: planning/foundation. Foundations exist, but thin CAT workflow and evidence remain to be built/proven.

### Сценарий: Telegram harness

- Пользователь: owner/trusted tester/design partner.
- Шаги: upload/deliver/test via Telegram where convenient.
- Ожидаемый результат: Telegram helps exercise backend workflows but does not define product readiness.
- Текущая готовность: foundations implemented; still not a substitute for CAT workflow evidence.

### Сценарий: glossary-controlled quality check

- Пользователь: author/operator/reviewer.
- Шаги: provide/approve glossary terms, run before/after translation, inspect metadata-only compliance findings.
- Ожидаемый результат: critical term consistency improves without structural regressions or raw leaks.
- Текущая готовность: local/fake foundations; automatic live glossary evidence is no-go; manual author controls need focused work.

### Сценарий: эксплуатация и восстановление

- Пользователь: owner/operator.
- Шаги: run app/server smoke, inspect safe diagnostics, verify backups, rehearse restore, verify retention/delete behavior.
- Ожидаемый результат: CAT project state and exports can be operated and recovered safely.
- Текущая готовность: scripts/runbooks/foundations exist; operational-safety evidence remains carry-forward work.

## 6. Основные компоненты продукта

| Компонент | Назначение | Где находится | Готовность | Риски/неясности |
| --- | --- | --- | --- | --- |
| CAT workflow | Import, glossary, review, QA, export | TBD / existing adapters/admin foundations | planning/foundation | Needs Gate 1-3 evidence. |
| Telegram bot | Harness for upload/test/delivery | `src/translator_service/bot/`, `bot_translation_service.py` | foundation | Not primary product surface. |
| Translation core | Extraction, planning, assembly, quality/profile checks | `src/translator_service/format_adapters/`, `translation_runner.py`, `persistent_planner.py`, `persistent_assembly.py` | partial | Needs CAT segmentation/review/export evidence. |
| Glossary | Manual/auto terminology control | glossary/prepared-package modules | foundation/no-go live readiness | Manual controls and compliance evidence missing. |
| Backend/API | Health endpoint and FastAPI/admin app | `src/translator_service/api.py`, `src/translator_service/admin/` | foundation | CAT editor/workbench surface TBD. |
| Worker | Persistent work execution | `worker.py`, `scheduler_runner.py` | foundation | Needs CAT workflow recovery evidence. |
| Storage/state | Job/work-unit/object storage | `persistent_jobs.py`, `postgres_scheduler.py`, `file_storage.py` | foundation | CAT project retention/delete/restore evidence missing. |
| Admin/Ops | Owner operations and diagnostics | `src/translator_service/admin/` | foundation | Alerts/backups reports need CAT interpretation. |
| Provider layer | DeepSeek-compatible providers | `deepseek_client.py`, `deepseek_key_pool.py`, `ai_provider_runtime.py` | foundation | Provider evidence is not quality proof. |

## 7. Неприкосновенные ограничения

- Do not claim free beta, paid beta, public production, glossary runtime quality or translation-quality readiness without evidence.
- Do not treat old Gate B/C as the product roadmap; use #813 and `docs/CAT_WORKFLOW_GATES.md`.
- Do not make paid beta/payment work active until quality/workflow evidence exists.
- Do not publish raw source text, translations, prompts, provider bodies, secrets or private diagnostics in GitHub/docs/PRs/release/public/support artifacts.
- Do not deploy, operate servers, mutate runtime data, run backup/restore/destructive cleanup, change retention/TTL, add production dependencies, change auth/security/payment/legal/public text or expand formats/channels without explicit owner approval.
- Do not weaken rights confirmation, beta allowlist, cost caps, kill switch, secret redaction, SSH-tunnel-only admin posture or metadata-only public artifact boundaries.
- Keep current format scope TXT/DOCX/EPUB until future format work is approved under #208 or successor issues.

## 8. What counts as success now

Near-term success:

- Gate 0 scope lock is clear.
- Manual/author-approved glossary path is defined and tested.
- Representative before/after evidence shows glossary-controlled improvement on critical terms.
- CAT-like thin workflow can import, review glossary, translate, show QA and export.
- Operational safety work is mapped to the CAT workflow.

Paid success is later:

- users pay or commit to pay for the workflow;
- support/refund burden is understood;
- payment/accounting/reconciliation are ready;
- quality/workflow/safety evidence remains positive.

## 9. What is not a goal now

- Broad free beta launch.
- Paid beta launch.
- Public production launch.
- Public website/customer portal.
- Full automatic glossary quality claim.
- Perfect scanner v2 / perfect automatic terminology extraction.
- Immediate PDF/OCR/MOBI/FB2/batch ZIP/arbitrary parser work.
- Public admin exposure.
- User-facing provider/model picker.
- Repo-wide ruff cleanup as release blocker.

## 10. How AI agents should use this file

- Start strategy/release work from #813 and `docs/CAT_WORKFLOW_GATES.md`.
- Treat Telegram bot work as harness/supporting flow unless a task explicitly says otherwise.
- Treat old Gate B issues as operational-safety carry-forward, not product readiness.
- For implementation, require a narrow owner-approved issue with acceptance criteria.
- For docs sync, update this brief when product direction, gates, confirmed state or non-goals change.
