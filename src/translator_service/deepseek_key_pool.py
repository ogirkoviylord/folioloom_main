from __future__ import annotations

import random
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from translator_service.deepseek_client import (
    DeepSeekApiError,
    DeepSeekClient,
    DeepSeekUnsafeModelOutputError,
)
from translator_service.provider_throttle import (
    ProviderAdaptiveThrottle,
    ProviderThrottleConfig,
    ProviderThrottleSnapshot,
)
from translator_service.scheduler import ProviderSlotInventoryItem
from translator_service.translation_context import (
    TranslationContextMemory,
    translate_with_context,
)

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
PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT = "unsafe_model_output"

_RECENT_FAILURE_PENALTY_SECONDS = 300.0


class _PooledClient(Protocol):
    last_usage: object | None

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        pass


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
    total_unsafe_model_output_failures: int = 0


@dataclass
class _DeepSeekChannel:
    config: DeepSeekChannelConfig
    client: _PooledClient
    slot_channel_id: str
    active_requests: int = 0
    cooldown_until: float = 0.0
    total_started_requests: int = 0
    total_successful_requests: int = 0
    total_temporary_failures: int = 0
    total_permanent_failures: int = 0
    consecutive_temporary_failures: int = 0
    consecutive_failures: int = 0
    last_selected_at: float | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error: str | None = None
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
    total_unsafe_model_output_failures: int = 0

    @property
    def label(self) -> str:
        return self.config.label or f"key-{abs(hash(self.config.api_key)) % 10_000}"

    @property
    def capacity(self) -> int:
        return max(1, self.config.max_parallel_requests)

    @property
    def weight(self) -> int:
        return max(1, self.config.weight)

    def snapshot(self, *, now: float) -> DeepSeekChannelSnapshot:
        cooldown_remaining_seconds = max(0.0, self.cooldown_until - now)
        average_latency_ms = (
            self.total_latency_ms / self.latency_sample_count
            if self.latency_sample_count > 0
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
            cooldown_remaining_seconds=cooldown_remaining_seconds,
            error_kind=self.error_kind,
            last_latency_ms=self.last_latency_ms,
            average_latency_ms=average_latency_ms,
            total_rate_limit_failures=self.total_rate_limit_failures,
            total_unavailable_failures=self.total_unavailable_failures,
            total_timeout_failures=self.total_timeout_failures,
            total_malformed_response_failures=self.total_malformed_response_failures,
            total_auth_failures=self.total_auth_failures,
            total_billing_failures=self.total_billing_failures,
            total_other_provider_failures=self.total_other_provider_failures,
            total_unsafe_model_output_failures=(
                self.total_unsafe_model_output_failures
            ),
        )


