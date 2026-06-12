from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.book_profile import (
    BookProfileDetection,
    BookProfileKind,
)
from translator_service.glossary_contracts import (
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
)
from translator_service.translation_contract_snapshot import (
    book_profile_detection_signature,
)

BOOK_PROFILE_SANITY_GATE_VERSION = "book-profile-sanity-v1"
BOOK_PROFILE_SANITY_RU_UK_MORPHOLOGY_STATUS = "TBD"


class BookProfileSanityRoute(StrEnum):
    PROFILE_ACCEPTED = "profile_accepted"
    PROFILE_NEEDS_REVIEW = "profile_needs_review"
    MIXED_NEEDS_REVIEW = "mixed_needs_review"


class BookProfileSanitySeverity(StrEnum):
    WARNING = "warning"
    BLOCKER = "blocker"


class BookProfileSanityReason(StrEnum):
    STRONG_SECONDARY_PROFILES = "strong_secondary_profiles"
    HIGH_CONFIDENCE_CONFLICTING_EVIDENCE = "high_confidence_conflicting_evidence"
    FRONTMATTER_OR_NAV_DOMINATED = "frontmatter_or_nav_dominated"
    LOW_EVIDENCE_COUNT = "low_evidence_count"
    MIXED_OR_UNKNOWN_PRIMARY = "mixed_or_unknown_primary"
    EXISTING_UNCERTAINTY_MARKERS = "existing_uncertainty_markers"
    REVIEW_REQUIRED_RULE = "review_required_rule"
    PRESSURE_CONTEXT_REVIEW_FLAG = "pressure_context_review_flag"


@dataclass(frozen=True)
class BookProfileSanityFinding:
    reason: BookProfileSanityReason
    severity: BookProfileSanitySeverity
    evidence_refs: tuple[str, ...]
    evidence_count: int
    primary_profile: str
    related_profiles: tuple[str, ...] = ()
    metadata: Mapping[str, int | str | float | bool] | None = None


@dataclass(frozen=True)
class BookProfileSanityResult:
    gate_version: str
    profile_signature: str
    pressure_signature: str
    sanity_signature: str
    recommended_route: BookProfileSanityRoute
    original_primary_profile: str
    original_confidence: float
    morphology_status: str
    findings: tuple[BookProfileSanityFinding, ...]

    @property
    def blocker_count(self) -> int:
        return sum(
            1
            for finding in self.findings
            if finding.severity is BookProfileSanitySeverity.BLOCKER
        )

    @property
    def warning_count(self) -> int:
        return sum(
            1
            for finding in self.findings
            if finding.severity is BookProfileSanitySeverity.WARNING
        )


