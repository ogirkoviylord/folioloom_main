# FolioLoom Admin Panel Full Audit

Date: 2026-06-03

## Scope And Evidence

Confirmed:
- I opened the in-app Browser and first checked `http://127.0.0.1:62062/admin/overview`.
- That target redirected to `/admin/login`; a local test password placeholder was rejected.
- I did not guess or read real secrets.
- I then launched an isolated local admin runtime from current `main` on `http://127.0.0.1:62063` with temporary audit-only paths under this folder.
- Screenshots and captured page metadata are saved in `artifacts/admin-audit-2026-06-03/`.
- The audit covers empty/test state, visible forms, filters, navigation, mobile/desktop layout, and safe local edge cases.

Limitations:
- Live production/beta data, real incident trace rows, real user rows, real provider keys, real activity streams, and real run reader states were not inspected.
- Accessibility findings are screenshot/DOM-snapshot based; they are not a full WCAG audit with keyboard/screen-reader testing.
- Dangerous actions were tested only in the local temporary runtime when safe.

Key evidence files:
- `page-capture-summary.json`
- `responsive-capture-summary.json`
- `02-overview.png`
- `06-providers.png`
- `10-settings-desktop.png`
- `24-mobile-overview.png`
- `25-mobile-providers.png`
- `29-integrations-telegram-expanded.png`
- `31-settings-invalid-telegram-id.png`
- `33-settings-allowlist-enabled-empty.png`

## Executive Summary

Overall rating: 6/10.

The admin panel is more coherent than a raw internal tool: it has a clear operational direction, good safety language, metadata-only framing, and a useful incident-first `Overview`. It is not yet a team-ready operations console. The biggest weaknesses are operational safety around high-impact actions, unclear information architecture between similar pages, weak empty states, limited role support, and mobile navigation that consumes too much vertical space.

Critical issues:
- `Enable allowlist` can be clicked with an empty allowlist and no confirmation. In a live closed beta this can block all non-listed users immediately.
- High-risk actions are visually close to routine actions and do not consistently show impact previews, confirmations, or recovery cues.
- Role model appears effectively owner-only; the UI talks about team workflows, but does not provide role-specific permissions or safe operator modes.
- Audit page exists but is empty in the tested state and does not yet prove a usable audit workflow to the operator.
- Raw-text reader warning is good, but the Reader still makes screenshot/support leakage a workflow risk unless stronger guardrails exist around export/copy/share behavior.

UX issues:
- `Logs`, `Translations`, `Activity`, `Operations`, `Security Events`, and `Upload Safety` overlap conceptually. A new operator will not know which page answers which incident question.
- Advanced navigation hides important pages like `Costs`, `Quality`, `Audit`, and `Security Events`.
- Mobile layout pushes content far below a huge nav block; there is no compact hamburger or sticky page toolbar.
- Empty tables say “No data found” but rarely explain what creates data, whether this is good/bad, or where to go next.
- Expandable integration cards expose `+`/`-` visually but are not announced as buttons/links in the DOM snapshot.

Product issues:
- The panel is strong for founder/operator diagnosis, weak for support, moderation, finance, and onboarding a new employee.
- Billing is present as a future placeholder, which may confuse operators because paid beta is blocked.
- Multi-channel integrations appear in UI even though the current product is Telegram-first; this risks scope confusion.

Missing features:
- Role-based operator modes.
- Confirmation and impact preview for blocking/destructive actions.
- Global search or command palette.
- Saved filters and incident queue.
- Explicit “copy safe evidence” affordances across all relevant incident pages, not only implied by trace/log concepts.
- Onboarding/help text for new operators.
- Better empty-state next steps.

Security risks:
- Empty allowlist enablement without confirmation: High.
- State-changing beta controls without clear impact preview: High.
- Integration secret forms inside broad integrations UI without role separation: Medium.
- Raw text reader workflow leakage risk: High.
- Audit log discoverability/empty-state weakness: Medium.

## Page Audits

### 1. Login

Screenshot: `32-login-invalid-local.png`

Purpose:
- Authenticate an admin owner into the console.

