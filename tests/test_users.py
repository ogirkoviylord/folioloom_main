import unittest

from translator_service.users import InMemoryUserRepository, register_or_update_user


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


if __name__ == "__main__":
    unittest.main()
