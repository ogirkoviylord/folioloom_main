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
        if not self._config.enabled:
            return
        self._last_reason = reason
        self._successes_since_ramp = 0
        self._consecutive_failures += 1
        self._decrease(max_capacity=max_capacity)
        if self._consecutive_failures >= max(1, self._config.circuit_failure_threshold):
            self._open_circuit(now=now, reason=reason)

    def record_permanent_failure(self, *, now: float, reason: str) -> None:
        if not self._config.enabled:
            return
        self._last_reason = reason
        self._consecutive_failures += 1
        self._current_limit = max(1, self._config.min_parallel)
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
            if circuit_state == PROVIDER_CIRCUIT_HALF_OPEN:
                current_limit = min(current_limit, 1)
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
        next_limit = min(max(1, max_capacity), max(minimum, decreased))
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
