# FolioLoom Admin Console Design

## Goal

Build the first owner-facing admin console for FolioLoom as a service-level
operations console, not as a Telegram-bot settings page.

The console must let the owner configure provider keys, operational settings,
and urgent job controls from a browser. It must also prepare the product for a
future public website, where Telegram becomes one customer channel among
several instead of the center of the architecture.

The first version optimizes for a practical owner MVP:

- secure browser access through a temporary owner password bootstrap;
- masked management of API keys and integration credentials;
- service-level settings for translation, scheduling, safety, and limits;
- operations visibility for translation jobs, workers, failures, retries, and
  cancellations;
- security event review and auditability;
- future compatibility with web accounts, mobile admin usage, and additional
  customer channels.

## Current State

As of 2026-05-09, the `codex/dev` branch has moved from an admin-console
concept to a deploy-ready owner-console MVP. The console is still bootstrap
owner auth, not a full multi-admin product, but it already controls practical
runtime configuration and exposes service operations from the browser.

The current implemented state includes:

- FastAPI admin console mounted under `/admin`;
- bootstrap owner login, signed HTTP-only session cookie, CSRF protection for
  mutating form routes, no-store admin pages, and role-shaped owner session
  model;
- service-first navigation: Overview, Integrations, AI Providers, Billing,
  Costs, Quality, Live, Logs, Activity, Users, Settings, Operations, Security,
  and Audit;
- environment badge in the admin shell;
- Overview action center for owner-visible issues such as missing required
  integrations, failed translations, high usage/cost signals, disk pressure,
  DeepSeek key problems, runtime status problems, and secret safety warnings;
- multi-instance integration connections, including Telegram stable/dev style
  connection rows and reserved shells for future channels/surfaces;
- AI Providers page with DeepSeek key-pool rows, add/update/enable/disable/remove
  flows, masked fingerprints, validation status, health summaries, runtime
  status, and manual reload requests;
- encrypted SQLite-backed admin secret store behind a `SecretStore` boundary,
  using `ADMIN_SECRET_MASTER_KEY` as the deployment-held master key;
- runtime DeepSeek key loading from admin-managed encrypted secrets, with env
  fallback for bootstrap and a reloadable translator that can switch from env
  fallback to admin keys without bot restart;
- provider runtime status and reload request tables in the shared admin DB;
- Live monitor page/API for translation and local server metrics, with reserved
  shape for future VPS/provider metrics;
- Operations overview wired to persistent jobs/workers where available;
- Costs and Quality read models from safe translation run metadata;
- Users, Activity, Security, and Audit pages backed by the admin activity/audit
  stores;
- Translation Logs list with filters, JSON API, downloadable run archive, and a
  per-run Details page;
- per-translation Details page at `/admin/logs/{run_id}` showing safe inputs,
  totals, translation stack, profile/adapter/model metadata, security totals,
  fragment progress metadata, events, result/error state, and archive download;
- deploy scripts and runbooks for OVH/Ubuntu/Docker deployment;
- `scripts/predeploy_check.sh` for local predeploy validation;
- `scripts/server_smoke_check.sh` for server smoke checks, including a strict
  post-bootstrap mode that proves the bot can see admin-managed provider keys;
- backup/restore scripts and runbooks that include `admin.sqlite3`,
  `ADMIN_SECRET_MASTER_KEY` handling, artifact checksums, and SQLite integrity
  verification for the admin DB inside runtime archives.

The console now has these practical owner workflows:

- add several DeepSeek API keys in the browser;
- change key labels, weights, and parallel capacity;
- disable a key without losing its encrypted secret;
- remove a key and disable its secret;
- request provider runtime reload from the browser;
- check whether the bot runtime has reported admin/env provider source and
  active channels;
- inspect translation runs and drill into a specific run's safe execution
  details;
- run predeploy checks before touching the VPS;
- run server smoke checks after deploy and after adding provider keys.

The project still also has these non-admin service pieces that make the console
valuable:

