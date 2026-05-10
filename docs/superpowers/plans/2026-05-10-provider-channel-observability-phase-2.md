# Provider Channel Observability Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make DeepSeek provider channels observable and safer to operate by adding latency/error-aware key scoring, richer redacted channel telemetry, and admin/runtime visibility for provider degradation.

**Architecture:** Keep scheduler fairness from Phase 1 unchanged. Phase 2 stays inside the provider/runtime/admin layer: `DeepSeekKeyPoolTranslator` becomes the telemetry source, `SQLiteAIProviderRuntimeStore` persists safe channel snapshots, and admin pages/API render provider degradation without raw document text or API keys. Adaptive global throttling, Postgres provider-channel leases, and cost-aware scheduling remain separate later phases.

**Tech Stack:** Python 3.13, `unittest`, SQLite admin runtime store, FastAPI admin routes/views, existing DeepSeek-compatible provider layer.

**Implementation status (2026-05-10):** Implemented, documented and verified. Individual per-task commit steps are intentionally left open because Phase 2 is being committed as one cohesive changeset.

---

## Scope

This plan implements Phase 2 only:

- richer `DeepSeekChannelSnapshot` fields for safe runtime diagnostics;
- error-kind classification for 429, 503, timeout, malformed response, auth, billing, and unknown provider errors;
- latency/error-aware weighted least-loaded key selection;
- runtime persistence of safe channel telemetry;
- admin AI Providers and Live Monitor visibility for provider degradation;
- tests proving telemetry redaction, key scoring, cooldown/failover, runtime store compatibility, and admin rendering.

This plan does not implement:

- AIMD global capacity ramp;
- provider-wide circuit breaker;
- cost/token-budget scheduling;
- Postgres-backed provider-channel leases;
- automatic disabling of admin keys;
- raw request/response logging.

Those are Phase 3 and Phase 4 concerns.

## File Structure

- Modify `src/translator_service/deepseek_key_pool.py`: add telemetry fields, error classification, latency tracking, and scoring.
- Modify `src/translator_service/bot/runtime.py`: always build a pool for DeepSeek channels and record runtime telemetry snapshots.
- Modify `src/translator_service/admin/provider_runtime.py`: persist richer channel telemetry with backwards-compatible JSON parsing.
- Modify `src/translator_service/admin/provider_health.py`: derive provider degradation from runtime status/channel telemetry.
- Modify `src/translator_service/admin/routes.py`: include runtime channel telemetry in `/admin/api/ai-providers/runtime` and pass runtime into health builder.
- Modify `src/translator_service/admin/views.py`: render channel health/cooldown/counters/latency in AI Providers and Live Monitor.
- Modify `.env.server.example`, `README.md`, `README.project.md`, `docs/deployment/admin-vps-runbook.md`: document Phase 2 observability and safe defaults.
- Test `tests/test_deepseek_key_pool.py`: telemetry, scoring, classification, redaction.
- Test `tests/test_ai_provider_runtime.py`: richer runtime status roundtrip and backwards compatibility.
- Test `tests/test_admin_provider_health.py`: runtime degradation affects health safely.
- Test `tests/test_bot_runtime.py`: pool construction and runtime telemetry recording.
- Test `tests/test_admin_routes.py`: admin page/API render safe telemetry.
- Test `tests/test_admin_live_monitor.py`: live runtime cards expose degradation safely if needed.

## Runtime Vocabulary

Use these stable status strings:

```python
CHANNEL_HEALTH_HEALTHY = "healthy"
CHANNEL_HEALTH_BUSY = "busy"
CHANNEL_HEALTH_COOLING_DOWN = "cooling_down"
CHANNEL_HEALTH_DEGRADED = "degraded"
```

Use these stable error-kind strings:

```python
PROVIDER_ERROR_RATE_LIMITED = "rate_limited"
PROVIDER_ERROR_UNAVAILABLE = "unavailable"
PROVIDER_ERROR_TIMEOUT = "timeout"
PROVIDER_ERROR_MALFORMED_RESPONSE = "malformed_response"
PROVIDER_ERROR_AUTH = "auth"
PROVIDER_ERROR_BILLING = "billing"
PROVIDER_ERROR_PROVIDER = "provider_error"
```

Admin/log surfaces must never include:

- raw document text;
- translated document text;
- prompt bodies;
- raw API keys;
- admin secret IDs such as `.api_keys.`;
- bearer tokens.

---

## Task 1: DeepSeek Channel Telemetry Contract

**Files:**

- Modify `src/translator_service/deepseek_key_pool.py`
- Modify `tests/test_deepseek_key_pool.py`

- [x] **Step 1: Add failing snapshot telemetry test**

Append to `DeepSeekKeyPoolTranslatorTest`:

```python
def test_snapshot_reports_safe_channel_health_latency_and_error_kind(self):
    now = FakeClock(100.0)
    factory = RecordingClientFactory(
        {
            "secret-key-a": [
                DeepSeekApiError(
                    "DeepSeek API returned HTTP 429: Bearer secret-key-a busy"
                )
            ],
            "key-b": ["ok"],
        }
    )
    pool = DeepSeekKeyPoolTranslator(
        channels=[
            DeepSeekChannelConfig(api_key="secret-key-a", label="primary"),
            DeepSeekChannelConfig(api_key="key-b", label="backup"),
        ],
        client_factory=factory,
        cooldown_seconds=30,
        max_cooldown_seconds=120,
        clock=now,
    )

    self.assertEqual(
        pool.translate(text="source", source_language="en", target_language="uk"),
        "ok",
    )

    primary, backup = pool.snapshot()
    self.assertEqual(primary.health, "cooling_down")
    self.assertEqual(primary.error_kind, "rate_limited")
    self.assertEqual(primary.total_rate_limit_failures, 1)
    self.assertEqual(primary.cooldown_remaining_seconds, 30.0)
    self.assertIsNotNone(primary.last_latency_ms)
    self.assertIsNotNone(primary.average_latency_ms)
    self.assertIn("HTTP 429", primary.last_error or "")
    self.assertNotIn("secret-key-a", primary.last_error or "")
    self.assertNotIn("Bearer", primary.last_error or "")
    self.assertEqual(backup.health, "healthy")
```

