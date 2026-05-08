import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.users import (
    InMemoryUserRepository,
    SQLiteUserSettingsRepository,
    register_or_update_user,
)


class UserRegistrationTest(unittest.TestCase):
    def test_registers_new_user_from_telegram_profile(self):
        repository = InMemoryUserRepository()

        user = register_or_update_user(
            repository,
            telegram_id=42,
            username="reader",
            language_code="ru",
        )

        self.assertEqual(user.telegram_id, 42)
        self.assertEqual(user.username, "reader")
        self.assertEqual(user.language_code, "ru")
        self.assertEqual(repository.get_by_telegram_id(42), user)

    def test_updates_returning_user_profile_without_creating_duplicate(self):
        repository = InMemoryUserRepository()
        first = register_or_update_user(
            repository,
            telegram_id=42,
            username="reader",
            language_code="ru",
        )

        second = register_or_update_user(
            repository,
            telegram_id=42,
            username="reader_new",
            language_code="en",
        )

        self.assertEqual(second.telegram_id, first.telegram_id)
        self.assertEqual(second.username, "reader_new")
        self.assertEqual(second.language_code, "en")
        self.assertEqual(repository.count(), 1)


class UserSettingsTest(unittest.TestCase):
    def test_sqlite_settings_persist_interface_language_between_instances(self):
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "settings.sqlite3"
            first = SQLiteUserSettingsRepository(db_path)
            self.addCleanup(first.close)

            first.set_interface_language(telegram_id=42, language_code="ru")
            first.set_progress_preview_enabled(telegram_id=42, enabled=False)

            second = SQLiteUserSettingsRepository(db_path)
            self.addCleanup(second.close)
            settings = second.get(42)

            self.assertEqual(settings.interface_language, "ru")
            self.assertFalse(settings.progress_preview_enabled)

    def test_sqlite_settings_reset_restores_first_run_defaults(self):
        with TemporaryDirectory() as temp_dir:
            repository = SQLiteUserSettingsRepository(
                Path(temp_dir) / "settings.sqlite3"
            )
            self.addCleanup(repository.close)
            repository.set_interface_language(telegram_id=42, language_code="uk")
            repository.set_progress_preview_enabled(telegram_id=42, enabled=False)

            repository.reset(42)

            settings = repository.get(42)
            self.assertIsNone(settings.interface_language)
            self.assertTrue(settings.progress_preview_enabled)


if __name__ == "__main__":
    unittest.main()
