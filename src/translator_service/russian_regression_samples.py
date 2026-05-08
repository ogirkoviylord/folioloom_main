from dataclasses import dataclass

from translator_service.russian_quality import RussianQualityTrack
from translator_service.text_analysis import TextType


@dataclass(frozen=True)
class RussianRegressionSample:
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
    reference_translation: str | None = None


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

REQUIRED_RUSSIAN_SOURCE_LANGUAGES = {
    "auto",
    "en",
    "uk",
    "pl",
    "nl",
    "de",
    "fr",
    "es",
    "zh",
    "ja",
    "ko",
    "he",
    "ar",
}


def russian_regression_samples() -> tuple[RussianRegressionSample, ...]:
    return (
        RussianRegressionSample(
            sample_id="ru-ordinary-calque-decision-overview",
            category="ordinary_prose",
            source_language="en",
            source_text="He made a decision after a high-level overview of the system.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Avoid сделал решение.",
                "Avoid mechanical высокоуровневый обзор in general prose.",
            ),
            banned_outputs=("сделал решение", "высокоуровневый обзор"),
            required_preservations=("system",),
            required_prompt_terms=(
                "made a decision",
                "решил",
                "high-level overview",
                "общее описание",
            ),
            reference_translation="Он принял решение после общего описания системы.",
        ),
        RussianRegressionSample(
            sample_id="ru-literary-rain-window",
            category="literary",
            source_language="en",
            source_text="The room held its breath while the rain traced silver lines across the window.",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
            expected_text_type=TextType.LITERARY_FICTION,
            expected_behavior=(
                "Preserve imagery and rhythm.",
                "Do not flatten the sentence into neutral explanation.",
            ),
            banned_outputs=("Комната удерживала свое дыхание", "дождь прослеживал"),
            required_preservations=("room", "rain", "window"),
            required_prompt_terms=("voice, rhythm", "imagery"),
            reference_translation="Комната словно затаила дыхание, пока дождь чертил серебряные линии на стекле.",
        ),
        RussianRegressionSample(
            sample_id="ru-technical-api-placeholder-callback",
            category="technical",
            source_language="en",
            source_text="Set the API endpoint and pass the placeholder token to the callback handler.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.TECHNICAL,
            expected_behavior=(
                "Preserve API and technical identifiers.",
                "Use stable Russian technical terminology or controlled transcription.",
            ),
            banned_outputs=("конечная точка API", "знак-заполнитель"),
            required_preservations=("API", "endpoint", "callback"),
            required_prompt_terms=(
                "technical documentation",
                "preserve code identifiers",
                "placeholder",
                "плейсхолдер",
                "callback",
            ),
            reference_translation="Укажите API endpoint и передайте токен-плейсхолдер в callback-обработчик.",
        ),
        RussianRegressionSample(
            sample_id="ru-business-acme-obligation",
            category="business_legal",
            source_language="en",
            source_text="Acme B.V. shall deliver the materials by 15 March 2026 under this agreement.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.BUSINESS_LEGAL_LIKE,
            expected_behavior=(
                "Preserve legal company name and date.",
                "Preserve obligation without creative paraphrase.",
            ),
            banned_outputs=("обещает", "когда-нибудь"),
            required_preservations=("Acme B.V.", "15 March 2026"),
            required_prompt_terms=("formal Russian", "obligations", "legal entity names"),
            reference_translation="Acme B.V. обязуется предоставить материалы до 15 марта 2026 года в соответствии с настоящим соглашением.",
        ),
        RussianRegressionSample(
            sample_id="ru-scientific-correlation-hedging",
            category="scientific",
            source_language="en",
            source_text="The results suggest a moderate correlation, but the sample size limits the conclusion.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.SCIENTIFIC_ACADEMIC,
            expected_behavior=(
                "Preserve hedging.",
                "Do not overstate the conclusion.",
            ),
            banned_outputs=("доказывают", "однозначно подтверждают"),
            required_preservations=("moderate correlation", "sample size"),
            required_prompt_terms=("Preserve claims", "hedging", "exact terminology"),
        ),
        RussianRegressionSample(
            sample_id="ru-journalistic-officials-policy",
            category="journalistic",
            source_language="en",
            source_text="Officials said the policy would be reviewed after public consultations.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.JOURNALISTIC_PUBLICISTIC,
            expected_behavior=(
                "Preserve attribution.",
                "Use readable Russian publicistic rhythm.",
            ),
            banned_outputs=("без источника", "как известно"),
            required_preservations=("Officials said", "public consultations"),
            required_prompt_terms=("publicistic", "facts", "attribution"),
        ),
        RussianRegressionSample(
            sample_id="ru-mixed-language-labels",
            category="mixed_language",
            source_language="auto",
            source_text="English: The endpoint failed. Polski: Zażółć gęślą jaźń. Nederlands: De klant bevestigde de bestelling.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.MIXED_UNKNOWN,
            expected_behavior=(
                "Translate all human-language segments into Russian.",
                "Treat the Polish pangram as an orthographic sample.",
            ),
            banned_outputs=("The endpoint failed", "De klant bevestigde"),
            required_preservations=("English:", "Polski:", "Nederlands:", "endpoint"),
            required_prompt_terms=("conservative general Russian", "technical and named-entity protections"),
        ),
        RussianRegressionSample(
            sample_id="ru-named-entities-maria-openai",
            category="named_entities",
            source_language="en",
            source_text="Maria Johnson visited Baker Street and met the OpenAI Research team.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Transliterate ordinary personal names.",
                "Preserve brand spelling.",
            ),
            banned_outputs=("OpenAI Research команда",),
            required_preservations=("Maria Johnson", "Baker Street", "OpenAI"),
            required_prompt_terms=("Transliterate ordinary personal names", "Preserve brands"),
        ),
        RussianRegressionSample(
            sample_id="ru-protected-content-token-url-row",
            category="protected_content",
            source_language="en",
            source_text="Set ${API_TOKEN}, call https://example.com/v1/items, and keep ROW-001 unchanged.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.TECHNICAL,
            expected_behavior=(
                "Preserve placeholder, URL, and row identifier byte-for-byte.",
                "Translate surrounding prose only.",
            ),
            banned_outputs=("${ТОКЕН_API}", "СТРОКА-001"),
            required_preservations=("${API_TOKEN}", "https://example.com/v1/items", "ROW-001"),
            required_prompt_terms=("Do not add Russian case endings", "protected markers"),
        ),
        RussianRegressionSample(
            sample_id="ru-heading-title-case",
            category="heading_title_case",
            source_language="en",
            source_text="Translation Quality Roadmap",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=("Use Russian sentence-style capitalization.",),
            banned_outputs=("Дорожная Карта Качества Перевода",),
            required_preservations=("Translation Quality Roadmap",),
            required_prompt_terms=("natural modern Russian",),
        ),
        RussianRegressionSample(
            sample_id="ru-uk-literary-door",
            category="literary",
            source_language="uk",
            source_text="Українська: Вона тихо зачинила двері, і дім знову навчився мовчати.",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Translate Ukrainian prose into natural Russian.",
                "Preserve the quiet literary image.",
            ),
            banned_outputs=("дом научился молчать" ,),
            required_preservations=("Вона", "дім"),
            required_prompt_terms=("Literary Russian quality track", "voice, rhythm"),
            reference_translation="Она тихо закрыла дверь, и дом снова научился молчать.",
        ),
        RussianRegressionSample(
            sample_id="ru-pl-orthography-sample",
            category="mixed_language",
            source_language="pl",
            source_text="Polski: Zażółć gęślą jaźń — próbka polskich znaków.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Treat Polish pangram text as an orthographic sample.",
                "Do not render the pangram as nonsense prose.",
            ),
            banned_outputs=("Пожелти гуслью душу",),
            required_preservations=("ż", "ó", "ł", "ć", "ę", "ś", "ą", "ź", "ń"),
            required_prompt_terms=("Precision Russian quality track", "structure, code"),
            reference_translation="Проверка польских диакритических знаков: ż, ó, ł, ć, ę, ś, ą, ź, ń.",
        ),
        RussianRegressionSample(
            sample_id="ru-nl-business-order",
            category="business_legal",
            source_language="nl",
            source_text="Nederlands: De klant bevestigde de bestelling en betaalt binnen 14 dagen.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Translate Dutch business text into clear Russian.",
                "Preserve payment timing.",
            ),
            banned_outputs=("bestelling", "binnen 14 dagen"),
            required_preservations=("14"),
            required_prompt_terms=("Precision Russian quality track", "dates, numbers"),
        ),
        RussianRegressionSample(
            sample_id="ru-de-scientific-results",
            category="scientific",
            source_language="de",
            source_text="Deutsch: Die Ergebnisse deuten auf einen moderaten Zusammenhang hin, aber die Stichprobe ist klein.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Preserve scientific hedging.",
                "Do not overstate German source claims.",
            ),
            banned_outputs=("доказывают", "Zusammenhang"),
            required_preservations=("moderaten", "Stichprobe"),
            required_prompt_terms=("Precision Russian quality track", "terminology"),
        ),
        RussianRegressionSample(
            sample_id="ru-fr-hotel-price",
            category="ordinary_prose",
            source_language="fr",
            source_text="Français: Où est l’hôtel? Cela coûte 1 234,56 € aujourd’hui.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Translate French question naturally.",
                "Preserve amount and currency.",
            ),
            banned_outputs=("Où est", "coûte"),
            required_preservations=("1 234,56 €",),
            required_prompt_terms=("Precision Russian quality track", "dates, numbers"),
        ),
        RussianRegressionSample(
            sample_id="ru-es-marketing-claim",
            category="technical",
            source_language="es",
            source_text="Español: La versión beta mejora la velocidad un 20 %, sin cambiar la API pública.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Preserve measured claim without exaggeration.",
                "Preserve API spelling.",
            ),
            banned_outputs=("гарантирует", "API pública"),
            required_preservations=("20 %", "API"),
            required_prompt_terms=("Precision Russian quality track", "URLs, IDs"),
        ),
        RussianRegressionSample(
            sample_id="ru-zh-placeholder-variable",
            category="protected_content",
            source_language="zh",
            source_text="中文: 请保留变量 ${API_TOKEN}，并将说明翻译成俄语。",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.TECHNICAL,
            expected_behavior=(
                "Translate Chinese instruction text into Russian.",
                "Preserve placeholder exactly.",
            ),
            banned_outputs=("请保留变量", "${ТОКЕН_API}"),
            required_preservations=("${API_TOKEN}",),
            required_prompt_terms=("Precision Russian quality track", "placeholders"),
        ),
        RussianRegressionSample(
            sample_id="ru-ja-product-name",
            category="named_entities",
            source_language="ja",
            source_text="日本語: OpenAI Research は新しいモデル ID GPT-5.4 を発表しました。",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Translate Japanese sentence into Russian.",
                "Preserve brand and model identifier.",
            ),
            banned_outputs=("発表しました", "ОпенАИ"),
            required_preservations=("OpenAI Research", "GPT-5.4"),
            required_prompt_terms=("Preserve brands", "Precision Russian quality track"),
        ),
        RussianRegressionSample(
            sample_id="ru-ko-ui-label",
            category="technical",
            source_language="ko",
            source_text="한국어: 설정 화면에서 callback URL을 입력하고 저장을 누르세요.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Translate Korean UI instruction into Russian.",
                "Preserve callback URL term.",
            ),
            banned_outputs=("설정 화면", "저장을"),
            required_preservations=("callback URL",),
            required_prompt_terms=("callback", "Precision Russian quality track"),
        ),
        RussianRegressionSample(
            sample_id="ru-he-rtl-greeting",
            category="ordinary_prose",
            source_language="he",
            source_text="עברית: שלום עולם — זהו טקסט קצר בתוך מסמך מעורב.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Translate Hebrew RTL text into Russian.",
                "Do not leave sentence-length RTL text untranslated.",
            ),
            banned_outputs=("שלום עולם", "טקסט קצר"),
            required_preservations=("עברית:",),
            required_prompt_terms=("Precision Russian quality track", "structure"),
        ),
        RussianRegressionSample(
            sample_id="ru-ar-contract-signed",
            category="business_legal",
            source_language="ar",
            source_text="العربية: تم توقيع العقد في 5 مايو 2026 ويجب حفظ رقم المستند DOC-77.",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
            expected_text_type=TextType.GENERAL,
            expected_behavior=(
                "Translate Arabic legal-like text into Russian.",
                "Preserve date and document identifier.",
            ),
            banned_outputs=("تم توقيع", "رقم المستند"),
            required_preservations=("5", "2026", "DOC-77"),
            required_prompt_terms=("Precision Russian quality track", "legal obligations"),
        ),
    )


def format_russian_regression_sample_pack() -> str:
    sections = [
        "Russian Translation Regression Sample Pack",
        "",
        "Target language: ru",
        "Purpose: manual and automated QA for many-source translation into Russian.",
        "",
    ]
    for sample in russian_regression_samples():
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