- [x] **Step 2: Run the focused test and verify it fails**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_snapshot_reports_safe_channel_health_latency_and_error_kind
```

Expected: FAIL because `DeepSeekChannelSnapshot.health`, `error_kind`, `cooldown_remaining_seconds`, and latency fields do not exist.

- [x] **Step 3: Extend snapshot dataclass**

In `src/translator_service/deepseek_key_pool.py`, add constants near imports:

```python
CHANNEL_HEALTH_HEALTHY = "healthy"
CHANNEL_HEALTH_BUSY = "busy"
CHANNEL_HEALTH_COOLING_DOWN = "cooling_down"
CHANNEL_HEALTH_DEGRADED = "degraded"

PROVIDER_ERROR_RATE_LIMITED = "rate_limited"
PROVIDER_ERROR_UNAVAILABLE = "unavailable"
PROVIDER_ERROR_TIMEOUT = "timeout"
PROVIDER_ERROR_MALFORMED_RESPONSE = "malformed_response"
PROVIDER_ERROR_AUTH = "auth"
PROVIDER_ERROR_BILLING = "billing"
PROVIDER_ERROR_PROVIDER = "provider_error"
```

Extend `DeepSeekChannelSnapshot`:

```python
@dataclass(frozen=True)
class DeepSeekChannelSnapshot:
    label: str
    max_parallel_requests: int
    weight: int
    active_requests: int
    total_started_requests: int
    total_successful_requests: int
    total_temporary_failures: int
    total_permanent_failures: int
    consecutive_temporary_failures: int
    cooldown_until: float
    last_selected_at: float | None
    last_success_at: float | None
    last_failure_at: float | None
    last_error: str | None
    health: str = CHANNEL_HEALTH_HEALTHY
    cooldown_remaining_seconds: float = 0.0
    error_kind: str | None = None
    last_latency_ms: float | None = None
    average_latency_ms: float | None = None
    total_rate_limit_failures: int = 0
    total_unavailable_failures: int = 0
    total_timeout_failures: int = 0
    total_malformed_response_failures: int = 0
    total_auth_failures: int = 0
    total_billing_failures: int = 0
    total_other_provider_failures: int = 0
```

- [x] **Step 4: Extend channel state and snapshot method**

Add fields to `_DeepSeekChannel`:

```python
    error_kind: str | None = None
    last_latency_ms: float | None = None
    total_latency_ms: float = 0.0
    latency_sample_count: int = 0
    total_rate_limit_failures: int = 0
    total_unavailable_failures: int = 0
    total_timeout_failures: int = 0
    total_malformed_response_failures: int = 0
    total_auth_failures: int = 0
    total_billing_failures: int = 0
    total_other_provider_failures: int = 0
```

Change `_DeepSeekChannel.snapshot()`:

```python
    def snapshot(self, *, now: float) -> DeepSeekChannelSnapshot:
        cooldown_remaining = max(0.0, self.cooldown_until - now)
        average_latency_ms = (
            self.total_latency_ms / self.latency_sample_count
            if self.latency_sample_count
            else None
        )
        return DeepSeekChannelSnapshot(
            label=self.label,
            max_parallel_requests=self.capacity,
            weight=self.weight,
            active_requests=self.active_requests,
            total_started_requests=self.total_started_requests,
            total_successful_requests=self.total_successful_requests,
            total_temporary_failures=self.total_temporary_failures,
            total_permanent_failures=self.total_permanent_failures,
            consecutive_temporary_failures=self.consecutive_temporary_failures,
            cooldown_until=self.cooldown_until,
            last_selected_at=self.last_selected_at,
            last_success_at=self.last_success_at,
            last_failure_at=self.last_failure_at,
            last_error=self.last_error,
            health=_channel_health(self, now=now),
            cooldown_remaining_seconds=cooldown_remaining,
            error_kind=self.error_kind,
            last_latency_ms=self.last_latency_ms,
            average_latency_ms=average_latency_ms,
            total_rate_limit_failures=self.total_rate_limit_failures,
            total_unavailable_failures=self.total_unavailable_failures,
            total_timeout_failures=self.total_timeout_failures,
            total_malformed_response_failures=(
                self.total_malformed_response_failures
            ),
            total_auth_failures=self.total_auth_failures,
            total_billing_failures=self.total_billing_failures,
            total_other_provider_failures=self.total_other_provider_failures,
        )
```

Change pool snapshot:

```python
    def snapshot(self) -> list[DeepSeekChannelSnapshot]:
        with self._condition:
            now = self._clock()
            return [channel.snapshot(now=now) for channel in self._channels]
```

- [x] **Step 5: Add helper functions**

Add below `_is_channel_cooldown_error`:

```python
def _provider_error_kind(error: DeepSeekApiError) -> str:
    message = str(error).lower()
    if "http 429" in message or "rate limit" in message:
        return PROVIDER_ERROR_RATE_LIMITED
    if "http 503" in message or "http 502" in message or "http 504" in message:
        return PROVIDER_ERROR_UNAVAILABLE
    if "timeout" in message or "timed out" in message:
        return PROVIDER_ERROR_TIMEOUT
    if "malformed" in message or "invalid json" in message:
        return PROVIDER_ERROR_MALFORMED_RESPONSE
    if "http 401" in message or "http 403" in message or "auth" in message:
        return PROVIDER_ERROR_AUTH
    if "billing" in message or "insufficient" in message or "quota" in message:
        return PROVIDER_ERROR_BILLING
    return PROVIDER_ERROR_PROVIDER


def _channel_health(channel: _DeepSeekChannel, *, now: float) -> str:
    if channel.cooldown_until > now:
        return CHANNEL_HEALTH_COOLING_DOWN
    if channel.active_requests >= channel.capacity:
        return CHANNEL_HEALTH_BUSY
    if channel.consecutive_temporary_failures or channel.total_permanent_failures:
        return CHANNEL_HEALTH_DEGRADED
    return CHANNEL_HEALTH_HEALTHY
```

Update redaction:

```python
def _redact_channel_error(error: DeepSeekApiError, channel: _DeepSeekChannel) -> str:
    message = str(error).replace(channel.config.api_key, "[redacted-api-key]")
    message = message.replace("Bearer", "[redacted]")
    if len(message) > 300:
        return f"{message[:297]}..."
    return message
