from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class RussianQualityTrack(StrEnum):
    LITERARY = "literary"
    PRECISION = "precision"


@dataclass(frozen=True)
class RussianQualityDecision:
    track: RussianQualityTrack | None
    confidence: float
    reasons: tuple[str, ...]


def detect_russian_quality_track(
    text: str,
    *,
    target_language: str,
) -> RussianQualityDecision:
    if target_language.strip().lower() != "ru":
        return RussianQualityDecision(track=None, confidence=1.0, reasons=())

    precision_score = _score_terms(text, _PRECISION_TERMS)
    precision_score += len(
        re.findall(
            r"https?://|\$\{[^}]+\}|\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b",
            text,
        )
    )
    precision_score += len(
        re.findall(
            r"\b\d+(?:[.,]\d+)?\s*(?:€|\$|%|kg|km|mb|gb|tokens?)\b",
            text,
            flags=re.IGNORECASE,
        )
    )
    precision_score += len(
        re.findall(
            r"\b\d{1,2}\s+"
            r"(?:january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+\d{4}\b",
            text,
            flags=re.IGNORECASE,
        )
    )

    literary_score = _score_terms(text, _LITERARY_TERMS)
    literary_score += len(re.findall(r"[“”\"].+?[“”\"]", text))

    if precision_score >= literary_score and precision_score > 0:
        return RussianQualityDecision(
            track=RussianQualityTrack.PRECISION,
            confidence=min(1.0, 0.55 + precision_score * 0.1),
            reasons=("precision_signals",),
        )
    if literary_score > 0:
        return RussianQualityDecision(
            track=RussianQualityTrack.LITERARY,
            confidence=min(1.0, 0.55 + literary_score * 0.1),
            reasons=("literary_signals",),
        )
    return RussianQualityDecision(
        track=RussianQualityTrack.PRECISION,
        confidence=0.5,
        reasons=("conservative_fallback",),
    )


def russian_quality_track_signature(track: RussianQualityTrack | None) -> str:
    if track is None:
        return "russian-quality:none"
    return f"russian-quality:{track.value}-v1"


def _score_terms(text: str, terms: tuple[str, ...]) -> int:
    normalized = f" {text.lower()} "
    return sum(1 for term in terms if term in normalized)


_PRECISION_TERMS = (
    "api",
    "endpoint",
    "token",
    "placeholder",
    "callback",
    "shall",
    "agreement",
    "contract",
    "invoice",
    "sample size",
    "correlation",
    "results suggest",
    "table",
    "row",
    "column",
    "b.v.",
    "llc",
    "gmbh",
)

_LITERARY_TERMS = (
    "whispered",
    "rain",
    "window",
    "room",
    "voice",
    "heart",
    "silence",
    "breath",
    "dream",
    "shadow",
)
