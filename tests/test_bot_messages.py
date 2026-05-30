import unittest
from importlib.util import find_spec

from translator_service.bot.messages import (
    build_back_to_menu_message,
    build_cancel_requested_message,
    build_duplicate_upload_message,
    build_help_message,
    build_how_it_works_message,
    build_language_selected_message,
    build_language_selection_message,
    build_main_menu,
    build_my_book_detail_message,
    build_my_books_message,
    build_nothing_to_cancel_message,
    build_order_estimate_message,
    build_pending_translation_message,
    build_preview_translation_message,
    build_rights_confirmation_message,
    build_settings_message,
    build_start_message,
    build_translation_job_status_message,
    build_translation_language_selection_message,
    build_translation_mode_selection_message,
    build_translation_progress_message,
    build_unknown_text_message,
    build_upload_error_message,
    build_upload_prompt_message,
    get_back_text,
    get_cancel_text,
    get_confirm_rights_text,
    get_main_menu_text,
    get_progress_activity_phrase,
    get_toggle_progress_preview_text,
    is_back_text,
    is_cancel_text,
    is_confirm_rights_text,
    is_confirm_translation_text,
    is_continue_translation_text,
    is_help_text,
    is_how_it_works_text,
    is_language_menu_text,
    is_main_menu_text,
    is_my_books_text,
    is_settings_text,
    is_toggle_progress_preview_text,
    is_translate_book_text,
    translation_mode_for_button_text,
)
from translator_service.bot_translation_service import (
    TRANSLATION_MODE_BOOK_MANUSCRIPT,
    TRANSLATION_MODE_DOCUMENT_FORM,
    DuplicatePreviewError,
    PendingTranslation,
    PreviewTranslation,
)
from translator_service.documents import DocumentFormat
from translator_service.job_runner import (
    DocumentKind,
    TranslationJob,
    TranslationJobStatus,
)
from translator_service.order_estimates import OrderEstimate


