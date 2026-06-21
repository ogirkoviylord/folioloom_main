from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

PREPARED_GLOSSARY_CANDIDATE_QUALITY_POLICY_VERSION = (
    "prepared-glossary-candidate-quality-v1"
)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’]*")
_PRONOUN_TOKENS = frozenset(
    {
        "he",
        "her",
        "hers",
        "herself",
        "him",
        "himself",
        "his",
        "i",
        "it",
        "its",
        "itself",
        "me",
        "mine",
        "my",
        "our",
        "ours",
        "ourselves",
        "she",
        "their",
        "theirs",
        "them",
        "themselves",
        "they",
        "us",
        "we",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
    }
)
_DETERMINER_TOKENS = frozenset(
    {
        "a",
        "all",
        "an",
        "another",
        "any",
        "each",
        "every",
        "many",
        "much",
        "no",
        "some",
        "that",
        "the",
        "these",
        "this",
        "those",
    }
)
_FUNCTION_TOKENS = frozenset(
    {
        "about",
        "above",
        "after",
        "again",
        "against",
        "along",
        "although",
        "and",
        "as",
        "at",
        "be",
        "being",
        "because",
        "before",
        "been",
        "between",
        "but",
        "by",
        "down",
        "for",
        "from",
        "if",
        "in",
        "into",
        "nor",
        "now",
        "of",
        "off",
        "on",
        "or",
        "over",
        "so",
        "than",
        "then",
        "though",
        "through",
        "to",
        "under",
        "until",
        "up",
        "was",
        "were",
        "when",
        "while",
        "with",
        "yet",
    }
)
_BOILERPLATE_TOKENS = frozenset(
    {
        "book",
        "chapter",
        "contents",
        "dedication",
        "epilogue",
        "part",
        "preface",
        "prologue",
        "section",
        "volume",
    }
)
_HONORIFIC_TOKENS = frozenset(
    {
        "dr",
        "lady",
        "lord",
        "miss",
        "mr",
        "mrs",
        "ms",
        "prof",
        "professor",
        "sir",
    }
)
_COMMON_INVOCATION_TOKENS = frozenset({"god", "lord"})
_COMMON_INVOCATION_PREFIX_TOKENS = frozenset({"dear", "good", "oh"})
_SAFE_STRUCTURAL_VOCATIVE_PREFIX_TOKENS = frozenset({"oh"})
_BROAD_PERSON_ALIAS_TOKENS = frozenset(
    {
        "alice",
        "elizabeth",
        "henry",
        "jane",
        "john",
        "mary",
        "william",
    }
)
_LOW_VALUE_GENERIC_NOUN_TOKENS = frozenset(
    {
        "kind",
        "moment",
        "people",
        "thing",
        "things",
    }
)
_LOW_VALUE_ALIAS_TOKENS = (
    _PRONOUN_TOKENS
    | _DETERMINER_TOKENS
    | _FUNCTION_TOKENS
    | _BOILERPLATE_TOKENS
    | _HONORIFIC_TOKENS
    | _LOW_VALUE_GENERIC_NOUN_TOKENS
)
_LOW_VALUE_REPEATED_TERM_START_TOKENS = frozenset(
    {
        "came",
        "cannot",
        "found",
        "grew",
        "looked",
        "must",
        "once",
        "thought",
        "went",
    }
)
_LOW_VALUE_REPEATED_TERM_END_TOKENS = frozenset(
    {
        "back",
        "been",
        "down",
        "myself",
        "round",
        "since",
        "upon",
    }
)
@dataclass(frozen=True)
class PreparedGlossaryCandidateQualityDecision:
    entry_id: str
    status: str
    reason_codes: tuple[str, ...]
    alias_omitted_count: int
    source_digest: str
    source_char_count: int


@dataclass(frozen=True)
class PreparedGlossaryCandidateQualityResult:
    entries: tuple[Any, ...]
    decisions: tuple[PreparedGlossaryCandidateQualityDecision, ...]
    selector_signature: str

    @property
    def metadata(self) -> dict[str, Any]:
        reason_codes: list[str] = []
        dropped_count = 0
        omitted_count = 0
        alias_omitted_count = 0
        for decision in self.decisions:
            if decision.status == "dropped":
                dropped_count += 1
            if decision.status == "omitted":
                omitted_count += 1
            alias_omitted_count += decision.alias_omitted_count
            reason_codes.extend(decision.reason_codes)
        return {
            "policy_version": PREPARED_GLOSSARY_CANDIDATE_QUALITY_POLICY_VERSION,
            "metadata_only": True,
            "raw_payload_included": False,
            "input_candidate_count": len(self.decisions),
            "selected_candidate_count": len(self.entries),
            "dropped_candidate_count": dropped_count,
            "omitted_candidate_count": omitted_count,
            "alias_omitted_count": alias_omitted_count,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "selector_signature": self.selector_signature,
        }