- FastAPI application scaffold with `/health`;
- Telegram runtime using env-based bootstrap settings;
- DeepSeek client and multi-key `DeepSeekKeyPoolTranslator`;
- persistent translation jobs and work units;
- SQLite local job store and PostgreSQL scheduler design work;
- scheduler settings in `Settings`;
- run logs and security telemetry modules;
- order, pricing, billing, user, document, and file-storage domain modules;
- dev/stable environment separation documented in README.

The configuration boundary is no longer only environment variables. Environment
variables remain the bootstrap layer for deployment-held secrets and safe
defaults, while the admin database now holds encrypted provider/integration
secrets, audit/activity state, runtime reload requests, runtime provider
status, and translation details read models.

Remaining gaps before a full production admin product:

- role-aware access control;
- named admin accounts and login lifecycle;
- public HTTPS/admin access policy beyond the current SSH-tunnel-first model;
- rate limiting/lockout for failed admin login;
- managed secret-store adapter for cloud/Vault/Doppler/1Password style
  deployments;
- browser-managed service settings beyond provider/integration secrets;
- complete job retry/cancel workflows for every scheduler state;
- payment provider integration and finance dashboard;
- mobile-first admin console polish;
- future channel-independent customer and order management.

## Product Direction

FolioLoom should be designed as a service with many external integrations and
multiple customer channels:

- Telegram is the first active customer channel.
- A public website should later become another customer channel.
- A partner API or other messaging channel may be added later.
- Other external systems should be attachable through integration adapters
  without changing the service core.

The admin console manages the service core:

- integrations;
- customer channels;
- translation engine settings;
- documents;
- orders;
- billing and finance;
- customer identities;
- jobs and workers;
- security;
- audit history.

Telegram-specific settings stay under an integration or channel page. Core
objects must not be named or modeled as if they only belong to Telegram.

Prefer these names:

- `Service Settings`, not `Bot Settings`;
- `Customer Identity`, not only `Telegram User`;
- `Translation Job`, not `Bot Job`;
- `Document`, not `Telegram File`;
- `Channel`, not only `Bot`;
- `Integration`, not only `API Key`.

This naming rule is part of the design because it prevents a rewrite when the
web product arrives.

Integrations are the places where FolioLoom connects outward as a service or
becomes available inside another customer-facing surface. Customer-facing
messengers must be modeled as channel integrations. The same admin area should
also be ready for website widgets, partner APIs, webhooks, automation tools,
social platforms, CRM, email, auth, observability, and any other external system
that FolioLoom connects to as part of delivery or operations.

AI/model providers and payment providers should not be buried inside the general
Integrations page. They need first-class admin areas because they have their own
operational models:

- AI Providers manages model vendors, key pools, model capabilities, routing,
  fallback, cost controls, and provider health.
- Billing manages payment intermediaries, checkout, subscriptions,
  transactions, revenue, refunds, disputes, payouts, fees, tax settings, and
  billing webhooks.

Telegram is the first channel integration. WhatsApp, Instagram, Discord, and
other bot-capable messaging platforms can become additional channel
integrations later. Each integration can have its own tokens, webhook settings,
app IDs, verification secrets, scopes, delivery limits, and status checks, while
still sending work into the same FolioLoom service core when it is a customer
channel.

## MVP Decision

Use a layered admin console, implemented as FastAPI admin endpoints plus a
browser UI.

The first release should follow option C from the brainstorming session:
an operations console that includes configuration, integration keys, job
visibility, and security/audit surfaces.

It should be built in layers:

1. Central backend skeleton: admin auth dependency, RBAC model, settings store,
   secret store boundary, audit log, and route contracts.
2. Feature slices: integrations, service settings, operations, security/audit,
   then UI pages.
3. Mobile-ready layout work later, using the same backend routes and action
   model.

This keeps architectural decisions centralized while allowing later
implementation work to be split across independent agents.

## In Scope For MVP

### Overview

The overview page shows service health at a glance:

- environment selector or indicator for dev/stable/production;
- API health;
- scheduler/worker health;
- active job count;
- queued job count;
- failed or interrupted job count;
- DeepSeek channel state summary;
- recent security warnings;
- recent configuration changes.

