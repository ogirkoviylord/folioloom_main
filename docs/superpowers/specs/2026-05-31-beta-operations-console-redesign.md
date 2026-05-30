# Beta Operations Console Redesign

Status: Approved design direction, not implemented.
Owner approval: approved in owner conversation on 2026-05-31.

## Goal

Redesign the existing SSH-tunneled admin console into a beta operations console
that helps the owner understand what needs attention, investigate translation
and provider failures, and collect safe evidence for Codex without hunting
through several similar admin pages.

This is not a public admin hardening plan, paid billing dashboard, deployment
change, auth/RBAC redesign, or production-readiness claim.

## Owner Problem

The current admin console exposes several pages that feel similar during an
incident:

- `Logs`
- `Activity`
- `Operations`
- `AI Providers`
- provider key detail/settings surfaces

The owner specifically gets lost when a translation crashes. The current
workflow is to click through several log-like pages, download details, send
Codex the details and the failed book, and ask for debugging help. This is too
slow and too dependent on the owner already knowing which internal artifact is
the right one.

The owner also wants provider/key failures, such as issue #141-style key
failures, to be visible and diagnosable without confusing key inventory,
validation, runtime visibility and key settings.

## Design Principles

- Make the admin console incident-first, not module-first.
- Default to read-only observation; state-changing actions live deeper.
- Show what needs attention, why it appears, and the next safe step.
- Keep existing raw/advanced admin pages available until the new workflow
  proves it covers real incidents.
- Preserve current safety guardrails: no raw document text, prompts,
  translations, API keys, stack traces, provider internals, backup archives or
  restored files in ordinary admin views or evidence packets.
- Keep public admin exposure, payments, legal/privacy copy, deployment,
  database schema/state changes, runtime data operations and new production
  dependencies out of this redesign unless a separate approved issue covers
  them.
- Treat `Unknown` as an honest failure category when the system cannot infer a
  cause.

## Core Concept

The redesign should organize the owner experience around objects and incident
flows instead of standalone pages:

- `Translation`
- `User`
- `Upload`
- `Job`
- `Work unit`
- `Provider key`
- `Incident`

Existing pages may remain as implementation details, but the owner should move
through connected trace views rather than deciding whether to open `Logs`,
`Activity` or `Operations`.

## Primary Workflow: Translation Failure Trace

The first implementation slice should solve the owner's highest-friction path:
a translation crashed and the owner needs to know why.

A failed translation should open a trace page that gathers safe metadata from
the relevant surfaces:

- user reference;
- upload and document metadata;
- target language and translation mode;
- job id and work-unit state;
- translation run id;
- status timeline;
- safe failure reason;
- failure category, including `Unknown` when necessary;
- provider/key metadata if the failure is provider-related;
- links to advanced logs, activity and operations views;
- safe evidence summary for Codex.

The trace page should avoid presenting archive download as the primary path.
Downloads may remain available as an advanced fallback.

## Evidence Packet

The owner needs a safe way to pass incident context to Codex.

The evidence packet should be copyable or downloadable and include only safe
metadata:

- `run_id`;
- `job_id`;
- safe user reference;
- document kind and safe filename/metadata where already allowed;
- language direction and translation mode;
- timestamps;
- status;
- safe failure category;
- safe error summary;
- provider/key status metadata;
- links to relevant admin trace/detail pages.

The evidence packet must not include raw document text, translated text,
prompts, API keys, unredacted provider responses, stack traces, secret ids,
object-storage paths or backup artifacts.

## Provider Incident Clarity

Provider and key diagnostics should distinguish these questions:

- Is a key configured?
- Is a key valid?
- Is a key enabled for use?
- Does runtime see the key?
- Is runtime reload pending or stale?
- Does the provider have low balance or unavailable balance status?
- Which safe failure categories affected the key recently?
- Is there an active fallback key?

The provider incident UI should not make key inventory, key settings, runtime
status and provider health look like duplicated controls. The first layer
should explain state; mutating actions such as disable, rotate, capacity
changes, runtime reload and bulk testing should remain deeper and clearly
classified.

