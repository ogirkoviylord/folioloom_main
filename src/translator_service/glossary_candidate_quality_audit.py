from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.glossary_prepared_prep_service import (
    DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
    PreparedGlossaryPackagePrepRequest,
    PreparedGlossaryPrepService,
)

GLOSSARY_CANDIDATE_QUALITY_AUDIT_SCHEMA_VERSION = (
    "glossary-candidate-quality-audit-v1"
)


@dataclass(frozen=True)
class PreparedGlossaryCandidateQualityAuditCase:
    input_path: Path
    document_kind: str
    target_language: str
    source_language: str = "en"
    translation_mode: str = "book_manuscript"
    input_id: str | None = None
    target_metadata_path: Path | None = None


def audit_prepared_glossary_candidate_quality(
    cases: Sequence[PreparedGlossaryCandidateQualityAuditCase],
) -> dict[str, Any]:
    case_reports = tuple(_audit_case(case) for case in cases)
    totals = _totals(case_reports)
    report = {
        "schema_version": GLOSSARY_CANDIDATE_QUALITY_AUDIT_SCHEMA_VERSION,
        "metadata_only": True,
        "raw_payload_included": False,
        "case_count": len(case_reports),
        "totals": totals,
        "confirmed_counts": _confirmed_counts(totals),
        "unknown_items": _unknown_items(totals),
        "tbd_items": _tbd_items(totals),
        "recommendation": _recommendation(totals),
        "cases": list(case_reports),
    }
    report["ordinary_artifact_safety"] = _ordinary_artifact_safety(report)
    return report


def default_candidate_quality_audit_cases() -> tuple[
    PreparedGlossaryCandidateQualityAuditCase,
    ...,
]:
    return (
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/glossary_adversarial_terms.en.txt"),
            document_kind="txt",
            target_language="ru",
            input_id="glossary_adversarial_terms_txt_ru",
            target_metadata_path=Path(
                "test_samples/glossary_targets/"
                "glossary_adversarial_terms.runtime-glossary-targets.json"
            ),
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/glossary_adversarial_terms.en.txt"),
            document_kind="txt",
            target_language="uk",
            input_id="glossary_adversarial_terms_txt_uk",
            target_metadata_path=Path(
                "test_samples/glossary_targets/"
                "glossary_adversarial_terms.runtime-glossary-targets.json"
            ),
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/sample_book.en.txt"),
            document_kind="txt",
            target_language="ru",
            input_id="sample_book_txt_ru",
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/sample_book.en.docx"),
            document_kind="docx",
            target_language="ru",
            input_id="sample_book_docx_ru",
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/sample_book.en.epub"),
            document_kind="epub",
            target_language="ru",
            input_id="sample_book_epub_ru",
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/russian_profile_regression.en-ru.txt"),
            document_kind="txt",
            target_language="ru",
            input_id="russian_profile_regression_txt_ru",
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/ukrainian_profile_regression.en-uk.txt"),
            document_kind="txt",
            target_language="uk",
            input_id="ukrainian_profile_regression_txt_uk",
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/gutenberg_time_machine_noimages.en.epub"),
            document_kind="epub",
            target_language="ru",
            input_id="gutenberg_time_machine_epub_ru",
            target_metadata_path=Path(
                "test_samples/glossary_targets/"
                "gutenberg_time_machine_noimages.runtime-glossary-targets.json"
            ),
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/gutenberg_time_machine_noimages.en.epub"),
            document_kind="epub",
            target_language="uk",
            input_id="gutenberg_time_machine_epub_uk",
            target_metadata_path=Path(
                "test_samples/glossary_targets/"
                "gutenberg_time_machine_noimages.runtime-glossary-targets.json"
            ),
        ),
    )