Main actions:
- Enter password.
- Sign in.

Clarity: 8/10.

What works:
- Minimal page.
- Invalid credentials message is neutral.
- No username enumeration because there is only a password field.

What is bad:
- No visible reminder that admin must remain SSH-tunnel-only.
- No lockout, rate-limit, last login, or support path visible from UI.

What is missing:
- “Use SSH tunnel” context.
- Caps lock/keyboard hint.
- Session/security metadata after login.

Potential errors:
- Owner may enter production credentials into a non-production local copy if environment label is absent.

UX problems:
- Error is clear but generic; that is acceptable for security, but there is no recovery cue.

QA observations:
- Invalid login state renders correctly.

### 2. Overview

Screenshot: `02-overview.png`, `24-mobile-overview.png`

Purpose:
- Triage inbox for actionable beta operations items.

Main actions:
- Open integrations.
- Open provider setup.
- Open settings.

Clarity: 8/10.

What works:
- Best page in the product conceptually.
- Items answer what happened, affected area, why now, and next step.
- Good operational severity labels: `Action needed`, `Blocked`.

What is bad:
- Does not show owner confidence: “local/test empty state” vs “live issue”.
- No global status line: can users translate right now, yes/no?
- No grouping by severity or age when the list grows.

What is missing:
- “Copy safe evidence” from overview item.
- Dismiss/snooze/assign state.
- Owner checklist for free beta blockers.

Potential errors:
- Operator may follow `Open integrations` even though Telegram-first scope means many integration cards are future/non-current.

UX problems:
- On mobile, nav consumes the first screen and triage starts far down.

QA observations:
- Mobile cards stack cleanly; no overlap seen.

### 3. Live Monitor

Screenshot: `03-live.png`

Purpose:
- Monitor active processing, queues, provider capacity, recent runs, and runtime state.

Main actions:
- Keep screen open.
- Inspect attention items, DeepSeek runtime, recent runs.

Clarity: 7/10.

What works:
- Clear top metrics: active, queued, failed, tokens.
- Separates provider runtime and recent runs.

What is bad:
- It reads like a status dashboard and an incident page at once.
- “Open monitor” is ambiguous because you are already on the monitor.

What is missing:
- Refresh timestamp and auto-refresh state clarity.
- Clear “system healthy/unhealthy” summary.
- Worker heartbeat drill-down in empty state.

Potential errors:
- Operator may assume zero rows means healthy; in an unconfigured runtime zero rows can also mean not connected.

UX problems:
- Dense diagnostic labels are useful for engineers but heavy for support staff.

QA observations:
- Empty table renders; no visual breakage seen.

### 4. Translations

Screenshot: `04-translations.png`, `27-mobile-translations.png`

Purpose:
- Review translation runs by state, date, file, direction, tokens, and safe errors.

Main actions:
- Filter by status/date.
- Open actions when rows exist.

Clarity: 7/10.

What works:
- Page description is explicit.
- Table headers match likely investigation needs.

What is bad:
- `Translations` and `Logs` appear nearly identical in empty state.
- Filter has only status/date visible in mobile; no obvious user/job search.

What is missing:
- Search by job ID, run ID, user ID, filename.
- Saved views: failed, active, high-cost, recently completed.
- “What creates a row here?” empty-state explanation.

Potential errors:
- Operator may look here for live jobs that are actually under `Operations`.

UX problems:
- Mobile table horizontally clips; columns extend beyond visible area.

QA observations:
- Filtered no-result state stays generic; it does not say filters are active.

### 5. Users

Screenshot: `05-users.png`

Purpose:
- List users with settings/security state inferred from activity.

Main actions:
- Open user profile when rows exist.

Clarity: 6/10.

What works:
- Columns anticipate support needs: channel, interface, target language, preview, security, last seen.

What is bad:
- Empty state does not explain how users appear.
- No search or filter in empty state.

What is missing:
- Search by Telegram ID.
- Support notes or tags.
- Allowlist state from user perspective.
- Recent documents/translations summary.

Potential errors:
- Support operator may conclude no users exist when ingestion/activity tracking is simply not populated in this environment.