## Overview As Triage

The redesigned overview should be a triage inbox, not a dashboard of every
metric. It should show only actionable items that have a clear reason and next
step.

Suggested severity model:

- `Info`: safe fact, no action required.
- `Watch`: observe; not currently blocking.
- `Investigate`: open a trace or provider incident view.
- `Action needed`: owner decision or safe operational action required.
- `Blocked`: translations or provider work cannot proceed.

Each item should answer:

- What happened?
- Why is it shown now?
- Who or what is affected?
- Where should the owner click next?

Examples:

- failed translations awaiting investigation;
- provider keys with recent safe failure categories;
- low DeepSeek balance;
- high or stalled translation queue;
- upload-safety failures that need investigation;
- backup/restore visibility gaps when they are part of the current beta
  readiness work.

## Navigation Direction

The owner currently finds this grouping easier:

- `Overview`
- `Live`
- `Translations`
- `Users`
- `Providers`
- `Beta Controls`
- `Safety`
- `Settings`

`Billing` should not be treated as active paid readiness while Gate C is
blocked. It may remain reserved or moved deeper until payment work is approved.

`Logs`, `Activity` and `Operations` should not all remain top-level incident
entrypoints. They can remain as advanced/raw views, but the primary workflow
should be translation trace and user/provider incident views.

## User Profile Direction

The `Users` area should behave like a profile for beta support and debugging:

- recent user actions;
- uploaded documents as safe metadata;
- selected target language and translation mode;
- linked translation runs;
- linked failures;
- bug reports or support-relevant events when implemented.

This is a support/debug view, not a public customer-management system.

## Action Semantics

State-changing actions should not compete visually with read-only diagnosis.

Recommended action classes:

- `View`: open detail, trace or related entity.
- `Copy evidence`: copy safe metadata for Codex.
- `Refresh`: read-only status refresh.
- `Probe`: provider or runtime check that may call an external/internal service.
- `Change`: update key, setting or beta-control state.
- `Danger`: cancel, disable, remove, rotate or otherwise affect active service
  behavior.

Risky actions should show what they change before execution and require
confirmation where appropriate. Disabled actions should explain why they are
unavailable.

## Visual Design Direction

The console should feel like a calm operational tool, not a marketing SaaS
dashboard and not a dark "server room" interface. The owner should be able to
open it during a beta incident, quickly see what needs attention, and avoid
visual noise.

Visual tone:

- light, quiet and work-focused;
- dense enough for operational scanning, but not cramped;
- low-decoration, high-readability;
- status colors used sparingly and consistently;
- no hero sections, promotional cards, decorative gradients, bento layouts or
  ornamental imagery;
- no nested cards; use panels, tables, lists and detail rails instead.

Recommended palette:

- page background: near-white or very light neutral gray;
- primary surfaces: white;
- borders: light neutral gray;
- primary text: near-black neutral;
- secondary text: muted gray;
- links and primary read actions: blue;
- system/technical diagnostics: restrained indigo;
- warning/watch/probe states: amber;
- dangerous or blocking states: red;
- healthy states: muted green, used only where it helps scanning.

The palette must not become one-note blue, purple, beige, dark slate or
decorative gradient-heavy. Color must map to action semantics and operational
meaning.

Typography:

- compact operational scale, not hero-scale typography;
- page title around admin-console scale, not landing-page scale;
- labels, table cells, buttons and status badges have explicit font sizes and
  line heights;
- no negative letter spacing;
- long ids and filenames use monospace or constrained text styles only when it
  improves scanning.

## Application Shell

Use a stable left sidebar and a restrained main workspace.

Sidebar:

- fixed navigation groups with clear active state;
- recommended top-level labels: `Overview`, `Live`, `Translations`, `Users`,
  `Providers`, `Beta Controls`, `Safety`, `Settings`, `Advanced`;
- `Advanced` can contain raw `Logs`, `Activity`, `Operations`, `Audit` and
  other diagnostic surfaces until the new flows prove enough;