The overview must avoid exposing secrets, document text, or private customer
content.

### Integrations

The integrations page manages external service connections and user-facing
surfaces, not model-provider or billing-provider configuration.

The long-term admin model should be an integration registry, not a fixed list of
API-key fields. Each integration belongs to a category:

- `channel`: customer-facing entry points such as Telegram, website, WhatsApp,
  Instagram, Discord, partner API, or future messengers;
- `storage`: object storage, backup, and file delivery providers;
- `notification`: email, SMS, push, Telegram owner alerts, or incident routing;
- `auth`: future login, identity, SSO, or passkey providers;
- `analytics`: product analytics, revenue analytics, attribution, or BI tools;
- `crm`: customer support, CRM, helpdesk, or sales tools;
- `observability`: logs, metrics, traces, error reporting, uptime checks;
- `automation`: no-code/low-code automation, webhooks, or internal workflows;
- `social_or_marketing`: social platforms, publishing, campaigns, and lead
  capture surfaces.

MVP only implements concrete controls for channel/surface-style integrations
such as Telegram and reserved shells for WhatsApp, Instagram, Discord, website
widget, and webhooks. Other categories should appear as reserved architecture,
not as fake working UI.

MVP integration controls:

- Telegram connection rows, including separate stable/dev bot entries;
- per-connection bot token or provider credential fields;
- per-connection status and provider identity;
- reserved grouping for future integration categories, with detailed controls
  deferred.

Each integration must be multi-instance by design. The page should behave like a
folder: the integration row can be opened, and inside it the owner can see,
add, disable, and later validate individual connections. A connection is one
real configured attachment to an external system. For Telegram this can be a
stable bot and a dev bot. For Discord it can be multiple bots or servers. For
WhatsApp or Instagram it can be multiple business accounts or apps. For
webhooks it can be multiple outbound endpoints. This rule applies to every
integration category, not only messengers.

Connection-level data:

- connection label, such as `stable`, `dev`, `main`, or a customer/account name;
- provider-specific credential references;
- enabled/disabled state;
- masked secret metadata and fingerprint;
- future validation status, last successful check, and last failure summary;
- future routing/environment metadata when the same integration can serve
  different deployments or customer segments.

Secret behavior:

- stored secrets are never shown in full after saving;
- each secret has a stable label and masked fingerprint;
- replacing a secret requires explicit confirmation;
- testing a secret validates connectivity without logging the key;
- audit events record who changed a secret, when, and which secret label changed,
  but never record the secret value.

For future integrations, the admin view should follow the same pattern:

- show integration name, category, provider, environment, and enabled state;
- show safe provider identity and status metadata;
- manage tokens, app secrets, webhook secrets, and verification tokens as
  masked secrets;
- validate connection, webhook readiness, or account status without logging
  credentials;
- keep provider-specific setup details isolated behind an integration adapter.

### AI Providers

The AI Providers page manages model and translation providers separately from
general Integrations. DeepSeek is the first active provider.

MVP AI provider controls:

- DeepSeek multi-key pool;
- per-key label;
- per-key enabled/disabled state;
- per-key weight;
- per-key max parallel requests;
- masked key fingerprint and version;
- DeepSeek base URL;
- DeepSeek model used by the service;
- reserved grouping for future model providers.

For DeepSeek key pools, the admin view should show channel labels, capacity,
weight, cooldown state, recent failures, and last validation status without
showing API keys.

Future AI provider requirement:

- The admin console must eventually allow adding new AI/model providers from
  the UI, not only selecting from built-in providers.
- A custom provider record should capture provider name, API base URL,
  authentication scheme, supported models, default model, timeout/retry policy,
  key-pool settings, pricing/cost metadata when available, and capability tags
  such as translation, OCR, summarization, embeddings, or quality review.
- Custom providers must use the same encrypted secret storage, masking, audit
  trail, validation, enabled/disabled state, and per-key pool controls as
  built-in providers.
- Runtime provider selection should remain adapter-based, so adding a provider
  in the admin panel does not require hardcoding provider-specific behavior into
  unrelated service code.

### Service Settings

