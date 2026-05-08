from __future__ import annotations

import unittest
from base64 import urlsafe_b64encode
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.integration_connections import (
    SQLiteIntegrationConnectionStore,
)
from translator_service.admin.integrations import DEFAULT_INTEGRATION_REGISTRY
from translator_service.admin.secrets import (
    SecretNotFound,
    SQLiteEncryptedSecretStore,
)

MASTER_KEY = urlsafe_b64encode(b"2" * 32).decode("ascii")


class AdminIntegrationConnectionsTest(unittest.TestCase):
    def test_adds_multiple_connections_for_one_integration(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            telegram = DEFAULT_INTEGRATION_REGISTRY.get_definition("telegram")

            with SQLiteEncryptedSecretStore(
                db_path,
                master_key=MASTER_KEY,
            ) as secrets:
                with SQLiteIntegrationConnectionStore(db_path) as connections:
                    stable = connections.add_connection(
                        definition=telegram,
                        label="stable",
                        secret_values={"telegram.bot_token": "111:stable-token"},
                        actor_id="owner",
                        secret_store=secrets,
                    )
                    dev = connections.add_connection(
                        definition=telegram,
                        label="dev",
                        secret_values={"telegram.bot_token": "222:dev-token"},
                        actor_id="owner",
                        secret_store=secrets,
                    )

                    rows = connections.list_connections(
                        telegram,
                        secret_describer=secrets.describe_secret,
                    )

            self.assertEqual([row.label for row in rows], ["stable", "dev"])
            self.assertNotEqual(
                stable.secret_values[0].secret_id,
                dev.secret_values[0].secret_id,
            )
            self.assertTrue(all(row.enabled for row in rows))
            self.assertEqual(rows[0].secret_values[0].masked_value, "111****oken")
            self.assertEqual(rows[1].secret_values[0].masked_value, "222****oken")

    def test_remove_connection_disables_only_its_secrets(self):
        with TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "admin.sqlite3")
            telegram = DEFAULT_INTEGRATION_REGISTRY.get_definition("telegram")

            with SQLiteEncryptedSecretStore(
                db_path,
                master_key=MASTER_KEY,
            ) as secrets:
                with SQLiteIntegrationConnectionStore(db_path) as connections:
                    stable = connections.add_connection(
                        definition=telegram,
                        label="stable",
                        secret_values={"telegram.bot_token": "111:stable-token"},
                        actor_id="owner",
                        secret_store=secrets,
                    )
                    dev = connections.add_connection(
                        definition=telegram,
                        label="dev",
                        secret_values={"telegram.bot_token": "222:dev-token"},
                        actor_id="owner",
                        secret_store=secrets,
                    )

                    removed = connections.remove_connection(
                        definition=telegram,
                        connection_id=stable.connection_id,
                        actor_id="owner",
                        secret_store=secrets,
                    )
                    active_rows = connections.list_connections(
                        telegram,
                        secret_describer=secrets.describe_secret,
                    )
                    all_rows = connections.list_connections(
                        telegram,
                        secret_describer=secrets.describe_secret,
                        include_removed=True,
                    )

                    with self.assertRaises(SecretNotFound):
                        secrets.get_secret_value(stable.secret_values[0].secret_id)
                    self.assertEqual(
                        secrets.get_secret_value(dev.secret_values[0].secret_id),
                        "222:dev-token",
                    )

            self.assertFalse(removed.enabled)
            self.assertEqual([row.label for row in active_rows], ["dev"])
            self.assertEqual([row.label for row in all_rows], ["stable", "dev"])


if __name__ == "__main__":
    unittest.main()
