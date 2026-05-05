from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ProtectedText:
    text: str
    replacements: dict[str, str]


_PROTECTED_PATTERNS = [
    re.compile(r"\u00a0"),
    re.compile(r"\u00ad"),
    re.compile(r" {2,}"),
    re.compile(r"https?://[^\s<>\]\)\"']+"),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"\{\{[^{}\n]+\}\}"),
    re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}"),
    re.compile(r"%[A-Z_][A-Z0-9_]*%"),
    re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}"),
    re.compile(r"</?[A-Za-z][^<>\n]*?>"),
    re.compile(
        r'"[A-Za-z_][A-Za-z0-9_-]*"\s*:\s*'
        r'(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null)'
    ),
    re.compile(r'"[A-Za-z_][A-Za-z0-9_-]*"\s*:\s*"[A-Z][A-Za-z]*(?:[ -][A-Z][A-Za-z]*)*"'),
    re.compile(r'"[A-Za-z_][A-Za-z0-9_-]*"\s*:'),
    re.compile(r':\s*"[A-Z][A-Za-z]*(?:[ -][A-Z][A-Za-z]*)*"'),
    re.compile(r"(?m)^[ \t]*[A-Za-z_][A-Za-z0-9_-]*\s*:"),
    re.compile(r"\b[A-Z][A-Z0-9_]{1,}(?:-[A-Z0-9]+)*\b"),
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
    "endnote",
    "endnotes",
    "footnote",
    "footnotes",
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
) -> ProtectedText:
    matches = _collect_non_overlapping_matches(text, extra_phrases=extra_phrases)
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
    for pattern in _PROTECTED_PATTERNS:
        candidates.extend(pattern.finditer(text))

    candidates.sort(key=lambda match: (match.start(), -(match.end() - match.start())))
    matches: list[re.Match[str]] = []
    occupied_until = -1
    for match in candidates:
        if match.start() < occupied_until:
            continue
        matches.append(match)
        occupied_until = match.end()
    return matches