def filter_prepared_glossary_candidates(
    entries: Sequence[Any],
    *,
    upstream_selector_signature: str,
    source_language: str = "Unknown",
    max_selected_candidates: int | None = None,
) -> PreparedGlossaryCandidateQualityResult:
    """Filter prepared-glossary prep candidates before provider boundaries.

    The policy is deliberately local and metadata-only. It rejects obvious
    function-word/pronoun/common-phrase candidates without claiming semantic
    truth about names or terms.
    """

    accepted: list[Any] = []
    decisions: list[PreparedGlossaryCandidateQualityDecision] = []
    for entry in entries:
        source_canonical = _entry_source(entry)
        reason_codes = _source_reason_codes(source_canonical)
        pruned_aliases, alias_reason_codes = _pruned_aliases(
            _entry_aliases(entry),
            source_canonical=source_canonical,
        )
        alias_omitted_count = len(_entry_aliases(entry)) - len(pruned_aliases)
        if reason_codes:
            decisions.append(
                _decision(
                    entry,
                    status="dropped",
                    reason_codes=(*reason_codes, *alias_reason_codes),
                    alias_omitted_count=alias_omitted_count,
                )
            )
            continue
        if (
            max_selected_candidates is not None
            and len(accepted) >= max(0, max_selected_candidates)
        ):
            decisions.append(
                _decision(
                    entry,
                    status="omitted",
                    reason_codes=(
                        "candidate_quality_selection_cap_exhausted",
                        *alias_reason_codes,
                    ),
                    alias_omitted_count=alias_omitted_count,
                )
            )
            continue
        accepted.append(_replace_aliases(entry, pruned_aliases))
        decisions.append(
            _decision(
                entry,
                status="accepted",
                reason_codes=alias_reason_codes,
                alias_omitted_count=alias_omitted_count,
            )
        )
    selector_signature = _selector_signature(
        upstream_selector_signature=upstream_selector_signature,
        source_language=source_language,
        decisions=tuple(decisions),
        entries=tuple(accepted),
    )
    return PreparedGlossaryCandidateQualityResult(
        entries=tuple(accepted),
        decisions=tuple(decisions),
        selector_signature=selector_signature,
    )


def _source_reason_codes(source: str) -> tuple[str, ...]:
    tokens = _tokens(source)
    if not tokens:
        return ("candidate_quality_empty_source",)
    first_token = tokens[0]
    last_token = tokens[-1]
    reasons: list[str] = []
    if _is_boilerplate_phrase(tokens):
        reasons.append("candidate_quality_boilerplate_source")
    if all(token in _LOW_VALUE_ALIAS_TOKENS for token in tokens):
        reasons.append("candidate_quality_low_value_source")
    if (
        len(tokens) <= 2
        and any(token in _PRONOUN_TOKENS for token in tokens)
        and not _has_honorific_name_shape(tokens)
    ):
        reasons.append("candidate_quality_pronoun_phrase")
    if (
        len(tokens) <= 2
        and (first_token in _FUNCTION_TOKENS or last_token in _FUNCTION_TOKENS)
        and not _has_honorific_name_shape(tokens)
    ):
        reasons.append("candidate_quality_function_word_phrase")
    if (
        len(tokens) <= 3
        and first_token
        in (
            _FUNCTION_TOKENS
            | _DETERMINER_TOKENS
            | _PRONOUN_TOKENS
            | _COMMON_INVOCATION_PREFIX_TOKENS
        )
        and any(token in _COMMON_INVOCATION_TOKENS for token in tokens[1:])
    ):
        reasons.append("candidate_quality_common_phrase")
    if _is_low_value_repeated_term_phrase(tokens):
        reasons.append("candidate_quality_low_value_repeated_term_phrase")
    if _is_terminal_possessive_source(source):
        reasons.append("candidate_quality_possessive_source")
    if _is_corrupted_possessive_source(source):
        reasons.append("candidate_quality_corrupted_possessive_source")
    if _is_safe_structural_vocative_phrase(tokens):
        reasons.append("candidate_quality_vocative_phrase")
    return tuple(dict.fromkeys(reasons))


