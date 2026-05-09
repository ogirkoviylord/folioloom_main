from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from translator_service.russian_quality import (
    RussianQualityTrack,
    detect_russian_quality_track,
)
from translator_service.russian_quality_checks import (
    RussianQualityIssue,
    check_russian_translation_quality,
)


@dataclass(frozen=True)
class TranslationEvalCriterion:
    name: str
    weight: float
    description: str


@dataclass(frozen=True)
class TranslationEvalRubric:
    language: str
    version: str
    quality_track: RussianQualityTrack | None
    criteria: tuple[TranslationEvalCriterion, ...]
    pass_score: float = 85.0


@dataclass(frozen=True)
class TranslationEvalIssue:
    code: str
    category: str
    severity: str
    message: str
    source_fragment: str | None = None
    penalty: float = 0.0


@dataclass(frozen=True)
class TranslationEvalResult:
    sample_id: str | None
    source_language: str
    target_language: str
    quality_track: RussianQualityTrack | None
    rubric_version: str
    score: float
    passed: bool
    issues: tuple[TranslationEvalIssue, ...]


@dataclass(frozen=True)
class TranslationEvalReport:
    sample_count: int
    passed_count: int
    failed_count: int
    average_score: float
    issue_counts: dict[str, int]
    worst_sample_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExternalMetricResult:
    metric_name: str
    metric_version: str
    score: float
    metadata: dict | None = None


class ExternalMetricAdapter(Protocol):
    def score(
        self,
        *,
        source_text: str,
        translated_text: str,
        reference_translation: str | None = None,
    ) -> ExternalMetricResult:
        ...


class OptionalMetricDisabledError(RuntimeError):
    pass


RUSSIAN_MQM_RUBRIC_VERSION = "russian-mqm-rubric-v1"


def build_russian_eval_rubric(
    quality_track: RussianQualityTrack | None,
) -> TranslationEvalRubric:
    if quality_track is RussianQualityTrack.LITERARY:
        criteria = (
            TranslationEvalCriterion(
                name="accuracy",
                weight=0.25,
                description="Meaning is preserved without omissions or additions.",
            ),
            TranslationEvalCriterion(
                name="fluency",
                weight=0.25,
                description="Russian reads naturally and idiomatically.",
            ),
            TranslationEvalCriterion(
                name="style",
                weight=0.20,
                description="Register, rhythm, imagery, and tone fit the source.",
            ),
            TranslationEvalCriterion(
                name="voice",
                weight=0.15,
                description="Narrator and speaker voice remain consistent.",
            ),
            TranslationEvalCriterion(
                name="terminology",
                weight=0.08,
                description="Recurring terms and names are consistent.",
            ),
            TranslationEvalCriterion(
                name="structure",
                weight=0.07,
                description="Paragraphs, lists, headings, and protected content survive.",
            ),
        )
    else:
        criteria = (
            TranslationEvalCriterion(
                name="accuracy",
                weight=0.35,
                description="Facts, obligations, numbers, dates, and constraints are preserved.",
            ),
            TranslationEvalCriterion(
                name="terminology",
                weight=0.22,
                description="Domain terms, names, identifiers, and labels are consistent.",
            ),
            TranslationEvalCriterion(
                name="structure",
                weight=0.18,
                description="Formatting, tables, lists, placeholders, links, and IDs survive.",
            ),
            TranslationEvalCriterion(
                name="fluency",
                weight=0.12,
                description="Russian is clear and readable without changing meaning.",
            ),
            TranslationEvalCriterion(
                name="style",
                weight=0.08,
                description="Register is appropriate for the document type.",
            ),
            TranslationEvalCriterion(
                name="voice",
                weight=0.05,
                description="Speaker or author stance is not distorted.",
            ),
        )
    return TranslationEvalRubric(
        language="ru",
        version=RUSSIAN_MQM_RUBRIC_VERSION,
        quality_track=quality_track,
        criteria=criteria,
    )


