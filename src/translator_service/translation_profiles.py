from dataclasses import dataclass

from translator_service.russian_quality import RussianQualityTrack
from translator_service.text_analysis import TextType


@dataclass(frozen=True)
class TargetLanguageProfile:
    language_code: str
    version: str
    default_rules: tuple[str, ...]
    named_entity_rules: tuple[str, ...]
    terminology_rules: tuple[str, ...]
    term_examples: tuple[str, ...]
    naturalness_examples: tuple[str, ...]
    protected_grammar_examples: tuple[str, ...]
    text_type_rules: dict[TextType, str]
    quality_track_rules: dict[RussianQualityTrack, str]


_PROFILE_DISPLAY_NAMES = {
    "ru": "Russian",
    "uk": "Ukrainian",
}


def get_target_language_profile(
    target_language: str,
) -> TargetLanguageProfile | None:
    normalized = _language_root(target_language)
    if normalized == "ru":
        return RUSSIAN_PROFILE
    if normalized == "uk":
        return UKRAINIAN_PROFILE
    return None


def _language_root(language_code: str) -> str:
    return language_code.strip().lower().replace("_", "-").split("-", 1)[0]


def _profile_display_name(profile: TargetLanguageProfile) -> str:
    return _PROFILE_DISPLAY_NAMES.get(profile.language_code, profile.language_code)


def target_language_policy_signature(target_language: str) -> str:
    profile = get_target_language_profile(target_language)
    if profile is None:
        return "target-profile:default-v1"
    return f"target-profile:{profile.language_code}:{profile.version}"


def build_target_language_profile_prompt(
    *,
    target_language: str,
    text_type: TextType,
    quality_track: RussianQualityTrack | None = None,
) -> str:
    profile = get_target_language_profile(target_language)
    if profile is None:
        return ""

    text_type_rule = profile.text_type_rules.get(
        text_type,
        profile.text_type_rules[TextType.GENERAL],
    )
    quality_track_rule = (
        profile.quality_track_rules[quality_track]
        if quality_track in profile.quality_track_rules
        else ""
    )
    display_name = _profile_display_name(profile)
    sections = [
        f"Target-language policy: {display_name} target-language profile {profile.version}.",
        f"Detected text type: {text_type.value}.",
        f"Text-type instruction: {text_type_rule}",
        quality_track_rule,
        f"Default {display_name} rules: " + " ".join(profile.default_rules),
        "Named entity rules: " + " ".join(profile.named_entity_rules),
        "Terminology rules: " + " ".join(profile.terminology_rules),
        "Term examples: " + "; ".join(profile.term_examples) + ".",
        f"{display_name} naturalness examples: "
        + " ".join(profile.naturalness_examples),
        "Protected-term grammar examples: "
        + " ".join(profile.protected_grammar_examples),
    ]
    return " ".join(sections)


