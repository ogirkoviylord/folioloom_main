import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.secrets import (
    SecretStoreUnavailable,
    SQLiteEncryptedSecretStore,
)

MASTER_KEY = base64.urlsafe_b64encode(b"1" * 32).decode("ascii")


class AdminSecretsTest(unittest.TestCase):
    def test_stores_encrypted_secret_and_returns_metadata(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as store:
                metadata = store.put_secret(
                    secret_id="deepseek.main",
                    label="DeepSeek main",
                    kind="api_key",
                    plaintext="sk-secret-value",
                    actor_id="bootstrap-owner",
                )
                loaded = store.describe_secret("deepseek.main")
                plaintext = store.get_secret_value("deepseek.main")
            raw_db = db_path.read_bytes()

        self.assertEqual(metadata.secret_id, "deepseek.main")
        self.assertEqual(loaded.masked_value, "sk-****alue")
        self.assertEqual(plaintext, "sk-secret-value")
        self.assertNotIn(b"sk-secret-value", raw_db)

    def test_replacement_increments_version(self):
        with SQLiteEncryptedSecretStore(":memory:", master_key=MASTER_KEY) as store:
            first = store.put_secret(
                secret_id="telegram.prod",
                label="Telegram production",
                kind="bot_token",
                plaintext="123456:old-token",
                actor_id="bootstrap-owner",
            )
            second = store.put_secret(
                secret_id="telegram.prod",
                label="Telegram production",
                kind="bot_token",
                plaintext="123456:new-token",
                actor_id="bootstrap-owner",
            )

            self.assertEqual(first.version, 1)
            self.assertEqual(second.version, 2)
            self.assertEqual(
                store.get_secret_value("telegram.prod"),
                "123456:new-token",
            )

    def test_missing_master_key_fails_closed(self):
        with self.assertRaises(SecretStoreUnavailable):
            SQLiteEncryptedSecretStore(":memory:", master_key="")


if __name__ == "__main__":
    unittest.main()