def _audit_case(case: PreparedGlossaryCandidateQualityAuditCase) -> dict[str, Any]:
    content = case.input_path.read_bytes()
    source_sha256 = hashlib.sha256(content).hexdigest()
    provider_called = False
    selected_source_digests: set[str] = set()

    def provider(provider_request: Any) -> dict[str, Any]:
        nonlocal provider_called
        provider_called = True
        selected_source_digests.update(
            _candidate_source_digests(provider_request.packet)
        )
        return _fake_package_from_packet(provider_request.packet)

    request = PreparedGlossaryPackagePrepRequest(
        user_telegram_id=0,
        file_name=case.input_path.name,
        document_kind=case.document_kind,
        source_language=case.source_language,
        target_language=case.target_language,
        translation_mode=case.translation_mode,
        glossary_mode="with_glossary",
        source_sha256=source_sha256,
        content=content,
    )
    attachment = PreparedGlossaryPrepService(provider=provider).prepare(request)
    metadata = dict(attachment.metadata)
    candidate_quality = _quality_summary(metadata.get("candidate_quality"))
    validation = metadata.get("validation")
    validation_metadata = dict(validation) if isinstance(validation, Mapping) else {}
    package_quality = _quality_summary(validation_metadata.get("quality"))
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "input_id": case.input_id or case.input_path.name,
        "document_kind": case.document_kind,
        "source_language": case.source_language,
        "target_language": case.target_language,
        "source_sha256_short": source_sha256[:12],
        "prep_status": metadata.get("status", "Unknown"),
        "attachment_enabled": bool(attachment.enabled),
        "provider_called": provider_called,
        "reason_codes": list(attachment.reason_codes),
        "selected_candidate_count": _int_metadata(
            metadata.get("selected_candidate_count")
        ),
        "prep_candidate_quality": candidate_quality,
        "package_validation_status": validation_metadata.get("status", "not_run"),
        "package_quality": package_quality,
        "target_metadata": _target_metadata_summary(
            case.target_metadata_path,
            target_language=case.target_language,
            selected_source_digests=selected_source_digests,
        ),
    }


def _fake_package_from_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    target_language = str(packet.get("target_language") or "Unknown")
    entries = []
    for index, candidate in enumerate(packet.get("candidates", ())):
        if not isinstance(candidate, Mapping):
            continue
        target = f"audit-target-{index + 1}"
        entries.append(
            {
                "source_entry_id": candidate.get("source_entry_id", "Unknown"),
                "source_canonical": candidate.get("source_canonical", "Unknown"),
                "aliases": list(candidate.get("aliases", ())),
                "evidence_refs": list(candidate.get("evidence_refs", ())),
                "source_unit_refs": list(candidate.get("source_unit_refs", ())),
                "source_block_refs": list(candidate.get("source_block_refs", ())),
                "target_canonical": target,
                "target_variants": [target],
                "forbidden_variants": [],
                "strategy": "metadata_only_audit_fake_provider",
                "confidence": 0.9,
                "needs_review": False,
                "reason_codes": [],
            }
        )
    return {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": f"prepared:audit:{target_language}",
        "source_language": packet.get("source_language", "Unknown"),
        "target_language": target_language,
        "glossary_mode": "with_glossary",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": packet.get(
            "provider_model",
            DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
        ),
        "provider_run_id": "provider-run:audit-fake",
        "source_document_fingerprint": packet.get(
            "source_document_fingerprint",
            "Unknown",
        ),
        "candidate_selector_signature": packet.get(
            "candidate_selector_signature",
            "Unknown",
        ),
        "owner_approved": True,
        "entries": entries,
    }


def _quality_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "metadata_only": True,
            "raw_payload_included": False,
            "status": "not_run",
            "input_candidate_count": 0,
            "selected_candidate_count": 0,
            "dropped_candidate_count": 0,
            "omitted_candidate_count": 0,
            "alias_omitted_count": 0,
            "reason_codes": [],
        }
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "status": "ran",
        "policy_version": str(value.get("policy_version", "Unknown")),
        "input_candidate_count": _int_metadata(value.get("input_candidate_count")),
        "selected_candidate_count": _int_metadata(
            value.get("selected_candidate_count")
        ),
        "dropped_candidate_count": _int_metadata(
            value.get("dropped_candidate_count")
        ),
        "omitted_candidate_count": _int_metadata(
            value.get("omitted_candidate_count")
        ),
        "alias_omitted_count": _int_metadata(value.get("alias_omitted_count")),
        "reason_codes": _string_list(value.get("reason_codes")),
    }


