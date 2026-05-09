# API Channel Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a managed DeepSeek API channel pool with safe configuration, channel state snapshots, weighted capacity-aware selection, backoff, and diagnostics.

**Architecture:** Keep `DeepSeekKeyPoolTranslator` as the public translator wrapper and make channel behavior explicit inside `src/translator_service/deepseek_key_pool.py`. The bot runtime remains the environment configuration boundary, while tests verify pool behavior without touching real DeepSeek APIs.

**Tech Stack:** Python dataclasses, `threading.Condition`, existing `unittest` suite, existing DeepSeek client protocol.

---

## File Map

- Modify `src/translator_service/deepseek_key_pool.py`: add channel config fields, immutable snapshot dataclass, counters, selection scoring, failure recording, exponential cooldown, and redacted diagnostics.
- Modify `src/translator_service/bot/runtime.py`: parse channel weights and max cooldown from environment, then pass them into the pool.
- Modify `tests/test_deepseek_key_pool.py`: add focused unit tests for snapshots, errors, cooldown, selection, and usage behavior.
- Modify `tests/test_bot_runtime.py`: add runtime configuration tests for deduped keys, weights, and max cooldown.
- Modify `README.md`: document multi-key local configuration.

## Task 1: Channel Snapshot Model

**Files:**
- Modify: `src/translator_service/deepseek_key_pool.py`
- Test: `tests/test_deepseek_key_pool.py`

- [ ] **Step 1: Write the failing snapshot test**

Add `DeepSeekChannelSnapshot` to the imports and insert this test in `DeepSeekKeyPoolTranslatorTest` after `test_fails_over_to_next_channel_and_cools_down_rate_limited_channel`:

```python
    def test_snapshot_exposes_channel_state_without_api_keys(self):
        factory = RecordingClientFactory({"secret-key-a": ["ok"]})
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(
                    api_key="secret-key-a",
                    label="primary",
                    max_parallel_requests=2,
                    weight=3,
                )
            ],
            client_factory=factory,
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )

        snapshot = pool.snapshot()

        self.assertEqual(len(snapshot), 1)
        self.assertIsInstance(snapshot[0], DeepSeekChannelSnapshot)
        self.assertEqual(snapshot[0].label, "primary")
        self.assertEqual(snapshot[0].max_parallel_requests, 2)
        self.assertEqual(snapshot[0].weight, 3)
        self.assertEqual(snapshot[0].active_requests, 0)
        self.assertEqual(snapshot[0].total_started_requests, 0)
        self.assertEqual(snapshot[0].total_successful_requests, 0)
        self.assertEqual(snapshot[0].total_temporary_failures, 0)
        self.assertEqual(snapshot[0].total_permanent_failures, 0)
        self.assertIsNone(snapshot[0].last_error)
        self.assertNotIn("secret-key-a", repr(snapshot[0]))
```

- [ ] **Step 2: Run the failing snapshot test**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_snapshot_exposes_channel_state_without_api_keys
```

Expected: FAIL because `DeepSeekChannelSnapshot`, `weight`, and `snapshot()` do not exist.

- [ ] **Step 3: Add config and snapshot dataclasses**

In `src/translator_service/deepseek_key_pool.py`, replace the current `DeepSeekChannelConfig` and `_DeepSeekChannel` dataclasses with this shape:

```python
@dataclass(frozen=True)
class DeepSeekChannelConfig:
    api_key: str
    label: str | None = None
    max_parallel_requests: int = 1
    weight: int = 1
    cooldown_seconds: float | None = None
    max_cooldown_seconds: float | None = None


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


@dataclass
class _DeepSeekChannel:
    config: DeepSeekChannelConfig
    client: _PooledClient
    active_requests: int = 0
    cooldown_until: float = 0.0
    total_started_requests: int = 0
    total_successful_requests: int = 0
    total_temporary_failures: int = 0
    total_permanent_failures: int = 0
    consecutive_temporary_failures: int = 0
    last_selected_at: float | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error: str | None = None

    @property
    def label(self) -> str:
        return self.config.label or f"key-{abs(hash(self.config.api_key)) % 10_000}"

    @property
    def capacity(self) -> int:
        return max(1, self.config.max_parallel_requests)

    @property
    def weight(self) -> int:
        return max(1, self.config.weight)

    def snapshot(self) -> DeepSeekChannelSnapshot:
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
        )
```

Add this method to `DeepSeekKeyPoolTranslator` after `last_usage`:

```python
    def snapshot(self) -> list[DeepSeekChannelSnapshot]:
        with self._condition:
            return [channel.snapshot() for channel in self._channels]
