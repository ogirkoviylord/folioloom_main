from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourcePairProfile:
    source_language: str
    target_language: str
    version: str
    prompt: str


def build_source_pair_profile_prompt(
    source_language: str,
    target_language: str,
) -> str:
    profile = _profile_for_pair(source_language, target_language)
    if profile is None:
        return ""
    return profile.prompt


def source_pair_profile_signature(
    source_language: str,
    target_language: str,
) -> str:
    profile = _profile_for_pair(source_language, target_language)
    if profile is None:
        return "source-pair:none"
    return f"source-pair:{profile.source_language}-{profile.target_language}:{profile.version}"


def _profile_for_pair(
    source_language: str,
    target_language: str,
) -> SourcePairProfile | None:
    normalized_target = _language_root(target_language)
    normalized_source = _language_root(source_language)
    return _SOURCE_PAIR_PROFILES.get(
        (normalized_source, normalized_target),
        _SOURCE_PAIR_PROFILES.get(("auto", normalized_target)),
    )


def _language_root(language_code: str) -> str:
    return language_code.strip().lower().replace("_", "-").split("-", 1)[0]


_SOURCE_PAIR_PROFILES = {
    ("en", "ru"): SourcePairProfile(
        source_language="en",
        target_language="ru",
        version="v1",
        prompt=(
            "Source-pair policy: English to Russian source-pair profile. "
            "Translate meaning into idiomatic Russian; avoid English word order, "
            "mechanical possessives, articles carried into Russian phrasing, and "
            "literal phrasal verbs. "
            "Resolve English false friends by context, including actual, accurate, "
            "eventually, control, public, regular, and data. "
            "Use Russian sentence-style capitalization unless a title, brand, or "
            "official name requires the source form."
        ),
    ),
    ("uk", "ru"): SourcePairProfile(
        source_language="uk",
        target_language="ru",
        version="v1",
        prompt=(
            "Source-pair policy: Ukrainian to Russian source-pair profile. "
            "Translate close Slavic wording into natural Russian without Ukrainian "
            "syntax calques or false friends. Do not transliterate Ukrainian words "
            "as a substitute for translation; translate words containing і, ї, є, ґ "
            "unless they are names, citations, usernames, addresses, or protected text. "
            "Preserve tone and document register without over-formalizing shared phrasing."
        ),
    ),
    ("pl", "ru"): SourcePairProfile(
        source_language="pl",
        target_language="ru",
        version="v1",
        prompt=(
            "Source-pair policy: Polish to Russian source-pair profile. "
            "Translate Polish meaning rather than transliterating Polish diacritics. "
            "Watch false friends and administrative/legal terms; preserve exact legal "
            "names and addresses. Treat pan/pani and forms of address by Russian "
            "register. Recognize pangrams and orthographic samples as letter tests."
        ),
    ),
    ("nl", "ru"): SourcePairProfile(
        source_language="nl",
        target_language="ru",
        version="v1",
        prompt=(
            "Source-pair policy: Dutch to Russian source-pair profile. "
            "Resolve separable verbs, split Dutch compounds by meaning, and avoid "
            "Germanic noun-stacking in Russian. Preserve legal suffixes such as B.V. "
            "inside company names. Translate afspraak by context, not as a fixed loanword; "
            "use established Russian place names such as Нидерланды where appropriate."
        ),
    ),
    ("de", "ru"): SourcePairProfile(
        source_language="de",
        target_language="ru",
        version="v1",
        prompt=(
            "Source-pair policy: German to Russian source-pair profile. "
            "Break compound nouns and nominal chains into readable Russian clauses. "
            "Resolve verb-final clauses, separable verbs, modal scope, and negation before "
            "drafting Russian. Preserve legal suffixes such as GmbH, AG, and e.V. in "
            "company names; avoid bureaucratic calques unless the source is official."
        ),
    ),
    ("fr", "ru"): SourcePairProfile(
        source_language="fr",
        target_language="ru",
        version="v1",
        prompt=(
            "Source-pair policy: French to Russian source-pair profile. "
            "Avoid French abstract-noun calques and passive stiffness when Russian "
            "naturally uses verbs. Preserve the scope of ne pas and other negation. "
            "Resolve false friends such as actuel, éventuellement, contrôle, librairie, "
            "and sensible. Convert French quotation and spacing conventions to Russian "
            "unless preserving a citation or title."
        ),
    ),
    ("es", "ru"): SourcePairProfile(
        source_language="es",
        target_language="ru",
        version="v1",
        prompt=(
            "Source-pair policy: Spanish to Russian source-pair profile. "
            "Resolve ser/estar, subject omission, Romance syntax, and inverted punctuation "
            "before writing Russian. Avoid false friends such as actual, eventualmente, "
            "sensible, éxito, constipado, and librería. Preserve official accents in "
            "legal, citation, brand, and identity contexts."
        ),
    ),
    ("en", "uk"): SourcePairProfile(
        source_language="en",
        target_language="uk",
        version="v1",
        prompt=(
            "Source-pair policy: English to Ukrainian source-pair profile. "
            "Translate meaning into idiomatic Ukrainian; avoid English word order, "
            "mechanical possessives, article-like phrasing, literal phrasal verbs, "
            "and Title Case capitalization. "
            "Resolve English false friends by context, including actual, accurate, "
            "eventually, control, regular, data, decade, and magazine. "
            "Preserve protected code, API, URL, and exact identifier text."
        ),
    ),
    ("ru", "uk"): SourcePairProfile(
        source_language="ru",
        target_language="uk",
        version="v1",
        prompt=(
            "Source-pair policy: Russian to Ukrainian source-pair profile. "
            "Translate close Slavic wording into standard Ukrainian, not word-by-word replacement. "
            "Avoid Russian syntax calques, surzhyk, and lexical calques such as "
            "приймати участь, на протязі, являється, and слідуючий. "
            "Do not preserve Russian words unless they are names, citations, usernames, "
            "addresses, legal identities, or protected text. "
            "Preserve tone and document register without over-formalizing shared phrasing."
        ),
    ),
    ("auto", "ru"): SourcePairProfile(
        source_language="auto",
        target_language="ru",
        version="v1",
        prompt=(
            "Source-pair policy: Mixed-source to Russian source-pair profile. "
            "Use source_language hints when present, do not assume English, and translate "
            "every human-language span into Russian, including secondary languages. "
            "Keep labels consistent in Russian while preserving protected markers, code, "
            "URLs, placeholders, exact identifiers, and intentional names."
        ),
    ),
    ("auto", "uk"): SourcePairProfile(
        source_language="auto",
        target_language="uk",
        version="v1",
        prompt=(
            "Source-pair policy: Mixed-source to Ukrainian source-pair profile. "
            "Use source_language hints when present, do not assume English, and translate "
            "every human-language span into Ukrainian, including secondary languages. "
            "Keep labels consistent in Ukrainian while preserving protected markers, code, "
            "URLs, placeholders, exact identifiers, and intentional names."
        ),
    ),
}
