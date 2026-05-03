import unittest

from translator_service.bot.messages import (
    CONFIRM_TRANSLATION_TEXT,
    build_language_selected_message,
    build_language_selection_message,
    build_translation_language_selection_message,
    build_main_menu,
    build_order_estimate_message,
    build_pending_translation_message,
    build_start_message,
    build_translation_job_status_message,
    is_confirm_translation_text,
)
from translator_service.bot_translation_service import PendingTranslation
from translator_service.documents import DocumentFormat
from translator_service.job_runner import TranslationJob, TranslationJobStatus
from translator_service.order_estimates import OrderEstimate


class BotMessagesTest(unittest.TestCase):
    def test_start_message_explains_translation_service_and_menu(self):
        message = build_start_message()

        self.assertIn("перевод", message.lower())
        self.assertNotIn("DeepSeek", message)
        self.assertNotIn("Дипсик", message)
        self.assertIn("EPUB", message)
        self.assertIn("DOCX", message)
        self.assertIn("PDF", message)
        self.assertIn("TXT", message)
        self.assertIn("Перевести документ", message)
        self.assertIn("Баланс", message)

    def test_start_message_is_localized_for_supported_interface_languages(self):
        expectations = {
            "ru": "Сервис перевода документов.",
            "uk": "Сервіс перекладу документів.",
            "fr": "Service de traduction de documents.",
            "es": "Servicio de traducción de documentos.",
            "en": "Document translation service.",
        }

        for language_code, expected_text in expectations.items():
            with self.subTest(language_code=language_code):
                self.assertIn(
                    expected_text,
                    build_start_message(interface_language=language_code),
                )

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

    def test_translation_job_status_message_for_ready_job(self):
        message = build_translation_job_status_message(
            TranslationJob(
                id="job-1",
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"notes",
                source_language="ru",
                target_language="en",
                status=TranslationJobStatus.READY,
                result_file_name="notes.en.txt",
            )
        )

        self.assertIn("готов", message.lower())
        self.assertIn("notes.en.txt", message)

    def test_translation_job_status_message_for_failed_job(self):
        message = build_translation_job_status_message(
            TranslationJob(
                id="job-1",
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"notes",
                source_language="ru",
                target_language="en",
                status=TranslationJobStatus.FAILED,
                error_message="provider failed",
            )
        )

        self.assertIn("ошибка", message.lower())
        self.assertIn("provider failed", message)

    def test_pending_translation_message_shows_confirm_instruction(self):
        message = build_pending_translation_message(
            PendingTranslation(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"notes",
                source_language="ru",
                target_language="en",
                price_usd=0.10,
                fragment_count=2,
            )
        )

        self.assertIn("notes.txt", message)
        self.assertIn("$0.10", message)
        self.assertIn("2", message)
        self.assertIn(CONFIRM_TRANSLATION_TEXT, message)

    def test_confirm_translation_text_accepts_button_text_and_command(self):
        self.assertTrue(is_confirm_translation_text("Подтвердить"))
        self.assertTrue(is_confirm_translation_text(" подтвердить "))
        self.assertTrue(is_confirm_translation_text("/confirm"))

    def test_confirm_translation_text_rejects_other_messages(self):
        self.assertFalse(is_confirm_translation_text("да"))
        self.assertFalse(is_confirm_translation_text("перевести"))

    def test_language_selection_message_lists_supported_languages(self):
        message = build_language_selection_message()

        self.assertIn("интерфейс", message.lower())
        self.assertIn("Русский", message)
        self.assertIn("Українська", message)
        self.assertIn("Français", message)
        self.assertIn("Español", message)
        self.assertIn("English", message)

    def test_language_selection_message_is_localized(self):
        self.assertIn(
            "Choose interface language",
            build_language_selection_message(interface_language="en"),
        )
        self.assertIn(
            "Choisissez la langue de l’interface",
            build_language_selection_message(interface_language="fr"),
        )
        self.assertIn(
            "Elige el idioma de la interfaz",
            build_language_selection_message(interface_language="es"),
        )

    def test_language_selected_message_confirms_choice(self):
        message = build_language_selected_message("Українська")

        self.assertIn("Українська", message)
        self.assertIn("интерфейс", message.lower())

    def test_language_selected_message_is_localized(self):
        self.assertIn(
            "Interface language",
            build_language_selected_message("English", interface_language="en"),
        )
        self.assertIn(
            "Langue de l’interface",
            build_language_selected_message("Français", interface_language="fr"),
        )

    def test_translation_language_selection_message_is_about_uploaded_file(self):
        message = build_translation_language_selection_message("notes.txt")

        self.assertIn("notes.txt", message)
        self.assertIn("язык перевода", message.lower())
        self.assertIn("English", message)

    def test_translation_language_selection_message_is_localized(self):
        message = build_translation_language_selection_message(
            "notes.txt",
            interface_language="en",
        )

        self.assertIn("Choose translation language", message)
        self.assertIn("notes.txt", message)

    def test_pending_translation_message_uses_localized_confirm_button(self):
        message = build_pending_translation_message(
            PendingTranslation(
                user_telegram_id=42,
                file_name="notes.txt",
                content=b"notes",
                source_language="auto",
                target_language="fr",
                price_usd=0.10,
                fragment_count=2,
            ),
            interface_language="en",
        )

        self.assertIn("Document is ready for translation", message)
        self.assertIn("Confirm", message)

    def test_confirm_translation_text_accepts_localized_buttons(self):
        self.assertTrue(is_confirm_translation_text("Подтвердить"))
        self.assertTrue(is_confirm_translation_text("Підтвердити"))
        self.assertTrue(is_confirm_translation_text("Confirmer"))
        self.assertTrue(is_confirm_translation_text("Confirmar"))
        self.assertTrue(is_confirm_translation_text("Confirm"))


if __name__ == "__main__":
    unittest.main()