class DeepSeekKeyPoolTranslator:
    def __init__(
        self,
        *,
        channels: list[DeepSeekChannelConfig],
        client_factory: Callable[..., _PooledClient] | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        retry_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
        cooldown_seconds: float = 30.0,
        max_cooldown_seconds: float = 300.0,
        throttle_config: ProviderThrottleConfig | None = None,
        cooldown_jitter_fraction: float = 0.0,
        cooldown_jitter_random: Callable[[], float] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not channels:
            raise ValueError("DeepSeek key pool requires at least one channel")
        if client_factory is None and (model is None or base_url is None):
            raise ValueError("model and base_url are required without client_factory")

        self._clock = clock or time.monotonic
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        self._max_cooldown_seconds = max(self._cooldown_seconds, max_cooldown_seconds)
        self._throttle = ProviderAdaptiveThrottle(
            throttle_config or ProviderThrottleConfig(enabled=False)
        )
        self._cooldown_jitter_fraction = max(0.0, min(1.0, cooldown_jitter_fraction))
        self._cooldown_jitter_random = cooldown_jitter_random or random.random
        self._condition = threading.Condition()
        self._last_usage = threading.local()
        self._provider_slot_channel_id = threading.local()
        self._channels = [
            _DeepSeekChannel(
                config=channel,
                client=_build_client(
                    channel=channel,
                    client_factory=client_factory,
                    model=model,
                    base_url=base_url,
                    timeout_seconds=timeout_seconds,
                    retry_attempts=retry_attempts,
                    retry_delay_seconds=retry_delay_seconds,
                ),
                slot_channel_id=f"deepseek-channel-{index + 1}",
            )
            for index, channel in enumerate(channels)
        ]

    @property
    def last_usage(self):
        return getattr(self._last_usage, "value", None)

    def snapshot(self) -> list[DeepSeekChannelSnapshot]:
        with self._condition:
            now = self._clock()
            return [channel.snapshot(now=now) for channel in self._channels]

    def provider_snapshot(self) -> ProviderThrottleSnapshot:
        with self._condition:
            return self._throttle.snapshot(
                now=self._clock(),
                max_capacity=self._configured_capacity(),
            )

    def provider_slot_inventory(self) -> list[ProviderSlotInventoryItem]:
        with self._condition:
            return [
                ProviderSlotInventoryItem(
                    provider_id="deepseek",
                    channel_id=channel.slot_channel_id,
                    max_parallel_requests=channel.capacity,
                    capacity_source="deepseek_key_pool",
                )
                for channel in self._channels
            ]

    @contextmanager
    def provider_slot_channel_lease(self, channel_id: str) -> Iterator[None]:
        previous = getattr(self._provider_slot_channel_id, "value", None)
        had_previous = hasattr(self._provider_slot_channel_id, "value")
        self._provider_slot_channel_id.value = channel_id
        try:
            yield
        finally:
            if had_previous:
                self._provider_slot_channel_id.value = previous
            else:
                del self._provider_slot_channel_id.value

    def available_parallel_slots(self) -> int:
        with self._condition:
            now = self._clock()
            provider_slots = self._throttle.snapshot(
                now=now,
                max_capacity=self._configured_capacity(),
            ).available_slots
            channel_slots = sum(
                max(0, channel.capacity - channel.active_requests)
                for channel in self._channels
                if channel.cooldown_until <= now
            )
            return min(provider_slots, channel_slots)

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
        translation_context: TranslationContextMemory | None = None,
    ) -> str:
        attempted_labels: set[str] = set()
        last_rate_error: DeepSeekApiError | None = None
        attempt_limit = (
            1 if self._leased_provider_slot_channel_id() else len(self._channels)
        )

        while len(attempted_labels) < attempt_limit:
            channel = self._acquire_channel(exclude_labels=attempted_labels)
            attempted_labels.add(channel.label)
            started_at = self._clock()
            try:
                translated = translate_with_context(
                    channel.client,
                    text=text,
                    source_language=source_language,
                    target_language=target_language,
                    translation_context=translation_context,
                )
                latency_ms = self._elapsed_ms_since(started_at)
                self._record_channel_success(channel, latency_ms=latency_ms)
                self._last_usage.value = getattr(channel.client, "last_usage", None)
                return translated
            except DeepSeekApiError as error:
                latency_ms = self._elapsed_ms_since(started_at)
                if _is_unsafe_model_output_error(error):
                    self._record_channel_unsafe_model_output(
                        channel,
                        error,
                        latency_ms=latency_ms,
                    )
                    raise
                if not _is_channel_cooldown_error(error):
                    self._record_channel_permanent_failure(channel, error, latency_ms=latency_ms)
                    raise
                last_rate_error = error
                self._cool_down_channel(channel, error, latency_ms=latency_ms)
            finally:
                self._release_channel(channel)

        if last_rate_error is not None:
            raise last_rate_error
        raise DeepSeekApiError("DeepSeek key pool has no available channels")

    def _acquire_channel(self, *, exclude_labels: set[str]) -> _DeepSeekChannel:
        with self._condition:
            leased_channel_id = self._leased_provider_slot_channel_id()
            if leased_channel_id is not None and all(
                channel.slot_channel_id != leased_channel_id
                for channel in self._channels
            ):
                raise DeepSeekApiError("DeepSeek key pool has no leased channel")
            while True:
                now = self._clock()
                candidates = [
                    channel
                    for channel in self._channels
                    if channel.label not in exclude_labels
                    and (
                        leased_channel_id is None
                        or channel.slot_channel_id == leased_channel_id
                    )
                    and channel.cooldown_until <= now
                    and channel.active_requests < channel.capacity
                ]
                if candidates:
                    if not self._throttle.start_request(
                        now=now,
                        max_capacity=self._configured_capacity(),
                    ):
                        self._condition.wait(timeout=0.05)
                        continue
                    channel = min(
                        candidates,
                        key=lambda candidate: _channel_selection_key(candidate, now=now),
                    )
                    channel.active_requests += 1
                    channel.total_started_requests += 1
                    channel.last_selected_at = now
                    channel.last_error = None
                    return channel

                wait_for = _seconds_until_next_channel(
                    self._channels,
                    exclude_labels=exclude_labels,
                    leased_channel_id=leased_channel_id,
                    now=now,
                )
                self._condition.wait(timeout=wait_for)

    def _release_channel(self, channel: _DeepSeekChannel) -> None:
        with self._condition:
            channel.active_requests = max(0, channel.active_requests - 1)
            self._throttle.finish_request()
            self._condition.notify_all()

    def _elapsed_ms_since(self, started_at: float) -> float:
        return max(0.0, (self._clock() - started_at) * 1000.0)

    def _record_channel_success(self, channel: _DeepSeekChannel, *, latency_ms: float) -> None:
        with self._condition:
            now = self._clock()
            _record_channel_latency(channel, latency_ms)
            channel.total_successful_requests += 1
            channel.consecutive_temporary_failures = 0
            channel.consecutive_failures = 0
            channel.last_success_at = now
            channel.last_error = None
            channel.error_kind = None
            self._throttle.record_success(
                now=now,
                max_capacity=self._configured_capacity(),
            )
            self._condition.notify_all()

    def _record_channel_permanent_failure(
        self,
        channel: _DeepSeekChannel,
        error: DeepSeekApiError,
        *,
        latency_ms: float,
    ) -> None:
        with self._condition:
            error_kind = _classify_provider_error(error)
            _record_channel_latency(channel, latency_ms)
            channel.total_permanent_failures += 1
            channel.consecutive_failures += 1
            channel.last_failure_at = self._clock()
            channel.last_error = _redact_channel_error(error, channel)
            channel.error_kind = error_kind
            _increment_error_kind_counter(channel, error_kind)
            if error_kind in {PROVIDER_ERROR_AUTH, PROVIDER_ERROR_BILLING}:
                self._throttle.record_permanent_failure(
                    now=channel.last_failure_at,
                    reason=error_kind,
                )
            elif error_kind == PROVIDER_ERROR_MALFORMED_RESPONSE:
                self._throttle.record_temporary_failure(
                    now=channel.last_failure_at,
                    max_capacity=self._configured_capacity(),
                    reason=error_kind,
                )
            self._condition.notify_all()

    def _record_channel_unsafe_model_output(
        self,
        channel: _DeepSeekChannel,
        error: DeepSeekApiError,
        *,
        latency_ms: float,
    ) -> None:
        with self._condition:
            _record_channel_latency(channel, latency_ms)
            channel.error_kind = PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT
            channel.last_error = _redact_channel_error(error, channel)
            channel.total_unsafe_model_output_failures += 1
            self._condition.notify_all()

    def _cool_down_channel(
        self,
        channel: _DeepSeekChannel,
        error: DeepSeekApiError,
        *,
        latency_ms: float,
    ) -> None:
        with self._condition:
            now = self._clock()
            error_kind = _classify_provider_error(error)
            _record_channel_latency(channel, latency_ms)
            channel.total_temporary_failures += 1
            channel.consecutive_temporary_failures += 1
            channel.consecutive_failures += 1
            channel.last_failure_at = now
            channel.last_error = _redact_channel_error(error, channel)
            channel.error_kind = error_kind
            _increment_error_kind_counter(channel, error_kind)
            cooldown_seconds = _channel_cooldown_seconds(
                channel,
                default_cooldown_seconds=self._cooldown_seconds,
                default_max_cooldown_seconds=self._max_cooldown_seconds,
            )
            cooldown_seconds = _apply_cooldown_jitter(
                cooldown_seconds,
                fraction=self._cooldown_jitter_fraction,
                random_value=self._cooldown_jitter_random(),
            )
            self._throttle.record_temporary_failure(
                now=now,
                max_capacity=self._configured_capacity(),
                reason=error_kind,
            )
            channel.cooldown_until = max(
                channel.cooldown_until,
                now + cooldown_seconds,
            )
            self._condition.notify_all()

    def _configured_capacity(self) -> int:
        return max(1, sum(channel.capacity for channel in self._channels))

    def _leased_provider_slot_channel_id(self) -> str | None:
        return getattr(self._provider_slot_channel_id, "value", None)


