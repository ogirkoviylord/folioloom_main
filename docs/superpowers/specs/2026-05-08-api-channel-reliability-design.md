# API Channel Reliability Design

## Goal

Strengthen FolioLoom's provider-side multi-channel foundation before expanding user-facing channels such as Web, partner API, or new messengers. The first implementation target is the DeepSeek API channel layer: multiple API keys must behave like a managed pool with clear capacity rules, temporary-failure handling, runtime diagnostics, and stable configuration.

This design keeps DeepSeek as the only translation provider. The user never chooses a provider or channel. API channels are an internal reliability and throughput mechanism.

## Current State

The dev branch already has a basic `DeepSeekKeyPoolTranslator`.

Implemented behavior:

- `DEEPSEEK_API_KEYS` enables multiple API keys.
- A single key still builds a plain `DeepSeekClient`.
- Multiple keys build a `DeepSeekKeyPoolTranslator`.
- Each channel has a label and `max_parallel_requests`.
- Requests are assigned to channels with available capacity.
- HTTP 429 and HTTP 503 errors cool down the current channel and fail over to another channel.
- `last_usage` remains thread-local so parallel translations do not overwrite each other's token accounting.

The current version is intentionally small. It does not yet expose a state snapshot, counters, last error metadata, weighted selection, per-channel backoff, or enough diagnostics for later admin/status screens.

## Scope

This phase improves the provider API channel layer only.

In scope:

- channel state tracking;
- safer channel selection under capacity, cooldown, and error pressure;
- channel health snapshots for tests, logs, and future admin surfaces;
- better runtime configuration parsing for multiple keys;
- focused unit tests around channel behavior;
- README notes for local multi-key configuration.

Out of scope for this phase:

- adding non-DeepSeek providers;
- user-facing provider selection;
- web app, partner API, WhatsApp, or other user-channel adapters;
- production admin UI;
- replacing SQLite/local storage with PostgreSQL/S3;
- changing payment or order semantics.

## Design

### Channel Model

Each API key is represented as a channel with immutable configuration and mutable runtime state.

Configuration fields:

- `api_key`;
- `label`;
- `max_parallel_requests`;
- `weight`;
- `cooldown_seconds`;
- `max_cooldown_seconds`.

Runtime state fields:

- active request count;
- total started requests;
- total successful requests;
- total temporary failures;
- total permanent failures;
- consecutive temporary failures;
- current cooldown deadline;
- last selected time;
- last successful time;
- last failure time;
- redacted last error message.

The snapshot must never expose API keys or source text.

### Selection

The selector chooses among channels that are not cooling down and have spare capacity. It should prefer channels with lower relative load, then higher weight, then older last-selected time, then stable label order. This keeps behavior deterministic enough for tests while still spreading requests.

If all non-excluded channels are cooling down or full, the caller waits until the next relevant state change. Waiting must remain bounded by condition wakeups and short timeout slices so tests and shutdown-sensitive code do not hang indefinitely.

Within one translation call, a channel that already failed with a temporary error is excluded from further attempts for that same text. Another channel may try the same request.

### Failure Handling

Temporary provider pressure is represented by DeepSeek API errors containing HTTP 429 or HTTP 503. Those errors:

- increment temporary failure counters;
- increase consecutive temporary failure count;
- place the channel in cooldown;
- trigger failover to another channel when available.

Cooldown uses exponential backoff per channel:

```text
cooldown = min(max_cooldown_seconds, cooldown_seconds * 2 ** (consecutive_temporary_failures - 1))
```

A successful request resets consecutive temporary failures for that channel.

Permanent provider errors are not retried on another key by default. They increment permanent failure counters, store a redacted last error, and re-raise. This avoids multiplying bad requests when the prompt, payload, auth setup, or provider response is invalid.

### Diagnostics

`DeepSeekKeyPoolTranslator` exposes a `snapshot()` method returning a list of small frozen dataclass views, one per channel.

The snapshot is for:

- unit tests;
- developer logs;
- future health endpoints;
- future admin screens.

The first implementation does not need a public HTTP endpoint. The shape should still be stable enough that a future status command or admin page can use it without reaching into private fields.

### Runtime Configuration

The bot runtime continues to support:

- `DEEPSEEK_API_KEY` for one key;
- `DEEPSEEK_API_KEYS` as a comma-separated list for multiple keys;
- `DEEPSEEK_MAX_PARALLEL_PER_KEY`;
- `DEEPSEEK_CHANNEL_COOLDOWN_SECONDS`.

This phase adds:

- safe parsing for `DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS`;
- optional `DEEPSEEK_CHANNEL_WEIGHTS` as comma-separated positive integers aligned to `DEEPSEEK_API_KEYS`;
- stable labels `deepseek-1`, `deepseek-2`, and so on;
- deduplication of repeated keys while preserving first occurrence order.

If weights are missing or invalid, the runtime logs a warning and falls back to weight `1`.

### Testing

Unit tests should cover:

- failover and cooldown on HTTP 429/503;
- exponential cooldown growth;
- success resetting consecutive temporary failures;
- permanent errors not failing over to other channels;
- snapshot redaction and counters;
- capacity-aware selection;
- weighted selection preference when channels are otherwise equally available;
- env parsing for deduped keys, weights, max parallel, and cooldown settings;
- thread-local usage under parallel calls.

Existing translator and bot runtime tests should keep passing.

## Future Multi-Channel Bridge

Provider API channels are not the same as user-facing product channels, but they set the pattern for future channel work: adapters should be thin, state should be observable, identifiers should not leak private credentials or user text, and failures should be represented in a way the backend can explain later.

After API channels are reliable, the next multi-channel phase can introduce a channel-independent user interaction boundary for Telegram, Web, partner API, and future messengers. That later phase should reuse the same principles: internal IDs, adapter-local delivery details, durable job state, and diagnostic snapshots.

## Acceptance Criteria

- Multiple DeepSeek keys can be configured without code changes.
- Temporary pressure on one key does not fail a translation while another configured key is available.
- Repeated temporary pressure backs off the affected key without blocking healthy keys.
- Permanent errors are not blindly replayed across all keys.
- Runtime channel state is inspectable without exposing API keys or document text.
- Tests prove selection, backoff, failover, and configuration behavior.
- README documents local multi-key configuration.