```

- [ ] **Step 4: Run the snapshot test to verify it passes**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_snapshot_exposes_channel_state_without_api_keys
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add src/translator_service/deepseek_key_pool.py tests/test_deepseek_key_pool.py
git commit -m "feat: expose deepseek channel snapshots"
```

## Task 2: Request Counters and Permanent Error Recording

**Files:**
- Modify: `src/translator_service/deepseek_key_pool.py`
- Test: `tests/test_deepseek_key_pool.py`

- [ ] **Step 1: Write failing tests for success and permanent errors**

Insert these tests in `DeepSeekKeyPoolTranslatorTest` after the snapshot test:

```python
    def test_snapshot_tracks_successful_request_counters(self):
        factory = RecordingClientFactory({"key-a": ["ok"]})
        pool = DeepSeekKeyPoolTranslator(
            channels=[DeepSeekChannelConfig(api_key="key-a", label="a")],
            client_factory=factory,
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )

        result = pool.translate(text="source", source_language="en", target_language="uk")

        snapshot = pool.snapshot()[0]
        self.assertEqual(result, "ok")
        self.assertEqual(snapshot.total_started_requests, 1)
        self.assertEqual(snapshot.total_successful_requests, 1)
        self.assertEqual(snapshot.total_temporary_failures, 0)
        self.assertEqual(snapshot.total_permanent_failures, 0)
        self.assertEqual(snapshot.consecutive_temporary_failures, 0)
        self.assertEqual(snapshot.last_selected_at, 100.0)
        self.assertEqual(snapshot.last_success_at, 100.0)
        self.assertIsNone(snapshot.last_error)

    def test_permanent_error_is_recorded_and_not_replayed_on_other_channels(self):
        factory = RecordingClientFactory(
            {
                "key-a": [DeepSeekApiError("DeepSeek API returned HTTP 400: bad request for key-a")],
                "key-b": ["should-not-run"],
            }
        )
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a"),
                DeepSeekChannelConfig(api_key="key-b", label="b"),
            ],
            client_factory=factory,
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )

        with self.assertRaisesRegex(DeepSeekApiError, "HTTP 400"):
            pool.translate(text="source", source_language="en", target_language="uk")

        first, second = pool.snapshot()
        self.assertEqual(factory.calls, [("key-a", "source")])
        self.assertEqual(first.total_started_requests, 1)
        self.assertEqual(first.total_permanent_failures, 1)
        self.assertEqual(first.total_temporary_failures, 0)
        self.assertEqual(first.last_failure_at, 100.0)
        self.assertIn("HTTP 400", first.last_error or "")
        self.assertNotIn("key-a", first.last_error or "")
        self.assertEqual(second.total_started_requests, 0)
```

- [ ] **Step 2: Run the failing counter tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_snapshot_tracks_successful_request_counters \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_permanent_error_is_recorded_and_not_replayed_on_other_channels
```

Expected: FAIL because counters and permanent error recording are not updated.

- [ ] **Step 3: Add request state recording helpers**

In `DeepSeekKeyPoolTranslator.translate`, replace the current success and non-cooldown error branches with helper calls:

```python
                self._record_channel_success(channel)
                self._last_usage.value = getattr(channel.client, "last_usage", None)
                return translated
            except DeepSeekApiError as error:
                if not _is_channel_cooldown_error(error):
                    self._record_channel_permanent_failure(channel, error)
                    raise
                last_rate_error = error
                self._cool_down_channel(channel, error)
```

In `_acquire_channel`, before returning the channel, record selection state:

```python
                    channel.active_requests += 1
                    channel.total_started_requests += 1
                    channel.last_selected_at = now
                    channel.last_error = None
                    return channel
```

Add these methods before the existing `_cool_down_channel` method:

```python
    def _record_channel_success(self, channel: _DeepSeekChannel) -> None:
        with self._condition:
            now = self._clock()
            channel.total_successful_requests += 1
            channel.consecutive_temporary_failures = 0
            channel.last_success_at = now
            channel.last_error = None
            self._condition.notify_all()

    def _record_channel_permanent_failure(
        self,
        channel: _DeepSeekChannel,
        error: DeepSeekApiError,
    ) -> None:
        with self._condition:
            channel.total_permanent_failures += 1
            channel.last_failure_at = self._clock()
            channel.last_error = _redact_channel_error(error, channel)
            self._condition.notify_all()
