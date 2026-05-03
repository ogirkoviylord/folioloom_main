from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageOption:
    code: str
    name: str
    button_text: str


SUPPORTED_TARGET_LANGUAGES = [
    LanguageOption(code="ru", name="Russian", button_text="Русский"),
    LanguageOption(code="uk", name="Ukrainian", button_text="Українська"),
    LanguageOption(code="fr", name="French", button_text="Français"),
    LanguageOption(code="es", name="Spanish", button_text="Español"),
    LanguageOption(code="en", name="English", button_text="English"),
]


def find_language_by_button_text(text: str) -> LanguageOption | None:
    normalized = text.strip().lower()
    for language in SUPPORTED_TARGET_LANGUAGES:
        if language.button_text.lower() == normalized:
            return language

    return None