The service settings page manages runtime behavior that is not tied to one
customer channel.

MVP settings:

- `service_name`;
- active environment label;
- `max_upload_mb`;
- `deepseek_model`;
- object storage root or storage profile label;
- persistent jobs database path or database profile label;
- user settings database path or database profile label;
- translation run log root or log profile label;
- translation max parallel units;
- scheduler backend;
- scheduler lease seconds;
- scheduler poll seconds;
- scheduler retry base delay seconds;
- scheduler retry max delay seconds;
- security max events per run;
- security max unsafe model outputs per run;
- security max repair failures per run;
- user cooldown thresholds, windows, and durations.

MVP can store some settings as reload-required settings if live reload would be
risky. The UI must make this explicit:

- "applies immediately";
- "applies after service restart";
- "bootstrap-only, change in env/deployment".

This avoids pretending every setting can be changed safely while workers are
active.

### Live Monitor

The Live Monitor page is a compact, always-open browser view for the current
state of the service. It should be suitable for a separate browser window,
tablet, or future PWA/native wrapper.

MVP live monitor:

- show active translation count;
- show queued translation count;
- show failed translations for the current day;
- show total tokens for the current day;
- show total tokens for the last hour;
- show recent translation runs with safe metadata only;
- poll a JSON snapshot endpoint every few seconds;
- show local server health: CPU, memory, disk, and uptime;
- reserve future worker/event loop health and VPS provider status cards.

Local server health should be collected through a read-only collector. It may
use optional host libraries such as `psutil` when available, but it must degrade
to partial metrics rather than breaking the live endpoint. Each metric should be
nullable and independently safe to fail.

Future VPS provider metrics should be implemented as read-only provider
adapters. Provider API tokens must live in encrypted secret storage, provider
responses must be normalized before reaching the UI, and failed provider reads
must never break local service metrics.

The first implementation may use polling instead of WebSocket or SSE because it
is simpler and reliable enough for an owner console. The API shape should still
allow a later event stream without changing the visible page model.

Live monitor privacy rules are the same as Logs: never show source text,
translated text, prompts, provider credentials, or raw provider responses.

### Operations

The operations page controls translation work.

MVP operations:

- list translation jobs by status;
- inspect job summary and safe metadata;
- inspect work-unit progress and retry state;
- show last safe error message;
- retry failed or interrupted work when the scheduler contract allows it;
- request cancellation for running or queued jobs;
- show worker/scheduler heartbeat state;
- show provider-channel cooldown and failure summaries.

Operations actions must be explicit and auditable. Destructive or risky actions
require confirmation. The UI should distinguish safe actions from actions that
may affect a paying customer or an in-progress translation.

### Translation Logs

The logs page lets the owner review translation runs without opening server log
files or SSH access.

Implemented MVP logs:

- list translation runs from the privacy-safe translation run snapshots;
- filter by status;
- filter by started date range;
- sort newest runs first;
- show job ID, order ID when available, safe user reference, file name,
  document kind, language direction, status, start/finish timestamps, fragment
  count, token totals, elapsed seconds, result file name, and safe error
  summary;
- provide a JSON API with the same safe read model;
- provide a `Details` action for each run;
- provide a per-run detail page at `/admin/logs/{run_id}`;
- show safe input metadata, model, prompt version, adapter version,
  translation policy, language/profile signatures, run totals, security totals,
  fragment status/timing/token/retry/block metadata, and lifecycle events;
- provide a per-run downloadable archive containing the underlying run files.

The logs page must never show source text, translated text, prompts, provider
credentials, or raw provider responses. Fragment-level details can be added
only through privacy-safe hashes and metadata unless a future explicit
forensic-text retention mode is designed and enabled. The current implementation
does not expose raw source or translated document text in the admin UI.

### Security And Audit

The MVP uses a temporary owner-password bootstrap, then models future admin
accounts and roles so login can evolve later.

MVP access:

- a single owner password or owner secret from environment;
- HTTP-only session cookie or equivalent browser session mechanism;
- CSRF protection for mutating browser form actions;
- strict no-cache behavior for pages containing operational data;
- rate limiting or cooldown for failed login attempts when feasible.

