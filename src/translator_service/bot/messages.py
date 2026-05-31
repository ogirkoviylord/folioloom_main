import html
from pathlib import PurePath

from translator_service.beta_access import BetaAccessDenied
from translator_service.bot.activity_phrases import get_activity_phrases
from translator_service.bot_translation_service import (
    TRANSLATION_MODE_BOOK_MANUSCRIPT,
    TRANSLATION_MODE_DOCUMENT_FORM,
    DuplicatePreviewError,
    PendingTranslation,
    PreviewTranslation,
)
from translator_service.documents import (
    EmptyDocumentError,
    FileTooLargeError,
    UnsupportedDocumentError,
)
from translator_service.extractors import TextExtractionError
from translator_service.job_runner import TranslationJob, TranslationJobStatus
from translator_service.languages import (
    SUPPORTED_TARGET_LANGUAGES,
    language_code_for_name,
    localized_language_name_for_code,
)
from translator_service.order_estimates import OrderEstimate
from translator_service.security_telemetry import SecurityCooldownActive

CONFIRM_TRANSLATION_TEXT = "Start Translation"
SUPPORTED_TRANSLATION_FORMATS = ("EPUB", "DOCX", "TXT")


# Beta FolioLoom interface. Keep copy centralized so adding another language is a
# matter of adding one locale block and the shared language registry entry.
MESSAGES = {
    "en": {
        "main_menu": [
            "📖 Translate a Book",
            "📚 My Books",
            "🧵 How It Works",
            "🌍 Language",
            "⚙️ Settings",
            "Help",
        ],
        "main_menu_button": "Main Menu",
        "start_title": "Welcome to FolioLoom.",
        "tagline": "Books, beautifully translated.",
        "start_body": (
            "Send a book, chapter, or manuscript, and I’ll help bring it into a "
            "new language while keeping its structure and voice intact."
        ),
        "permission_note": "Only upload texts you own or have permission to translate.",
        "formats": "Supported formats: {formats}.",
        "main_menu_title": "FolioLoom",
        "main_menu_prompt": "Choose what you’d like to do.",
        "upload_prompt": (
            "Send me a book, chapter, or manuscript.\n\n"
            "Supported formats: {formats}.\n\n"
            "I’ll read the file, prepare the text, and guide you through the translation."
        ),
        "help": (
            "Help\n\n"
            "FolioLoom is for translating books, chapters, and manuscripts.\n\n"
            "Good to know:\n"
            "- Use clean {formats} files.\n"
            "- Very large books may take time.\n"
            "- Split difficult manuscripts into chapters if needed.\n"
            "- Review the final translation before publishing.\n\n"
            "Only upload texts you own or have permission to translate."
        ),
        "how_it_works": (
            "How FolioLoom Works\n\n"
            "1. Send a supported book, chapter, or manuscript.\n"
            "2. Choose the language for the translation.\n"
            "3. Review the estimate and settings.\n"
            "4. Start the translation.\n"
            "5. Download the result when it is ready.\n\n"
            "I keep chapters, paragraphs, and document structure as carefully as the current file allows."
        ),
        "interface_language_prompt": "Language\n\nChoose interface language:",
        "interface_language_selected": "Interface language: {language_text}.",
        "settings_title": "Settings",
        "settings_body": "Choose how FolioLoom works for you.",
        "settings_preview": "Latest passage preview",
        "settings_preview_on": "On",
        "settings_preview_off": "Off",
        "settings_language": "Interface language",
        "my_books_title": "My Books",
        "my_books_empty": "No books yet. Send a book or manuscript to start your first translation.",
        "my_books_download_hint": "Open a book below to view status, continue, or download.",
        "queue_title": "Queue",
        "queue_summary": "{total} active: {queued} queued, {translating} translating.",
        "last_book": "Last Book",
        "book_button": "Book {index}",
        "back_to_my_books": "Back to My Books",
        "book_detail_title": "Book Details",
        "book_detail_file": "File",
        "book_detail_format": "Format",
        "book_detail_language": "Language",
        "book_detail_status": "Status",
        "book_detail_result": "Result",
        "book_detail_updated": "Updated",
        "final_download_available": "Final download available",
        "partial_download_available": "Partial download available",
        "resume_available": "This translation can be continued from saved progress.",
        "resume_unavailable": "This translation cannot be continued right now.",
        "download_available": "download available",
        "download_missing": "no download yet",
        "download_book": "Download {index}",
        "download_translation": "Download Translation",
        "continue_translation": "Continue Translation",
        "preview_title": "Translation preview",
        "preview_body": (
            "Here is a short translated sample. Full translation starts only "
            "after you continue."
        ),
        "preview_cost_placeholder": "Cost: ???",
        "preview_instruction": (
            "Continue if the quality and language look right, or go back to "
            "change the translation settings."
        ),
        "preview_required": (
            "Review the translation preview first, then choose Continue "
            "Translation to start the full translation."
        ),
        "preview_already_generated": (
            "A preview for this same document, language, and mode is already "
            "prepared. I cannot start another identical preview yet. Go back "
            "or open My Books to check existing work."
        ),
        "duplicate_ready": (
            "This document has already been translated with these settings.\n\n"
            "Choose whether to download the existing translation or translate "
            "it again as a new attempt."
        ),
        "duplicate_active": (
            "A matching translation is already in progress.\n\n"
            "Open the existing book to check its status, or go back to change "
            "translation settings."
        ),
        "duplicate_existing": (
            "A matching translation already exists in My Books.\n\n"
            "Open the existing book or translate this upload again as a new "
            "attempt."
        ),
        "duplicate_translate_again": "Translate Again",
        "duplicate_open_existing": "Open Existing Translation",
        "translation_mode_prompt": (
            "File received.\n\n"
            "Title: {file_name}\n"
            "Format: {file_format}\n"
            "{source_language_line}\n"
            "Choose how to translate this document.\n\n"
            "{document_form_help}\n\n"
            "{book_manuscript_help}\n\n"
            "{format_scope_note}"
        ),
        "translation_mode_document_form": "Document / form",
        "translation_mode_book_manuscript": "Book / manuscript",
        "translation_mode_document_form_help": (
            "Document / form: for statements, applications, forms, and structured "
            "documents. I’ll prioritize layout cues, labels, tables, numbers, dates, "
            "addresses, signatures, and fields that should stay unchanged."
        ),
        "translation_mode_book_manuscript_help": (
            "Book / manuscript: for books, chapters, long manuscripts, and editorial "
            "text. I’ll prioritize chapters, paragraphs, continuity, and author "
            "voice."
        ),
        "translation_mode_format_scope_note": (
            "This choice affects translation behavior only; it does not add new file "
            "formats. Use {formats}."
        ),
        "translation_mode_required": (
            "Choose how to translate this document before selecting the "
            "target language."
        ),
        "delete_book": "Delete Book",
        "confirm_delete_book": "Yes, Delete Book",
        "keep_book": "Keep Book",
        "delete_book_confirm": "Delete this book?\n\nThis removes {file_name} from My Books and deletes its stored files from FolioLoom. This cannot be undone.",
        "book_deleted": "Book deleted.",
        "delete_unavailable": "This book could not be deleted.",
        "download_unavailable": "This file is not available for download yet.",
        "status_queued": "Queued",
        "status_translating": "Translating",
        "status_paused": "Paused",
        "status_assembling": "Assembling",
        "status_partial": "Partial",
        "status_cancel_requested": "Stopping",
        "status_cancelled": "Cancelled",
        "status_deleted": "Deleted",
        "status_interrupted": "Interrupted",
        "status_failed": "Failed",
        "status_ready": "Ready",
        "status_expired": "Expired",
        "hide_preview": "Hide Preview",
        "show_preview": "Show Preview",
        "reset_settings": "Reset Settings",
        "settings_reset": "Settings have been reset. Please choose interface language again.",
        "translation_language_prompt": (
            "File received.\n\n"
            "Title: {file_name}\n"
            "Format: {file_format}\n"
            "{source_language_line}\n"
            "Choose the target language."
        ),
        "rights_confirmation_prompt": (
            "File received.\n\n"
            "Title: {file_name}\n\n"
            "Please confirm that you have the right to translate this document: "
            "you are the author or rights holder, you have permission from the "
            "rights holder, or the document is public domain / authorized for translation."
        ),
        "confirm_rights": "✅ I confirm the rights",
        "original_language": "Source language",
        "source_language_with_admixtures": "{primary}; admixtures: {admixtures}",
        "progress": "Translation progress",
        "activity": "{phrase} {indicator}",
        "back": "Back",
        "back_to_menu": "Returning to the Main menu.",
        "cancel": "Cancel",
        "cancel_hint": "To stop translation, press “{cancel_text}” or send /cancel.",
        "elapsed": "Elapsed",
        "time_left": "Time left",
        "estimated_time": "Estimated time",
        "time_unknown": "estimating",
        "last_fragment": "Latest translated passage",
        "cancel_requested": "Stopping translation after the current passage.",
        "nothing_to_cancel": "There is no active translation to stop.",
        "no_pending_translation": "There is no translation waiting for confirmation.",
        "estimate_title": "Translation estimate",
        "document_ready": "Ready to begin.",
        "book": "Book",
        "mode": "Mode",
        "file": "File",
        "format": "Format",
        "characters": "Characters",
        "tokens": "Estimated tokens",
        "price": "Price",
        "from": "From",
        "to": "To",
        "translation_mode_document_form_summary": (
            "Document/form mode: structure, labels, tables, numbers, dates, "
            "addresses, signatures, and protected fields stay the priority."
        ),
        "translation_mode_book_manuscript_summary": (
            "Book/manuscript mode: chapters, paragraphs, continuity, and author "
            "voice stay the priority."
        ),
        "preservation_note": "I’ll preserve chapters, paragraphs, and as much formatting as the current file allows.",
        "confirm_instruction": "Press “{confirm_text}” to start translation.",
        "queue_instruction": "Press “{confirm_text}” to queue translation.",
        "queued": "Your translation is queued: {file_name}.",
        "translating": "Your translation is in progress: {file_name}.",
        "paused": "Translation paused by an admin.\n\nI will not continue it until it is resumed.",
        "ready": "Your translation is ready.\n\nYou can download the translated file below: {result_name}.",
        "partial": "Translation finished with skipped passages.\n\nPartial result: {result_name}.\n\nSome passages remain in the original language. You can continue from My Books later without uploading the file again.",
        "cancelled": "Translation cancelled.\n\nPartial result: {result_name}.",
        "cancelled_without_result": (
            "Translation cancelled.\n\n"
            "A partial result is not available yet because the translation was cancelled before any passage was translated."
        ),
        "deleted": "Translation deleted by an admin.\n\nThe job and stored files are no longer available.",
        "failed": "Something went wrong while translating.\n\nYour file is safe. Please try again, or return to the main menu.",
        "status": "Translation status: {status}",
        "confirm": "Start Translation",
        "unsupported_file": (
            "This file type is not supported yet.\n\n"
            "Please send one of these formats:\n{formats}"
        ),
        "file_too_large": (
            "This file is larger than the current limit of {limit}.\n\n"
            "Try sending a smaller file or splitting the book into chapters."
        ),
        "empty_file": "This file is empty. Please send a book, chapter, or manuscript with text.",
        "extraction_failed": (
            "I couldn’t read this file reliably.\n\n"
            "Try sending a cleaner copy, or use one of these formats:\n{formats}"
        ),
        "translation_failed": (
            "Something went wrong while translating.\n\n"
            "Your file is safe. Please try again, or return to the main menu."
        ),
        "security_cooldown": (
            "For safety, new translations are temporarily paused for this account.\n\n"
            "Please try again later."
        ),
        "beta_access_denied": (
            "FolioLoom is invite-only during the closed beta.\n\n"
            "Ask the owner to add your Telegram ID to the beta allowlist."
        ),
        "unknown_text": (
            "Send a book, chapter, or manuscript to begin, or choose an option from the menu."
        ),
    },
    "ru": {
        "main_menu": [
            "📖 Перевести книгу",
            "📚 Мои книги",
            "🧵 Как это работает",
            "🌍 Язык",
            "⚙️ Настройки",
            "Помощь",
        ],
        "main_menu_button": "Главное меню",
        "start_title": "Добро пожаловать в FolioLoom.",
        "tagline": "Books, beautifully translated.",
        "start_body": (
            "Отправьте книгу, главу или рукопись — я помогу перевести текст на другой язык, "
            "сохранив структуру и голос автора."
        ),
        "permission_note": "Загружайте только тексты, которые принадлежат вам или на перевод которых у вас есть разрешение.",
        "formats": "Поддерживаемые форматы: {formats}.",
        "main_menu_title": "FolioLoom",
        "main_menu_prompt": "Выберите, что хотите сделать.",
        "upload_prompt": (
            "Отправьте книгу, главу или рукопись.\n\n"
            "Поддерживаемые форматы: {formats}.\n\n"
            "Я прочитаю файл, подготовлю текст и помогу выбрать настройки перевода."
        ),
        "help": (
            "Помощь\n\n"
            "FolioLoom создан для перевода книг, глав и рукописей.\n\n"
            "Полезно знать:\n"
            "- Используйте чистые файлы {formats}.\n"
            "- Очень большие книги могут переводиться дольше.\n"
            "- Сложные рукописи при необходимости лучше делить на главы.\n"
            "- Перед публикацией проверьте финальный перевод.\n\n"
            "Загружайте только тексты, которые принадлежат вам или на перевод которых у вас есть разрешение."
        ),
        "how_it_works": (
            "Как работает FolioLoom\n\n"
            "1. Отправьте поддерживаемую книгу, главу или рукопись.\n"
            "2. Выберите язык перевода.\n"
            "3. Проверьте оценку и настройки.\n"
            "4. Запустите перевод.\n"
            "5. Скачайте результат, когда он будет готов.\n\n"
            "Я сохраняю главы, абзацы и структуру документа настолько бережно, насколько позволяет исходный файл."
        ),
        "interface_language_prompt": "Язык\n\nВыберите язык интерфейса:",
        "interface_language_selected": "Язык интерфейса: {language_text}.",
        "settings_title": "Настройки",
        "settings_body": "Выберите, как FolioLoom будет работать для вас.",
        "settings_preview": "Последний отрывок",
        "settings_preview_on": "включен",
        "settings_preview_off": "выключен",
        "settings_language": "Язык интерфейса",
        "my_books_title": "Мои книги",
        "my_books_empty": "Книг пока нет. Отправьте книгу или рукопись, чтобы начать первый перевод.",
        "my_books_download_hint": "Откройте книгу ниже, чтобы посмотреть статус, продолжить или скачать перевод.",
        "queue_title": "Очередь",
        "queue_summary": "Активных переводов: {total}. В очереди: {queued}, переводится: {translating}.",
        "last_book": "Последняя книга",
        "book_button": "Книга {index}",
        "back_to_my_books": "Назад к моим книгам",
        "book_detail_title": "Карточка книги",
        "book_detail_file": "Файл",
        "book_detail_format": "Формат",
        "book_detail_language": "Язык",
        "book_detail_status": "Статус",
        "book_detail_result": "Результат",
        "book_detail_updated": "Обновлено",
        "final_download_available": "Финальный файл доступен для скачивания",
        "partial_download_available": "Частичный файл доступен для скачивания",
        "resume_available": "Этот перевод можно продолжить с сохраненного места.",
        "resume_unavailable": "Этот перевод сейчас нельзя продолжить.",
        "download_available": "можно скачать",
        "download_missing": "файла пока нет",
        "download_book": "Скачать {index}",
        "download_translation": "Скачать перевод",
        "continue_translation": "Продолжить перевод",
        "preview_title": "Предпросмотр перевода",
        "preview_body": (
            "Вот короткий переведенный отрывок. Полный перевод начнется только "
            "после вашего подтверждения."
        ),
        "preview_cost_placeholder": "Стоимость: ???",
        "preview_instruction": (
            "Продолжайте, если качество и язык подходят, или вернитесь назад, "
            "чтобы изменить настройки перевода."
        ),
        "preview_required": (
            "Сначала посмотрите предпросмотр, затем нажмите "
            "«Продолжить перевод», чтобы начать полный перевод."
        ),
        "preview_already_generated": (
            "Предпросмотр для этого же документа, языка и режима уже "
            "подготовлен. Я пока не могу запустить еще один такой же "
            "предпросмотр. Вернитесь назад или откройте «Мои книги», чтобы "
            "проверить существующую работу."
        ),
        "duplicate_ready": (
            "Этот документ уже переводился с такими настройками.\n\n"
            "Выберите: скачать существующий перевод или перевести заново как "
            "новую попытку."
        ),
        "duplicate_active": (
            "Такой перевод уже выполняется.\n\n"
            "Откройте существующую книгу, чтобы проверить статус, или "
            "вернитесь назад и измените настройки перевода."
        ),
        "duplicate_existing": (
            "Такой перевод уже есть в «Моих книгах».\n\n"
            "Откройте существующую книгу или переведите эту загрузку заново "
            "как новую попытку."
        ),
        "duplicate_translate_again": "Перевести заново",
        "duplicate_open_existing": "Открыть существующий перевод",
        "translation_mode_prompt": (
            "Файл получен.\n\n"
            "Название: {file_name}\n"
            "Формат: {file_format}\n"
            "{source_language_line}\n"
            "Выберите, как переводить этот документ.\n\n"
            "{document_form_help}\n\n"
            "{book_manuscript_help}\n\n"
            "{format_scope_note}"
        ),
        "translation_mode_document_form": "Документ / форма",
        "translation_mode_book_manuscript": "Книга / рукопись",
        "translation_mode_document_form_help": (
            "Документ / форма: для заявлений, анкет, форм и "
            "структурированных документов. Я буду беречь разметку, подписи, "
            "таблицы, числа, даты, адреса, места для подписи и поля, которые "
            "не нужно переводить."
        ),
        "translation_mode_book_manuscript_help": (
            "Книга / рукопись: для книг, глав, длинных рукописей и "
            "редакторских текстов. Я буду беречь главы, абзацы, связность и "
            "авторский голос."
        ),
        "translation_mode_format_scope_note": (
            "Этот выбор влияет только на поведение перевода; он не добавляет "
            "новые форматы файлов. Используйте {formats}."
        ),
        "translation_mode_required": (
            "Выберите, как переводить этот документ, прежде чем выбирать "
            "язык перевода."
        ),
        "delete_book": "Удалить книгу",
        "confirm_delete_book": "Да, удалить книгу",
        "keep_book": "Оставить книгу",
        "delete_book_confirm": "Удалить эту книгу?\n\n{file_name} исчезнет из «Моих книг», а сохраненные файлы будут удалены с сервера FolioLoom. Это нельзя отменить.",
        "book_deleted": "Книга удалена.",
        "delete_unavailable": "Эту книгу не получилось удалить.",
        "download_unavailable": "Этот файл пока нельзя скачать.",
        "status_queued": "В очереди",
        "status_translating": "Переводится",
        "status_paused": "На паузе",
        "status_assembling": "Собирается",
        "status_partial": "Частичный",
        "status_cancel_requested": "Останавливается",
        "status_cancelled": "Отменен",
        "status_deleted": "Удален",
        "status_interrupted": "Прерван",
        "status_failed": "Ошибка",
        "status_ready": "Готов",
        "status_expired": "Истек",
        "hide_preview": "Скрыть отрывок",
        "show_preview": "Показывать отрывок",
        "reset_settings": "Сбросить настройки",
        "settings_reset": "Настройки сброшены. Выберите язык интерфейса заново.",
        "translation_language_prompt": (
            "Файл получен.\n\n"
            "Название: {file_name}\n"
            "Формат: {file_format}\n"
            "{source_language_line}\n"
            "Теперь выберите язык перевода."
        ),
        "rights_confirmation_prompt": (
            "Файл получен.\n\n"
            "Название: {file_name}\n\n"
            "Подтвердите, что у вас есть право переводить этот документ: "
            "вы автор, правообладатель, работаете с разрешения правообладателя, "
            "или документ находится в public domain / разрешен к переводу."
        ),
        "confirm_rights": "✅ Подтверждаю права",
        "original_language": "Язык оригинала",
        "source_language_with_admixtures": "{primary}; примеси: {admixtures}",
        "progress": "Прогресс перевода",
        "activity": "{phrase} {indicator}",
        "back": "Назад",
        "back_to_menu": "Возвращаемся в главное меню.",
        "cancel": "Отмена",
        "cancel_hint": "Чтобы остановить перевод, нажмите «{cancel_text}» или отправьте /cancel.",
        "elapsed": "Прошло",
        "time_left": "Осталось",
        "estimated_time": "Примерное время",
        "time_unknown": "уточняется",
        "last_fragment": "Последний переведенный отрывок",
        "cancel_requested": "Останавливаю перевод после текущего отрывка.",
        "nothing_to_cancel": "Сейчас нет активного перевода для остановки.",
        "no_pending_translation": "Нет перевода, который ожидает подтверждения.",
        "estimate_title": "Оценка перевода",
        "document_ready": "Всё готово к переводу.",
        "book": "Книга",
        "mode": "Режим",
        "file": "Файл",
        "format": "Формат",
        "characters": "Символов",
        "tokens": "Примерные токены",
        "price": "Цена",
        "from": "С языка",
        "to": "На язык",
        "translation_mode_document_form_summary": (
            "Режим документа/формы: в приоритете структура, подписи, "
            "таблицы, числа, даты, адреса, места для подписи и защищенные "
            "поля."
        ),
        "translation_mode_book_manuscript_summary": (
            "Режим книги/рукописи: в приоритете главы, абзацы, связность "
            "и авторский голос."
        ),
        "preservation_note": "Я сохраню главы, абзацы и форматирование настолько, насколько позволяет исходный файл.",
        "confirm_instruction": "Нажмите «{confirm_text}», чтобы начать перевод.",
        "queue_instruction": "Нажмите «{confirm_text}», чтобы поставить перевод в очередь.",
        "queued": "Перевод в очереди: {file_name}.",
        "translating": "Перевод выполняется: {file_name}.",
        "paused": "Администратор поставил перевод на паузу.\n\nЯ не продолжу его, пока перевод снова не запустят.",
        "ready": "Перевод готов.\n\nВы можете скачать файл ниже: {result_name}.",
        "partial": "Перевод завершен с пропущенными отрывками.\n\nЧастичный результат: {result_name}.\n\nНекоторые отрывки остались на исходном языке. Позже можно продолжить из My Books без новой загрузки файла.",
        "cancelled": "Перевод отменен.\n\nЧастичный результат: {result_name}.",
        "cancelled_without_result": (
            "Перевод отменен.\n\n"
            "Частичный результат пока недоступен: перевод был отменен до того, как был переведен первый отрывок."
        ),
        "deleted": "Администратор удалил перевод.\n\nЗадача и сохраненные файлы больше недоступны.",
        "failed": "Во время перевода что-то пошло не так.\n\nФайл не потерян. Попробуйте еще раз или вернитесь в главное меню.",
        "status": "Статус перевода: {status}",
        "confirm": "Начать перевод",
        "unsupported_file": (
            "Этот тип файла пока не поддерживается.\n\n"
            "Пожалуйста, отправьте файл одного из этих форматов:\n{formats}"
        ),
        "file_too_large": (
            "Файл больше текущего лимита: {limit}.\n\n"
            "Попробуйте отправить файл меньшего размера или разделить книгу на главы."
        ),
        "empty_file": "Этот файл пустой. Отправьте книгу, главу или рукопись с текстом.",
        "extraction_failed": (
            "Не получилось надежно прочитать этот файл.\n\n"
            "Попробуйте отправить более чистую копию или используйте один из этих форматов:\n{formats}"
        ),
        "translation_failed": (
            "Во время перевода что-то пошло не так.\n\n"
            "Файл не потерян. Попробуйте еще раз или вернитесь в главное меню."
        ),
        "security_cooldown": (
            "В целях безопасности новые переводы временно приостановлены для этого аккаунта.\n\n"
            "Попробуйте позже."
        ),
        "beta_access_denied": (
            "FolioLoom работает по приглашениям во время закрытой беты.\n\n"
            "Попросите владельца добавить ваш Telegram ID в beta allowlist."
        ),
        "unknown_text": (
            "Отправьте книгу, главу или рукопись, чтобы начать, или выберите действие в главном меню."
        ),
    },
}

