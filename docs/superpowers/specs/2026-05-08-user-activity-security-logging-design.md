# User Activity and Security Logging Design

## Goal

Build a browser-admin logging system that lets the owner investigate user
behavior and security events across FolioLoom.

The first version is for support and safety, not broad product analytics. It
must answer these questions quickly:

- who is this user;
- what buttons, commands, and settings did they use;
- what documents and translations did they start;
- where did a translation fail, cancel, or complete;
- which suspicious inputs, unsafe outputs, cooldowns, or admin views touched
  this user or job.

## Decision

Use a SQLite event store now and keep the schema compatible with a future
PostgreSQL backend.

This is better than JSONL-only logs because the browser admin panel needs
filtering by user, Telegram id, event type, outcome, date, job id, and security
state. It is intentionally simpler than a warehouse or analytics stack because
the near-term goal is investigation and operational safety.

## Storage

Use the existing admin database path for local/dev storage:

```text
ADMIN_DB_PATH=var/admin.sqlite3
```

Add two tables:

```sql
CREATE TABLE IF NOT EXISTS user_activity_events (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  channel TEXT,
  channel_user_id TEXT,
  surface TEXT NOT NULL,
  event_type TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  outcome TEXT NOT NULL,
  job_id TEXT,
  order_id TEXT,
  translation_run_dir TEXT,
  metadata_json TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS user_profiles (
  user_id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  channel_user_id TEXT NOT NULL,
  interface_language TEXT,
  progress_preview_enabled INTEGER,
  default_source_language TEXT,
  last_target_language TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  security_state TEXT NOT NULL,
  metadata_json TEXT NOT NULL,
  UNIQUE(channel, channel_user_id)
);
```

Useful indexes:

- `user_activity_events(created_at)`;
- `user_activity_events(actor_id, created_at)`;
- `user_activity_events(channel, channel_user_id, created_at)`;
- `user_activity_events(event_type, created_at)`;
- `user_activity_events(outcome, created_at)`;
- `user_activity_events(job_id)`;
- `user_activity_events(surface, created_at)`;
- `user_profiles(last_seen_at)`;
- `user_profiles(security_state)`.

## Event Model

Every event is append-only. Events explain what happened. Profiles explain the
current known state of the user.

Core fields:

- `actor_type`: `user`, `admin`, `system`, or `worker`;
- `actor_id`: internal actor id such as `telegram:340499970`,
  `admin:owner`, or `worker:local`;
- `channel`: external channel such as `telegram`, `admin`, or `system`;
- `channel_user_id`: provider-specific id, for example Telegram numeric id;
- `surface`: where it happened: `bot`, `admin`, `worker`, or `security`;
- `event_type`: stable dotted event name;
- `action`: short verb such as `clicked`, `uploaded`, `confirmed`, `failed`;
- `target_type`: optional object class such as `button`, `document`,
  `translation_job`, `setting`, or `admin_page`;
- `target_id`: optional stable object id;
- `outcome`: `success`, `failure`, `blocked`, or `ignored`;
- `metadata_json`: safe structured details.

Required first event taxonomy:

```text
bot.started
bot.command.received
bot.button.clicked
bot.inline_button.clicked

user.seen
user.interface_language.changed
user.setting.changed

document.uploaded
document.rejected
document.estimated

translation.target_language.selected
translation.confirmed
translation.started
translation.progressed
translation.completed
translation.cancel_requested
translation.cancelled
translation.failed

security.suspicious_input_detected
security.unsafe_model_output_detected
security.cooldown_applied
security.user_blocked

admin.login
admin.logout
admin.user.viewed
admin.activity.viewed
admin.translation_log.viewed
admin.setting.changed
admin.secret.changed
```

## User Profiles

`user_profiles` stores the latest user state:

- `user_id`, initially `telegram:<telegram_id>`;
- `channel`, initially `telegram`;
- `channel_user_id`;
- interface language;
- progress preview setting;
- default source language;
- last selected target language;
- first seen and last seen timestamps;
- security state: `normal`, `watched`, `limited`, or `blocked`;
- safe metadata for future channel identity details.

Profiles are updated when activity is recorded. Event writes should call an
upsert helper so a user appearing in the bot becomes visible in `/admin/users`
without a separate import step.

## Privacy And Safety

