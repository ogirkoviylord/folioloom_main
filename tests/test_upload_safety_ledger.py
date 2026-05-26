import unittest
from dataclasses import fields

from translator_service.upload_safety_ledger import (
    InMemoryUploadSafetyLedger,
    UploadSafetyLedgerWriteError,
    UploadSafetyMetadata,
    UploadSafetyState,
    UploadSafetyTransitionError,
)


class UploadSafetyLedgerTest(unittest.TestCase):
    def test_records_valid_path_to_accepted_source(self):
        ledger = InMemoryUploadSafetyLedger()
        metadata = _metadata()

        ledger.create_received(metadata)
        ledger.transition("upload-1", UploadSafetyState.QUARANTINED)
        ledger.transition("upload-1", UploadSafetyState.SCAN_STARTED)
        ledger.transition("upload-1", UploadSafetyState.SCAN_CLEAN)
        ledger.transition("upload-1", UploadSafetyState.CONTAINER_STARTED)
        ledger.transition("upload-1", UploadSafetyState.CONTAINER_CLEAN)
        accepted = ledger.create_accepted_source(
            "upload-1",
            accepted_source_object_key="original/accepted-book.txt",
        )

        self.assertEqual(accepted.state, UploadSafetyState.ACCEPTED_SOURCE_CREATED)
        self.assertEqual(
            accepted.accepted_source_object_key,
            "original/accepted-book.txt",
        )
        self.assertEqual(
            ledger.parser_access_decision("upload-1").accepted_source_object_key,
            "original/accepted-book.txt",
        )

    def test_state_enum_supports_required_issue_states(self):
        self.assertEqual(
            {state.value for state in UploadSafetyState},
            {
                "received",
                "quarantined",
                "scan_started",
                "scan_clean",
                "scan_blocked",
                "scan_failed",
                "container_started",
                "container_clean",
                "container_blocked",
                "container_failed",
                "accepted_source_created",
                "rejected",
                "quarantine_expired",
                "quarantine_deleted",
            },
        )

    def test_rejects_accepted_source_before_clean_scan_and_container(self):
        ledger = InMemoryUploadSafetyLedger()
        ledger.create_received(_metadata())
        ledger.transition("upload-1", UploadSafetyState.QUARANTINED)
        ledger.transition("upload-1", UploadSafetyState.SCAN_STARTED)
        ledger.transition("upload-1", UploadSafetyState.SCAN_CLEAN)

        with self.assertRaises(UploadSafetyTransitionError):
            ledger.create_accepted_source(
                "upload-1",
                accepted_source_object_key="original/unsafe.txt",
            )

    def test_blocked_or_failed_states_cannot_grant_parser_or_worker_access(self):
        for terminal_state in (
            UploadSafetyState.SCAN_BLOCKED,
            UploadSafetyState.SCAN_FAILED,
            UploadSafetyState.CONTAINER_BLOCKED,
            UploadSafetyState.CONTAINER_FAILED,
        ):
            with self.subTest(terminal_state=terminal_state):
                ledger = InMemoryUploadSafetyLedger()
                ledger.create_received(_metadata(upload_id=f"upload-{terminal_state}"))
                ledger.transition(
                    f"upload-{terminal_state}",
                    UploadSafetyState.QUARANTINED,
                )
                if terminal_state in {
                    UploadSafetyState.CONTAINER_BLOCKED,
                    UploadSafetyState.CONTAINER_FAILED,
                }:
                    ledger.transition(
                        f"upload-{terminal_state}",
                        UploadSafetyState.SCAN_STARTED,
                    )
                    ledger.transition(
                        f"upload-{terminal_state}",
                        UploadSafetyState.SCAN_CLEAN,
                    )
                    ledger.transition(
                        f"upload-{terminal_state}",
                        UploadSafetyState.CONTAINER_STARTED,
                    )
                else:
                    ledger.transition(
                        f"upload-{terminal_state}",
                        UploadSafetyState.SCAN_STARTED,
                    )

                ledger.transition(f"upload-{terminal_state}", terminal_state)

                self.assertFalse(
                    ledger.parser_access_decision(
                        f"upload-{terminal_state}",
                    ).allowed
                )
                self.assertFalse(
                    ledger.worker_access_decision(
                        f"upload-{terminal_state}",
                    ).allowed
                )
                with self.assertRaises(UploadSafetyTransitionError):
                    ledger.create_accepted_source(
                        f"upload-{terminal_state}",
                        accepted_source_object_key="original/blocked.txt",
                    )

    def test_unscanned_upload_is_not_accepted(self):
        ledger = InMemoryUploadSafetyLedger()
        ledger.create_received(_metadata())
        ledger.transition("upload-1", UploadSafetyState.QUARANTINED)

        with self.assertRaises(UploadSafetyTransitionError):
            ledger.transition("upload-1", UploadSafetyState.CONTAINER_STARTED)

        self.assertFalse(ledger.parser_access_decision("upload-1").allowed)

    def test_metadata_model_does_not_require_or_store_raw_document_text(self):
        metadata = _metadata(original_file_name="manuscript.txt")
        field_names = {field.name for field in fields(UploadSafetyMetadata)}

        self.assertNotIn("raw_document_text", field_names)
        self.assertNotIn("source_text", field_names)
        self.assertNotIn("content", field_names)
        self.assertEqual(metadata.original_file_name, "manuscript.txt")

    def test_store_write_failure_denies_access_fail_closed(self):
        ledger = InMemoryUploadSafetyLedger(fail_writes=True)

        with self.assertRaises(UploadSafetyLedgerWriteError):
            ledger.create_received(_metadata())

        decision = ledger.parser_access_decision("upload-1")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "ledger_missing")


def _metadata(
    *,
    upload_id: str = "upload-1",
    original_file_name: str = "book.txt",
) -> UploadSafetyMetadata:
    return UploadSafetyMetadata(
        upload_id=upload_id,
        user_id="telegram:42",
        quarantine_object_key=f"quarantine/{upload_id}.txt",
        original_file_name=original_file_name,
        document_format="txt",
        size_bytes=1024,
        sha256="a" * 64,
    )


if __name__ == "__main__":
    unittest.main()