for _language_code, _fallbacks in {
    "uk": {
        "main_menu": [
            "📖 Перекласти книгу",
            "📚 Мої книги",
            "🧵 Як це працює",
            "🌍 Мова",
            "⚙️ Налаштування",
            "Допомога",
        ],
        "main_menu_button": "Головне меню",
        "start_title": "Ласкаво просимо до FolioLoom.",
        "start_body": "Надішліть книгу, розділ або рукопис — я допоможу перекласти текст іншою мовою, зберігаючи структуру й голос автора.",
        "permission_note": "Завантажуйте лише тексти, які належать вам або які ви маєте право перекладати.",
        "main_menu_prompt": "Оберіть, що хочете зробити.",
        "upload_prompt": "Надішліть книгу, розділ або рукопис.\n\nПідтримувані формати: {formats}.\n\nЯ прочитаю файл, підготую текст і допоможу вибрати налаштування перекладу.",
        "interface_language_prompt": "Мова\n\nВиберіть мову інтерфейсу:",
        "interface_language_selected": "Мова інтерфейсу: {language_text}.",
        "settings_title": "Налаштування",
        "settings_body": "Оберіть, як FolioLoom працюватиме для вас.",
        "settings_preview": "Останній уривок",
        "settings_preview_on": "увімкнено",
        "settings_preview_off": "вимкнено",
        "settings_language": "Мова інтерфейсу",
        "my_books_title": "Мої книги",
        "my_books_empty": "Книг ще немає. Надішліть книгу або рукопис, щоб почати перший переклад.",
        "my_books_download_hint": "Відкрийте книгу нижче, щоб переглянути статус, продовжити або завантажити переклад.",
        "last_book": "Остання книга",
        "book_button": "Книга {index}",
        "back_to_my_books": "Назад до моїх книг",
        "book_detail_title": "Картка книги",
        "book_detail_file": "Файл",
        "book_detail_format": "Формат",
        "book_detail_language": "Мова",
        "book_detail_status": "Статус",
        "book_detail_result": "Результат",
        "book_detail_updated": "Оновлено",
        "final_download_available": "Фінальний файл доступний для завантаження",
        "partial_download_available": "Частковий файл доступний для завантаження",
        "resume_available": "Цей переклад можна продовжити зі збереженого місця.",
        "resume_unavailable": "Цей переклад зараз не можна продовжити.",
        "download_available": "можна завантажити",
        "download_missing": "файла ще немає",
        "download_book": "Завантажити {index}",
        "download_translation": "Завантажити переклад",
        "continue_translation": "Продовжити переклад",
        "translation_mode_prompt": (
            "Файл отримано.\n\n"
            "Назва: {file_name}\n"
            "Формат: {file_format}\n"
            "{source_language_line}\n"
            "Виберіть, як перекладати цей документ.\n\n"
            "{document_form_help}\n\n"
            "{book_manuscript_help}\n\n"
            "{format_scope_note}"
        ),
        "translation_mode_document_form": "Документ / форма",
        "translation_mode_book_manuscript": "Книга / рукопис",
        "translation_mode_document_form_help": (
            "Документ / форма: для заяв, анкет, форм і структурованих "
            "документів. Я зберігатиму розмітку, підписи, таблиці, числа, "
            "дати, адреси, місця для підпису й поля, які не треба перекладати."
        ),
        "translation_mode_book_manuscript_help": (
            "Книга / рукопис: для книг, розділів, довгих рукописів і "
            "редакторських текстів. Я зберігатиму розділи, абзаци, "
            "послідовність і авторський голос."
        ),
        "translation_mode_format_scope_note": (
            "Цей вибір впливає лише на поведінку перекладу; він не додає "
            "нові формати файлів. Використовуйте {formats}."
        ),
        "translation_mode_required": (
            "Виберіть, як перекладати цей документ, перш ніж вибирати "
            "мову перекладу."
        ),
        "delete_book": "Видалити книгу",
        "confirm_delete_book": "Так, видалити книгу",
        "keep_book": "Залишити книгу",
        "delete_book_confirm": "Видалити цю книгу?\n\n{file_name} зникне з «Моїх книг», а збережені файли буде видалено із сервера FolioLoom. Це не можна скасувати.",
        "book_deleted": "Книгу видалено.",
        "delete_unavailable": "Цю книгу не вдалося видалити.",
        "download_unavailable": "Цей файл ще не можна завантажити.",
        "status_queued": "У черзі",
        "status_translating": "Перекладається",
        "status_assembling": "Збирається",
        "status_partial": "Частковий",
        "status_cancel_requested": "Зупиняється",
        "status_cancelled": "Скасовано",
        "status_interrupted": "Перервано",
        "status_failed": "Помилка",
        "status_ready": "Готово",
        "status_expired": "Строк минув",
        "hide_preview": "Сховати уривок",
        "show_preview": "Показувати уривок",
        "reset_settings": "Скинути налаштування",
        "settings_reset": "Налаштування скинуто. Виберіть мову інтерфейсу знову.",
        "translation_language_prompt": "Файл отримано.\n\nНазва: {file_name}\nФормат: {file_format}\n{source_language_line}\nТепер виберіть мову перекладу.",
        "rights_confirmation_prompt": (
            "Файл отримано.\n\n"
            "Назва: {file_name}\n\n"
            "Підтвердьте, що ви маєте право перекладати цей документ: "
            "ви автор, правовласник, працюєте з дозволу правовласника, "
            "або документ є public domain / дозволений для перекладу."
        ),
        "confirm_rights": "✅ Підтверджую права",
        "original_language": "Мова оригіналу",
        "source_language_with_admixtures": "{primary}; домішки: {admixtures}",
        "back": "Назад",
        "back_to_menu": "Повертаємося до головного меню.",
        "cancel": "Скасувати",
        "confirm": "Почати переклад",
        "document_ready": "Усе готово до перекладу.",
        "from": "З мови",
        "to": "Мовою",
        "formats": "Підтримувані формати: {formats}.",
        "help": "Допомога\n\nFolioLoom створений для перекладу книг, розділів і рукописів.\n\nКорисно знати:\n- Використовуйте чисті файли {formats}.\n- Дуже великі книги можуть перекладатися довше.\n- Складні рукописи за потреби краще ділити на розділи.\n- Перед публікацією перевіряйте фінальний переклад.\n\nЗавантажуйте лише тексти, які належать вам або які ви маєте право перекладати.",
        "how_it_works": "Як працює FolioLoom\n\n1. Надішліть підтримувану книгу, розділ або рукопис.\n2. Виберіть мову перекладу.\n3. Перевірте оцінку та налаштування.\n4. Запустіть переклад.\n5. Завантажте результат, коли він буде готовий.\n\nЯ зберігаю розділи, абзаци й структуру документа настільки дбайливо, наскільки дозволяє початковий файл.",
        "progress": "Прогрес перекладу",
        "activity": "{phrase} {indicator}",
        "cancel_hint": "Щоб зупинити переклад, натисніть «{cancel_text}» або надішліть /cancel.",
        "elapsed": "Минуло",
        "time_left": "Залишилось",
        "estimated_time": "Орієнтовний час",
        "time_unknown": "уточнюється",
        "last_fragment": "Останній перекладений уривок",
        "cancel_requested": "Зупиняю переклад після поточного уривка.",
        "nothing_to_cancel": "Зараз немає активного перекладу для зупинки.",
        "no_pending_translation": "Немає перекладу, який очікує підтвердження.",
        "estimate_title": "Оцінка перекладу",
        "book": "Книга",
        "mode": "Режим",
        "file": "Файл",
        "format": "Формат",
        "characters": "Символів",
        "tokens": "Орієнтовні токени",
        "price": "Ціна",
        "translation_mode_document_form_summary": (
            "Режим документа/форми: в пріоритеті структура, підписи, "
            "таблиці, числа, дати, адреси, місця для підпису й захищені поля."
        ),
        "translation_mode_book_manuscript_summary": (
            "Режим книги/рукопису: в пріоритеті розділи, абзаци, "
            "послідовність і авторський голос."
        ),
        "preservation_note": "Я збережу розділи, абзаци й форматування настільки, наскільки це дозволяє початковий файл.",
        "confirm_instruction": "Натисніть «{confirm_text}», щоб почати переклад.",
        "queue_instruction": "Натисніть «{confirm_text}», щоб поставити переклад у чергу.",
        "queued": "Переклад у черзі: {file_name}.",
        "translating": "Переклад виконується: {file_name}.",
        "ready": "Переклад готовий.\n\nВи можете завантажити файл нижче: {result_name}.",
        "partial": "Переклад завершено з пропущеними уривками.\n\nЧастковий результат: {result_name}.\n\nДеякі уривки залишилися мовою оригіналу. Пізніше можна продовжити з My Books без нового завантаження файлу.",
        "cancelled": "Переклад скасовано.\n\nЧастковий результат: {result_name}.",
        "cancelled_without_result": (
            "Переклад скасовано.\n\n"
            "Частковий результат ще недоступний, бо переклад було скасовано до перекладу першого уривка."
        ),
        "failed": "Під час перекладу щось пішло не так.\n\nФайл не втрачено. Спробуйте ще раз або поверніться до головного меню.",
        "status": "Статус перекладу: {status}",
        "unsupported_file": "Цей тип файлу поки не підтримується.\n\nБудь ласка, надішліть файл одного з цих форматів:\n{formats}",
        "file_too_large": "Файл більший за поточний ліміт: {limit}.\n\nСпробуйте надіслати менший файл або розділити книгу на глави.",
        "empty_file": "Цей файл порожній. Надішліть книгу, розділ або рукопис з текстом.",
        "extraction_failed": "Не вдалося надійно прочитати цей файл.\n\nСпробуйте надіслати чистішу копію або використайте один із цих форматів:\n{formats}",
        "translation_failed": "Під час перекладу щось пішло не так.\n\nФайл не втрачено. Спробуйте ще раз або поверніться до головного меню.",
        "preview_already_generated": (
            "Попередній перегляд для цього самого документа, мови й режиму "
            "вже підготовлено. Я поки не можу запустити ще один такий самий "
            "попередній перегляд. Поверніться назад або відкрийте «Мої "
            "книги», щоб перевірити наявну роботу."
        ),
        "duplicate_ready": (
            "Цей документ уже перекладався з такими налаштуваннями.\n\n"
            "Виберіть: завантажити наявний переклад або перекласти заново як "
            "нову спробу."
        ),
        "duplicate_active": (
            "Такий переклад уже виконується.\n\n"
            "Відкрийте наявну книгу, щоб перевірити статус, або поверніться "
            "назад і змініть налаштування перекладу."
        ),
        "duplicate_existing": (
            "Такий переклад уже є в «Моїх книгах».\n\n"
            "Відкрийте наявну книгу або перекладіть це завантаження заново "
            "як нову спробу."
        ),
        "duplicate_translate_again": "Перекласти заново",
        "duplicate_open_existing": "Відкрити наявний переклад",
        "unknown_text": "Надішліть книгу, розділ або рукопис, щоб почати, або виберіть дію в головному меню.",
    },
    "fr": {
        "main_menu": [
            "📖 Traduire un livre",
            "📚 Mes livres",
            "🧵 Fonctionnement",
            "🌍 Langue",
            "⚙️ Réglages",
            "Aide",
        ],
        "main_menu_button": "Menu principal",
        "start_title": "Bienvenue dans FolioLoom.",
        "start_body": "Envoyez un livre, un chapitre ou un manuscrit, et je vous aiderai à le porter dans une autre langue en préservant sa structure et sa voix.",
        "permission_note": "N’envoyez que des textes qui vous appartiennent ou que vous avez le droit de traduire.",
        "main_menu_prompt": "Choisissez ce que vous voulez faire.",
        "upload_prompt": "Envoyez-moi un livre, un chapitre ou un manuscrit.\n\nFormats pris en charge : {formats}.\n\nJe lirai le fichier, préparerai le texte et vous guiderai dans le choix de la langue.",
        "interface_language_prompt": "Langue\n\nChoisissez la langue de l’interface :",
        "interface_language_selected": "Langue de l’interface : {language_text}.",
        "settings_title": "Réglages",
        "settings_body": "Choisissez comment FolioLoom fonctionne pour vous.",
        "settings_preview": "Aperçu du dernier passage",
        "settings_preview_on": "activé",
        "settings_preview_off": "désactivé",
        "settings_language": "Langue de l’interface",
        "my_books_title": "Mes livres",
        "my_books_empty": "Aucun livre pour le moment. Envoyez un livre ou un manuscrit pour lancer votre première traduction.",
        "my_books_download_hint": "Ouvrez un livre ci-dessous pour voir son statut, continuer ou télécharger.",
        "last_book": "Dernier livre",
        "book_button": "Livre {index}",
        "back_to_my_books": "Retour à Mes livres",
        "book_detail_title": "Détails du livre",
        "book_detail_file": "Fichier",
        "book_detail_format": "Format",
        "book_detail_language": "Langue",
        "book_detail_status": "Statut",
        "book_detail_result": "Résultat",
        "book_detail_updated": "Mis à jour",
        "final_download_available": "Téléchargement final disponible",
        "partial_download_available": "Téléchargement partiel disponible",
        "resume_available": "Cette traduction peut reprendre depuis la progression enregistrée.",
        "resume_unavailable": "Cette traduction ne peut pas être reprise pour le moment.",
        "download_available": "téléchargement disponible",
        "download_missing": "pas encore de fichier",
        "download_book": "Télécharger {index}",
        "download_translation": "Télécharger la traduction",
        "continue_translation": "Continuer la traduction",
        "translation_mode_prompt": (
            "Fichier reçu.\n\n"
            "Titre : {file_name}\n"
            "Format : {file_format}\n"
            "{source_language_line}\n"
            "Choisissez comment traduire ce document.\n\n"
            "{document_form_help}\n\n"
            "{book_manuscript_help}\n\n"
            "{format_scope_note}"
        ),
        "translation_mode_document_form": "Document / formulaire",
        "translation_mode_book_manuscript": "Livre / manuscrit",
        "translation_mode_document_form_help": (
            "Document / formulaire : pour les déclarations, demandes, formulaires "
            "et documents structurés. Je privilégierai la mise en page, les "
            "libellés, les tableaux, les nombres, les dates, les adresses, les "
            "signatures et les champs à conserver."
        ),
        "translation_mode_book_manuscript_help": (
            "Livre / manuscrit : pour les livres, chapitres, longs manuscrits et "
            "textes éditoriaux. Je privilégierai les chapitres, paragraphes, la "
            "continuité et la voix de l’auteur."
        ),
        "translation_mode_format_scope_note": (
            "Ce choix modifie seulement le comportement de traduction ; il n’ajoute "
            "pas de nouveaux formats de fichier. Utilisez {formats}."
        ),
        "translation_mode_required": (
            "Choisissez comment traduire ce document avant de choisir la langue cible."
        ),
        "delete_book": "Supprimer le livre",
        "confirm_delete_book": "Oui, supprimer",
        "keep_book": "Garder le livre",
        "delete_book_confirm": "Supprimer ce livre ?\n\n{file_name} sera retiré de Mes livres et ses fichiers enregistrés seront supprimés du serveur FolioLoom. Cette action est définitive.",
        "book_deleted": "Livre supprimé.",
        "delete_unavailable": "Ce livre n’a pas pu être supprimé.",
        "download_unavailable": "Ce fichier n’est pas encore disponible au téléchargement.",
        "status_queued": "En file d’attente",
        "status_translating": "En traduction",
        "status_assembling": "Assemblage",
        "status_partial": "Partiel",
        "status_cancel_requested": "Arrêt en cours",
        "status_cancelled": "Annulée",
        "status_interrupted": "Interrompue",
        "status_failed": "Échec",
        "status_ready": "Prête",
        "status_expired": "Expirée",
        "hide_preview": "Masquer l’aperçu",
        "show_preview": "Afficher l’aperçu",
        "reset_settings": "Réinitialiser les réglages",
        "settings_reset": "Les réglages ont été réinitialisés. Choisissez de nouveau la langue de l’interface.",
        "translation_language_prompt": "Fichier reçu.\n\nTitre : {file_name}\nFormat : {file_format}\n{source_language_line}\nChoisissez maintenant la langue de traduction.",
        "rights_confirmation_prompt": (
            "Fichier reçu.\n\n"
            "Titre : {file_name}\n\n"
            "Veuillez confirmer que vous avez le droit de traduire ce document : "
            "vous en êtes l’auteur ou le titulaire des droits, vous avez "
            "l’autorisation du titulaire des droits, ou le document est dans le "
            "domaine public / autorisé à la traduction."
        ),
        "confirm_rights": "✅ Je confirme les droits",
        "original_language": "Langue source",
        "source_language_with_admixtures": "{primary}; éléments mêlés : {admixtures}",
        "back": "Retour",
        "back_to_menu": "Retour au menu principal.",
        "cancel": "Annuler",
        "confirm": "Lancer la traduction",
        "document_ready": "Prêt à commencer.",
        "from": "Depuis",
        "to": "Vers",
        "formats": "Formats pris en charge : {formats}.",
        "help": "Aide\n\nFolioLoom est conçu pour traduire des livres, chapitres et manuscrits.\n\nÀ savoir :\n- Utilisez des fichiers {formats} propres.\n- Les très grands livres peuvent prendre du temps.\n- Si besoin, divisez les manuscrits difficiles en chapitres.\n- Relisez la traduction finale avant publication.\n\nN’envoyez que des textes qui vous appartiennent ou que vous avez le droit de traduire.",
        "how_it_works": "Comment fonctionne FolioLoom\n\n1. Envoyez un livre, un chapitre ou un manuscrit pris en charge.\n2. Choisissez la langue de traduction.\n3. Vérifiez l’estimation et les réglages.\n4. Lancez la traduction.\n5. Téléchargez le résultat quand il est prêt.\n\nJe préserve les chapitres, les paragraphes et la structure du document aussi soigneusement que le fichier le permet.",
        "progress": "Progression de la traduction",
        "activity": "{phrase} {indicator}",
        "cancel_hint": "Pour arrêter la traduction, appuyez sur « {cancel_text} » ou envoyez /cancel.",
        "elapsed": "Écoulé",
        "time_left": "Temps restant",
        "estimated_time": "Durée estimée",
        "time_unknown": "estimation en cours",
        "last_fragment": "Dernier passage traduit",
        "cancel_requested": "J’arrête la traduction après le passage en cours.",
        "nothing_to_cancel": "Aucune traduction active à arrêter.",
        "no_pending_translation": "Aucune traduction n’attend de confirmation.",
        "estimate_title": "Estimation de traduction",
        "book": "Livre",
        "mode": "Mode",
        "file": "Fichier",
        "format": "Format",
        "characters": "Caractères",
        "tokens": "Jetons estimés",
        "price": "Prix",
        "translation_mode_document_form_summary": (
            "Mode document/formulaire : la structure, les libellés, les tableaux, "
            "les nombres, les dates, les adresses, les signatures et les champs "
            "protégés restent prioritaires."
        ),
        "translation_mode_book_manuscript_summary": (
            "Mode livre/manuscrit : les chapitres, les paragraphes, la continuité "
            "et la voix de l’auteur restent prioritaires."
        ),
        "preservation_note": "Je préserverai les chapitres, paragraphes et autant de mise en forme que le fichier le permet.",
        "confirm_instruction": "Appuyez sur « {confirm_text} » pour lancer la traduction.",
        "queue_instruction": "Appuyez sur « {confirm_text} » pour mettre la traduction en file d’attente.",
        "queued": "Votre traduction est en file d’attente : {file_name}.",
        "translating": "Votre traduction est en cours : {file_name}.",
        "ready": "Votre traduction est prête.\n\nVous pouvez télécharger le fichier ci-dessous : {result_name}.",
        "partial": "La traduction est terminée avec des passages ignorés.\n\nRésultat partiel : {result_name}.\n\nCertains passages restent dans la langue d'origine. Vous pourrez continuer depuis My Books plus tard sans téléverser à nouveau le fichier.",
        "cancelled": "Traduction annulée.\n\nRésultat partiel : {result_name}.",
        "cancelled_without_result": (
            "Traduction annulée.\n\n"
            "Aucun résultat partiel n'est encore disponible, car la traduction a été annulée avant le premier passage traduit."
        ),
        "failed": "Un problème est survenu pendant la traduction.\n\nVotre fichier est en sécurité. Réessayez ou revenez au menu principal.",
        "status": "Statut de la traduction : {status}",
        "unsupported_file": "Ce type de fichier n’est pas encore pris en charge.\n\nVeuillez envoyer l’un de ces formats :\n{formats}",
        "file_too_large": "Ce fichier dépasse la limite actuelle de {limit}.\n\nEssayez un fichier plus petit ou divisez le livre en chapitres.",
        "empty_file": "Ce fichier est vide. Envoyez un livre, un chapitre ou un manuscrit contenant du texte.",
        "extraction_failed": "Je n’ai pas pu lire ce fichier de façon fiable.\n\nEssayez une copie plus propre ou utilisez l’un de ces formats :\n{formats}",
        "translation_failed": "Un problème est survenu pendant la traduction.\n\nVotre fichier est en sécurité. Réessayez ou revenez au menu principal.",
        "preview_already_generated": (
            "Un aperçu pour ce même document, cette langue et ce mode est "
            "déjà prêt. Je ne peux pas lancer un autre aperçu identique pour "
            "le moment. Revenez en arrière ou ouvrez Mes livres pour vérifier "
            "le travail existant."
        ),
        "unknown_text": "Envoyez un livre, un chapitre ou un manuscrit pour commencer, ou choisissez une option dans le menu principal.",
    },
    "es": {
        "main_menu": [
            "📖 Traducir un libro",
            "📚 Mis libros",
            "🧵 Cómo funciona",
            "🌍 Idioma",
            "⚙️ Ajustes",
            "Ayuda",
        ],
        "main_menu_button": "Menú principal",
        "start_title": "Bienvenido a FolioLoom.",
        "start_body": "Envía un libro, capítulo o manuscrito y te ayudaré a llevarlo a otro idioma conservando su estructura y su voz.",
        "permission_note": "Sube solo textos que te pertenezcan o que tengas permiso para traducir.",
        "main_menu_prompt": "Elige qué quieres hacer.",
        "upload_prompt": "Envíame un libro, capítulo o manuscrito.\n\nFormatos admitidos: {formats}.\n\nLeeré el archivo, prepararé el texto y te guiaré por la traducción.",
        "interface_language_prompt": "Idioma\n\nElige el idioma de la interfaz:",
        "interface_language_selected": "Idioma de la interfaz: {language_text}.",
        "settings_title": "Ajustes",
        "settings_body": "Elige cómo FolioLoom funciona para ti.",
        "settings_preview": "Vista del último pasaje",
        "settings_preview_on": "activada",
        "settings_preview_off": "desactivada",
        "settings_language": "Idioma de la interfaz",
        "my_books_title": "Mis libros",
        "my_books_empty": "Todavía no hay libros. Envía un libro o manuscrito para iniciar tu primera traducción.",
        "my_books_download_hint": "Abre un libro debajo para ver el estado, continuar o descargar.",
        "last_book": "Último libro",
        "book_button": "Libro {index}",
        "back_to_my_books": "Volver a Mis libros",
        "book_detail_title": "Detalles del libro",
        "book_detail_file": "Archivo",
        "book_detail_format": "Formato",
        "book_detail_language": "Idioma",
        "book_detail_status": "Estado",
        "book_detail_result": "Resultado",
        "book_detail_updated": "Actualizado",
        "final_download_available": "Descarga final disponible",
        "partial_download_available": "Descarga parcial disponible",
        "resume_available": "Esta traducción puede continuar desde el progreso guardado.",
        "resume_unavailable": "Esta traducción no se puede continuar ahora mismo.",
        "download_available": "descarga disponible",
        "download_missing": "sin archivo todavía",
        "download_book": "Descargar {index}",
        "download_translation": "Descargar traducción",
        "continue_translation": "Continuar traducción",
        "translation_mode_prompt": (
            "Archivo recibido.\n\n"
            "Título: {file_name}\n"
            "Formato: {file_format}\n"
            "{source_language_line}\n"
            "Elige cómo traducir este documento.\n\n"
            "{document_form_help}\n\n"
            "{book_manuscript_help}\n\n"
            "{format_scope_note}"
        ),
        "translation_mode_document_form": "Documento / formulario",
        "translation_mode_book_manuscript": "Libro / manuscrito",
        "translation_mode_document_form_help": (
            "Documento / formulario: para declaraciones, solicitudes, formularios "
            "y documentos estructurados. Daré prioridad al diseño, las etiquetas, "
            "las tablas, los números, las fechas, las direcciones, las firmas y los "
            "campos que deben conservarse."
        ),
        "translation_mode_book_manuscript_help": (
            "Libro / manuscrito: para libros, capítulos, manuscritos largos y textos "
            "editoriales. Daré prioridad a capítulos, párrafos, continuidad "
            "y voz autoral."
        ),
        "translation_mode_format_scope_note": (
            "Esta elección solo cambia el comportamiento de traducción; no añade "
            "nuevos formatos de archivo. Usa {formats}."
        ),
        "translation_mode_required": (
            "Elige cómo traducir este documento antes de elegir el idioma de destino."
        ),
        "delete_book": "Eliminar libro",
        "confirm_delete_book": "Sí, eliminar libro",
        "keep_book": "Conservar libro",
        "delete_book_confirm": "¿Eliminar este libro?\n\n{file_name} desaparecerá de Mis libros y sus archivos guardados se eliminarán del servidor de FolioLoom. Esta acción no se puede deshacer.",
        "book_deleted": "Libro eliminado.",
        "delete_unavailable": "No se pudo eliminar este libro.",
        "download_unavailable": "Este archivo todavía no está disponible para descargar.",
        "status_queued": "En cola",
        "status_translating": "Traduciéndose",
        "status_assembling": "Preparando archivo",
        "status_partial": "Parcial",
        "status_cancel_requested": "Deteniéndose",
        "status_cancelled": "Cancelada",
        "status_interrupted": "Interrumpida",
        "status_failed": "Error",
        "status_ready": "Lista",
        "status_expired": "Caducada",
        "hide_preview": "Ocultar vista",
        "show_preview": "Mostrar vista",
        "reset_settings": "Restablecer ajustes",
        "settings_reset": "Los ajustes se han restablecido. Elige de nuevo el idioma de la interfaz.",
        "translation_language_prompt": "Archivo recibido.\n\nTítulo: {file_name}\nFormato: {file_format}\n{source_language_line}\nAhora elige el idioma de traducción.",
        "rights_confirmation_prompt": (
            "Archivo recibido.\n\n"
            "Título: {file_name}\n\n"
            "Confirma que tienes derecho a traducir este documento: eres "
            "el autor o titular de los derechos, tienes permiso del titular "
            "de los derechos, o el documento está en public domain / autorizado "
            "para traducción."
        ),
        "confirm_rights": "✅ Confirmo los derechos",
        "original_language": "Idioma original",
        "source_language_with_admixtures": "{primary}; mezclas: {admixtures}",
        "back": "Atrás",
        "back_to_menu": "Volvemos al menú principal.",
        "cancel": "Cancelar",
        "confirm": "Iniciar traducción",
        "document_ready": "Todo listo para empezar.",
        "from": "Desde",
        "to": "A",
        "formats": "Formatos admitidos: {formats}.",
        "help": "Ayuda\n\nFolioLoom está pensado para traducir libros, capítulos y manuscritos.\n\nConviene saber:\n- Usa archivos {formats} limpios.\n- Los libros muy grandes pueden tardar.\n- Si hace falta, divide los manuscritos difíciles en capítulos.\n- Revisa la traducción final antes de publicarla.\n\nSube solo textos que te pertenezcan o que tengas permiso para traducir.",
        "how_it_works": "Cómo funciona FolioLoom\n\n1. Envía un libro, capítulo o manuscrito admitido.\n2. Elige el idioma de traducción.\n3. Revisa la estimación y los ajustes.\n4. Inicia la traducción.\n5. Descarga el resultado cuando esté listo.\n\nConservo capítulos, párrafos y la estructura del documento con todo el cuidado que permita el archivo.",
        "progress": "Progreso de traducción",
        "activity": "{phrase} {indicator}",
        "cancel_hint": "Para detener la traducción, pulsa «{cancel_text}» o envía /cancel.",
        "elapsed": "Transcurrido",
        "time_left": "Restante",
        "estimated_time": "Tiempo estimado",
        "time_unknown": "calculando",
        "last_fragment": "Último pasaje traducido",
        "cancel_requested": "Detendré la traducción después del pasaje actual.",
        "nothing_to_cancel": "No hay una traducción activa para detener.",
        "no_pending_translation": "No hay ninguna traducción esperando confirmación.",
        "estimate_title": "Estimación de traducción",
        "book": "Libro",
        "mode": "Modo",
        "file": "Archivo",
        "format": "Formato",
        "characters": "Caracteres",
        "tokens": "Tokens estimados",
        "price": "Precio",
        "translation_mode_document_form_summary": (
            "Modo documento/formulario: la estructura, las etiquetas, las tablas, "
            "los números, las fechas, las direcciones, las firmas y los campos "
            "protegidos son la prioridad."
        ),
        "translation_mode_book_manuscript_summary": (
            "Modo libro/manuscrito: los capítulos, párrafos, continuidad y voz "
            "autoral son la prioridad."
        ),
        "preservation_note": "Conservaré capítulos, párrafos y tanto formato como permita el archivo actual.",
        "confirm_instruction": "Pulsa «{confirm_text}» para iniciar la traducción.",
        "queue_instruction": "Pulsa «{confirm_text}» para poner la traducción en cola.",
        "queued": "Tu traducción está en cola: {file_name}.",
        "translating": "Tu traducción está en curso: {file_name}.",
        "ready": "Tu traducción está lista.\n\nPuedes descargar el archivo abajo: {result_name}.",
        "partial": "La traducción terminó con pasajes omitidos.\n\nResultado parcial: {result_name}.\n\nAlgunos pasajes permanecen en el idioma original. Más adelante podrás continuar desde My Books sin volver a subir el archivo.",
        "cancelled": "Traducción cancelada.\n\nResultado parcial: {result_name}.",
        "cancelled_without_result": (
            "Traducción cancelada.\n\n"
            "Todavía no hay un resultado parcial disponible porque la traducción se canceló antes de traducir el primer pasaje."
        ),
        "failed": "Algo salió mal durante la traducción.\n\nTu archivo está a salvo. Inténtalo de nuevo o vuelve al menú principal.",
        "status": "Estado de traducción: {status}",
        "unsupported_file": "Este tipo de archivo aún no es compatible.\n\nEnvía uno de estos formatos:\n{formats}",
        "file_too_large": "Este archivo supera el límite actual de {limit}.\n\nPrueba con un archivo más pequeño o divide el libro en capítulos.",
        "empty_file": "Este archivo está vacío. Envía un libro, capítulo o manuscrito con texto.",
        "extraction_failed": "No pude leer este archivo de forma fiable.\n\nPrueba con una copia más limpia o usa uno de estos formatos:\n{formats}",
        "translation_failed": "Algo salió mal durante la traducción.\n\nTu archivo está a salvo. Inténtalo de nuevo o vuelve al menú principal.",
        "preview_already_generated": (
            "Ya hay una vista previa preparada para este mismo documento, "
            "idioma y modo. Todavía no puedo iniciar otra vista previa "
            "idéntica. Vuelve atrás o abre Mis libros para revisar el trabajo "
            "existente."
        ),
        "unknown_text": "Envía un libro, capítulo o manuscrito para empezar, o elige una opción del menú principal.",
    },
    "nl": {
        "main_menu": [
            "📖 Boek vertalen",
            "📚 Mijn boeken",
            "🧵 Zo werkt het",
            "🌍 Taal",
            "⚙️ Instellingen",
            "Hulp",
        ],
        "main_menu_button": "Hoofdmenu",
        "start_title": "Welkom bij FolioLoom.",
        "start_body": "Stuur een boek, hoofdstuk of manuscript, dan help ik het naar een nieuwe taal te brengen met behoud van structuur en stem.",
        "permission_note": "Upload alleen teksten die van jou zijn of waarvoor je toestemming hebt om ze te vertalen.",
        "main_menu_prompt": "Kies wat je wilt doen.",
        "upload_prompt": "Stuur me een boek, hoofdstuk of manuscript.\n\nOndersteunde formaten: {formats}.\n\nIk lees het bestand, bereid de tekst voor en begeleid je door de vertaling.",
        "interface_language_prompt": "Taal\n\nKies de interfacetaal:",
        "interface_language_selected": "Interfacetaal: {language_text}.",
        "settings_title": "Instellingen",
        "settings_body": "Kies hoe FolioLoom voor jou werkt.",
        "settings_preview": "Voorbeeld van laatste passage",
        "settings_preview_on": "aan",
        "settings_preview_off": "uit",
        "settings_language": "Interfacetaal",
        "my_books_title": "Mijn boeken",
        "my_books_empty": "Nog geen boeken. Stuur een boek of manuscript om je eerste vertaling te starten.",
        "my_books_download_hint": "Open hieronder een boek om de status te bekijken, verder te gaan of te downloaden.",
        "last_book": "Laatste boek",
        "book_button": "Boek {index}",
        "back_to_my_books": "Terug naar Mijn boeken",
        "book_detail_title": "Boekdetails",
        "book_detail_file": "Bestand",
        "book_detail_format": "Formaat",
        "book_detail_language": "Taal",
        "book_detail_status": "Status",
        "book_detail_result": "Resultaat",
        "book_detail_updated": "Bijgewerkt",
        "final_download_available": "Definitieve download beschikbaar",
        "partial_download_available": "Gedeeltelijke download beschikbaar",
        "resume_available": "Deze vertaling kan vanaf de opgeslagen voortgang worden hervat.",
        "resume_unavailable": "Deze vertaling kan nu niet worden hervat.",
        "download_available": "download beschikbaar",
        "download_missing": "nog geen bestand",
        "download_book": "Download {index}",
        "download_translation": "Vertaling downloaden",
        "continue_translation": "Vertaling hervatten",
        "translation_mode_prompt": (
            "Bestand ontvangen.\n\n"
            "Titel: {file_name}\n"
            "Formaat: {file_format}\n"
            "{source_language_line}\n"
            "Kies hoe dit document moet worden vertaald.\n\n"
            "{document_form_help}\n\n"
            "{book_manuscript_help}\n\n"
            "{format_scope_note}"
        ),
        "translation_mode_document_form": "Document / formulier",
        "translation_mode_book_manuscript": "Boek / manuscript",
        "translation_mode_document_form_help": (
            "Document / formulier: voor verklaringen, aanvragen, formulieren en "
            "gestructureerde documenten. Ik geef voorrang aan opmaak, labels, "
            "tabellen, nummers, datums, adressen, handtekeningen en velden die "
            "behouden moeten blijven."
        ),
        "translation_mode_book_manuscript_help": (
            "Boek / manuscript: voor boeken, hoofdstukken, lange manuscripten en "
            "redactionele tekst. Ik geef voorrang aan hoofdstukken, alinea’s, "
            "continuïteit en auteursstem."
        ),
        "translation_mode_format_scope_note": (
            "Deze keuze verandert alleen het vertaalgedrag; er komen geen nieuwe "
            "bestandsformaten bij. Gebruik {formats}."
        ),
        "translation_mode_required": (
            "Kies hoe dit document moet worden vertaald voordat je de "
            "doeltaal kiest."
        ),
        "delete_book": "Boek verwijderen",
        "confirm_delete_book": "Ja, boek verwijderen",
        "keep_book": "Boek bewaren",
        "delete_book_confirm": "Dit boek verwijderen?\n\n{file_name} verdwijnt uit Mijn boeken en de opgeslagen bestanden worden van de FolioLoom-server verwijderd. Dit kan niet ongedaan worden gemaakt.",
        "book_deleted": "Boek verwijderd.",
        "delete_unavailable": "Dit boek kon niet worden verwijderd.",
        "download_unavailable": "Dit bestand is nog niet beschikbaar om te downloaden.",
        "status_queued": "In wachtrij",
        "status_translating": "Wordt vertaald",
        "status_assembling": "Wordt samengesteld",
        "status_partial": "Gedeeltelijk",
        "status_cancel_requested": "Wordt gestopt",
        "status_cancelled": "Geannuleerd",
        "status_interrupted": "Onderbroken",
        "status_failed": "Mislukt",
        "status_ready": "Klaar",
        "status_expired": "Verlopen",
        "hide_preview": "Voorbeeld verbergen",
        "show_preview": "Voorbeeld tonen",
        "reset_settings": "Instellingen resetten",
        "settings_reset": "De instellingen zijn gereset. Kies opnieuw de interfacetaal.",
        "translation_language_prompt": "Bestand ontvangen.\n\nTitel: {file_name}\nFormaat: {file_format}\n{source_language_line}\nKies nu de taal waarnaar je wilt vertalen.",
        "rights_confirmation_prompt": (
            "Bestand ontvangen.\n\n"
            "Titel: {file_name}\n\n"
            "Bevestig dat je het recht hebt om dit document te vertalen: "
            "je bent de auteur of rechthebbende, je hebt toestemming van de "
            "rechthebbende, of het document is public domain / toegestaan voor "
            "vertaling."
        ),
        "confirm_rights": "✅ Ik bevestig de rechten",
        "original_language": "Brontaal",
        "source_language_with_admixtures": "{primary}; bijmenging: {admixtures}",
        "back": "Terug",
        "back_to_menu": "Terug naar het Hoofdmenu.",
        "cancel": "Annuleren",
        "confirm": "Vertaling starten",
        "document_ready": "Klaar om te beginnen.",
        "from": "Van",
        "to": "Naar",
        "formats": "Ondersteunde formaten: {formats}.",
        "help": "Hulp\n\nFolioLoom is bedoeld voor het vertalen van boeken, hoofdstukken en manuscripten.\n\nGoed om te weten:\n- Gebruik schone {formats}-bestanden.\n- Zeer grote boeken kunnen tijd kosten.\n- Splits lastige manuscripten indien nodig in hoofdstukken.\n- Controleer de eindvertaling voor publicatie.\n\nUpload alleen teksten die van jou zijn of waarvoor je toestemming hebt om ze te vertalen.",
        "how_it_works": "Zo werkt FolioLoom\n\n1. Stuur een ondersteund boek, hoofdstuk of manuscript.\n2. Kies de taal voor de vertaling.\n3. Controleer de inschatting en instellingen.\n4. Start de vertaling.\n5. Download het resultaat zodra het klaar is.\n\nIk behoud hoofdstukken, alinea’s en documentstructuur zo zorgvuldig als het bestand toelaat.",
        "progress": "Vertaalvoortgang",
        "activity": "{phrase} {indicator}",
        "cancel_hint": "Om de vertaling te stoppen, druk op “{cancel_text}” of stuur /cancel.",
        "elapsed": "Verstreken",
        "time_left": "Resterende tijd",
        "estimated_time": "Geschatte tijd",
        "time_unknown": "wordt geschat",
        "last_fragment": "Laatste vertaalde passage",
        "cancel_requested": "Ik stop de vertaling na de huidige passage.",
        "nothing_to_cancel": "Er is nu geen actieve vertaling om te stoppen.",
        "no_pending_translation": "Er wacht geen vertaling op bevestiging.",
        "estimate_title": "Vertaalinschatting",
        "book": "Boek",
        "mode": "Modus",
        "file": "Bestand",
        "format": "Formaat",
        "characters": "Tekens",
        "tokens": "Geschatte tokens",
        "price": "Prijs",
        "translation_mode_document_form_summary": (
            "Document/formulier-modus: structuur, labels, tabellen, nummers, datums, "
            "adressen, handtekeningen en beschermde velden blijven de prioriteit."
        ),
        "translation_mode_book_manuscript_summary": (
            "Boek/manuscript-modus: hoofdstukken, alinea’s, continuïteit en "
            "auteursstem blijven de prioriteit."
        ),
        "preservation_note": "Ik behoud hoofdstukken, alinea’s en zoveel opmaak als het huidige bestand toelaat.",
        "confirm_instruction": "Druk op “{confirm_text}” om de vertaling te starten.",
        "queue_instruction": "Druk op “{confirm_text}” om de vertaling in de wachtrij te zetten.",
        "queued": "Je vertaling staat in de wachtrij: {file_name}.",
        "translating": "Je vertaling wordt uitgevoerd: {file_name}.",
        "ready": "Je vertaling is klaar.\n\nJe kunt het bestand hieronder downloaden: {result_name}.",
        "partial": "De vertaling is voltooid met overgeslagen passages.\n\nGedeeltelijk resultaat: {result_name}.\n\nSommige passages blijven in de oorspronkelijke taal. Je kunt later doorgaan vanuit My Books zonder het bestand opnieuw te uploaden.",
        "cancelled": "Vertaling geannuleerd.\n\nGedeeltelijk resultaat: {result_name}.",
        "cancelled_without_result": (
            "Vertaling geannuleerd.\n\n"
            "Er is nog geen gedeeltelijk resultaat beschikbaar omdat de vertaling is geannuleerd voordat er een passage was vertaald."
        ),
        "failed": "Er ging iets mis tijdens het vertalen.\n\nJe bestand is veilig. Probeer het opnieuw of ga terug naar het hoofdmenu.",
        "status": "Vertaalstatus: {status}",
        "unsupported_file": "Dit bestandstype wordt nog niet ondersteund.\n\nStuur een van deze formaten:\n{formats}",
        "file_too_large": "Dit bestand is groter dan de huidige limiet van {limit}.\n\nProbeer een kleiner bestand of splits het boek in hoofdstukken.",
        "empty_file": "Dit bestand is leeg. Stuur een boek, hoofdstuk of manuscript met tekst.",
        "extraction_failed": "Ik kon dit bestand niet betrouwbaar lezen.\n\nProbeer een schonere kopie of gebruik een van deze formaten:\n{formats}",
        "translation_failed": "Er ging iets mis tijdens het vertalen.\n\nJe bestand is veilig. Probeer het opnieuw of ga terug naar het hoofdmenu.",
        "preview_already_generated": (
            "Er staat al een voorbeeld klaar voor hetzelfde document, dezelfde "
            "taal en dezelfde modus. Ik kan nog geen tweede identiek voorbeeld "
            "starten. Ga terug of open Mijn boeken om bestaand werk te "
            "controleren."
        ),
        "unknown_text": "Stuur een boek, hoofdstuk of manuscript om te beginnen, of kies een optie in het Hoofdmenu.",
    },
}.items():
    MESSAGES[_language_code] = {**MESSAGES["en"], **_fallbacks}