- each item should have a small icon only if the icon improves recognition;
  icons must be consistent in stroke weight, size and alignment.

Header:

- compact page title and one-line purpose;
- environment badge such as `local`, `dev` or `beta`;
- signed-in actor/session affordance;
- no crowded status widgets in the global header.

Main workspace:

- max-width constrained enough for readable tables and traces;
- consistent vertical rhythm between toolbar, filters, list/table and detail
  content;
- avoid wide text blocks; operational detail should live in rows, timeline
  entries, summary fields and side rails.

## Screen-Level Design

### Overview

Overview is a triage inbox. It should show a short list of items that require
attention, not every available metric.

Each triage row should include:

- severity;
- what happened;
- affected entity;
- why it is shown now;
- next action, usually `Open trace` or `Open provider`.

Avoid showing many competing buttons. A triage row should have one primary
path forward.

### Translations

The translations list should be table-first on desktop and compact-list-first
on narrow screens.

Desktop row anatomy:

- status;
- started/updated time;
- safe user reference;
- safe filename/document metadata;
- mode and language direction;
- job/run reference;
- safe failure category or current state;
- one primary action: `Open trace`.

Filters should be simple segmented controls or tabs:

- `Failed`;
- `Running`;
- `Queued`;
- `Completed`;
- `Needs review` if evidence exists.

Do not add five row-level actions. Advanced links belong in the trace page.

### Translation Trace

The trace screen is the central investigation view. It should read like a case
file, not a generic log viewer.

Recommended layout:

- top summary strip with status, failure category, start/fail time and primary
  action;
- left/main column with timeline and grouped facts;
- right sticky rail with `What to check next` and `Evidence`;
- advanced links at the bottom or in a collapsed section.

Summary blocks:

- `User`;
- `Document`;
- `Choices`;
- `Job`;
- `Provider`, only when relevant or known.

Timeline entries should be compact, timestamped and safe. Unknown states should
be explicit rather than hidden.

### Providers

Providers should distinguish status from settings.

First layer:

- provider health;
- active/degraded/missing channels;
- balance status;
- runtime freshness;
- recent provider/key incidents;
- whether fallback capacity exists.

Second layer:

- key inventory;
- validation state;
- runtime visibility;
- recent failures;
- safe details.

Third layer:

- disable, rotate, capacity changes, runtime reload and bulk tests.

Mutating controls should never visually compete with read-only diagnosis.

### Users

The user view should support debugging and beta support:

- user safe reference;
- recent uploads;
- recent translation choices;
- linked failed/running/completed translations;
- recent activity timeline;
- bug reports or support-relevant events when implemented.

This should feel like a support profile, not a CRM or public customer account
dashboard.

## Component System

Implement repeated UI through a small design system rather than one-off HTML
styles.

Core components:

- `StatusBadge`: status, severity and category badges with fixed variants.
- `IncidentRow`: triage row with reason, affected entity and one next action.
- `TraceTimeline`: compact event timeline with safe metadata only.
- `EvidenceBox`: safe copy/download evidence area.
- `EntityLink`: consistent links for user, job, run, upload and provider key.
- `ActionButton`: variants for `view`, `copy`, `refresh`, `probe`, `change`
  and `danger`.
- `KeyHealthRow`: provider key state row that separates configured, valid,
  runtime-visible, active and recently failing states.
- `AdvancedLinkGroup`: secondary access to raw logs/activity/operations.

Status badge rules:

- badges must have stable widths where practical;
- status text should be short and predictable;
- color is not the only signal; include readable labels;
- do not invent many near-identical severity colors.

Button rules:

- buttons must not resize surrounding layout on hover, loading or disabled
  states;
- button labels should be short: `Open trace`, `Copy evidence`, `Refresh`,
  `Test key`, `Reload`, `Disable`;
- long labels should wrap only where the component is designed for two lines;
- dangerous actions require visual separation and confirmation when
  appropriate;
- disabled actions must explain why they are unavailable.