MVP roles:

- `owner`;
- `operator`;
- `viewer`.

Only `owner` is active in the first bootstrap login, but route permissions must
be expressed through the role model so later multi-admin login does not require
rewriting the admin API.

Permission groups:

- view overview;
- view integrations;
- manage integrations;
- view service settings;
- manage service settings;
- view operations;
- retry jobs;
- cancel jobs;
- view security events;
- view audit log;
- manage admins.

Audit log requirements:

- record successful and failed sensitive actions;
- record setting changes with old/new values for non-secret settings;
- record secret changes by secret label and fingerprint only;
- record operation actions such as retry and cancel;
- include actor, role, timestamp, action, target type, target ID, outcome, and
  redacted reason/error;
- never store secret values or document text.

Security event view:

- summarize security telemetry events;
- show severity, category, run/job reference, customer reference if available,
  and safe redacted details;
- allow marking reviewed later, but MVP may keep review state read-only if the
  underlying telemetry model is not ready.

## Model Now, UI Later

The MVP should introduce or reserve service-level concepts even if the first UI
only shows a subset.

### Integrations And Channels

Represent Telegram as a `channel`, not as the whole product.

Channel fields may include:

- channel ID;
- channel type such as `telegram`, `whatsapp`, `instagram`, `discord`,
  `website`, or `api`;
- display name;
- enabled state;
- environment;
- integration references;
- channel-specific limits.

MVP only needs Telegram channel display and integration wiring. The model should
allow website, API, WhatsApp, Instagram, Discord, and other bot-capable
messaging channels later.

Channel integrations should share a common shape where possible:

- channel ID;
- provider type;
- environment;
- enabled state;
- display name;
- secret references;
- webhook or callback configuration;
- health check status;
- last inbound event timestamp;
- last delivery error;
- channel-specific capability flags.

The admin store should separate an integration definition from its configured
connections. The definition says what Telegram, Discord, Webhooks, or any other
adapter needs. The connection row says which concrete account, bot, endpoint,
workspace, app, or environment is attached right now. This keeps the UI flexible
enough to support two Telegram bots today and many accounts or endpoints per
provider later.

Channels are a subset of integrations. Provider-specific requirements should
live in adapter metadata rather than leaking into the service core. For example,
a Discord bot, WhatsApp business integration, Instagram messaging integration,
and Telegram bot may all have different setup fields, but they should all
produce service-level customer events, documents, orders, and translation jobs.

Non-channel integrations also use adapter metadata, but they do not create
customer conversations directly. For example, a payment provider handles
checkout and refunds, an analytics provider receives events, a CRM receives
customer lifecycle updates, and an observability provider receives logs or
alerts.

### Customer Identity

Use an internal customer identity concept above Telegram user IDs.

Today:

- one customer identity can map to a Telegram user ID.

Later:

- the same identity can map to a web account;
- multiple identities can be merged or linked only through explicit future
  account-management flows.

The admin MVP does not need full customer management, but operations and audit
events should use service-level customer references where possible.

### Orders And Documents

Orders and documents must remain service-level objects.

Telegram may be the upload source, but documents, estimates, payment state,
translation jobs, and final files should not depend on Telegram naming.

### Billing And Finance

Payment work has not started yet and is not required for the admin-console MVP,
but FolioLoom will need it. The admin console must reserve a service-level
Billing area for payment intermediaries, transactions, revenue, costs, and
profit views.

Payment provider integrations are part of the integration registry before the
finance dashboard exists. A provider such as Stripe sits between FolioLoom and
the user: it can own checkout sessions, payment intents, invoices,
subscriptions, refunds, disputes, payouts, fees, tax settings, customer payment
methods, and webhook events. Other payment providers or local acquirers may
offer different shapes, so FolioLoom should normalize their events into
service-level orders, payments, refunds, ledger entries, and audit records.

Future payment integration views should include:

- provider connection status;
- test/live environment;
- public provider identity, account ID, or merchant label when safe to show;
- masked API keys or webhook signing secrets;
- webhook health and last event timestamp;
- supported checkout mode;
- supported currencies and regions;
- payment method readiness;
- payout or settlement status where available;
- dispute and chargeback visibility where available.