```

Add this helper near `_is_channel_cooldown_error`:

```python
def _redact_channel_error(error: DeepSeekApiError, channel: _DeepSeekChannel) -> str:
    message = str(error).replace(channel.config.api_key, "[redacted-api-key]")
    if len(message) > 300:
        return f"{message[:297]}..."
    return message
```

- [ ] **Step 4: Run the counter tests to verify they pass**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_snapshot_tracks_successful_request_counters \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_permanent_error_is_recorded_and_not_replayed_on_other_channels
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add src/translator_service/deepseek_key_pool.py tests/test_deepseek_key_pool.py
git commit -m "feat: record deepseek channel outcomes"
```

## Task 3: Temporary Failure Backoff

**Files:**
- Modify: `src/translator_service/deepseek_key_pool.py`
- Test: `tests/test_deepseek_key_pool.py`

- [ ] **Step 1: Write failing tests for temporary errors and backoff**

Insert these tests in `DeepSeekKeyPoolTranslatorTest` after the permanent error test:

```python
    def test_temporary_error_records_cooldown_and_fails_over(self):
        factory = RecordingClientFactory(
            {
                "key-a": [DeepSeekApiError("DeepSeek API returned HTTP 429: key-a busy")],
                "key-b": ["ok"],
            }
        )
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a"),
                DeepSeekChannelConfig(api_key="key-b", label="b"),
            ],
            client_factory=factory,
            cooldown_seconds=30,
            max_cooldown_seconds=120,
            clock=lambda: 100.0,
        )

        result = pool.translate(text="source", source_language="en", target_language="uk")

        first, second = pool.snapshot()
        self.assertEqual(result, "ok")
        self.assertEqual(factory.calls, [("key-a", "source"), ("key-b", "source")])
        self.assertEqual(first.total_temporary_failures, 1)
        self.assertEqual(first.consecutive_temporary_failures, 1)
        self.assertEqual(first.cooldown_until, 130.0)
        self.assertEqual(first.last_failure_at, 100.0)
        self.assertIn("HTTP 429", first.last_error or "")
        self.assertNotIn("key-a", first.last_error or "")
        self.assertEqual(second.total_successful_requests, 1)

    def test_repeated_temporary_errors_use_exponential_backoff_capped_by_max(self):
        now = FakeClock(100.0)
        factory = RecordingClientFactory(
            {
                "key-a": [
                    DeepSeekApiError("DeepSeek API returned HTTP 503: first key-a"),
                    DeepSeekApiError("DeepSeek API returned HTTP 503: second key-a"),
                    DeepSeekApiError("DeepSeek API returned HTTP 503: third key-a"),
                ],
                "key-b": ["ok-1", "ok-2", "ok-3"],
            }
        )
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a"),
                DeepSeekChannelConfig(api_key="key-b", label="b"),
            ],
            client_factory=factory,
            cooldown_seconds=10,
            max_cooldown_seconds=25,
            clock=now,
        )

        self.assertEqual(pool.translate(text="one", source_language="en", target_language="uk"), "ok-1")
        self.assertEqual(pool.snapshot()[0].cooldown_until, 110.0)
        now.value = 110.0
        self.assertEqual(pool.translate(text="two", source_language="en", target_language="uk"), "ok-2")
        self.assertEqual(pool.snapshot()[0].cooldown_until, 130.0)
        now.value = 130.0
        self.assertEqual(pool.translate(text="three", source_language="en", target_language="uk"), "ok-3")
        self.assertEqual(pool.snapshot()[0].cooldown_until, 155.0)
        self.assertEqual(pool.snapshot()[0].consecutive_temporary_failures, 3)

    def test_success_resets_consecutive_temporary_failure_count(self):
        now = FakeClock(100.0)
        factory = RecordingClientFactory(
            {
                "key-a": [
                    DeepSeekApiError("DeepSeek API returned HTTP 429: busy"),
                    "recovered",
                ],
                "key-b": ["fallback"],
            }
        )
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a"),
                DeepSeekChannelConfig(api_key="key-b", label="b"),
            ],
            client_factory=factory,
            cooldown_seconds=10,
            max_cooldown_seconds=40,
            clock=now,
        )

        self.assertEqual(pool.translate(text="one", source_language="en", target_language="uk"), "fallback")
        now.value = 110.0
        self.assertEqual(pool.translate(text="two", source_language="en", target_language="uk"), "recovered")

        first = pool.snapshot()[0]
        self.assertEqual(first.total_temporary_failures, 1)
        self.assertEqual(first.total_successful_requests, 1)
        self.assertEqual(first.consecutive_temporary_failures, 0)
        self.assertIsNone(first.last_error)
```