UX problems:
- No task framing: “Find a user to investigate” would help.

QA observations:
- Empty table is stable.

### 6. Providers

Screenshot: `06-providers.png`, `25-mobile-providers.png`

Purpose:
- Manage provider-level diagnostics, runtime health, balance, and DeepSeek keys.

Main actions:
- Reload runtime.
- Refresh balance.
- Test all active keys.
- Add key.
- Open key management.

Clarity: 7/10 for engineers, 5/10 for non-engineers.

What works:
- Strong separation between configured keys, runtime state, balance, capacity, failure categories.
- Good safety copy: raw key values and secret IDs stay hidden.
- Disabled test-all state communicates why it is unavailable.

What is bad:
- Many `Unknown`/`n/a` values in empty state create cognitive noise.
- Routine and risky actions are visually similar.
- “Refresh balance” and “Reload now” may cause external/runtime effects but appear like normal buttons.

What is missing:
- Action classes: View / Probe / Change / Danger.
- Confirmation or impact text before reload/probe actions.
- Clear distinction between safe read-only diagnosis and external provider calls.

Potential errors:
- Operator may click `Refresh balance` or key tests during an incident without understanding provider traffic implications.

UX problems:
- Mobile page is very long; provider incident state becomes a wall.

QA observations:
- Mobile rendering repeats large nav and long cards; no overlap, but scan cost is high.

### 7. DeepSeek Keys

Screenshot: `07-provider-keys.png`

Purpose:
- Manage admin-managed DeepSeek keys and runtime reload.

Main actions:
- Add key.
- Test all keys.
- Reload runtime.
- Manage key inventory when rows exist.

Clarity: 7/10.

What works:
- Field guide is helpful.
- “Read-only env keys” vs admin keys is a strong distinction.
- No raw key values are shown in empty state.

What is bad:
- Add-key form appears close to high-risk runtime actions.
- “Weight” and “max parallel” need stronger guardrails for cost/capacity risk.

What is missing:
- Dry-run validation before saving.
- Required rotation reason.
- Confirmation for capacity changes.
- Last-used and last-failed context per key.

Potential errors:
- Admin may set too high max parallel or misleading weight.

UX problems:
- Key management is a specialized provider ops task but sits inside general admin navigation.

QA observations:
- Empty key inventory renders clearly.

### 8. Beta Controls

Screenshot: `08-beta-controls.png`

Purpose:
- Control beta allowlist and beta safety caps.

Main actions:
- Enable/disable allowlist.
- Add Telegram ID.
- Save beta safety caps.

Clarity: 7/10.

What works:
- Copy explains what allowlist and caps do.
- Safety summary ties missing secrets to actions.

What is bad:
- High-risk controls are too easy to operate.
- Allowlist can be enabled while empty.
- Negative Telegram ID is rejected silently with no visible error.

What is missing:
- Confirmation modal for allowlist enable/disable.
- Empty-list block or strong warning.
- Validation messages for rejected IDs.
- Preview: “0 users will be allowed”.

Potential errors:
- Owner can block every beta user by enabling an empty allowlist.
- Operator can save malformed caps if server-side validation is weak.

UX problems:
- Same content appears under `Settings`, creating duplication.

QA observations:
- `-1` Telegram ID produced no visible error and no add.

### 9. Upload Safety

Screenshot: `09-safety-upload.png`, `23-upload-safety-filter.png`

Purpose:
- Show scanner and upload-safety ledger metadata.

Main actions:
- Filter upload safety records.
- Open upload details when rows exist.

Clarity: 7/10.

What works:
- Metadata-only framing is correct.
- Top metrics cover scanner health, scanned/accepted/blocked/failed-closed, access violations.

What is bad:
- `Scanner health unknown` needs stronger severity in beta context.
- Empty state does not say whether upload safety is configured, disabled, unavailable, or just idle.

What is missing:
- Scanner config status.
- Last scanner heartbeat.
- Explicit fail-open/fail-closed state.
- Link to relevant release gate or runbook.

Potential errors:
- Operator may treat unknown scanner health as harmless.