```

- [x] **Step 6: Track latency and classified counters**

In `translate()`, capture duration:

```python
            started_at = self._clock()
            try:
                translated = channel.client.translate(
                    text=text,
                    source_language=source_language,
                    target_language=target_language,
                )
                self._record_channel_latency(channel, started_at=started_at)
                self._record_channel_success(channel)
                self._last_usage.value = getattr(channel.client, "last_usage", None)
                return translated
            except DeepSeekApiError as error:
                self._record_channel_latency(channel, started_at=started_at)
                if not _is_channel_cooldown_error(error):
                    self._record_channel_permanent_failure(channel, error)
                    raise
                last_rate_error = error
                self._cool_down_channel(channel, error)
```

Add method:

```python
    def _record_channel_latency(
        self,
        channel: _DeepSeekChannel,
        *,
        started_at: float,
    ) -> None:
        with self._condition:
            latency_ms = max(0.0, (self._clock() - started_at) * 1000.0)
            channel.last_latency_ms = latency_ms
            channel.total_latency_ms += latency_ms
            channel.latency_sample_count += 1
```

In `_record_channel_success()`, clear `error_kind`:

```python
            channel.error_kind = None
```

In permanent and temporary failure handlers:

```python
            error_kind = _provider_error_kind(error)
            channel.error_kind = error_kind
            _increment_error_kind_counter(channel, error_kind)
```

Add:

```python
def _increment_error_kind_counter(channel: _DeepSeekChannel, error_kind: str) -> None:
    if error_kind == PROVIDER_ERROR_RATE_LIMITED:
        channel.total_rate_limit_failures += 1
    elif error_kind == PROVIDER_ERROR_UNAVAILABLE:
        channel.total_unavailable_failures += 1
    elif error_kind == PROVIDER_ERROR_TIMEOUT:
        channel.total_timeout_failures += 1
    elif error_kind == PROVIDER_ERROR_MALFORMED_RESPONSE:
        channel.total_malformed_response_failures += 1
    elif error_kind == PROVIDER_ERROR_AUTH:
        channel.total_auth_failures += 1
    elif error_kind == PROVIDER_ERROR_BILLING:
        channel.total_billing_failures += 1
    else:
        channel.total_other_provider_failures += 1
```

- [x] **Step 7: Run key pool tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool
```

Expected: OK.

- [ ] **Step 8: Commit**

```bash
git add src/translator_service/deepseek_key_pool.py tests/test_deepseek_key_pool.py
git commit -m "feat: add deepseek channel telemetry"
```

## Task 2: Latency/Error-Aware Weighted Least-Loaded Scoring

**Files:**

- Modify `src/translator_service/deepseek_key_pool.py`
- Modify `tests/test_deepseek_key_pool.py`

- [x] **Step 1: Add failing tests for scoring**

Add:

```python
def test_selection_penalizes_recent_provider_errors(self):
    now = FakeClock(100.0)
    factory = RecordingClientFactory(
        {
            "key-a": [
                DeepSeekApiError("DeepSeek API returned HTTP 429: busy"),
                "recovered",
            ],
            "key-b": ["fallback", "healthy"],
        }
    )
    pool = DeepSeekKeyPoolTranslator(
        channels=[
            DeepSeekChannelConfig(api_key="key-a", label="a"),
            DeepSeekChannelConfig(api_key="key-b", label="b"),
        ],
        client_factory=factory,
        cooldown_seconds=1,
        max_cooldown_seconds=1,
        clock=now,
    )

    self.assertEqual(pool.translate(text="one", source_language="en", target_language="uk"), "fallback")
    now.value = 101.0
    self.assertEqual(pool.translate(text="two", source_language="en", target_language="uk"), "healthy")

    self.assertEqual(factory.calls, [("key-a", "one"), ("key-b", "one"), ("key-b", "two")])


def test_selection_penalizes_slower_channel_when_load_is_equal(self):
    now = FakeClock(100.0)
    factory = LatencyClientFactory({"key-a": 2.0, "key-b": 0.1}, clock=now)
    pool = DeepSeekKeyPoolTranslator(
        channels=[
            DeepSeekChannelConfig(api_key="key-a", label="a"),
            DeepSeekChannelConfig(api_key="key-b", label="b"),
        ],
        client_factory=factory,
        cooldown_seconds=30,
        clock=now,
    )

    self.assertEqual(pool.translate(text="one", source_language="en", target_language="uk"), "[key-a] one")
    self.assertEqual(pool.translate(text="two", source_language="en", target_language="uk"), "[key-b] two")
    self.assertEqual(pool.translate(text="three", source_language="en", target_language="uk"), "[key-b] three")
```

Add helper:

```python
class LatencyClientFactory:
    def __init__(self, delays_by_key, *, clock: FakeClock) -> None:
        self.delays_by_key = dict(delays_by_key)
        self.clock = clock

    def __call__(self, *, api_key: str):
        return LatencyClient(api_key=api_key, factory=self)


class LatencyClient:
    def __init__(self, *, api_key: str, factory: LatencyClientFactory) -> None:
        self.api_key = api_key
        self.factory = factory
        self.last_usage = _Usage(prompt_tokens=1)

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.factory.clock.value += self.factory.delays_by_key[self.api_key]
        return f"[{self.api_key}] {text}"
```

- [x] **Step 2: Run tests and verify they fail**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_selection_penalizes_recent_provider_errors \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_selection_penalizes_slower_channel_when_load_is_equal
```

Expected: FAIL because scoring ignores recent errors and latency.

- [x] **Step 3: Replace channel selection key**

Change call site:

```python
                    channel = min(
                        candidates,
                        key=lambda candidate: _channel_selection_key(
                            candidate,
                            now=now,
                        ),
                    )
