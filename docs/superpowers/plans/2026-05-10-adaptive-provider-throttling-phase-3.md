# Adaptive Provider Throttling Phase 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add beta-safe adaptive throttling for DeepSeek-compatible provider calls: AIMD concurrency ramp, cooldown jitter, provider circuit breaker, runtime/admin visibility and scheduler claim avoidance when provider capacity is temporarily unavailable.

**Architecture:** Keep Phase 1 scheduler fairness and Phase 2 channel telemetry intact. Add a local per-worker provider safety loop inside `DeepSeekKeyPoolTranslator`: it gates provider call starts, shrinks concurrency on provider degradation, slowly ramps after stable successes, and opens a provider-level circuit for hard auth/billing or sustained temporary failures. Persist only safe provider-level runtime snapshots in the existing SQLite admin runtime store; do not make Redis mandatory and do not introduce distributed global provider leases in Phase 3.

**Tech Stack:** Python 3.13, `unittest`, SQLite admin runtime store, existing FastAPI admin views/routes, existing worker/scheduler runner, existing DeepSeek-compatible provider layer.

**Implementation status (2026-05-10):** Implemented, documented and verified as one cohesive changeset.

---

## Scope

Phase 3 implements:

- local AIMD-style provider concurrency limit per runtime process;
- slow-start/ramp from safe initial capacity to configured channel capacity;
- multiplicative decrease on 429/503/timeout and malformed provider output;
- provider circuit breaker for auth/billing failures and repeated temporary failures;
- jittered per-channel cooldown to reduce retry storms;
- scheduler runner capacity hints so workers do not claim new units while provider capacity is currently zero;
- runtime/admin API/UI visibility for adaptive limit, circuit state, throttle events and safe last reason;
- docs/env defaults for safe beta operation.

Phase 3 does not implement:

- cross-worker distributed provider capacity accounting;
- Redis-based scheduler correctness;
- token/cost-aware scheduling or budget depletion logic;
- automatic admin key disablement;
- paid-beta billing gates;
- raw request/response logging.

## Design Decisions

1. **Local safety first:** Each worker process adapts independently. This is not perfect global coordination, but it is safe, simple and avoids making Redis required for correctness.
2. **Provider pool owns provider starts:** Scheduler fairness decides who gets a work-unit slot; provider throttle decides whether this process may start another provider call right now.
3. **Scheduler avoids obvious waste:** If the translator reports `available_parallel_slots() == 0`, scheduler runner does not claim more units just to block inside the provider pool.
4. **AIMD, not magic:** Start low, increase by one after a configurable number of clean successes, decrease by a factor after provider failures.
5. **Circuit breaker is loud, not silent:** Auth/billing and sustained provider degradation should surface in admin and stop new starts for a short reset window.
6. **No secrets/text in telemetry:** Store reason kind and redacted excerpts only. No document text, prompts, translations, API keys or secret ids.

## File Structure

- Create `src/translator_service/provider_throttle.py`: pure adaptive throttle/circuit breaker policy with deterministic tests.
- Modify `tests/test_provider_throttle.py`: policy tests for ramp, decrease, circuit open/half-open, snapshots.
- Modify `src/translator_service/deepseek_key_pool.py`: integrate adaptive provider gate, provider snapshot, cooldown jitter.
- Modify `tests/test_deepseek_key_pool.py`: pool-level tests for adaptive cap, failover, circuit and redaction.
- Modify `src/translator_service/bot/runtime.py`: parse env defaults, pass throttle config into key pool, record provider-level snapshot.
- Modify `tests/test_bot_runtime.py`: env/config and runtime snapshot tests.
- Modify `src/translator_service/admin/provider_runtime.py`: persist provider-level runtime state with backwards-compatible schema migration.
- Modify `tests/test_ai_provider_runtime.py`: provider state roundtrip and legacy row tests.
- Modify `src/translator_service/scheduler_runner.py`: use optional translator capacity hint before claiming more work.
- Modify `tests/test_scheduler_runner.py`: no-claim behavior when provider capacity is zero.
- Modify `src/translator_service/admin/provider_health.py`: degrade health when provider circuit is open.
- Modify `src/translator_service/admin/routes.py`: include provider adaptive state in `/admin/api/ai-providers/runtime`.
- Modify `src/translator_service/admin/views.py`: show adaptive/circuit state in AI Providers and Live Monitor.
- Modify `tests/test_admin_provider_health.py`, `tests/test_admin_routes.py`, `tests/test_admin_live_monitor.py`: admin visibility/redaction tests.
- Modify `.env.server.example`, `README.md`, `README.project.md`, `docs/deployment/admin-vps-runbook.md`, `CURRENT_PROJECT_STATE.md`, `DOCUMENT_INDEX.md`: docs and defaults.
- Modify `tests/test_server_deployment_config.py`: required env defaults.

## Runtime Vocabulary

Use stable circuit states:

```python
PROVIDER_CIRCUIT_CLOSED = "closed"
PROVIDER_CIRCUIT_OPEN = "open"
PROVIDER_CIRCUIT_HALF_OPEN = "half_open"
```

Use stable throttle event kinds:

```python
THROTTLE_EVENT_SUCCESS = "success"
THROTTLE_EVENT_TEMPORARY_FAILURE = "temporary_failure"
THROTTLE_EVENT_PERMANENT_FAILURE = "permanent_failure"
THROTTLE_EVENT_CIRCUIT_OPENED = "circuit_opened"
THROTTLE_EVENT_RAMPED_UP = "ramped_up"
THROTTLE_EVENT_DECREASED = "decreased"
```

## Safe Beta Defaults

Add these defaults to `.env.server.example`:

```env
DEEPSEEK_ADAPTIVE_THROTTLING_ENABLED=true
DEEPSEEK_ADAPTIVE_INITIAL_PARALLEL=1
DEEPSEEK_ADAPTIVE_MIN_PARALLEL=1
DEEPSEEK_ADAPTIVE_SUCCESS_RAMP_INTERVAL=8
DEEPSEEK_ADAPTIVE_DECREASE_FACTOR=0.5
DEEPSEEK_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=5
DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS=120
DEEPSEEK_CHANNEL_COOLDOWN_JITTER_FRACTION=0.20
```

Recommended behavior:

- one key/capacity 1: stays serial and behaves like legacy path;
- many keys: starts at 1 active provider call per worker, ramps toward configured capacity after stable successes;
- 429/503/timeout: cool down affected channel, decrease provider adaptive limit, fail over if another channel is available;
- auth/billing: open provider circuit and expose operator-visible degraded state;
- admin key reload: new key pool starts with fresh throttle state.

---

## Task 1: Pure Adaptive Throttle Policy

**Files:**

- Create `src/translator_service/provider_throttle.py`
- Create `tests/test_provider_throttle.py`

- [x] **Step 1: Add failing tests for AIMD ramp/decrease**

Create `tests/test_provider_throttle.py`:

```python
import unittest

from translator_service.provider_throttle import (
    PROVIDER_CIRCUIT_CLOSED,
    PROVIDER_CIRCUIT_OPEN,
    ProviderAdaptiveThrottle,
    ProviderThrottleConfig,
)


class ProviderAdaptiveThrottleTest(unittest.TestCase):
    def test_starts_at_initial_limit_and_ramps_after_clean_successes(self):
        throttle = ProviderAdaptiveThrottle(
            ProviderThrottleConfig(
                enabled=True,
                initial_parallel=1,
                min_parallel=1,
                success_ramp_interval=2,
            )
        )

        self.assertEqual(throttle.snapshot(now=100.0, max_capacity=4).current_limit, 1)
        throttle.record_success(now=101.0, max_capacity=4)
        self.assertEqual(throttle.snapshot(now=101.0, max_capacity=4).current_limit, 1)
        throttle.record_success(now=102.0, max_capacity=4)

        snapshot = throttle.snapshot(now=102.0, max_capacity=4)
        self.assertEqual(snapshot.current_limit, 2)
        self.assertEqual(snapshot.total_ramp_ups, 1)
        self.assertEqual(snapshot.circuit_state, PROVIDER_CIRCUIT_CLOSED)

    def test_temporary_failure_decreases_limit_without_going_below_minimum(self):
        throttle = ProviderAdaptiveThrottle(
            ProviderThrottleConfig(
                enabled=True,
                initial_parallel=4,
                min_parallel=1,
                decrease_factor=0.5,
                success_ramp_interval=99,
            )
        )

        throttle.record_temporary_failure(now=100.0, max_capacity=8, reason="rate_limited")

        snapshot = throttle.snapshot(now=100.0, max_capacity=8)
        self.assertEqual(snapshot.current_limit, 2)
        self.assertEqual(snapshot.total_decreases, 1)
        self.assertEqual(snapshot.last_reason, "rate_limited")

    def test_repeated_temporary_failures_open_circuit(self):
        throttle = ProviderAdaptiveThrottle(
            ProviderThrottleConfig(
                enabled=True,
                initial_parallel=4,
                min_parallel=1,
                circuit_failure_threshold=2,
                circuit_reset_seconds=120.0,
            )
        )

        throttle.record_temporary_failure(now=100.0, max_capacity=4, reason="unavailable")
        throttle.record_temporary_failure(now=101.0, max_capacity=4, reason="unavailable")

        snapshot = throttle.snapshot(now=101.0, max_capacity=4)
        self.assertEqual(snapshot.circuit_state, PROVIDER_CIRCUIT_OPEN)
        self.assertEqual(snapshot.circuit_open_remaining_seconds, 120.0)
        self.assertEqual(snapshot.available_slots, 0)
```

- [x] **Step 2: Run tests and verify failure**

```bash
PYTHONPATH=src python3 -m unittest tests.test_provider_throttle
```

Expected: FAIL because `translator_service.provider_throttle` does not exist.

- [x] **Step 3: Implement policy module**

