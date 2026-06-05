import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Event, Lock
from typing import Callable, Protocol

logger = logging.getLogger(__name__)


class SchedulerWakeupEvent(StrEnum):
    WORK_ENQUEUED = "work_enqueued"
    PROVIDER_SLOT_RELEASED = "provider_slot_released"
    LEASE_RECOVERED = "lease_recovered"
    CAP_PRESSURE_CLEARED = "cap_pressure_cleared"


@dataclass(frozen=True)
class SchedulerWakeupNotification:
    event_type: SchedulerWakeupEvent
    created_at: datetime
    source: str = "internal"


@dataclass(frozen=True)
class SchedulerWakeupDiagnostics:
    enabled: bool
    backend: str
    status: str
    notifications_received: int
    last_event_type: str | None
    last_event_at: datetime | None
    diagnostic_scope: str = "wake_up_hint_only_postgresql_is_truth"


class SchedulerWakeupNotifier(Protocol):
    def notify(self, notification: SchedulerWakeupNotification) -> None:
        pass

    def wait_for_wakeup(self, *, timeout_seconds: float) -> bool:
        pass

    def diagnostics(self) -> SchedulerWakeupDiagnostics:
        pass


class InMemorySchedulerWakeupNotifier:
    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._notifications_received = 0
        self._last_event_type: str | None = None
        self._last_event_at: datetime | None = None

    def notify(self, notification: SchedulerWakeupNotification) -> None:
        with self._lock:
            self._notifications_received += 1
            self._last_event_type = notification.event_type.value
            self._last_event_at = _aware_utc(notification.created_at)
            self._event.set()

    def wait_for_wakeup(self, *, timeout_seconds: float) -> bool:
        woke = self._event.wait(max(0.0, float(timeout_seconds)))
        if woke:
            self._event.clear()
        return woke

    def diagnostics(self) -> SchedulerWakeupDiagnostics:
        with self._lock:
            return SchedulerWakeupDiagnostics(
                enabled=True,
                backend="in_memory",
                status="available",
                notifications_received=self._notifications_received,
                last_event_type=self._last_event_type,
                last_event_at=self._last_event_at,
            )


def scheduler_wakeup_diagnostics(
    notifier: SchedulerWakeupNotifier | None,
) -> SchedulerWakeupDiagnostics:
    if notifier is None:
        return SchedulerWakeupDiagnostics(
            enabled=False,
            backend="none",
            status="disabled",
            notifications_received=0,
            last_event_type=None,
            last_event_at=None,
        )
    try:
        return notifier.diagnostics()
    except Exception as error:
        logger.warning(
            "Scheduler wake-up diagnostics unavailable: error_type=%s",
            type(error).__name__,
        )
        return SchedulerWakeupDiagnostics(
            enabled=True,
            backend="unknown",
            status="unavailable",
            notifications_received=0,
            last_event_type=None,
            last_event_at=None,
        )


def wait_for_scheduler_wakeup(
    notifier: SchedulerWakeupNotifier | None,
    *,
    timeout_seconds: float,
    fallback_sleep: Callable[[float], None],
) -> bool:
    timeout = max(0.0, float(timeout_seconds))
    if notifier is None:
        fallback_sleep(timeout)
        return False
    try:
        return notifier.wait_for_wakeup(timeout_seconds=timeout)
    except Exception as error:
        logger.warning(
            "Scheduler wake-up backend unavailable; falling back to polling: "
            "error_type=%s",
            type(error).__name__,
        )
        fallback_sleep(timeout)
        return False


def scheduler_wakeup_notification(
    event_type: SchedulerWakeupEvent,
    *,
    source: str = "internal",
    now: datetime | None = None,
) -> SchedulerWakeupNotification:
    return SchedulerWakeupNotification(
        event_type=event_type,
        created_at=_aware_utc(now or datetime.now(UTC)),
        source=source,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