```

Replace helper:

```python
def _channel_selection_key(
    channel: _DeepSeekChannel,
    *,
    now: float,
) -> tuple[float, float, int, float, str]:
    active_load = channel.active_requests / channel.capacity
    weighted_fairness = channel.total_started_requests / (
        channel.capacity * channel.weight
    )
    error_penalty = min(5, channel.consecutive_temporary_failures) * 0.25
    if channel.last_failure_at is not None and now - channel.last_failure_at < 300:
        error_penalty += 0.25
    latency_penalty = 0.0
    if channel.latency_sample_count:
        average_latency_ms = channel.total_latency_ms / channel.latency_sample_count
        latency_penalty = min(1.0, average_latency_ms / 10_000.0)
    last_selected_at = (
        channel.last_selected_at
        if channel.last_selected_at is not None
        else float("-inf")
    )
    return (
        active_load,
        weighted_fairness + error_penalty + latency_penalty,
        -channel.weight,
        last_selected_at,
        channel.label,
    )
```

- [x] **Step 4: Run key pool tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add src/translator_service/deepseek_key_pool.py tests/test_deepseek_key_pool.py
git commit -m "feat: score deepseek channels by health and latency"
```

## Task 3: Runtime Store Persists Channel Telemetry

**Files:**

- Modify `src/translator_service/admin/provider_runtime.py`
- Modify `tests/test_ai_provider_runtime.py`

- [x] **Step 1: Add failing runtime store roundtrip test**

Add to `AIProviderRuntimeTest`:

```python
def test_runtime_status_roundtrips_channel_telemetry(self):
    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "admin.sqlite3"
        with SQLiteAIProviderRuntimeStore(db_path) as store:
            store.record_status(
                provider_id="deepseek",
                source="admin_store+env",
                status="degraded",
                reload_interval_seconds=30.0,
                active_channels=(
                    AIProviderRuntimeChannel(
                        label="primary",
                        weight=3,
                        max_parallel_requests=2,
                        active_requests=1,
                        health="cooling_down",
                        cooldown_remaining_seconds=12.5,
                        total_started_requests=10,
                        total_successful_requests=8,
                        total_temporary_failures=2,
                        total_permanent_failures=1,
                        total_rate_limit_failures=2,
                        total_unavailable_failures=0,
                        total_timeout_failures=0,
                        total_malformed_response_failures=0,
                        total_auth_failures=1,
                        total_billing_failures=0,
                        average_latency_ms=1234.5,
                        last_latency_ms=999.0,
                        error_kind="rate_limited",
                        last_error_excerpt="HTTP 429 [redacted-api-key]",
                    ),
                ),
                error=None,
            )
            status = store.get_status("deepseek")

    channel = status.active_channels[0]
    self.assertEqual(channel.health, "cooling_down")
    self.assertEqual(channel.active_requests, 1)
    self.assertEqual(channel.cooldown_remaining_seconds, 12.5)
    self.assertEqual(channel.total_rate_limit_failures, 2)
    self.assertEqual(channel.total_auth_failures, 1)
    self.assertEqual(channel.average_latency_ms, 1234.5)
    self.assertEqual(channel.error_kind, "rate_limited")
    self.assertNotIn("sk-", repr(status))
    self.assertNotIn(".api_keys.", repr(status))
```

- [x] **Step 2: Run test and verify it fails**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_ai_provider_runtime.AIProviderRuntimeTest.test_runtime_status_roundtrips_channel_telemetry
```

Expected: FAIL because `AIProviderRuntimeChannel` lacks telemetry fields.

- [x] **Step 3: Extend dataclass with safe defaults**

In `src/translator_service/admin/provider_runtime.py`:

```python
@dataclass(frozen=True)
class AIProviderRuntimeChannel:
    label: str
    weight: int
    max_parallel_requests: int
    active_requests: int = 0
    health: str = "healthy"
    cooldown_remaining_seconds: float = 0.0
    total_started_requests: int = 0
    total_successful_requests: int = 0
    total_temporary_failures: int = 0
    total_permanent_failures: int = 0
    total_rate_limit_failures: int = 0
    total_unavailable_failures: int = 0
    total_timeout_failures: int = 0
    total_malformed_response_failures: int = 0
    total_auth_failures: int = 0
    total_billing_failures: int = 0
    total_other_provider_failures: int = 0
    average_latency_ms: float | None = None
    last_latency_ms: float | None = None
    error_kind: str | None = None
    last_error_excerpt: str | None = None
```

- [x] **Step 4: Persist all fields**

In `record_status()`, replace payload item dict:

```python
                {
                    "label": channel.label,
                    "weight": max(1, int(channel.weight)),
                    "max_parallel_requests": max(
                        1,
                        int(channel.max_parallel_requests),
                    ),
                    "active_requests": max(0, int(channel.active_requests)),
                    "health": channel.health,
                    "cooldown_remaining_seconds": max(
                        0.0,
                        float(channel.cooldown_remaining_seconds),
                    ),
                    "total_started_requests": max(
                        0,
                        int(channel.total_started_requests),
                    ),
                    "total_successful_requests": max(
                        0,
                        int(channel.total_successful_requests),
                    ),
                    "total_temporary_failures": max(
                        0,
                        int(channel.total_temporary_failures),
                    ),
                    "total_permanent_failures": max(
                        0,
                        int(channel.total_permanent_failures),
                    ),
                    "total_rate_limit_failures": max(
                        0,
                        int(channel.total_rate_limit_failures),
                    ),
                    "total_unavailable_failures": max(
                        0,
                        int(channel.total_unavailable_failures),
                    ),
                    "total_timeout_failures": max(
                        0,
                        int(channel.total_timeout_failures),
                    ),
                    "total_malformed_response_failures": max(
                        0,
                        int(channel.total_malformed_response_failures),
                    ),
                    "total_auth_failures": max(0, int(channel.total_auth_failures)),
                    "total_billing_failures": max(
                        0,
                        int(channel.total_billing_failures),
                    ),
                    "total_other_provider_failures": max(
                        0,
                        int(channel.total_other_provider_failures),
                    ),
                    "average_latency_ms": channel.average_latency_ms,
                    "last_latency_ms": channel.last_latency_ms,
                    "error_kind": channel.error_kind,
                    "last_error_excerpt": channel.last_error_excerpt,
                }