Add this helper near the existing test helpers:

```python
class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value
```

- [ ] **Step 2: Run the failing backoff tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_temporary_error_records_cooldown_and_fails_over \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_repeated_temporary_errors_use_exponential_backoff_capped_by_max \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_success_resets_consecutive_temporary_failure_count
```

Expected: FAIL because `max_cooldown_seconds` is not accepted and cooldown is fixed.

- [ ] **Step 3: Add max cooldown and exponential backoff**

In `DeepSeekKeyPoolTranslator.__init__`, add `max_cooldown_seconds` to the signature:

```python
        max_cooldown_seconds: float = 300.0,
```

Store it beside `_cooldown_seconds`:

```python
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        self._max_cooldown_seconds = max(self._cooldown_seconds, max_cooldown_seconds)
```

Replace `_cool_down_channel` with:

```python
    def _cool_down_channel(
        self,
        channel: _DeepSeekChannel,
        error: DeepSeekApiError,
    ) -> None:
        with self._condition:
            now = self._clock()
            channel.total_temporary_failures += 1
            channel.consecutive_temporary_failures += 1
            channel.last_failure_at = now
            channel.last_error = _redact_channel_error(error, channel)
            cooldown_seconds = _channel_cooldown_seconds(
                channel,
                default_cooldown_seconds=self._cooldown_seconds,
                default_max_cooldown_seconds=self._max_cooldown_seconds,
            )
            channel.cooldown_until = max(
                channel.cooldown_until,
                now + cooldown_seconds,
            )
            self._condition.notify_all()
```

Add this helper near `_seconds_until_next_channel`:

```python
def _channel_cooldown_seconds(
    channel: _DeepSeekChannel,
    *,
    default_cooldown_seconds: float,
    default_max_cooldown_seconds: float,
) -> float:
    base = (
        channel.config.cooldown_seconds
        if channel.config.cooldown_seconds is not None
        else default_cooldown_seconds
    )
    maximum = (
        channel.config.max_cooldown_seconds
        if channel.config.max_cooldown_seconds is not None
        else default_max_cooldown_seconds
    )
    base = max(0.0, base)
    maximum = max(base, maximum)
    multiplier = 2 ** max(0, channel.consecutive_temporary_failures - 1)
    return min(maximum, base * multiplier)
```

- [ ] **Step 4: Run the backoff tests to verify they pass**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_temporary_error_records_cooldown_and_fails_over \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_repeated_temporary_errors_use_exponential_backoff_capped_by_max \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_success_resets_consecutive_temporary_failure_count
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/translator_service/deepseek_key_pool.py tests/test_deepseek_key_pool.py
git commit -m "feat: back off unhealthy deepseek channels"
```

## Task 4: Weighted Capacity-Aware Selection

**Files:**
- Modify: `src/translator_service/deepseek_key_pool.py`
- Test: `tests/test_deepseek_key_pool.py`

- [ ] **Step 1: Write failing tests for selection behavior**

Insert these tests in `DeepSeekKeyPoolTranslatorTest` after the backoff tests:

```python
    def test_selection_prefers_higher_weight_when_channels_are_otherwise_equal(self):
        factory = RecordingClientFactory({"key-a": ["a"], "key-b": ["b"]})
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a", weight=1),
                DeepSeekChannelConfig(api_key="key-b", label="b", weight=3),
            ],
            client_factory=factory,
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )

        self.assertEqual(pool.translate(text="source", source_language="en", target_language="uk"), "b")

        self.assertEqual(factory.calls, [("key-b", "source")])

    def test_selection_uses_available_capacity_before_waiting(self):
        barrier = threading.Barrier(2)
        factory = BlockingClientFactory(barrier=barrier)
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a", max_parallel_requests=1),
                DeepSeekChannelConfig(api_key="key-b", label="b", max_parallel_requests=1),
            ],
            client_factory=factory,
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )
        results = {}

        def translate(text: str) -> None:
            results[text] = pool.translate(
                text=text,
                source_language="en",
                target_language="uk",
            )

        first = threading.Thread(target=translate, args=("one",))
        second = threading.Thread(target=translate, args=("two",))
        first.start()
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(set(results.values()), {"[key-a] one", "[key-b] two"})
        self.assertEqual([item.active_requests for item in pool.snapshot()], [0, 0])
        self.assertEqual([item.total_started_requests for item in pool.snapshot()], [1, 1])
```

