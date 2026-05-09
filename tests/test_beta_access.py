import unittest
from unittest.mock import patch

from translator_service.beta_access import BetaAccessDenied, BetaAccessPolicy
from translator_service.config import Settings


class BetaAccessTest(unittest.TestCase):
    def test_disabled_allowlist_allows_everyone_even_with_ids(self):
        policy = BetaAccessPolicy.from_telegram_ids((42,), enabled=False)

        policy.assert_allowed(42)
        policy.assert_allowed(100)

    def test_enabled_allowlist_blocks_unlisted_telegram_user(self):
        policy = BetaAccessPolicy.from_telegram_ids((42, 100), enabled=True)

        policy.assert_allowed(42)
        with self.assertRaises(BetaAccessDenied):
            policy.assert_allowed(101)

    def test_settings_parse_beta_allowlist_from_env(self):
        with patch.dict(
            "os.environ",
            {"BETA_ALLOWLIST_TELEGRAM_IDS": "42, 100  ,bad, -7, 42"},
            clear=False,
        ):
            settings = Settings()

        self.assertEqual(settings.beta_allowlist_telegram_ids, (42, 100))

    def test_settings_parse_beta_allowlist_enabled_from_env(self):
        with patch.dict(
            "os.environ",
            {"BETA_ALLOWLIST_ENABLED": "true"},
            clear=False,
        ):
            settings = Settings()

        self.assertTrue(settings.beta_allowlist_enabled)


if __name__ == "__main__":
    unittest.main()
