import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.audit import AuditOutcome, SQLiteAdminAuditLog
from translator_service.admin.rbac import AdminRole


class AdminAuditTest(unittest.TestCase):
    def test_records_sensitive_action_without_secret_value(self):
        with TemporaryDirectory() as temp_dir:
            with SQLiteAdminAuditLog(Path(temp_dir) / "admin.sqlite3") as audit:
                event = audit.record(
                    actor_id="bootstrap-owner",
                    role=AdminRole.OWNER,
                    action="secret.replaced",
                    target_type="integration_secret",
                    target_id="deepseek.main",
                    outcome=AuditOutcome.SUCCESS,
                    reason="changed api_key sk-live-secret-value",
                    metadata={
                        "secret": "sk-live-secret-value",
                        "fingerprint": "abc123",
                    },
                )

                events = audit.list_events(limit=10)

        self.assertEqual(events[0].id, event.id)
        self.assertEqual(events[0].action, "secret.replaced")
        self.assertNotIn("sk-live-secret-value", events[0].reason)
        self.assertNotIn("sk-live-secret-value", events[0].metadata_json)
        self.assertIn("[redacted]", events[0].reason)


if __name__ == "__main__":
    unittest.main()