RUSSIAN_PROFILE = TargetLanguageProfile(
    language_code="ru",
    version="russian-v2",
    default_rules=(
        "Write natural modern Russian and avoid English word order, literal calques, and awkward nominalizations.",
        "Preserve meaning, tone, author voice, paragraph boundaries, and document structure.",
        "Do not add explanations or simplify specialized content unless the source does so.",
    ),
    named_entity_rules=(
        "Preserve brands, product names, legal company names, URLs, usernames, code identifiers, API names, package names, library names, commands, flags, filenames, and environment variables.",
        "Transliterate ordinary personal names for Russian readers when the document is not a legal identity, citation, username, email, or code-owner context.",
        "Use established Russian country and city names where they exist; preserve exact address components when precision matters.",
    ),
    terminology_rules=(
        "Use stable Russian technical terminology where it is natural.",
        "Preserve or transcribe established English IT terms when literal translation sounds artificial.",
        "Keep the same terminology choice consistently throughout the document.",
        "Avoid false friends such as actual, accurate, eventually, control, public, and regular.",
    ),
    term_examples=(
        "query parameters -> параметры запроса",
        "regular expression -> регулярное выражение",
        "footnote -> сноска",
        "endnote -> концевая сноска or затекстовая сноска by context",
        "tracked changes -> исправления or отслеживаемые изменения by context",
        "placeholder -> плейсхолдер in technical UI/LLM context, заполнитель in general UI context",
        "prompt -> промпт in LLM context, подсказка only for user hints",
        "token -> токен in LLM/API/security context",
        "callback -> callback for code/API reference, колбэк in explanatory prose",
        "endpoint -> endpoint for API references, эндпоинт in explanatory prose",
        "framework -> фреймворк",
    ),
    naturalness_examples=(
        "Do not translate made a decision as сделал решение; prefer решил or принял решение by register.",
        "Do not translate high-level overview mechanically as высокоуровневый обзор in general prose; prefer общее описание unless the source is explicitly technical.",
        "Avoid mechanical possessives and English sentence order when Russian would normally use a noun phrase, omit the pronoun, or move the verb earlier.",
    ),
    protected_grammar_examples=(
        "When preserved terms need Russian grammar, write a Russian support noun such as модуль FastAPI, пакет requests, метод callback, or callback-функцию.",
        "Do not add Russian case endings inside inline code, API names, package names, URLs, commands, or protected markers.",
    ),
    text_type_rules={
        TextType.GENERAL: "Use clear contemporary Russian with moderate rewriting for natural Russian syntax.",
        TextType.LITERARY_FICTION: "Preserve voice, rhythm, dialogue, imagery, irony, ambiguity, and narrator perspective.",
        TextType.LITERARY_NON_FICTION: "Preserve author voice while producing polished editorial Russian.",
        TextType.JOURNALISTIC_PUBLICISTIC: "Use readable Russian publicistic style and preserve facts, attribution, dates, and quotes.",
        TextType.SCIENTIFIC_ACADEMIC: "Preserve claims, hedging, citations, units, formulas, and exact terminology.",
        TextType.TECHNICAL: "For technical documentation, be concise; preserve code identifiers, API names, package names, filenames, command flags, env vars, and product names.",
        TextType.BUSINESS_LEGAL_LIKE: "Use formal Russian without creative paraphrase; preserve obligations, defined terms, dates, amounts, and legal entity names.",
        TextType.EDUCATIONAL: "Use clear explanatory Russian and translate descriptive learning headings.",
        TextType.MARKETING: "Use idiomatic Russian marketing copy without inventing claims, benefits, or guarantees.",
        TextType.MIXED_UNKNOWN: "Use conservative general Russian with technical and named-entity protections enabled.",
    },
    quality_track_rules={
        RussianQualityTrack.LITERARY: "Literary Russian quality track: preserve voice, rhythm, dialogue, imagery, narrator perspective, and author style; allow natural Russian sentence restructuring when it improves literary fluency without adding explanations.",
        RussianQualityTrack.PRECISION: "Precision Russian quality track: prioritize terminology, dates, numbers, legal obligations, structure, code, URLs, IDs, placeholders, tables, lists, and exact named entities over stylistic embellishment.",
    },
)