UX problems:
- Filters are useful but no saved “blocked/infected/failed-closed” views.

QA observations:
- Filtered empty state does not make active filters obvious.

### 10. Settings

Screenshot: `10-settings-desktop.png`, `26-mobile-settings.png`

Purpose:
- Configure allowlist, beta safety controls, and inspect secret/config safety.

Main actions:
- Same as Beta Controls.
- Open missing secret/config targets.

Clarity: 6/10.

What works:
- Safety summary is useful and transparent.
- Environment badge is visible.

What is bad:
- Duplicates `Beta Controls`.
- Contains operational kill/cap controls without a dedicated “danger zone”.
- Decimal fields display comma values (`5,0`, `50,0`) which may be locale-dependent and risky if parsing expects dot elsewhere.

What is missing:
- Separate settings categories.
- Change history inline.
- Impact preview before saving caps.

Potential errors:
- Owner may not know whether `Settings` or `Beta Controls` is canonical.

UX problems:
- On mobile, form is readable but long; action buttons are not sticky.

QA observations:
- Empty allowlist enablement succeeded locally with no confirmation.

### 11. Logs

Screenshot: `11-logs-desktop.png`

Purpose:
- Review translation run logs.

Main actions:
- Filter runs.
- Open details, text diagnostics, reader, archive when rows exist.

Clarity: 6/10.

What works:
- Same columns as translations make it predictable.

What is bad:
- Too similar to `Translations`.
- Name `Logs` suggests raw logs, but page is actually translation run list.

What is missing:
- Clear distinction from `Translations`.
- Safe evidence packet CTA in empty/details states.

Potential errors:
- Operator may choose archive download instead of safe evidence flow if details page presents it.

UX problems:
- Advanced nav placement hides it, but logs are central to incident investigation.

QA observations:
- Empty state renders.

### 12. Internal Reader

Screenshot: `12-reader-desktop.png`, `28-mobile-reader.png`

Purpose:
- Generate owner-only before/after reports for approved local TXT/DOCX/EPUB fixtures.

Main actions:
- Choose sample/manual path.
- Provide source path and optional translation JSON mapping.
- Choose format and max fragment chars.
- Open reader.

Clarity: 7/10 for owner/dev, 4/10 for support.

What works:
- Raw text warning is prominent and good.
- Scope is owner-only and fixture-oriented.

What is bad:
- Manual path defaults to repository/test paths that may encourage path guessing.
- Raw text screenshot/support leakage risk is explicitly present.

What is missing:
- Stronger allowlist of approved fixture roots.
- Clear “do not use live `var/` data” UI constraint.
- Output privacy reminder on the generated report itself.

Potential errors:
- Operator may paste a live/runtime path.
- Screenshots of reader output could leak raw source/translation text.

UX problems:
- “Translation mapping JSON path” is technical; no validator or file picker.

QA observations:
- Form is readable on mobile.

### 13. Activity

Screenshot: `13-activity-desktop.png`, `22-activity-filter.png`

Purpose:
- Show user commands, buttons, settings, lifecycle events, and security outcomes.

Main actions:
- Filter by user, channel, surface, event, action, outcome, job, date.

Clarity: 7/10.

What works:
- Good event model for support and incident reconstruction.
- Filters are broad.

What is bad:
- Empty state is not actionable.
- No presets for common support investigations.

What is missing:
- “User timeline” jump.
- “Related translation/job” drill-in from filters.
- Export/copy safe evidence.

Potential errors:
- Support may filter too narrowly and conclude nothing happened.

UX problems:
- Event taxonomy is internal and not explained.

QA observations:
- Filtered empty state generic.

### 14. Operations

Screenshot: `14-operations-desktop.png`

Purpose:
- Inspect persistent jobs and workers.

Main actions:
- View job state.
- Pause/cancel/delete/retry when rows exist.

Clarity: 6/10.

What works:
- Top counters are useful.
- Worker visibility is present.

What is bad:
- Dangerous actions are not visible in empty state, so confirmation behavior could not be verified.
- Operators need guidance on when to act.

