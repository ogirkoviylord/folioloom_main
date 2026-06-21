from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ProtectedText:
    text: str
    replacements: dict[str, str]


_UPPERCASE_TOKEN_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]{1,}(?:-[A-Z0-9]+)*\b")
_ROMAN_NUMERAL_PATTERN = re.compile(
    r"\b(?=[IVXLCDM]+\b)M{0,4}(?:CM|CD|D?C{0,3})"
    r"(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\b"
)
_LITERARY_ALL_CAPS_WORDS = frozenset(
    {
        "ANOTHER",
        "AND",
        "BOOK",
        "CHAPTER",
        "CONTENTS",
        "EIGHT",
        "EIGHTEEN",
        "ELEVEN",
        "FIFTEEN",
        "FIVE",
        "FOR",
        "FOUR",
        "FOURTEEN",
        "IN",
        "NINE",
        "NINETEEN",
        "OF",
        "ON",
        "ONE",
        "OR",
        "PART",
        "SEVEN",
        "SEVENTEEN",
        "SIX",
        "SIXTEEN",
        "TABLE",
        "TEN",
        "THE",
        "THIRTEEN",
        "THREE",
        "TO",
        "TWELVE",
        "TWENTY",
        "TWO",
        "VOLUME",
        "WITH",
        "WITHOUT",
        "WONDERS",
    }
)
_LITERARY_TECHNICAL_ACRONYMS = frozenset(
    {
        "API",
        "CSS",
        "DOCX",
        "EPUB",
        "HTML",
        "HTTP",
        "HTTPS",
        "ID",
        "ISBN",
        "JSON",
        "NCX",
        "OPF",
        "TXT",
        "URL",
        "XML",
        "XHTML",
    }
)

_PROTECTED_PATTERNS = [
    re.compile(r"\u00a0"),
    re.compile(r"\u00ad"),
    re.compile(r" {2,}"),
    re.compile(r"https?://[^\s<>\]\)\"']*[^\s<>\]\)\"'.,;:!?]"),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"\{\{[^{}\n]+\}\}"),
    re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}"),
    re.compile(r"%[A-Z_][A-Z0-9_]*%"),
    re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}"),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\s*="),
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\([^()\n]*\)"),
    re.compile(r"\b(?:print|return)\s*\([^()\n]*\)"),
    re.compile(r"\bassert\b[^\n;]+"),
    re.compile(r"</?[A-Za-z][^<>\n]*?>"),
    re.compile(
        r'"[A-Za-z_][A-Za-z0-9_-]*"\s*:\s*'
        r'(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)'
    ),
    re.compile(r'"[A-Za-z_][A-Za-z0-9_-]*"\s*:\s*"[A-Z][A-Za-z]*(?:[ -][A-Z][A-Za-z]*)*"'),
    re.compile(r'"[A-Za-z_][A-Za-z0-9_-]*"\s*:'),
    re.compile(r':\s*"[A-Z][A-Za-z]*(?:[ -][A-Z][A-Za-z]*)*"'),
    re.compile(r"(?m)^[ \t]*[A-Za-z_][A-Za-z0-9_-]*\s*:"),
    _UPPERCASE_TOKEN_PATTERN,
    re.compile(r"\b[A-Z]{2,}_[A-Z0-9_]+\b"),
    re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b"),
    re.compile(r"\b(?=[A-Za-z0-9]*\d)(?:[A-Z][a-z]?\d*){2,}\b"),
    re.compile(r"\b[A-Za-z]{1,4}\d+\b"),
    re.compile(r"\b\d+[−-]\d+\b"),
]
_PROTECTED_TERMS = (
    "tracked changes",
    "query-параметры",
    "query parameters",
    "placeholders",
    "placeholder",
    "regex",
    "merge cells",
    "section breaks",
    "inline_code",
)


def protect_text(
    text: str,
    *,
    extra_phrases: tuple[str, ...] = (),
    literary_heading: bool = False,
) -> ProtectedText:
    matches = _collect_non_overlapping_matches(
        text,
        extra_phrases=extra_phrases,
        literary_heading=literary_heading,
    )
    if not matches:
        return ProtectedText(text=text, replacements={})

    replacements: dict[str, str] = {}
    output_parts: list[str] = []
    cursor = 0
    for index, match in enumerate(matches):
        marker = f"ZXQPROTECTED{index}QXZ"
        replacements[marker] = match.group(0)
        output_parts.append(text[cursor : match.start()])
        output_parts.append(marker)
        cursor = match.end()

    output_parts.append(text[cursor:])
    return ProtectedText(text="".join(output_parts), replacements=replacements)


def restore_protected_text(text: str, replacements: dict[str, str]) -> str:
    restored = text
    for marker, original in replacements.items():
        restored = restored.replace(marker, original)
    return restored


def _collect_non_overlapping_matches(
    text: str,
    *,
    extra_phrases: tuple[str, ...],
    literary_heading: bool,
) -> list[re.Match[str]]:
    candidates: list[re.Match[str]] = []
    for phrase in extra_phrases:
        phrase = phrase.strip()
        if not phrase:
            continue
        candidates.extend(re.finditer(re.escape(phrase), text))
    for term in _PROTECTED_TERMS:
        candidates.extend(
            re.finditer(
                rf"(?<![\w-]){re.escape(term)}(?![\w-])",
                text,
                flags=re.IGNORECASE,
            )
        )
    if literary_heading:
        candidates.extend(
            match
            for match in _ROMAN_NUMERAL_PATTERN.finditer(text)
            if match.group(0)
        )
    for pattern in _PROTECTED_PATTERNS:
        for match in pattern.finditer(text):
            if (
                literary_heading
                and pattern is _UPPERCASE_TOKEN_PATTERN
                and _is_literary_all_caps_translatable_word(match.group(0))
            ):
                continue
            candidates.append(match)

    candidates.sort(key=lambda match: (match.start(), -(match.end() - match.start())))
    matches: list[re.Match[str]] = []
    occupied_until = -1
    for match in candidates:
        if match.start() < occupied_until:
            continue
        matches.append(match)
        occupied_until = match.end()
    return matches


def _is_literary_all_caps_translatable_word(text: str) -> bool:
    if text in _LITERARY_TECHNICAL_ACRONYMS:
        return False
    if text in _LITERARY_ALL_CAPS_WORDS:
        return True
    return text.isalpha() and len(text) >= 5
