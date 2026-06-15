# Context Map

## 1. Как пользоваться этой картой

Этот файл нужен AI-агентам перед началом задачи: он показывает, где искать контекст, какие части проекта связаны между собой и какие зоны нельзя менять без явного approve человека. Сначала сверяйтесь с `AGENTS.md`, затем с документами из раздела 2 и только после этого читайте код или тесты конкретной зоны.

## 2. Главные документы проекта

| Файл | Назначение | Когда читать |
|---|---|---|
| `AGENTS.md` | Правила работы в репозитории, запреты, формат отчета после задачи. | Перед любой задачей. |
| `docs/AGENT_SKILL_ROUTING.md` | Детальный справочник Skill Dispatch Contract: выбор роли, repo-level skill, supporting skills, approval evidence, state machine и stop-list. | Когда задача неоднозначная, multi-agent, risky, cross-role или требует выбора между repo-level и specialized skills. |
| `README.md` | Основной entrypoint: статус FolioLoom, supported/not supported, команды проверки, deployment overview. | Перед изменениями продукта, backend, bot, worker, deploy или тестов. |
| `README.project.md` | Project overview. | Когда нужен обзор проекта; сверять с `DOCUMENT_INDEX.md`. |
| `CURRENT_PROJECT_STATE.md` | Фактическое состояние проекта на restart, реализованные зоны и gaps. | Перед задачами про текущее состояние, roadmap, readiness или handoff. |
| `DOCUMENT_INDEX.md` | Индекс активных и historical docs; отделяет source of truth от архивных планов. | Перед чтением старых specs/plans. |
| `docs/PROJECT_BRIEF.md` | Продуктовый brief: аудитории, ценность, ограничения, компоненты, success criteria. | Перед продуктовыми и архитектурными задачами. |
| `docs/HANDOFF.md` | Текущий handoff: состояние, фокус, safe/risky tasks, последние изменения и вопросы владельцу. | Перед задачами по текущему состоянию, перед продолжением работы другим агентом и после завершенных изменений. |
| `docs/DECISIONS.md` | Журнал принятых и proposed решений; отделяет active decisions от TBD/Unknown. | Перед архитектурными, продуктовыми, релизными и рискованными задачами. |
| `docs/ROADMAP.md` | Рабочая очередь верхнего уровня для AI-оркестра: фазы, backlog candidates и правила scope. | Перед разбиением большой цели на issues и выбором следующей работы. |
| `docs/QUALITY_GATES.md` | Gate-ы качества для задач, code changes, docs changes, risky changes, PR и release. | Перед implementation/review и при выборе tests/checks. |
| `docs/RISK_REGISTER.md` | Реестр рисков: product, technical, security, privacy/legal, payment, operational и AI workflow. | Перед risky tasks, Architect review и release/readiness решениями. |
| `docs/RELEASE_CHECKLIST.md` | Checklist для documentation-only, internal, closed beta и future production release decisions. | Перед release, deploy, public launch или важным production change. |
| `docs/restart/folioloom-restart-spec.md` | Canonical restart-ТЗ и рамки продукта. | Перед крупными изменениями продукта, safety, payment или deployment. |
| `docs/restart/release-gates.md` | Gate A-D для stabilization, free beta, paid beta, public production. | Перед release/readiness задачами. |
| `docs/restart/two-week-engineering-plan.md` | Ближайший engineering plan. | Перед планированием следующей работы. |
| `docs/restart/real-file-test-matrix.md` | Real-file corpus и QA matrix для TXT/DOCX/EPUB. | Перед задачами про качество файлов, fixtures и release evidence. |
| `docs/restart/upload-safety-and-retention.md` | Upload hardening, quarantine, local malware scanning, TTL и retention rules. | Перед задачами про загрузки, malware scanning, хранение, удаление и user data. |
| `docs/deployment/admin-vps-runbook.md` | VPS/admin/tunnel deployment model. | Перед ops/deployment/admin access задачами. |
| `docs/deployment/restore-runbook.md` | Backup verification и restore rehearsal. | Перед backup/restore задачами. |
| `docs/deployment/server-beta.md` | Historical/superseded deployment note. | Читать только как архив, если активные runbooks не отвечают на вопрос. |
| `docs/superpowers/specs/` | Specs по admin, scheduler, provider, quality, pricing draft и другим зонам. | Читать точечный spec для соответствующей зоны. |
| `docs/superpowers/specs/2026-06-12-glossary-profile-diagnostics-sidecars.md` | Design-only owner-only glossary/profile diagnostic sidecar schema, raw-field manifest, access/export boundaries and implementation gates. | Перед #412 follow-ups, #413 provider spike planning, glossary/profile diagnostic storage/admin/archive work. |
| `docs/superpowers/specs/2026-06-12-deepseek-pro-glossary-profile-spike-report.md` | Metadata-only #413 bounded DeepSeek Pro glossary/profile spike report with validation outcomes, token overrun evidence and recommendation not to integrate runtime roles yet. | Перед follow-up provider/glossary prompt design, any further #413-style live spike, runtime integration review or glossary diagnostics planning. |
| `docs/superpowers/specs/2026-06-12-chunked-deepseek-pro-glossary-editor-spike-report.md` | Metadata-only #416 bounded chunked DeepSeek Pro glossary-editor spike report with validation outcomes, merge findings, token/latency shape and pivot-before-runtime recommendation. | Перед follow-up chunked glossary editor prompt design, further live spike planning, runtime integration review or glossary diagnostics planning. |
| `docs/superpowers/specs/2026-06-12-runtime-glossary-integration-architecture.md` | No-code #433 runtime glossary integration architecture with job/work-unit/prompt/cache/diagnostics touchpoints, fallback matrix, readiness gates and follow-up order. | Перед runtime glossary shadow work, prompt/cache integration proposals, glossary diagnostics implementation and release/privacy policy decisions. |
| `docs/superpowers/specs/2026-06-14-glossary-terminology-policy-registry-architecture.md` | No-code #517 glossary terminology policy registry architecture: language-neutral core boundary, policy descriptor, match modes, reason codes, fallback matrix and #516 child-issue sequencing. | Перед #518 terminology policy registry foundation, #519 RU/UK variant fixtures, #520 compliance adapter, #521 prompt-context policy metadata work and future language-policy proposals. |
| `docs/superpowers/specs/2026-06-14-language-policy-package-acceptance-matrix.md` | No-code #530 real language-policy package acceptance matrix: package contract, evidence levels, local acceptance thresholds, fixture rules, core-neutrality proof and subagent file ownership. | Перед #531 RU/UK package v1, #532 contrast package v1, #533 fake/dry provider evidence protocol and any future real language-policy package implementation. |
| `docs/superpowers/specs/2026-06-14-policy-provider-evidence-protocol-preflight.md` | Metadata-only #533 provider-evidence protocol and package-aware fake/dry preflight report: selected RU/UK/DE policy units, paired glossary-on/off structural and compliance summaries, #534 approval packet shape and live-provider/quality Unknowns. | Перед #534 bounded live provider evidence smoke, #535 runtime rollout design, #536 cache-key design and #537 decision packet work. |
| `docs/superpowers/specs/2026-06-14-policy-provider-evidence-live-smoke-report.md` | Metadata-only #534 bounded paired live provider evidence smoke report: 6 approved package-policy calls completed, structural validation passed, RU/UK glossary-on compliance passed, RU/UK glossary-off had target-form-missing findings, DE on/off passed, quality remains Unknown. | Перед #535 runtime rollout design, #536 cache-key design, #537 decision packet and any owner-only quality/go-no-go review. |
| `docs/superpowers/specs/2026-06-14-glossary-runtime-rollout-design.md` | No-code #535 glossary runtime rollout state machine and evidence gates: off, shadow-only, owner-only smoke/review, battle-test candidate, limited beta candidate, default candidate and no-go boundaries. | Перед any runtime glossary rollout proposal, owner-only battle-test implementation issue, #536 cache-key design and #537 decision packet work. |
| `docs/superpowers/specs/2026-06-14-glossary-cache-key-design.md` | No-code #536 glossary-aware cache-key design: output-affecting dimensions, missing/Unknown bypass rules, stale-cache failure modes, future validation tests and approval gates. | Перед any glossary-aware cache reuse proposal, cache-key implementation issue, runtime rollout proposal and #537 decision packet work. |
| `docs/superpowers/specs/2026-06-14-glossary-language-policy-decision-packet.md` | Metadata-only #537 decision packet for #529: child issue status, confirmed facts, Unknown/TBD items, owner options and closeout recommendation. | Перед choosing the next glossary issue, owner go/no-go discussion, quality review, battle-test proposal, provider smoke proposal or cache-key implementation. |
| `docs/superpowers/specs/2026-06-15-deepseek-pro-glossary-prep-before-telegram-battle-test.md` | No-code #608 architecture review: DeepSeek Pro remains glossary-prep only, runtime translation keeps the configured runtime model, and real Telegram `with_glossary` battle-tests need a READY job-scoped prepared glossary package before #607. | Перед #608 child implementation, #607 owner-assisted Telegram battle-test, prepared glossary package design, live Pro glossary-prep approval packets or glossary diagnostics/archive changes. |
| `docs/superpowers/specs/2026-06-15-deepseek-pro-glossary-prep-live-spike-report.md` | Metadata-only #614 bounded live DeepSeek Pro prepared-glossary spike report: fake/dry preflight passed, 1 approved live call completed within caps, but the provider response failed #610 validation because required top-level package fields were omitted. | Перед #607 owner-assisted Telegram battle-test, any fresh Pro-prep provider retry, prepared-package prompt/contract hardening or glossary diagnostics review. |
| `docs/superpowers/specs/2026-06-12-bounded-chunked-deepseek-pro-glossary-editor-retry-report.md` | Metadata-only #431 bounded chunked DeepSeek Pro glossary-editor retry report with validation outcomes, token/latency shape and pivot-before-runtime recommendation. | Перед further provider prompt retries, glossary editor runtime planning, glossary diagnostics implementation and release/privacy policy decisions. |
| `docs/superpowers/specs/2026-06-12-reduced-glossary-runtime-go-no-go.md` | No-code #451 reduced glossary runtime go/no-go review after #444-#450, with boundary verdicts for prompts, cache, diagnostics, storage/admin, provider retry and release policy. | Перед runtime glossary prompt/cache/storage/admin proposals, reduced provider retry follow-ups and glossary release-policy decisions. |
| `docs/superpowers/specs/2026-06-13-reduced-glossary-readiness-after-packet-fixes.md` | Metadata-only #463 local/fake reduced glossary readiness report after #461/#462, recording structural passes but default local readiness failures for fake low-confidence outputs and EPUB reducer diagnostic/drop pressure. | Перед #464 provider retry, reduced packet/reducer threshold decisions, runtime glossary prompt/cache proposals and glossary release-policy decisions. |
| `docs/superpowers/specs/2026-06-13-reduced-glossary-editor-post-fix-retry-report.md` | Metadata-only #464 bounded post-fix reduced glossary-editor provider retry report, recording all four approved packets validated with provider usage present and warning-only merge findings. | Перед #466 disabled prompt-policy adapter work, runtime glossary prompt/cache proposals and any further provider retry planning. |
| `docs/superpowers/specs/2026-06-13-glossary-runtime-cache-policy-decision.md` | Owner-approved #465 design-only cache policy: first glossary-injected enabled/test-path adapter bypasses cache, while compact signatures remain metadata for planning/diagnostics/future cache-key design. | Перед #466 disabled prompt-policy adapter, future glossary-aware cache-key work, runtime glossary prompt/cache proposals and review. |
| `docs/superpowers/specs/2026-06-13-glossary-runtime-provider-smoke-report.md` | Metadata-only #477 bounded glossary runtime provider smoke report: TXT smoke calls validated, approved EPUB RU/UK calls ended with provider `length` and local `truncated_output`/`external_text` validation failures. | Перед #478 quality review, runtime prompt rollout proposals, EPUB runtime prompt-budget iteration and glossary release-policy decisions. |
| `docs/superpowers/specs/2026-06-13-bounded-paired-epub-glossary-runtime-smoke-report.md` | Metadata-only #491 bounded paired EPUB glossary runtime provider smoke report: fake preflight passed, but all four approved live glossary-on/off EPUB calls ended with provider `length` and local `truncated_output`/`external_text` validation failures. | Перед #492 quality/decision review, future EPUB runtime unit-splitting/output-budget proposals, any paired provider retry approval, and glossary runtime rollout discussion. |
| `docs/superpowers/specs/2026-06-13-epub-glossary-runtime-quality-decision-review.md` | Metadata-only #492 EPUB glossary runtime quality/decision review: verdict `FAIL` for rollout/battle-test readiness and positive quality claims from #491 because all paired EPUB glossary-on/off live calls failed validation. | Перед future EPUB runtime unit-splitting/output-budget issues, paired provider-smoke approval requests, owner go/no-go discussion, runtime glossary rollout proposals and glossary release-policy decisions. |
| `docs/superpowers/specs/2026-06-13-glossary-on-off-quality-review.md` | Metadata-only #478 glossary-on/off quality review: verdict `NEEDS REVIEW` because approved EPUB outputs were invalid and no paired non-glossary comparison outputs were available. | Перед #479 decision prep, paired quality evaluation design, runtime prompt rollout proposals and glossary release-policy decisions. |
| `docs/superpowers/specs/2026-06-13-controlled-glossary-runtime-decision-prep.md` | Metadata-only #479 controlled glossary runtime decision prep: rejects normal/limited-beta rollout for now, recommends shadow-only plus local EPUB prompt/selection iteration before a fresh paired smoke approval, and leaves final owner path as `TBD`. | Перед созданием следующих runtime glossary issues, owner go/no-go discussion, paired provider-smoke approval or rollout planning. |
| `docs/superpowers/specs/2026-06-12-reduced-glossary-editor-retry-report.md` | Metadata-only #449 bounded reduced glossary-editor provider retry report with fake/dry evidence, live validation outcomes, timeout/token caveats and NO-GO runtime recommendation. | Перед reduced glossary prompt/packet-budget iteration, runtime glossary architecture updates and provider retry follow-ups. |
| `docs/superpowers/plans/` | Архив implementation plans; многие планы уже реализованы или superseded. | Читать только после `DOCUMENT_INDEX.md`; не считать unchecked items roadmap без подтверждения. |