Create `src/translator_service/provider_throttle.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


PROVIDER_CIRCUIT_CLOSED = "closed"
PROVIDER_CIRCUIT_OPEN = "open"
PROVIDER_CIRCUIT_HALF_OPEN = "half_open"

THROTTLE_EVENT_SUCCESS = "success"
THROTTLE_EVENT_TEMPORARY_FAILURE = "temporary_failure"
THROTTLE_EVENT_PERMANENT_FAILURE = "permanent_failure"
THROTTLE_EVENT_CIRCUIT_OPENED = "circuit_opened"
THROTTLE_EVENT_RAMPED_UP = "ramped_up"
THROTTLE_EVENT_DECREASED = "decreased"


@dataclass(frozen=True)
class ProviderThrottleConfig:
    enabled: bool = True
    initial_parallel: int = 1
    min_parallel: int = 1
    success_ramp_interval: int = 8
    decrease_factor: float = 0.5
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: float = 120.0


@dataclass(frozen=True)
class ProviderThrottleSnapshot:
    enabled: bool
    current_limit: int
    max_capacity: int
    active_requests: int
    available_slots: int
    circuit_state: str
    circuit_open_remaining_seconds: float
    last_reason: str | None
    total_ramp_ups: int
    total_decreases: int
    total_circuit_opened: int


class ProviderAdaptiveThrottle:
    def __init__(self, config: ProviderThrottleConfig) -> None:
        self._config = config
        self._current_limit = max(
            max(1, config.min_parallel),
            max(1, config.initial_parallel),
        )
        self._active_requests = 0
        self._successes_since_ramp = 0
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._last_reason: str | None = None
        self._total_ramp_ups = 0
        self._total_decreases = 0
        self._total_circuit_opened = 0

    def can_start(self, *, now: float, max_capacity: int) -> bool:
        snapshot = self.snapshot(now=now, max_capacity=max_capacity)
        return snapshot.available_slots > 0

    def start_request(self, *, now: float, max_capacity: int) -> bool:
        if not self.can_start(now=now, max_capacity=max_capacity):
            return False
        self._active_requests += 1
        return True

    def finish_request(self) -> None:
        self._active_requests = max(0, self._active_requests - 1)

    def record_success(self, *, now: float, max_capacity: int) -> None:
        if not self._config.enabled:
            return
        self._last_reason = None
        self._consecutive_failures = 0
        self._successes_since_ramp += 1
        if self._circuit_state(now) == PROVIDER_CIRCUIT_HALF_OPEN:
            self._circuit_open_until = 0.0
        if self._successes_since_ramp < max(1, self._config.success_ramp_interval):
            return
        self._successes_since_ramp = 0
        capped_limit = min(max(1, max_capacity), self._current_limit + 1)
        if capped_limit > self._current_limit:
            self._current_limit = capped_limit
            self._total_ramp_ups += 1

    def record_temporary_failure(
        self,
        *,
        now: float,
        max_capacity: int,
        reason: str,
    ) -> None:
        self._last_reason = reason
        self._successes_since_ramp = 0
        self._consecutive_failures += 1
        self._decrease(max_capacity=max_capacity)
        if self._consecutive_failures >= max(1, self._config.circuit_failure_threshold):
            self._open_circuit(now=now, reason=reason)

    def record_permanent_failure(self, *, now: float, reason: str) -> None:
        self._last_reason = reason
        self._consecutive_failures += 1
        self._open_circuit(now=now, reason=reason)

    def snapshot(self, *, now: float, max_capacity: int) -> ProviderThrottleSnapshot:
        max_capacity = max(1, int(max_capacity))
        if not self._config.enabled:
            current_limit = max_capacity
            available_slots = max(0, max_capacity - self._active_requests)
            circuit_state = PROVIDER_CIRCUIT_CLOSED
            remaining = 0.0
        else:
            current_limit = min(max_capacity, max(1, self._current_limit))
            circuit_state = self._circuit_state(now)
            remaining = max(0.0, self._circuit_open_until - now)
            available_slots = (
                0
                if circuit_state == PROVIDER_CIRCUIT_OPEN
                else max(0, current_limit - self._active_requests)
            )
        return ProviderThrottleSnapshot(
            enabled=self._config.enabled,
            current_limit=current_limit,
            max_capacity=max_capacity,
            active_requests=self._active_requests,
            available_slots=available_slots,
            circuit_state=circuit_state,
            circuit_open_remaining_seconds=remaining,
            last_reason=self._last_reason,
            total_ramp_ups=self._total_ramp_ups,
            total_decreases=self._total_decreases,
            total_circuit_opened=self._total_circuit_opened,
        )

    def _decrease(self, *, max_capacity: int) -> None:
        minimum = max(1, self._config.min_parallel)
        decreased = int(max(1, self._current_limit) * self._config.decrease_factor)
        next_limit = min(max_capacity, max(minimum, decreased))
        if next_limit < self._current_limit:
            self._current_limit = next_limit
            self._total_decreases += 1

    def _open_circuit(self, *, now: float, reason: str) -> None:
        self._last_reason = reason
        self._circuit_open_until = max(
            self._circuit_open_until,
            now + max(0.0, self._config.circuit_reset_seconds),
        )
        self._total_circuit_opened += 1

    def _circuit_state(self, now: float) -> str:
        if self._circuit_open_until <= 0.0:
            return PROVIDER_CIRCUIT_CLOSED
        if now < self._circuit_open_until:
            return PROVIDER_CIRCUIT_OPEN
        return PROVIDER_CIRCUIT_HALF_OPEN
```

- [x] **Step 4: Verify policy tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_provider_throttle
```

Expected: OK.

- [x] **Step 5: Commit**

```bash
git add src/translator_service/provider_throttle.py tests/test_provider_throttle.py
git commit -m "feat: add provider adaptive throttle policy"
```

## Task 2: Runtime Env Defaults for Adaptive Throttling

**Files:**

- Modify `src/translator_service/bot/runtime.py`
- Modify `.env.server.example`
- Modify `tests/test_bot_runtime.py`
- Modify `tests/test_server_deployment_config.py`

- [x] **Step 1: Add failing env parsing tests**

Add to `tests/test_bot_runtime.py`:

```python
def test_deepseek_throttle_config_uses_safe_beta_defaults(self):
    from translator_service.bot.runtime import _deepseek_throttle_config_from_env

    with patch.dict("os.environ", {}, clear=True):
        config = _deepseek_throttle_config_from_env()

    self.assertTrue(config.enabled)
    self.assertEqual(config.initial_parallel, 1)
    self.assertEqual(config.min_parallel, 1)
    self.assertEqual(config.success_ramp_interval, 8)
    self.assertEqual(config.decrease_factor, 0.5)
    self.assertEqual(config.circuit_failure_threshold, 5)
    self.assertEqual(config.circuit_reset_seconds, 120.0)