What is missing:
- Runbook-linked action guidance.
- Confirmation/impact preview for job mutation.
- “Copy safe evidence” per job.

Potential errors:
- Operator may pause/cancel/delete without knowing user impact.

UX problems:
- `Operations` is under Advanced, but job recovery may be a primary incident workflow.

QA observations:
- Empty state stable.

### 15. Audit

Screenshot: `15-audit-desktop.png`

Purpose:
- Show sensitive admin changes with actor, outcome, reason, redacted metadata.

Main actions:
- View audit entries when present.

Clarity: 5/10.

What works:
- The stated intent is exactly right for safety.

What is bad:
- Empty page does not show table headers, filters, or examples.
- No proof to an operator that allowlist/key/settings changes are being recorded.

What is missing:
- Audit table, filters, actor filter, action type filter.
- “Last sensitive action” summary.
- Retention/export policy.

Potential errors:
- Owner may believe audit exists but not know how to verify coverage.

UX problems:
- Too bare for such an important trust surface.

QA observations:
- Empty page renders mostly as a promise, not a tool.

### 16. Integrations

Screenshot: `16-integrations-desktop.png`, `29-integrations-telegram-expanded.png`

Purpose:
- Configure user-facing channels, embedded surfaces, webhooks, and automation connections.

Main actions:
- Expand integration card.
- Add connection with name and secret.

Clarity: 5/10.

What works:
- Cards are visually clean.
- Telegram connection form is simple.

What is bad:
- Non-Telegram integrations appear active in a Telegram-first product stage.
- Expand affordance is a small `+`; DOM snapshot exposes it as generic text, not a button.
- Required secrets are spread across Integrations and Settings.

What is missing:
- “Current scope: Telegram only” gating.
- Disabled/deferred states for WhatsApp/Instagram/Discord/Widget/Webhooks if not approved.
- Strong secret handling explanation per form.

Potential errors:
- Owner may configure unsupported channels or assume multi-channel product readiness.

UX problems:
- Clicking the card title expands; this is discoverable only by trying.

QA observations:
- Accessibility risk: expandable cards are not represented as buttons/links in DOM snapshot.

### 17. Billing

Screenshot: `17-billing-desktop.png`

Purpose:
- Placeholder for future payment providers, subscriptions, invoices, refunds, tax, payouts.

Main actions:
- None.

Clarity: 4/10.

What works:
- It does not claim billing is ready.

What is bad:
- Visible Billing navigation can imply paid readiness despite Gate C being blocked.
- Placeholder is too prominent for current product stage.

What is missing:
- Explicit “Blocked until Gate C” note.
- Link to payment/readiness decision.

Potential errors:
- New employee may search here for cost/budget work and confuse billing with beta cost safety.

UX problems:
- Billing belongs behind a future/deferred label.

QA observations:
- Placeholder renders.

### 18. Costs

Screenshot: `18-costs-desktop.png`

Purpose:
- Show token spend and beta safety budget.

Main actions:
- Inspect spend, top runs, top users, caps/remaining budget.

Clarity: 8/10.

What works:
- Explicitly separates usage view from billing setup.
- Good top-level today/7-day/month metrics.
- Budget cards are readable.

What is bad:
- No chart/trend.
- No filters by language/provider/model/user.

What is missing:
- Cost anomaly detection.
- Export safe cost summary.
- Forecast against monthly cap.

Potential errors:
- Finance role may treat beta safety as paid billing ledger unless the distinction is repeated everywhere.

UX problems:
- Costs is hidden under Advanced despite being important to owner.

QA observations:
- Empty state clear enough.

### 19. Quality

Screenshot: `19-quality-desktop.png`

Purpose:
- Show offline QA scores and run quality checks.

Main actions:
- Run quality check.
- Review Russian/Ukrainian sample scoring.

Clarity: 6/10.

What works:
- States that candidate/source/reference text stay out of admin UI.
- Shows expected path `var/quality-runs/latest.jsonl`.

What is bad:
- `Run quality check` may be an expensive or long operation but looks ordinary.
- Quality metrics can be mistaken for universal beta success criteria.