Future billing views should include:

- payment transactions;
- order payment state;
- refunds;
- customer balances or credits if the product keeps them;
- invoices or receipts;
- gross revenue;
- payment provider fees;
- translation provider cost estimates;
- refunds and chargebacks;
- net revenue;
- profit or contribution-margin estimates;
- revenue by channel, document type, language pair, and period.

Finance data must distinguish confirmed accounting facts from estimates. For
example, provider token-cost estimates, payment fees, and profit calculations
may use different timing and currency assumptions. The UI should label these
clearly instead of presenting all numbers as final accounting truth.

MVP does not implement the billing dashboard, but the admin architecture should
avoid choices that would make it hard to add transactions and finance views
later. Orders, jobs, pricing snapshots, ledger entries, provider usage, and
payment-provider events should have stable references that a future finance
view can join.

For a future Stripe implementation, the design should prefer modern hosted or
embedded checkout surfaces over collecting raw card data directly. Provider
webhook handling must be idempotent, auditable, and separate from admin-only
views.

### Admin Accounts

The first login is bootstrap-only, but the data model and permission checks
should assume future admin accounts.

Future account sources may include:

- email/password plus 2FA;
- OIDC provider;
- Telegram identity for owner convenience;
- passkeys or WebAuthn for high-security owner access.

## Later Scope

The following are intentionally out of MVP:

- full email/password login and account recovery;
- multi-admin invitation flow;
- 2FA/passkeys;
- full implementation for WhatsApp, Instagram, Discord, or other future
  external integrations;
- payment provider integration and checkout;
- public customer website;
- customer upload page;
- customer account library;
- checkout UI and invoices;
- billing transaction dashboard;
- profit and margin reporting;
- advanced analytics dashboards;
- revenue and cohort reports;
- mobile-first admin UI implementation;
- notification routing to email, Telegram, or push;
- full approval workflows for dangerous changes.

## Mobile Admin Future Requirement

The owner wants to manage FolioLoom from anywhere, without always having access
to a laptop. The MVP does not need a polished mobile interface, but the design
must preserve a path to one.

Mobile-ready principles:

- critical actions fit into short task cards;
- overview metrics degrade into stacked cards;
- tables have detail screens instead of relying on horizontal scrolling;
- retry/cancel/change-secret actions use confirmation sheets;
- secret input flows are step-by-step and easy to abandon safely;
- the smallest useful mobile console focuses on alerts, jobs, key health,
  cancellation, retry, and emergency disable actions;
- backend routes do not assume a desktop-only UI.

The future mobile console can be a responsive web UI first. A native app is not
required unless browser limitations become painful.

## Architecture

### Backend Layers

The admin console should have these backend layers:

1. Admin auth/session layer.
2. RBAC and permission checks.
3. Admin route layer under a clear prefix such as `/admin`.
4. Application services for settings, secrets, audit, operations, and security.
5. Repositories backed by SQLite for local/dev and PostgreSQL-compatible shapes
   for production.
6. Existing FolioLoom domain services for jobs, scheduler, translation,
   security telemetry, billing, and users.

FastAPI can host both machine-readable admin APIs and server-rendered pages.
The first UI can be server-rendered or lightweight static pages calling JSON
endpoints. The route contracts should remain clean enough to support a richer
frontend later.

### Storage

Use a persistent admin store for non-secret settings, admin metadata, audit
events, and secret metadata.

Secret values need a dedicated boundary. The architecture decision is to use a
`SecretStore` abstraction long term, with an encrypted database-backed
implementation for the admin MVP.

The `SecretStore` interface should hide where secret values live. Admin routes
and UI code should only ask the secret store to write, read for runtime use,
describe, rotate, disable, or validate a secret. This lets local/dev use an
encrypted database while a later production deployment can move to AWS Secrets
Manager, GCP Secret Manager, Azure Key Vault, Vault, Doppler, 1Password, or
another managed secret system without rewriting admin pages.