def evaluate_russian_translation(
    *,
    source_text: str,
    translated_text: str,
    source_language: str,
    target_language: str,
    quality_track: RussianQualityTrack | None = None,
    sample_id: str | None = None,
) -> TranslationEvalResult:
    track = quality_track
    if track is None and _language_root(target_language) == "ru":
        track = detect_russian_quality_track(
            source_text,
            target_language=target_language,
        ).track
    rubric = build_russian_eval_rubric(track)
    qa_result = check_russian_translation_quality(
        source_text=source_text,
        translated_text=translated_text,
        source_language=source_language,
        target_language=target_language,
        quality_track=track,
    )
    issues = tuple(_eval_issue(issue) for issue in qa_result.issues)
    score = max(0.0, 100.0 - sum(issue.penalty for issue in issues))
    score = round(score, 2)
    passed = score >= rubric.pass_score and not any(
        issue.severity in {"error", "critical"} for issue in issues
    )
    return TranslationEvalResult(
        sample_id=sample_id,
        source_language=source_language,
        target_language=target_language,
        quality_track=track,
        rubric_version=rubric.version,
        score=score,
        passed=passed,
        issues=issues,
    )


def build_translation_eval_report(
    results: list[TranslationEvalResult] | tuple[TranslationEvalResult, ...],
) -> TranslationEvalReport:
    sample_count = len(results)
    passed_count = sum(1 for result in results if result.passed)
    failed_count = sample_count - passed_count
    average_score = (
        round(sum(result.score for result in results) / sample_count, 2)
        if sample_count
        else 0.0
    )
    issue_counter: Counter[str] = Counter()
    for result in results:
        for issue in result.issues:
            issue_counter[issue.category] += 1
    worst_score = min((result.score for result in results), default=0.0)
    worst_sample_ids = tuple(
        result.sample_id
        for result in results
        if result.sample_id is not None and result.score == worst_score
    )
    return TranslationEvalReport(
        sample_count=sample_count,
        passed_count=passed_count,
        failed_count=failed_count,
        average_score=average_score,
        issue_counts=dict(sorted(issue_counter.items())),
        worst_sample_ids=worst_sample_ids,
    )


def run_optional_metric(
    adapter: ExternalMetricAdapter,
    *,
    source_text: str,
    translated_text: str,
    reference_translation: str | None = None,
    opt_in: bool = False,
) -> ExternalMetricResult:
    if not opt_in:
        raise OptionalMetricDisabledError(
            "Optional translation metrics require explicit opt-in."
        )
    return adapter.score(
        source_text=source_text,
        translated_text=translated_text,
        reference_translation=reference_translation,
    )


def _eval_issue(issue: RussianQualityIssue) -> TranslationEvalIssue:
    category = _ISSUE_CATEGORY_BY_CODE.get(issue.code, "accuracy")
    return TranslationEvalIssue(
        code=issue.code,
        category=category,
        severity=issue.severity,
        message=issue.message,
        source_fragment=issue.source_fragment,
        penalty=_penalty_for(issue.severity, category),
    )


def _penalty_for(severity: str, category: str) -> float:
    base = {
        "warning": 4.0,
        "error": 12.0,
        "critical": 25.0,
    }.get(severity, 8.0)
    if category == "protected_content":
        return base * 1.25
    if category == "untranslated_text":
        return base * 1.5
    return base


def _language_root(language: str) -> str:
    return language.strip().lower().split("-", 1)[0].split("_", 1)[0]


_ISSUE_CATEGORY_BY_CODE = {
    "missing_url": "protected_content",
    "missing_placeholder": "protected_content",
    "missing_identifier": "protected_content",
    "missing_date": "accuracy",
    "missing_number": "accuracy",
    "missing_currency_amount": "accuracy",
    "protected_marker_leaked": "protected_content",
    "provider_commentary": "structure",
    "untranslated_source_residue": "untranslated_text",
}