def _totals(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    prep_input = 0
    prep_selected = 0
    prep_dropped = 0
    prep_omitted = 0
    package_selected = 0
    package_dropped = 0
    package_omitted = 0
    alias_omitted = 0
    ready_cases = 0
    provider_called = 0
    package_ready = 0
    package_needs_review = 0
    package_invalid = 0
    package_not_run = 0
    target_metadata_checked = 0
    target_metadata_not_configured = 0
    expected_durable = 0
    selected_expected_durable = 0
    suspected_missing_durable = 0
    reason_codes: list[str] = []
    for case in cases:
        prep_quality = case.get("prep_candidate_quality", {})
        package_quality = case.get("package_quality", {})
        target_metadata = case.get("target_metadata", {})
        prep_input += _int_metadata(prep_quality.get("input_candidate_count"))
        prep_selected += _int_metadata(prep_quality.get("selected_candidate_count"))
        prep_dropped += _int_metadata(prep_quality.get("dropped_candidate_count"))
        prep_omitted += _int_metadata(prep_quality.get("omitted_candidate_count"))
        package_selected += _int_metadata(
            package_quality.get("selected_candidate_count")
        )
        package_dropped += _int_metadata(
            package_quality.get("dropped_candidate_count")
        )
        package_omitted += _int_metadata(
            package_quality.get("omitted_candidate_count")
        )
        alias_omitted += _int_metadata(prep_quality.get("alias_omitted_count"))
        alias_omitted += _int_metadata(package_quality.get("alias_omitted_count"))
        if case.get("attachment_enabled") is True:
            ready_cases += 1
        if case.get("provider_called") is True:
            provider_called += 1
        status = case.get("package_validation_status")
        if status == "ready":
            package_ready += 1
        elif status == "needs_review":
            package_needs_review += 1
        elif status == "invalid":
            package_invalid += 1
        elif status == "not_run":
            package_not_run += 1
        if target_metadata.get("status") == "checked":
            target_metadata_checked += 1
        if target_metadata.get("status") == "not_configured":
            target_metadata_not_configured += 1
        expected_durable += _int_metadata(
            target_metadata.get("expected_durable_candidate_count")
        )
        selected_expected_durable += _int_metadata(
            target_metadata.get("selected_expected_durable_candidate_count")
        )
        suspected_missing_durable += _int_metadata(
            target_metadata.get("suspected_missing_durable_candidate_count")
        )
        reason_codes.extend(_string_list(case.get("reason_codes")))
        reason_codes.extend(_string_list(prep_quality.get("reason_codes")))
        reason_codes.extend(_string_list(package_quality.get("reason_codes")))
        reason_codes.extend(_string_list(target_metadata.get("reason_codes")))
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "prep_input_candidate_count": prep_input,
        "prep_selected_candidate_count": prep_selected,
        "prep_dropped_candidate_count": prep_dropped,
        "prep_omitted_candidate_count": prep_omitted,
        "package_selected_candidate_count": package_selected,
        "package_dropped_candidate_count": package_dropped,
        "package_omitted_candidate_count": package_omitted,
        "alias_omitted_count": alias_omitted,
        "low_value_candidate_rate": _rate(prep_dropped + package_dropped, prep_input),
        "ready_case_count": ready_cases,
        "provider_called_case_count": provider_called,
        "package_ready_case_count": package_ready,
        "package_needs_review_case_count": package_needs_review,
        "package_invalid_case_count": package_invalid,
        "package_not_run_case_count": package_not_run,
        "target_metadata_checked_case_count": target_metadata_checked,
        "target_metadata_not_configured_case_count": target_metadata_not_configured,
        "expected_durable_candidate_count": expected_durable,
        "selected_expected_durable_candidate_count": selected_expected_durable,
        "suspected_missing_durable_candidate_count": suspected_missing_durable,
        "reason_codes": list(dict.fromkeys(reason_codes)),
    }


def _candidate_source_digests(packet: Mapping[str, Any]) -> set[str]:
    candidates = packet.get("candidates", ())
    if not isinstance(candidates, Sequence) or isinstance(
        candidates,
        (str, bytes, bytearray),
    ):
        return set()
    digests: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        for term in _candidate_terms(candidate):
            digests.add(_term_digest(term))
    return digests


def _candidate_terms(candidate: Mapping[str, Any]) -> tuple[str, ...]:
    terms: list[str] = []
    source = candidate.get("source_canonical")
    if isinstance(source, str) and source.strip():
        terms.append(source.strip())
    aliases = candidate.get("aliases", ())
    if isinstance(aliases, Sequence) and not isinstance(
        aliases,
        (str, bytes, bytearray),
    ):
        terms.extend(str(alias).strip() for alias in aliases if isinstance(alias, str))
    return tuple(term for term in terms if term)


