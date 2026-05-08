import unittest
from base64 import urlsafe_b64encode
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.secrets import SQLiteEncryptedSecretStore

MASTER_KEY = urlsafe_b64encode(b"3" * 32).decode("ascii")


class AdminAIProviderKeysTest(unittest.TestCase):
    def test_adds_multiple_provider_keys_with_metadata(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    first = keys.add_key(
                        provider_id="deepseek",
                        label="main",
                        plaintext="sk-main-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                        weight=3,
                        max_parallel_requests=2,
                    )
                    second = keys.add_key(
                        provider_id="deepseek",
                        label="backup",
                        plaintext="sk-backup-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )
                    summaries = keys.list_keys(
                        "deepseek",
                        secret_describer=secrets.describe_secret,
                    )
                    first_plaintext = secrets.get_secret_value(first.secret_id)
                    second_plaintext = secrets.get_secret_value(second.secret_id)

            self.assertEqual(
                [summary.label for summary in summaries],
                ["main", "backup"],
            )
            self.assertEqual(first.weight, 3)
            self.assertEqual(first.max_parallel_requests, 2)
            self.assertEqual(second.weight, 1)
            self.assertEqual(summaries[0].masked_value, "sk-****cret")
            self.assertEqual(summaries[1].masked_value, "sk-****cret")
            self.assertNotEqual(first.key_id, second.key_id)
            self.assertEqual(first_plaintext, "sk-main-secret")
            self.assertEqual(second_plaintext, "sk-backup-secret")

    def test_removing_key_hides_it_from_enabled_pool_and_disables_secret(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    saved = keys.add_key(
                        provider_id="deepseek",
                        label="main",
                        plaintext="sk-main-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )

                    removed = keys.remove_key(
                        provider_id="deepseek",
                        key_id=saved.key_id,
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )
                    active = keys.list_keys(
                        "deepseek",
                        secret_describer=secrets.describe_secret,
                    )
                    all_keys = keys.list_keys(
                        "deepseek",
                        secret_describer=secrets.describe_secret,
                        include_removed=True,
                    )

            self.assertFalse(removed.enabled)
            self.assertEqual(active, ())
            self.assertEqual(len(all_keys), 1)
            self.assertFalse(all_keys[0].enabled)
            self.assertTrue(all_keys[0].disabled)


if __name__ == "__main__":
    unittest.main()