```

- [x] **Step 5: Parse with backwards-compatible defaults**

In `_status_from_row()` channel parser:

```python
            AIProviderRuntimeChannel(
                label=str(item.get("label", "")),
                weight=max(1, int(item.get("weight", 1))),
                max_parallel_requests=max(
                    1,
                    int(item.get("max_parallel_requests", 1)),
                ),
                active_requests=max(0, int(item.get("active_requests", 0))),
                health=str(item.get("health", "healthy")),
                cooldown_remaining_seconds=max(
                    0.0,
                    float(item.get("cooldown_remaining_seconds", 0.0)),
                ),
                total_started_requests=max(
                    0,
                    int(item.get("total_started_requests", 0)),
                ),
                total_successful_requests=max(
                    0,
                    int(item.get("total_successful_requests", 0)),
                ),
                total_temporary_failures=max(
                    0,
                    int(item.get("total_temporary_failures", 0)),
                ),
                total_permanent_failures=max(
                    0,
                    int(item.get("total_permanent_failures", 0)),
                ),
                total_rate_limit_failures=max(
                    0,
                    int(item.get("total_rate_limit_failures", 0)),
                ),
                total_unavailable_failures=max(
                    0,
                    int(item.get("total_unavailable_failures", 0)),
                ),
                total_timeout_failures=max(
                    0,
                    int(item.get("total_timeout_failures", 0)),
                ),
                total_malformed_response_failures=max(
                    0,
                    int(item.get("total_malformed_response_failures", 0)),
                ),
                total_auth_failures=max(0, int(item.get("total_auth_failures", 0))),
                total_billing_failures=max(
                    0,
                    int(item.get("total_billing_failures", 0)),
                ),
                total_other_provider_failures=max(
                    0,
                    int(item.get("total_other_provider_failures", 0)),
                ),
                average_latency_ms=_optional_float(item.get("average_latency_ms")),
                last_latency_ms=_optional_float(item.get("last_latency_ms")),
                error_kind=(
                    str(item["error_kind"]) if item.get("error_kind") else None
                ),
                last_error_excerpt=(
                    str(item["last_error_excerpt"])
                    if item.get("last_error_excerpt")
                    else None
                ),
            )
```

Add helper:

```python
def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
```

- [x] **Step 6: Run runtime tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_ai_provider_runtime
```

Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add src/translator_service/admin/provider_runtime.py tests/test_ai_provider_runtime.py
git commit -m "feat: persist provider runtime channel telemetry"
```

## Task 4: Record Runtime Telemetry From DeepSeek Pool

**Files:**

- Modify `src/translator_service/bot/runtime.py`
- Modify `tests/test_bot_runtime.py`

- [x] **Step 1: Add failing test for single-key pool and runtime telemetry**

Add to `tests/test_bot_runtime.py`:

```python
def test_deepseek_translator_uses_pool_for_single_key_runtime_telemetry(self):
    with patch.dict(
        "os.environ",
        {
            "DEEPSEEK_API_KEY": "key-a",
            "DEEPSEEK_API_KEYS": "",
            "DEEPSEEK_MAX_PARALLEL_PER_KEY": "1",
        },
    ):
        translator = build_deepseek_translator(Settings(admin_secret_master_key=""))

    self.assertIsInstance(translator, DeepSeekKeyPoolTranslator)
    self.assertEqual([channel.label for channel in translator.snapshot()], ["deepseek-1"])
```

Add to reloadable runtime tests:

```python
def test_reloadable_translator_records_channel_telemetry_snapshot(self):
    with TemporaryDirectory() as temp_dir:
        db_path = str(Path(temp_dir) / "admin.sqlite3")
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEYS": "key-a,key-b",
                "DEEPSEEK_MAX_PARALLEL_PER_KEY": "1",
            },
        ):
            translator = ReloadableDeepSeekTranslator(
                settings=Settings(
                    admin_db_path=db_path,
                    admin_secret_master_key=MASTER_KEY,
                    admin_provider_runtime_reload_seconds=0.0,
                )
            )
            snapshot = translator.snapshot()
            with SQLiteAIProviderRuntimeStore(db_path) as runtime:
                status = runtime.get_status("deepseek")

    self.assertEqual([channel.label for channel in snapshot], ["deepseek-1", "deepseek-2"])
    self.assertIsNotNone(status)
    self.assertEqual(len(status.active_channels), 2)
    self.assertEqual(status.active_channels[0].health, "healthy")
    self.assertEqual(status.active_channels[0].active_requests, 0)
```

- [x] **Step 2: Run tests and verify they fail**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_bot_runtime.BotRuntimeTest.test_deepseek_translator_uses_pool_for_single_key_runtime_telemetry \
  tests.test_bot_runtime.BotRuntimeTest.test_reloadable_translator_records_channel_telemetry_snapshot
```

Expected: FAIL because single-key env uses `DeepSeekClient` and runtime status only records static channel config.

- [x] **Step 3: Always return `DeepSeekKeyPoolTranslator`**

In `_deepseek_translator_from_channels()`, remove the single-channel `DeepSeekClient` special case. Keep the existing `client_factory` and always return:

```python
    return DeepSeekKeyPoolTranslator(
        channels=channels,
        client_factory=client_factory,
        model=settings.deepseek_model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
        cooldown_seconds=cooldown_seconds,
        max_cooldown_seconds=max_cooldown_seconds,
    )
```

Update existing tests that expected `DeepSeekClient` for one key to expect `DeepSeekKeyPoolTranslator` and one channel.

- [x] **Step 4: Add telemetry conversion helper**

In `src/translator_service/bot/runtime.py`:

```python
def _runtime_channel_from_snapshot(snapshot) -> AIProviderRuntimeChannel:
    return AIProviderRuntimeChannel(
        label=snapshot.label,
        weight=snapshot.weight,
        max_parallel_requests=snapshot.max_parallel_requests,
        active_requests=snapshot.active_requests,
        health=snapshot.health,
        cooldown_remaining_seconds=snapshot.cooldown_remaining_seconds,
        total_started_requests=snapshot.total_started_requests,
        total_successful_requests=snapshot.total_successful_requests,
        total_temporary_failures=snapshot.total_temporary_failures,
        total_permanent_failures=snapshot.total_permanent_failures,
        total_rate_limit_failures=snapshot.total_rate_limit_failures,
        total_unavailable_failures=snapshot.total_unavailable_failures,
        total_timeout_failures=snapshot.total_timeout_failures,
        total_malformed_response_failures=(
            snapshot.total_malformed_response_failures
        ),
        total_auth_failures=snapshot.total_auth_failures,
        total_billing_failures=snapshot.total_billing_failures,
        total_other_provider_failures=snapshot.total_other_provider_failures,
        average_latency_ms=snapshot.average_latency_ms,
        last_latency_ms=snapshot.last_latency_ms,
        error_kind=snapshot.error_kind,
        last_error_excerpt=snapshot.last_error,
    )
```

