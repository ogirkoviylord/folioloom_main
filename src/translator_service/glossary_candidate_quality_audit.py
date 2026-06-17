from __future__ import annotations

import hashlib
import json
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


def audit_prepared_glossary_candidate_quality(
    cases: Sequence[PreparedGlossaryCandidateQualityAuditCase],
) -> dict[str, Any]:
    case_reports = tuple(_audit_case(case) for case in cases)
    totals = _totals(case_reports)
    return {
        "schema_version": GLOSSARY_CANDIDATE_QUALITY_AUDIT_SCHEMA_VERSION,
        "metadata_only": True,
        "raw_payload_included": False,
        "case_count": len(case_reports),
        "totals": totals,
        "cases": list(case_reports),
    }


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
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/sample_book.en.txt"),
            document_kind="txt",
            target_language="ru",
            input_id="sample_book_txt_ru",
        ),
        PreparedGlossaryCandidateQualityAuditCase(
            input_path=Path("test_samples/gutenberg_time_machine_noimages.en.epub"),
            document_kind="epub",
            target_language="ru",
            input_id="gutenberg_time_machine_epub_ru",
        ),
    )


def _audit_case(case: PreparedGlossaryCandidateQualityAuditCase) -> dict[str, Any]:
    content = case.input_path.read_bytes()
    source_sha256 = hashlib.sha256(content).hexdigest()
    provider_called = False

    def provider(provider_request: Any) -> dict[str, Any]:
        nonlocal provider_called
        provider_called = True
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
        "alias_omitted_count": _int_metadata(value.get("alias_omitted_count")),
        "reason_codes": _string_list(value.get("reason_codes")),
    }


def _totals(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    prep_input = 0
    prep_selected = 0
    prep_dropped = 0
    package_selected = 0
    package_dropped = 0
    alias_omitted = 0
    ready_cases = 0
    provider_called = 0
    reason_codes: list[str] = []
    for case in cases:
        prep_quality = case.get("prep_candidate_quality", {})
        package_quality = case.get("package_quality", {})
        prep_input += _int_metadata(prep_quality.get("input_candidate_count"))
        prep_selected += _int_metadata(prep_quality.get("selected_candidate_count"))
        prep_dropped += _int_metadata(prep_quality.get("dropped_candidate_count"))
        package_selected += _int_metadata(
            package_quality.get("selected_candidate_count")
        )
        package_dropped += _int_metadata(
            package_quality.get("dropped_candidate_count")
        )
        alias_omitted += _int_metadata(prep_quality.get("alias_omitted_count"))
        alias_omitted += _int_metadata(package_quality.get("alias_omitted_count"))
        if case.get("attachment_enabled") is True:
            ready_cases += 1
        if case.get("provider_called") is True:
            provider_called += 1
        reason_codes.extend(_string_list(case.get("reason_codes")))
        reason_codes.extend(_string_list(prep_quality.get("reason_codes")))
        reason_codes.extend(_string_list(package_quality.get("reason_codes")))
    return {
        "metadata_only": True,
        "raw_payload_included": False,
        "prep_input_candidate_count": prep_input,
        "prep_selected_candidate_count": prep_selected,
        "prep_dropped_candidate_count": prep_dropped,
        "package_selected_candidate_count": package_selected,
        "package_dropped_candidate_count": package_dropped,
        "alias_omitted_count": alias_omitted,
        "low_value_candidate_rate": _rate(prep_dropped + package_dropped, prep_input),
        "ready_case_count": ready_cases,
        "provider_called_case_count": provider_called,
        "reason_codes": list(dict.fromkeys(reason_codes)),
    }


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