- [ ] **Step 2: Run the failing selection tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_selection_prefers_higher_weight_when_channels_are_otherwise_equal \
  tests.test_deepseek_key_pool.DeepSeekKeyPoolTranslatorTest.test_selection_uses_available_capacity_before_waiting
```

Expected: first test FAILS because current selection ignores weight.

- [ ] **Step 3: Add weighted selection scoring**

In `_acquire_channel`, replace the current `min(... key=lambda candidate: ...)` key with:

```python
                    channel = min(candidates, key=_channel_selection_key)
```

Add this helper near `_seconds_until_next_channel`:

```python
def _channel_selection_key(channel: _DeepSeekChannel) -> tuple[float, int, float, str]:
    load_denominator = channel.capacity * channel.weight
    relative_load = (
        channel.active_requests + channel.total_started_requests
    ) / load_denominator
    last_selected_at = (
        channel.last_selected_at
        if channel.last_selected_at is not None
        else float("-inf")
    )
    return (
        relative_load,
        -channel.weight,
        last_selected_at,
        channel.label,
    )
```

- [ ] **Step 4: Run selection tests and existing pool tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add src/translator_service/deepseek_key_pool.py tests/test_deepseek_key_pool.py
git commit -m "feat: weight deepseek channel selection"
```

## Task 5: Runtime Environment Parsing

**Files:**
- Modify: `src/translator_service/bot/runtime.py`
- Test: `tests/test_bot_runtime.py`

- [ ] **Step 1: Write failing runtime configuration tests**

Update `test_build_deepseek_translator_uses_key_pool_for_multiple_keys` to assert channel snapshots:

```python
    def test_build_deepseek_translator_uses_key_pool_for_multiple_keys(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEYS": "key-a, key-b",
                "DEEPSEEK_BASE_URL": "https://deepseek.test",
                "DEEPSEEK_MAX_PARALLEL_PER_KEY": "2",
                "DEEPSEEK_CHANNEL_COOLDOWN_SECONDS": "7",
                "DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS": "31",
                "DEEPSEEK_CHANNEL_WEIGHTS": "3, 1",
            },
            clear=False,
        ):
            translator = build_deepseek_translator(
                Settings(deepseek_model="deepseek-test")
            )

        self.assertIsInstance(translator, DeepSeekKeyPoolTranslator)
        snapshot = translator.snapshot()
        self.assertEqual([channel.label for channel in snapshot], ["deepseek-1", "deepseek-2"])
        self.assertEqual([channel.max_parallel_requests for channel in snapshot], [2, 2])
        self.assertEqual([channel.weight for channel in snapshot], [3, 1])
```

Add these tests after it:

```python
    def test_build_deepseek_translator_deduplicates_multiple_keys(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEYS": "key-a, key-a, key-b",
                "DEEPSEEK_BASE_URL": "https://deepseek.test",
            },
            clear=False,
        ):
            translator = build_deepseek_translator(
                Settings(deepseek_model="deepseek-test")
            )

        self.assertIsInstance(translator, DeepSeekKeyPoolTranslator)
        self.assertEqual([channel.label for channel in translator.snapshot()], ["deepseek-1", "deepseek-2"])

    def test_invalid_deepseek_channel_weights_fall_back_to_one(self):
        with patch.dict(
            "os.environ",
            {
                "DEEPSEEK_API_KEYS": "key-a, key-b",
                "DEEPSEEK_BASE_URL": "https://deepseek.test",
                "DEEPSEEK_CHANNEL_WEIGHTS": "3",
            },
            clear=False,
        ):
            translator = build_deepseek_translator(
                Settings(deepseek_model="deepseek-test")
            )

        self.assertIsInstance(translator, DeepSeekKeyPoolTranslator)
        self.assertEqual([channel.weight for channel in translator.snapshot()], [1, 1])
```

- [ ] **Step 2: Run the failing runtime tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_bot_runtime.BotRuntimeTest.test_build_deepseek_translator_uses_key_pool_for_multiple_keys \
  tests.test_bot_runtime.BotRuntimeTest.test_build_deepseek_translator_deduplicates_multiple_keys \
  tests.test_bot_runtime.BotRuntimeTest.test_invalid_deepseek_channel_weights_fall_back_to_one