- [x] **Step 5: Record snapshots safely**

Add fields in `ReloadableDeepSeekTranslator.__init__`:

```python
        self._runtime_source = "unknown"
        self._runtime_status = "missing_keys"
        self._runtime_error: str | None = None
```

In `_reload_locked()`, after calculating `source/status/error`, set:

```python
        self._runtime_source = source
        self._runtime_status = status
        self._runtime_error = error
```

Add method:

```python
    def _record_current_runtime_snapshot(self) -> None:
        translator = self._translator
        if translator is None:
            return
        snapshot = getattr(translator, "snapshot", None)
        if snapshot is None:
            return
        snapshots = snapshot()
        _record_deepseek_runtime_status(
            self._settings,
            source=self._runtime_source,
            status=_runtime_status_from_snapshots(
                self._runtime_status,
                snapshots,
            ),
            channels=[
                DeepSeekChannelConfig(
                    api_key="redacted-runtime-placeholder",
                    label=item.label,
                    max_parallel_requests=item.max_parallel_requests,
                    weight=item.weight,
                )
                for item in snapshots
            ],
            error=self._runtime_error,
            runtime_channels=tuple(
                _runtime_channel_from_snapshot(item) for item in snapshots
            ),
        )
```

Change `_record_deepseek_runtime_status()` signature:

```python
def _record_deepseek_runtime_status(
    settings: Settings,
    *,
    source: str = "admin_store",
    status: str,
    channels: list[DeepSeekChannelConfig],
    error: str | None,
    runtime_channels: tuple[AIProviderRuntimeChannel, ...] | None = None,
) -> None:
```

Use:

```python
            active_channels=runtime_channels
            if runtime_channels is not None
            else tuple(
                AIProviderRuntimeChannel(
                    label=channel.label or "unnamed",
                    weight=channel.weight,
                    max_parallel_requests=channel.max_parallel_requests,
                )
                for channel in channels
            ),
```

Add:

```python
def _runtime_status_from_snapshots(base_status: str, snapshots) -> str:
    if base_status != "ok":
        return base_status
    if any(item.health in {"cooling_down", "degraded"} for item in snapshots):
        return "degraded"
    return "ok"
```

- [x] **Step 6: Call snapshot recording**

In `ReloadableDeepSeekTranslator.snapshot()` after getting `result = snapshot()`:

```python
        result = snapshot()
        with self._lock:
            self._record_current_runtime_snapshot()
        return result
```

In `translate()`:

```python
        try:
            translated = translator.translate(
                text=text,
                source_language=source_language,
                target_language=target_language,
            )
            self._last_usage.value = getattr(translator, "last_usage", None)
            return translated
        finally:
            with self._lock:
                self._record_current_runtime_snapshot()
```

- [x] **Step 7: Run runtime tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime tests.test_ai_provider_runtime
```

Expected: OK.

- [ ] **Step 8: Commit**

```bash
git add src/translator_service/bot/runtime.py tests/test_bot_runtime.py
git commit -m "feat: record deepseek runtime telemetry"
```

## Task 5: Provider Health Uses Runtime Degradation

**Files:**

- Modify `src/translator_service/admin/provider_health.py`
- Modify `src/translator_service/admin/routes.py`
- Modify `tests/test_admin_provider_health.py`
- Modify `tests/test_admin_routes.py`

- [x] **Step 1: Add failing provider health test**

In `tests/test_admin_provider_health.py`, import `AIProviderRuntimeChannel` and `AIProviderRuntimeStatus`, then add:

```python
def test_runtime_cooldown_degrades_provider_health_without_exposing_secret_text(self):
    runtime = AIProviderRuntimeStatus(
        provider_id="deepseek",
        source="admin_store",
        status="degraded",
        reload_interval_seconds=30.0,
        last_reloaded_at=datetime(2026, 5, 10, tzinfo=UTC),
        active_channels=(
            AIProviderRuntimeChannel(
                label="main",
                weight=1,
                max_parallel_requests=1,
                health="cooling_down",
                total_rate_limit_failures=3,
                error_kind="rate_limited",
                last_error_excerpt="HTTP 429 Bearer sk-live-secret-value",
            ),
        ),
    )

    health = build_provider_health(
        (_provider(),),
        {"deepseek": (_key(),)},
        runtime_statuses=(runtime,),
    )

    self.assertEqual(health[0].status, "degraded")
    self.assertEqual(health[0].last_validation_status, "runtime degraded")
    self.assertIn("rate_limited", health[0].last_error_excerpt)
    self.assertNotIn("sk-live-secret-value", health[0].last_error_excerpt)
    self.assertNotIn("Bearer", health[0].last_error_excerpt)
```

- [x] **Step 2: Run test and verify it fails**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_provider_health.AdminProviderHealthTest.test_runtime_cooldown_degrades_provider_health_without_exposing_secret_text
```

Expected: FAIL because `build_provider_health()` does not accept runtime statuses.

- [x] **Step 3: Extend health builder**

In `provider_health.py`, import:

```python
from translator_service.admin.provider_runtime import AIProviderRuntimeStatus
```

Change signature:

```python
def build_provider_health(
    summaries: tuple[IntegrationSummary, ...],
    key_pools: Mapping[str, tuple[AIProviderKeySummary, ...]],
    validation_metadata: ValidationMetadata | None = None,
    runtime_statuses: tuple[AIProviderRuntimeStatus, ...] = (),
) -> tuple[ProviderHealthSummary, ...]:
```

Build map:

```python
    runtime_by_provider = {status.provider_id: status for status in runtime_statuses}
```

Pass:

