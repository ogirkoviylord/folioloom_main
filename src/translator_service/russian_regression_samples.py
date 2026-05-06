from dataclasses import dataclass

from translator_service.text_analysis import TextType


@dataclass(frozen=True)
class RussianRegressionSample:
    sample_id: str
    category: str
    source_text: str
    target_language: str
    expected_text_type: TextType
    expected_behavior: tuple[str, ...]
    required_prompt_terms: tuple[str, ...]


REQUIRED_RUSSIAN_SAMPLE_CATEGORIES = {
    "ordinary_prose",
    "literary",
    "technical",
    "business_legal",
    "scientific",
    "journalistic",
    "mixed_language",
    "named_entities",
    "protected_content",
    "heading_title_case",
}


def russian_regression_samples() -> tuple[RussianRegressionSample, ...]:
    return (
        RussianRegressionSample(
            sample_id="ru-ordinary-calque-decision-overview",
            category="ordinary_prose",
            source_text="He made a decision after a high-level overview of the system.",
            target_language="ru",
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Avoid сделал решение.",
                "Avoid mechanical высокоуровневый обзор in general prose.",
            ),
            required_prompt_terms=(
                "made a decision",
                "решил",
                "high-level overview",
                "общее описание",
            ),
        ),
        RussianRegressionSample(
            sample_id="ru-literary-rain-window",
            category="literary",
            source_text="The room held its breath while the rain traced silver lines across the window.",
            target_language="ru",
            expected_text_type=TextType.LITERARY_FICTION,
            expected_behavior=(
                "Preserve imagery and rhythm.",
                "Do not flatten the sentence into neutral explanation.",
            ),
            required_prompt_terms=("voice, rhythm", "imagery"),
        ),
        RussianRegressionSample(
            sample_id="ru-technical-api-placeholder-callback",
            category="technical",
            source_text="Set the API endpoint and pass the placeholder token to the callback handler.",
            target_language="ru",
            expected_text_type=TextType.TECHNICAL,
            expected_behavior=(
                "Preserve API and technical identifiers.",
                "Use stable Russian technical terminology or controlled transcription.",
            ),
            required_prompt_terms=(
                "technical documentation",
                "preserve code identifiers",
                "placeholder",
                "плейсхолдер",
                "callback",
            ),
        ),
        RussianRegressionSample(
            sample_id="ru-business-acme-obligation",
            category="business_legal",
            source_text="Acme B.V. shall deliver the materials by 15 March 2026 under this agreement.",
            target_language="ru",
            expected_text_type=TextType.BUSINESS_LEGAL_LIKE,
            expected_behavior=(
                "Preserve legal company name and date.",
                "Preserve obligation without creative paraphrase.",
            ),
            required_prompt_terms=("formal Russian", "obligations", "legal entity names"),
        ),
        RussianRegressionSample(
            sample_id="ru-scientific-correlation-hedging",
            category="scientific",
            source_text="The results suggest a moderate correlation, but the sample size limits the conclusion.",
            target_language="ru",
            expected_text_type=TextType.SCIENTIFIC_ACADEMIC,
            expected_behavior=(
                "Preserve hedging.",
                "Do not overstate the conclusion.",
            ),
            required_prompt_terms=("Preserve claims", "hedging", "exact terminology"),
        ),
        RussianRegressionSample(
            sample_id="ru-journalistic-officials-policy",
            category="journalistic",
            source_text="Officials said the policy would be reviewed after public consultations.",
            target_language="ru",
            expected_text_type=TextType.JOURNALISTIC_PUBLICISTIC,
            expected_behavior=(
                "Preserve attribution.",
                "Use readable Russian publicistic rhythm.",
            ),
            required_prompt_terms=("publicistic", "facts", "attribution"),
        ),
        RussianRegressionSample(
            sample_id="ru-mixed-language-labels",
            category="mixed_language",
            source_text="English: The endpoint failed. Polski: Zażółć gęślą jaźń. Nederlands: De klant bevestigde de bestelling.",
            target_language="ru",
            expected_text_type=TextType.MIXED_UNKNOWN,
            expected_behavior=(
                "Translate all human-language segments into Russian.",
                "Treat the Polish pangram as an orthographic sample.",
            ),
            required_prompt_terms=("conservative general Russian", "technical and named-entity protections"),
        ),
        RussianRegressionSample(
            sample_id="ru-named-entities-maria-openai",
            category="named_entities",
            source_text="Maria Johnson visited Baker Street and met the OpenAI Research team.",
            target_language="ru",
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Transliterate ordinary personal names.",
                "Preserve brand spelling.",
            ),
            required_prompt_terms=("Transliterate ordinary personal names", "Preserve brands"),
        ),
        RussianRegressionSample(
            sample_id="ru-protected-content-token-url-row",
            category="protected_content",
            source_text="Set ${API_TOKEN}, call https://example.com/v1/items, and keep ROW-001 unchanged.",
            target_language="ru",
            expected_text_type=TextType.TECHNICAL,
            expected_behavior=(
                "Preserve placeholder, URL, and row identifier byte-for-byte.",
                "Translate surrounding prose only.",
            ),
            required_prompt_terms=("Do not add Russian case endings", "protected markers"),
        ),
        RussianRegressionSample(
            sample_id="ru-heading-title-case",
            category="heading_title_case",
            source_text="Translation Quality Roadmap",
            target_language="ru",
            expected_text_type=TextType.GENERAL,
            expected_behavior=("Use Russian sentence-style capitalization.",),
            required_prompt_terms=("natural modern Russian",),
        ),
    )


def format_russian_regression_sample_pack() -> str:
    sections = [
        "Russian Translation Regression Sample Pack",
        "",
        "Target language: ru",
        "Purpose: manual and automated QA for English/mixed-source translation into Russian.",
        "",
    ]
    for sample in russian_regression_samples():
        sections.extend(
            [
                f"## {sample.sample_id}",
                f"Category: {sample.category}",
                f"Expected text type: {sample.expected_text_type.value}",
                "",
                "Source:",
                sample.source_text,
                "",
                "Expected behavior:",
                *[f"- {item}" for item in sample.expected_behavior],
                "",
                "Required prompt terms:",
                *[f"- {term}" for term in sample.required_prompt_terms],
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"
