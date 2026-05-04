from translator_service.job_runner import TranslationJob, TranslationJobStatus
from translator_service.bot_translation_service import PendingTranslation
from translator_service.languages import SUPPORTED_TARGET_LANGUAGES
from translator_service.order_estimates import OrderEstimate


CONFIRM_TRANSLATION_TEXT = "Подтвердить"


MESSAGES = {
    "ru": {
        "main_menu": [
            "Перевести документ",
            "Мои переводы",
            "Баланс",
            "Настройки",
            "Помощь",
        ],
        "start_title": "Сервис перевода документов.",
        "formats": "Поддерживаемые форматы: EPUB, DOCX, PDF, TXT.",
        "main_menu_title": "Главное меню:",
        "interface_language_prompt": "Выберите язык интерфейса:",
        "interface_language_selected": "Язык интерфейса: {language_text}.",
        "translation_language_prompt": "Файл получен: {file_name}\n\nВыберите язык перевода:",
        "original_language": "Язык оригинала",
        "progress": "Прогресс перевода",
        "estimate_title": "Предварительная оценка перевода",
        "document_ready": "Документ готов к переводу",
        "file": "Файл",
        "format": "Формат",
        "characters": "Символов",
        "fragments": "Фрагментов",
        "tokens": "Примерные токены",
        "price": "Цена",
        "direction": "Направление",
        "confirm_instruction": "Нажмите «{confirm_text}», чтобы начать перевод.",
        "queue_instruction": "Нажмите «{confirm_text}», чтобы поставить перевод в очередь.",
        "queued": "Файл {file_name} в очереди на перевод.",
        "translating": "Файл {file_name} переводится.",
        "ready": "Перевод готов: {result_name}.",
        "failed": "Ошибка перевода. Попробуйте еще раз позже.",
        "status": "Статус задачи: {status}",
        "confirm": "Подтвердить",
    },
    "uk": {
        "main_menu": [
            "Перекласти документ",
            "Мої переклади",
            "Баланс",
            "Налаштування",
            "Допомога",
        ],
        "start_title": "Сервіс перекладу документів.",
        "formats": "Підтримувані формати: EPUB, DOCX, PDF, TXT.",
        "main_menu_title": "Головне меню:",
        "interface_language_prompt": "Виберіть мову інтерфейсу:",
        "interface_language_selected": "Мова інтерфейсу: {language_text}.",
        "translation_language_prompt": "Файл отримано: {file_name}\n\nВиберіть мову перекладу:",
        "original_language": "Мова оригіналу",
        "progress": "Прогрес перекладу",
        "estimate_title": "Попередня оцінка перекладу",
        "document_ready": "Документ готовий до перекладу",
        "file": "Файл",
        "format": "Формат",
        "characters": "Символів",
        "fragments": "Фрагментів",
        "tokens": "Орієнтовні токени",
        "price": "Ціна",
        "direction": "Напрямок",
        "confirm_instruction": "Натисніть «{confirm_text}», щоб почати переклад.",
        "queue_instruction": "Натисніть «{confirm_text}», щоб поставити переклад у чергу.",
        "queued": "Файл {file_name} у черзі на переклад.",
        "translating": "Файл {file_name} перекладається.",
        "ready": "Переклад готовий: {result_name}.",
        "failed": "Помилка перекладу. Спробуйте ще раз пізніше.",
        "status": "Статус завдання: {status}",
        "confirm": "Підтвердити",
    },
    "fr": {
        "main_menu": [
            "Traduire un document",
            "Mes traductions",
            "Solde",
            "Paramètres",
            "Aide",
        ],
        "start_title": "Service de traduction de documents.",
        "formats": "Formats pris en charge : EPUB, DOCX, PDF, TXT.",
        "main_menu_title": "Menu principal :",
        "interface_language_prompt": "Choisissez la langue de l’interface :",
        "interface_language_selected": "Langue de l’interface : {language_text}.",
        "translation_language_prompt": "Fichier reçu : {file_name}\n\nChoisissez la langue de traduction :",
        "original_language": "Langue d’origine",
        "progress": "Progression de la traduction",
        "estimate_title": "Estimation de la traduction",
        "document_ready": "Le document est prêt à être traduit",
        "file": "Fichier",
        "format": "Format",
        "characters": "Caractères",
        "fragments": "Fragments",
        "tokens": "Jetons estimés",
        "price": "Prix",
        "direction": "Direction",
        "confirm_instruction": "Appuyez sur « {confirm_text} » pour lancer la traduction.",
        "queue_instruction": "Appuyez sur « {confirm_text} » pour mettre la traduction en file d’attente.",
        "queued": "Le fichier {file_name} est en file d’attente.",
        "translating": "Le fichier {file_name} est en cours de traduction.",
        "ready": "Traduction prête : {result_name}.",
        "failed": "Erreur de traduction. Veuillez réessayer plus tard.",
        "status": "Statut de la tâche : {status}",
        "confirm": "Confirmer",
    },
    "es": {
        "main_menu": [
            "Traducir documento",
            "Mis traducciones",
            "Saldo",
            "Ajustes",
            "Ayuda",
        ],
        "start_title": "Servicio de traducción de documentos.",
        "formats": "Formatos admitidos: EPUB, DOCX, PDF, TXT.",
        "main_menu_title": "Menú principal:",
        "interface_language_prompt": "Elige el idioma de la interfaz:",
        "interface_language_selected": "Idioma de la interfaz: {language_text}.",
        "translation_language_prompt": "Archivo recibido: {file_name}\n\nElige el idioma de traducción:",
        "original_language": "Idioma original",
        "progress": "Progreso de traducción",
        "estimate_title": "Estimación de traducción",
        "document_ready": "El documento está listo para traducirse",
        "file": "Archivo",
        "format": "Formato",
        "characters": "Caracteres",
        "fragments": "Fragmentos",
        "tokens": "Tokens estimados",
        "price": "Precio",
        "direction": "Dirección",
        "confirm_instruction": "Pulsa «{confirm_text}» para iniciar la traducción.",
        "queue_instruction": "Pulsa «{confirm_text}» para poner la traducción en cola.",
        "queued": "El archivo {file_name} está en cola para traducirse.",
        "translating": "El archivo {file_name} se está traduciendo.",
        "ready": "Traducción lista: {result_name}.",
        "failed": "Error de traducción. Inténtalo de nuevo más tarde.",
        "status": "Estado de la tarea: {status}",
        "confirm": "Confirmar",
    },
    "en": {
        "main_menu": [
            "Translate document",
            "My translations",
            "Balance",
            "Settings",
            "Help",
        ],
        "start_title": "Document translation service.",
        "formats": "Supported formats: EPUB, DOCX, PDF, TXT.",
        "main_menu_title": "Main menu:",
        "interface_language_prompt": "Choose interface language:",
        "interface_language_selected": "Interface language: {language_text}.",
        "translation_language_prompt": "File received: {file_name}\n\nChoose translation language:",
        "original_language": "Original language",
        "progress": "Translation progress",
        "estimate_title": "Translation estimate",
        "document_ready": "Document is ready for translation",
        "file": "File",
        "format": "Format",
        "characters": "Characters",
        "fragments": "Fragments",
        "tokens": "Estimated tokens",
        "price": "Price",
        "direction": "Direction",
        "confirm_instruction": "Press “{confirm_text}” to start translation.",
        "queue_instruction": "Press “{confirm_text}” to queue translation.",
        "queued": "File {file_name} is queued for translation.",
        "translating": "File {file_name} is being translated.",
        "ready": "Translation ready: {result_name}.",
        "failed": "Translation error. Please try again later.",
        "status": "Job status: {status}",
        "confirm": "Confirm",
    },
}


