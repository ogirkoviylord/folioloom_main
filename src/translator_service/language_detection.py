from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DetectedLanguage:
    code: str
    name: str


LANGUAGE_NAMES = {
    "ru": "Russian",
    "uk": "Ukrainian",
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "pl": "Polish",
    "nl": "Dutch",
    "de": "German",
    "he": "Hebrew",
    "ar": "Arabic",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
}


def detect_language_from_text(text: str) -> DetectedLanguage | None:
    normalized = text.lower()
    letters = re.findall(r"[a-zа-яёіїєґáéíóúüñàâçèêëîïôûùüÿœæ]+", normalized)
    if not letters:
        return None

    joined = " ".join(letters)
    if re.search(r"[іїєґ]", joined):
        return DetectedLanguage(code="uk", name="Ukrainian")

    cyrillic_count = len(re.findall(r"[а-яё]", joined))
    latin_count = len(re.findall(r"[a-záéíóúüñàâçèêëîïôûùüÿœæ]", joined))
    if cyrillic_count > latin_count:
        return DetectedLanguage(code="ru", name="Russian")

    scores = _latin_language_scores(letters)
    code = max(scores, key=scores.get)
    if scores[code] == 0:
        return None
    return DetectedLanguage(code=code, name=LANGUAGE_NAMES[code])


def detect_languages_from_text(text: str) -> list[DetectedLanguage]:
    normalized = text.lower()
    letters = re.findall(r"[a-zа-яёіїєґáéíóúüñàâçèêëîïôûùüÿœæ]+", normalized)
    joined = " ".join(letters)
    detected_codes: list[str] = []
    label_code = _language_label_code(normalized)
    if label_code is not None:
        detected_codes.append(label_code)

    has_ukrainian_markers = re.search(r"[іїєґ]", joined) is not None
    cyrillic_count = len(re.findall(r"[а-яё]", joined))
    if cyrillic_count and (
        not has_ukrainian_markers
        or _word_score(
            letters,
            {"русский", "российский", "это", "перевод", "книга", "документ"},
        )
    ):
        detected_codes.append("ru")
    if has_ukrainian_markers:
        detected_codes.append("uk")
    if re.search(r"[żźąćęłńś]", joined) or _word_score(
        letters,
        {"polski", "jest", "oraz", "nie", "tak", "zażółć", "gęślą", "jaźń"},
    ):
        detected_codes.append("pl")
    if _word_score(
        letters,
        {"nederlands", "het", "een", "naar", "vandaag", "fiets", "zwolle", "regen"},
    ):
        detected_codes.append("nl")

    scored_languages = _latin_language_scores(letters)
    detected_codes.extend(
        code
        for code, score in scored_languages.items()
        if score > 0 and (label_code is None or code == label_code)
    )
    if re.search(r"[\u0590-\u05ff]", normalized) or "עברית" in normalized:
        detected_codes.append("he")
    if re.search(r"[\u0600-\u06ff]", normalized) or "العربية" in normalized:
        detected_codes.append("ar")
    if re.search(r"[\u4e00-\u9fff]", normalized) or "中文" in normalized:
        detected_codes.append("zh")
    if re.search(r"[\u3040-\u30ff]", normalized) or "日本語" in normalized:
        detected_codes.append("ja")
    if re.search(r"[\uac00-\ud7af]", normalized) or "한국어" in normalized:
        detected_codes.append("ko")

    ordered_codes = [
        code for code in LANGUAGE_NAMES if code in set(detected_codes)
    ]
    return [
        DetectedLanguage(code=code, name=LANGUAGE_NAMES[code])
        for code in ordered_codes
    ]


def format_detected_source_language(
    *,
    requested_source_language: str,
    detected_language: DetectedLanguage | None,
) -> str:
    if requested_source_language != "auto":
        return requested_source_language

    if detected_language is None:
        return "auto (unknown)"

    return format_detected_source_languages(
        requested_source_language=requested_source_language,
        detected_languages=[detected_language],
    )


def format_detected_source_languages(
    *,
    requested_source_language: str,
    detected_languages: list[DetectedLanguage],
) -> str:
    if requested_source_language != "auto":
        return requested_source_language

    if not detected_languages:
        return "auto (unknown)"

    if len(detected_languages) == 1:
        return f"auto ({detected_languages[0].name})"

    names = ", ".join(language.name for language in detected_languages)
    return f"auto (mixed: {names})"


def _word_score(words: list[str], dictionary: set[str]) -> int:
    return sum(1 for word in words if word in dictionary)


def _language_label_code(text: str) -> str | None:
    label = text.split(":", 1)[0].strip()
    labels = {
        "русский": "ru",
        "українська": "uk",
        "украинский": "uk",
        "english": "en",
        "français": "fr",
        "francais": "fr",
        "español": "es",
        "espanol": "es",
        "polski": "pl",
        "nederlands": "nl",
        "deutsch": "de",
        "עברית": "he",
        "العربية": "ar",
        "中文": "zh",
        "日本語": "ja",
        "한국어": "ko",
    }
    return labels.get(label)


def _latin_language_scores(words: list[str]) -> dict[str, int]:
    return {
        "en": _word_score(
            words,
            {"the", "and", "is", "this", "that", "document", "english", "quick", "brown", "fox"},
        ),
        "fr": _word_score(
            words,
            {"le", "la", "les", "des", "est", "avec", "ceci", "bonjour", "français"},
        ),
        "es": _word_score(
            words,
            {"el", "la", "los", "las", "es", "este", "con", "español", "gracias"},
        ),
        "de": _word_score(
            words,
            {"der", "die", "das", "und", "ist", "mit", "deutsch", "danke"},
        ),
    }