def build_main_menu(interface_language: str = "en") -> list[str]:
    return list(_messages(interface_language)["main_menu"])


def build_start_message(interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    return (
        f"{messages['start_title']}\n\n"
        f"{messages['tagline']}\n\n"
        f"{messages['start_body']}\n\n"
        f"{messages['permission_note']}\n\n"
        f"{messages['formats'].format(formats=_supported_formats_text())}\n\n"
        f"{messages['main_menu_prompt']}"
    )


def get_main_menu_text(interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    return f"{messages['main_menu_title']}\n\n{messages['main_menu_prompt']}"


def build_upload_prompt_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["upload_prompt"].format(
        formats=_supported_formats_text()
    )


def build_help_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["help"].format(
        formats=_supported_formats_text()
    )


def build_how_it_works_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["how_it_works"]


def build_unknown_text_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["unknown_text"]


def build_settings_message(
    *,
    interface_language: str = "en",
    progress_preview_enabled: bool = True,
) -> str:
    messages = _messages(interface_language)
    preview_status = (
        messages["settings_preview_on"]
        if progress_preview_enabled
        else messages["settings_preview_off"]
    )
    language_name = localized_language_name_for_code(
        interface_language,
        interface_language,
    )
    return (
        f"{messages['settings_title']}\n\n"
        f"{messages['settings_body']}\n\n"
        f"{messages['settings_preview']}: {preview_status}\n"
        f"{messages['settings_language']}: {language_name}"
    )


def build_my_books_message(
    books,
    interface_language: str = "en",
    queue_summary=None,
) -> str:
    messages = _messages(interface_language)
    if not books:
        lines = [messages["my_books_title"]]
        lines.extend(_queue_summary_lines(queue_summary, interface_language))
        lines.extend(["", messages["my_books_empty"]])
        return "\n".join(lines)

    lines = [messages["my_books_title"], ""]
    queue_lines = _queue_summary_lines(queue_summary, interface_language)
    if queue_lines:
        lines = [messages["my_books_title"], *queue_lines, ""]
    latest = _book_value(books[0])
    lines.extend(
        [
            f"{messages['last_book']}: {latest.get('file_name', '-')}",
            "",
        ]
    )
    for index, book in enumerate(books, start=1):
        value = _book_value(book)
        availability = (
            messages["download_available"]
            if bool(value.get("has_result"))
            else messages["download_missing"]
        )
        lines.append(
            f"{index}. {value.get('file_name', '-')}"
            f" · {_language_pair_text(value, interface_language)}"
            f" · {_status_label(value.get('status', '-'), interface_language)}"
            f" · {availability}"
        )
    lines.extend(["", messages["my_books_download_hint"]])
    return "\n".join(lines)


def _queue_summary_lines(queue_summary, interface_language: str) -> list[str]:
    if queue_summary is None:
        return []
    value = _book_value(queue_summary)
    total = int(value.get("total_active") or 0)
    if total <= 0:
        return []
    messages = _messages(interface_language)
    lines = [
        messages["queue_title"],
        messages["queue_summary"].format(
            total=total,
            queued=int(value.get("queued") or 0),
            translating=int(value.get("translating") or 0),
        ),
    ]
    for index, book in enumerate(value.get("items") or (), start=1):
        book_value = _book_value(book)
        lines.append(
            f"{index}. {book_value.get('file_name', '-')}"
            f" · {_status_label(book_value.get('status', '-'), interface_language)}"
        )
    return lines


def build_my_book_detail_message(book, interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    value = _book_value(book)
    result_text = messages["download_missing"]
    if bool(value.get("has_result")):
        result_text = (
            messages["partial_download_available"]
            if bool(value.get("has_partial_result"))
            else messages["final_download_available"]
        )
    resume_text = (
        messages["resume_available"]
        if bool(value.get("can_resume"))
        else messages["resume_unavailable"]
    )
    updated_at = value.get("updated_at")
    lines = [
        messages["book_detail_title"],
        "",
        f"{messages['book_detail_file']}: {value.get('file_name', '-')}",
        f"{messages['book_detail_format']}: {str(value.get('document_kind', '-')).upper()}",
        f"{messages['book_detail_language']}: {_language_pair_text(value, interface_language)}",
        f"{messages['book_detail_status']}: {_status_label(value.get('status', '-'), interface_language)}",
    ]
    progress_line = _book_progress_line(value, interface_language)
    if progress_line is not None:
        lines.append(progress_line)
    lines.append(f"{messages['book_detail_result']}: {result_text}")
    if updated_at:
        lines.append(f"{messages['book_detail_updated']}: {updated_at}")
    lines.extend(["", resume_text])
    return "\n".join(lines)


def build_delete_book_confirmation_message(book, interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    value = _book_value(book)
    return messages["delete_book_confirm"].format(
        file_name=value.get("file_name", "-")
    )


def build_book_deleted_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["book_deleted"]


def build_delete_unavailable_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["delete_unavailable"]


def build_language_selection_message(interface_language: str = "en") -> str:
    language_lines = "\n".join(
        f"- {language.button_text}" for language in SUPPORTED_TARGET_LANGUAGES
    )
    return f"{_messages(interface_language)['interface_language_prompt']}\n{language_lines}"


def build_language_selected_message(
    language_text: str,
    interface_language: str = "en",
) -> str:
    return _messages(interface_language)["interface_language_selected"].format(
        language_text=language_text
    )


def build_translation_language_selection_message(
    file_name: str,
    interface_language: str = "en",
    source_language_display: str | None = None,
) -> str:
    messages = _messages(interface_language)
    language_lines = "\n".join(
        f"- {language.button_text}" for language in SUPPORTED_TARGET_LANGUAGES
    )
    source_language_line = (
        f"{messages['original_language']}: {_localized_source_language_display_text(source_language_display, 'auto', interface_language)}\n"
        if source_language_display
        else ""
    )
    return (
        messages["translation_language_prompt"].format(
            file_name=file_name,
            file_format=_file_format_label(file_name),
            source_language_line=source_language_line,
        )
        + f"\n{language_lines}"
    )


def build_translation_mode_selection_message(
    file_name: str,
    interface_language: str = "en",
    source_language_display: str | None = None,
) -> str:
    messages = _messages(interface_language)
    source_language_line = ""
    if source_language_display:
        localized_source_language = _localized_source_language_display_text(
            source_language_display,
            "auto",
            interface_language,
        )
        source_language_line = (
            f"{messages['original_language']}: {localized_source_language}\n"
        )
    return messages["translation_mode_prompt"].format(
        file_name=file_name,
        file_format=_file_format_label(file_name),
        source_language_line=source_language_line,
        document_form_help=messages["translation_mode_document_form_help"],
        book_manuscript_help=messages["translation_mode_book_manuscript_help"],
        format_scope_note=messages["translation_mode_format_scope_note"].format(
            formats=_supported_formats_text()
        ),
    )


def build_rights_confirmation_message(
    file_name: str,
    interface_language: str = "en",
) -> str:
    return _messages(interface_language)["rights_confirmation_prompt"].format(
        file_name=file_name,
    )


def build_order_estimate_message(
    estimate: OrderEstimate,
    interface_language: str = "en",
) -> str:
    messages = _messages(interface_language)
    confirm_text = get_confirm_translation_text(interface_language)
    return (
        f"{messages['estimate_title']}\n\n"
        f"{messages['file']}: {estimate.file_name}\n"
        f"{messages['format']}: {estimate.document_format.value.upper()}\n"
        f"{messages['characters']}: {estimate.character_count}\n"
        "\n"
        f"{messages['queue_instruction'].format(confirm_text=confirm_text)}"
    )


def build_pending_translation_message(
    pending: PendingTranslation,
    interface_language: str = "en",
) -> str:
    messages = _messages(interface_language)
    confirm_text = get_confirm_translation_text(interface_language)
    source_text = _localized_source_language_display_text(
        pending.source_language_display,
        pending.source_language,
        interface_language,
    )
    target_text = localized_language_name_for_code(
        pending.target_language,
        interface_language,
    )
    duration_text = _format_duration(
        pending.estimated_seconds or 0,
        interface_language,
    )
    lines = [
        messages["document_ready"],
        "",
        f"{messages['book']}: {pending.file_name}",
        f"{messages['from']}: {source_text}",
        f"{messages['to']}: {target_text}",
    ]
    mode_display = _translation_mode_display(
        pending.translation_mode,
        interface_language,
    )
    if mode_display is not None:
        mode_label, mode_summary = mode_display
        lines.extend(
            [
                f"{messages['mode']}: {mode_label}",
                mode_summary,
            ]
        )
    lines.extend(
        [
            f"{messages['estimated_time']}: {duration_text}",
            "",
            messages["preservation_note"],
            "",
            messages["confirm_instruction"].format(confirm_text=confirm_text),
        ]
    )
    return "\n".join(lines)


def build_preview_translation_message(
    preview: PreviewTranslation,
    interface_language: str = "en",
) -> str:
    messages = _messages(interface_language)
    safe_preview = html.escape(preview.text.strip())
    return (
        f"{messages['preview_title']}\n\n"
        f"{messages['book']}: {preview.file_name}\n"
        f"{messages['to']}: {localized_language_name_for_code(preview.target_language, interface_language)}\n"
        f"{messages['preview_cost_placeholder']}\n\n"
        f"{messages['preview_body']}\n\n"
        f"<blockquote>{safe_preview}</blockquote>\n\n"
        f"{messages['preview_instruction']}"
    )


def build_preview_required_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["preview_required"]


def build_duplicate_upload_message(match, interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    status = getattr(match, "status", "")
    if status == "ready":
        return messages["duplicate_ready"]
    if status in {"queued", "translating", "assembling", "cancel_requested"}:
        return messages["duplicate_active"]
    return messages["duplicate_existing"]


def get_duplicate_translate_again_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["duplicate_translate_again"]


def get_duplicate_open_existing_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["duplicate_open_existing"]


def build_translation_mode_required_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["translation_mode_required"]


def get_translation_mode_document_form_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["translation_mode_document_form"]


def get_translation_mode_book_manuscript_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["translation_mode_book_manuscript"]


def _translation_mode_display(
    translation_mode: str | None,
    interface_language: str,
) -> tuple[str, str] | None:
    messages = _messages(interface_language)
    if translation_mode == TRANSLATION_MODE_DOCUMENT_FORM:
        return (
            messages["translation_mode_document_form"],
            messages["translation_mode_document_form_summary"],
        )
    if translation_mode == TRANSLATION_MODE_BOOK_MANUSCRIPT:
        return (
            messages["translation_mode_book_manuscript"],
            messages["translation_mode_book_manuscript_summary"],
        )
    return None


def translation_mode_for_button_text(text: str | None) -> str | None:
    normalized = _normalize_text(text)
    if not normalized:
        return None

    for messages in MESSAGES.values():
        if normalized == messages["translation_mode_document_form"].lower():
            return TRANSLATION_MODE_DOCUMENT_FORM
        if normalized == messages["translation_mode_book_manuscript"].lower():
            return TRANSLATION_MODE_BOOK_MANUSCRIPT
    return None


def is_translation_mode_button_text(text: str | None) -> bool:
    return translation_mode_for_button_text(text) is not None


def is_confirm_translation_text(text: str | None) -> bool:
    if text is None:
        return False

    normalized = text.strip().lower()
    localized_confirm_texts = {
        messages["confirm"].lower() for messages in MESSAGES.values()
    }
    legacy_confirm_texts = {
        "подтвердить",
        "підтвердити",
        "confirmer",
        "confirmar",
        "confirm",
        "bevestigen",
    }
    return normalized in localized_confirm_texts | legacy_confirm_texts | {"/confirm"}


def is_continue_translation_text(text: str | None) -> bool:
    return _matches_localized_text(text, "continue_translation")


def get_confirm_rights_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["confirm_rights"]


def is_confirm_rights_text(text: str | None) -> bool:
    return _matches_localized_text(text, "confirm_rights")


def is_translate_book_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 0)


def is_my_books_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 1)


def is_how_it_works_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 2)


def is_language_menu_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 3)


def is_settings_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 4)


