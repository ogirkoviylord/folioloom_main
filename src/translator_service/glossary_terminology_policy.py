from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

TERMINOLOGY_POLICY_SCHEMA_VERSION = "glossary-terminology-policy-v1"
TERMINOLOGY_POLICY_MATCH_SCHEMA_VERSION = "glossary-terminology-match-v1"

_POLICY_ID_RE = re.compile(r"^terminology_policy\.[a-z0-9][a-z0-9._:-]{0,126}$")
_SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,31}$")
_LANGUAGE_TAG_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8}){0,4}$")
_LANGUAGE_FAMILY_RE = re.compile(r"^[a-z][a-z0-9._:-]{1,63}$")


class TerminologyMatchMode(StrEnum):
    EXACT = "exact"
    CASEFOLD = "casefold"
    VARIANT_LIST = "variant_list"
    INFLECTION_AWARE = "inflection_aware"
    SCRIPT_OR_SEGMENTATION_AWARE = "script_or_segmentation_aware"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class TerminologyNormalizationMode(StrEnum):
    NFC = "nfc"
    NFC_CASEFOLD = "nfc_casefold"


class AllowedVariantStrategy(StrEnum):
    CANONICAL_ONLY = "canonical_only"
    CANONICAL_AND_VARIANTS = "canonical_and_variants"
    MANUAL_REVIEW_ONLY = "manual_review_only"


class ForbiddenVariantStrategy(StrEnum):
    IGNORE = "ignore"
    CONFIGURED_FORBIDDEN_VARIANTS = "configured_forbidden_variants"
    MANUAL_REVIEW_ONLY = "manual_review_only"


class UnsupportedTerminologyFallback(StrEnum):
    TBD = "tbd"
    UNKNOWN = "unknown"
    NEEDS_REVIEW = "needs_review"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class TerminologyPolicyReasonCode(StrEnum):
    SOURCE_TERM_ABSENT = "source_term_absent"
    MISSING_SELECTED_ENTRY = "missing_selected_entry"
    GLOSSARY_CONTEXT_OMITTED = "glossary_context_omitted"
    TARGET_METADATA_MISSING = "target_metadata_missing"
    POLICY_EXACT_MATCH = "policy_exact_match"
    POLICY_CASEFOLD_MATCH = "policy_casefold_match"
    POLICY_VARIANT_MATCH = "policy_variant_match"
    POLICY_FORBIDDEN_VARIANT_PRESENT = "policy_forbidden_variant_present"
    POLICY_TARGET_FORM_MISSING = "policy_target_form_missing"
    POLICY_MANUAL_REVIEW_REQUIRED = "policy_manual_review_required"
    POLICY_UNSUPPORTED_LANGUAGE = "policy_unsupported_language"
    POLICY_UNIMPLEMENTED_MATCH_MODE = "policy_unimplemented_match_mode"
    POLICY_DATA_INVALID = "policy_data_invalid"
    MORPHOLOGY_POLICY_TBD = "morphology_policy_tbd"
    SEMANTIC_TRUTH_NOT_PROVEN = "semantic_truth_not_proven"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class TerminologyPolicyValidationCode(StrEnum):
    MISSING_FIELD = "missing_field"
    INVALID_SCHEMA_VERSION = "invalid_schema_version"
    INVALID_POLICY_ID = "invalid_policy_id"
    INVALID_POLICY_VERSION = "invalid_policy_version"
    INVALID_LANGUAGE_TAG = "invalid_language_tag"
    INVALID_LANGUAGE_FAMILY = "invalid_language_family"
    INVALID_ENUM = "invalid_enum"
    INVALID_REASON_CODE = "invalid_reason_code"
    DUPLICATE_REASON_CODE = "duplicate_reason_code"


