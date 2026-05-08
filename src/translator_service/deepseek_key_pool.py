from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable, Protocol

from translator_service.deepseek_client import DeepSeekApiError, DeepSeekClient


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
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not channels:
            raise ValueError("DeepSeek key pool requires at least one channel")
        if client_factory is None and (model is None or base_url is None):
            raise ValueError("model and base_url are required without client_factory")

        self._clock = clock or time.monotonic
        self._cooldown_seconds = max(0.0, cooldown_seconds)
        self._max_cooldown_seconds = max(self._cooldown_seconds, max_cooldown_seconds)
        self._condition = threading.Condition()
        self._last_usage = threading.local()
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
            )
            for channel in channels
        ]

    @property
    def last_usage(self):
        return getattr(self._last_usage, "value", None)

    def snapshot(self) -> list[DeepSeekChannelSnapshot]:
        with self._condition:
            return [channel.snapshot() for channel in self._channels]

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        attempted_labels: set[str] = set()
        last_rate_error: DeepSeekApiError | None = None

        while len(attempted_labels) < len(self._channels):
            channel = self._acquire_channel(exclude_labels=attempted_labels)
            attempted_labels.add(channel.label)
            try:
                translated = channel.client.translate(
                    text=text,
                    source_language=source_language,
                    target_language=target_language,
                )
                self._record_channel_success(channel)
                self._last_usage.value = getattr(channel.client, "last_usage", None)
                return translated
            except DeepSeekApiError as error:
                if not _is_channel_cooldown_error(error):
                    self._record_channel_permanent_failure(channel, error)
                    raise
                last_rate_error = error
                self._cool_down_channel(channel, error)
            finally:
                self._release_channel(channel)

        if last_rate_error is not None:
            raise last_rate_error
        raise DeepSeekApiError("DeepSeek key pool has no available channels")

    def _acquire_channel(self, *, exclude_labels: set[str]) -> _DeepSeekChannel:
        with self._condition:
            while True:
                now = self._clock()
                candidates = [
                    channel
                    for channel in self._channels
                    if channel.label not in exclude_labels
                    and channel.cooldown_until <= now
                    and channel.active_requests < channel.capacity
                ]
                if candidates:
                    channel = min(candidates, key=_channel_selection_key)
                    channel.active_requests += 1
                    channel.total_started_requests += 1
                    channel.last_selected_at = now
                    channel.last_error = None
                    return channel

                wait_for = _seconds_until_next_channel(
                    self._channels,
                    exclude_labels=exclude_labels,
                    now=now,
                )
                self._condition.wait(timeout=wait_for)

    def _release_channel(self, channel: _DeepSeekChannel) -> None:
        with self._condition:
            channel.active_requests = max(0, channel.active_requests - 1)
            self._condition.notify_all()

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
    now: float,
) -> float:
    cooldowns = [
        channel.cooldown_until - now
        for channel in channels
        if channel.label not in exclude_labels and channel.cooldown_until > now
    ]
    if cooldowns:
        return max(0.01, min(cooldowns))
    return 0.01


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


def _is_channel_cooldown_error(error: DeepSeekApiError) -> bool:
    message = str(error)
    return "HTTP 429" in message or "HTTP 503" in message


def _redact_channel_error(error: DeepSeekApiError, channel: _DeepSeekChannel) -> str:
    message = str(error).replace(channel.config.api_key, "[redacted-api-key]")
    if len(message) > 300:
        return f"{message[:297]}..."
    return message
