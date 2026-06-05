import unittest
from datetime import UTC, datetime

from translator_service.scheduler_notifications import (
    InMemorySchedulerWakeupNotifier,
    SchedulerWakeupDiagnostics,
    SchedulerWakeupEvent,
    scheduler_wakeup_diagnostics,
    scheduler_wakeup_notification,
    wait_for_scheduler_wakeup,
)


class SchedulerNotificationTest(unittest.TestCase):
    def test_diagnostics_mark_notifications_as_wakeup_hints_only(self):
        diagnostics = scheduler_wakeup_diagnostics(None)

        self.assertEqual(
            diagnostics,
            SchedulerWakeupDiagnostics(
                enabled=False,
                backend="none",
                status="disabled",
                notifications_received=0,
                last_event_type=None,
                last_event_at=None,
            ),
        )
        self.assertEqual(
            diagnostics.diagnostic_scope,
            "wake_up_hint_only_postgresql_is_truth",
        )

    def test_in_memory_notifier_accepts_duplicate_and_out_of_order_hints(self):
        notifier = InMemorySchedulerWakeupNotifier()
        first_at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
        second_at = datetime(2026, 6, 5, 12, 1, tzinfo=UTC)

        notifier.notify(
            scheduler_wakeup_notification(
                SchedulerWakeupEvent.PROVIDER_SLOT_RELEASED,
                now=second_at,
            )
        )
        notifier.notify(
            scheduler_wakeup_notification(
                SchedulerWakeupEvent.WORK_ENQUEUED,
                now=first_at,
            )
        )
        notifier.notify(
            scheduler_wakeup_notification(
                SchedulerWakeupEvent.WORK_ENQUEUED,
                now=first_at,
            )
        )

        self.assertTrue(notifier.wait_for_wakeup(timeout_seconds=0))
        self.assertFalse(notifier.wait_for_wakeup(timeout_seconds=0))
        diagnostics = notifier.diagnostics()
        self.assertEqual(diagnostics.notifications_received, 3)
        self.assertEqual(
            diagnostics.last_event_type,
            SchedulerWakeupEvent.WORK_ENQUEUED.value,
        )

    def test_wait_falls_back_to_polling_when_backend_is_missing_or_unavailable(self):
        sleep_calls = []

        self.assertFalse(
            wait_for_scheduler_wakeup(
                None,
                timeout_seconds=0.25,
                fallback_sleep=sleep_calls.append,
            )
        )
        self.assertEqual(sleep_calls, [0.25])

        class FailingNotifier:
            def wait_for_wakeup(self, *, timeout_seconds: float) -> bool:
                raise RuntimeError("notification backend unavailable")

        self.assertFalse(
            wait_for_scheduler_wakeup(
                FailingNotifier(),
                timeout_seconds=0.5,
                fallback_sleep=sleep_calls.append,
            )
        )
        self.assertEqual(sleep_calls, [0.25, 0.5])


if __name__ == "__main__":
    unittest.main()