def test_deepseek_throttle_config_can_be_disabled_for_legacy_behavior(self):
    from translator_service.bot.runtime import _deepseek_throttle_config_from_env

    with patch.dict(
        "os.environ",
        {
            "DEEPSEEK_ADAPTIVE_THROTTLING_ENABLED": "false",
            "DEEPSEEK_ADAPTIVE_INITIAL_PARALLEL": "3",
            "DEEPSEEK_ADAPTIVE_MIN_PARALLEL": "2",
            "DEEPSEEK_ADAPTIVE_SUCCESS_RAMP_INTERVAL": "4",
            "DEEPSEEK_ADAPTIVE_DECREASE_FACTOR": "0.75",
            "DEEPSEEK_PROVIDER_CIRCUIT_FAILURE_THRESHOLD": "7",
            "DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS": "60",
        },
        clear=True,
    ):
        config = _deepseek_throttle_config_from_env()

    self.assertFalse(config.enabled)
    self.assertEqual(config.initial_parallel, 3)
    self.assertEqual(config.min_parallel, 2)
    self.assertEqual(config.success_ramp_interval, 4)
    self.assertEqual(config.decrease_factor, 0.75)
    self.assertEqual(config.circuit_failure_threshold, 7)
    self.assertEqual(config.circuit_reset_seconds, 60.0)
```

Add to `tests/test_server_deployment_config.py`:

```python
def test_server_env_documents_adaptive_provider_throttling_defaults(self):
    env_text = Path(".env.server.example").read_text()

    self.assertIn("DEEPSEEK_ADAPTIVE_THROTTLING_ENABLED=true", env_text)
    self.assertIn("DEEPSEEK_ADAPTIVE_INITIAL_PARALLEL=1", env_text)
    self.assertIn("DEEPSEEK_ADAPTIVE_MIN_PARALLEL=1", env_text)
    self.assertIn("DEEPSEEK_ADAPTIVE_SUCCESS_RAMP_INTERVAL=8", env_text)
    self.assertIn("DEEPSEEK_ADAPTIVE_DECREASE_FACTOR=0.5", env_text)
    self.assertIn("DEEPSEEK_PROVIDER_CIRCUIT_FAILURE_THRESHOLD=5", env_text)
    self.assertIn("DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS=120", env_text)
    self.assertIn("DEEPSEEK_CHANNEL_COOLDOWN_JITTER_FRACTION=0.20", env_text)