def build_main_menu(interface_language: str = "ru") -> list[str]:
    return list(_messages(interface_language)["main_menu"])


def build_start_message(interface_language: str = "ru") -> str:
    messages = _messages(interface_language)
    menu_lines = "\n".join(f"- {item}" for item in build_main_menu(interface_language))
    return (
        f"{messages['start_title']}\n\n"
        f"{messages['formats']}\n\n"
        f"{messages['main_menu_title']}\n{menu_lines}"
    )


def build_language_selection_message(interface_language: str = "ru") -> str:
    language_lines = "\n".join(
        f"- {language.button_text}" for language in SUPPORTED_TARGET_LANGUAGES
    )
    return f"{_messages(interface_language)['interface_language_prompt']}\n{language_lines}"


def build_language_selected_message(
    language_text: str,
    interface_language: str = "ru",
) -> str:
    return _messages(interface_language)["interface_language_selected"].format(
        language_text=language_text
    )


def build_translation_language_selection_message(
    file_name: str,
    interface_language: str = "ru",
    source_language_display: str | None = None,
) -> str:
    messages = _messages(interface_language)
    language_lines = "\n".join(
        f"- {language.button_text}" for language in SUPPORTED_TARGET_LANGUAGES
    )
    source_language_line = (
        f"\n{messages['original_language']}: {source_language_display}\n"
        if source_language_display
        else ""
    )
    return (
        messages["translation_language_prompt"].format(
            file_name=file_name
        )
        + source_language_line
        + f"\n{language_lines}"
    )