def _pruned_aliases(
    aliases: tuple[str, ...],
    *,
    source_canonical: str = "",
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    pruned: list[str] = []
    reason_codes: list[str] = []
    seen: set[str] = set()
    source_tokens = _tokens(source_canonical)
    for alias in aliases:
        tokens = _tokens(alias)
        alias_reasons: list[str] = []
        if not tokens:
            alias_reasons.append("candidate_quality_alias_empty")
        if tokens and all(token in _LOW_VALUE_ALIAS_TOKENS for token in tokens):
            alias_reasons.append("candidate_quality_low_value_alias")
        if len(tokens) == 1 and len(tokens[0]) <= 2:
            alias_reasons.append("candidate_quality_short_alias")
        alias_reasons.extend(_source_reason_codes(alias))
        if _is_broad_canonical_component_alias(tokens, source_tokens):
            alias_reasons.append("candidate_quality_broad_alias_pruned")
        if alias_reasons:
            reason_codes.append("candidate_quality_alias_pruned")
            reason_codes.extend(alias_reasons)
            continue
        key = " ".join(tokens)
        if key in seen:
            continue
        seen.add(key)
        pruned.append(alias)
    return tuple(pruned), tuple(dict.fromkeys(reason_codes))


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(match.group(0).casefold() for match in _TOKEN_RE.finditer(text))


def _is_boilerplate_phrase(tokens: tuple[str, ...]) -> bool:
    if tokens[0] in _BOILERPLATE_TOKENS:
        return True
    return all(_is_roman_numeral(token) for token in tokens)


def _is_roman_numeral(token: str) -> bool:
    return bool(re.fullmatch(r"[ivxlcdm]+", token))


def _has_honorific_name_shape(tokens: tuple[str, ...]) -> bool:
    return len(tokens) >= 2 and tokens[0] in _HONORIFIC_TOKENS


def _is_low_value_repeated_term_phrase(tokens: tuple[str, ...]) -> bool:
    if len(tokens) != 2:
        return False
    left, right = tokens
    if left == right:
        return True
    if (
        left in _LOW_VALUE_REPEATED_TERM_START_TOKENS
        or right in _LOW_VALUE_REPEATED_TERM_END_TOKENS
    ):
        return True
    return (
        left in (_DETERMINER_TOKENS | _PRONOUN_TOKENS)
        or right in _LOW_VALUE_GENERIC_NOUN_TOKENS
    ) and any(token in _LOW_VALUE_GENERIC_NOUN_TOKENS for token in tokens)


def _is_terminal_possessive_source(source: str) -> bool:
    stripped = source.strip().rstrip(".")
    return bool(
        len(_tokens(stripped)) > 1
        and re.search(r"[A-Za-z][A-Za-z0-9]*['’]s$", stripped)
    )


def _is_corrupted_possessive_source(source: str) -> bool:
    stripped = source.strip().rstrip(".")
    return bool(re.search(r"\b[A-Z][A-Za-z0-9]+\s+s$", stripped))


def _is_safe_structural_vocative_phrase(tokens: tuple[str, ...]) -> bool:
    return (
        2 <= len(tokens) <= 3
        and tokens[0] in _SAFE_STRUCTURAL_VOCATIVE_PREFIX_TOKENS
        and (
            tokens[1] in _BROAD_PERSON_ALIAS_TOKENS
            or tokens[1] in _HONORIFIC_TOKENS
        )
    )


def _is_broad_canonical_component_alias(
    alias_tokens: tuple[str, ...],
    source_tokens: tuple[str, ...],
) -> bool:
    if len(alias_tokens) != 1 or len(source_tokens) <= 1:
        return False
    if source_tokens[0] in _HONORIFIC_TOKENS:
        return False
    alias_token = alias_tokens[0]
    return alias_token == source_tokens[0] and alias_token in _BROAD_PERSON_ALIAS_TOKENS


def _entry_source(entry: Any) -> str:
    return str(getattr(entry, "source_canonical", "") or "")


def _entry_aliases(entry: Any) -> tuple[str, ...]:
    aliases = getattr(entry, "aliases", ())
    return tuple(str(alias) for alias in aliases if isinstance(alias, str))


def _replace_aliases(entry: Any, aliases: tuple[str, ...]) -> Any:
    try:
        return replace(entry, aliases=aliases)
    except (TypeError, ValueError):
        return entry


def _decision(
    entry: Any,
    *,
    status: str,
    reason_codes: Sequence[str],
    alias_omitted_count: int,
) -> PreparedGlossaryCandidateQualityDecision:
    source = _entry_source(entry)
    return PreparedGlossaryCandidateQualityDecision(
        entry_id=_entry_id(entry),
        status=status,
        reason_codes=tuple(dict.fromkeys(str(code) for code in reason_codes)),
        alias_omitted_count=alias_omitted_count,
        source_digest=hashlib.sha256(source.casefold().encode("utf-8")).hexdigest()[
            :16
        ],
        source_char_count=len(source),
    )


def _selector_signature(
    *,
    upstream_selector_signature: str,
    source_language: str,
    decisions: tuple[PreparedGlossaryCandidateQualityDecision, ...],
    entries: tuple[Any, ...],
) -> str:
    payload = {
        "policy_version": PREPARED_GLOSSARY_CANDIDATE_QUALITY_POLICY_VERSION,
        "source_language": source_language or "Unknown",
        "upstream_selector_signature": upstream_selector_signature,
        "accepted_entry_ids": [_entry_id(entry) for entry in entries],
        "decisions": [
            {
                "entry_id": decision.entry_id,
                "status": decision.status,
                "reason_codes": list(decision.reason_codes),
                "alias_omitted_count": decision.alias_omitted_count,
                "source_digest": decision.source_digest,
                "source_char_count": decision.source_char_count,
            }
            for decision in decisions
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"prepared-glossary-candidate-quality:v1:{digest}"


def _entry_id(entry: Any) -> str:
    identifier = getattr(entry, "entry_id", None)
    if identifier is None:
        identifier = getattr(entry, "source_entry_id", None)
    return str(identifier or "Unknown")
