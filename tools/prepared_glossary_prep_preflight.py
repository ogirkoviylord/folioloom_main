from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from translator_service.book_profile import detect_book_profile
from translator_service.format_adapters.epub import plan_epub_translation
from translator_service.glossary_candidate_reducer import (
    GlossaryCandidateDecisionStatus,
    GlossaryCandidateReducerCaps,
    glossary_candidate_reduction_payload,
    reduce_glossary_candidates,
)
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
    validate_prepared_glossary_package,
)
from translator_service.glossary_scanner import scan_glossary_candidates

ISSUE_619_SCHEMA_VERSION = "prepared-glossary-pro-prep-preflight-v1"
DEFAULT_PROVIDER_MODEL = "deepseek-v4-pro"
APPROVED_INPUT = Path("test_samples/gutenberg_time_machine_noimages.en.epub")
APPROVED_TARGET = "ru"
DEFAULT_MAX_CANDIDATES = 8
DEFAULT_MAX_EXCERPT_CHARS = 1_200
DEFAULT_MAX_FRAGMENT_CHARS = 1_200
DEFAULT_DIAGNOSTIC_ROOT = Path(
    "outputs/glossary-battle-test/issue-619-pro-prep-fake"
)


@dataclass(frozen=True)
class PreparedGlossaryPrepPreflightConfig:
    input_path: Path = APPROVED_INPUT
    target_language: str = APPROVED_TARGET
    diagnostic_root: Path = DEFAULT_DIAGNOSTIC_ROOT
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS
    max_fragment_chars: int = DEFAULT_MAX_FRAGMENT_CHARS
    provider_model: str = DEFAULT_PROVIDER_MODEL


@dataclass(frozen=True)
class PreparedGlossaryPrepPreflightResult:
    status: str
    reason_codes: tuple[str, ...]
    diagnostics_dir: Path
    metadata_report_path: Path
    prepared_package_path: Path
    selected_candidate_count: int
    validation_status: str
    validation_reason_codes: tuple[str, ...]
    package_id: str
    package_signature: str


def run_preflight(
    config: PreparedGlossaryPrepPreflightConfig,
    *,
    timestamp: str | None = None,
) -> PreparedGlossaryPrepPreflightResult:
    _validate_issue_boundary(config)
    timestamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    diagnostics_dir = config.diagnostic_root / timestamp
    diagnostics_dir.mkdir(parents=True, exist_ok=False)

    source_bytes = config.input_path.read_bytes()
    plan = plan_epub_translation(
        content=source_bytes,
        max_fragment_chars=config.max_fragment_chars,
    )
    snapshot = scan_glossary_candidates(
        plan,
        source_language="en",
        target_language=config.target_language,
        snapshot_id="issue-619-gutenberg-time-machine",
    )
    profile = detect_book_profile(
        plan,
        source_language="en",
        target_language=config.target_language,
        glossary_snapshot=snapshot,
    )
    reduction = reduce_glossary_candidates(
        snapshot,
        profile_detection=profile,
        pressure_context={
            "issue": "619",
            "input": str(config.input_path),
            "target_language": config.target_language,
            "max_candidates": config.max_candidates,
            "metadata_only": True,
        },
        caps=GlossaryCandidateReducerCaps(
            max_editor_entries=config.max_candidates,
            max_diagnostic_entries=config.max_candidates,
            max_estimated_editor_tokens=2_400,
            min_editor_score=1,
            min_diagnostic_score=1,
        ),
    )
    candidates = _selected_candidates(
        reduction.retained_snapshot.entries,
        reduction.decisions,
        limit=config.max_candidates,
    )
    packet = _prep_packet(
        config=config,
        source_document_fingerprint=_document_fingerprint(source_bytes),
        reducer_signature=reduction.reducer_signature,
        candidates=candidates,
        plan_block_text_by_id=_plan_block_text_by_id(plan),
        evidence_by_id={
            evidence.evidence_id: evidence
            for evidence in reduction.retained_snapshot.evidence
        },
    )
    prompt = _fake_prompt(packet)
    prepared_package = _fake_prepared_package(
        config=config,
        packet=packet,
        reducer_signature=reduction.reducer_signature,
        source_document_fingerprint=_document_fingerprint(source_bytes),
    )
    fake_response = {
        "schema_version": "fake-deepseek-pro-glossary-prep-response-v1",
        "metadata_only": False,
        "provider_model": config.provider_model,
        "content": prepared_package,
    }
    validation = validate_prepared_glossary_package(
        prepared_package,
        target_language=config.target_language,
    )
    metadata_report = _metadata_report(
        config=config,
        diagnostics_dir=diagnostics_dir,
        reduction_payload=glossary_candidate_reduction_payload(reduction),
        selected_candidate_count=len(candidates),
        validation_metadata=validation.metadata,
    )
    if not _metadata_report_is_safe(metadata_report):
        raise ValueError("metadata report contains unsafe raw or secret material")

    _write_json(diagnostics_dir / "raw_preflight_packet.json", packet)
    (diagnostics_dir / "fake_prompt.txt").write_text(prompt, encoding="utf-8")
    _write_json(diagnostics_dir / "fake_provider_response.json", fake_response)
    _write_json(diagnostics_dir / "prepared_package.json", prepared_package)
    metadata_report_path = diagnostics_dir / "metadata_report.json"
    _write_json(metadata_report_path, metadata_report)

    return PreparedGlossaryPrepPreflightResult(
        status="ready" if validation.ready else "failed",
        reason_codes=tuple(validation.reason_codes),
        diagnostics_dir=diagnostics_dir,
        metadata_report_path=metadata_report_path,
        prepared_package_path=diagnostics_dir / "prepared_package.json",
        selected_candidate_count=len(candidates),
        validation_status=validation.status,
        validation_reason_codes=tuple(validation.reason_codes),
        package_id=validation.package_id,
        package_signature=validation.package_signature,
    )


