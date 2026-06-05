import threading
import unittest

from translator_service.deepseek_client import (
    DeepSeekApiError,
    DeepSeekUnsafeModelOutputError,
)
from translator_service.deepseek_key_pool import (
    CHANNEL_HEALTH_COOLING_DOWN,
    CHANNEL_HEALTH_HEALTHY,
    PROVIDER_ERROR_RATE_LIMITED,
    PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT,
    DeepSeekChannelConfig,
    DeepSeekChannelSnapshot,
    DeepSeekKeyPoolTranslator,
)
from translator_service.provider_throttle import ProviderThrottleConfig
from translator_service.translation_context import TranslationContextMemory


class DeepSeekKeyPoolTranslatorTest(unittest.TestCase):
    def test_fails_over_to_next_channel_and_cools_down_rate_limited_channel(self):
        factory = RecordingClientFactory(
            {
                "key-a": [DeepSeekApiError("DeepSeek API returned HTTP 429: rate limit")],
                "key-b": ["переклад"],
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

        result = pool.translate(
            text="source",
            source_language="en",
            target_language="uk",
        )

        self.assertEqual(result, "переклад")
        self.assertEqual(factory.calls, [("key-a", "source"), ("key-b", "source")])

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

    def test_provider_slot_inventory_exposes_safe_logical_channels(self):
        factory = RecordingClientFactory({"secret-key-a": ["ok"], "secret-key-b": ["ok"]})
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(
                    api_key="secret-key-a",
                    label="primary",
                    max_parallel_requests=2,
                ),
                DeepSeekChannelConfig(
                    api_key="secret-key-b",
                    label="backup",
                    max_parallel_requests=1,
                ),
            ],
            client_factory=factory,
        )

        inventory = pool.provider_slot_inventory()

        self.assertEqual(
            [(item.provider_id, item.channel_id, item.max_parallel_requests) for item in inventory],
            [
                ("deepseek", "deepseek-channel-1", 2),
                ("deepseek", "deepseek-channel-2", 1),
            ],
        )
        inventory_repr = repr(inventory)
        self.assertNotIn("secret-key-a", inventory_repr)
        self.assertNotIn("secret-key-b", inventory_repr)
        self.assertNotIn("primary", inventory_repr)
        self.assertNotIn("backup", inventory_repr)

    def test_provider_capacity_caps_expose_safe_default_account_and_model_caps(self):
        factory = RecordingClientFactory({"secret-key-a": ["ok"], "secret-key-b": ["ok"]})
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(
                    api_key="secret-key-a",
                    label="primary",
                    max_parallel_requests=2,
                ),
                DeepSeekChannelConfig(
                    api_key="secret-key-b",
                    label="backup",
                    max_parallel_requests=1,
                ),
            ],
            client_factory=factory,
        )

        caps = pool.provider_capacity_caps()

        self.assertEqual(
            [(cap.scope.value, cap.cap_id, cap.max_parallel_requests) for cap in caps],
            [
                ("account", "deepseek-account-default", 3),
                ("model", "deepseek-model-default", 3),
            ],
        )
        self.assertEqual(
            [cap.channel_ids for cap in caps],
            [
                ("deepseek-channel-1", "deepseek-channel-2"),
                ("deepseek-channel-1", "deepseek-channel-2"),
            ],
        )
        caps_repr = repr(caps)
        self.assertNotIn("secret-key-a", caps_repr)
        self.assertNotIn("secret-key-b", caps_repr)
        self.assertNotIn("primary", caps_repr)
        self.assertNotIn("backup", caps_repr)

    def test_provider_slot_channel_lease_binds_translation_to_safe_channel_id(self):
        factory = RecordingClientFactory(
            {
                "key-a": ["from-a"],
                "key-b": ["from-b"],
            }
        )
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a", weight=1),
                DeepSeekChannelConfig(api_key="key-b", label="b", weight=10),
            ],
            client_factory=factory,
        )

        with pool.provider_slot_channel_lease("deepseek-channel-1"):
            result = pool.translate(
                text="source",
                source_language="en",
                target_language="uk",
            )

        self.assertEqual(result, "from-a")
        self.assertEqual(factory.calls, [("key-a", "source")])

    def test_provider_slot_channel_lease_does_not_fail_over_to_other_channel(self):
        factory = RecordingClientFactory(
            {
                "key-a": [
                    DeepSeekApiError("DeepSeek API returned HTTP 429: rate limit")
                ],
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

        with self.assertRaisesRegex(DeepSeekApiError, "HTTP 429"):
            with pool.provider_slot_channel_lease("deepseek-channel-1"):
                pool.translate(
                    text="source",
                    source_language="en",
                    target_language="uk",
                )

        self.assertEqual(factory.calls, [("key-a", "source")])

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

    def test_forwards_translation_context_to_context_aware_client(self):
        factory = RecordingClientFactory({"key-a": ["ok"]})
        pool = DeepSeekKeyPoolTranslator(
            channels=[DeepSeekChannelConfig(api_key="key-a", label="a")],
            client_factory=factory,
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )
        context = TranslationContextMemory(
            style_summary="Keep the established book manuscript voice."
        )

        result = pool.translate(
            text="source",
            source_language="en",
            target_language="ru",
            translation_context=context,
        )

        self.assertEqual(result, "ok")
        self.assertEqual(factory.contexts, [context])

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

    def test_unsafe_model_output_does_not_degrade_channel_or_throttle(self):
        factory = RecordingClientFactory(
            {
                "key-a": [DeepSeekUnsafeModelOutputError("tool_or_execution_claim")],
                "key-b": ["should-not-run"],
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
                min_parallel=1,
                circuit_failure_threshold=1,
                circuit_reset_seconds=60.0,
            ),
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )

        with self.assertRaisesRegex(
            DeepSeekUnsafeModelOutputError,
            "tool_or_execution_claim",
        ):
            pool.translate(text="source", source_language="en", target_language="uk")

        first, second = pool.snapshot()
        provider_snapshot = pool.provider_snapshot()
        self.assertEqual(factory.calls, [("key-a", "source")])
        self.assertEqual(first.total_started_requests, 1)
        self.assertEqual(first.total_temporary_failures, 0)
        self.assertEqual(first.total_permanent_failures, 0)
        self.assertEqual(first.total_other_provider_failures, 0)
        self.assertEqual(first.total_unsafe_model_output_failures, 1)
        self.assertEqual(first.consecutive_temporary_failures, 0)
        self.assertEqual(first.health, CHANNEL_HEALTH_HEALTHY)
        self.assertEqual(first.error_kind, PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT)
        self.assertIsNone(first.last_failure_at)
        self.assertEqual(first.cooldown_remaining_seconds, 0.0)
        self.assertIn("unsafe model output", first.last_error or "")
        self.assertEqual(second.total_started_requests, 0)
        self.assertEqual(provider_snapshot.current_limit, 2)
        self.assertEqual(provider_snapshot.available_slots, 2)
        self.assertEqual(provider_snapshot.circuit_state, "closed")
        self.assertIsNone(provider_snapshot.last_reason)

    def test_legacy_unsafe_output_message_does_not_degrade_or_throttle(self):
        factory = RecordingClientFactory(
            {
                "key-a": [
                    DeepSeekApiError(
                        "DeepSeek produced invalid translation batch contract "
                        "after repair: unsafe_model_output"
                    )
                ],
                "key-b": ["should-not-run"],
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
                min_parallel=1,
                circuit_failure_threshold=1,
                circuit_reset_seconds=60.0,
            ),
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )

        with self.assertRaisesRegex(DeepSeekApiError, "unsafe_model_output"):
            pool.translate(text="source", source_language="en", target_language="uk")

        first, second = pool.snapshot()
        provider_snapshot = pool.provider_snapshot()
        self.assertEqual(factory.calls, [("key-a", "source")])
        self.assertEqual(first.total_started_requests, 1)
        self.assertEqual(first.total_temporary_failures, 0)
        self.assertEqual(first.total_permanent_failures, 0)
        self.assertEqual(first.total_other_provider_failures, 0)
        self.assertEqual(first.total_unsafe_model_output_failures, 1)
        self.assertEqual(first.consecutive_temporary_failures, 0)
        self.assertEqual(first.health, CHANNEL_HEALTH_HEALTHY)
        self.assertEqual(first.error_kind, PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT)
        self.assertIsNone(first.last_failure_at)
        self.assertEqual(first.cooldown_remaining_seconds, 0.0)
        self.assertEqual(second.total_started_requests, 0)
        self.assertEqual(provider_snapshot.current_limit, 2)
        self.assertEqual(provider_snapshot.available_slots, 2)
        self.assertEqual(provider_snapshot.circuit_state, "closed")
        self.assertIsNone(provider_snapshot.last_reason)

    def test_temporary_error_records_cooldown_and_fails_over(self):
        factory = RecordingClientFactory(
            {
                "key-a": [
                    DeepSeekApiError(
                        "DeepSeek API returned HTTP 429: Bearer key-a busy "
                        "fallback sk-unrelated-secret .api_keys.deepseek",
                    )
                ],
                "key-b": ["ok"],
            }
        )
        now = FakeClock(100.0)
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a"),
                DeepSeekChannelConfig(api_key="key-b", label="b"),
            ],
            client_factory=factory,
            cooldown_seconds=30,
            max_cooldown_seconds=120,
            clock=now,
        )

        result = pool.translate(text="source", source_language="en", target_language="uk")

        first, second = pool.snapshot()
        self.assertEqual(result, "ok")
        self.assertEqual(factory.calls, [("key-a", "source"), ("key-b", "source")])
        self.assertEqual(first.total_temporary_failures, 1)
        self.assertEqual(first.consecutive_temporary_failures, 1)
        self.assertEqual(first.cooldown_until, 130.0)
        self.assertEqual(first.cooldown_remaining_seconds, 30.0)
        self.assertEqual(first.health, CHANNEL_HEALTH_COOLING_DOWN)
        self.assertEqual(first.error_kind, PROVIDER_ERROR_RATE_LIMITED)
        self.assertEqual(first.total_rate_limit_failures, 1)
        self.assertEqual(first.last_latency_ms, 0.0)
        self.assertEqual(first.average_latency_ms, 0.0)
        self.assertEqual(first.last_failure_at, 100.0)
        self.assertIn("HTTP 429", first.last_error or "")
        self.assertNotIn("key-a", first.last_error or "")
        self.assertNotIn("Bearer", first.last_error or "")
        self.assertNotIn("sk-unrelated-secret", first.last_error or "")
        self.assertNotIn(".api_keys.", first.last_error or "")
        self.assertNotIn("key-a", repr(first))
        now.value = 125.0
        self.assertEqual(pool.snapshot()[0].cooldown_remaining_seconds, 5.0)
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
                DeepSeekChannelConfig(api_key="key-a", label="a", weight=2),
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
                DeepSeekChannelConfig(api_key="key-a", label="a", weight=2),
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

    def test_recent_provider_error_penalizes_channel_after_cooldown_expires(self):
        now = FakeClock(100.0)
        factory = RecordingClientFactory(
            {
                "key-a": [
                    DeepSeekApiError("DeepSeek API returned HTTP 429: busy"),
                    "recovered",
                ],
                "key-b": ["fallback", "healthy-next"],
            }
        )
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a"),
                DeepSeekChannelConfig(api_key="key-b", label="b"),
            ],
            client_factory=factory,
            cooldown_seconds=10,
            clock=now,
        )

        self.assertEqual(pool.translate(text="one", source_language="en", target_language="uk"), "fallback")
        now.value = 110.0

        self.assertEqual(pool.translate(text="two", source_language="en", target_language="uk"), "healthy-next")

        self.assertEqual(factory.calls, [("key-a", "one"), ("key-b", "one"), ("key-b", "two")])

    def test_slower_channel_is_penalized_when_load_and_fairness_are_equal(self):
        now = FakeClock(100.0)
        factory = LatencyClientFactory(
            clock=now,
            delays_by_key={
                "key-a": [0.500, 0.500],
                "key-b": [0.010, 0.010],
            },
        )
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

        self.assertEqual(factory.calls, [("key-a", "one"), ("key-b", "two"), ("key-b", "three")])

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

    def test_adaptive_throttle_limits_concurrent_provider_starts(self):
        started = threading.Event()
        release = threading.Event()
        factory = HoldingClientFactory(started=started, release=release)
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
        result = {}

        def translate() -> None:
            result["value"] = pool.translate(
                text="one",
                source_language="en",
                target_language="uk",
            )

        thread = threading.Thread(target=translate)
        thread.start()
        self.assertTrue(started.wait(timeout=1.0))

        self.assertEqual(pool.available_parallel_slots(), 0)
        provider_snapshot = pool.provider_snapshot()
        self.assertEqual(provider_snapshot.current_limit, 1)
        self.assertEqual(provider_snapshot.active_requests, 1)

        release.set()
        thread.join(timeout=5.0)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["value"], "[key-a] one")

    def test_provider_circuit_opens_after_repeated_temporary_failures(self):
        now = FakeClock(100.0)
        factory = RecordingClientFactory(
            {
                "key-a": [
                    DeepSeekApiError("DeepSeek API returned HTTP 503: unavailable")
                ],
                "key-b": [
                    DeepSeekApiError("DeepSeek API returned HTTP 503: unavailable")
                ],
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
                min_parallel=1,
                circuit_failure_threshold=2,
                circuit_reset_seconds=60.0,
            ),
            cooldown_seconds=0,
            clock=now,
        )

        with self.assertRaises(DeepSeekApiError):
            pool.translate(text="source", source_language="en", target_language="uk")

        snapshot = pool.provider_snapshot()
        self.assertEqual(snapshot.circuit_state, "open")
        self.assertEqual(snapshot.available_slots, 0)
        self.assertEqual(snapshot.last_reason, "unavailable")

    def test_channel_cooldown_jitter_is_applied_to_temporary_failures(self):
        now = FakeClock(100.0)
        factory = RecordingClientFactory(
            {
                "key-a": [DeepSeekApiError("DeepSeek API returned HTTP 429: busy")],
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
            cooldown_jitter_fraction=0.20,
            cooldown_jitter_random=lambda: 0.0,
            clock=now,
        )

        self.assertEqual(
            pool.translate(text="source", source_language="en", target_language="uk"),
            "ok",
        )

        first = pool.snapshot()[0]
        self.assertEqual(first.cooldown_until, 124.0)

    def test_keeps_last_usage_thread_local_for_parallel_calls(self):
        barrier = threading.Barrier(2)
        factory = BlockingClientFactory(barrier=barrier)
        pool = DeepSeekKeyPoolTranslator(
            channels=[
                DeepSeekChannelConfig(api_key="key-a", label="a"),
                DeepSeekChannelConfig(api_key="key-b", label="b"),
            ],
            client_factory=factory,
            cooldown_seconds=30,
            clock=lambda: 100.0,
        )
        usages = {}

        def translate(text: str) -> None:
            result = pool.translate(
                text=text,
                source_language="en",
                target_language="uk",
            )
            usages[text] = (result, pool.last_usage.prompt_tokens)

        first = threading.Thread(target=translate, args=("one",))
        second = threading.Thread(target=translate, args=("two",))
        first.start()
        second.start()
        first.join(timeout=5)
        second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(usages["one"], ("[key-a] one", 101))
        self.assertEqual(usages["two"], ("[key-b] two", 202))


class RecordingClientFactory:
    def __init__(self, results_by_key):
        self.results_by_key = {
            key: list(results)
            for key, results in results_by_key.items()
        }
        self.calls = []
        self.contexts = []

    def __call__(self, *, api_key: str):
        return RecordingClient(api_key=api_key, factory=self)


class RecordingClient:
    def __init__(self, *, api_key: str, factory: RecordingClientFactory) -> None:
        self.api_key = api_key
        self.factory = factory
        self.last_usage = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
        translation_context: TranslationContextMemory | None = None,
    ) -> str:
        self.factory.calls.append((self.api_key, text))
        self.factory.contexts.append(translation_context)
        result = self.factory.results_by_key[self.api_key].pop(0)
        if isinstance(result, Exception):
            raise result
        self.last_usage = _Usage(prompt_tokens=1)
        return result