def _target_metadata_summary(
    path: Path | None,
    *,
    target_language: str,
    selected_source_digests: set[str],
) -> dict[str, Any]:
    if path is None:
        return {
            "metadata_only": True,
            "raw_payload_included": False,
            "status": "not_configured",
            "detection_status": "Unknown",
            "expected_durable_candidate_count": 0,
            "selected_expected_durable_candidate_count": 0,
            "suspected_missing_durable_candidate_count": 0,
            "reason_codes": ["target_metadata_not_configured"],
        }
    if not path.exists():
        return _target_metadata_unavailable("target_metadata_missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _target_metadata_unavailable("target_metadata_invalid")
    if not isinstance(payload, Mapping):
        return _target_metadata_unavailable("target_metadata_invalid")
    targets = payload.get("targets")
    if not isinstance(targets, Mapping):
        return _target_metadata_unavailable("target_metadata_targets_invalid")
    target_payload = targets.get(target_language)
    if not isinstance(target_payload, Mapping):
        return _target_metadata_unavailable("target_metadata_target_missing")
    entries = target_payload.get("entries")
    if not isinstance(entries, Sequence) or isinstance(
        entries,
        (str, bytes, bytearray),
    ):
        return _target_metadata_unavailable("target_metadata_entries_invalid")
    expected_term_sets = tuple(
        term_set
        for entry in entries
        if isinstance(entry, Mapping)
        for term_set in (_target_metadata_entry_term_digests(entry),)
        if term_set
    )
    selected_count = sum(
        1 for term_set in expected_term_sets if term_set & selected_source_digests
    )
    missing_count = max(0, len(expected_term_sets) - selected_count)
    reason_codes = []
    if missing_count:
        reason_codes.append("target_metadata_suspected_missing_durable_candidate")
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "status": "checked",
        "detection_status": "confirmed",
        "target_metadata_sha256_short": hashlib.sha256(
            path.read_bytes()
        ).hexdigest()[:12],
        "expected_durable_candidate_count": len(expected_term_sets),
        "selected_expected_durable_candidate_count": selected_count,
        "suspected_missing_durable_candidate_count": missing_count,
        "reason_codes": reason_codes,
    }


def _target_metadata_unavailable(reason_code: str) -> dict[str, Any]:
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "status": "unavailable",
        "detection_status": "Unknown",
        "expected_durable_candidate_count": 0,
        "selected_expected_durable_candidate_count": 0,
        "suspected_missing_durable_candidate_count": 0,
        "reason_codes": [reason_code],
    }


def _target_metadata_entry_term_digests(entry: Mapping[str, Any]) -> frozenset[str]:
    terms: list[str] = []
    source = entry.get("source_canonical")
    if isinstance(source, str) and source.strip():
        terms.append(source.strip())
    aliases = entry.get("aliases", ())
    if isinstance(aliases, Sequence) and not isinstance(
        aliases,
        (str, bytes, bytearray),
    ):
        terms.extend(str(alias).strip() for alias in aliases if isinstance(alias, str))
    return frozenset(_term_digest(term) for term in terms if term)


def _term_digest(term: str) -> str:
    return hashlib.sha256(term.casefold().encode("utf-8")).hexdigest()[:16]


def _confirmed_counts(totals: Mapping[str, Any]) -> dict[str, int | float | bool]:
    keys = (
        "prep_input_candidate_count",
        "prep_selected_candidate_count",
        "prep_dropped_candidate_count",
        "prep_omitted_candidate_count",
        "package_selected_candidate_count",
        "package_dropped_candidate_count",
        "package_omitted_candidate_count",
        "alias_omitted_count",
        "low_value_candidate_rate",
        "package_ready_case_count",
        "package_needs_review_case_count",
        "package_invalid_case_count",
        "target_metadata_checked_case_count",
        "expected_durable_candidate_count",
        "selected_expected_durable_candidate_count",
        "suspected_missing_durable_candidate_count",
    )
    confirmed: dict[str, int | float | bool] = {
        "metadata_only": True,
        "raw_payload_included": False,
    }
    for key in keys:
        value = totals.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            confirmed[key] = value
    return confirmed


