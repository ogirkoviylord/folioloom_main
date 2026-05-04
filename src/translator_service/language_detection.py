from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DetectedLanguage:
    code: str
    name: str


def detect_language_from_text(text: str) -> DetectedLanguage | None:
    normalized = text.lower()
    letters = re.findall(r"[a-zа-яёіїєґáéíóúüñàâçèêëîïôûùüÿœæ]+", normalized)
    if not letters:
        return None

    joined = " ".join(letters)
    if re.search(r"[іїєґ]", joined):
        return DetectedLanguage(code="uk", name="Ukrainian")

    cyrillic_count = len(re.findall(r"[а-яёіїєґ]", joined))
    latin_count = len(re.findall(r"[a-záéíóúüñàâçèêëîïôûùüÿœæ]", joined))
    if cyrillic_count > latin_count:
        return DetectedLanguage(code="ru", name="Russian")

    scores = {
        "en": _word_score(letters, {"the", "and", "is", "this", "that", "document"}),
        "fr": _word_score(letters, {"le", "la", "les", "des", "est", "avec", "ceci"}),
        "es": _word_score(letters, {"el", "la", "los", "las", "es", "este", "con"}),
    }
    code = max(scores, key=scores.get)
    if scores[code] == 0:
        return None

    names = {"en": "English", "fr": "French", "es": "Spanish"}
    return DetectedLanguage(code=code, name=names[code])


def format_detected_source_language(
    *,
    requested_source_language: str,
    detected_language: DetectedLanguage | None,
) -> str:
    if requested_source_language != "auto":
        return requested_source_language

    if detected_language is None:
        return "auto (unknown)"

    return f"auto ({detected_language.name})"


def _word_score(words: list[str], dictionary: set[str]) -> int:
    return sum(1 for word in words if word in dictionary)