MVP secret storage:

- store secret values encrypted in the admin database;
- keep the master encryption key only in environment or deployment secrets;
- fail closed for secret writes and reads if the master key is missing;
- use authenticated encryption from a maintained library, with a fresh nonce or
  equivalent per secret version;
- store key ID, algorithm, ciphertext, nonce or algorithm metadata, secret
  version, created time, updated time, actor, disabled state, and safe labels;
- store fingerprints and masked display values separately from ciphertext;
- never store raw secret values in audit events, settings rows, logs, or read
  API responses;
- support multiple secret versions so rotation can be added without changing
  the public admin contract;
- keep bootstrap-only secrets such as the first owner password and the master
  encryption key outside the database.

Secret metadata should be readable by the admin UI. Secret values should only be
available to runtime services through explicit secret references and permission
checks. A normal admin read endpoint should return metadata, validation status,
masked display, and fingerprint only.

Production can keep using the encrypted database implementation at first if the
deployment threat model accepts it. The interface still needs to be shaped so a
managed secret store can replace it later.

### Configuration Precedence

Configuration should follow explicit precedence:

1. Hardcoded safe defaults.
2. Environment bootstrap settings.
3. Admin-managed persisted settings.
4. Runtime overrides only where the setting is marked live-reloadable.

Bootstrap-only secrets include the first owner password and any encryption key
needed to read persisted secrets.

Settings must carry metadata:

- key;
- display label;
- value type;
- validation rules;
- scope;
- sensitivity;
- apply mode;
- default source;
- last changed by;
- last changed at.

### Apply Modes

Settings need apply modes because not all settings can safely change while the
service is running.

Recommended modes:

- `live`: can be read dynamically or applied without restart;
- `restart_required`: saved now, active after restart;
- `bootstrap_only`: visible as configured state, but changed outside the admin
  console through deployment/env management.

The UI must show apply mode clearly before saving.

### API Route Groups

MVP route groups:

- `/admin/login`;
- `/admin/logout`;
- `/admin/overview`;
- `/admin/integrations`;
- `/admin/settings`;
- `/admin/operations/jobs`;
- `/admin/operations/workers`;
- `/admin/security/events`;
- `/admin/audit`;

JSON API groups can mirror these under `/admin/api/...` if the UI is not fully
server-rendered.

## UI Design

The desktop MVP uses an operations-console layout:

- left navigation;
- top environment indicator and owner session menu;
- main content area with focused pages;
- compact cards for health metrics;
- tables for jobs and audit events;
- forms for integrations and settings;
- confirmation dialogs for risky actions.

Recommended navigation:

- Overview;
- Integrations;
- Service Settings;
- Channels;
- Customers;
- Orders;
- Documents;
- Billing;
- Operations;
- Security;
- Audit Log.

The MVP can hide or stub sections that are modeled but not fully implemented.
If a section is visible but not implemented, it should explain status in admin
language such as "modeled for future website channel" rather than marketing
copy.

Visual direction:

- quiet, utilitarian, service-operator feel;
- high readability and dense information;
- restrained color palette with status colors used meaningfully;
- no marketing hero layout;
- no decorative cards inside cards;
- no in-app instructional prose where a label, tooltip, or confirmation copy is
  enough.

## Data Flow

### Secret Replacement

1. Owner opens an integration page.
2. Existing secret appears as label plus masked fingerprint.
3. Owner enters replacement value.
4. Backend validates format locally.
5. Optional test call validates provider connectivity.
6. Backend stores secret through the secret store boundary.
7. Backend stores metadata and audit event.
8. UI shows new masked fingerprint and validation result.

The response never includes the raw secret.

### Setting Change

1. Owner changes a non-secret setting.
2. Backend validates type, range, and allowed values.
3. Backend checks permission.
4. Backend stores setting version.
5. Backend records audit event with redacted old/new values.
6. If setting is live, the service reads the new value through the settings
   service.
7. If restart is required, the UI shows pending restart state.

### Job Retry Or Cancel

