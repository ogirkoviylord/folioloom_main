from dataclasses import dataclass

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


def get_target_language_profile(
    target_language: str,
) -> TargetLanguageProfile | None:
    normalized = target_language.strip().lower()
    if normalized == "ru":
        return RUSSIAN_PROFILE
    return None


def target_language_policy_signature(target_language: str) -> str:
    profile = get_target_language_profile(target_language)
    if profile is None:
        return "target-profile:default-v1"
    return f"target-profile:{profile.language_code}:{profile.version}"


def build_target_language_profile_prompt(
    *,
    target_language: str,
    text_type: TextType,
) -> str:
    profile = get_target_language_profile(target_language)
    if profile is None:
        return ""

    text_type_rule = profile.text_type_rules.get(
        text_type,
        profile.text_type_rules[TextType.GENERAL],
    )
    sections = [
        f"Target-language policy: Russian target-language profile {profile.version}.",
        f"Detected text type: {text_type.value}.",
        f"Text-type instruction: {text_type_rule}",
        "Default Russian rules: " + " ".join(profile.default_rules),
        "Named entity rules: " + " ".join(profile.named_entity_rules),
        "Terminology rules: " + " ".join(profile.terminology_rules),
        "Term examples: " + "; ".join(profile.term_examples) + ".",
        "Russian naturalness examples: "
        + " ".join(profile.naturalness_examples),
        "Protected-term grammar examples: "
        + " ".join(profile.protected_grammar_examples),
    ]
    return " ".join(sections)


RUSSIAN_PROFILE = TargetLanguageProfile(
    language_code="ru",
    version="russian-v1",
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
)
