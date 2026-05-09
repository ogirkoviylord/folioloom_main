from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class TranslationMetricScore:
    name: str
    version: str
    score: float


def score_meteor_core(candidate: str, reference: str) -> TranslationMetricScore:
    candidate_tokens = _word_tokens(candidate)
    reference_tokens = _word_tokens(reference)
    score = _meteor_core_score(candidate_tokens, reference_tokens)
    return TranslationMetricScore(
        name="meteor_core",
        version="meteor-core-v1",
        score=score,
    )


def score_chrf(candidate: str, reference: str) -> TranslationMetricScore:
    score = _chrf_score(candidate, reference)
    return TranslationMetricScore(name="chrf", version="chrf-v1", score=score)


def score_reference_translation(
    *,
    candidate: str,
    reference: str,
) -> tuple[TranslationMetricScore, ...]:
    return (
        score_meteor_core(candidate, reference),
        score_chrf(candidate, reference),
    )


_WORD_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)?", flags=re.UNICODE)


def _word_tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _WORD_RE.finditer(text))


def _meteor_core_score(
    candidate_tokens: tuple[str, ...],
    reference_tokens: tuple[str, ...],
) -> float:
    if not candidate_tokens or not reference_tokens:
        return 0.0
    if candidate_tokens == reference_tokens:
        return 1.0

    matches = _aligned_exact_matches(candidate_tokens, reference_tokens)
    match_count = len(matches)
    if match_count == 0:
        return 0.0

    precision = match_count / len(candidate_tokens)
    recall = match_count / len(reference_tokens)
    f_mean = (10 * precision * recall) / (recall + 9 * precision)
    chunks = _contiguous_chunk_count(matches)
    penalty = 0.5 * (chunks / match_count) ** 3
    return round(max(0.0, min(1.0, f_mean * (1 - penalty))), 4)


def _aligned_exact_matches(
    candidate_tokens: tuple[str, ...],
    reference_tokens: tuple[str, ...],
) -> tuple[tuple[int, int], ...]:
    used_reference_indexes: set[int] = set()
    matches: list[tuple[int, int]] = []
    for candidate_index, token in enumerate(candidate_tokens):
        for reference_index, reference_token in enumerate(reference_tokens):
            if reference_index in used_reference_indexes:
                continue
            if token != reference_token:
                continue
            used_reference_indexes.add(reference_index)
            matches.append((candidate_index, reference_index))
            break
    return tuple(matches)


def _contiguous_chunk_count(matches: tuple[tuple[int, int], ...]) -> int:
    if not matches:
        return 0
    chunks = 1
    previous_candidate, previous_reference = matches[0]
    for candidate_index, reference_index in matches[1:]:
        if (
            candidate_index != previous_candidate + 1
            or reference_index != previous_reference + 1
        ):
            chunks += 1
        previous_candidate = candidate_index
        previous_reference = reference_index
    return chunks


def _chrf_score(candidate: str, reference: str) -> float:
    candidate_text = _normalize_character_text(candidate)
    reference_text = _normalize_character_text(reference)
    if not candidate_text or not reference_text:
        return 0.0
    if candidate_text == reference_text:
        return 1.0

    precisions: list[float] = []
    recalls: list[float] = []
    for ngram_size in range(1, 7):
        candidate_ngrams = _character_ngrams(candidate_text, ngram_size)
        reference_ngrams = _character_ngrams(reference_text, ngram_size)
        if not candidate_ngrams or not reference_ngrams:
            continue
        overlap = sum((candidate_ngrams & reference_ngrams).values())
        precisions.append(overlap / sum(candidate_ngrams.values()))
        recalls.append(overlap / sum(reference_ngrams.values()))

    if not precisions or not recalls:
        return 0.0
    precision = sum(precisions) / len(precisions)
    recall = sum(recalls) / len(recalls)
    if precision == 0.0 and recall == 0.0:
        return 0.0
    beta_squared = 4
    score = (
        (1 + beta_squared)
        * precision
        * recall
        / (beta_squared * precision + recall)
    )
    return round(max(0.0, min(1.0, score)), 4)


def _normalize_character_text(text: str) -> str:
    return " ".join(text.casefold().split())


def _character_ngrams(text: str, size: int) -> Counter[str]:
    if len(text) < size:
        return Counter()
    return Counter(text[index : index + size] for index in range(len(text) - size + 1))