class BotMessagesTest(unittest.TestCase):
    def test_start_message_explains_translation_service_without_repeating_menu_buttons(self):
        message = build_start_message()

        self.assertIn("Welcome to FolioLoom", message)
        self.assertIn("Books, beautifully translated.", message)
        self.assertIn("Choose what you’d like to do.", message)
        self.assertNotIn("DeepSeek", message)
        self.assertNotIn("Дипсик", message)
        self.assertIn("EPUB", message)
        self.assertIn("DOCX", message)
        self.assertIn("TXT", message)
        self.assertNotIn("PDF", message)
        self.assertNotIn("📖 Translate a Book", message)
        self.assertNotIn("🧵 How It Works", message)
        self.assertNotIn("🌍 Language", message)
        self.assertNotIn("Balance", message)

    def test_start_message_is_localized_for_supported_interface_languages(self):
        expectations = {
            "ru": "Добро пожаловать в FolioLoom.",
            "uk": "Ласкаво просимо до FolioLoom.",
            "fr": "Bienvenue dans FolioLoom.",
            "es": "Bienvenido a FolioLoom.",
            "en": "Welcome to FolioLoom.",
            "nl": "Welkom bij FolioLoom.",
        }

        for language_code, expected_text in expectations.items():
            with self.subTest(language_code=language_code):
                self.assertIn(
                    expected_text,
                    build_start_message(interface_language=language_code),
                )

    def test_duplicate_preview_error_uses_specific_safe_message(self):
        message = build_upload_error_message(
            DuplicatePreviewError(
                "Preview has already been generated for this document."
            ),
            interface_language="uk",
        )

        self.assertIn("Попередній перегляд", message)
        self.assertIn("вже підготовлено", message)
        self.assertNotIn("Під час перекладу щось пішло не так", message)
        self.assertNotIn("Preview has already been generated", message)

    def test_duplicate_upload_messages_are_neutral_and_localized(self):
        ready_match = type("Match", (), {"status": "ready"})()
        active_match = type("Match", (), {"status": "queued"})()

        english = build_duplicate_upload_message(ready_match, "en")
        russian = build_duplicate_upload_message(ready_match, "ru")
        ukrainian = build_duplicate_upload_message(active_match, "uk")

        self.assertIn("has already been translated", english)
        self.assertIn("translate it again as a new attempt", english)
        self.assertIn("уже переводился", russian)
        self.assertIn("новую попытку", russian)
        self.assertIn("уже виконується", ukrainian)
        self.assertNotIn("bad", english.lower())
        self.assertNotIn("incomplete", english.lower())

    def test_main_menu_contains_primary_user_actions(self):
        self.assertEqual(
            build_main_menu(),
            [
                "📖 Translate a Book",
                "📚 My Books",
                "🧵 How It Works",
                "🌍 Language",
                "⚙️ Settings",
                "Help",
            ],
        )
        self.assertEqual(
            build_main_menu("nl"),
            [
                "📖 Boek vertalen",
                "📚 Mijn boeken",
                "🧵 Zo werkt het",
                "🌍 Taal",
                "⚙️ Instellingen",
                "Hulp",
            ],
        )
        self.assertEqual(
            build_main_menu("ru"),
            [
                "📖 Перевести книгу",
                "📚 Мои книги",
                "🧵 Как это работает",
                "🌍 Язык",
                "⚙️ Настройки",
                "Помощь",
            ],
        )

    def test_settings_message_shows_preview_preference_and_language(self):
        message = build_settings_message(
            interface_language="en",
            progress_preview_enabled=True,
        )

        self.assertIn("Settings", message)
        self.assertIn("Latest passage preview: On", message)
        self.assertIn("Interface language: English", message)
        self.assertEqual(get_toggle_progress_preview_text("en", True), "Hide Preview")
        self.assertEqual(get_toggle_progress_preview_text("en", False), "Show Preview")

    def test_settings_message_is_localized(self):
        message = build_settings_message(
            interface_language="ru",
            progress_preview_enabled=False,
        )

        self.assertIn("Настройки", message)
        self.assertIn("Последний отрывок: выключен", message)
        self.assertIn("Язык интерфейса: Русский", message)
        self.assertEqual(get_toggle_progress_preview_text("ru", False), "Показывать отрывок")

    def test_my_books_message_shows_empty_state_and_recent_books(self):
        self.assertIn("No books yet", build_my_books_message([], "en"))
        message = build_my_books_message(
            [
                {
                    "job_id": "job-1",
                    "file_name": "book.epub",
                    "source_language": "en",
                    "target_language": "uk",
                    "status": "ready",
                    "has_result": True,
                },
                {
                    "job_id": "job-2",
                    "file_name": "draft.docx",
                    "source_language": "en",
                    "target_language": "ru",
                    "status": "cancelled",
                    "has_result": False,
                },
            ],
            "en",
        )

        self.assertIn("My Books", message)
        self.assertIn("Last Book: book.epub", message)
        self.assertIn("book.epub", message)
        self.assertIn("English -> Ukrainian", message)
        self.assertIn("Ready", message)
        self.assertIn("download available", message)
        self.assertIn("draft.docx", message)
        self.assertTrue(is_my_books_text("📚 My Books"))
        self.assertTrue(is_my_books_text("📚 Мои книги"))

    def test_my_books_message_shows_active_queue_summary(self):
        message = build_my_books_message(
            [
                {
                    "job_id": "job-1",
                    "file_name": "queued.epub",
                    "source_language": "en",
                    "target_language": "uk",
                    "status": "queued",
                    "has_result": False,
                }
            ],
            "en",
            queue_summary={
                "total_active": 1,
                "queued": 1,
                "translating": 0,
                "items": [
                    {
                        "file_name": "queued.epub",
                        "status": "queued",
                    }
                ],
            },
        )

        self.assertIn("Queue", message)
        self.assertIn("1 active", message)
        self.assertIn("queued.epub", message)

    def test_my_book_detail_message_shows_status_and_available_actions(self):
        message = build_my_book_detail_message(
            {
                "file_name": "book.epub",
                "document_kind": "epub",
                "source_language": "en",
                "target_language": "uk",
                "status": "cancelled",
                "has_result": True,
                "has_partial_result": True,
                "can_resume": True,
            },
            "en",
        )

        self.assertIn("Book Details", message)
        self.assertIn("book.epub", message)
        self.assertIn("EPUB", message)
        self.assertIn("English -> Ukrainian", message)
        self.assertIn("Cancelled", message)
        self.assertIn("Partial download available", message)
        self.assertIn("This translation can be continued", message)

    def test_help_and_how_it_works_have_distinct_roles(self):
        help_message = build_help_message("en")
        how_message = build_how_it_works_message("en")

        self.assertIn("Good to know", help_message)
        self.assertIn("Very large books", help_message)
        self.assertIn("EPUB", help_message)
        self.assertNotIn("1. Send", help_message)
        self.assertIn("1. Send", how_message)
        self.assertIn("5. Download", how_message)
        self.assertIn("chapters, paragraphs", how_message)
        self.assertNotIn("Good to know", how_message)

    def test_help_and_how_it_works_roles_are_localized(self):
        expectations = {
            "ru": ("Полезно знать", "1. Отправьте"),
            "uk": ("Корисно знати", "1. Надішліть"),
            "fr": ("À savoir", "1. Envoyez"),
            "es": ("Conviene saber", "1. Envía"),
            "nl": ("Goed om te weten", "1. Stuur"),
        }

        for language_code, (help_marker, how_marker) in expectations.items():
            with self.subTest(language_code=language_code):
                self.assertIn(help_marker, build_help_message(language_code))
                self.assertIn(how_marker, build_how_it_works_message(language_code))

    def test_order_estimate_message_hides_price_from_user_ui(self):
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
        self.assertNotIn("Fragments", message)
        self.assertNotIn("$0.10", message)
        self.assertNotIn("Price", message)
        self.assertIn("Start Translation", message)

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

        self.assertIn("translation is ready", message.lower())
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
                error_message="DeepSeek API request failed",
            )
        )

        self.assertIn("something went wrong", message.lower())
        self.assertNotIn("DeepSeek", message)
        self.assertNotIn("API", message)

    def test_translation_job_status_message_for_cancelled_job(self):
        message = build_translation_job_status_message(
            TranslationJob(
                id="job-1",
                user_telegram_id=42,
                file_name="book.epub",
                content=b"book",
                source_language="en",
                target_language="uk",
                status=TranslationJobStatus.CANCELLED,
                result_file_name="book.uk.partial.epub",
            ),
            interface_language="en",
        )

        self.assertIn("cancelled", message.lower())
        self.assertIn("book.uk.partial.epub", message)

    def test_partial_status_message_uses_neutral_recovery_copy(self):
        disallowed_fragments = {
            "en": ("problematic", "quality"),
            "ru": ("проблемн", "качество"),
            "uk": ("проблемн", "якість"),
            "fr": ("probl", "qualité"),
            "es": ("problem", "calidad"),
            "nl": ("problem", "kwaliteit"),
        }

        for language_code, fragments in disallowed_fragments.items():
            with self.subTest(language_code=language_code):
                message = build_translation_job_status_message(
                    TranslationJob(
                        id="job-1",
                        user_telegram_id=42,
                        file_name="book.epub",
                        content=b"book",
                        source_language="en",
                        target_language="uk",
                        status=TranslationJobStatus.PARTIAL,
                        result_file_name="book.uk.partial.epub",
                    ),
                    interface_language=language_code,
                )

                self.assertIn("book.uk.partial.epub", message)
                lowered = message.lower()
                for fragment in fragments:
                    self.assertNotIn(fragment, lowered)

    def test_translation_job_status_message_for_cancelled_job_without_result(self):
        message = build_translation_job_status_message(
            TranslationJob(
                id="job-1",
                user_telegram_id=42,
                file_name="book.epub",
                content=b"book",
                source_language="en",
                target_language="uk",
                status=TranslationJobStatus.CANCELLED,
                result_file_name=None,
            ),
            interface_language="en",
        )

        self.assertIn("cancelled", message.lower())
        self.assertIn("partial result is not available yet", message)
        self.assertIn("before any passage was translated", message)
        self.assertNotIn("Partial result:", message)
        self.assertNotIn("partial.epub", message)
        self.assertNotIn("DeepSeek", message)
        self.assertNotIn("/var/", message)

    def test_cancelled_without_result_message_is_localized(self):
        expectations = {
            "ru": "Частичный результат пока недоступен",
            "uk": "Частковий результат ще недоступний",
            "fr": "Aucun résultat partiel",
            "es": "Todavía no hay un resultado parcial",
            "nl": "geen gedeeltelijk resultaat beschikbaar",
        }

        for language_code, expected_text in expectations.items():
            with self.subTest(language_code=language_code):
                message = build_translation_job_status_message(
                    TranslationJob(
                        id="job-1",
                        user_telegram_id=42,
                        file_name="book.epub",
                        content=b"book",
                        source_language="en",
                        target_language="uk",
                        status=TranslationJobStatus.CANCELLED,
                    ),
                    interface_language=language_code,
                )

                self.assertIn(expected_text, message)
                self.assertNotIn("partial result", message.lower())

    def test_translation_job_status_message_for_admin_paused_and_deleted_jobs(self):
        paused = build_translation_job_status_message(
            TranslationJob(
                id="job-1",
                user_telegram_id=42,
                file_name="book.epub",
                content=b"book",
                source_language="en",
                target_language="uk",
                status=TranslationJobStatus.PAUSED,
            ),
            interface_language="en",
        )
        deleted = build_translation_job_status_message(
            TranslationJob(
                id="job-1",
                user_telegram_id=42,
                file_name="book.epub",
                content=b"book",
                source_language="en",
                target_language="uk",
                status=TranslationJobStatus.DELETED,
            ),
            interface_language="en",
        )

        self.assertIn("paused by an admin", paused.lower())
        self.assertIn("deleted by an admin", deleted.lower())

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
                estimated_seconds=24,
            )
        )

        self.assertIn("notes.txt", message)
        self.assertNotIn("$0.10", message)
        self.assertNotIn("Price", message)
        self.assertNotIn("Fragments", message)
        self.assertIn("24 sec", message)
        self.assertIn("Start Translation", message)

    def test_pending_translation_message_localizes_duration_and_language_names(self):
        message = build_pending_translation_message(
            PendingTranslation(
                user_telegram_id=42,
                file_name="boek.docx",
                content=b"notes",
                source_language="auto",
                target_language="nl",
                price_usd=0.10,
                fragment_count=2,
                source_language_display="Dutch",
                estimated_seconds=3661,
            ),
            interface_language="ru",
        )

        self.assertIn("С языка: Нидерландский", message)
        self.assertIn("На язык: Нидерландский", message)
        self.assertIn("Примерное время: 1 ч 1 мин", message)

    def test_rights_confirmation_message_is_localized(self):
        expectations = {
            "en": "right to translate this document",
            "ru": "есть право переводить этот документ",
            "uk": "маєте право перекладати цей документ",
            "fr": "droit de traduire ce document",
            "es": "derecho a traducir este documento",
            "nl": "recht hebt om dit document te vertalen",
        }

        for language_code, expected_text in expectations.items():
            with self.subTest(language_code=language_code):
                message = build_rights_confirmation_message(
                    "book.txt",
                    language_code,
                )
                self.assertIn(expected_text, message)
                self.assertIn("book.txt", message)

    def test_confirm_rights_text_accepts_localized_buttons(self):
        expectations = {
            "en": "✅ I confirm the rights",
            "ru": "✅ Подтверждаю права",
            "uk": "✅ Підтверджую права",
            "fr": "✅ Je confirme les droits",
            "es": "✅ Confirmo los derechos",
            "nl": "✅ Ik bevestig de rechten",
        }

        for language_code, expected_text in expectations.items():
            with self.subTest(language_code=language_code):
                self.assertEqual(get_confirm_rights_text(language_code), expected_text)
                self.assertTrue(is_confirm_rights_text(expected_text))
        self.assertFalse(is_confirm_rights_text("Start Translation"))

    def test_confirm_translation_text_accepts_button_text_and_command(self):
        self.assertTrue(is_confirm_translation_text("Подтвердить"))
        self.assertTrue(is_confirm_translation_text(" подтвердить "))
        self.assertTrue(is_confirm_translation_text("Start Translation"))
        self.assertTrue(is_confirm_translation_text("/confirm"))

    def test_confirm_translation_text_rejects_other_messages(self):
        self.assertFalse(is_confirm_translation_text("да"))
        self.assertFalse(is_confirm_translation_text("перевести"))

    def test_confirm_translation_text_rejects_missing_message_text(self):
        self.assertFalse(is_confirm_translation_text(None))

    def test_language_selection_message_lists_supported_languages(self):
        message = build_language_selection_message()

        self.assertIn("interface", message.lower())
        self.assertIn("Русский", message)
        self.assertIn("Українська", message)
        self.assertIn("Français", message)
        self.assertIn("Español", message)
        self.assertIn("English", message)
        self.assertIn("Nederlands", message)

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
        self.assertIn(
            "Kies de interfacetaal",
            build_language_selection_message(interface_language="nl"),
        )

    def test_language_selected_message_confirms_choice(self):
        message = build_language_selected_message("Українська")

        self.assertIn("Українська", message)
        self.assertIn("Interface language", message)

    def test_language_selected_message_is_localized(self):
        self.assertIn(
            "Interface language",
            build_language_selected_message("English", interface_language="en"),
        )
        self.assertIn(
            "Langue de l’interface",
            build_language_selected_message("Français", interface_language="fr"),
        )
        self.assertIn(
            "Interfacetaal",
            build_language_selected_message("Nederlands", interface_language="nl"),
        )

    def test_translation_language_selection_message_is_about_uploaded_file(self):
        message = build_translation_language_selection_message("notes.txt")

        self.assertIn("notes.txt", message)
        self.assertIn("Choose the target language", message)
        self.assertIn("English", message)

    def test_translation_language_selection_message_is_localized(self):
        message = build_translation_language_selection_message(
            "notes.txt",
            interface_language="en",
        )

        self.assertIn("Choose the target language", message)
        self.assertIn("notes.txt", message)

    def test_translation_mode_selection_message_localizes_labels_help_and_scope(self):
        expectations = {
            "en": ("Document / form", "Book / manuscript", "statements"),
            "ru": (
                "Документ / форма",
                "Книга / рукопись",
                "заявлений",
            ),
            "uk": (
                "Документ / форма",
                "Книга / рукопис",
                "заяв",
            ),
            "fr": (
                "Document / formulaire",
                "Livre / manuscrit",
                "déclarations",
            ),
            "es": (
                "Documento / formulario",
                "Libro / manuscrito",
                "declaraciones",
            ),
            "nl": (
                "Document / formulier",
                "Boek / manuscript",
                "verklaringen",
            ),
        }

        for (
            language_code,
            (document_label, book_label, help_marker),
        ) in expectations.items():
            with self.subTest(language_code=language_code):
                message = build_translation_mode_selection_message(
                    "application.docx",
                    interface_language=language_code,
                    source_language_display="Ukrainian",
                )

                self.assertIn(document_label, message)
                self.assertIn(book_label, message)
                self.assertIn(help_marker, message)
                self.assertIn("EPUB, DOCX, TXT", message)
                self.assertNotIn("PDF", message)
                self.assertNotIn("FB2", message)
                self.assertNotIn("MOBI", message)
                self.assertNotIn("OCR", message)
                self.assertNotIn("DeepSeek", message)
                self.assertNotIn("provider", message.lower())
                self.assertEqual(
                    translation_mode_for_button_text(document_label),
                    TRANSLATION_MODE_DOCUMENT_FORM,
                )
                self.assertEqual(
                    translation_mode_for_button_text(book_label),
                    TRANSLATION_MODE_BOOK_MANUSCRIPT,
                )

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
                source_language_display="French",
                estimated_seconds=24,
            ),
            interface_language="en",
        )

        self.assertIn("Ready to begin", message)
        self.assertIn("From: French", message)
        self.assertIn("To: French", message)
        self.assertIn("Estimated time: 24 sec", message)
        self.assertIn("Start Translation", message)

    def test_pending_translation_message_summarizes_selected_document_form_mode(self):
        message = build_pending_translation_message(
            PendingTranslation(
                user_telegram_id=42,
                file_name="application.docx",
                content=b"notes",
                source_language="uk",
                target_language="ru",
                price_usd=0.10,
                fragment_count=2,
                source_language_display="Ukrainian",
                estimated_seconds=24,
                translation_mode=TRANSLATION_MODE_DOCUMENT_FORM,
            ),
            interface_language="en",
        )

        self.assertIn("Mode: Document / form", message)
        self.assertIn("structure, labels, tables", message)
        self.assertIn("protected fields", message)
        self.assertNotIn("$0.10", message)
        self.assertNotIn("Price", message)
        self.assertNotIn("PDF", message)
        self.assertNotIn("FB2", message)
        self.assertNotIn("DeepSeek", message)

    def test_pending_translation_message_summarizes_selected_book_mode_locally(self):
        message = build_pending_translation_message(
            PendingTranslation(
                user_telegram_id=42,
                file_name="manuscript.txt",
                content=b"notes",
                source_language="en",
                target_language="ru",
                price_usd=0.10,
                fragment_count=2,
                source_language_display="English",
                estimated_seconds=24,
                translation_mode=TRANSLATION_MODE_BOOK_MANUSCRIPT,
            ),
            interface_language="ru",
        )

        self.assertIn("Режим: Книга / рукопись", message)
        self.assertIn("авторский голос", message)
        self.assertNotIn("PDF", message)
        self.assertNotIn("FB2", message)
        self.assertNotIn("DeepSeek", message)

    def test_preview_translation_message_shows_snippet_and_free_beta_placeholder(self):
        message = build_preview_translation_message(
            PreviewTranslation(
                preview_id="preview:42:abc",
                user_telegram_id=42,
                file_name="notes.txt",
                document_kind=DocumentKind.TXT,
                source_language="en",
                target_language="ru",
                text="Translated <sample>",
                prompt_tokens=10,
                completion_tokens=5,
                estimated_cost_usd=0.01,
                beta_safety_reason_code=None,
                metadata={},
            ),
            interface_language="ru",
        )

        self.assertIn("Предпросмотр перевода", message)
        self.assertIn("Стоимость: ???", message)
        self.assertIn("<blockquote>Translated &lt;sample&gt;</blockquote>", message)
        self.assertNotIn("$", message)
        self.assertNotIn("Оплатить", message)

    def test_continue_translation_text_accepts_localized_buttons(self):
        self.assertTrue(is_continue_translation_text("Continue Translation"))
        self.assertTrue(is_continue_translation_text("Продолжить перевод"))
        self.assertFalse(is_continue_translation_text("Start Translation"))

    def test_translation_language_selection_message_shows_detected_source_language(self):
        message = build_translation_language_selection_message(
            "book.epub",
            interface_language="en",
            source_language_display="English",
        )

        self.assertIn("book.epub", message)
        self.assertIn("Source language: English", message)

    def test_translation_language_selection_message_localizes_detected_source_language(self):
        message = build_translation_language_selection_message(
            "boek.docx",
            interface_language="ru",
            source_language_display="Dutch",
        )

        self.assertIn("Язык оригинала: Нидерландский", message)

    def test_translation_language_selection_message_localizes_admixtures(self):
        message = build_translation_language_selection_message(
            "mixed.docx",
            interface_language="ru",
            source_language_display="Russian (admixtures: English, Dutch)",
        )

        self.assertIn(
            "Язык оригинала: Русский; примеси: Английский, Нидерландский",
            message,
        )

    def test_translation_progress_message_shows_percent_and_bar_without_fragment_count(self):
        message = build_translation_progress_message(
            completed_fragments=3,
            total_fragments=10,
            interface_language="en",
            estimated_total_seconds=100,
            elapsed_seconds=30,
            last_translated_text="Translated paragraph from the document.",
        )

        self.assertIn("Translation progress", message)
        self.assertNotIn("3/10", message)
        self.assertIn("30%", message)
        self.assertIn("Elapsed: 30 sec", message)
        self.assertIn("Time left: ~1 min 10 sec", message)
        self.assertIn("Working through the text ⠋", message)
        self.assertIn("Latest translated passage", message)
        self.assertIn("<blockquote expandable>", message)
        self.assertIn("</blockquote>", message)
        self.assertIn("Translated paragraph from the document.", message)
        self.assertIn("/cancel", message)

    def test_translation_progress_message_uses_elapsed_estimate_before_first_fragment(self):
        message = build_translation_progress_message(
            completed_fragments=0,
            total_fragments=10,
            interface_language="en",
            estimated_total_seconds=100,
            elapsed_seconds=40,
        )

        self.assertIn("[####------] 40%", message)

    def test_translation_progress_message_escapes_expandable_quote_excerpt(self):
        message = build_translation_progress_message(
            completed_fragments=1,
            total_fragments=2,
            interface_language="en",
            elapsed_seconds=5,
            last_translated_text="A <chapter> & a note",
        )

        self.assertIn("<blockquote expandable>A &lt;chapter&gt; &amp; a note</blockquote>", message)
        self.assertNotIn("A <chapter> & a note", message)

    def test_translation_progress_message_localizes_time_units(self):
        message = build_translation_progress_message(
            completed_fragments=1,
            total_fragments=2,
            interface_language="nl",
            estimated_total_seconds=3661,
            elapsed_seconds=61,
        )

        self.assertIn("Verstreken: 1 min 1 sec", message)
        self.assertIn("Resterende tijd: ~1 u", message)

    def test_progress_activity_phrases_are_localized_and_lively(self):
        self.assertEqual(get_progress_activity_phrase("en", 0), "Turning the next page")
        self.assertEqual(get_progress_activity_phrase("ru", 1), "Главы остаются на своих местах")
        self.assertEqual(get_progress_activity_phrase("nl", 2), "De komma’s gedragen zich")

    def test_progress_activity_phrases_live_in_dedicated_module(self):
        self.assertIsNotNone(find_spec("translator_service.bot.activity_phrases"))

    def test_progress_activity_phrase_rotation_includes_workshop_copy(self):
        expectations = {
            "en": "Aligning the margins",
            "ru": "Выравниваю поля",
            "uk": "Вирівнюю поля",
            "fr": "J’aligne les marges",
            "es": "Alineando los márgenes",
            "nl": "De marges rechtzetten",
        }

        for language_code, expected in expectations.items():
            with self.subTest(language_code=language_code):
                self.assertEqual(
                    get_progress_activity_phrase(language_code, 6),
                    expected,
                )

    def test_translation_progress_message_can_use_lively_activity_phrase(self):
        message = build_translation_progress_message(
            completed_fragments=2,
            total_fragments=5,
            interface_language="ru",
            elapsed_seconds=12,
            activity_indicator="❦",
            activity_phrase_index=2,
        )

        self.assertIn("Запятые ведут себя прилично ❦", message)

    def test_translation_progress_message_uses_phrase_pack_for_all_locales(self):
        expectations = {
            "uk": "Коми поводяться чемно ✦",
            "fr": "Les virgules se tiennent bien ✦",
            "es": "Las comas se portan bien ✦",
            "nl": "De komma’s gedragen zich ✦",
        }

        for language_code, expected in expectations.items():
            with self.subTest(language_code=language_code):
                message = build_translation_progress_message(
                    completed_fragments=1,
                    total_fragments=3,
                    interface_language=language_code,
                    activity_indicator="✦",
                    activity_phrase_index=2,
                )

                self.assertIn(expected, message)

    def test_unknown_text_message_points_back_to_menu(self):
        self.assertIn("Send a book", build_unknown_text_message("en"))
        self.assertIn("книгу", build_unknown_text_message("ru"))
        self.assertIn("Hoofdmenu", build_unknown_text_message("nl"))

    def test_cancel_messages_are_localized(self):
        self.assertIn("Stopping translation", build_cancel_requested_message("en"))
        self.assertIn("no active translation", build_nothing_to_cancel_message("en"))

    def test_back_button_text_is_localized_and_recognized(self):
        self.assertEqual(get_back_text("ru"), "Назад")
        self.assertTrue(is_back_text(" назад "))
        self.assertTrue(is_back_text("Back"))
        self.assertFalse(is_back_text(None))

    def test_cancel_button_text_is_localized_and_recognized(self):
        self.assertEqual(get_cancel_text("ru"), "Отмена")
        self.assertTrue(is_cancel_text(" отмена "))
        self.assertTrue(is_cancel_text("Cancel"))
        self.assertTrue(is_cancel_text("/cancel"))
        self.assertFalse(is_cancel_text(None))

    def test_back_to_menu_message_is_localized(self):
        self.assertIn("главное меню", build_back_to_menu_message("ru").lower())
        self.assertIn("Main menu", build_back_to_menu_message("en"))
        self.assertIn("Hoofdmenu", build_back_to_menu_message("nl"))

    def test_confirm_translation_text_accepts_localized_buttons(self):
        self.assertTrue(is_confirm_translation_text("Подтвердить"))
        self.assertTrue(is_confirm_translation_text("Підтвердити"))
        self.assertTrue(is_confirm_translation_text("Confirmer"))
        self.assertTrue(is_confirm_translation_text("Confirmar"))
        self.assertTrue(is_confirm_translation_text("Start Translation"))
        self.assertTrue(is_confirm_translation_text("Bevestigen"))

    def test_main_menu_buttons_are_recognized_across_locales(self):
        self.assertTrue(is_translate_book_text("📖 Translate a Book"))
        self.assertTrue(is_translate_book_text("📖 Перевести книгу"))
        self.assertTrue(is_how_it_works_text("🧵 How It Works"))
        self.assertTrue(is_how_it_works_text("🧵 Zo werkt het"))
        self.assertTrue(is_language_menu_text("🌍 Language"))
        self.assertTrue(is_language_menu_text("🌍 Язык"))
        self.assertTrue(is_settings_text("⚙️ Settings"))
        self.assertTrue(is_settings_text("⚙️ Настройки"))
        self.assertTrue(is_settings_text("⚙️ Instellingen"))
        self.assertTrue(is_toggle_progress_preview_text("Hide Preview"))
        self.assertTrue(is_toggle_progress_preview_text("Показывать отрывок"))
        self.assertTrue(is_help_text("Help"))
        self.assertTrue(is_help_text("Помощь"))
        self.assertTrue(is_help_text("Hulp"))
        self.assertTrue(is_main_menu_text("Main Menu"))
        self.assertTrue(is_main_menu_text("Главное меню"))

    def test_folioloom_support_messages_do_not_advertise_pdf_or_dead_features(self):
        for language_code in ("en", "ru", "uk", "fr", "es", "nl"):
            with self.subTest(language_code=language_code):
                combined = "\n".join(
                    [
                        build_start_message(language_code),
                        build_upload_prompt_message(language_code),
                        build_help_message(language_code),
                        build_how_it_works_message(language_code),
                    ]
                )
                self.assertIn("FolioLoom", combined)
                self.assertIn("EPUB", combined)
                self.assertIn("DOCX", combined)
                self.assertIn("TXT", combined)
                self.assertNotIn("PDF", combined)
                self.assertNotIn("DeepSeek", combined)
                self.assertNotIn("Balance", combined)
                self.assertNotIn("Pricing", combined)
                self.assertNotIn("My Books", combined)

    def test_main_menu_text_is_localized(self):
        self.assertIn("FolioLoom", get_main_menu_text("en"))
        self.assertIn("Choose what", get_main_menu_text("en"))
        self.assertIn("Выберите", get_main_menu_text("ru"))
        self.assertNotIn("Books, beautifully translated.", get_main_menu_text("en"))
        self.assertNotIn("📖 Translate a Book", get_main_menu_text("en"))


if __name__ == "__main__":
    unittest.main()
