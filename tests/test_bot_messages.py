import unittest

from translator_service.bot.messages import (
    build_main_menu,
    build_order_estimate_message,
    build_start_message,
)
from translator_service.documents import DocumentFormat
from translator_service.order_estimates import OrderEstimate


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

    def test_order_estimate_message_shows_price_and_volume(self):
        message = build_order_estimate_message(
            OrderEstimate(
                file_name="notes.txt",
                document_format=DocumentFormat.TXT,
                character_count=36,
                estimated_input_tokens=9,
                estimated_output_tokens=11,
                fragment_count=2,
                price_usd=0.10,
            )
        )

        self.assertIn("notes.txt", message)
        self.assertIn("TXT", message)
        self.assertIn("36", message)
        self.assertIn("2", message)
        self.assertIn("$0.10", message)
        self.assertIn("Подтвердить", message)


if __name__ == "__main__":
    unittest.main()