def _validate_issue_boundary(config: PreparedGlossaryPrepPreflightConfig) -> None:
    if config.input_path != APPROVED_INPUT:
        raise ValueError("issue_619_input_not_approved")
    if config.target_language != APPROVED_TARGET:
        raise ValueError("issue_619_target_not_approved")
    if config.max_candidates <= 0 or config.max_candidates > DEFAULT_MAX_CANDIDATES:
        raise ValueError("issue_619_candidate_bound_invalid")
    if (
        config.max_excerpt_chars <= 0
        or config.max_excerpt_chars > DEFAULT_MAX_EXCERPT_CHARS
    ):
        raise ValueError("issue_619_excerpt_bound_invalid")


def _selected_candidates(
    entries: Sequence[Any],
    decisions: Sequence[Any],
    *,
    limit: int,
) -> tuple[Any, ...]:
    retained_ids = {
        decision.entry_id
        for decision in decisions
        if decision.status is GlossaryCandidateDecisionStatus.RETAINED_FOR_EDITOR
    }
    return tuple(entry for entry in entries if entry.entry_id in retained_ids)[:limit]


def _prep_packet(
    *,
    config: PreparedGlossaryPrepPreflightConfig,
    source_document_fingerprint: str,
    reducer_signature: str,
    candidates: Sequence[Any],
    plan_block_text_by_id: Mapping[str, str],
    evidence_by_id: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": ISSUE_619_SCHEMA_VERSION,
        "issue": "619",
        "input_path": str(config.input_path),
        "source_language": "en",
        "target_language": config.target_language,
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": config.provider_model,
        "source_document_fingerprint": source_document_fingerprint,
        "candidate_selector_signature": reducer_signature,
        "max_candidates": config.max_candidates,
        "max_excerpt_chars": config.max_excerpt_chars,
        "candidates": [
            _candidate_payload(
                entry,
                plan_block_text_by_id=plan_block_text_by_id,
                evidence_by_id=evidence_by_id,
                max_excerpt_chars=config.max_excerpt_chars,
            )
            for entry in candidates
        ],
    }


def _candidate_payload(
    entry: Any,
    *,
    plan_block_text_by_id: Mapping[str, str],
    evidence_by_id: Mapping[str, Any],
    max_excerpt_chars: int,
) -> dict[str, Any]:
    evidence_payloads = []
    for evidence_id in entry.evidence_refs:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            continue
        source_text = plan_block_text_by_id.get(evidence.source_block_id, "")
        evidence_payloads.append(
            {
                "evidence_id": evidence.evidence_id,
                "unit_sequence": evidence.unit_sequence,
                "source_block_id": evidence.source_block_id,
                "bounded_excerpt": source_text[:max_excerpt_chars],
            }
        )
    return {
        "source_entry_id": entry.entry_id,
        "source_canonical": entry.source_canonical,
        "aliases": list(entry.aliases),
        "evidence_refs": list(entry.evidence_refs),
        "evidence": evidence_payloads,
        "confidence": entry.confidence,
        "category": str(entry.category),
    }


def _fake_prompt(packet: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "Role: DeepSeek Pro glossary preparation fake preflight.",
            "Return a compact prepared glossary package JSON object.",
            json.dumps(packet, ensure_ascii=False, sort_keys=True),
        ]
    )


def _fake_prepared_package(
    *,
    config: PreparedGlossaryPrepPreflightConfig,
    packet: Mapping[str, Any],
    reducer_signature: str,
    source_document_fingerprint: str,
) -> dict[str, Any]:
    entries = [
        _fake_prepared_entry(index=index, candidate=candidate)
        for index, candidate in enumerate(packet.get("candidates", ()), start=1)
        if isinstance(candidate, Mapping)
    ]
    return {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": _package_id(
            source_document_fingerprint,
            config.target_language,
            len(entries),
        ),
        "source_language": "en",
        "target_language": config.target_language,
        "glossary_mode": "with_glossary",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": config.provider_model,
        "provider_run_id": "fake-preflight:issue-619",
        "diagnostics_ref": "raw_preflight_packet.json",
        "source_document_fingerprint": source_document_fingerprint,
        "candidate_selector_signature": reducer_signature,
        "owner_approved": True,
        "entries": entries,
    }