```

- [x] **Step 2: Implement env parser**

In `src/translator_service/bot/runtime.py`, import `ProviderThrottleConfig` and add:

```python
from translator_service.provider_throttle import ProviderThrottleConfig
```

Add near the existing DeepSeek env helpers:

```python
def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _deepseek_throttle_config_from_env() -> ProviderThrottleConfig:
    return ProviderThrottleConfig(
        enabled=_env_bool("DEEPSEEK_ADAPTIVE_THROTTLING_ENABLED", True),
        initial_parallel=max(
            1,
            _env_int("DEEPSEEK_ADAPTIVE_INITIAL_PARALLEL", 1),
        ),
        min_parallel=max(
            1,
            _env_int("DEEPSEEK_ADAPTIVE_MIN_PARALLEL", 1),
        ),
        success_ramp_interval=max(
            1,
            _env_int("DEEPSEEK_ADAPTIVE_SUCCESS_RAMP_INTERVAL", 8),
        ),
        decrease_factor=min(
            0.95,
            max(0.1, _env_float("DEEPSEEK_ADAPTIVE_DECREASE_FACTOR", 0.5)),
        ),
        circuit_failure_threshold=max(
            1,
            _env_int("DEEPSEEK_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 5),
        ),
        circuit_reset_seconds=max(
            1.0,
            _env_float("DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS", 120.0),
        ),
    )
```

- [x] **Step 3: Document env defaults**

Add the safe beta defaults from this plan to `.env.server.example` near provider channel safety.

- [x] **Step 4: Verify**

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime tests.test_server_deployment_config
```

Expected: OK.

- [x] **Step 5: Commit**

```bash
git add src/translator_service/bot/runtime.py .env.server.example tests/test_bot_runtime.py tests/test_server_deployment_config.py
git commit -m "feat: configure deepseek adaptive throttling"
```

## Task 3: Integrate Adaptive Gate and Cooldown Jitter in Key Pool

**Files:**

- Modify `src/translator_service/deepseek_key_pool.py`
- Modify `tests/test_deepseek_key_pool.py`

- [x] **Step 1: Add failing pool tests**

Add tests:

```python
def test_adaptive_throttle_limits_concurrent_provider_starts(self):
    barrier = threading.Barrier(2)
    factory = BlockingClientFactory(barrier=barrier)
    pool = DeepSeekKeyPoolTranslator(
        channels=[
            DeepSeekChannelConfig(api_key="key-a", label="a"),
            DeepSeekChannelConfig(api_key="key-b", label="b"),
        ],
        client_factory=factory,
        throttle_config=ProviderThrottleConfig(
            enabled=True,
            initial_parallel=1,
            min_parallel=1,
            success_ramp_interval=99,
        ),
    )

    first = threading.Thread(
        target=lambda: pool.translate(text="one", source_language="en", target_language="uk")
    )
    first.start()
    barrier.wait(timeout=1.0)

    self.assertEqual(pool.available_parallel_slots(), 0)
    self.assertEqual(pool.provider_snapshot().current_limit, 1)
    first.join(timeout=1.0)


def test_provider_circuit_opens_after_repeated_temporary_failures(self):
    now = FakeClock(100.0)
    factory = RecordingClientFactory(
        {
            "key-a": [DeepSeekApiError("DeepSeek API returned HTTP 503: unavailable")],
            "key-b": [DeepSeekApiError("DeepSeek API returned HTTP 503: unavailable")],
        }
    )
    pool = DeepSeekKeyPoolTranslator(
        channels=[
            DeepSeekChannelConfig(api_key="key-a", label="a"),
            DeepSeekChannelConfig(api_key="key-b", label="b"),
        ],
        client_factory=factory,
        throttle_config=ProviderThrottleConfig(
            enabled=True,
            initial_parallel=2,
            circuit_failure_threshold=2,
            circuit_reset_seconds=60.0,
        ),
        cooldown_seconds=1,
        clock=now,
    )

    with self.assertRaises(DeepSeekApiError):
        pool.translate(text="source", source_language="en", target_language="uk")

    snapshot = pool.provider_snapshot()
    self.assertEqual(snapshot.circuit_state, "open")
    self.assertEqual(snapshot.available_slots, 0)
    self.assertIn("unavailable", snapshot.last_reason or "")
```

- [x] **Step 2: Run focused tests and verify failure**

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool
```

Expected: FAIL because `throttle_config`, `provider_snapshot()` and `available_parallel_slots()` do not exist.

- [x] **Step 3: Extend key pool constructor and snapshots**

In `src/translator_service/deepseek_key_pool.py`:

```python
from translator_service.provider_throttle import (
    ProviderAdaptiveThrottle,
    ProviderThrottleConfig,
    ProviderThrottleSnapshot,
)
```

Extend `DeepSeekKeyPoolTranslator.__init__`:

```python
        throttle_config: ProviderThrottleConfig | None = None,
        cooldown_jitter_fraction: float = 0.0,
```

Set:

```python
        self._throttle = ProviderAdaptiveThrottle(
            throttle_config or ProviderThrottleConfig(enabled=False)
        )
        self._cooldown_jitter_fraction = max(0.0, min(1.0, cooldown_jitter_fraction))
```

Add methods:

```python
    def provider_snapshot(self) -> ProviderThrottleSnapshot:
        with self._condition:
            return self._throttle.snapshot(
                now=self._clock(),
                max_capacity=self._configured_capacity(),
            )

    def available_parallel_slots(self) -> int:
        with self._condition:
            snapshot = self._throttle.snapshot(
                now=self._clock(),
                max_capacity=self._configured_capacity(),
            )
            channel_slots = sum(
                max(0, channel.capacity - channel.active_requests)
                for channel in self._channels
                if channel.cooldown_until <= self._clock()
            )
            return min(snapshot.available_slots, channel_slots)

    def _configured_capacity(self) -> int:
        return max(1, sum(channel.capacity for channel in self._channels))
```

- [x] **Step 4: Gate acquire/release with throttle**

Inside `_acquire_channel`, before choosing candidates, only consider a start when throttle allows it:

```python
                if not self._throttle.start_request(
                    now=now,
                    max_capacity=self._configured_capacity(),
                ):
                    self._condition.wait(timeout=0.05)
                    continue
```

If a channel candidate cannot be found after taking a throttle slot, immediately release it:

```python
                if not candidates:
                    self._throttle.finish_request()
                    self._condition.wait(timeout=wait_for)
                    continue
```

Inside `_release_channel`, add:

```python
            self._throttle.finish_request()
```

- [x] **Step 5: Record success/failure events**

After channel success:

```python
            self._throttle.record_success(
                now=now,
                max_capacity=self._configured_capacity(),
            )
```

After temporary failure:

```python
            self._throttle.record_temporary_failure(
                now=now,
                max_capacity=self._configured_capacity(),
                reason=error_kind,
            )
```

After permanent auth/billing failure:

```python
            if error_kind in {PROVIDER_ERROR_AUTH, PROVIDER_ERROR_BILLING}:
                self._throttle.record_permanent_failure(now=now, reason=error_kind)
```

- [x] **Step 6: Add cooldown jitter**

Change `_channel_cooldown_seconds()` to accept a jitter fraction and optional deterministic random source if tests need one. Minimal implementation:

```python
def _apply_cooldown_jitter(seconds: float, *, fraction: float, random_value: float) -> float:
    fraction = max(0.0, min(1.0, fraction))
    if fraction <= 0.0 or seconds <= 0.0:
        return seconds
    delta = seconds * fraction
    return max(0.0, seconds - delta + (2 * delta * random_value))
```

Use it before setting `cooldown_until`. Tests should inject a deterministic `random_value` source rather than relying on global randomness.

- [x] **Step 7: Verify key pool tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool tests.test_provider_throttle
```

Expected: OK.

- [x] **Step 8: Commit**

```bash
git add src/translator_service/deepseek_key_pool.py tests/test_deepseek_key_pool.py
git commit -m "feat: gate deepseek pool with adaptive throttle"
```

## Task 4: Persist Provider-Level Runtime State

**Files:**

- Modify `src/translator_service/admin/provider_runtime.py`
- Modify `tests/test_ai_provider_runtime.py`

- [x] **Step 1: Add failing runtime store test**

Add:

```python
def test_runtime_status_roundtrips_provider_state(self):
    with SQLiteAIProviderRuntimeStore(":memory:") as store:
        store.record_status(
            provider_id="deepseek",
            source="bot_runtime",
            status="degraded",
            reload_interval_seconds=30.0,
            active_channels=(),
            provider_state=AIProviderRuntimeProviderState(
                adaptive_enabled=True,
                current_limit=1,
                max_capacity=4,
                active_requests=0,
                available_slots=1,
                circuit_state="open",
                circuit_open_remaining_seconds=42.0,
                last_reason="billing",
                total_ramp_ups=2,
                total_decreases=3,
                total_circuit_opened=1,
            ),
            error=None,
        )

        status = store.get_status("deepseek")

    self.assertIsNotNone(status)
    self.assertEqual(status.provider_state.circuit_state, "open")
    self.assertEqual(status.provider_state.current_limit, 1)
    self.assertEqual(status.provider_state.last_reason, "billing")
```

- [x] **Step 2: Implement dataclass and schema migration**

In `provider_runtime.py`:

```python
@dataclass(frozen=True)
class AIProviderRuntimeProviderState:
    adaptive_enabled: bool = False
    current_limit: int = 1
    max_capacity: int = 1
    active_requests: int = 0
    available_slots: int = 1
    circuit_state: str = "closed"
    circuit_open_remaining_seconds: float = 0.0
    last_reason: str | None = None
    total_ramp_ups: int = 0
    total_decreases: int = 0
    total_circuit_opened: int = 0
```

Extend `AIProviderRuntimeStatus`:

```python
    provider_state: AIProviderRuntimeProviderState = AIProviderRuntimeProviderState()
```

Add `provider_state_json TEXT NOT NULL DEFAULT '{}'` to the table. In `_create_schema()`, run a defensive migration:

```python
columns = {
    row["name"]
    for row in self._connection.execute(
        "PRAGMA table_info(admin_ai_provider_runtime_status)"
    )
}
if "provider_state_json" not in columns:
    self._connection.execute(
        "ALTER TABLE admin_ai_provider_runtime_status "
        "ADD COLUMN provider_state_json TEXT NOT NULL DEFAULT '{}'"
    )
```

- [x] **Step 3: Extend record/get parsing**

Add `provider_state` keyword to `record_status()` with default:

```python
        provider_state: AIProviderRuntimeProviderState | None = None,
```

Store JSON:

```python
provider_state_payload = json.dumps(
    _provider_state_payload(provider_state or AIProviderRuntimeProviderState()),
    sort_keys=True,
)
```

Parse legacy rows using defaults:

```python
def _provider_state_from_payload(value: object) -> AIProviderRuntimeProviderState:
    payload = value if isinstance(value, dict) else {}
    return AIProviderRuntimeProviderState(
        adaptive_enabled=bool(payload.get("adaptive_enabled", False)),
        current_limit=_int_at_least(payload.get("current_limit", 1), minimum=1, default=1),
        max_capacity=_int_at_least(payload.get("max_capacity", 1), minimum=1, default=1),
        active_requests=_int_at_least(payload.get("active_requests", 0), minimum=0, default=0),
        available_slots=_int_at_least(payload.get("available_slots", 1), minimum=0, default=1),
        circuit_state=_string_or_default(payload.get("circuit_state", "closed"), "closed"),
        circuit_open_remaining_seconds=_float_at_least(payload.get("circuit_open_remaining_seconds", 0.0), minimum=0.0, default=0.0),
        last_reason=_optional_string(payload.get("last_reason")),
        total_ramp_ups=_int_at_least(payload.get("total_ramp_ups", 0), minimum=0, default=0),
        total_decreases=_int_at_least(payload.get("total_decreases", 0), minimum=0, default=0),
        total_circuit_opened=_int_at_least(payload.get("total_circuit_opened", 0), minimum=0, default=0),
    )
```

- [x] **Step 4: Verify runtime tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_ai_provider_runtime
```

Expected: OK.

- [x] **Step 5: Commit**

```bash
git add src/translator_service/admin/provider_runtime.py tests/test_ai_provider_runtime.py
git commit -m "feat: persist provider adaptive runtime state"
```

## Task 5: Record Provider Snapshot From Bot Runtime

**Files:**

- Modify `src/translator_service/bot/runtime.py`
- Modify `tests/test_bot_runtime.py`

- [x] **Step 1: Add failing runtime snapshot test**

Extend existing reloadable translator runtime telemetry tests:

```python
def test_reloadable_translator_records_provider_adaptive_state(self):
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "admin.sqlite3"
        settings = Settings(admin_db_path=str(db_path), admin_provider_runtime_reload_seconds=999.0)
        with SQLiteAIProviderKeyStore(db_path, master_key=TEST_MASTER_KEY) as keys:
            keys.upsert_key(
                provider_id="deepseek",
                label="main",
                plaintext="sk-main-secret",
                enabled=True,
                weight=1,
                max_parallel_requests=2,
            )

        translator = ReloadableDeepSeekTranslator(settings, clock=FakeClock(100.0))
        translator.snapshot()

        with SQLiteAIProviderRuntimeStore(db_path) as runtime:
            status = runtime.get_status("deepseek")

    self.assertIsNotNone(status)
    self.assertTrue(status.provider_state.adaptive_enabled)
    self.assertEqual(status.provider_state.current_limit, 1)
    self.assertEqual(status.provider_state.max_capacity, 2)
    self.assertEqual(status.provider_state.circuit_state, "closed")
```

- [x] **Step 2: Pass throttle config into key pool**

In `_deepseek_translator_from_channels()`, pass:

```python
        throttle_config=_deepseek_throttle_config_from_env(),
        cooldown_jitter_fraction=_env_float(
            "DEEPSEEK_CHANNEL_COOLDOWN_JITTER_FRACTION",
            0.20,
        ),
```

- [x] **Step 3: Convert provider snapshot**

Add helper:

```python
def _runtime_provider_state_from_snapshot(snapshot) -> AIProviderRuntimeProviderState:
    return AIProviderRuntimeProviderState(
        adaptive_enabled=snapshot.enabled,
        current_limit=snapshot.current_limit,
        max_capacity=snapshot.max_capacity,
        active_requests=snapshot.active_requests,
        available_slots=snapshot.available_slots,
        circuit_state=snapshot.circuit_state,
        circuit_open_remaining_seconds=snapshot.circuit_open_remaining_seconds,
        last_reason=snapshot.last_reason,
        total_ramp_ups=snapshot.total_ramp_ups,
        total_decreases=snapshot.total_decreases,
        total_circuit_opened=snapshot.total_circuit_opened,
    )
```

When recording runtime snapshots, call `provider_snapshot()` if available and pass `provider_state=` into `_record_deepseek_runtime_status()`.

- [x] **Step 4: Verify bot runtime tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_bot_runtime tests.test_ai_provider_runtime
```

Expected: OK.

- [x] **Step 5: Commit**

```bash
git add src/translator_service/bot/runtime.py tests/test_bot_runtime.py
git commit -m "feat: record provider adaptive runtime state"
```

## Task 6: Scheduler Runner Uses Provider Capacity Hint

**Files:**

- Modify `src/translator_service/scheduler_runner.py`
- Modify `tests/test_scheduler_runner.py`

- [x] **Step 1: Add failing no-claim test**

Add a fake translator with zero current capacity and assert no claim is made:

```python
class CapacityHintTranslator:
    last_usage = None

    def __init__(self, slots: int) -> None:
        self.slots = slots
        self.calls = 0

    def available_parallel_slots(self) -> int:
        return self.slots

    def translate(self, *, text, source_language, target_language, context=None):
        self.calls += 1
        return "translated"


def test_parallel_scheduler_does_not_claim_when_provider_capacity_is_zero(self):
    store, storage, job_id = _store_with_pending_units(count=2)
    translator = CapacityHintTranslator(slots=0)

    summary = run_scheduler_once(
        store=store,
        storage=storage,
        worker_id="worker",
        translator=translator,
        limits=SchedulerLimits(max_active_units_global=2),
        lease_seconds=60,
        max_parallel_units=2,
    )

    self.assertEqual(summary.completed_units, 0)
    self.assertEqual(translator.calls, 0)
    self.assertEqual(
        [unit.status.value for unit in store.list_work_units(job_id)],
        ["scheduled", "scheduled"],
    )
```

- [x] **Step 2: Implement capacity helper**

In `scheduler_runner.py`:

```python
def _translator_available_parallel_slots(translator: PersistentWorkUnitTranslator) -> int | None:
    available = getattr(translator, "available_parallel_slots", None)
    if available is None:
        return None
    return max(0, int(available()))
```

Inside `_run_scheduled_parallel_once`, before claiming:

```python
            hinted_slots = _translator_available_parallel_slots(translator)
            claim_capacity = capacity if hinted_slots is None else min(capacity, len(active) + hinted_slots)
            while len(active) < claim_capacity:
                ...
```

If `hinted_slots == 0` and no active futures exist, break the loop without claiming.

- [x] **Step 3: Verify scheduler runner tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_scheduler_runner
```

Expected: OK.

- [x] **Step 4: Commit**

```bash
git add src/translator_service/scheduler_runner.py tests/test_scheduler_runner.py
git commit -m "feat: avoid scheduler claims when provider is throttled"
```

## Task 7: Admin Health, API and Live Monitor Visibility

**Files:**

- Modify `src/translator_service/admin/provider_health.py`
- Modify `src/translator_service/admin/routes.py`
- Modify `src/translator_service/admin/views.py`
- Modify `tests/test_admin_provider_health.py`
- Modify `tests/test_admin_routes.py`
- Modify `tests/test_admin_live_monitor.py`

- [x] **Step 1: Add failing admin tests**

Add provider health test:

```python
def test_open_provider_circuit_degrades_provider_health(self):
    runtime = AIProviderRuntimeStatus(
        provider_id="deepseek",
        source="bot_runtime",
        status="ok",
        reload_interval_seconds=30.0,
        last_reloaded_at=datetime(2026, 5, 10, tzinfo=UTC),
        active_channels=(),
        provider_state=AIProviderRuntimeProviderState(
            adaptive_enabled=True,
            current_limit=1,
            max_capacity=4,
            available_slots=0,
            circuit_state="open",
            circuit_open_remaining_seconds=90.0,
            last_reason="billing sk-secret",
        ),
    )

    health = build_provider_health(
        (_provider(),),
        {"deepseek": (_key(),)},
        runtime_statuses=(runtime,),
    )

    self.assertEqual(health[0].status, "degraded")
    self.assertIn("circuit", health[0].last_error_excerpt)
    self.assertNotIn("sk-secret", health[0].last_error_excerpt)
```

Extend route/API tests to assert JSON:

```python
self.assertEqual(payload["providers"][0]["provider_state"]["circuit_state"], "open")
self.assertEqual(payload["providers"][0]["provider_state"]["current_limit"], 1)
self.assertIn("Circuit", page.text)
self.assertIn("open", page.text)
self.assertNotIn("sk-runtime-secret", page.text)
```

- [x] **Step 2: Degrade provider health from provider state**

In `provider_health.py`, extend runtime degradation:

```python
if runtime.provider_state.circuit_state.lower() in {"open", "half_open"}:
    return True
```

Extend runtime error excerpt:

```python
state = runtime.provider_state
if state.circuit_state.lower() != "closed":
    summaries.append(
        f"provider circuit {state.circuit_state}; reason {state.last_reason or 'n/a'}"
    )
```

- [x] **Step 3: Extend runtime API payload**

In `routes.py`:

```python
def _ai_provider_runtime_provider_state_payload(state):
    return {
        "adaptive_enabled": state.adaptive_enabled,
        "current_limit": state.current_limit,
        "max_capacity": state.max_capacity,
        "active_requests": state.active_requests,
        "available_slots": state.available_slots,
        "circuit_state": _safe_runtime_text(state.circuit_state),
        "circuit_open_remaining_seconds": state.circuit_open_remaining_seconds,
        "last_reason": _safe_runtime_text(state.last_reason),
        "total_ramp_ups": state.total_ramp_ups,
        "total_decreases": state.total_decreases,
        "total_circuit_opened": state.total_circuit_opened,
    }
```

Include it in `_ai_provider_runtime_payload()`.

- [x] **Step 4: Render adaptive/circuit state**

In `views.py`, add a small provider runtime state row above channel rows:

```python
def _runtime_provider_state_row(state: AIProviderRuntimeProviderState) -> str:
    return f"""
          <div class="key-row">
            <div>
              <strong>Adaptive throttle</strong>
              <span>circuit {escape(_safe_runtime_text(state.circuit_state))}</span>
              <span>reason {escape(_safe_runtime_text(state.last_reason))}</span>
            </div>
            <span>limit {state.current_limit}/{state.max_capacity}</span>
            <span>available {state.available_slots}</span>
            <span>open for {escape(_format_seconds(state.circuit_open_remaining_seconds))}</span>
            <span>ramp/decrease/open {state.total_ramp_ups}/{state.total_decreases}/{state.total_circuit_opened}</span>
          </div>
    """
```

Live Monitor cards should include:

- `Adaptive limit`
- `Provider circuit`
- `Available provider slots`

- [x] **Step 5: Verify admin tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_admin_provider_health tests.test_admin_routes tests.test_admin_live_monitor
```

Expected: OK.

- [x] **Step 6: Commit**

```bash
git add src/translator_service/admin/provider_health.py src/translator_service/admin/routes.py src/translator_service/admin/views.py tests/test_admin_provider_health.py tests/test_admin_routes.py tests/test_admin_live_monitor.py
git commit -m "feat: show provider adaptive throttle in admin"
```

## Task 8: Documentation and Deployment Defaults

**Files:**

- Modify `.env.server.example`
- Modify `README.md`
- Modify `README.project.md`
- Modify `docs/deployment/admin-vps-runbook.md`
- Modify `CURRENT_PROJECT_STATE.md`
- Modify `DOCUMENT_INDEX.md`
- Modify `tests/test_server_deployment_config.py`

- [x] **Step 1: Document operational semantics**

Add to README files near worker/provider concurrency:

```markdown
Phase 3 adaptive provider throttling starts each runtime conservatively and
ramps DeepSeek concurrency after clean successes. 429/503/timeouts decrease the
local adaptive limit and cool down affected channels; auth/billing failures open
a provider circuit for the configured reset window. This is local per worker,
not a distributed global quota system.
```

- [x] **Step 2: Document VPS runbook actions**

Add to `docs/deployment/admin-vps-runbook.md`:

```markdown
If `/admin/ai-providers` shows an open provider circuit, do not raise
`TRANSLATION_MAX_PARALLEL_UNITS` as a first response. Check the redacted reason,
DeepSeek balance/auth state, per-channel 429/503/timeout counters and cooldowns.
The circuit should half-open after `DEEPSEEK_PROVIDER_CIRCUIT_RESET_SECONDS`.
Use runtime reload after fixing keys or balance.
```

- [x] **Step 3: Update current state and index**

In `CURRENT_PROJECT_STATE.md`, after implementation, add Phase 3 verification results.

In `DOCUMENT_INDEX.md`, add this plan under Active Backend / Safety References.

- [x] **Step 4: Verify docs/config tests**

```bash
PYTHONPATH=src python3 -m unittest tests.test_server_deployment_config
```

Expected: OK.

- [x] **Step 5: Commit**

```bash
git add .env.server.example README.md README.project.md docs/deployment/admin-vps-runbook.md CURRENT_PROJECT_STATE.md DOCUMENT_INDEX.md tests/test_server_deployment_config.py
git commit -m "docs: document adaptive provider throttling"
```

## Task 9: Full Verification

**Files:**

- No code files unless fixing issues found by verification.

- [x] **Step 1: Run Phase 3 targeted suite**

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_provider_throttle \
  tests.test_deepseek_key_pool \
  tests.test_ai_provider_runtime \
  tests.test_bot_runtime \
  tests.test_scheduler_runner \
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

Expected: OK.

- [x] **Step 3: Compile**

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: OK.

- [x] **Step 4: Predeploy**

```bash
scripts/predeploy_check.sh
```

Expected: `Predeploy check passed.`

- [x] **Step 5: Docker/Postgres scheduler integration**

```bash
docker compose up -d postgres
docker compose run --rm --no-deps \
  -v "$PWD:/workspace" \
  -w /workspace \
  -e TEST_POSTGRES_DSN=postgresql://translator:translator@postgres:5432/translator \
  -e PYTHONPATH=src \
  api python -m unittest tests.test_postgres_scheduler
```

Expected: OK.

- [x] **Step 6: Diff hygiene**

```bash
git diff --check
```

Expected: no output.

- [x] **Step 7: Final commit if verification fixes were needed**

```bash
git status --short
git add <changed-files>
git commit -m "test: verify adaptive provider throttling"
```

Only run this commit step if verification required follow-up edits.

## Acceptance Criteria

- Provider calls start conservatively and ramp only after stable successes.
- 429/503/timeout reduce local provider concurrency and continue failover when healthy channels exist.
- Auth/billing errors open a provider circuit and avoid new claims while circuit capacity is zero.
- Scheduler runner does not claim fresh work units when the translator reports zero provider slots.
- Admin AI Providers and Live Monitor show adaptive limit, available slots, circuit state, cooldowns and redacted reasons.
- Runtime API includes provider adaptive state without secrets or raw document text.
- Capacity=1 legacy behavior remains serial and test-covered.
- Redis remains optional for scheduler correctness.
- All Phase 3, scheduler, predeploy and Docker/Postgres checks pass.

## Risks and Tradeoffs

- Local per-worker AIMD does not perfectly coordinate across multiple worker containers. It is still safer than static max concurrency and avoids adding distributed correctness dependencies in beta.
- Scheduler capacity hints are advisory. A provider can degrade between claim and translate; leases/retries still provide correctness.
- Circuit breaker reset is time-based and local. Admin reload creates a fresh runtime/key pool after key/balance changes.
- Aggressive defaults can starve throughput, so beta defaults intentionally start at 1 and ramp slowly.

## Follow-Up Phases

- Phase 4: cost/token-budget-aware scheduling, per-user quota accounting and admin kill switch.
- Later: optional distributed provider capacity coordination if multiple worker replicas become common.