def _build_client(
    *,
    channel: DeepSeekChannelConfig,
    client_factory: Callable[..., _PooledClient] | None,
    model: str | None,
    base_url: str | None,
    timeout_seconds: float,
    retry_attempts: int,
    retry_delay_seconds: float,
) -> _PooledClient:
    if client_factory is not None:
        return client_factory(api_key=channel.api_key)
    return DeepSeekClient(
        api_key=channel.api_key,
        model=model or "",
        base_url=base_url or "",
        timeout_seconds=timeout_seconds,
        retry_attempts=retry_attempts,
        retry_delay_seconds=retry_delay_seconds,
    )


def _seconds_until_next_channel(
    channels: list[_DeepSeekChannel],
    *,
    exclude_labels: set[str],
    leased_channel_id: str | None = None,
    now: float,
) -> float:
    cooldowns = [
        channel.cooldown_until - now
        for channel in channels
        if channel.label not in exclude_labels and channel.cooldown_until > now
        and (
            leased_channel_id is None
            or channel.slot_channel_id == leased_channel_id
        )
    ]
    if cooldowns:
        return max(0.01, min(cooldowns))
    return 0.01


def _channel_selection_key(
    channel: _DeepSeekChannel,
    *,
    now: float,
) -> tuple[float, float, int, float, int, float, str]:
    active_load = channel.active_requests / channel.capacity
    fairness = channel.total_started_requests / (channel.capacity * channel.weight)
    error_penalty = _recent_error_penalty(channel, now=now)
    latency_penalty = (
        channel.total_latency_ms / channel.latency_sample_count
        if channel.latency_sample_count > 0
        else 0.0
    )
    last_selected_at = (
        channel.last_selected_at
        if channel.last_selected_at is not None
        else float("-inf")
    )
    return (
        active_load,
        fairness,
        error_penalty,
        latency_penalty,
        -channel.weight,
        last_selected_at,
        channel.label,
    )


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