Table/list rules:

- table columns should have explicit min/max behavior;
- long filenames, ids and error categories must truncate or wrap safely without
  overlapping adjacent content;
- every row should have one dominant action;
- dense rows should use detail pages rather than stuffing all diagnostics into
  the table.

## Responsive And Overflow Rules

The admin console must be comfortable on a desktop and usable on a narrow
laptop or mobile-width browser.

Desktop:

- sidebar stays visible;
- tables use stable column widths;
- trace detail uses main column plus right rail.

Narrow/mobile:

- sidebar can collapse into a top/nav drawer pattern;
- table rows become stacked compact items;
- right trace rail moves below the main summary;
- action buttons stack predictably and keep full hit areas;
- long filenames, ids, statuses and button labels cannot overflow their
  containers.

Hard visual failures:

- clipped button text;
- table columns pushing off-screen without a usable fallback;
- overlapping badges, ids or actions;
- unreadable small captions;
- repeated card nesting;
- dangerous actions styled like ordinary links;
- raw/advanced links visually competing with the primary safe trace path.

## Visual QA Gates

Each implementation slice should include browser-based visual verification,
not only unit tests.

Minimum visual checks:

- desktop viewport;
- narrow laptop viewport;
- mobile-width viewport;
- one empty state;
- one healthy state;
- one failed/blocked state;
- long filename and long id examples;
- disabled/probe/danger action examples.

Before handoff, verify:

- text stays inside buttons and panels;
- badges and actions do not overlap;
- tables collapse or scroll intentionally;
- primary next action is visually obvious;
- advanced/raw views are available but not dominant;
- no raw document text, prompts, translations, API keys or stack traces appear
  in the redesigned surfaces.

Use the Browser plugin for local rendered verification after frontend changes.
If concept images or Figma mockups are approved later, compare rendered
screenshots against the accepted concept and record visible deviations.

## Implementation Order

The redesign should be split into small issues and PRs:

1. Translation Failure Trace and safe evidence packet.
2. Provider/key incident clarity.
3. Overview triage inbox backed by the new trace/incident links.
4. Navigation cleanup: demote or group raw `Logs`, `Activity` and `Operations`
   behind the new primary workflows.
5. Action semantics and visual treatment for read-only, probe, change and
   danger actions.
6. User profile support/debug view improvements.

Do not start with a broad navigation rewrite. The first PR should prove that a
real failed translation can be investigated in one place.

## Non-Goals

- Public admin exposure or public-production hardening.
- Named admin accounts, MFA, role redesign or auth/session changes.
- Paid beta, billing ledger, payment UI, refunds or pricing changes.
- Deployment, Docker, server script or bind-address changes.
- Database schema/state migrations.
- Runtime `var/` operations, destructive cleanup, retention/TTL behavior or
  backup mutation.
- New production dependencies.
- Displaying raw document text, prompts, translated text, API keys, secret
  values, unredacted provider responses or stack traces.
- Claiming Gate B, closed beta, public beta or production readiness.

## Required Reviews And Tests

Before implementation, create scoped GitHub issues with acceptance criteria and
verification plans. Risky slices involving provider controls, admin actions,
auth/security boundaries, user data, database/state, deployment or dependencies
need Architect review and explicit owner approval where required by
`AGENTS.md` and `docs/QUALITY_GATES.md`.

For code changes, run focused admin tests for touched surfaces. Broad admin,
provider, bot/backend contract or shared behavior changes should also run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m compileall src
```

Release-adjacent changes should additionally use `scripts/predeploy_check.sh`
where applicable. CI status remains `Unknown` unless a visible PR/checks page
is inspected.

## Open Items

- Final issue numbers: TBD.
- Exact UI labels for `Translations` versus `Translation Runs`: TBD.
- Exact first incident categories beyond translation failures and provider/key
  failures: TBD.
- Whether Gate B Alerts/Backups visibility is eventually satisfied by admin UI,
  owner report, or both: TBD until an implementation issue records evidence.
