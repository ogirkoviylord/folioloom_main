import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEventInput,
)


class UserActivityStoreTest(unittest.TestCase):
    def test_records_event_and_upserts_user_profile(self):
        with TemporaryDirectory() as temp_dir:
            with SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3") as store:
                store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="bot.button.clicked",
                        action="clicked",
                        target_type="button",
                        target_id="translate_book",
                        outcome=ActivityOutcome.SUCCESS,
                        metadata={"button_text": "Translate"},
                    )
                )

                profile = store.get_user_profile("telegram:42")
                events = store.list_events(actor_id="telegram:42")

            self.assertIsNotNone(profile)
            self.assertEqual(profile.user_id, "telegram:42")
            self.assertEqual(profile.channel, "telegram")
            self.assertEqual(profile.channel_user_id, "42")
            self.assertEqual(profile.security_state, "normal")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "bot.button.clicked")
            self.assertEqual(events[0].target_id, "translate_book")

    def test_filters_events_by_surface_outcome_and_job(self):
        with TemporaryDirectory() as temp_dir:
            with SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3") as store:
                store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="translation.completed",
                        action="completed",
                        outcome=ActivityOutcome.SUCCESS,
                        job_id="job-1",
                    )
                )
                store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.SECURITY,
                        event_type="security.suspicious_input_detected",
                        action="blocked",
                        outcome=ActivityOutcome.BLOCKED,
                    )
                )

                security_events = store.list_events(surface=ActivitySurface.SECURITY)
                blocked_events = store.list_events(outcome=ActivityOutcome.BLOCKED)
                job_events = store.list_events(job_id="job-1")

            self.assertEqual(
                [event.event_type for event in security_events],
                ["security.suspicious_input_detected"],
            )
            self.assertEqual(
                [event.event_type for event in blocked_events],
                ["security.suspicious_input_detected"],
            )
            self.assertEqual([event.job_id for event in job_events], ["job-1"])

    def test_metadata_is_redacted_and_truncated(self):
        with TemporaryDirectory() as temp_dir:
            with SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3") as store:
                store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="bot.message.received",
                        action="received",
                        outcome=ActivityOutcome.SUCCESS,
                        metadata={
                            "api_key": "sk-secret-value",
                            "text_preview": "x" * 900,
                        },
                    )
                )

                event = store.list_events(actor_id="telegram:42")[0]

            self.assertEqual(event.metadata["api_key"], "[redacted]")
            self.assertLess(len(event.metadata["text_preview"]), 650)
            self.assertTrue(event.metadata["text_preview"].endswith("..."))

    def test_same_store_can_record_from_worker_thread(self):
        with TemporaryDirectory() as temp_dir:
            with SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3") as store:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        store.record_event,
                        UserActivityEventInput(
                            actor_type=ActivityActorType.USER,
                            actor_id="telegram:42",
                            channel="telegram",
                            channel_user_id="42",
                            surface=ActivitySurface.BOT,
                            event_type="translation.confirmed",
                            action="confirmed",
                            outcome=ActivityOutcome.SUCCESS,
                        ),
                    )
                    event = future.result()

                events = store.list_events(actor_id="telegram:42")

            self.assertEqual(event.event_type, "translation.confirmed")
            self.assertEqual(len(events), 1)

    def test_date_to_date_only_includes_entire_day(self):
        with TemporaryDirectory() as temp_dir:
            with SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3") as store:
                event = store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:42",
                        channel="telegram",
                        channel_user_id="42",
                        surface=ActivitySurface.BOT,
                        event_type="translation.completed",
                        action="completed",
                        outcome=ActivityOutcome.SUCCESS,
                    )
                )
                store._connection.execute(
                    "UPDATE user_activity_events SET created_at = ? WHERE id = ?",
                    (
                        datetime(2026, 5, 9, 23, 59, 59, tzinfo=UTC).isoformat(
                            timespec="microseconds"
                        ),
                        event.id,
                    ),
                )
                store._connection.commit()

                events = store.list_events(date_to="2026-05-09")

            self.assertEqual(
                [event.event_type for event in events],
                ["translation.completed"],
            )


if __name__ == "__main__":
    unittest.main()