What is missing:
- Last run timestamp, duration, command/source.
- Explanation that RU/UK metrics are regression diagnostics, not universal launch metrics.

Potential errors:
- New employee may overinterpret METEOR/chrF scores.

UX problems:
- Requires knowledge of local file path and QA process.

QA observations:
- No-run state renders with missing samples.

### 20. Security Events

Screenshot: `20-security-events-desktop.png`

Purpose:
- Show blocked actions, cooldowns, policy trips, and suspicious service behavior.

Main actions:
- Inspect security event table.

Clarity: 7/10.

What works:
- Clear purpose.
- Uses shared metadata table shape.

What is bad:
- Empty state does not distinguish “no security events” from “security telemetry not connected”.

What is missing:
- Severity classification.
- Event presets: blocked upload, auth failure, rate limit, suspicious document.
- Escalation guidance.

Potential errors:
- Operator may assume no events means all clear.

UX problems:
- Security page hidden in Advanced.

QA observations:
- Empty table stable.

## Navigation Analysis

What is clear immediately:
- `Overview`, `Live`, `Translations`, `Users`, `Providers`, `Beta Controls`, `Safety`, `Settings` form the intended primary workflows.
- The UI has a calm operational style and consistent sidebar.

What requires searching:
- Incident evidence is split between `Overview`, `Translations`, `Logs`, `Operations`, `Activity`, and trace/detail pages.
- Costs are hidden in Advanced even though budget/caps are core beta operations.
- Audit and Security Events are hidden despite being high-trust surfaces.
- Integrations is hidden in Advanced while Overview points there as a required setup step.

Pages that feel misplaced:
- `Costs` should be primary for the owner during beta.
- `Audit` and `Security Events` should be closer to Safety or a Security group.
- `Billing` should be deferred/disabled, not equal weight with active pages.
- `Integrations` should either be primary setup or clearly deferred; currently it is Advanced but Overview sends users there.
- `Logs` and `Translations` need clearer separation or consolidation.

Grouping problems:
- `Settings` and `Beta Controls` duplicate content.
- `Safety` means Upload Safety, while Security Events is elsewhere. This naming will confuse operators.
- `Advanced` is a grab bag of important, future, risky, and diagnostic pages.

Searchability:
- No global search or command palette.
- No obvious way to jump by job ID, run ID, user ID, or filename globally.

## Role Analysis

### Founder

Easy:
- See blocking setup items.
- Check provider/key setup.
- Check beta budget and caps.

Hard:
- Decide where to investigate a failed user complaint.
- Know which pages are active vs future/deferred.

Missing:
- Founder daily checklist.
- Gate B readiness view.
- Safe evidence packet workflow from overview.

### Support Operator

Easy:
- Find `Users`, `Activity`, `Translations`.

Hard:
- Reconstruct a complaint without real presets.
- Know when raw text is forbidden.
- Distinguish Logs vs Translations vs Activity.

Missing:
- User support profile as primary entry.
- Saved support investigation flow.
- Safe notes/export.

### Content Moderator

Easy:
- Upload Safety page hints at blocked/infected/safety cases.

Hard:
- No moderation queue.
- No content policy workflow.
- Raw text is intentionally restricted.

Missing:
- Moderation queue/status.
- Policy reason taxonomy.
- Escalation and owner-review flow.

### Financial Manager

Easy:
- Costs page separates token spend from billing.
- Budget cards readable.

Hard:
- Costs hidden under Advanced.
- No forecasts or exports.
- Billing placeholder could confuse paid-vs-beta accounting.

Missing:
- Forecast to cap.
- Cost by user/language/model.
- Export safe finance summary.

### DevOps Engineer

Easy:
- Live, Providers, Operations, Upload Safety provide useful runtime hints.

Hard:
- No consolidated runtime health page.
- Unknown states are not prioritized by severity.
- No backup/restore visibility page in this UI.

Missing:
- Worker heartbeat details.
- Backup status.
- Restore rehearsal evidence.
- Environment/runtime config summary.

### New Employee

