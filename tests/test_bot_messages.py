import unittest

from translator_service.bot.messages import build_main_menu, build_start_message


class BotMessagesTest(unittest.TestCase):
    def test_start_message_explains_translation_service_and_menu(self):
        message = build_start_message()

        self.assertIn("перевод", message.lower())
        self.assertIn("EPUB", message)
        self.assertIn("DOCX", message)
        self.assertIn("PDF", message)
        self.assertIn("TXT", message)
        self.assertIn("Перевести документ", message)
        self.assertIn("Баланс", message)

    def test_main_menu_contains_primary_user_actions(self):
        menu = build_main_menu()

        self.assertEqual(
            menu,
            [
                "Перевести документ",
                "Мои переводы",
                "Баланс",
                "Настройки",
                "Помощь",
            ],
        )


if __name__ == "__main__":
    unittest.main()