1. Owner views a job in operations.
2. UI shows allowed actions based on job state and permission.
3. Owner confirms retry or cancel.
4. Backend checks scheduler/job contract and permission.
5. Backend records the operation request and audit event.
6. Scheduler or job store changes state.
7. UI updates from the latest job snapshot.

## Error Handling

Admin errors must be explicit and safe:

- validation errors explain what field is invalid;
- secret test failures redact provider responses;
- permission failures return a generic denial and record an audit event;
- unavailable scheduler or store errors surface as health warnings;
- job actions that are no longer valid return a state conflict, not a silent
  no-op;
- all unexpected errors avoid secret values, document text, and source excerpts.

## Security Requirements

The admin console is a high-risk surface because it can change credentials,
pricing-relevant settings, and job operations.

Minimum MVP requirements:

- owner bootstrap secret is required for access;
- mutating routes require a session and permission check;
- CSRF protection for browser form mutations;
- secrets are never returned after save;
- logs and audit events redact secrets;
- admin pages should not be cached by browsers or proxies;
- every sensitive change writes an audit event;
- dangerous operations require confirmation;
- route tests cover unauthenticated and unauthorized access;
- no customer document text appears in overview, audit, or error surfaces.

Threats to account for:

- stolen owner password;
- accidental secret leak through UI, logs, or audit rows;
- CSRF causing a secret replacement or job cancellation;
- privilege confusion when future roles are added;
- operator retry/cancel actions affecting customer work;
- provider error messages echoing sensitive data;
- public exposure of admin routes when deployed.

## Testing Strategy

Unit tests:

- settings validation and apply modes;
- secret masking and fingerprinting;
- secret store read/write boundary;
- encrypted secret storage does not persist plaintext;
- missing master key fails closed for secret value operations;
- secret metadata read APIs return no raw secret value;
- secret versioning supports replacement without losing audit history;
- audit event creation and redaction;
- RBAC permission decisions;
- job action eligibility.

API tests:

- unauthenticated admin routes are rejected;
- owner session can view allowed pages;
- mutating routes require CSRF or equivalent protection;
- secret read endpoints never return raw values;
- setting updates validate type/range;
- retry and cancel endpoints reject invalid job states;
- audit events are written for sensitive actions.

UI or integration tests:

- login/logout flow;
- integrations page masks secrets;
- settings page shows apply mode;
- operations page shows job actions by status;
- confirmation flow for retry/cancel;
- no obvious responsive breakage at mobile widths once mobile layout work starts.

Security regression tests:

- secret values do not appear in API responses, audit payloads, or logs tested
  in-process;
- provider errors are redacted before display;
- role checks protect manage operations separately from view operations.

## Acceptance Criteria

- The design treats Telegram as a channel, not as the whole product.
- The design treats Integrations as a broad registry for external systems, not
  only as messenger bots or API-key fields.
- Admin navigation and naming are service-first and future website compatible.
- MVP scope includes integrations, service settings, operations, security, and
  audit.
- API keys and tokens can be replaced and validated without being displayed
  after save.
- DeepSeek key pool state can be surfaced without exposing key values.
- Owner bootstrap auth is sufficient for MVP but route permissions use a role
  model.
- Sensitive settings and operations create audit events.
- Job retry and cancel are available only when allowed by job state.
- The UI can distinguish live, restart-required, and bootstrap-only settings.
- The design explicitly preserves a path to mobile admin usage.
- The design reserves a Billing area for future transaction, revenue, cost, and
  profit views without requiring payment implementation in the admin MVP.
- The design uses a `SecretStore` abstraction, with encrypted database-backed
  secret storage as the MVP implementation and a path to managed secret stores
  later.
- The design does not require implementing the public customer website in the
  admin-console MVP.

## Implementation Planning Notes

The implementation plan should be written after this design is reviewed.

Recommended execution style:

1. Build the backend skeleton centrally: auth, RBAC, stores, audit, settings,
   secret boundary, and route contracts.
2. Split feature implementation into independent slices after the skeleton is
   stable: integrations, operations, UI, and security tests.
3. Keep mobile UI as a future design task, but avoid backend shortcuts that make
   mobile admin actions hard later.
