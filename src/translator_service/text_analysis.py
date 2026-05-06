from dataclasses import dataclass
from enum import Enum
from math import ceil
import re


class TextType(str, Enum):
    GENERAL = "general"
    LITERARY_FICTION = "literary fiction"
    LITERARY_NON_FICTION = "literary non-fiction"
    JOURNALISTIC_PUBLICISTIC = "journalistic/publicistic"
    SCIENTIFIC_ACADEMIC = "scientific/academic"
    TECHNICAL = "technical"
    BUSINESS_LEGAL_LIKE = "business/legal-like"
    EDUCATIONAL = "educational"
    MARKETING = "marketing"
    MIXED_UNKNOWN = "mixed/unknown"


@dataclass(frozen=True)
class TextAnalysis:
    character_count: int
    estimated_input_tokens: int
    fragment_count: int


def estimate_text_volume(text: str, *, max_fragment_chars: int) -> TextAnalysis:
    normalized_text = text.strip()
    character_count = len(normalized_text)

    return TextAnalysis(
        character_count=character_count,
        estimated_input_tokens=ceil(character_count / 4),
        fragment_count=len(
            split_text_into_fragments(
                normalized_text,
                max_fragment_chars=max_fragment_chars,
            )
        ),
    )


def split_text_into_fragments(text: str, *, max_fragment_chars: int) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in text.strip().split("\n\n")]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        return []

    fragments: list[str] = []
    current = paragraphs[0]

    for paragraph in paragraphs[1:]:
        candidate = f"{current}\n\n{paragraph}"
        if len(candidate) <= max_fragment_chars:
            current = candidate
            continue

        fragments.append(current)
        current = paragraph

    fragments.append(current)
    return fragments


def detect_text_type(text: str) -> TextType:
    normalized = f" {text.strip().lower()} "
    if not normalized.strip():
        return TextType.MIXED_UNKNOWN
    if _has_multiple_language_labels(text):
        return TextType.MIXED_UNKNOWN

    scores = {
        TextType.TECHNICAL: _score_terms(
            normalized,
            (
                "api",
                "endpoint",
                "placeholder",
                "token",
                "callback",
                "json",
                "xml",
                "yaml",
                "regex",
                "command",
                "function",
                "handler",
                "package",
                "library",
                "environment variable",
            ),
        )
        + len(re.findall(r"`[^`]+`|\b[a-z_][a-z0-9_]*\([^)]*\)", text)),
        TextType.BUSINESS_LEGAL_LIKE: _score_terms(
            normalized,
            (
                "shall",
                "agreement",
                "contract",
                "invoice",
                "materials",
                "deliver",
                "obligation",
                "party",
                "parties",
                "liability",
                "terms and conditions",
                "inc.",
                "llc",
                "gmbh",
                "b.v.",
            ),
        ),
        TextType.SCIENTIFIC_ACADEMIC: _score_terms(
            normalized,
            (
                "results",
                "suggest",
                "correlation",
                "sample size",
                "conclusion",
                "methodology",
                "hypothesis",
                "statistically",
                "citation",
                "study",
                "data indicate",
            ),
        ),
        TextType.JOURNALISTIC_PUBLICISTIC: _score_terms(
            normalized,
            (
                "officials said",
                "policy",
                "public consultations",
                "according to",
                "reported",
                "minister",
                "government",
                "statement",
                "press",
            ),
        ),
        TextType.LITERARY_FICTION: _score_terms(
            normalized,
            (
                "held its breath",
                "rain",
                "silver lines",
                "window",
                "whispered",
                "room",
                "voice",
                "heart",
                "silence",
            ),
        ),
        TextType.MARKETING: _score_terms(
            normalized,
            (
                "buy",
                "save",
                "limited offer",
                "best",
                "benefits",
                "guarantee",
                "subscribe",
                "customers love",
            ),
        ),
        TextType.EDUCATIONAL: _score_terms(
            normalized,
            (
                "lesson",
                "chapter explains",
                "students",
                "learn",
                "exercise",
                "example",
                "definition",
            ),
        ),
    }
    best_type, best_score = max(scores.items(), key=lambda item: item[1])
    if best_score <= 1:
        return TextType.GENERAL
    return best_type


def _score_terms(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in text)


def _has_multiple_language_labels(text: str) -> bool:
    labels = re.findall(
        r"\b(English|Polski|Nederlands|Russian|Русский|Українська|Ukrainian|French|Spanish|Deutsch|German|中文|日本語|한국어)\s*:",
        text,
        flags=re.IGNORECASE,
    )
    return len(labels) > 1