Easy:
- Understand that this is an admin console for translations.
- See missing setup items.

Hard:
- Know product stage and forbidden areas.
- Know which actions are dangerous.
- Know where to start for a complaint.

Missing:
- First-run guide.
- Role-specific mode.
- Inline “when to use this page” hints.

## Security & Safety Review

Findings:

1. Empty allowlist can be enabled with one click.
- Severity: High.
- Evidence: `33-settings-allowlist-enabled-empty.png`.
- Risk: blocks all users not in the list; with zero users, this can stop beta uploads.
- Fix: block enablement when list is empty or require explicit confirmation showing “0 users will be allowed”.

2. High-risk settings lack impact preview.
- Severity: High.
- Evidence: Settings/Beta Controls forms.
- Risk: caps, pause, allowlist changes can stop service or alter beta spend controls.
- Fix: add confirmation summary and audit reason field for high-impact changes.

3. Expandable integrations are not accessible as controls.
- Severity: Medium.
- Evidence: DOM snapshot exposes integration card as generic text.
- Risk: keyboard/screen-reader users may not discover forms.
- Fix: use `<button>` or accessible `<summary>` labels with `aria-expanded`.

4. Raw text reader can leak via screenshots/support notes.
- Severity: High.
- Evidence: Reader warning itself confirms raw text visibility.
- Risk: owner-only exception can be copied outside allowed surfaces.
- Fix: watermark raw reader, add copy/export friction, and keep explicit “not for issue/PR/support” banner on generated report.

5. Audit page is not operationally useful in empty state.
- Severity: Medium.
- Risk: team cannot verify sensitive actions were recorded.
- Fix: show table headers, last checked time, coverage checklist, filters, and sample-safe placeholder rows.

6. Billing placeholder can imply readiness.
- Severity: Medium.
- Risk: team may treat paid path as closer than Gate C allows.
- Fix: label as `Deferred until Gate C` and move behind future/disabled grouping.

7. No visible role-based access model.
- Severity: Medium.
- Risk: support/finance/devops roles can see or trigger owner-level controls if shared access is added later.
- Fix: add role model before broader team access.

8. External/provider probe actions are visually routine.
- Severity: Medium.
- Risk: operator may generate provider traffic or reload runtime during incident.
- Fix: label Probe/Change/Danger classes and require confirmation for reload/test-all.

## Business Process Review

Can the team serve customers through this panel?
- Partially. The ingredients exist (`Users`, `Translations`, `Activity`), but support workflow is not guided enough.

Can the team find problems?
- Founder/engineer: yes, with knowledge.
- New support operator: only partially; too many similar diagnostic pages.

Can the team analyze expenses?
- Yes for beta token spend and caps; no for paid billing, reconciliation, forecasts, or exports.

Can the team investigate complaints?
- Partially. Needs a user-centric complaint workflow and safe evidence packet.

Can the team moderate content?
- Not really. Upload Safety exists, but moderation workflow is not a first-class product area.

Can the team track translations?
- Yes at a basic level through Translations/Logs/Live/Operations, but these should be unified around Translation Trace.

Process bottlenecks:
- Incident investigation spans too many pages.
- Empty states do not teach.
- Risky actions do not require enough intent.
- Role boundaries are not visible.
- Future surfaces compete with active beta operations.

## New Employee Test

First 5 minutes:
- They will understand this is an admin console for FolioLoom.
- They will see missing Telegram/DeepSeek setup.
- They will understand there are translation, user, provider, safety, and settings areas.

Where they get confused:
- Whether to use `Translations` or `Logs`.
- Why `Billing`, WhatsApp, Instagram, Discord, and Website Widget exist if the product is Telegram-first and paid launch is blocked.
- Whether `Safety` includes security events.

What they cannot find:
- A single “investigate user complaint” workflow.
- A global search by user/job/run/file.
- Backup/restore visibility.
- Release readiness / Gate B status.

Likely wrong actions:
- Enable allowlist too early.
- Click provider probes/reload during an incident.
- Treat Billing as active.
- Screenshot Reader output into support/issue context.
- Assume empty tables mean healthy systems.