`user_activity_events` must not store full document text or full user message
text by default.

Allowed metadata:

- button label or callback id;
- command name;
- file name, size, format, and object key;
- language codes;
- setting key and old/new safe value;
- job id, order id, translation run directory;
- token totals and result file name;
- message kind, text length, and text hash;
- short safe preview only in explicit dev/debug mode.

Full source and translated text stay in `translation-runs/fragments/*.json`.
Activity events link to those run logs through `translation_run_dir`.

Sensitive metadata must be redacted before storage. Keys containing `secret`,
`token`, `password`, or `key` are stored as `[redacted]`. Long text values are
truncated.

## Translation Linkage

Every translation should produce an activity chain:

```text
document.uploaded
translation.target_language.selected
document.estimated
translation.confirmed
translation.started
translation.completed | translation.failed | translation.cancelled
```

The final translation event should include:

```json
{
  "file_name": "book.txt",
  "document_kind": "txt",
  "source_language": "auto",
  "target_language": "ru",
  "fragment_count": 12,
  "total_tokens": 1036,
  "result_file_name": "book.ru.txt"
}
```

And it must set:

- `actor_id`;
- `channel`;
- `channel_user_id`;
- `job_id`;
- `translation_run_dir` when available.

This gives the admin path:

```text
User -> Timeline -> Translation Event -> Run Log -> Fragment Detail
```

## Admin Pages

Add browser pages:

```text
/admin/users
/admin/users/{user_id}
/admin/activity
/admin/security/events
```

`/admin/users` shows:

- user id;
- channel;
- channel user id;
- interface language;
- last seen;
- translation count;
- failure count;
- security state.

`/admin/users/{user_id}` shows:

- current profile/settings;
- latest document and translation events;
- timeline of recent activity;
- security events for that user;
- links to translation run logs where available.

`/admin/activity` shows a global event stream with filters:

- user id;
- channel user id;
- event type;
- action;
- outcome;
- surface;
- date range;
- job id;
- security only.

`/admin/security/events` shows only security-surface events and users with
`watched`, `limited`, or `blocked` states.

## Instrumentation Points

Telegram runtime should record:

- `/start`, `/menu`, `/help`, `/language`, `/status`, `/cancel`;
- main menu button clicks;
- language button clicks;
- settings toggles;
- inline cancel callbacks;
- upload attempts and upload rejection reasons.

`BotTranslationService` should record:

- pending upload prepared;
- estimate created;
- target language selected;
- translation confirmed;
- translation started;
- translation progress milestones;
- translation completed, failed, or cancelled.

Security modules should record:

- suspicious user input;
- unsafe model output;
- repair failures;
- cooldowns and blocks.

Admin routes should record:

- admin login and logout;
- user detail page viewed;
- activity page viewed;
- translation log viewed;
- settings and secret changes.

## Error Handling

Activity logging must not break the user-facing bot flow. If SQLite logging
fails, the application should log an internal warning and continue the user
action, except for security enforcement decisions where the security action
itself must still be applied.

Admin writes such as `admin.secret.changed` may fail closed if audit logging or
secret storage is unavailable because those are sensitive owner actions.

## First Slice

The first implementation slice should include:

1. `src/translator_service/user_activity.py` with SQLite store, dataclasses,
   filtering, profile upsert, and metadata redaction.
2. Tests for record/list/filter/profile behavior.
3. Translation lifecycle instrumentation in `BotTranslationService`.
4. Basic Telegram runtime instrumentation for commands, buttons, uploads, and
   settings.
5. Admin pages and APIs for users, user detail, activity, and security events.
6. Links from translation activity rows to existing translation run log paths.

## Acceptance Criteria

- After one test translation, `/admin/users` shows the Telegram user.
- `/admin/users/{user_id}` shows the user's settings and event timeline.
- `/admin/activity` shows button, upload, target-language, confirmation, and
  translation completion events.
- `/admin/security/events` shows only security events and watched/limited/blocked
  users.
- Translation completion events include `job_id` and `translation_run_dir` when
  available.
- Activity metadata never stores full document text by default.
- Activity logging failures do not fail ordinary user translation flows.
- Tests cover SQLite persistence, filters, profile upsert, metadata redaction,
  translation lifecycle events, and admin route access.
