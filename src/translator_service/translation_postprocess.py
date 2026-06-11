from __future__ import annotations

import re

_CYRILLIC_TARGET_LANGUAGES = {"ru", "uk"}
_CYRILLIC_RE = r"А-Яа-яЁёІіЇїЄєҐґ"
_GERMAN_ORIENTED_GUILLEMET_PAIR_RE = re.compile(
    r"(^|[\s>(\[{—–-])»([^\s«»][^«»\n]*?)«(?=[\s<.,!?;:)\]}—–-]|$)",
    flags=re.MULTILINE,
)
_RUSSIAN_FRONT_MATTER_LABELS = {
    "title": "Название",
    "author": "Автор",
    "illustrator": "Иллюстратор",
    "language": "Язык",
    "credits": "Подготовка текста",
}
_FRONT_MATTER_LABEL_RE = re.compile(
    r"(?m)^(?P<prefix>\s*)"
    r"(?P<label>Title|Author|Illustrator|Language|Credits)"
    r":(?P<spacing>\s*)"
)


def clean_inline_formatting_artifacts(text: str, *, target_language: str) -> str:
    text = normalize_python_like_code_layout(text)
    if _language_root(target_language) not in _CYRILLIC_TARGET_LANGUAGES:
        return text

    text = normalize_cyrillic_guillemet_orientation(text)
    if _language_root(target_language) == "ru":
        text = localize_russian_front_matter_labels(text)
    cleaned = re.sub(
        rf"\s+(?:subscript|superscript)\s+[A-Za-z]?\d+[A-Za-z]?(?=[{_CYRILLIC_RE}])",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\b([A-Z][A-Za-z]?\d+O)O\b", r"\1", cleaned)


def normalize_cyrillic_guillemet_orientation(text: str) -> str:
    return _GERMAN_ORIENTED_GUILLEMET_PAIR_RE.sub(r"\1«\2»", text)


def localize_russian_front_matter_labels(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        label = _RUSSIAN_FRONT_MATTER_LABELS[match.group("label").lower()]
        return f"{match.group('prefix')}{label}:{match.group('spacing')}"

    return _FRONT_MATTER_LABEL_RE.sub(replace, text)


def _language_root(language_code: str) -> str:
    return language_code.strip().lower().replace("_", "-").split("-", 1)[0]


def normalize_python_like_code_layout(text: str) -> str:
    if not _looks_like_squashed_python_code(text):
        return text

    normalized = re.sub(
        r"(?<!\n)(for\s+[A-Za-z_][A-Za-z0-9_]*\s+in\s+[A-Za-z_][A-Za-z0-9_.]*:)",
        r"\n\1",
        text,
    )
    normalized = re.sub(r"\s{2,}(translated\s*=)", r"\n    \1", normalized)
    normalized = re.sub(r"\s{2,}(assert\s+)", r"\n    \1", normalized)
    normalized = re.sub(r"\s{2,}(print\s*\()", r"\n    \1", normalized)
    return normalized.lstrip("\n")


def _looks_like_squashed_python_code(text: str) -> bool:
    return (
        "for " in text
        and " in " in text
        and ":" in text
        and (
            "translated =" in text
            or "assert " in text
            or "print(" in text
            or "print (" in text
        )
    )
