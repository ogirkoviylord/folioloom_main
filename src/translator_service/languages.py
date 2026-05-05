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


def find_language_by_button_text(text: str | None) -> LanguageOption | None:
    if text is None:
        return None

    normalized = text.strip().lower()
    for language in SUPPORTED_TARGET_LANGUAGES:
        if language.button_text.lower() == normalized:
            return language

    return None


def language_name_for_code(language_code: str) -> str:
    normalized = language_code.strip().lower()
    if normalized == "auto":
        return "all detected source languages"

    for language in SUPPORTED_TARGET_LANGUAGES:
        if language.code == normalized:
            return language.name

    source_language_names = {
        "pl": "Polish",
        "nl": "Dutch",
        "de": "German",
        "he": "Hebrew",
        "ar": "Arabic",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean",
    }
    return source_language_names.get(normalized, language_code)