```python
            runtime=runtime_by_provider.get(summary.integration_id),
```

Change `_provider_health_summary()` signature:

```python
    runtime: AIProviderRuntimeStatus | None = None,
```

Before final status:

```python
    runtime_degraded = runtime is not None and (
        runtime.status != "ok"
        or any(
            channel.health in {"cooling_down", "degraded"}
            for channel in runtime.active_channels
        )
    )
    if runtime_degraded and last_validation_status == _DEFAULT_VALIDATION_STATUS:
        last_validation_status = "runtime degraded"
    runtime_error_excerpt = _runtime_error_excerpt(runtime)
    if runtime_error_excerpt != _DEFAULT_ERROR_EXCERPT:
        last_error_excerpt = runtime_error_excerpt
```

Add:

```python
def _runtime_error_excerpt(
    runtime: AIProviderRuntimeStatus | None,
) -> str:
    if runtime is None:
        return _DEFAULT_ERROR_EXCERPT
    for channel in runtime.active_channels:
        if channel.error_kind or channel.last_error_excerpt:
            raw = " ".join(
                part
                for part in (
                    channel.label,
                    channel.error_kind,
                    channel.last_error_excerpt,
                )
                if part
            )
            return _last_error_excerpt({"last_error": raw})
    if runtime.error:
        return _last_error_excerpt({"last_error": runtime.error})
    return _DEFAULT_ERROR_EXCERPT
```

- [x] **Step 4: Pass runtime statuses from routes**

In `_ai_provider_health(settings)` in `routes.py`, fetch runtime once:

```python
    runtime_statuses = _ai_provider_runtime_statuses(settings)
```

Pass into both `build_provider_health(...)` calls:

```python
            runtime_statuses=runtime_statuses,
```

- [x] **Step 5: Run tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_health tests.test_admin_routes
```

Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add \
  src/translator_service/admin/provider_health.py \
  src/translator_service/admin/routes.py \
  tests/test_admin_provider_health.py \
  tests/test_admin_routes.py
git commit -m "feat: derive provider health from runtime telemetry"
```

## Task 6: Admin Runtime UI and API Show Channel Telemetry

**Files:**

- Modify `src/translator_service/admin/views.py`
- Modify `src/translator_service/admin/routes.py`
- Modify `tests/test_admin_routes.py`

- [x] **Step 1: Add failing admin route test**

Extend `test_ai_provider_page_shows_runtime_status_and_requests_reload()` by recording richer channel fields:

```python
                        AIProviderRuntimeChannel(
                            label="stable",
                            weight=3,
                            max_parallel_requests=2,
                            active_requests=1,
                            health="cooling_down",
                            cooldown_remaining_seconds=12.0,
                            total_started_requests=10,
                            total_successful_requests=8,
                            total_temporary_failures=2,
                            total_permanent_failures=0,
                            total_rate_limit_failures=2,
                            average_latency_ms=456.7,
                            error_kind="rate_limited",
                            last_error_excerpt="HTTP 429 [redacted-api-key]",
                        ),
```

Add assertions:

```python
self.assertIn("cooling_down", page.text)
self.assertIn("active 1/2", page.text)
self.assertIn("cooldown 12s", page.text)
self.assertIn("429: 2", page.text)
self.assertIn("latency 456.7ms", page.text)
self.assertIn("rate_limited", page.text)
self.assertNotIn("sk-live-secret-value", page.text)
runtime_payload = runtime_api.json()["providers"][0]["active_channels"][0]
self.assertEqual(runtime_payload["health"], "cooling_down")
self.assertEqual(runtime_payload["active_requests"], 1)
self.assertEqual(runtime_payload["cooldown_remaining_seconds"], 12.0)
self.assertEqual(runtime_payload["total_rate_limit_failures"], 2)
self.assertEqual(runtime_payload["error_kind"], "rate_limited")
```

- [x] **Step 2: Run test and verify it fails**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_admin_routes.AdminRoutesTest.test_ai_provider_page_shows_runtime_status_and_requests_reload
```

Expected: FAIL because UI/API do not include telemetry fields.

- [x] **Step 3: Extend runtime API payload**

In `_ai_provider_runtime_payload()` channel dict:

```python
            {
                "label": channel.label,
                "weight": channel.weight,
                "max_parallel_requests": channel.max_parallel_requests,
                "active_requests": channel.active_requests,
                "health": channel.health,
                "cooldown_remaining_seconds": channel.cooldown_remaining_seconds,
                "total_started_requests": channel.total_started_requests,
                "total_successful_requests": channel.total_successful_requests,
                "total_temporary_failures": channel.total_temporary_failures,
                "total_permanent_failures": channel.total_permanent_failures,
                "total_rate_limit_failures": channel.total_rate_limit_failures,
                "total_unavailable_failures": channel.total_unavailable_failures,
                "total_timeout_failures": channel.total_timeout_failures,
                "total_malformed_response_failures": (
                    channel.total_malformed_response_failures
                ),
                "total_auth_failures": channel.total_auth_failures,
                "total_billing_failures": channel.total_billing_failures,
                "average_latency_ms": channel.average_latency_ms,
                "last_latency_ms": channel.last_latency_ms,
                "error_kind": channel.error_kind,
                "last_error_excerpt": channel.last_error_excerpt,
            }
```

- [x] **Step 4: Render runtime channel rows**

In `views.py`, replace channel span generation in `_provider_runtime_panel()` with:

```python
        channels = "\n".join(
            _provider_runtime_channel_row(channel)
            for channel in runtime.active_channels
        )
```

Add helper:

```python
def _provider_runtime_channel_row(channel: AIProviderRuntimeChannel) -> str:
    cooldown = _format_seconds(channel.cooldown_remaining_seconds)
    latency = (
        "n/a"
        if channel.average_latency_ms is None
        else f"{channel.average_latency_ms:.1f}ms"
    )
    error = channel.last_error_excerpt or "n/a"
    return f"""
      <div class="key-row">
        <div>
          <strong>{escape(channel.label)}</strong>
          <span>
            {escape(channel.health)} · active
            {channel.active_requests}/{channel.max_parallel_requests} ·
            weight {channel.weight} · cooldown {escape(cooldown)} ·
            latency {escape(latency)}
          </span>
          <span>
            started {channel.total_started_requests} ·
            ok {channel.total_successful_requests} ·
            temporary {channel.total_temporary_failures} ·
            permanent {channel.total_permanent_failures} ·
            429: {channel.total_rate_limit_failures} ·
            503: {channel.total_unavailable_failures} ·
            timeout: {channel.total_timeout_failures} ·
            auth: {channel.total_auth_failures} ·
            billing: {channel.total_billing_failures}
          </span>
          <span>
            {escape(channel.error_kind or "no_error")} · {escape(error)}
          </span>
        </div>
      </div>
    """
