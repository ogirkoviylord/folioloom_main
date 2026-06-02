# Release Checklist

## 1. Назначение

Этот документ используется перед релизом, деплоем, public launch или любым
важным production change в FolioLoom.

AI-агенты не имеют права считать релиз готовым без прохождения этого checklist
и сверки с `docs/HANDOFF.md`, `docs/ROADMAP.md`, `docs/DECISIONS.md`,
`docs/QUALITY_GATES.md`, `docs/RISK_REGISTER.md` и
`docs/restart/release-gates.md`.

Финальное решение `GO / NO-GO` всегда принимает человек-владелец проекта. Этот
файл помогает собрать evidence, но не заменяет human approval.

## 2. Release types

### Documentation-only release

Применимо, когда меняются только документы. Для такого релиза code tests можно
не запускать, если документ не меняет поведение, deployment process, release
readiness claims, security/privacy/legal/payment claims или user data handling.
Нужно явно указать, что tests не запускались и почему.

### Internal development release

Применимо для локального handoff, merge или dev-итерации без production deploy
и без публичного beta/public launch. Нужны focused tests для измененной зоны и
проверка, что scope не затрагивает high-risk области без approval.

### Closed beta release

Применимо. Текущий подтвержденный milestone проекта - free closed beta для
trusted Telegram users с форматами TXT, DOCX и EPUB. Перед таким релизом нужен
Gate B evidence report или явные owner-approved deferrals.

### Public beta release

TBD. В активных документах public beta как отдельная стадия не подтверждена.
Paid beta и public production описаны как будущие gated стадии, но не готовы.

### Production release

Применимо только как будущий тип релиза. Текущий статус проекта: public
production not ready. Production release требует Gate D, legal/privacy/support
готовности, monitoring/alerts, backup/restore evidence, security hardening и
явного human approval.

## 3. Pre-release checklist

- [ ] Current state reviewed in `docs/HANDOFF.md`.
- [ ] Roadmap phase confirmed in `docs/ROADMAP.md`.
- [ ] Relevant decisions reviewed in `docs/DECISIONS.md`.
- [ ] Risks reviewed in `docs/RISK_REGISTER.md`.
- [ ] Quality gates passed in `docs/QUALITY_GATES.md`.
- [ ] Relevant Gate A/B/C/D items reviewed in `docs/restart/release-gates.md`.
- [ ] For closed beta, Gate B evidence report exists or owner-approved
  deferrals are recorded.
- [ ] No unresolved high/critical risks without explicit acceptance.
- [ ] No paid/public/production readiness claims added without evidence.
- [ ] Human owner approved release scope.

## 4. Code readiness