def _fake_prepared_entry(*, index: int, candidate: Mapping[str, Any]) -> dict[str, Any]:
    source = str(candidate.get("source_canonical") or f"candidate-{index}")
    evidence_refs = [
        str(item)
        for item in candidate.get("evidence_refs", ())
        if str(item)
    ][:4]
    return {
        "source_entry_id": str(candidate.get("source_entry_id") or f"entry-{index}"),
        "source_canonical": source,
        "aliases": [
            str(item)
            for item in candidate.get("aliases", ())
            if str(item)
        ][:2],
        "evidence_refs": evidence_refs or [f"fake-evidence:{index}"],
        "target_canonical": f"FAKE_RU_TERM_{index}",
        "target_variants": [f"FAKE_RU_TERM_{index}"],
        "forbidden_variants": [],
        "strategy": "fake_preflight_only",
        "confidence": 0.75,
        "needs_review": False,
        "reason_codes": ["fake_preflight_not_semantic"],
    }


def _metadata_report(
    *,
    config: PreparedGlossaryPrepPreflightConfig,
    diagnostics_dir: Path,
    reduction_payload: Mapping[str, Any],
    selected_candidate_count: int,
    validation_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": ISSUE_619_SCHEMA_VERSION,
        "metadata_only": True,
        "raw_payload_included": False,
        "issue": "619",
        "input_path": str(config.input_path),
        "target_language": config.target_language,
        "provider_model": config.provider_model,
        "live_provider_calls": 0,
        "provider_tokens_total": 0,
        "diagnostics_dir": str(diagnostics_dir),
        "selected_candidate_count": selected_candidate_count,
        "max_candidates": config.max_candidates,
        "max_excerpt_chars": config.max_excerpt_chars,
        "reducer_signature": str(reduction_payload.get("reducer_signature")),
        "source_glossary_signature": str(
            reduction_payload.get("source_glossary_signature")
        ),
        "reduced_glossary_signature": str(
            reduction_payload.get("reduced_glossary_signature")
        ),
        "validation": dict(validation_metadata),
        "ordinary_artifact_policy": {
            "raw_source_text_allowed": False,
            "prompt_bodies_allowed": False,
            "provider_responses_allowed": False,
            "translated_bodies_allowed": False,
            "api_keys_or_auth_allowed": False,
        },
        "raw_capable_files": [
            "raw_preflight_packet.json",
            "fake_prompt.txt",
            "fake_provider_response.json",
            "prepared_package.json",
        ],
    }


def _metadata_report_is_safe(report: Mapping[str, Any]) -> bool:
    text = json.dumps(report, ensure_ascii=False, sort_keys=True)
    unsafe_needles = (
        "<html",
        "<body",
        "Time Traveller",
        "RAW PROMPT",
        "Bearer ",
        "sk-",
        "Authorization",
    )
    return not any(needle in text for needle in unsafe_needles)


def _plan_block_text_by_id(plan: Any) -> dict[str, str]:
    return {
        block.source_block_id: block.text
        for unit in plan.units
        for block in unit.blocks
    }


def _document_fingerprint(source_bytes: bytes) -> str:
    return f"sha256:{hashlib.sha256(source_bytes).hexdigest()[:24]}"


def _package_id(
    source_document_fingerprint: str,
    target_language: str,
    entry_count: int,
) -> str:
    digest = hashlib.sha256(
        f"{source_document_fingerprint}:{target_language}:{entry_count}".encode()
    ).hexdigest()[:16]
    return f"prepared:issue-619:{target_language}:{digest}"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run local fake prepared glossary Pro-prep preflight for #619."
    )
    parser.add_argument("--input", default=str(APPROVED_INPUT))
    parser.add_argument("--target", default=APPROVED_TARGET)
    parser.add_argument("--diagnostic-root", default=str(DEFAULT_DIAGNOSTIC_ROOT))
    parser.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    parser.add_argument(
        "--max-excerpt-chars",
        type=int,
        default=DEFAULT_MAX_EXCERPT_CHARS,
    )
    parser.add_argument("--timestamp")
    args = parser.parse_args(argv)
    result = run_preflight(
        PreparedGlossaryPrepPreflightConfig(
            input_path=Path(args.input),
            target_language=args.target,
            diagnostic_root=Path(args.diagnostic_root),
            max_candidates=args.max_candidates,
            max_excerpt_chars=args.max_excerpt_chars,
        ),
        timestamp=args.timestamp,
    )
    print(
        json.dumps(
            {
                "status": result.status,
                "validation_status": result.validation_status,
                "selected_candidate_count": result.selected_candidate_count,
                "metadata_report_path": str(result.metadata_report_path),
                "diagnostics_dir": str(result.diagnostics_dir),
                "live_provider_calls": 0,
                "provider_tokens_total": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