```

- [x] **Step 5: Update Live Monitor runtime cards**

In `_live_runtime_cards()`, compute:

```python
    degraded_count = 0
    rate_limit_count = 0
    timeout_count = 0
    if status is not None:
        degraded_count = sum(
            1
            for channel in status.active_channels
            if channel.health in {"cooling_down", "degraded"}
        )
        rate_limit_count = sum(
            channel.total_rate_limit_failures for channel in status.active_channels
        )
        timeout_count = sum(
            channel.total_timeout_failures for channel in status.active_channels
        )
```

Add cards:

```python
        ("Degraded channels", str(degraded_count)),
        ("429 count", str(rate_limit_count)),
        ("Timeout count", str(timeout_count)),
```

- [x] **Step 6: Run admin route tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_routes tests.test_admin_live_monitor
```

Expected: OK.

- [ ] **Step 7: Commit**

```bash
git add src/translator_service/admin/views.py src/translator_service/admin/routes.py tests/test_admin_routes.py tests/test_admin_live_monitor.py
git commit -m "feat: show provider channel telemetry in admin"
```

## Task 7: Documentation and Defaults

**Files:**

- Modify `.env.server.example`
- Modify `README.md`
- Modify `README.project.md`
- Modify `docs/deployment/admin-vps-runbook.md`
- Test `tests/test_server_deployment_config.py`

- [x] **Step 1: Add env documentation**

In `.env.server.example`, add comments near DeepSeek channel settings:

```env
# Provider channel safety. Runtime telemetry in admin shows per-key cooldown,
# counters, latency and safe error summaries. Keep per-key parallelism at 1 for
# beta unless the provider account explicitly supports more.
DEEPSEEK_CHANNEL_COOLDOWN_SECONDS=30
DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS=300
```

- [x] **Step 2: Add deployment docs**

In README and runbook, add:

```markdown
The AI Providers admin page reports DeepSeek runtime channel health without
secrets or document text: active requests, per-key capacity, cooldown,
429/503/timeout/auth/billing counters, latency and a redacted last error. A
degraded channel does not disable the key automatically in Phase 2; it lowers
selection priority and remains visible for operator action.
```

- [x] **Step 3: Add server deployment config assertions**

In `tests/test_server_deployment_config.py`, ensure required lines include:

```python
"DEEPSEEK_CHANNEL_COOLDOWN_SECONDS=30",
"DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS=300",
```

- [x] **Step 4: Run docs/config tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_server_deployment_config
```

Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add .env.server.example README.md README.project.md docs/deployment/admin-vps-runbook.md tests/test_server_deployment_config.py
git commit -m "docs: document provider channel telemetry"
```

## Task 8: Verification

**Files:**

- No code changes expected.

- [x] **Step 1: Run targeted Phase 2 suite**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_deepseek_key_pool \
  tests.test_ai_provider_runtime \
  tests.test_bot_runtime \
  tests.test_admin_provider_health \
  tests.test_admin_routes \
  tests.test_admin_live_monitor \
  tests.test_server_deployment_config
```

Expected: OK.

- [x] **Step 2: Run scheduler regression suite**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_worker \
  tests.test_scheduler \
  tests.test_scheduler_runner \
  tests.test_persistent_jobs \
  tests.test_postgres_scheduler
```

Expected: OK. Postgres integration may skip if `TEST_POSTGRES_DSN` is unset.

- [x] **Step 3: Run compile**

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: OK.

- [x] **Step 4: Run predeploy check**

```bash
scripts/predeploy_check.sh
```

Expected: OK.

- [x] **Step 5: Run real Postgres integration if Docker is available**

```bash
docker compose up -d postgres
docker compose run --rm --no-deps \
  -v "$PWD:/workspace" \
  -w /workspace \
  -e TEST_POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator \
  -e PYTHONPATH=src \
  api python -m unittest tests.test_postgres_scheduler
```

Expected:

```text
Ran 14 tests
OK
```

---

## Acceptance Criteria

- Single-key DeepSeek runtime still works and remains serial when capacity is 1.
- Arbitrary key count still works.
- Weighted least-loaded selection still prefers capacity and weights, but penalizes recent provider errors and high latency.
- 429/503/timeouts cool down channels and fail over when another channel is healthy.
- Auth/billing errors are visible as degraded provider state and do not leak secrets.
- Admin AI Providers shows per-channel health, active requests, capacity, cooldown, counters, latency and redacted last error.
- Live Monitor shows provider degradation summary.
- Runtime API includes safe channel telemetry.
- Admin/log surfaces do not expose raw document text, translated text, prompt bodies, raw API keys, bearer tokens, or `.api_keys.` secret IDs.
- Existing scheduler Phase 1 tests remain green.

## Self-Review

Spec coverage:

- Better key scoring: Tasks 1 and 2.
- Cooldown/failover visibility: Tasks 1, 3, 4, 5 and 6.
- Latency/error-aware scoring: Task 2.
- Admin/provider degradation visibility: Tasks 3, 5 and 6.
- Runtime reload/admin key changes: Task 4 preserves reload flow and records snapshots after reload/translate.
- Safe redaction: Tasks 1, 3, 5 and 6.
- No AIMD/cost-aware scheduling: explicitly out of scope.

Placeholder scan:

- No `TBD`, no generic “add tests”, no undefined task-level function names intentionally left unresolved.

Residual risks:

- This plan keeps runtime telemetry in the existing SQLite admin runtime store, so it is operator-visible but not a cross-worker correctness mechanism.
- Multi-process provider-channel active request counts remain per-process telemetry until a later Postgres provider lease phase.
