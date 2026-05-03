from translator_service.job_runner import TranslationJob, TranslationJobStatus
from translator_service.bot_translation_service import PendingTranslation
from translator_service.order_estimates import OrderEstimate


CONFIRM_TRANSLATION_TEXT = "Подтвердить"


def build_main_menu() -> list[str]:
    return [
        "Перевести документ",
        "Мои переводы",
        "Баланс",
        "Настройки",
        "Помощь",
    ]


def build_start_message() -> str:
    menu_lines = "\n".join(f"- {item}" for item in build_main_menu())
    return (
        "Сервис перевода документов через DeepSeek.\n\n"
        "Поддерживаемые форматы: EPUB, DOCX, PDF, TXT.\n\n"
        f"Главное меню:\n{menu_lines}"
    )


def build_order_estimate_message(estimate: OrderEstimate) -> str:
    return (
        "Предварительная оценка перевода\n\n"
        f"Файл: {estimate.file_name}\n"
        f"Формат: {estimate.document_format.value.upper()}\n"
        f"Символов: {estimate.character_count}\n"
        f"Фрагментов: {estimate.fragment_count}\n"
        f"Примерные токены: {estimate.estimated_input_tokens} input, "
        f"{estimate.estimated_output_tokens} output\n"
        f"Цена: ${estimate.price_usd:.2f}\n\n"
        f"Нажмите «{CONFIRM_TRANSLATION_TEXT}», чтобы поставить перевод в очередь."
    )


def build_pending_translation_message(pending: PendingTranslation) -> str:
    return (
        "Документ готов к переводу\n\n"
        f"Файл: {pending.file_name}\n"
        f"Направление: {pending.source_language} → {pending.target_language}\n"
        f"Фрагментов: {pending.fragment_count}\n"
        f"Цена: ${pending.price_usd:.2f}\n\n"
        f"Нажмите «{CONFIRM_TRANSLATION_TEXT}», чтобы начать перевод."
    )


def is_confirm_translation_text(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {CONFIRM_TRANSLATION_TEXT.lower(), "/confirm"}


def build_translation_job_status_message(job: TranslationJob) -> str:
    if job.status is TranslationJobStatus.QUEUED:
        return f"Файл {job.file_name} в очереди на перевод."

    if job.status is TranslationJobStatus.TRANSLATING:
        return f"Файл {job.file_name} переводится."

    if job.status is TranslationJobStatus.READY:
        result_name = job.result_file_name or "результат"
        return f"Перевод готов: {result_name}."

    if job.status is TranslationJobStatus.FAILED:
        error = job.error_message or "неизвестная ошибка"
        return f"Ошибка перевода: {error}"

    return f"Статус задачи: {job.status.value}"
