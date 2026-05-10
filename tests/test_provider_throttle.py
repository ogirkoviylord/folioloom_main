import unittest

from translator_service.provider_throttle import (
    PROVIDER_CIRCUIT_CLOSED,
    PROVIDER_CIRCUIT_OPEN,
    ProviderAdaptiveThrottle,
    ProviderThrottleConfig,
)


class ProviderAdaptiveThrottleTest(unittest.TestCase):
    def test_starts_at_initial_limit(self):
        throttle = ProviderAdaptiveThrottle(
            ProviderThrottleConfig(
                enabled=True,
                initial_parallel=2,
                min_parallel=1,
            )
        )

        snapshot = throttle.snapshot(now=100.0, max_capacity=4)

        self.assertTrue(snapshot.enabled)
        self.assertEqual(snapshot.current_limit, 2)
        self.assertEqual(snapshot.available_slots, 2)
        self.assertEqual(snapshot.circuit_state, PROVIDER_CIRCUIT_CLOSED)

    def test_ramps_after_clean_successes(self):
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

        throttle.record_temporary_failure(now=101.0, max_capacity=8, reason="rate_limited")
        throttle.record_temporary_failure(now=102.0, max_capacity=8, reason="rate_limited")

        snapshot = throttle.snapshot(now=102.0, max_capacity=8)
        self.assertEqual(snapshot.current_limit, 1)

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
        self.assertEqual(snapshot.total_circuit_opened, 1)

    def test_permanent_failure_opens_circuit(self):
        throttle = ProviderAdaptiveThrottle(
            ProviderThrottleConfig(
                enabled=True,
                initial_parallel=4,
                min_parallel=1,
                circuit_reset_seconds=90.0,
            )
        )

        throttle.record_permanent_failure(now=100.0, reason="auth_failed")

        snapshot = throttle.snapshot(now=120.0, max_capacity=4)
        self.assertEqual(snapshot.circuit_state, PROVIDER_CIRCUIT_OPEN)
        self.assertEqual(snapshot.circuit_open_remaining_seconds, 70.0)
        self.assertEqual(snapshot.available_slots, 0)
        self.assertEqual(snapshot.last_reason, "auth_failed")
        self.assertEqual(snapshot.total_circuit_opened, 1)

    def test_half_open_circuit_allows_single_probe_after_permanent_failure(self):
        throttle = ProviderAdaptiveThrottle(
            ProviderThrottleConfig(
                enabled=True,
                initial_parallel=4,
                min_parallel=1,
                circuit_reset_seconds=90.0,
            )
        )

        throttle.record_permanent_failure(now=100.0, reason="auth_failed")

        snapshot = throttle.snapshot(now=190.0, max_capacity=4)
        self.assertEqual(snapshot.circuit_state, "half_open")
        self.assertEqual(snapshot.current_limit, 1)
        self.assertEqual(snapshot.available_slots, 1)
        self.assertTrue(throttle.start_request(now=190.0, max_capacity=4))
        self.assertEqual(
            throttle.snapshot(now=190.0, max_capacity=4).available_slots,
            0,
        )

    def test_disabled_config_exposes_max_capacity(self):
        throttle = ProviderAdaptiveThrottle(
            ProviderThrottleConfig(
                enabled=False,
                initial_parallel=1,
                min_parallel=1,
            )
        )

        self.assertTrue(throttle.start_request(now=100.0, max_capacity=5))
        throttle.record_temporary_failure(now=101.0, max_capacity=5, reason="rate_limited")

        snapshot = throttle.snapshot(now=102.0, max_capacity=5)
        self.assertFalse(snapshot.enabled)
        self.assertEqual(snapshot.current_limit, 5)
        self.assertEqual(snapshot.available_slots, 4)
        self.assertEqual(snapshot.circuit_state, PROVIDER_CIRCUIT_CLOSED)


if __name__ == "__main__":
    unittest.main()
