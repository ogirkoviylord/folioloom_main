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
    LanguageOption(code="nl", name="Dutch", button_text="Nederlands"),
]

_SOURCE_LANGUAGE_NAMES = {
    "pl": "Polish",
    "nl": "Dutch",
    "de": "German",
    "he": "Hebrew",
    "ar": "Arabic",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}

_LOCALIZED_LANGUAGE_NAMES = {
    "en": {
        "auto": "auto-detect",
        "mixed": "mixed",
        "ru": "Russian",
        "uk": "Ukrainian",
        "fr": "French",
        "es": "Spanish",
        "en": "English",
        "nl": "Dutch",
        "pl": "Polish",
        "de": "German",
        "he": "Hebrew",
        "ar": "Arabic",
        "zh": "Chinese",
        "ja": "Japanese",
        "ko": "Korean",
    },
    "ru": {
        "auto": "автоопределение",
        "mixed": "смешанный текст",
        "ru": "Русский",
        "uk": "Украинский",
        "fr": "Французский",
        "es": "Испанский",
        "en": "Английский",
        "nl": "Нидерландский",
        "pl": "Польский",
        "de": "Немецкий",
        "he": "Иврит",
        "ar": "Арабский",
        "zh": "Китайский",
        "ja": "Японский",
        "ko": "Корейский",
    },
    "uk": {
        "auto": "автовизначення",
        "mixed": "змішаний текст",
        "ru": "Російська",
        "uk": "Українська",
        "fr": "Французька",
        "es": "Іспанська",
        "en": "Англійська",
        "nl": "Нідерландська",
        "pl": "Польська",
        "de": "Німецька",
        "he": "Іврит",
        "ar": "Арабська",
        "zh": "Китайська",
        "ja": "Японська",
        "ko": "Корейська",
    },
    "fr": {
        "auto": "détection automatique",
        "mixed": "texte mixte",
        "ru": "Russe",
        "uk": "Ukrainien",
        "fr": "Français",
        "es": "Espagnol",
        "en": "Anglais",
        "nl": "Néerlandais",
        "pl": "Polonais",
        "de": "Allemand",
        "he": "Hébreu",
        "ar": "Arabe",
        "zh": "Chinois",
        "ja": "Japonais",
        "ko": "Coréen",
    },
    "es": {
        "auto": "detección automática",
        "mixed": "texto mixto",
        "ru": "Ruso",
        "uk": "Ucraniano",
        "fr": "Francés",
        "es": "Español",
        "en": "Inglés",
        "nl": "Neerlandés",
        "pl": "Polaco",
        "de": "Alemán",
        "he": "Hebreo",
        "ar": "Árabe",
        "zh": "Chino",
        "ja": "Japonés",
        "ko": "Coreano",
    },
    "nl": {
        "auto": "automatische detectie",
        "mixed": "gemengde tekst",
        "ru": "Russisch",
        "uk": "Oekraïens",
        "fr": "Frans",
        "es": "Spaans",
        "en": "Engels",
        "nl": "Nederlands",
        "pl": "Pools",
        "de": "Duits",
        "he": "Hebreeuws",
        "ar": "Arabisch",
        "zh": "Chinees",
        "ja": "Japans",
        "ko": "Koreaans",
    },
}


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

    return _SOURCE_LANGUAGE_NAMES.get(normalized, language_code)


def localized_language_name_for_code(
    language_code: str,
    interface_language: str = "en",
) -> str:
    normalized = language_code.strip().lower()
    names = _LOCALIZED_LANGUAGE_NAMES.get(
        interface_language.strip().lower(),
        _LOCALIZED_LANGUAGE_NAMES["en"],
    )
    return names.get(normalized, language_name_for_code(normalized))


def language_code_for_name(language_name: str) -> str | None:
    normalized = language_name.strip().lower()
    for language in SUPPORTED_TARGET_LANGUAGES:
        if language.name.lower() == normalized or language.button_text.lower() == normalized:
            return language.code
    for code, name in _SOURCE_LANGUAGE_NAMES.items():
        if name.lower() == normalized:
            return code
    return None