def _unknown_items(totals: Mapping[str, Any]) -> list[str]:
    unknowns = [
        "real_provider_behavior",
        "real_book_translation_quality",
        "semantic_or_literary_glossary_quality",
    ]
    if _int_metadata(totals.get("target_metadata_not_configured_case_count")):
        unknowns.append("durable_candidate_coverage_for_cases_without_target_metadata")
    if _int_metadata(totals.get("suspected_missing_durable_candidate_count")):
        unknowns.append("scanner_vs_reducer_attribution_for_missing_candidates")
    return unknowns


def _tbd_items(totals: Mapping[str, Any]) -> list[str]:
    if _int_metadata(totals.get("suspected_missing_durable_candidate_count")):
        return [
            "whether_reducer_scoring_should_change_under_issue_690",
            "whether_scanner_v2_shadow_evaluation_is_warranted_under_issue_692",
        ]
    return ["whether_broader_authorized_fixtures_change_the_result"]


def _recommendation(totals: Mapping[str, Any]) -> dict[str, Any]:
    missing_durable = _int_metadata(
        totals.get("suspected_missing_durable_candidate_count")
    )
    package_dropped = _int_metadata(totals.get("package_dropped_candidate_count"))
    package_needs_review = _int_metadata(totals.get("package_needs_review_case_count"))
    package_invalid = _int_metadata(totals.get("package_invalid_case_count"))
    if missing_durable:
        return {
            "metadata_only": True,
            "raw_payload_included": False,
            "primary_recommendation": "reducer_tuning",
            "reason_codes": [
                "target_metadata_suspected_missing_durable_candidate",
                "scanner_vs_reducer_attribution_unknown",
            ],
            "summary": (
                "Run #690-style reducer attribution before deciding whether "
                "scanner-v2 shadow evaluation is warranted."
            ),
        }
    if package_dropped or package_needs_review or package_invalid:
        return {
            "metadata_only": True,
            "raw_payload_included": False,
            "primary_recommendation": "provider_boundary_tuning",
            "reason_codes": ["package_quality_or_status_needs_follow_up"],
            "summary": "Review package/provider adjudication before scanner changes.",
        }
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "primary_recommendation": "no_tuning",
        "reason_codes": ["current_local_gates_stable_in_audit"],
        "summary": (
            "No candidate-policy/provider-boundary tuning indicated by this audit."
        ),
    }


_UNSAFE_METADATA_KEY_ALIASES = frozenset(
    re.sub(r"[^a-z0-9]+", "", key)
    for key in {
        "api_key",
        "auth_material",
        "authorization",
        "bounded_source_excerpt",
        "excerpt",
        "message",
        "messages",
        "passage",
        "passage_text",
        "prompt",
        "prompt_body",
        "prompt_messages",
        "provider_request",
        "provider_response",
        "raw_excerpt",
        "raw_output",
        "raw_passage",
        "raw_passages",
        "raw_prompt",
        "raw_provider_response",
        "raw_source",
        "raw_source_text",
        "request_body",
        "response_body",
        "source_canonical",
        "source_excerpt",
        "source_passage",
        "source_text",
        "target_text",
        "translated_text",
        "translation",
        "translation_text",
    }
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE),
    re.compile(r"Authorization\s*:", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[A-Z0-9_]*(API_KEY|TOKEN|PASSWORD|SECRET|DSN)\s*="),
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
)


def _ordinary_artifact_safety(report: Mapping[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    unsafe_key_match_count = _unsafe_key_match_count(report)
    secret_pattern_match_count = sum(
        1 for pattern in _SECRET_VALUE_PATTERNS if pattern.search(serialized)
    )
    status = (
        "passed"
        if unsafe_key_match_count == 0 and secret_pattern_match_count == 0
        else "failed"
    )
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "status": status,
        "unsafe_key_match_count": unsafe_key_match_count,
        "secret_pattern_match_count": secret_pattern_match_count,
        "checked_unsafe_key_family_count": len(_UNSAFE_METADATA_KEY_ALIASES),
        "checked_secret_pattern_family_count": len(_SECRET_VALUE_PATTERNS),
    }


def _unsafe_key_match_count(value: Any) -> int:
    if isinstance(value, Mapping):
        count = 0
        for key, item in value.items():
            alias = re.sub(r"[^a-z0-9]+", "", str(key).casefold())
            if alias in _UNSAFE_METADATA_KEY_ALIASES:
                count += 1
            count += _unsafe_key_match_count(item)
        return count
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_unsafe_key_match_count(item) for item in value)
    return 0


def _int_metadata(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    return 0


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def serialize_candidate_quality_audit(report: Mapping[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