def build_order_estimate_message(
    estimate: OrderEstimate,
    interface_language: str = "ru",
) -> str:
    messages = _messages(interface_language)
    confirm_text = get_confirm_translation_text(interface_language)
    return (
        f"{messages['estimate_title']}\n\n"
        f"{messages['file']}: {estimate.file_name}\n"
        f"{messages['format']}: {estimate.document_format.value.upper()}\n"
        f"{messages['characters']}: {estimate.character_count}\n"
        f"{messages['fragments']}: {estimate.fragment_count}\n"
        f"{messages['tokens']}: {estimate.estimated_input_tokens} input, "
        f"{estimate.estimated_output_tokens} output\n"
        f"{messages['price']}: ${estimate.price_usd:.2f}\n\n"
        f"{messages['queue_instruction'].format(confirm_text=confirm_text)}"
    )


def build_pending_translation_message(
    pending: PendingTranslation,
    interface_language: str = "ru",
) -> str:
    messages = _messages(interface_language)
    confirm_text = get_confirm_translation_text(interface_language)
    return (
        f"{messages['document_ready']}\n\n"
        f"{messages['file']}: {pending.file_name}\n"
        f"{messages['direction']}: "
        f"{pending.source_language_display or pending.source_language} → "
        f"{pending.target_language}\n"
        f"{messages['fragments']}: {pending.fragment_count}\n"
        f"{messages['price']}: ${pending.price_usd:.2f}\n\n"
        f"{messages['confirm_instruction'].format(confirm_text=confirm_text)}"
    )


def is_confirm_translation_text(text: str | None) -> bool:
    if text is None:
        return False

    normalized = text.strip().lower()
    localized_confirm_texts = {
        messages["confirm"].lower() for messages in MESSAGES.values()
    }
    return normalized in localized_confirm_texts | {"/confirm"}


def build_translation_progress_message(
    *,
    completed_fragments: int,
    total_fragments: int,
    interface_language: str = "ru",
) -> str:
    messages = _messages(interface_language)
    safe_total = max(total_fragments, 1)
    percent = min(100, round(completed_fragments / safe_total * 100))
    filled_cells = min(10, percent // 10)
    bar = "#" * filled_cells + "-" * (10 - filled_cells)
    return (
        f"{messages['progress']}: [{bar}] "
        f"{completed_fragments}/{total_fragments} ({percent}%)"
    )


def build_translation_job_status_message(
    job: TranslationJob,
    interface_language: str = "ru",
) -> str:
    messages = _messages(interface_language)
    if job.status is TranslationJobStatus.QUEUED:
        return messages["queued"].format(file_name=job.file_name)

    if job.status is TranslationJobStatus.TRANSLATING:
        return messages["translating"].format(file_name=job.file_name)

    if job.status is TranslationJobStatus.READY:
        result_name = job.result_file_name or "результат"
        return messages["ready"].format(result_name=result_name)

    if job.status is TranslationJobStatus.FAILED:
        return messages["failed"]

    return messages["status"].format(status=job.status.value)


def get_confirm_translation_text(interface_language: str = "ru") -> str:
    return _messages(interface_language)["confirm"]


def _messages(interface_language: str) -> dict:
    return MESSAGES.get(interface_language, MESSAGES["ru"])