class FakeClock:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class BlockingClientFactory:
    def __init__(self, *, barrier: threading.Barrier) -> None:
        self.barrier = barrier

    def __call__(self, *, api_key: str):
        return BlockingClient(api_key=api_key, barrier=self.barrier)


class BlockingClient:
    def __init__(self, *, api_key: str, barrier: threading.Barrier) -> None:
        self.api_key = api_key
        self.barrier = barrier
        self.last_usage = None

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.barrier.wait(timeout=5)
        prompt_tokens = 101 if self.api_key == "key-a" else 202
        self.last_usage = _Usage(prompt_tokens=prompt_tokens)
        return f"[{self.api_key}] {text}"


class HoldingClientFactory:
    def __init__(self, *, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release
        self.calls = []

    def __call__(self, *, api_key: str):
        return HoldingClient(api_key=api_key, factory=self)


class HoldingClient:
    def __init__(self, *, api_key: str, factory: HoldingClientFactory) -> None:
        self.api_key = api_key
        self.factory = factory
        self.last_usage = None

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.factory.calls.append((self.api_key, text))
        self.factory.started.set()
        if not self.factory.release.wait(timeout=5.0):
            raise TimeoutError("holding client was not released")
        self.last_usage = _Usage(prompt_tokens=1)
        return f"[{self.api_key}] {text}"


class LatencyClientFactory:
    def __init__(self, *, clock: FakeClock, delays_by_key):
        self.clock = clock
        self.delays_by_key = {
            key: list(delays)
            for key, delays in delays_by_key.items()
        }
        self.calls = []

    def __call__(self, *, api_key: str):
        return LatencyClient(api_key=api_key, factory=self)


class LatencyClient:
    def __init__(self, *, api_key: str, factory: LatencyClientFactory) -> None:
        self.api_key = api_key
        self.factory = factory
        self.last_usage = None

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.factory.calls.append((self.api_key, text))
        delay = self.factory.delays_by_key[self.api_key].pop(0)
        self.factory.clock.value += delay
        self.last_usage = _Usage(prompt_tokens=1)
        return f"[{self.api_key}] {text}"


class _Usage:
    def __init__(self, *, prompt_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = 0
        self.total_tokens = prompt_tokens
        self.prompt_cache_hit_tokens = 0
        self.prompt_cache_miss_tokens = prompt_tokens


if __name__ == "__main__":
    unittest.main()