```

Expected: FAIL because channel weights and max cooldown are not parsed.

- [ ] **Step 3: Add runtime parsing helpers**

In `src/translator_service/bot/runtime.py`, after `cooldown_seconds`, parse max cooldown and weights:

```python
    max_cooldown_seconds = _env_float(
        "DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS",
        max(300.0, cooldown_seconds),
    )
    channel_weights = _deepseek_channel_weights_from_env(len(api_keys))
```

Update channel construction:

```python
        channels=[
            DeepSeekChannelConfig(
                api_key=api_key,
                label=f"deepseek-{index}",
                max_parallel_requests=max_parallel_per_key,
                weight=channel_weights[index - 1],
            )
            for index, api_key in enumerate(api_keys, start=1)
        ],
```

Pass max cooldown into the pool:

```python
        max_cooldown_seconds=max_cooldown_seconds,
```

Add this helper after `_deepseek_api_keys_from_env`:

```python
def _deepseek_channel_weights_from_env(channel_count: int) -> list[int]:
    raw = os.getenv("DEEPSEEK_CHANNEL_WEIGHTS", "")
    if not raw.strip():
        return [1] * channel_count
    try:
        weights = [int(part.strip()) for part in raw.split(",")]
    except ValueError:
        logger.warning("Ignoring invalid DeepSeek channel weights: %r", raw)
        return [1] * channel_count
    if len(weights) != channel_count or any(weight < 1 for weight in weights):
        logger.warning("Ignoring invalid DeepSeek channel weights: %r", raw)
        return [1] * channel_count
    return weights
```

- [ ] **Step 4: Run runtime tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_bot_runtime.BotRuntimeTest.test_build_deepseek_translator_uses_key_pool_for_multiple_keys \
  tests.test_bot_runtime.BotRuntimeTest.test_build_deepseek_translator_deduplicates_multiple_keys \
  tests.test_bot_runtime.BotRuntimeTest.test_invalid_deepseek_channel_weights_fall_back_to_one
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add src/translator_service/bot/runtime.py tests/test_bot_runtime.py
git commit -m "feat: configure deepseek api channels"
```

## Task 6: README Configuration Notes

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add README documentation**

Insert this section after the `DeepSeek Smoke Test` section:

````markdown
## DeepSeek API Channels

For local development with one API key, keep using:

```bash
DEEPSEEK_API_KEY='your_key'
```

For multiple internal API channels, provide a comma-separated key list:

```bash
DEEPSEEK_API_KEYS='key_one,key_two,key_three' \
DEEPSEEK_MAX_PARALLEL_PER_KEY='1' \
DEEPSEEK_CHANNEL_COOLDOWN_SECONDS='30' \
DEEPSEEK_CHANNEL_MAX_COOLDOWN_SECONDS='300' \
DEEPSEEK_CHANNEL_WEIGHTS='1,1,1'
```

The bot treats these keys as internal reliability channels. Users do not see or choose provider channels. Repeated keys are ignored after their first occurrence, and invalid weights fall back to `1` for every channel.
````

- [ ] **Step 2: Review README formatting**

Run:

```bash
sed -n '54,95p' README.md
```

Expected: the new `DeepSeek API Channels` section appears between `DeepSeek Smoke Test` and `TXT Translation Probe`, and fenced code blocks are balanced.

- [ ] **Step 3: Commit Task 6**

Run:

```bash
git add README.md
git commit -m "docs: document deepseek api channels"
```

## Task 7: Full Verification

**Files:**
- No new file changes expected.

- [ ] **Step 1: Run focused tests**

Run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_deepseek_key_pool tests.test_bot_runtime
```

Expected: PASS.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Expected: PASS.

- [ ] **Step 3: Compile source files**

Run:

```bash
PYTHONPATH=src python3 -m compileall src
```

Expected: command exits with status 0 and reports successful compilation.

- [ ] **Step 4: Inspect final git state**

Run:

```bash
git status --short
git log --oneline -6
```

Expected: only intentional changes are present before final commit or handoff, and recent commits correspond to Tasks 1 through 6 plus the plan/spec commits.

## Self-Review

- Spec coverage: channel state, selection, temporary failure handling, diagnostics, runtime config, tests, and README documentation are covered by Tasks 1 through 7.
- Scope check: no task adds user-facing provider choice, new messengers, non-DeepSeek providers, payment changes, or storage migrations.
- Type consistency: `DeepSeekChannelConfig`, `DeepSeekChannelSnapshot`, `snapshot()`, `weight`, `cooldown_seconds`, and `max_cooldown_seconds` use the same names across tests, implementation, and runtime wiring.
- Verification: focused tests, full test suite, and compileall are included before completion.