class TerminologyMatchStatus(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    FORBIDDEN_VARIANT = "forbidden_variant"
    NEEDS_REVIEW = "needs_review"
    UNSUPPORTED = "unsupported"
    INVALID_POLICY = "invalid_policy"


DEFAULT_TERMINOLOGY_POLICY_REASON_CODES: tuple[TerminologyPolicyReasonCode, ...] = (
    TerminologyPolicyReasonCode.SOURCE_TERM_ABSENT,
    TerminologyPolicyReasonCode.MISSING_SELECTED_ENTRY,
    TerminologyPolicyReasonCode.GLOSSARY_CONTEXT_OMITTED,
    TerminologyPolicyReasonCode.TARGET_METADATA_MISSING,
    TerminologyPolicyReasonCode.POLICY_EXACT_MATCH,
    TerminologyPolicyReasonCode.POLICY_CASEFOLD_MATCH,
    TerminologyPolicyReasonCode.POLICY_VARIANT_MATCH,
    TerminologyPolicyReasonCode.POLICY_FORBIDDEN_VARIANT_PRESENT,
    TerminologyPolicyReasonCode.POLICY_TARGET_FORM_MISSING,
    TerminologyPolicyReasonCode.POLICY_MANUAL_REVIEW_REQUIRED,
    TerminologyPolicyReasonCode.POLICY_UNSUPPORTED_LANGUAGE,
    TerminologyPolicyReasonCode.POLICY_UNIMPLEMENTED_MATCH_MODE,
    TerminologyPolicyReasonCode.POLICY_DATA_INVALID,
    TerminologyPolicyReasonCode.MORPHOLOGY_POLICY_TBD,
    TerminologyPolicyReasonCode.SEMANTIC_TRUTH_NOT_PROVEN,
    TerminologyPolicyReasonCode.NEEDS_HUMAN_REVIEW,
)


@dataclass(frozen=True)
class TerminologyPolicy:
    policy_id: str
    policy_version: str
    target_language: str | None
    language_family: str | None
    match_mode: TerminologyMatchMode | str
    normalization_mode: TerminologyNormalizationMode | str
    allowed_variant_strategy: AllowedVariantStrategy | str
    forbidden_variant_strategy: ForbiddenVariantStrategy | str
    unsupported_fallback: UnsupportedTerminologyFallback | str
    reason_codes: tuple[TerminologyPolicyReasonCode | str, ...]
    schema_version: str = TERMINOLOGY_POLICY_SCHEMA_VERSION


@dataclass(frozen=True)
class TerminologyPolicyValidationIssue:
    code: TerminologyPolicyValidationCode
    path: str
    message: str


@dataclass(frozen=True)
class TerminologyPolicyValidationResult:
    issues: tuple[TerminologyPolicyValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class TerminologyPolicyResolution:
    target_language: str | None
    language_family: str | None
    policy: TerminologyPolicy | None
    supported: bool
    fallback: UnsupportedTerminologyFallback
    reason_codes: tuple[TerminologyPolicyReasonCode, ...]
    metadata_only: bool = True
    raw_payload_included: bool = False
    semantic_quality_claim_made: bool = False
    full_morphology_claim_made: bool = False


@dataclass(frozen=True)
class TerminologyMatchResult:
    policy_id: str | None
    policy_version: str | None
    match_mode: TerminologyMatchMode | None
    status: TerminologyMatchStatus
    checked: bool
    local_form_match: bool
    forbidden_form_match: bool
    matched_form_kind: str | None
    reason_codes: tuple[TerminologyPolicyReasonCode, ...]
    metadata_only: bool = True
    raw_payload_included: bool = False
    semantic_quality_claim_made: bool = False
    full_morphology_claim_made: bool = False


class TerminologyPolicyRegistry:
    def __init__(self, policies: Iterable[TerminologyPolicy] = ()) -> None:
        by_language: dict[str, TerminologyPolicy] = {}
        by_family: dict[str, TerminologyPolicy] = {}
        for policy in policies:
            result = validate_terminology_policy(policy)
            if not result.valid:
                first_issue = result.issues[0]
                raise ValueError(
                    "Invalid terminology policy: "
                    f"{first_issue.path} {first_issue.message}"
                )
            if policy.target_language is not None:
                key = _normalize_identifier(policy.target_language)
                if key in by_language:
                    raise ValueError(f"Duplicate target_language policy: {key}.")
                by_language[key] = policy
            if policy.language_family is not None:
                key = _normalize_identifier(policy.language_family)
                if key in by_family:
                    raise ValueError(f"Duplicate language_family policy: {key}.")
                by_family[key] = policy
        self._by_language = by_language
        self._by_family = by_family

    def resolve(
        self,
        target_language: str | None,
        *,
        language_family: str | None = None,
    ) -> TerminologyPolicyResolution:
        normalized_language = _normalize_identifier(target_language)
        normalized_family = _normalize_identifier(language_family)
        if normalized_language and normalized_language in self._by_language:
            policy = self._by_language[normalized_language]
            return TerminologyPolicyResolution(
                target_language=normalized_language,
                language_family=normalized_family,
                policy=policy,
                supported=True,
                fallback=_enum_value(
                    policy.unsupported_fallback,
                    UnsupportedTerminologyFallback,
                ),
                reason_codes=(),
            )
        if normalized_family and normalized_family in self._by_family:
            policy = self._by_family[normalized_family]
            return TerminologyPolicyResolution(
                target_language=normalized_language,
                language_family=normalized_family,
                policy=policy,
                supported=True,
                fallback=_enum_value(
                    policy.unsupported_fallback,
                    UnsupportedTerminologyFallback,
                ),
                reason_codes=(),
            )
        return TerminologyPolicyResolution(
            target_language=normalized_language,
            language_family=normalized_family,
            policy=None,
            supported=False,
            fallback=UnsupportedTerminologyFallback.MANUAL_REVIEW_REQUIRED,
            reason_codes=(
                TerminologyPolicyReasonCode.POLICY_UNSUPPORTED_LANGUAGE,
                TerminologyPolicyReasonCode.POLICY_MANUAL_REVIEW_REQUIRED,
                TerminologyPolicyReasonCode.NEEDS_HUMAN_REVIEW,
            ),
        )


EMPTY_TERMINOLOGY_POLICY_REGISTRY = TerminologyPolicyRegistry()


def validate_terminology_policy(
    policy: TerminologyPolicy,
) -> TerminologyPolicyValidationResult:
    issues: list[TerminologyPolicyValidationIssue] = []
    if policy.schema_version != TERMINOLOGY_POLICY_SCHEMA_VERSION:
        _add_validation_issue(
            issues,
            TerminologyPolicyValidationCode.INVALID_SCHEMA_VERSION,
            "schema_version",
            f"schema_version must be {TERMINOLOGY_POLICY_SCHEMA_VERSION}.",
        )
    if not _valid_policy_id(policy.policy_id):
        _add_validation_issue(
            issues,
            TerminologyPolicyValidationCode.INVALID_POLICY_ID,
            "policy_id",
            "policy_id must be a lowercase terminology_policy.* identifier.",
        )
    if not _safe_version(policy.policy_version):
        _add_validation_issue(
            issues,
            TerminologyPolicyValidationCode.INVALID_POLICY_VERSION,
            "policy_version",
            "policy_version must be a compact safe identifier.",
        )
    target_language = _normalize_identifier(policy.target_language)
    language_family = _normalize_identifier(policy.language_family)
    if not target_language and not language_family:
        _add_validation_issue(
            issues,
            TerminologyPolicyValidationCode.MISSING_FIELD,
            "target_language",
            "target_language or language_family is required.",
        )
    if target_language and not _LANGUAGE_TAG_RE.fullmatch(target_language):
        _add_validation_issue(
            issues,
            TerminologyPolicyValidationCode.INVALID_LANGUAGE_TAG,
            "target_language",
            "target_language must be a lowercase BCP-47-like tag.",
        )
    if language_family and not _LANGUAGE_FAMILY_RE.fullmatch(language_family):
        _add_validation_issue(
            issues,
            TerminologyPolicyValidationCode.INVALID_LANGUAGE_FAMILY,
            "language_family",
            "language_family must be a compact lowercase identifier.",
        )
    _validate_enum_field(
        policy.match_mode,
        TerminologyMatchMode,
        issues,
        "match_mode",
    )
    _validate_enum_field(
        policy.normalization_mode,
        TerminologyNormalizationMode,
        issues,
        "normalization_mode",
    )
    _validate_enum_field(
        policy.allowed_variant_strategy,
        AllowedVariantStrategy,
        issues,
        "allowed_variant_strategy",
    )
    _validate_enum_field(
        policy.forbidden_variant_strategy,
        ForbiddenVariantStrategy,
        issues,
        "forbidden_variant_strategy",
    )
    _validate_enum_field(
        policy.unsupported_fallback,
        UnsupportedTerminologyFallback,
        issues,
        "unsupported_fallback",
    )
    _validate_reason_codes(policy.reason_codes, issues)
    return TerminologyPolicyValidationResult(tuple(issues))


def match_terminology_target(
    policy: TerminologyPolicy,
    *,
    translated_text: str | None,
    target_canonical: str | None,
    target_variants: Iterable[str] = (),
    forbidden_variants: Iterable[str] = (),
) -> TerminologyMatchResult:
    validation = validate_terminology_policy(policy)
    if not validation.valid:
        return _match_result(
            policy=policy,
            status=TerminologyMatchStatus.INVALID_POLICY,
            checked=False,
            local_form_match=False,
            forbidden_form_match=False,
            matched_form_kind=None,
            reason_codes=(TerminologyPolicyReasonCode.POLICY_DATA_INVALID,),
        )

    match_mode = _enum_value(policy.match_mode, TerminologyMatchMode)
    if match_mode is TerminologyMatchMode.MANUAL_REVIEW_REQUIRED:
        return _manual_review_result(policy)
    if match_mode in (
        TerminologyMatchMode.INFLECTION_AWARE,
        TerminologyMatchMode.SCRIPT_OR_SEGMENTATION_AWARE,
    ):
        return _match_result(
            policy=policy,
            status=TerminologyMatchStatus.NEEDS_REVIEW,
            checked=False,
            local_form_match=False,
            forbidden_form_match=False,
            matched_form_kind=None,
            reason_codes=(
                TerminologyPolicyReasonCode.POLICY_UNIMPLEMENTED_MATCH_MODE,
                TerminologyPolicyReasonCode.POLICY_MANUAL_REVIEW_REQUIRED,
                TerminologyPolicyReasonCode.MORPHOLOGY_POLICY_TBD,
                TerminologyPolicyReasonCode.NEEDS_HUMAN_REVIEW,
            ),
        )
    if not translated_text:
        return _target_missing_result(policy)

    normalization_mode = _normalization_for_policy(policy)
    if _forbidden_variant_present(
        policy,
        translated_text=translated_text,
        forbidden_variants=forbidden_variants,
        normalization_mode=normalization_mode,
    ):
        return _match_result(
            policy=policy,
            status=TerminologyMatchStatus.FORBIDDEN_VARIANT,
            checked=True,
            local_form_match=False,
            forbidden_form_match=True,
            matched_form_kind="forbidden_variant",
            reason_codes=(
                TerminologyPolicyReasonCode.POLICY_FORBIDDEN_VARIANT_PRESENT,
                TerminologyPolicyReasonCode.SEMANTIC_TRUTH_NOT_PROVEN,
            ),
        )

    allowed_forms = _allowed_forms(
        policy,
        target_canonical=target_canonical,
        target_variants=target_variants,
    )
    if not allowed_forms:
        return _match_result(
            policy=policy,
            status=TerminologyMatchStatus.NEEDS_REVIEW,
            checked=False,
            local_form_match=False,
            forbidden_form_match=False,
            matched_form_kind=None,
            reason_codes=(
                TerminologyPolicyReasonCode.TARGET_METADATA_MISSING,
                TerminologyPolicyReasonCode.POLICY_MANUAL_REVIEW_REQUIRED,
                TerminologyPolicyReasonCode.NEEDS_HUMAN_REVIEW,
            ),
        )

    for form, form_kind in allowed_forms:
        if _bounded_literal_present(
            form,
            translated_text,
            normalization_mode=normalization_mode,
        ):
            return _match_result(
                policy=policy,
                status=TerminologyMatchStatus.MATCH,
                checked=True,
                local_form_match=True,
                forbidden_form_match=False,
                matched_form_kind=form_kind,
                reason_codes=(
                    _match_reason(match_mode, form_kind),
                    TerminologyPolicyReasonCode.SEMANTIC_TRUTH_NOT_PROVEN,
                ),
            )

    return _target_missing_result(policy)


def terminology_policy_resolution_payload(
    resolution: TerminologyPolicyResolution,
) -> dict[str, Any]:
    policy = resolution.policy
    return {
        "target_language": resolution.target_language,
        "language_family": resolution.language_family,
        "supported": resolution.supported,
        "policy_id": policy.policy_id if policy is not None else None,
        "policy_version": policy.policy_version if policy is not None else None,
        "fallback": resolution.fallback.value,
        "reason_codes": _reason_values(resolution.reason_codes),
        "metadata_only": resolution.metadata_only,
        "raw_payload_included": resolution.raw_payload_included,
        "semantic_quality_claim_made": resolution.semantic_quality_claim_made,
        "full_morphology_claim_made": resolution.full_morphology_claim_made,
    }


def terminology_match_payload(result: TerminologyMatchResult) -> dict[str, Any]:
    return {
        "schema_version": TERMINOLOGY_POLICY_MATCH_SCHEMA_VERSION,
        "policy_id": result.policy_id,
        "policy_version": result.policy_version,
        "match_mode": result.match_mode.value if result.match_mode else None,
        "status": result.status.value,
        "checked": result.checked,
        "local_form_match": result.local_form_match,
        "forbidden_form_match": result.forbidden_form_match,
        "matched_form_kind": result.matched_form_kind,
        "reason_codes": _reason_values(result.reason_codes),
        "metadata_only": result.metadata_only,
        "raw_payload_included": result.raw_payload_included,
        "semantic_quality_claim_made": result.semantic_quality_claim_made,
        "full_morphology_claim_made": result.full_morphology_claim_made,
    }


def _manual_review_result(policy: TerminologyPolicy) -> TerminologyMatchResult:
    return _match_result(
        policy=policy,
        status=TerminologyMatchStatus.NEEDS_REVIEW,
        checked=False,
        local_form_match=False,
        forbidden_form_match=False,
        matched_form_kind=None,
        reason_codes=(
            TerminologyPolicyReasonCode.POLICY_MANUAL_REVIEW_REQUIRED,
            TerminologyPolicyReasonCode.NEEDS_HUMAN_REVIEW,
        ),
    )


def _target_missing_result(policy: TerminologyPolicy) -> TerminologyMatchResult:
    return _match_result(
        policy=policy,
        status=TerminologyMatchStatus.NO_MATCH,
        checked=True,
        local_form_match=False,
        forbidden_form_match=False,
        matched_form_kind=None,
        reason_codes=(
            TerminologyPolicyReasonCode.POLICY_TARGET_FORM_MISSING,
            TerminologyPolicyReasonCode.SEMANTIC_TRUTH_NOT_PROVEN,
        ),
    )


def _match_result(
    *,
    policy: TerminologyPolicy,
    status: TerminologyMatchStatus,
    checked: bool,
    local_form_match: bool,
    forbidden_form_match: bool,
    matched_form_kind: str | None,
    reason_codes: Sequence[TerminologyPolicyReasonCode],
) -> TerminologyMatchResult:
    return TerminologyMatchResult(
        policy_id=policy.policy_id if _valid_policy_id(policy.policy_id) else None,
        policy_version=(
            policy.policy_version if _safe_version(policy.policy_version) else None
        ),
        match_mode=_maybe_enum_value(policy.match_mode, TerminologyMatchMode),
        status=status,
        checked=checked,
        local_form_match=local_form_match,
        forbidden_form_match=forbidden_form_match,
        matched_form_kind=matched_form_kind,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _normalization_for_policy(
    policy: TerminologyPolicy,
) -> TerminologyNormalizationMode:
    match_mode = _enum_value(policy.match_mode, TerminologyMatchMode)
    if match_mode is TerminologyMatchMode.EXACT:
        return TerminologyNormalizationMode.NFC
    if match_mode is TerminologyMatchMode.CASEFOLD:
        return TerminologyNormalizationMode.NFC_CASEFOLD
    return _enum_value(policy.normalization_mode, TerminologyNormalizationMode)


def _allowed_forms(
    policy: TerminologyPolicy,
    *,
    target_canonical: str | None,
    target_variants: Iterable[str],
) -> tuple[tuple[str, str], ...]:
    match_mode = _enum_value(policy.match_mode, TerminologyMatchMode)
    if match_mode in (TerminologyMatchMode.EXACT, TerminologyMatchMode.CASEFOLD):
        canonical = _normalize_text(target_canonical, TerminologyNormalizationMode.NFC)
        return ((canonical, "canonical"),) if canonical else ()

    strategy = _enum_value(policy.allowed_variant_strategy, AllowedVariantStrategy)
    if strategy is AllowedVariantStrategy.MANUAL_REVIEW_ONLY:
        return ()

    forms: list[tuple[str, str]] = []
    canonical = _normalize_text(target_canonical, TerminologyNormalizationMode.NFC)
    if canonical:
        forms.append((canonical, "canonical"))
    if strategy is AllowedVariantStrategy.CANONICAL_AND_VARIANTS:
        seen = {canonical} if canonical else set()
        for variant in target_variants:
            normalized = _normalize_text(variant, TerminologyNormalizationMode.NFC)
            if normalized and normalized not in seen:
                forms.append((normalized, "variant"))
                seen.add(normalized)
    return tuple(forms)


def _forbidden_variant_present(
    policy: TerminologyPolicy,
    *,
    translated_text: str,
    forbidden_variants: Iterable[str],
    normalization_mode: TerminologyNormalizationMode,
) -> bool:
    strategy = _enum_value(policy.forbidden_variant_strategy, ForbiddenVariantStrategy)
    if strategy is not ForbiddenVariantStrategy.CONFIGURED_FORBIDDEN_VARIANTS:
        return False
    return any(
        _bounded_literal_present(
            variant,
            translated_text,
            normalization_mode=normalization_mode,
        )
        for variant in forbidden_variants
    )


def _match_reason(
    match_mode: TerminologyMatchMode,
    form_kind: str,
) -> TerminologyPolicyReasonCode:
    if match_mode is TerminologyMatchMode.CASEFOLD:
        return TerminologyPolicyReasonCode.POLICY_CASEFOLD_MATCH
    if form_kind == "variant":
        return TerminologyPolicyReasonCode.POLICY_VARIANT_MATCH
    return TerminologyPolicyReasonCode.POLICY_EXACT_MATCH


def _bounded_literal_present(
    term: str,
    text: str,
    *,
    normalization_mode: TerminologyNormalizationMode,
) -> bool:
    normalized_term = _normalize_text(term, normalization_mode)
    normalized_text = _normalize_text(text, normalization_mode)
    if not normalized_term or not normalized_text:
        return False
    pattern = re.escape(normalized_term)
    if normalized_term[0].isalnum():
        pattern = rf"(?<!\w){pattern}"
    if normalized_term[-1].isalnum():
        pattern = rf"{pattern}(?!\w)"
    return re.search(pattern, normalized_text) is not None


def _normalize_text(
    value: str | None,
    mode: TerminologyNormalizationMode,
) -> str:
    if not isinstance(value, str):
        return ""
    normalized = unicodedata.normalize("NFC", value).strip()
    if mode is TerminologyNormalizationMode.NFC_CASEFOLD:
        normalized = normalized.casefold()
    return normalized


def _validate_enum_field(
    value: StrEnum | str,
    enum_type: type[StrEnum],
    issues: list[TerminologyPolicyValidationIssue],
    path: str,
) -> None:
    try:
        enum_type(value)
    except ValueError:
        _add_validation_issue(
            issues,
            TerminologyPolicyValidationCode.INVALID_ENUM,
            path,
            f"{path} must be a supported enum value.",
        )


def _validate_reason_codes(
    values: Sequence[TerminologyPolicyReasonCode | str],
    issues: list[TerminologyPolicyValidationIssue],
) -> None:
    if not values:
        _add_validation_issue(
            issues,
            TerminologyPolicyValidationCode.MISSING_FIELD,
            "reason_codes",
            "reason_codes must declare metadata-only policy outcomes.",
        )
        return
    seen: set[TerminologyPolicyReasonCode] = set()
    for index, value in enumerate(values):
        path = f"reason_codes[{index}]"
        try:
            reason = TerminologyPolicyReasonCode(value)
        except ValueError:
            _add_validation_issue(
                issues,
                TerminologyPolicyValidationCode.INVALID_REASON_CODE,
                path,
                "reason code must be a known metadata-only code.",
            )
            continue
        if reason in seen:
            _add_validation_issue(
                issues,
                TerminologyPolicyValidationCode.DUPLICATE_REASON_CODE,
                path,
                "reason code must be unique.",
            )
        seen.add(reason)


def _add_validation_issue(
    issues: list[TerminologyPolicyValidationIssue],
    code: TerminologyPolicyValidationCode,
    path: str,
    message: str,
) -> None:
    issues.append(
        TerminologyPolicyValidationIssue(
            code=code,
            path=path,
            message=message,
        )
    )


def _valid_policy_id(value: str) -> bool:
    return isinstance(value, str) and _POLICY_ID_RE.fullmatch(value.strip()) is not None


def _safe_version(value: str) -> bool:
    return (
        isinstance(value, str)
        and _SAFE_VERSION_RE.fullmatch(value.strip()) is not None
    )


def _enum_value(value: StrEnum | str, enum_type: type[StrEnum]) -> Any:
    return enum_type(value)


def _maybe_enum_value(value: StrEnum | str, enum_type: type[StrEnum]) -> Any | None:
    try:
        return enum_type(value)
    except ValueError:
        return None


def _normalize_identifier(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized or None


def _reason_values(
    reason_codes: Sequence[TerminologyPolicyReasonCode],
) -> list[str]:
    return sorted({reason.value for reason in reason_codes})