Confirmed project commands:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
scripts/predeploy_check.sh
```

Confirmed targeted/predeploy checks:

```bash
PYTHONPATH=src python3 -m unittest tests.test_<module>
python3 -m ruff check <focused files>
scripts/server_smoke_check.sh
scripts/server_status.sh
```

Notes:

- `scripts/predeploy_check.sh` is the current predeploy gate.
- Dedicated integration test command: TBD / not found.
- Dedicated typecheck command: TBD / not found.
- Dedicated formatting check command: TBD / not found.
- Repo-wide `python3 -m ruff check --no-cache src tests scripts` is documented
  as debt signal, not a free closed-beta blocker.
- Server smoke checks require an approved target environment.
- Agent-executed deploys are allowed only for an exact owner-approved
  target/ref/command and must use the documented deploy path, currently
  `scripts/deploy_server.sh`. This does not approve release readiness or allow
  secrets/env inspection, deployment-script edits, runtime-data operations,
  database/state changes, backup/restore changes, auth/security changes,
  legal/privacy changes, payment changes or provider-setting changes without
  separate approval.

Checklist:

- [ ] Unit tests pass: `PYTHONPATH=src python3 -m unittest discover -s tests`.
- [ ] Focused tests for changed areas pass.
- [ ] Integration tests pass, if available. Current formal command: TBD.
- [ ] Compile check passes: `PYTHONPATH=src python3 -m compileall src`.
- [ ] Lint passes, if available: targeted ruff or `scripts/predeploy_check.sh`.
- [ ] Typecheck passes, if available. Current command: TBD.
- [ ] Formatting check passes, if available. Current command: TBD.
- [ ] Predeploy gate passes: `scripts/predeploy_check.sh`.
- [ ] Smoke test performed: local/predeploy smoke, and server smoke only on an
  approved target environment.
- [ ] For agent-executed deploys, exact owner approval, target environment,
  branch/ref or commit, deploy command, rollback expectations and server
  smoke/status checks are recorded.
- [ ] No unexpected dependency changes.
- [ ] No secrets committed.
- [ ] No real `.env*` files read, edited or included in output.
- [ ] No high-risk files changed without approval.

## 5. Product readiness

Confirmed current product shape: Telegram-first translation service for
authorized long documents. Closed-beta formats are TXT, DOCX and EPUB.
Current audience is trusted beta users and owner/admin. Paid public SaaS,
public self-serve signup, public admin, new formats and payment UI are out of
scope for the next beta.

Checklist:

- [ ] Telegram upload -> validation -> rights confirmation works.
- [ ] Translation mode selection, target language selection, estimate and
  explicit confirmation work.
- [ ] Persistent job/work-unit creation works.
- [ ] Worker processing produces final or partial result.
- [ ] Progress, cancel, status/history/My Books flows work.
- [ ] Automatic final/partial result delivery is not duplicated for the same
  job/result within a running bot process; durable cross-restart delivery
  tracking remains Unknown unless separately evidenced.
- [ ] Core workflow survives bot/worker restart.
- [ ] User-facing errors are understandable and do not expose provider internals.
- [ ] Onboarding / instructions are clear for trusted beta users.
- [ ] Rights confirmation remains visible before full processing.
- [ ] Beta allowlist can be managed and enabled from SSH-tunneled admin.
- [ ] Cost caps and kill switch are checked before release.
- [ ] Admin/debug flow works through SSH tunnel, if applicable.
- [ ] Admin bulk provider key tests are not run during active translations or
  active provider requests; PR #38 guards this path and operator docs say to
  wait until both counters return to 0.
- [ ] Known limitations are documented.
- [ ] Out-of-scope features are not presented as ready.
- [ ] Free preview status is confirmed or explicitly deferred by owner.
  Current Gate B status: unchecked. Issues #51/#52 are merged and issue #53
  branch adds Telegram preview rendering; issue #54 preview-acceptance guard and
  release evidence are still required.
- [ ] Real TXT/DOCX/EPUB matrix has release evidence. Current Gate B status:
  unchecked.

## 6. Data and privacy readiness

Confirmed facts:

- User documents and generated files are stored through local object storage and
  runtime paths under the server `./var` mount / `/data` container paths.
- PostgreSQL is used for server scheduler/job/work-unit state.
- Real `.env`, `.env.dev` and `.env.beta` files exist locally and must not be
  read, edited or printed by agents.
- Retention/TTL policy is proposed in docs, but Gate B TTL cleanup remains
  unchecked.

Checklist:

- [ ] User data handling reviewed.
- [ ] File/data retention reviewed. Current TTL cleanup evidence: Unknown /
  Gate B unchecked.
- [ ] Delete behavior reviewed. Current evidence: Unknown unless release report
  proves it.
- [ ] Backup scope reviewed for source, intermediate, partial, final, runtime DB
  and admin state.
- [ ] Privacy/legal text reviewed, if applicable. Current public legal/privacy
  readiness: TBD / not production-ready.
- [ ] No unnecessary logging of sensitive data.
- [ ] Logs/admin do not expose raw document text, prompts, translations or API
  keys outside the approved owner-only Text diagnostics surface; safe archives,
  telemetry, normal admin pages and support artifacts remain redacted.
- [ ] Access controls reviewed, if applicable.
- [ ] Destructive operations reviewed and approved by human owner.
- [ ] Retention or user-data behavior changes have explicit human approval.

## 7. Security readiness

Checklist:

- [ ] Secrets are not committed.
- [ ] Real env files are not read, edited, copied or printed.
- [ ] `.env.server.example` and other examples contain placeholders only.
- [ ] Auth/permissions reviewed, if applicable.
- [ ] Admin remains SSH-tunnel-only for closed beta.
- [ ] External integrations reviewed: Telegram Bot API and DeepSeek-compatible
  provider layer.
- [ ] Provider details remain internal and are not exposed as user-facing model
  picker.
- [ ] Environment config reviewed.
- [ ] Rate limits / abuse controls reviewed, if applicable.
- [ ] Cost caps, job limits and kill switch reviewed.
- [ ] Dependency risks reviewed.
- [ ] No raw document text, prompts, translations or API keys appear in logs,
  telemetry, release artifacts or normal admin views. The approved owner-only
  Text diagnostics surface may show raw source/translated work-unit text for
  incident debugging.
- [x] Upload hardening/quarantine baseline is confirmed or explicitly deferred.
  Current Gate B status: checked by issue #73 local synthetic evidence.
- [x] Local malware/AV scanning gate is confirmed before parsing or explicitly
  deferred by owner. Current Gate B status: checked by issue #95 metadata-only
  local evidence.
- [ ] Public malware scanning services do not receive user documents by default.
- [ ] Scanner errors/timeouts/unavailable verdicts fail closed for beta unless
  owner-approved otherwise.

## 8. Operations readiness

Confirmed operational shape:

- Runtime services: `api`, `bot`, `worker`, `postgres`, `redis`, internal-only
  `clamd`.
- Deploy command documented: `scripts/deploy_server.sh`.
- Predeploy gate documented: `scripts/predeploy_check.sh`.
- Server smoke/status scripts documented: `scripts/server_smoke_check.sh` and
  `scripts/server_status.sh`.
- Restore runbook exists in `docs/deployment/restore-runbook.md`.
- Production deployment requires explicit human approval.

Checklist:

- [ ] Deployment steps documented.
- [ ] Production deployment explicitly approved by human owner.
- [ ] Rollback plan exists.
- [ ] Backup export exists and passes `scripts/verify_backup_export.py`.
- [ ] Restore rehearsal passed from a backup artifact.
- [ ] Monitoring/logging reviewed.
- [ ] Metadata-only owner runbook/report for Alerts MVP exists. Current Gate B
  status: unchecked; issue #71 chose owner report now and admin UI later.
- [ ] Metadata-only owner runbook/report for backup visibility exists. Current
  Gate B status: unchecked; issue #71 chose owner report now and admin UI later.
- [ ] Backup plan reviewed, if applicable.
- [ ] Incident response/contact path defined. Current public-production status:
  TBD / Unknown.
- [ ] Support/debug procedure documented.
- [ ] `scripts/server_smoke_check.sh` passed on target server or missing server
  condition is recorded.
- [ ] If upload scanning is enabled, `scripts/server_smoke_check.sh` confirms
  the bot container can reach internal `clamd` and records only safe
  PING/VERSION/EICAR metadata.

## 9. AI-agent release rules

- AI-агент не деплоит production без явного human approval.
- AI-агент не меняет release scope сам.
- AI-агент не принимает high/critical risks сам.
- AI-агент не меняет pricing, payment, legal, security или privacy без approve.
- AI-агент не меняет secrets, real env files, deployment files, auth, user data
  handling, retention, backups, database state или migrations без approve.
- AI-агент не объявляет paid beta, public beta или production ready без
  соответствующего gate evidence и human approval.
- AI-агент обязан обновить `docs/HANDOFF.md` после релиза.
- AI-агент обязан записать tests/checks run и честно отметить not run, Unknown
  или TBD.

## 10. Release decision

Use this format for the final release decision:

```text
Release name:
Release type:
Date:
Owner:
Scope:
Passed checks:
Known risks:
Accepted risks:
Rollback plan:
Final decision: GO / NO-GO
Human approval:
```

Rules:

- `Accepted risks` must name the human approver.
- `GO` is not valid without human approval.
- `NO-GO` should list blockers and next actions.
- For closed beta, Gate B must be complete or explicitly deferred in a signed
  go/no-go note.
- For paid beta, Gate C must be complete.
- For public production, Gate D must be complete.

## 11. Post-release checklist

- [ ] Verify app/service is working.
- [ ] Check logs.
- [ ] Check user-facing flow.
- [ ] Check admin/live/provider/cost surfaces, if applicable.
- [ ] Check critical metrics, if available.
- [ ] Check cost caps, kill switch and provider health for beta release.
- [ ] Document issues.
- [ ] Update `docs/HANDOFF.md`.
- [ ] Update `docs/ROADMAP.md` if phase changed.
- [ ] Add new decisions to `docs/DECISIONS.md` if needed.
- [ ] Add or update risks in `docs/RISK_REGISTER.md` if needed.
- [ ] Record release evidence, commands, artifacts and owner decision.