def check_book_profile_sanity(
    detection: BookProfileDetection,
    *,
    pressure_signals: Mapping[str, Any] | None = None,
    min_evidence_refs: int = 2,
) -> BookProfileSanityResult:
    """Return metadata-only sanity findings for a local book profile detection."""

    if min_evidence_refs < 0:
        raise ValueError("min_evidence_refs must be non-negative.")

    profile = detection.profile
    primary_profile = _profile_value(profile.primary_profile)
    confidence = _confidence(profile.confidence)
    secondary_profiles = tuple(
        sorted(_profile_value(item) for item in profile.secondary_profiles)
    )
    pressure_signature = _pressure_signature(pressure_signals)
    evidence_by_id = {
        evidence.evidence_id: evidence for evidence in detection.evidence
    }
    profile_evidence = tuple(
        evidence_by_id[evidence_ref]
        for evidence_ref in profile.evidence_refs
        if evidence_ref in evidence_by_id
    )
    evidence_refs = tuple(sorted(str(ref) for ref in profile.evidence_refs))
    frontmatter_count = _frontmatter_evidence_count(profile_evidence)
    frontmatter_ratio = (
        frontmatter_count / len(profile_evidence) if profile_evidence else 0.0
    )

    findings: list[BookProfileSanityFinding] = []
    _append_mixed_or_unknown_finding(
        findings,
        primary_profile=primary_profile,
        confidence=confidence,
        evidence_refs=evidence_refs,
        secondary_profiles=secondary_profiles,
    )
    _append_secondary_finding(
        findings,
        primary_profile=primary_profile,
        confidence=confidence,
        evidence_refs=evidence_refs,
        secondary_profiles=secondary_profiles,
        pressure_signals=pressure_signals,
    )
    _append_frontmatter_finding(
        findings,
        primary_profile=primary_profile,
        confidence=confidence,
        evidence_refs=evidence_refs,
        secondary_profiles=secondary_profiles,
        frontmatter_count=frontmatter_count,
        frontmatter_ratio=frontmatter_ratio,
    )
    _append_low_evidence_finding(
        findings,
        primary_profile=primary_profile,
        evidence_refs=evidence_refs,
        min_evidence_refs=min_evidence_refs,
    )
    _append_uncertainty_finding(
        findings,
        primary_profile=primary_profile,
        evidence_refs=evidence_refs,
        uncertainty_notes=profile.uncertainty_notes,
    )
    _append_review_rule_finding(
        findings,
        primary_profile=primary_profile,
        rules_require_review=any(rule.requires_review for rule in detection.rules),
        evidence_refs=evidence_refs,
    )
    _append_pressure_review_finding(
        findings,
        primary_profile=primary_profile,
        evidence_refs=evidence_refs,
        pressure_signals=pressure_signals,
    )

    sorted_findings = tuple(sorted(findings, key=_finding_sort_key))
    payload = _sanity_payload(
        gate_version=BOOK_PROFILE_SANITY_GATE_VERSION,
        profile_signature=book_profile_detection_signature(detection),
        pressure_signature=pressure_signature,
        recommended_route=_recommended_route(sorted_findings),
        original_primary_profile=primary_profile,
        original_confidence=confidence,
        morphology_status=_morphology_status(profile.target_language),
        findings=sorted_findings,
    )
    return BookProfileSanityResult(
        gate_version=BOOK_PROFILE_SANITY_GATE_VERSION,
        profile_signature=payload["profile_signature"],
        pressure_signature=pressure_signature,
        sanity_signature=f"book-profile-sanity:v1:{_payload_digest(payload)}",
        recommended_route=BookProfileSanityRoute(payload["recommended_route"]),
        original_primary_profile=primary_profile,
        original_confidence=confidence,
        morphology_status=str(payload["morphology_status"]),
        findings=sorted_findings,
    )


def book_profile_sanity_payload(result: BookProfileSanityResult) -> dict[str, Any]:
    return {
        **_sanity_payload(
            gate_version=result.gate_version,
            profile_signature=result.profile_signature,
            pressure_signature=result.pressure_signature,
            recommended_route=result.recommended_route,
            original_primary_profile=result.original_primary_profile,
            original_confidence=result.original_confidence,
            morphology_status=result.morphology_status,
            findings=result.findings,
        ),
        "sanity_signature": result.sanity_signature,
    }


