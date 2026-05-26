import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from translator_service.admin.upload_safety import (
    UPLOAD_SAFETY_ACTIVITY_EVENT_TYPE,
    UploadSafetyAdminReadModel,
    UploadSafetyAdminRecord,
    UploadSafetyFilters,
    UploadSafetyTimelineEvent,
    upload_safety_read_model_from_activity_events,
    upload_safety_read_model_from_ledger,
)
from translator_service.api import create_app
from translator_service.config import Settings
from translator_service.upload_safety_ledger import (
    InMemoryUploadSafetyLedger,
    UploadSafetyMetadata,
    UploadSafetyState,
)
from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEventInput,
)


class AdminUploadSafetyRoutesTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(
            create_app(
                settings=Settings(
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                )
            )
        )

    def test_upload_safety_pages_do_not_read_model_without_login(self):
        for path in ("/admin/upload-safety", "/admin/upload-safety/upload-1"):
            with self.subTest(path=path):
                with patch(
                    "translator_service.admin.routes._upload_safety_read_model",
                    side_effect=AssertionError(
                        "upload safety read model should be lazy"
                    ),
                ):
                    response = self.client.get(path, follow_redirects=False)

                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers["location"], "/admin/login")

    def test_upload_safety_list_reads_activity_store(self):
        with TemporaryDirectory() as temp_dir:
            admin_db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteUserActivityStore(admin_db_path) as store:
                store.record_event(_activity_event_input(upload_id="upload-activity"))
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                        admin_db_path=str(admin_db_path),
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/upload-safety")

        self.assertEqual(page.status_code, 200)
        self.assertIn("upload-activity", page.text)
        self.assertIn("scan_blocked", page.text)
        _assert_no_sensitive_upload_metadata(page.text)

    def test_upload_safety_filters_include_records_older_than_first_page(self):
        with TemporaryDirectory() as temp_dir:
            admin_db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteUserActivityStore(admin_db_path) as store:
                store.record_event(_activity_event_input(upload_id="upload-older"))
                for index in range(501):
                    store.record_event(
                        _activity_event_input(
                            upload_id=f"upload-newer-{index}",
                            final_action="accepted",
                            av_verdict="clean",
                            container_verdict="clean",
                            reason_code="accepted_source_created",
                            outcome=ActivityOutcome.SUCCESS,
                        )
                    )
            client = TestClient(
                create_app(
                    settings=Settings(
                        admin_owner_password="owner-pass",
                        admin_session_secret="session-secret",
                        admin_db_path=str(admin_db_path),
                    )
                )
            )
            client.post("/admin/login", data={"password": "owner-pass"})

            page = client.get("/admin/upload-safety?final_action=blocked")

        self.assertEqual(page.status_code, 200)
        self.assertIn("upload-older", page.text)
        self.assertIn("Blocked", page.text)
        self.assertNotIn("upload-newer-500", page.text)
        _assert_no_sensitive_upload_metadata(page.text)

    def test_upload_safety_list_filters_and_redacts_sensitive_metadata(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        read_model = UploadSafetyAdminReadModel(
            (
                _record(
                    upload_id="upload-blocked",
                    final_action="rejected",
                    av_verdict="infected",
                    reason_code="scanner_infected",
                    sanitized_original_filename="blocked-book.txt",
                    parser_access_granted=True,
                ),
                _record(
                    upload_id="upload-accepted",
                    final_action="accepted",
                    av_verdict="clean",
                    reason_code="accepted_source_created",
                    sanitized_original_filename="accepted-book.txt",
                ),
            )
        )

        with patch(
            "translator_service.admin.routes._upload_safety_read_model",
            return_value=read_model,
        ):
            page = self.client.get(
                "/admin/upload-safety?final_action=rejected&av_verdict=infected"
            )

        self.assertEqual(page.status_code, 200)
        self.assertIn("Upload Safety", page.text)
        self.assertIn("Scanned", page.text)
        self.assertIn("Access violations", page.text)
        self.assertIn("upload-blocked", page.text)
        self.assertNotIn("upload-accepted", page.text)
        self.assertNotIn("blocked-book.txt", page.text)
        self.assertNotIn("accepted-book.txt", page.text)
        _assert_no_sensitive_upload_metadata(page.text)

    def test_upload_safety_detail_shows_sanitized_metadata_only(self):
        self.client.post("/admin/login", data={"password": "owner-pass"})
        read_model = UploadSafetyAdminReadModel(
            (
                _record(
                    upload_id="upload-blocked",
                    final_action="rejected",
                    av_verdict="infected",
                    reason_code="scanner_infected",
                    sanitized_original_filename="blocked-book.txt",
                    parser_access_granted=False,
                    worker_access_granted=False,
                ),
            )
        )

        with patch(
            "translator_service.admin.routes._upload_safety_read_model",
            return_value=read_model,
        ):
            page = self.client.get("/admin/upload-safety/upload-blocked")

        self.assertEqual(page.status_code, 200)
        self.assertIn("blocked-book.txt", page.text)
        self.assertIn("scan_blocked", page.text)
        self.assertIn("short_hash", page.text)
        self.assertIn("abc12345", page.text)
        self.assertNotIn("allow anyway", page.text.lower())
        self.assertNotIn("rescan", page.text.lower())
        self.assertNotIn("download", page.text.lower())
        _assert_no_sensitive_upload_metadata(page.text)

    def test_upload_safety_read_model_supports_safe_filters(self):
        read_model = UploadSafetyAdminReadModel(
            (
                _record(
                    upload_id="upload-blocked",
                    final_action="rejected",
                    av_verdict="infected",
                    reason_code="scanner_infected",
                    sanitized_original_filename="blocked-book.txt",
                ),
                _record(
                    upload_id="upload-accepted",
                    final_action="accepted",
                    av_verdict="clean",
                    reason_code="accepted_source_created",
                    sanitized_original_filename="accepted-book.txt",
                ),
            )
        )

        records = read_model.list_records(
            UploadSafetyFilters(
                date_from="2026-05-26",
                date_to="2026-05-26",
                final_action="rejected",
                av_verdict="infected",
                container_verdict="clean",
                reason_code="scanner_infected",
                channel_user_id="telegram:42",
                declared_format="txt",
            )
        )

        self.assertEqual([record.upload_id for record in records], ["upload-blocked"])

    def test_upload_safety_read_model_can_build_from_ledger_history(self):
        observed_at = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
        ledger = InMemoryUploadSafetyLedger()
        _blocked_ledger_upload(ledger, upload_id="upload-ledger")

        read_model = upload_safety_read_model_from_ledger(
            ledger,
            observed_at=observed_at,
        )
        record = read_model.get_record("upload-ledger")

        self.assertIsNotNone(record)
        self.assertEqual(record.final_action, "blocked")
        self.assertEqual(record.short_hash, "01234567")
        self.assertIsNone(record.sanitized_original_filename)
        self.assertEqual(
            [event.state for event in record.timeline],
            [
                "received",
                "quarantined",
                "scan_started",
                "scan_blocked",
                "rejected",
            ],
        )
        summary = read_model.summarize()
        self.assertEqual(summary.blocked_count, 1)
        self.assertEqual(summary.failed_closed_count, 0)

    def test_upload_safety_read_model_classifies_failed_closed_history(self):
        observed_at = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
        ledger = InMemoryUploadSafetyLedger()
        _failed_ledger_upload(ledger, upload_id="upload-failed")

        read_model = upload_safety_read_model_from_ledger(
            ledger,
            observed_at=observed_at,
        )
        record = read_model.get_record("upload-failed")
        summary = read_model.summarize()

        self.assertIsNotNone(record)
        self.assertEqual(record.final_action, "failed_closed")
        self.assertEqual(summary.blocked_count, 0)
        self.assertEqual(summary.failed_closed_count, 1)

    def test_upload_safety_read_model_does_not_double_count_plain_rejected(self):
        observed_at = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
        ledger = InMemoryUploadSafetyLedger()
        _received_ledger_upload(ledger, upload_id="upload-rejected")
        ledger.transition("upload-rejected", UploadSafetyState.REJECTED)

        read_model = upload_safety_read_model_from_ledger(
            ledger,
            observed_at=observed_at,
        )
        record = read_model.get_record("upload-rejected")
        summary = read_model.summarize()

        self.assertIsNotNone(record)
        self.assertEqual(record.final_action, "rejected")
        self.assertEqual(summary.blocked_count, 0)
        self.assertEqual(summary.failed_closed_count, 0)

    def test_upload_safety_read_model_builds_from_metadata_activity_events(self):
        with TemporaryDirectory() as temp_dir:
            with SQLiteUserActivityStore(Path(temp_dir) / "admin.sqlite3") as store:
                store.record_event(
                    _activity_event_input(
                        upload_id="upload-from-event",
                        created_job_id="job-safe",
                    )
                )
                events = store.list_events(surface=ActivitySurface.SECURITY)

        read_model = upload_safety_read_model_from_activity_events(events)
        record = read_model.get_record("upload-from-event")

        self.assertIsNotNone(record)
        self.assertEqual(record.channel_user_id, "telegram:42")
        self.assertEqual(record.final_action, "blocked")
        self.assertEqual(record.reason_code, "scan_blocked")
        self.assertEqual(record.short_hash, "01234567")
        self.assertEqual(record.job_id, "job-safe")
        self.assertEqual([event.state for event in record.timeline], ["scan_blocked"])
        self.assertIsNone(record.sanitized_original_filename)


def _record(
    *,
    upload_id: str,
    final_action: str,
    av_verdict: str,
    reason_code: str,
    sanitized_original_filename: str,
    parser_access_granted: bool = False,
    worker_access_granted: bool = False,
) -> UploadSafetyAdminRecord:
    now = datetime(2026, 5, 26, 12, 0, tzinfo=UTC)
    return UploadSafetyAdminRecord(
        upload_id=upload_id,
        created_at=now,
        updated_at=now,
        channel_user_id="telegram:42",
        declared_format="txt",
        detected_format="txt",
        size_bytes=1234,
        av_verdict=av_verdict,
        container_verdict="clean",
        final_action=final_action,
        reason_code=reason_code,
        parser_access_granted=parser_access_granted,
        worker_access_granted=worker_access_granted,
        scanner_health="healthy",
        scanner_name="local-test-scanner",
        scanner_version="1.0",
        signature_database_version="daily-test",
        signature_database_age_seconds=3600,
        sanitized_original_filename=sanitized_original_filename,
        short_hash="abc12345",
        job_id="job-safe",
        timeline=(
            UploadSafetyTimelineEvent(now, "received"),
            UploadSafetyTimelineEvent(now, "quarantined"),
            UploadSafetyTimelineEvent(now, "scan_started"),
            UploadSafetyTimelineEvent(now, "scan_blocked", reason_code),
        ),
    )


def _activity_event_input(
    *,
    upload_id: str,
    created_job_id: str | None = None,
    final_action: str = "blocked",
    av_verdict: str = "infected",
    container_verdict: str = "not_checked",
    reason_code: str = "scan_blocked",
    outcome: ActivityOutcome = ActivityOutcome.BLOCKED,
) -> UserActivityEventInput:
    return UserActivityEventInput(
        actor_type=ActivityActorType.USER,
        actor_id="telegram:42",
        channel="telegram",
        channel_user_id="42",
        surface=ActivitySurface.SECURITY,
        event_type=UPLOAD_SAFETY_ACTIVITY_EVENT_TYPE,
        action=final_action,
        target_type="upload_safety",
        target_id=upload_id,
        outcome=outcome,
        job_id=created_job_id,
        metadata={
            "upload_id": upload_id,
            "declared_format": "txt",
            "detected_format": "txt",
            "size_bytes": 1234,
            "av_verdict": av_verdict,
            "container_verdict": container_verdict,
            "final_action": final_action,
            "reason_code": reason_code,
            "parser_access_granted": False,
            "worker_access_granted": False,
            "timeline": [{"state": reason_code, "reason_code": reason_code}],
            "scanner_health": "unknown",
            "scanner_name": "local-test-scanner",
            "scanner_version": "1.0",
            "signature_database_version": "daily-test",
            "signature_database_age_seconds": None,
            "short_hash": "01234567",
        },
    )


def _blocked_ledger_upload(
    ledger: InMemoryUploadSafetyLedger,
    *,
    upload_id: str,
) -> None:
    _received_ledger_upload(ledger, upload_id=upload_id)
    ledger.transition(upload_id, UploadSafetyState.QUARANTINED)
    ledger.transition(upload_id, UploadSafetyState.SCAN_STARTED)
    ledger.transition(upload_id, UploadSafetyState.SCAN_BLOCKED)
    ledger.transition(upload_id, UploadSafetyState.REJECTED)


def _failed_ledger_upload(
    ledger: InMemoryUploadSafetyLedger,
    *,
    upload_id: str,
) -> None:
    _received_ledger_upload(ledger, upload_id=upload_id)
    ledger.transition(upload_id, UploadSafetyState.QUARANTINED)
    ledger.transition(upload_id, UploadSafetyState.SCAN_STARTED)
    ledger.transition(
        upload_id,
        UploadSafetyState.SCAN_FAILED,
        safe_error_class="scanner_timeout",
    )
    ledger.transition(upload_id, UploadSafetyState.REJECTED)


def _received_ledger_upload(
    ledger: InMemoryUploadSafetyLedger,
    *,
    upload_id: str,
) -> None:
    ledger.create_received(
        UploadSafetyMetadata(
            upload_id=upload_id,
            user_id="telegram:42",
            quarantine_object_key="quarantine/secret-object-key.txt",
            original_file_name="raw-user-filename.txt",
            document_format="txt",
            size_bytes=1234,
            sha256=(
                "0123456789abcdef0123456789abcdef"
                "0123456789abcdef0123456789abcdef"
            ),
            scanner_name="local-test-scanner",
            scanner_version="1.0",
            signature_database_version="daily-test",
        )
    )


def _assert_no_sensitive_upload_metadata(html: str) -> None:
    forbidden = (
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "quarantine/telegram-42/upload-blocked.txt",
        "quarantine/secret-object-key.txt",
        "accepted/source/upload-accepted.txt",
        "/var/lib/folioloom/quarantine/upload-blocked.txt",
        "Eicar-Test-Signature raw scanner output",
        "Traceback (most recent call last)",
        "raw document text",
    )
    for value in forbidden:
        if value in html:
            raise AssertionError(f"Sensitive upload metadata leaked: {value}")


if __name__ == "__main__":
    unittest.main()
