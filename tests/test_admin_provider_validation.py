from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.provider_validation import (
    SQLiteAIProviderValidationStore,
)


class AdminProviderValidationStoreTest(unittest.TestCase):
    def test_records_latest_provider_validation_without_secret_material(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteAIProviderValidationStore(db_path) as store:
                store.record_result(
                    provider_id="deepseek",
                    key_id="key-main",
                    status="local_check_passed",
                    error=None,
                    actor_id="owner",
                )
                store.record_result(
                    provider_id="deepseek",
                    key_id="key-backup",
                    status="failed",
                    error="secret_id=deepseek.api_keys.key-backup value=sk-raw-secret",
                    actor_id="owner",
                )

                metadata = store.latest_by_provider()

            self.assertEqual(
                metadata["deepseek"]["last_validation_status"],
                "failed",
            )
            self.assertIn("[redacted]", metadata["deepseek"]["last_error"])
            serialized = str(metadata)
            self.assertNotIn("deepseek.api_keys.key-backup", serialized)
            self.assertNotIn("sk-raw-secret", serialized)
            self.assertNotIn("secret_id", serialized)
            self.assertNotIn("key-main", serialized)

    def test_provider_metadata_aggregates_latest_status_by_key(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteAIProviderValidationStore(db_path) as store:
                store.record_result(
                    provider_id="deepseek",
                    key_id="key-main",
                    status="failed",
                    error="HTTP 401",
                    actor_id="owner",
                )
                store.record_result(
                    provider_id="deepseek",
                    key_id="key-backup",
                    status="provider_check_passed",
                    error=None,
                    actor_id="owner",
                )

                metadata = store.latest_by_provider()

            self.assertEqual(
                metadata["deepseek"]["last_validation_status"],
                "failed",
            )
            self.assertEqual(metadata["deepseek"]["last_error"], "HTTP 401")


if __name__ == "__main__":
    unittest.main()
