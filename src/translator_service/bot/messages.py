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