UKRAINIAN_PROFILE = TargetLanguageProfile(
    language_code="uk",
    version="ukrainian-v1",
    default_rules=(
        "Write natural contemporary standard Ukrainian according to the current official Ukrainian orthography standard.",
        "Avoid Russian calques, surzhyk, English word order, literal phrasal translations, and awkward nominalizations.",
        "Use Ukrainian guillemets «...» for ordinary prose quotations; do not preserve German-oriented guillemets »...« in Ukrainian output.",
        "Preserve meaning, tone, author voice, paragraph boundaries, and document structure.",
        "Do not add explanations or simplify specialized content unless the source does so.",
    ),
    named_entity_rules=(
        "Preserve brands, product names, legal company names, URLs, usernames, code identifiers, API names, package names, library names, commands, flags, filenames, and environment variables.",
        "Transcribe ordinary personal names for Ukrainian readers when the document is not a legal identity, citation, username, email, or code-owner context.",
        "Use established Ukrainian country and city names where they exist; preserve exact address components when precision matters.",
    ),
    terminology_rules=(
        "Use stable Ukrainian technical terminology where it is natural.",
        "Preserve exact English technical terms only when they are protected names, API references, or code-like identifiers.",
        "Keep the same terminology choice consistently throughout the document.",
        "Avoid false friends and calques such as actual, accurate, eventually, control, regular, data, decade, magazine, приймати участь, на протязі, являється, and слідуючий.",
    ),
    term_examples=(
        "query parameters -> параметри запиту",
        "regular expression -> регулярний вираз",
        "footnote -> виноска",
        "endnote -> кінцева виноска by context",
        "tracked changes -> виправлення or відстежені зміни by context",
        "section break -> розрив розділу",
        "table of contents -> зміст",
        "placeholder -> заповнювач in general UI context, плейсхолдер in technical UI/LLM context",
        "prompt -> промпт in LLM context, підказка only for user hints",
        "token -> токен in LLM/API/security context",
        "callback -> callback for exact code/API reference, зворотний виклик or колбек in explanatory prose by context",
        "endpoint -> endpoint for exact API references, кінцева точка or glossary-pinned ендпоінт in explanatory prose",
        "framework -> фреймворк",
    ),
    naturalness_examples=(
        "Do not translate made a decision as зробив рішення; prefer вирішив or ухвалив рішення by register.",
        "Do not translate participate as приймати участь; use брати участь.",
        "Do not translate during or over as на протязі unless the source literally describes physical draft or extension; use протягом.",
        "Do not translate is or constitutes as являється; use є, a verb, or a natural Ukrainian construction.",
    ),
    protected_grammar_examples=(
        "When preserved terms need Ukrainian grammar, write a Ukrainian support noun such as модуль FastAPI, пакет requests, метод callback, змінна PATH, or команда git commit.",
        "Do not add Ukrainian case endings inside inline code, API names, package names, URLs, commands, or protected markers.",
    ),
    text_type_rules={
        TextType.GENERAL: "Use clear contemporary Ukrainian with moderate rewriting for natural Ukrainian syntax.",
        TextType.LITERARY_FICTION: "Preserve voice, rhythm, dialogue, imagery, irony, ambiguity, and narrator perspective.",
        TextType.LITERARY_NON_FICTION: "Preserve author voice while producing polished editorial Ukrainian.",
        TextType.JOURNALISTIC_PUBLICISTIC: "Use readable Ukrainian publicistic style and preserve facts, attribution, dates, and quotes.",
        TextType.SCIENTIFIC_ACADEMIC: "Preserve claims, hedging, citations, units, formulas, and exact terminology.",
        TextType.TECHNICAL: "For technical documentation, be concise; preserve code identifiers, API names, package names, filenames, command flags, env vars, and product names.",
        TextType.BUSINESS_LEGAL_LIKE: "Use formal Ukrainian without creative paraphrase; preserve obligations, defined terms, dates, amounts, and legal entity names.",
        TextType.EDUCATIONAL: "Use clear explanatory Ukrainian and translate descriptive learning headings.",
        TextType.MARKETING: "Use idiomatic Ukrainian marketing copy without inventing claims, benefits, urgency, or guarantees.",
        TextType.MIXED_UNKNOWN: "Use conservative general Ukrainian with technical and named-entity protections enabled.",
    },
    quality_track_rules={
        RussianQualityTrack.LITERARY: "Literary Ukrainian quality track: preserve voice, rhythm, dialogue, imagery, narrator perspective, ambiguity, and author style; allow natural Ukrainian sentence restructuring when it improves literary fluency without adding explanations.",
        RussianQualityTrack.PRECISION: "Precision Ukrainian quality track: prioritize terminology, dates, numbers, legal obligations, structure, code, URLs, IDs, placeholders, tables, lists, and exact named entities over stylistic embellishment.",
    },
)