## 3. Карта директорий

| Путь | Что внутри | Кто должен читать | Риск изменений |
|---|---|---|---|
| `.` | Корневые docs, env examples, real `.env*`, Dockerfile, compose, pyproject. | Все агенты. | human approval required для `.env*`, deploy, deps и конфигов. |
| `.agents/skills/` | Repo-level skill instructions for Idea Intake, Orchestrator, Architect, Implementer, Reviewer, Scribe and Release Readiness roles. | Все агенты при выборе или применении роли. | medium; keep aligned with `AGENTS.md` and `docs/AGENT_SKILL_ROUTING.md`. |
| `docs/` | Project docs, restart docs, deployment runbooks, specs/plans archive. | Scribe, Orchestrator, Architect, Reviewer. | medium; high для deployment, release gates, legal/privacy/safety текста. |
| `src/translator_service/` | Основной Python package: backend, bot, worker, translation core, persistence, safety. | Implementer, Architect, Reviewer. | medium/high по зоне. |
| `src/translator_service/admin/` | FastAPI admin console: auth, settings, secrets, provider keys, costs, audit, live, operations, owner-only text diagnostics, run-log reader and owner-only full diagnostic archive exports. Issue #549 adds `glossary_runtime_diagnostics.json` to downloaded archives only when glossary runtime diagnostic data exists; #612 extends that sidecar with prepared-glossary package status/linkage metadata from existing adapter events. | Admin/backend agents. | human approval required для auth, secrets, security, provider keys, user data and any raw-text/glossary diagnostic expansion. |
| `src/translator_service/bot/` | aiogram Telegram runtime, messages, activity phrases. | Bot/UI agents. | high; затрагивает UX, Telegram API, user data, payments-adjacent flows. Issue #546 adds a temporary per-attempt glossary mode selector for manual battle-test comparison only; default rollout, automatic paired translation and glossary-aware cache reuse remain unapproved. |
| `src/translator_service/format_adapters/` | TXT/DOCX/EPUB adapters, contracts, EPUB repair, TXT layout. | Translation/file-format agents. | medium/high; file parsing and output fidelity. |
| `src/translator_service/glossary_contracts.py` | Local glossary schema dataclasses, enums, validators and compact signature helpers for the glossary epic. | Implementer, Architect, Reviewer for glossary issues. | medium/high; contract changes can affect future prompt/cache/provider/runtime integrations, but this module has no provider/storage/runtime side effects by itself. |
| `src/translator_service/glossary_scanner.py` | Local deterministic glossary candidate/evidence scanner over existing TXT/DOCX/EPUB adapter plans. | Implementer, Architect, Reviewer for glossary issues. | medium/high; scanner output can affect future prompt budgets and glossary quality, but this module has no provider/storage/runtime side effects by itself. |
| `src/translator_service/book_profile.py` | Local deterministic book translation profile detector, profile contract validator and profile-specific glossary rule data for the glossary epic. | Implementer, Architect, Reviewer for glossary/profile issues. | medium/high; profile/rule output can affect future prompts/cache/provider/runtime diagnostics, but this module has no provider/storage/runtime side effects by itself. |
| `src/translator_service/book_profile_sanity.py` | Local metadata-only sanity gate for mixed or suspiciously confident book profile detections, with compact finding reasons, routes and signatures. | Implementer, Architect, Reviewer for glossary/profile sanity issues. | medium/high; sanity findings can affect future reducer/editor/runtime routing, but this module has no provider/runtime/prompt/cache/storage side effects by itself and serialized payloads stay metadata-only. |
| `src/translator_service/glossary_role_validators.py` | Local fake-output JSON validators for approved DeepSeek Pro glossary/profile roles and cross-role disagreement checks. | Implementer, Architect, Reviewer for glossary/provider-boundary issues. | medium/high; role outputs are untrusted model output and can affect future snapshots, but this module has no provider/runtime/prompt/diagnostic side effects by itself. |
| `src/translator_service/translation_contract_snapshot.py` | Local deterministic translation contract snapshot builder for glossary/profile planning metadata. | Implementer, Architect, Reviewer for glossary snapshot/cache/diagnostics issues. | medium/high; snapshots are user-data-adjacent contract metadata and can affect future cache/diagnostics/prompt integration, but this module has no provider/runtime/cache/storage side effects by itself. |
| `src/translator_service/glossary_selection.py` | Local deterministic per-work-unit glossary subset selector with prompt-budget metadata. | Implementer, Architect, Reviewer for glossary selection/prompt-budget issues. | medium/high; selection can affect future prompts, cost and diagnostics, but this module has no provider/runtime/prompt/cache/storage side effects by itself. |
| `src/translator_service/glossary_candidate_reducer.py` | Local deterministic candidate reducer that turns wide glossary scan snapshots into editor-ready, diagnostic-only and dropped decisions with compact reason/evidence metadata and stable signatures. | Implementer, Architect, Reviewer for glossary editor input reduction issues. | medium/high; reduction can affect future provider prompt budgets and glossary quality, but this module has no provider/runtime/prompt/cache/storage side effects by itself and serialized payloads stay metadata-only. |
| `src/translator_service/glossary_editor_packets.py` | Local deterministic DeepSeek Pro glossary-editor packet contract and packet builder with stable ids/signatures, compact reference payloads, budget reservation, split/degradation metadata, conservative reduced-packet defaults and optional reducer-retained candidate context. | Implementer, Architect, Reviewer for chunked glossary-editor issues. | medium/high; packets can affect future provider prompts and diagnostics, but this module has no provider/runtime/prompt/cache/storage side effects by itself. |
| `src/translator_service/glossary_editor_chunk_outputs.py` | Local fake-output validators and deterministic merge/adjudication contract for chunked glossary-editor packet outputs. | Implementer, Architect, Reviewer for chunked glossary-editor validator and provider-boundary issues. | medium/high; validators shape future provider output handling and conflict policy, but this module has no provider/runtime/prompt/cache/storage side effects by itself. |
| `src/translator_service/glossary_evaluation.py` | Local metadata-only glossary/editor evaluation harness and readiness gates over validated chunk outputs, merge/adjudication findings, packet budget metadata, reduced-packet reducer coverage/drop pressure and optional metadata-only provider reports. | Implementer, Architect, Reviewer for glossary readiness and runtime-integration planning issues. | medium/high; readiness metrics can influence provider retry and architecture sequencing, but this module has no provider/runtime/prompt/cache/storage side effects by itself and does not prove semantic truth. |
| `src/translator_service/glossary_terminology_policy.py` | Local-only glossary terminology policy registry foundation with policy descriptors, validation, registry resolution and exact/casefold/variant-list/manual-review match helpers. | Implementer, Architect, Reviewer for language-aware glossary compliance and future policy packages. | medium/high; policies can affect compliance and future prompt metadata, but this module has no provider/runtime/prompt/cache/storage/admin side effects by itself and must not become a hidden morphology or semantic-truth engine. |
| `src/translator_service/glossary_compliance.py` | Local metadata-only glossary compliance validator for disabled/test-only runtime smoke outputs, with default exact-form compatibility and optional terminology-policy registry metadata. | Implementer, Architect, Reviewer for glossary runtime smoke and terminology policy follow-ups. | medium/high; it keeps structural validation separate from glossary compliance, can distinguish approved variants, forbidden variants and needs-review outcomes when an explicit policy registry is provided, and has no provider/runtime/prompt/cache/storage side effects by itself. It does not prove semantic or morphological correctness. |
| `src/translator_service/glossary_pressure_report.py` | Local metadata-only glossary pressure report builder over adapter plans, scanner output, book profile detection and glossary-editor packet metadata. | Implementer, Architect, Reviewer for reduced-glossary pressure/reducer issues. | medium/high; pressure metrics can influence future reducer/provider/runtime sequencing, but this module has no provider/runtime/prompt/cache/storage side effects by itself and does not serialize raw source text. |
| `src/translator_service/glossary_persistent_runtime_resolver.py` | Local-only/default-off owner/test persistent EPUB work-unit glossary resolver; builds `GlossaryRuntimeAdapterHookConfig` from claimed work-unit source text, scanner/reducer/selector output, approved target-metadata overlay, and #611 #610-validated prepared package metadata. | Implementer, Architect, Reviewer for #557/#558/#559/#611 real-book glossary battle-test work. | high; it is worker/runtime-adjacent and can produce glossary prompt context only when explicitly enabled, owner battle-test enabled, EPUB, overlay/prepared metadata is READY, source term/alias present and target metadata exists. It has no provider calls, default rollout, cache reuse, DB/schema/state/storage/admin/retention mutation or release claims by itself. |
| `src/translator_service/glossary_profile_diagnostics.py` | Owner-only glossary/profile diagnostic sidecar schema, validator, metadata summary and dedicated file read/write boundary. | Implementer, Architect, Reviewer for glossary/profile diagnostics and sidecar work. | high; sidecars can contain raw-capable user-document/provider diagnostics, but the foundation keeps ordinary summaries metadata-only and leaves retention/export/delete `TBD`. |
| `src/translator_service/glossary_prepared_package.py` | Local-only #610 prepared glossary package schema/validator for compact DeepSeek Pro glossary-prep metadata before Telegram battle-tests. | Implementer, Architect, Reviewer for #608 child issues, prepared package validation, #611 handoff and #614 live Pro-prep planning. | high; prepared target metadata can affect future runtime prompts, but this module only validates compact packages, emits metadata-only summaries, rejects raw/secret/auth material and can export a #556-compatible overlay payload. It has no provider calls, admin/archive, storage/retention, rollout or cache-reuse side effects by itself; #611 separately allows worker-side reading of this compact package from job-scoped `translation_policy` only for explicit `with_glossary` owner/test paths. |
| `src/translator_service/glossary_target_metadata_overlay.py` | Local-only/default-off owner-approved target-metadata overlay contract for real-book glossary battle-test planning; validates compact payloads, rejects raw/prompt/provider/translation/secret/auth material, matches retained entries only by source term/alias and returns metadata-only reason codes. | Implementer, Architect, Reviewer for #556/#557 glossary runtime resolver work. | high; target metadata can affect future provider prompts, but this module has no provider calls, runtime prompt integration, cache reuse, durable state, storage/admin/retention side effects or release claims by itself. |
| `src/translator_service/glossary_runtime_shadow.py` | Disabled-by-default fake-runtime/shadow glossary planning helper over TXT fixture content, local scanner/profile/reducer/snapshot/selection and compact policy signatures. | Implementer, Architect, Reviewer for glossary runtime-shadow and prompt-planning proposals. | high; runtime-adjacent, but default disabled and does not call providers, inject prompts, mutate cache/state/storage/admin, or change user-visible behavior. |
| `src/translator_service/glossary_prompt_context.py` | Local bounded formatter for future glossary prompt-context sections from compact selected glossary entries, with escaping, metadata-only omission reporting, default-off compact terminology policy metadata, the #584 owner/test `mandatory_term:` checklist and the #596 binding target-form markers for included target-backed terms. | Implementer, Architect, Reviewer for controlled glossary prompt-context tests. | high; provider-facing prompt-context contract. #475 keeps it local only, #476 uses it only under an explicit disabled/test-only rehearsal flag, #521 adds only opt-in compact policy metadata, #584 strengthens the default-off owner/test prompt shape, and #596 adds local binding target-form wording after #593 found provider compliance misses; none of these approve normal runtime integration, live provider calls, cache reuse, durable state, admin/storage/retention changes or release/privacy claims. |
| `src/translator_service/translation_policy.py` | Translation prompt policy, output-contract policy, optional compact glossary/profile signature context and disabled-by-default glossary prompt-policy adapter decision contract. | Implementer, Architect, Reviewer for translation policy, provider-boundary and glossary prompt/cache-signature issues. | medium/high; policy signatures and adapter decisions can affect future prompt/cache behavior. #411 adds signatures only; #466 adds a default-off adapter decision with cache bypass for enabled/test-path glossary planning and does not inject glossary/profile data into normal prompts. |
| `src/translator_service/translation_runner.py` | TXT/DOCX/EPUB local translation runner and in-process translation unit orchestration. | Implementer, Architect, Reviewer for translation runtime, cache, prompt and controlled glossary test-path work. | high; #474 adds a default-off DOCX/EPUB glossary runtime adapter hook that emits compact metadata and requests cache bypass only for READY enabled/test-path units. #476 adds disabled/test-only fake prompt rehearsal, #501 narrows the owner-only battle-test path so bounded glossary context is injected only for useful READY units with source term/alias presence, target metadata and local pressure/budget pass, and #546 threads the selected hook through the Telegram in-memory DOCX/EPUB path. No normal prompt rollout, live provider calls, durable state or default user-visible glossary behavior are approved. |
| `src/translator_service/translation_cache.py` | In-memory translation cache key builder for repeated DOCX/EPUB translation units. | Implementer, Architect, Reviewer for cache/policy-signature work. | medium/high; cache-key changes can affect stale reuse, cost and latency. Glossary/profile signature context is optional and compact; migration/stale-cache behavior remains `TBD`. |
| `tests/` | Unit/regression tests for admin, bot, scheduler, worker, provider, translation, deployment smoke. | Reviewer, QA, Implementer. | low/medium; high если меняются safety/payment/auth expectations. |
| `scripts/` | Deploy, predeploy, server smoke/status, backup/verify, sample generation, security summary. | Ops, Reviewer, Implementer for scripts only. | human approval required for deploy/backup/server scripts. |
| `.github/` | GitHub issue templates, PR template and `workflows/checks.yml`. | CI / GitHub workflow agents. | low/medium; do not add deploy, secrets, production operations or required-approval gates without owner approval. |
| `database/`, `db/`, `migrations/` | Not found as project directories. | Database agents. | human approval required if created or changed. |
| `var/` | Runtime sqlite DBs, object storage, translation run artifacts. | Ops/debug agents only. | human approval required; likely user/runtime data. |
| `artifacts/`, `epub_audit_output/`, `test_samples/` | Sample/output files and real-file fixtures. | QA/file-format agents. | medium; high if copyrighted/user data risk. |
| `tools/` | Utility tooling, currently EPUB audit helper. | QA/tooling agents. | medium. |
| `tools/deepseek_glossary_profile_spike.py` | Standalone #413 bounded fixture spike runner for local/fake and approved live DeepSeek Pro glossary/profile role validation. | Glossary/provider spike agents only after exact owner approval. | high for live mode; can send fixture excerpts to provider and write owner-only raw diagnostics under approved untracked output directories. |
| `tools/deepseek_chunked_glossary_editor_spike.py` | Standalone #416/#431/#449/#464 bounded chunked glossary-editor spike runner for fake preflight and owner-approved live DeepSeek-compatible calls over approved packets. Issue #430 / #204N tightens the local prompt/evidence contract; issues #449 and #464 add explicit reduced-packet retry modes with approved TXT fixtures plus the owner-approved local EPUB input, max 4 calls and issue-specific diagnostics roots. | Glossary/provider spike agents only after exact owner approval and the issue-specific local gates or explicit owner gate deferral. | high for live mode; can send bounded fixture/book excerpts to provider and write owner-only raw diagnostics under approved untracked output directories. |
| `tools/prepared_glossary_prep_preflight.py` | Prepared-glossary Pro-prep runner for the committed Gutenberg control EPUB and `ru`: #619 fake/dry preflight, #614 owner-approved bounded live path and #622 local package-envelope hardening for provider responses that omit locally known top-level package metadata. | Glossary/provider prep agents before #607 owner-assisted Telegram battle-test or any fresh Pro-prep retry. | high for live mode; can send bounded fixture excerpts and prompts to a DeepSeek-compatible provider only under exact/bounded approval, and writes raw-capable diagnostics only under owner-only untracked `outputs/glossary-battle-test/<issue-or-purpose>/<timestamp>/`. #622 may locally wrap provider `entries` with deterministic local package metadata, but must not invent target-language semantic facts; #610 validation remains the final readiness gate. |
| `tools/glossary_runtime_provider_smoke.py` | Standalone #477 bounded glossary runtime provider smoke runner for fake preflight and owner-approved live DeepSeek-compatible calls over first READY glossary-injected runtime test-path units. Issues #487-#489 add metadata-only pressure, fallback and completion-first budget decisions; #490 adds fake paired EPUB glossary-on/off rehearsal metadata; #491 records bounded paired live EPUB failure evidence; #503 adds a local-only EPUB unit/output-budget selector that chooses only #501-style glossary-useful, pressure-safe EPUB units or emits metadata-only skip/fallback reasons; #505 adds a default-off owner-only approved target-metadata fixture overlay for the committed control EPUB fake/local path; #507 adds an explicit `--control-epub` issue boundary for paired `ru`/`uk` glossary-on/off fake/live smoke with max 4 calls and #507 diagnostics root; #510 adds metadata-only glossary compliance summaries; #520 upgrades those summaries to optional terminology-policy-aware metadata while keeping structural validation separate; #559 adds an explicit `--issue-559-real-epub` boundary for a bounded Gutenberg/Oz real-EPUB RU paired smoke with an effective 2-call cap, 60k token cap and owner-only diagnostics root; #576 adds an explicit `--issue-575-adversarial-txt` boundary for the post-#571 adversarial TXT `ru`/`uk` paired matrix with max 4 calls, 60k token cap, committed target-metadata fixture and owner-only #575 diagnostics root; #588 adds the matching `--issue-586-post-584-adversarial-txt` boundary for the post-#584 rerun with the same adversarial TXT safeguards and a separate owner-only diagnostics root; #591 fixes #586 drift so that boundary also inherits the #578 target-backed source-present useful-entry filter; #594 adds the `--issue-593-post-591-adversarial-txt` boundary for a fresh post-#591 rerun under a separate owner-only diagnostics root; #598 adds the `--issue-598-post-596-adversarial-txt` boundary for the post-#596 rerun with a separate owner-only diagnostics root; #600 records the post-#596/#601 bounded adversarial TXT live evidence where structural validation and glossary-on configured-form compliance passed for both `ru` and `uk`; #586 records bounded post-#584 adversarial TXT live evidence with structural validation passing, but that run predates the #591 filter fix and needs rerun before judging exact configured target-form compliance; #578 tightens that TXT path so prompt context and compliance use the same target-backed source-present useful entries; #580 strengthens default-off owner/test glossary context wording for included target-backed terms without changing rollout/cache behavior; #582 adds an explicit internal system-prompt acknowledgment flag only for service-generated glossary contexts. | Glossary/runtime provider smoke agents only after #474/#475/#476 are merged and exact owner approval is recorded; #487-#490, #503, #505, #510 and #520 local outputs plus #491/#507/#559/#575/#586/#600 provider-boundary evidence do not approve provider retries, quality claims or rollout. | high for live mode; can send bounded fixture/book excerpts plus glossary runtime prompts to provider and write owner-only raw diagnostics under the approved untracked diagnostics directory. Ordinary reports stay metadata-only/redacted. |
| `handoff/` | Restart package archive and copied configs. | Orchestrator/Scribe. | medium; may contain stale or bundled context. |
| `.superpowers/` | Local skill/process state. | Usually not needed. | low; avoid unrelated edits. |
| `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, `.DS_Store` | Generated/cache files. | Usually no one. | low; do not treat as source of truth. |

Glossary architecture boundary: `docs/DECISIONS.md` records the active
2026-06-14 rule that glossary core stays language-neutral. Issue #517 records
the policy-registry contract in
`docs/superpowers/specs/2026-06-14-glossary-terminology-policy-registry-architecture.md`.
Issue #530 records the real language-policy package acceptance matrix in
`docs/superpowers/specs/2026-06-14-language-policy-package-acceptance-matrix.md`.
Issue #533 records the metadata-only provider-evidence protocol and fake/dry
package-aware preflight in
`docs/superpowers/specs/2026-06-14-policy-provider-evidence-protocol-preflight.md`.
Issue #534 records bounded live provider evidence in
`docs/superpowers/specs/2026-06-14-policy-provider-evidence-live-smoke-report.md`.
Issue #535 records the no-code runtime rollout state machine and owner-approval
gates in
`docs/superpowers/specs/2026-06-14-glossary-runtime-rollout-design.md`.
Issue #536 records the no-code glossary-aware cache-key design in
`docs/superpowers/specs/2026-06-14-glossary-cache-key-design.md`.
Issue #537 records the metadata-only decision packet in
`docs/superpowers/specs/2026-06-14-glossary-language-policy-decision-packet.md`.
Issue #555 records the no-code real-book runtime glossary resolver contract in
`docs/superpowers/specs/2026-06-14-real-book-runtime-glossary-resolver-contract.md`.
Target-language terminology behavior must be isolated behind explicit
policy/adapter boundaries such as `target_language -> terminology_policy`; do
not add scattered RU/UK or other language-specific morphology branches to
glossary contracts, scanner, selection, snapshots, prompt formatter, compliance
or cache/signature core. Issues #518-#521 implemented the first local-only
registry, RU/UK synthetic fixture, compliance-adapter and prompt-metadata
foundations; #530 defines package acceptance only. None of these approve
runtime rollout, provider calls, cache reuse or release/privacy claims.

## 4. Основные зоны продукта

### Backend

- Пути: `src/translator_service/api.py`, `src/translator_service/config.py`, core modules in `src/translator_service/`.
- Назначение: FastAPI health/admin app, configuration, document/job/order/user/state services, provider runtime integration.
- Важные файлы: `api.py`, `config.py`, `documents.py`, `orders.py`, `users.py`, `file_storage.py`, `deepseek_client.py`, `ai_provider_runtime.py`, `deepseek_key_pool.py`, `beta_safety.py`, `security_telemetry.py`.
- Связанные тесты: `tests/test_api.py`, `tests/test_config.py`, `tests/test_documents.py`, `tests/test_orders.py`, `tests/test_users.py`, `tests/test_file_storage.py`, `tests/test_ai_provider_runtime.py`, `tests/test_deepseek_*`, `tests/test_beta_safety*`, `tests/test_security_*`.

### Bot / UI

- Пути: `src/translator_service/bot/`, `src/translator_service/bot_translation_service.py`.
- Назначение: Telegram-first UX: upload, language, estimate, rights confirmation, temporary #546 glossary mode selector for manual battle-test comparison, progress, cancel/status/history flows.
- Важные файлы: `bot/runtime.py`, `bot/messages.py`, `bot/activity_phrases.py`, `bot/__main__.py`, `bot_translation_service.py`.
- Связанные тесты: `tests/test_bot_runtime.py`, `tests/test_bot_runtime_logging.py`, `tests/test_bot_messages.py`, `tests/test_bot_translation_service.py`.

### Frontend

- Not found as separate web frontend directory.
- Admin UI appears server-rendered/route-based under `src/translator_service/admin/`.

### Admin

- Пути: `src/translator_service/admin/`.
- Назначение: SSH-tunneled owner/admin console: login/session auth, settings, allowlist, encrypted secrets, provider keys/health/probe/runtime, costs, live monitor, operations, audit, quality, deployment smoke.
- Важные файлы: `routes.py`, `views.py`, `auth.py`, `rbac.py`, `secrets.py`, `secret_safety.py`, `settings.py`, `ai_provider_keys.py`, `provider_*`, `costs.py`, `live.py`, `operations.py`, `audit.py`, `deployment_smoke.py`.
- Связанные тесты: `tests/test_admin_*.py`, `tests/test_server_deployment_config.py`.

### Worker / background jobs

- Пути: `src/translator_service/worker.py`, `scheduler.py`, `scheduler_runner.py`, `postgres_scheduler.py`, `persistent_jobs.py`, `persistent_job_store.py`, `job_runner.py`, `persistent_planner.py`, `persistent_assembly.py`.
- Назначение: persistent jobs/work units, leases, retries, worker loop, scheduler fairness/capacity, partial/final assembly.
- Glossary note: #546 threads the default-off selected glossary hook and
  metadata-only adapter events through persistent DOCX/EPUB worker execution,
  including EPUB and scheduler-backed work-unit execution. #551 repairs the
  external/scheduled worker evidence path so `with_glossary` is resolved per
  claimed work unit: READY hook data can inject bounded context, while missing
  runtime glossary data records metadata-only fallback/omission diagnostics for
  the owner-only archive sidecar. #555 defines the next resolver contract for
  real-book persistent EPUB jobs: approved target metadata plus local
  source-match/budget gates may produce READY hooks, while missing or invalid
  data must fall back with metadata-only reason codes. This does not approve
  default glossary rollout, live provider calls, arbitrary real-book glossary
  generation, glossary-aware cache reuse, durable state changes or
  provider/config changes.
- Важные файлы: listed above plus `translation_jobs.py`, `translation_runner.py`, `translation_run_logs.py`, `translation_metrics.py`.
- Связанные тесты: `tests/test_worker.py`, `tests/test_scheduler*.py`, `tests/test_postgres_scheduler.py`, `tests/test_persistent_*`, `tests/test_job_runner.py`, `tests/test_translation_*`.

### Database / migrations

- Пути: no dedicated migrations directory found.
- Назначение: PostgreSQL scheduler state through `postgres_scheduler.py`; SQLite fallback/runtime stores through `persistent_job_store.py`, `beta_safety_store.py` and admin/runtime DB paths.
- Risk level: human approval required.
- Human approval requirements: any schema/state migration, persistent data handling, `var/*.sqlite3`, PostgreSQL model changes, backup/restore behavior, retention/TTL behavior, or new database directory requires explicit human approval.

### Tests

- Где лежат: `tests/`.
- Как устроены: Python unittest/pytest-compatible test files grouped by module/feature; README verification uses `PYTHONPATH=src python3 -m unittest discover -s tests`, compileall, and `scripts/predeploy_check.sh`.
- Какие зоны покрыты: admin, bot, worker, scheduler/Postgres scheduler, provider layer, translation pipeline, format adapters, safety/security telemetry, deployment smoke, backup scripts.
- Какие зоны не покрыты: Unknown from this mapping task. Docs mention remaining release gaps for real-file matrix, DOCX visual/openability QA, EPUBCheck/equivalent, cancel/resume/restart validation, restore rehearsal artifacts and server smoke evidence.

### CI / GitHub Actions

- Workflows found: `.github/workflows/checks.yml`.
- Что проверяют: on pull requests and pushes to `main`, GitHub Actions checks out the repo, sets up Python 3.13, installs the project with `python -m pip install -e .`, runs `PYTHONPATH=src python -m compileall src`, and runs `PYTHONPATH=src python -m unittest discover -s tests`.
- Что не проверяют: deploy, server smoke, secrets, real `.env*`, backup/restore rehearsal, real-file release matrix, typecheck and formatting. Current GitHub run status is Unknown unless inspected on the PR/checks page.

### Deployment / infrastructure

- Файлы: `Dockerfile`, `docker-compose.yml`, `.env.server.example`, `scripts/deploy_server.sh`, `scripts/predeploy_check.sh`, `scripts/server_smoke_check.sh`, `scripts/server_status.sh`, `scripts/backup_server_data.py`, `scripts/verify_backup_export.py`, `docs/deployment/`.
- Назначение: VPS Docker Compose stack with `api`, `bot`, `worker`, `postgres`, `redis`; SSH-tunneled admin; backup/restore workflow.
- Почему high-risk: deployment touches secrets, server state, runtime data, public exposure, backups, restore, provider keys and production-like availability. Production deployment requires explicit human approval.

## 5. Где агентам искать информацию перед задачей

- Перед любой задачей читать `AGENTS.md`.
- Перед продуктовой задачей читать `docs/PROJECT_BRIEF.md` и `docs/restart/two-week-engineering-plan.md`; если появится `docs/ROADMAP.md`, читать и его.
- Перед задачей по текущему состоянию читать `CURRENT_PROJECT_STATE.md`; если появится `docs/HANDOFF.md`, читать и его.
- Перед архитектурной задачей читать `docs/restart/folioloom-restart-spec.md`, relevant specs in `docs/superpowers/specs/`; если появится `docs/DECISIONS.md`, читать и его.
- Перед релизной задачей читать `docs/restart/release-gates.md`; если появится `docs/RELEASE_CHECKLIST.md`, читать и его.
- Перед рискованной задачей читать `AGENTS.md`, `docs/PROJECT_BRIEF.md`, `docs/restart/release-gates.md`; если появятся `docs/RISK_REGISTER.md` и `docs/QUALITY_GATES.md`, читать их.
- Перед чтением старых plans/specs читать `DOCUMENT_INDEX.md`.

## 6. Зоны, требующие approve человека

- `.env`, `.env.dev`, `.env.beta` и любые `.env*`: secrets/env, provider keys, Telegram/admin/Postgres settings.
- `Dockerfile`, `docker-compose.yml`, `.env.server.example`, `scripts/deploy_server.sh`, `scripts/server_*`, `scripts/predeploy_check.sh`, `docs/deployment/`: deployment/infrastructure.
- `scripts/backup_server_data.py`, `scripts/verify_backup_export.py`, `var/`, object storage paths, sqlite/runtime DBs: user data, backups, restore and retention.
- Any database schema/state layer: `postgres_scheduler.py`, `persistent_job_store.py`, `beta_safety_store.py`, new migrations or DB directories.
- Payment/pricing/order zones: `pricing.py`, `billing.py`, `orders.py`, `order_estimates.py`, `order_payments.py`, payment/pricing docs/specs. Paid beta is gated.
- Auth/security/secrets zones: `src/translator_service/admin/auth.py`, `rbac.py`, `secrets.py`, `secret_safety.py`, `security_telemetry.py`, `security_summary.py`, admin session/secret settings.
- Legal/privacy/user-data handling: upload safety/retention docs, file storage,
  user activity, raw document handling, rights confirmation, logs/admin display
  of document text and the approved owner-only raw diagnostic surfaces.
- External API integrations: Telegram bot runtime, DeepSeek client/key pool/provider runtime, provider validation/probe/balance/key management.
- Destructive operations: deleting runtime data, changing retention/TTL, modifying backup/restore, force-resetting git, removing artifacts unless explicitly approved.

## 7. Потенциальные конфликтные зоны для параллельных агентов

- Нельзя параллельно менять `persistent_jobs`/scheduler/Postgres state и worker claim/cancellation logic без координации: это один state machine.
- Нельзя параллельно менять bot flow и backend job/order contract без общего API/contract plan.
- Нельзя параллельно менять provider key selection/throttling и admin provider health/runtime UI без согласования telemetry fields.
- Нельзя параллельно менять pricing/payment/order estimates и bot confirmation/payment-adjacent UX без owner approval и gate context.
- Нельзя параллельно менять file adapters, persistent assembly и real-file tests для одного формата без согласования expected output contracts.
- Нельзя параллельно менять auth/RBAC/secrets и admin routes/views: высокий риск ослабить доступ или redaction.
- Нельзя параллельно менять deployment scripts, compose/env contract и server runbooks без единого Reviewer/Architect pass.
- Нельзя параллельно менять retention/TTL/upload safety и backup/restore/runtime storage без data-handling decision.

## 8. Быстрые маршруты для типовых задач

### Если задача про bugfix

Читать:
- `AGENTS.md`
- `CURRENT_PROJECT_STATE.md`
- модуль и ближайшие тесты по имени файла/фичи

Проверять:
- targeted unit tests for touched zone
- `PYTHONPATH=src python3 -m compileall src` для code changes

### Если задача про новую функцию

Читать:
- `AGENTS.md`
- `docs/PROJECT_BRIEF.md`
- `docs/restart/folioloom-restart-spec.md`
- `docs/restart/release-gates.md`
- relevant spec/plan from `DOCUMENT_INDEX.md`

Проверять:
- focused tests for new behavior
- related safety/privacy/deployment/payment gates

### Если задача про тесты

Читать:
- `AGENTS.md`
- target module
- related existing `tests/test_*.py`
- `README.md` verification commands

Проверять:
- new/changed targeted tests
- avoid weakening existing assertions around safety, auth, payments, secrets and user data

### Если задача про релиз

Читать:
- `AGENTS.md`
- `README.md`
- `CURRENT_PROJECT_STATE.md`
- `DOCUMENT_INDEX.md`
- `docs/restart/release-gates.md`
- `docs/deployment/admin-vps-runbook.md`
- `docs/deployment/restore-runbook.md`

Проверять:
- common verification commands from release gates
- `scripts/predeploy_check.sh`
- server smoke/backup/restore evidence only with human-approved environment access

### Если задача про документацию

Читать:
- `AGENTS.md`
- `README.md`
- `DOCUMENT_INDEX.md`
- relevant existing docs under `docs/`
- relevant project files if documenting code behavior

Проверять:
- facts are confirmed by repo files
- use `TBD` for human decisions and `Unknown` where evidence is missing
- do not weaken safety, legal, privacy, security, payment or deployment guardrails