def serialize_book_profile_sanity(result: BookProfileSanityResult) -> str:
    return json.dumps(
        book_profile_sanity_payload(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _append_mixed_or_unknown_finding(
    findings: list[BookProfileSanityFinding],
    *,
    primary_profile: str,
    confidence: float,
    evidence_refs: tuple[str, ...],
    secondary_profiles: tuple[str, ...],
) -> None:
    if primary_profile not in {
        BookProfileKind.MIXED_UNKNOWN.value,
        BookProfileKind.UNKNOWN.value,
    }:
        return
    severity = (
        BookProfileSanitySeverity.BLOCKER
        if primary_profile == BookProfileKind.MIXED_UNKNOWN.value
        else BookProfileSanitySeverity.WARNING
    )
    findings.append(
        _finding(
            BookProfileSanityReason.MIXED_OR_UNKNOWN_PRIMARY,
            severity,
            primary_profile=primary_profile,
            evidence_refs=evidence_refs,
            related_profiles=secondary_profiles,
            metadata={"confidence": confidence},
        )
    )


def _append_secondary_finding(
    findings: list[BookProfileSanityFinding],
    *,
    primary_profile: str,
    confidence: float,
    evidence_refs: tuple[str, ...],
    secondary_profiles: tuple[str, ...],
    pressure_signals: Mapping[str, Any] | None,
) -> None:
    pressure_secondary_count = _signal_int(pressure_signals, "secondary_profile_count")
    secondary_count = max(len(secondary_profiles), pressure_secondary_count or 0)
    if secondary_count < 2:
        return
    severity = (
        BookProfileSanitySeverity.BLOCKER
        if confidence >= 0.82
        and _has_conflicting_profile(primary_profile, secondary_profiles)
        else BookProfileSanitySeverity.WARNING
    )
    findings.append(
        _finding(
            BookProfileSanityReason.STRONG_SECONDARY_PROFILES,
            severity,
            primary_profile=primary_profile,
            evidence_refs=evidence_refs,
            related_profiles=secondary_profiles,
            metadata={
                "confidence": confidence,
                "secondary_profile_count": secondary_count,
            },
        )
    )


def _append_frontmatter_finding(
    findings: list[BookProfileSanityFinding],
    *,
    primary_profile: str,
    confidence: float,
    evidence_refs: tuple[str, ...],
    secondary_profiles: tuple[str, ...],
    frontmatter_count: int,
    frontmatter_ratio: float,
) -> None:
    if frontmatter_count <= 0 or frontmatter_ratio < 0.5:
        return
    severity = BookProfileSanitySeverity.WARNING
    if (
        confidence >= 0.75
        and primary_profile == BookProfileKind.BUSINESS_LEGAL_LIKE.value
        and _has_bookish_secondary(secondary_profiles)
    ):
        severity = BookProfileSanitySeverity.BLOCKER
        findings.append(
            _finding(
                BookProfileSanityReason.HIGH_CONFIDENCE_CONFLICTING_EVIDENCE,
                severity,
                primary_profile=primary_profile,
                evidence_refs=evidence_refs,
                related_profiles=secondary_profiles,
                metadata={
                    "confidence": confidence,
                    "frontmatter_evidence_count": frontmatter_count,
                },
            )
        )
    findings.append(
        _finding(
            BookProfileSanityReason.FRONTMATTER_OR_NAV_DOMINATED,
            severity,
            primary_profile=primary_profile,
            evidence_refs=evidence_refs,
            related_profiles=secondary_profiles,
            metadata={
                "frontmatter_evidence_count": frontmatter_count,
                "frontmatter_ratio": round(frontmatter_ratio, 4),
            },
        )
    )


def _append_low_evidence_finding(
    findings: list[BookProfileSanityFinding],
    *,
    primary_profile: str,
    evidence_refs: tuple[str, ...],
    min_evidence_refs: int,
) -> None:
    if len(evidence_refs) >= min_evidence_refs:
        return
    findings.append(
        _finding(
            BookProfileSanityReason.LOW_EVIDENCE_COUNT,
            BookProfileSanitySeverity.WARNING,
            primary_profile=primary_profile,
            evidence_refs=evidence_refs,
            metadata={
                "evidence_count": len(evidence_refs),
                "min_evidence_refs": min_evidence_refs,
            },
        )
    )


def _append_uncertainty_finding(
    findings: list[BookProfileSanityFinding],
    *,
    primary_profile: str,
    evidence_refs: tuple[str, ...],
    uncertainty_notes: Sequence[str],
) -> None:
    actionable_notes = tuple(
        sorted(
            str(note)
            for note in uncertainty_notes
            if str(note) != "ru_uk_morphology_tbd"
        )
    )
    if not actionable_notes:
        return
    findings.append(
        _finding(
            BookProfileSanityReason.EXISTING_UNCERTAINTY_MARKERS,
            BookProfileSanitySeverity.WARNING,
            primary_profile=primary_profile,
            evidence_refs=evidence_refs,
            metadata={"uncertainty_marker_count": len(actionable_notes)},
        )
    )


def _append_review_rule_finding(
    findings: list[BookProfileSanityFinding],
    *,
    primary_profile: str,
    rules_require_review: bool,
    evidence_refs: tuple[str, ...],
) -> None:
    if not rules_require_review:
        return
    findings.append(
        _finding(
            BookProfileSanityReason.REVIEW_REQUIRED_RULE,
            BookProfileSanitySeverity.WARNING,
            primary_profile=primary_profile,
            evidence_refs=evidence_refs,
            metadata={"rules_require_review": True},
        )
    )


def _append_pressure_review_finding(
    findings: list[BookProfileSanityFinding],
    *,
    primary_profile: str,
    evidence_refs: tuple[str, ...],
    pressure_signals: Mapping[str, Any] | None,
) -> None:
    if not _signal_bool(pressure_signals, "profile_needs_review"):
        return
    findings.append(
        _finding(
            BookProfileSanityReason.PRESSURE_CONTEXT_REVIEW_FLAG,
            BookProfileSanitySeverity.WARNING,
            primary_profile=primary_profile,
            evidence_refs=evidence_refs,
            metadata={"profile_needs_review": True},
        )
    )


def _recommended_route(
    findings: Sequence[BookProfileSanityFinding],
) -> BookProfileSanityRoute:
    if any(
        finding.severity is BookProfileSanitySeverity.BLOCKER for finding in findings
    ):
        return BookProfileSanityRoute.MIXED_NEEDS_REVIEW
    if findings:
        return BookProfileSanityRoute.PROFILE_NEEDS_REVIEW
    return BookProfileSanityRoute.PROFILE_ACCEPTED


def _sanity_payload(
    *,
    gate_version: str,
    profile_signature: str,
    pressure_signature: str,
    recommended_route: BookProfileSanityRoute | str,
    original_primary_profile: str,
    original_confidence: float,
    morphology_status: str,
    findings: Sequence[BookProfileSanityFinding],
) -> dict[str, Any]:
    severity_counts = {
        severity.value: sum(1 for finding in findings if finding.severity is severity)
        for severity in BookProfileSanitySeverity
    }
    return {
        "gate_version": gate_version,
        "profile_signature": profile_signature,
        "pressure_signature": pressure_signature,
        "recommended_route": _enum_value(recommended_route),
        "original_primary_profile": original_primary_profile,
        "original_confidence": round(original_confidence, 4),
        "morphology_status": morphology_status,
        "finding_count": len(findings),
        "severity_counts": severity_counts,
        "findings": [_finding_payload(finding) for finding in findings],
    }


def _finding_payload(finding: BookProfileSanityFinding) -> dict[str, Any]:
    return {
        "reason": finding.reason.value,
        "severity": finding.severity.value,
        "evidence_refs": list(finding.evidence_refs),
        "evidence_count": finding.evidence_count,
        "primary_profile": finding.primary_profile,
        "related_profiles": list(finding.related_profiles),
        "metadata": dict(sorted((finding.metadata or {}).items())),
    }


def _finding(
    reason: BookProfileSanityReason,
    severity: BookProfileSanitySeverity,
    *,
    primary_profile: str,
    evidence_refs: tuple[str, ...],
    related_profiles: tuple[str, ...] = (),
    metadata: Mapping[str, int | str | float | bool] | None = None,
) -> BookProfileSanityFinding:
    return BookProfileSanityFinding(
        reason=reason,
        severity=severity,
        evidence_refs=evidence_refs,
        evidence_count=len(evidence_refs),
        primary_profile=primary_profile,
        related_profiles=related_profiles,
        metadata=dict(metadata or {}),
    )


def _finding_sort_key(
    finding: BookProfileSanityFinding,
) -> tuple[int, str, str, tuple[str, ...]]:
    severity_rank = 0 if finding.severity is BookProfileSanitySeverity.BLOCKER else 1
    return (
        severity_rank,
        finding.reason.value,
        finding.primary_profile,
        finding.evidence_refs,
    )


def _frontmatter_evidence_count(evidence: Sequence[GlossaryEvidenceRef]) -> int:
    return sum(1 for item in evidence if _is_frontmatter_or_nav(item))


def _is_frontmatter_or_nav(evidence: GlossaryEvidenceRef) -> bool:
    surface = _enum_value(evidence.surface)
    source_scope = evidence.source_scope.casefold()
    return surface in {
        GlossaryEvidenceSurface.NAV.value,
        GlossaryEvidenceSurface.TOC.value,
        GlossaryEvidenceSurface.METADATA.value,
    } or any(
        marker in source_scope
        for marker in ("frontmatter", "toc", "nav", "cover", "titlepage", "metadata")
    )


def _has_conflicting_profile(
    primary_profile: str,
    secondary_profiles: Sequence[str],
) -> bool:
    if primary_profile in _FACTUAL_OR_OPERATIONAL_PROFILES:
        return any(profile in _BOOKISH_PROFILES for profile in secondary_profiles)
    if primary_profile in _BOOKISH_PROFILES:
        return any(
            profile in _FACTUAL_OR_OPERATIONAL_PROFILES
            for profile in secondary_profiles
        )
    return False


def _has_bookish_secondary(secondary_profiles: Sequence[str]) -> bool:
    return any(profile in _BOOKISH_PROFILES for profile in secondary_profiles)


_BOOKISH_PROFILES = {
    BookProfileKind.LITERARY_FICTION.value,
    BookProfileKind.LITERARY_NON_FICTION.value,
    BookProfileKind.RELIGIOUS_PHILOSOPHICAL.value,
    BookProfileKind.HISTORICAL.value,
    BookProfileKind.MEMOIR.value,
}

_FACTUAL_OR_OPERATIONAL_PROFILES = {
    BookProfileKind.BUSINESS_LEGAL_LIKE.value,
    BookProfileKind.SCIENTIFIC_ACADEMIC.value,
    BookProfileKind.TECHNICAL.value,
    BookProfileKind.MARKETING.value,
}


def _morphology_status(target_language: str) -> str:
    if _language_root(target_language) in {"ru", "uk"}:
        return BOOK_PROFILE_SANITY_RU_UK_MORPHOLOGY_STATUS
    return "not_applicable"


def _pressure_signature(pressure_signals: Mapping[str, Any] | None) -> str:
    if not pressure_signals:
        return "book-profile-pressure:none"
    pressure_digest = _payload_digest(_metadata_digest_payload(pressure_signals))
    return f"book-profile-pressure:v1:{pressure_digest}"


def _metadata_digest_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _metadata_digest_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_metadata_digest_payload(item) for item in value]
    if isinstance(value, set):
        return sorted(_metadata_digest_payload(item) for item in value)
    if isinstance(value, str):
        return {"text_digest": _text_digest(value), "text_char_count": len(value)}
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return f"{value:.6f}" if math.isfinite(value) else str(value)
    return {"repr_digest": _text_digest(repr(value)), "type": type(value).__name__}


def _signal_int(
    pressure_signals: Mapping[str, Any] | None,
    key: str,
) -> int | None:
    if not pressure_signals or key not in pressure_signals:
        return None
    value = pressure_signals[key]
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _signal_bool(
    pressure_signals: Mapping[str, Any] | None,
    key: str,
) -> bool:
    return bool(pressure_signals and pressure_signals.get(key) is True)


def _profile_value(value: Any) -> str:
    if isinstance(value, BookProfileKind):
        return value.value
    return str(value)


def _confidence(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(float(value)):
            return min(1.0, max(0.0, float(value)))
    return 0.0


def _language_root(language: str) -> str:
    return language.strip().lower().split("-", 1)[0].split("_", 1)[0]


def _enum_value(value: Any) -> str:
    if isinstance(value, StrEnum):
        return value.value
    return str(value)


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _payload_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