def is_help_text(text: str | None) -> bool:
    return _matches_main_menu_item(text, 5)


def is_toggle_progress_preview_text(text: str | None) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    return normalized in {
        messages[key].lower()
        for messages in MESSAGES.values()
        for key in ("hide_preview", "show_preview")
    }


def is_reset_settings_text(text: str | None) -> bool:
    return _matches_localized_text(text, "reset_settings")


def is_main_menu_text(text: str | None) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    return normalized in {
        messages["main_menu_button"].lower() for messages in MESSAGES.values()
    }


def is_back_text(text: str | None) -> bool:
    return _matches_localized_text(text, "back")


def is_cancel_text(text: str | None) -> bool:
    return _matches_localized_text(text, "cancel") or _normalize_text(text) == "/cancel"


def build_translation_progress_message(
    *,
    completed_fragments: int,
    total_fragments: int,
    interface_language: str = "en",
    estimated_total_seconds: int | None = None,
    elapsed_seconds: int | None = None,
    last_translated_text: str | None = None,
    activity_indicator: str = "⠋",
    activity_phrase_index: int = 5,
) -> str:
    messages = _messages(interface_language)
    safe_total = max(total_fragments, 1)
    actual_percent = min(100, round(completed_fragments / safe_total * 100))
    estimated_percent = 0
    if estimated_total_seconds and elapsed_seconds is not None:
        estimated_percent = min(
            95,
            round(elapsed_seconds / max(estimated_total_seconds, 1) * 100),
        )
    percent = max(actual_percent, estimated_percent)
    filled_cells = min(10, percent // 10)
    bar = "#" * filled_cells + "-" * (10 - filled_cells)
    elapsed_line = ""
    if elapsed_seconds is not None:
        elapsed_line = f"\n{messages['elapsed']}: {_format_duration(elapsed_seconds, interface_language)}"

    time_left = messages["time_unknown"]
    if estimated_total_seconds is not None and elapsed_seconds is not None:
        remaining_seconds = max(0, estimated_total_seconds - elapsed_seconds)
        time_left = f"~{_format_duration(remaining_seconds, interface_language)}"

    last_fragment_line = ""
    if last_translated_text:
        last_fragment_line = (
            f"{messages['last_fragment']}:\n"
            f"<blockquote expandable>{html.escape(_shorten_progress_fragment(last_translated_text))}</blockquote>"
        )
    last_fragment_section = f"\n\n{last_fragment_line}" if last_fragment_line else ""

    return (
        f"{messages['progress']}: [{bar}] "
        f"{percent}%"
        f"{elapsed_line}\n"
        f"{messages['time_left']}: {time_left}"
        f"\n{messages['activity'].format(phrase=get_progress_activity_phrase(interface_language, activity_phrase_index), indicator=activity_indicator)}"
        f"{last_fragment_section}\n\n"
        f"{build_cancel_hint_message(interface_language)}"
    )


def build_cancel_requested_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["cancel_requested"]


def get_progress_activity_phrase(
    interface_language: str = "en",
    phrase_index: int = 0,
) -> str:
    phrases = get_activity_phrases(interface_language)
    return phrases[phrase_index % len(phrases)]


def build_nothing_to_cancel_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["nothing_to_cancel"]


def build_no_pending_translation_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["no_pending_translation"]


def build_back_to_menu_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["back_to_menu"]


def build_settings_reset_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["settings_reset"]


def build_cancel_hint_message(interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    return messages["cancel_hint"].format(cancel_text=messages["cancel"])


def _format_duration(seconds: int, interface_language: str = "en") -> str:
    safe_seconds = max(0, round(seconds))
    minutes, remaining_seconds = divmod(safe_seconds, 60)
    hours, remaining_minutes = divmod(minutes, 60)
    units = _time_units(interface_language)

    if hours:
        return f"{hours} {units['hour']} {remaining_minutes} {units['minute']}"
    if minutes:
        return f"{minutes} {units['minute']} {remaining_seconds} {units['second']}"
    return f"{remaining_seconds} {units['second']}"


def _shorten_progress_fragment(text: str, max_length: int = 500) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 1].rstrip() + "…"


def get_back_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["back"]


def get_cancel_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["cancel"]


def build_translation_job_status_message(
    job: TranslationJob,
    interface_language: str = "en",
) -> str:
    messages = _messages(interface_language)
    if job.status is TranslationJobStatus.QUEUED:
        return messages["queued"].format(file_name=job.file_name)

    if job.status is TranslationJobStatus.TRANSLATING:
        return messages["translating"].format(file_name=job.file_name)

    if job.status is TranslationJobStatus.PAUSED:
        return messages.get(
            "paused",
            messages["status"].format(status=job.status.value),
        )

    if job.status is TranslationJobStatus.READY:
        result_name = job.result_file_name or "результат"
        return messages["ready"].format(result_name=result_name)

    if job.status is TranslationJobStatus.PARTIAL:
        result_name = job.result_file_name or "partial result"
        return messages["partial"].format(result_name=result_name)

    if job.status is TranslationJobStatus.FAILED:
        return messages["failed"]

    if job.status is TranslationJobStatus.CANCELLED:
        if not job.result_file_name:
            return messages["cancelled_without_result"]
        result_name = job.result_file_name or "partial result"
        return messages["cancelled"].format(result_name=result_name)

    if job.status is TranslationJobStatus.DELETED:
        return messages.get(
            "deleted",
            messages["status"].format(status=job.status.value),
        )

    return messages["status"].format(status=job.status.value)


def get_confirm_translation_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["confirm"]


def get_main_menu_button_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["main_menu_button"]


def get_toggle_progress_preview_text(
    interface_language: str = "en",
    progress_preview_enabled: bool = True,
) -> str:
    key = "hide_preview" if progress_preview_enabled else "show_preview"
    return _messages(interface_language)[key]


def get_reset_settings_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["reset_settings"]


def get_download_book_text(index: int, interface_language: str = "en") -> str:
    return _messages(interface_language)["download_book"].format(index=index)


def get_last_book_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["last_book"]


def get_open_book_text(index: int, interface_language: str = "en") -> str:
    return _messages(interface_language)["book_button"].format(index=index)


def get_download_translation_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["download_translation"]


def get_continue_translation_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["continue_translation"]


def get_delete_book_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["delete_book"]


def get_confirm_delete_book_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["confirm_delete_book"]


def get_keep_book_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["keep_book"]


def get_back_to_my_books_text(interface_language: str = "en") -> str:
    return _messages(interface_language)["back_to_my_books"]


def build_download_unavailable_message(interface_language: str = "en") -> str:
    return _messages(interface_language)["download_unavailable"]


def build_upload_error_message(error: Exception, interface_language: str = "en") -> str:
    messages = _messages(interface_language)
    if isinstance(error, BetaAccessDenied):
        return messages.get("beta_access_denied", MESSAGES["en"]["beta_access_denied"])
    if isinstance(error, SecurityCooldownActive):
        return messages.get("security_cooldown", messages["translation_failed"])
    if isinstance(error, DuplicatePreviewError):
        return messages.get("preview_already_generated", str(error))
    if isinstance(error, UnsupportedDocumentError):
        return messages["unsupported_file"].format(formats=_supported_formats_lines())
    if isinstance(error, ValueError) and "TXT, DOCX, and EPUB" in str(error):
        return messages["unsupported_file"].format(formats=_supported_formats_lines())
    if isinstance(error, FileTooLargeError):
        return messages["file_too_large"].format(limit=_upload_limit_from_error(error))
    if isinstance(error, EmptyDocumentError):
        return messages["empty_file"]
    if isinstance(error, TextExtractionError):
        return messages["extraction_failed"].format(formats=_supported_formats_lines())
    return messages["translation_failed"]


def _messages(interface_language: str) -> dict:
    return MESSAGES.get(interface_language, MESSAGES["en"])


def _book_value(book, key: str | None = None):
    if isinstance(book, dict):
        return book if key is None else book.get(key)
    if key is None:
        return {
            "file_name": getattr(book, "file_name", "-"),
            "job_id": getattr(book, "job_id", "-"),
            "document_kind": getattr(book, "document_kind", "-"),
            "source_language": getattr(book, "source_language", "-"),
            "target_language": getattr(book, "target_language", "-"),
            "status": getattr(book, "status", "-"),
            "has_result": getattr(book, "has_result", False),
            "has_partial_result": getattr(book, "has_partial_result", False),
            "can_resume": getattr(book, "can_resume", False),
            "can_cancel": getattr(book, "can_cancel", False),
            "created_at": getattr(book, "created_at", None),
            "updated_at": getattr(book, "updated_at", None),
            "progress_completed_fragments": getattr(
                book,
                "progress_completed_fragments",
                None,
            ),
            "progress_total_fragments": getattr(
                book,
                "progress_total_fragments",
                None,
            ),
            "progress_percent": getattr(book, "progress_percent", None),
            "total_active": getattr(book, "total_active", None),
            "queued": getattr(book, "queued", None),
            "translating": getattr(book, "translating", None),
            "items": getattr(book, "items", ()),
        }
    return getattr(book, key)


def _language_pair_text(book: dict, interface_language: str) -> str:
    source_language = str(book.get("source_language") or "-")
    target_language = str(book.get("target_language") or "-")
    source_text = localized_language_name_for_code(source_language, interface_language)
    target_text = localized_language_name_for_code(target_language, interface_language)
    return f"{source_text} -> {target_text}"


def _status_label(status: object, interface_language: str) -> str:
    raw_status = str(status or "-")
    messages = _messages(interface_language)
    return messages.get(
        f"status_{raw_status}",
        raw_status.replace("_", " ").title(),
    )


def _book_progress_line(book: dict, interface_language: str) -> str | None:
    completed = _optional_int(book.get("progress_completed_fragments"))
    total = _optional_int(book.get("progress_total_fragments"))
    if completed is None or total is None or total <= 0:
        return None
    completed = min(max(0, completed), total)
    percent = _optional_int(book.get("progress_percent"))
    if percent is None:
        percent = round(completed / total * 100)
    percent = min(100, max(0, percent))
    progress_label = _messages(interface_language)["progress"]
    return f"{progress_label}: {percent}% ({completed}/{total})"


def _optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _time_units(interface_language: str) -> dict[str, str]:
    return {
        "en": {"hour": "h", "minute": "min", "second": "sec"},
        "ru": {"hour": "ч", "minute": "мин", "second": "сек"},
        "uk": {"hour": "год", "minute": "хв", "second": "с"},
        "fr": {"hour": "h", "minute": "min", "second": "s"},
        "es": {"hour": "h", "minute": "min", "second": "s"},
        "nl": {"hour": "u", "minute": "min", "second": "sec"},
    }.get(interface_language, {"hour": "h", "minute": "min", "second": "sec"})


def _localized_source_language_display_text(
    source_language_display: str | None,
    source_language: str,
    interface_language: str,
) -> str:
    display = source_language_display
    if not display:
        return localized_language_name_for_code(source_language, interface_language)

    normalized = display.strip()
    if "(admixtures:" in normalized.lower() and normalized.endswith(")"):
        primary, detail = normalized.split("(", 1)
        names = detail[:-1].split(":", 1)[1]
        localized_primary = _localized_name_from_display_name(
            primary.strip(),
            interface_language,
        )
        localized_admixtures = [
            _localized_name_from_display_name(name.strip(), interface_language)
            for name in names.split(",")
            if name.strip()
        ]
        return _messages(interface_language)["source_language_with_admixtures"].format(
            primary=localized_primary,
            admixtures=", ".join(localized_admixtures),
        )

    if normalized.lower().startswith("auto"):
        auto_text = localized_language_name_for_code("auto", interface_language)
        if "(" not in normalized or not normalized.endswith(")"):
            return auto_text
        detail = normalized.split("(", 1)[1][:-1].strip()
        if detail.lower().startswith("mixed:"):
            names = detail.split(":", 1)[1]
            localized_names = [
                _localized_name_from_display_name(name.strip(), interface_language)
                for name in names.split(",")
                if name.strip()
            ]
            mixed_text = localized_language_name_for_code("mixed", interface_language)
            return f"{auto_text} ({mixed_text}: {', '.join(localized_names)})"
        return f"{auto_text} ({_localized_name_from_display_name(detail, interface_language)})"

    return _localized_name_from_display_name(normalized, interface_language)


def _localized_name_from_display_name(
    language_name: str,
    interface_language: str,
) -> str:
    language_code = language_code_for_name(language_name)
    if language_code is None:
        return language_name
    return localized_language_name_for_code(language_code, interface_language)


def _matches_localized_text(text: str | None, key: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    return normalized in {messages[key].lower() for messages in MESSAGES.values()}


def _normalize_text(text: str | None) -> str:
    if text is None:
        return ""
    return text.strip().lower()


def _matches_main_menu_item(text: str | None, item_index: int) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    return normalized in {
        messages["main_menu"][item_index].lower() for messages in MESSAGES.values()
    }


def _supported_formats_text() -> str:
    return ", ".join(SUPPORTED_TRANSLATION_FORMATS)


def _supported_formats_lines() -> str:
    return "\n".join(SUPPORTED_TRANSLATION_FORMATS)


def _file_format_label(file_name: str) -> str:
    extension = PurePath(file_name).suffix.lower().lstrip(".")
    return extension.upper() if extension else "unknown"


def _upload_limit_from_error(error: Exception) -> str:
    message = str(error)
    marker = "of "
    if marker in message and message.endswith(" MB"):
        return message.split(marker, 1)[1]
    return "50 MB"