def _apply_cooldown_jitter(
    seconds: float,
    *,
    fraction: float,
    random_value: float,
) -> float:
    seconds = max(0.0, seconds)
    fraction = max(0.0, min(1.0, fraction))
    if seconds <= 0.0 or fraction <= 0.0:
        return seconds
    random_value = max(0.0, min(1.0, random_value))
    delta = seconds * fraction
    return max(0.0, seconds - delta + (2 * delta * random_value))


def _is_channel_cooldown_error(error: DeepSeekApiError) -> bool:
    error_kind = _classify_provider_error(error)
    return error_kind in {
        PROVIDER_ERROR_RATE_LIMITED,
        PROVIDER_ERROR_UNAVAILABLE,
        PROVIDER_ERROR_TIMEOUT,
    }


def _is_unsafe_model_output_error(error: DeepSeekApiError) -> bool:
    return _classify_provider_error(error) == PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT


def _redact_channel_error(error: DeepSeekApiError, channel: _DeepSeekChannel) -> str:
    message = str(error).replace(channel.config.api_key, "[redacted-api-key]")
    message = re.sub(r"\bbearer\b", "[redacted-auth-scheme]", message, flags=re.IGNORECASE)
    message = re.sub(r"\bsk-[A-Za-z0-9._-]+", "[redacted-api-key]", message)
    message = re.sub(
        r"\b[A-Za-z0-9._-]*api_keys[A-Za-z0-9._-]*\b",
        "[redacted-secret-id]",
        message,
    )
    if len(message) > 300:
        return f"{message[:297]}..."
    return message


def _channel_health(channel: _DeepSeekChannel, *, now: float) -> str:
    if channel.cooldown_until > now:
        return CHANNEL_HEALTH_COOLING_DOWN
    if channel.active_requests >= channel.capacity:
        return CHANNEL_HEALTH_BUSY
    if (
        channel.error_kind is not None
        and channel.error_kind != PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT
    ):
        return CHANNEL_HEALTH_DEGRADED
    return CHANNEL_HEALTH_HEALTHY


def _classify_provider_error(error: DeepSeekApiError) -> str:
    if isinstance(error, DeepSeekUnsafeModelOutputError):
        return PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT
    message = str(error).lower()
    if "unsafe model output" in message or "unsafe_model_output" in message:
        return PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT
    if "http 429" in message or "rate limit" in message or "rate-limited" in message:
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
    elif error_kind == PROVIDER_ERROR_UNSAFE_MODEL_OUTPUT:
        channel.total_unsafe_model_output_failures += 1
    else:
        channel.total_other_provider_failures += 1


def _record_channel_latency(channel: _DeepSeekChannel, latency_ms: float) -> None:
    channel.last_latency_ms = latency_ms
    channel.total_latency_ms += latency_ms
    channel.latency_sample_count += 1


def _recent_error_penalty(channel: _DeepSeekChannel, *, now: float) -> int:
    if channel.last_failure_at is None:
        return 0
    if now - channel.last_failure_at > _RECENT_FAILURE_PENALTY_SECONDS:
        return 0
    return max(1, channel.consecutive_failures)
