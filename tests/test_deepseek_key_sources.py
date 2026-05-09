from __future__ import annotations

import unittest
from base64 import urlsafe_b64encode
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from translator_service.admin.ai_provider_keys import SQLiteAIProviderKeyStore
from translator_service.admin.secrets import SQLiteEncryptedSecretStore
from translator_service.bot.runtime import _deepseek_channel_configs
from translator_service.config import Settings

MASTER_KEY = urlsafe_b64encode(b"6" * 32).decode("ascii")


class DeepSeekKeySourcesTest(unittest.TestCase):
    def test_runtime_uses_admin_and_env_keys_together(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "admin.sqlite3"
            settings = Settings(
                admin_db_path=str(db_path),
                admin_secret_master_key=MASTER_KEY,
            )
            with SQLiteEncryptedSecretStore(db_path, master_key=MASTER_KEY) as secrets:
                with SQLiteAIProviderKeyStore(db_path) as keys:
                    keys.add_key(
                        provider_id="deepseek",
                        label="admin-main",
                        plaintext="sk-admin-secret",
                        actor_id="bootstrap-owner",
                        secret_store=secrets,
                    )

            with patch.dict(
                "os.environ",
                {"DEEPSEEK_API_KEYS": "sk-env-one, sk-env-two"},
            ):
                channels = _deepseek_channel_configs(settings)

        self.assertEqual(
            [channel.label for channel in channels],
            ["admin-main", "deepseek-1", "deepseek-2"],
        )
        self.assertEqual(
            [channel.api_key for channel in channels],
            ["sk-admin-secret", "sk-env-one", "sk-env-two"],
        )


if __name__ == "__main__":
    unittest.main()
