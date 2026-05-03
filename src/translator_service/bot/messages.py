from translator_service.order_estimates import OrderEstimate


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
        "Нажмите «Подтвердить», чтобы поставить перевод в очередь."
    )
