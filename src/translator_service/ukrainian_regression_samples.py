from dataclasses import dataclass

from translator_service.russian_quality import RussianQualityTrack
from translator_service.text_analysis import TextType


@dataclass(frozen=True)
class UkrainianRegressionSample:
    sample_id: str
    category: str
    source_language: str
    source_text: str
    target_language: str
    quality_track: RussianQualityTrack
    expected_text_type: TextType
    expected_behavior: tuple[str, ...]
    banned_outputs: tuple[str, ...]
    required_preservations: tuple[str, ...]
    required_prompt_terms: tuple[str, ...]
    required_source_pair_terms: tuple[str, ...] = ()
    reference_translation: str | None = None


REQUIRED_UKRAINIAN_SAMPLE_CATEGORIES = {
    "ordinary_prose",
    "russian_calque",
    "literary",
    "technical",
    "business_legal",
    "scientific",
    "journalistic",
    "mixed_language",
    "named_entities",
    "protected_content",
    "heading_title_case",
    "typography",
}

REQUIRED_UKRAINIAN_SOURCE_LANGUAGES = {
    "auto",
    "en",
    "ru",
}


def ukrainian_regression_samples() -> tuple[UkrainianRegressionSample, ...]:
    return (
        UkrainianRegressionSample(
            sample_id="uk-ordinary-calque-decision-overview",
            category="ordinary_prose",
            source_language="en",
            source_text="He made a decision after a high-level overview of the system.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Avoid зробив рішення.",
                "Avoid awkward високорівневим оглядом in general prose.",
            ),
            banned_outputs=("зробив рішення", "високорівневим оглядом"),
            required_preservations=("system",),
            required_prompt_terms=(
                "standard Ukrainian",
                "зробив рішення",
                "вирішив",
                "ухвалив рішення",
            ),
            required_source_pair_terms=(
                "English to Ukrainian source-pair profile",
                "English word order",
            ),
            reference_translation="Він ухвалив рішення після загального огляду системи.",
        ),
        UkrainianRegressionSample(
            sample_id="uk-ru-calque-participation-duration",
            category="russian_calque",
            source_language="ru",
            source_text="Он принял участие в проекте на протяжении месяца. Следующий раздел является обзором.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Translate Russian meaning into standard Ukrainian, not word replacement.",
                "Avoid прийняв участь, на протязі, слідуючий, and являється.",
            ),
            banned_outputs=("прийняв участь", "на протязі", "слідуючий", "являється"),
            required_preservations=("місяця",),
            required_prompt_terms=(
                "Avoid Russian calques",
                "брати участь",
                "протягом",
            ),
            required_source_pair_terms=(
                "Russian to Ukrainian source-pair profile",
                "standard Ukrainian",
                "surzhyk",
            ),
            reference_translation="Він узяв участь у проєкті протягом місяця. Наступний розділ є оглядом.",
        ),
        UkrainianRegressionSample(
            sample_id="uk-literary-rain-window",
            category="literary",
            source_language="en",
            source_text="The room held its breath while the rain traced silver lines across the window.",
            target_language="uk",
            quality_track=RussianQualityTrack.LITERARY,
            expected_text_type=TextType.LITERARY_FICTION,
            expected_behavior=(
                "Preserve imagery and rhythm.",
                "Do not flatten literary prose into neutral explanation.",
            ),
            banned_outputs=("Кімната тримала своє дихання", "дощ простежував"),
            required_preservations=("room", "rain", "window"),
            required_prompt_terms=("Literary Ukrainian quality track", "voice, rhythm"),
            required_source_pair_terms=("English to Ukrainian source-pair profile",),
            reference_translation="Кімната ніби затамувала подих, поки дощ креслив срібні лінії на шибці.",
        ),
        UkrainianRegressionSample(
            sample_id="uk-technical-api-placeholder-callback",
            category="technical",
            source_language="en",
            source_text="Set the API endpoint and pass the placeholder token to the callback handler.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.TECHNICAL,
            expected_behavior=(
                "Preserve API and exact technical references.",
                "Use stable Ukrainian technical terminology where natural.",
            ),
            banned_outputs=("знак-заповнювач", "контрольний обробник"),
            required_preservations=("API", "endpoint", "callback"),
            required_prompt_terms=(
                "technical documentation",
                "preserve code identifiers",
                "заповнювач",
                "callback",
            ),
            required_source_pair_terms=("false friends", "phrasal verbs"),
            reference_translation="Задайте API endpoint і передайте токен-заповнювач обробнику callback.",
        ),
        UkrainianRegressionSample(
            sample_id="uk-business-acme-obligation",
            category="business_legal",
            source_language="en",
            source_text="Acme B.V. shall deliver the materials by 15 March 2026 under this agreement.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.BUSINESS_LEGAL_LIKE,
            expected_behavior=(
                "Preserve legal company name and date.",
                "Preserve obligation without creative paraphrase.",
            ),
            banned_outputs=("обіцяє", "коли-небудь"),
            required_preservations=("Acme B.V.", "15 March 2026"),
            required_prompt_terms=("formal Ukrainian", "obligations", "legal entity names"),
            required_source_pair_terms=("English to Ukrainian source-pair profile",),
        ),
        UkrainianRegressionSample(
            sample_id="uk-scientific-correlation-hedging",
            category="scientific",
            source_language="en",
            source_text="The results suggest a moderate correlation, but the sample size limits the conclusion.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.SCIENTIFIC_ACADEMIC,
            expected_behavior=(
                "Preserve hedging.",
                "Do not overstate the conclusion.",
            ),
            banned_outputs=("доводять", "однозначно підтверджують"),
            required_preservations=("moderate correlation", "sample size"),
            required_prompt_terms=("Preserve claims", "hedging", "exact terminology"),
            required_source_pair_terms=("English to Ukrainian source-pair profile",),
        ),
        UkrainianRegressionSample(
            sample_id="uk-journalistic-officials-policy",
            category="journalistic",
            source_language="en",
            source_text="Officials said the policy would be reviewed after public consultations.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.JOURNALISTIC_PUBLICISTIC,
            expected_behavior=(
                "Preserve attribution.",
                "Use readable Ukrainian publicistic style.",
            ),
            banned_outputs=("без джерела", "як відомо"),
            required_preservations=("Officials said", "public consultations"),
            required_prompt_terms=("publicistic", "facts", "attribution"),
            required_source_pair_terms=("English to Ukrainian source-pair profile",),
        ),
        UkrainianRegressionSample(
            sample_id="uk-mixed-language-labels",
            category="mixed_language",
            source_language="auto",
            source_text="English: The endpoint failed. Russian: Пользователь открыл настройки.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.MIXED_UNKNOWN,
            expected_behavior=(
                "Translate all human-language segments into Ukrainian.",
                "Preserve protected technical terms and useful labels.",
            ),
            banned_outputs=("The endpoint failed", "Пользователь открыл настройки"),
            required_preservations=("English:", "Russian:", "endpoint"),
            required_prompt_terms=("conservative general Ukrainian", "technical and named-entity protections"),
            required_source_pair_terms=(
                "Mixed-source to Ukrainian source-pair profile",
                "translate every human-language span",
            ),
        ),
        UkrainianRegressionSample(
            sample_id="uk-named-entities-maria-openai",
            category="named_entities",
            source_language="en",
            source_text="Maria Johnson visited Baker Street and met the OpenAI Research team.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Transcribe ordinary personal names when appropriate.",
                "Preserve brand spelling.",
            ),
            banned_outputs=("OpenAI Research команда",),
            required_preservations=("Maria Johnson", "Baker Street", "OpenAI"),
            required_prompt_terms=("Transcribe ordinary personal names", "Preserve brands"),
            required_source_pair_terms=("English to Ukrainian source-pair profile",),
        ),
        UkrainianRegressionSample(
            sample_id="uk-protected-content-token-url-row",
            category="protected_content",
            source_language="en",
            source_text="Set ${API_TOKEN}, call https://example.com/v1/items, and keep ROW-001 unchanged.",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.TECHNICAL,
            expected_behavior=(
                "Preserve placeholder, URL, and row identifier byte-for-byte.",
                "Translate surrounding prose only.",
            ),
            banned_outputs=("${ТОКЕН_API}", "РЯДОК-001"),
            required_preservations=("${API_TOKEN}", "https://example.com/v1/items", "ROW-001"),
            required_prompt_terms=("Do not add Ukrainian case endings", "protected markers"),
            required_source_pair_terms=("Preserve protected code",),
        ),
        UkrainianRegressionSample(
            sample_id="uk-heading-title-case",
            category="heading_title_case",
            source_language="en",
            source_text="Translation Quality Roadmap",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=("Use Ukrainian sentence-style capitalization.",),
            banned_outputs=("Дорожня Карта Якості Перекладу",),
            required_preservations=("Translation Quality Roadmap",),
            required_prompt_terms=("standard Ukrainian",),
            required_source_pair_terms=("Title Case",),
        ),
        UkrainianRegressionSample(
            sample_id="uk-typography-german-guillemets",
            category="typography",
            source_language="en",
            source_text="She whispered, »The project is alive,« and closed the window.",
            target_language="uk",
            quality_track=RussianQualityTrack.LITERARY,
            expected_text_type=TextType.LITERARY_FICTION,
            expected_behavior=(
                "Normalize ordinary prose quotations to Ukrainian guillemets.",
                "Do not preserve German-oriented guillemet direction in Ukrainian prose.",
            ),
            banned_outputs=("»The project is alive,«", "»Проєкт живий,«"),
            required_preservations=("project", "window"),
            required_prompt_terms=("Use Ukrainian guillemets", "«...»"),
            required_source_pair_terms=("English to Ukrainian source-pair profile",),
        ),
    )


def format_ukrainian_regression_sample_pack() -> str:
    sections = [
        "Ukrainian Translation Regression Sample Pack",
        "",
        "Target language: uk",
        "Purpose: manual and automated QA for many-source translation into Ukrainian.",
        "",
    ]
    for sample in ukrainian_regression_samples():
        sections.extend(
            [
                f"## {sample.sample_id}",
                f"Category: {sample.category}",
                f"Source language: {sample.source_language}",
                f"Quality track: {sample.quality_track.value}",
                f"Expected text type: {sample.expected_text_type.value}",
                "",
                "Source:",
                sample.source_text,
                "",
                "Expected behavior:",
                *[f"- {item}" for item in sample.expected_behavior],
                "",
                "Banned outputs:",
                *[f"- {item}" for item in sample.banned_outputs],
                "",
                "Required preservations:",
                *[f"- {item}" for item in sample.required_preservations],
                "",
                *(
                    ["Reference translation:", sample.reference_translation, ""]
                    if sample.reference_translation is not None
                    else []
                ),
                "Required prompt terms:",
                *[f"- {term}" for term in sample.required_prompt_terms],
                "",
            ]
        )
    return "\n".join(sections).rstrip() + "\n"