## Priority Roadmap

### P0 - Critical

1. Add confirmation and blocking rules for allowlist enablement.
- Impact: prevents accidental beta lockout.
- Risk: High if not fixed.
- Complexity: Low/Medium.

2. Add action classes and confirmations for high-impact controls.
- Impact: prevents accidental pause/cap/provider runtime mistakes.
- Risk: High.
- Complexity: Medium.

3. Make Audit page operational.
- Impact: improves trust and reviewability of sensitive changes.
- Risk: Medium/High.
- Complexity: Medium.

4. Strengthen raw-text Reader leakage guardrails.
- Impact: protects user/source/translation privacy.
- Risk: High.
- Complexity: Medium.

### P1 - Important

1. Consolidate incident workflow around Translation Trace.
- Impact: faster debugging and support.
- Risk: Medium.
- Complexity: Medium/High.

2. Clarify navigation groups.
- Impact: new operators find things faster.
- Risk: Medium.
- Complexity: Low/Medium.

3. Add global search by user/job/run/file.
- Impact: major support speedup.
- Risk: Medium.
- Complexity: Medium.

4. Improve empty states with “what this means / next step”.
- Impact: reduces false confidence.
- Risk: Low/Medium.
- Complexity: Low.

5. Move/de-emphasize deferred Billing and non-Telegram integrations.
- Impact: reduces scope confusion.
- Risk: Medium.
- Complexity: Low.

6. Add mobile compact nav.
- Impact: makes mobile emergency checks usable.
- Risk: Low.
- Complexity: Medium.

### P2 - Later

1. Saved filters and investigation presets.
2. Cost charts and forecast-to-cap.
3. Role-specific landing pages.
4. Keyboard shortcuts for Reader.
5. Exportable safe incident reports.
6. Inline runbook links.
7. Better visual severity mapping.
8. Setup wizard for first admin launch.

## Quick Wins

1. Disable `Enable allowlist` when zero IDs are present.
- Effect: prevents lockout.
- Complexity: Low.
- Why first: highest safety impact for a tiny UI/backend check.

2. Add confirmation text to allowlist toggle.
- Effect: forces intent.
- Complexity: Low.
- Why first: high-risk action.

3. Add visible error for invalid Telegram ID.
- Effect: removes silent failure.
- Complexity: Low.
- Why first: current edge case fails quietly.

4. Rename `Logs` to `Run Logs` or merge with `Translations`.
- Effect: reduces navigation confusion.
- Complexity: Low.
- Why first: immediate clarity.

5. Label Billing as `Deferred - Gate C`.
- Effect: prevents paid-readiness misunderstanding.
- Complexity: Low.
- Why first: aligns UI with project guardrails.

6. Change integration card expanders to real buttons.
- Effect: improves accessibility and discoverability.
- Complexity: Low/Medium.
- Why first: current affordance is weak.

7. Add empty-state next steps to tables.
- Effect: teaches operators what “no data” means.
- Complexity: Low.
- Why first: most pages currently empty in setup state.

8. Add `Copy safe evidence` CTA to Overview items.
- Effect: shortens Codex/debug workflow.
- Complexity: Medium.
- Why first: matches approved console direction.

9. Move `Costs` to primary nav during beta.
- Effect: makes budget visible.
- Complexity: Low.
- Why first: beta cost guard is core operations.

10. Add mobile hamburger/compact nav.
- Effect: makes emergency mobile checks usable.
- Complexity: Medium.
- Why first: current mobile top nav consumes too much screen.

## Routing Receipt

- Classification: `spike / discovery`.
- Risk level: Medium for audit, High/Critical areas observed but not changed.
- Primary repo-level skill: `pr-review`-style review/audit route.
- Supporting skills: `product-design:audit`, `browser:control-in-app-browser`.
- Human approval status: not required for local isolated analysis; missing for live admin credentials, destructive operations, auth/security changes, deployment, real runtime data access, or code changes.
- Allowed action: analysis only.
- Verification: in-app Browser visual/DOM audit, screenshots, local isolated admin runtime, safe local edge-case checks.
