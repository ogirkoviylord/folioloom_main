from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
ISSUE_614_SCHEMA_VERSION = "prepared-glossary-pro-prep-live-v1"
DEFAULT_PROVIDER_MODEL = "deepseek-v4-pro"
DEFAULT_PROVIDER_BASE_URL = "https://api.deepseek.com"
APPROVED_INPUT = Path("test_samples/gutenberg_time_machine_noimages.en.epub")
APPROVED_TARGET = "ru"
DEFAULT_MAX_CANDIDATES = 8
DEFAULT_MAX_EXCERPT_CHARS = 1_200
DEFAULT_MAX_FRAGMENT_CHARS = 1_200
DEFAULT_MAX_CALLS = 6
DEFAULT_MAX_TOKENS_TOTAL = 60_000
DEFAULT_MAX_COMPLETION_TOKENS = 4_000
DEFAULT_DIAGNOSTIC_ROOT = Path(
    "outputs/glossary-battle-test/issue-619-pro-prep-fake"
)
ISSUE_614_DIAGNOSTIC_ROOT = Path(
    "outputs/glossary-battle-test/issue-614-pro-prep"
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


@dataclass(frozen=True)
class ChatCallResult:
    ok: bool
    content: str
    usage: Mapping[str, int]
    finish_reason: str | None
    http_status: int | None
    elapsed_seconds: float
    request_payload: Mapping[str, Any]
    response_payload: Mapping[str, Any] | None = None
    response_text: str | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class PreparedGlossaryPrepLiveConfig(PreparedGlossaryPrepPreflightConfig):
    diagnostic_root: Path = ISSUE_614_DIAGNOSTIC_ROOT
    provider_base_url: str = DEFAULT_PROVIDER_BASE_URL
    max_calls: int = DEFAULT_MAX_CALLS
    max_tokens_total: int = DEFAULT_MAX_TOKENS_TOTAL
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS


@dataclass(frozen=True)
class PreparedGlossaryPrepLiveResult:
    status: str
    reason_codes: tuple[str, ...]
    diagnostics_dir: Path
    metadata_report_path: Path
    prepared_package_path: Path
    selected_candidate_count: int
    validation_status: str
    validation_reason_codes: tuple[str, ...]
    calls_made: int
    provider_tokens_total: int | None
    package_id: str
    package_signature: str


class OpenAICompatibleProvider:
    def __init__(self, *, api_key: str, base_url: str, timeout_seconds: float = 90.0):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ) -> ChatCallResult:
        request_payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": max_completion_tokens,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
        }
        request = Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(request_payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        start = time.monotonic()
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                response_bytes = response.read()
                http_status = response.status
        except HTTPError as error:
            elapsed = time.monotonic() - start
            response_text = _decode_response(error.read())
            return ChatCallResult(
                ok=False,
                content="",
                usage={},
                finish_reason=None,
                http_status=error.code,
                elapsed_seconds=elapsed,
                request_payload=request_payload,
                response_text=response_text,
                error_type=error.__class__.__name__,
                error_message=f"HTTP {error.code}",
            )
        except (URLError, TimeoutError) as error:
            elapsed = time.monotonic() - start
            return ChatCallResult(
                ok=False,
                content="",
                usage={},
                finish_reason=None,
                http_status=None,
                elapsed_seconds=elapsed,
                request_payload=request_payload,
                response_text=None,
                error_type=error.__class__.__name__,
                error_message=(
                    "provider_response_timeout"
                    if isinstance(error, TimeoutError)
                    else error.__class__.__name__
                ),
            )

        elapsed = time.monotonic() - start
        response_text = _decode_response(response_bytes)
        try:
            response_payload = json.loads(response_text)
        except json.JSONDecodeError as error:
            return ChatCallResult(
                ok=False,
                content="",
                usage={},
                finish_reason=None,
                http_status=http_status,
                elapsed_seconds=elapsed,
                request_payload=request_payload,
                response_text=response_text,
                error_type=error.__class__.__name__,
                error_message="provider_response_invalid_json",
            )
        choice = (response_payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return ChatCallResult(
            ok=http_status == 200,
            content=str(message.get("content") or ""),
            usage=_provider_usage(response_payload.get("usage")),
            finish_reason=choice.get("finish_reason"),
            http_status=http_status,
            elapsed_seconds=elapsed,
            request_payload=request_payload,
            response_payload=response_payload,
            response_text=response_text,
        )


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


def run_live_preparation(
    config: PreparedGlossaryPrepLiveConfig,
    *,
    provider: Any,
    timestamp: str | None = None,
    allow_test_diagnostic_root: bool = False,
) -> PreparedGlossaryPrepLiveResult:
    _validate_issue_614_boundary(
        config,
        allow_test_diagnostic_root=allow_test_diagnostic_root,
    )
    timestamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    diagnostics_dir = config.diagnostic_root / timestamp
    diagnostics_dir.mkdir(parents=True, exist_ok=False)

    artifacts = _build_preflight_artifacts(config, issue_id="614")
    fake_validation = validate_prepared_glossary_package(
        artifacts["fake_prepared_package"],
        target_language=config.target_language,
    )
    if not fake_validation.ready:
        raise ValueError("issue_614_fake_preflight_failed")

    system_prompt = _live_system_prompt()
    user_prompt = _live_user_prompt(artifacts["packet"])
    estimated_prompt_tokens = _estimate_tokens(system_prompt + "\n" + user_prompt)
    reserved_tokens = estimated_prompt_tokens * 2 + config.max_completion_tokens
    if reserved_tokens > config.max_tokens_total:
        raise ValueError("issue_614_token_reservation_exceeds_cap")

    call_result = provider.chat(
        model=config.provider_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_completion_tokens=config.max_completion_tokens,
    )
    package_payload, parse_reason_codes = _provider_package_payload(call_result.content)
    validation = validate_prepared_glossary_package(
        package_payload,
        target_language=config.target_language,
    )
    observed_tokens = _usage_total_tokens(call_result.usage)
    token_cap_exceeded = (
        observed_tokens is not None and observed_tokens > config.max_tokens_total
    )
    reason_codes = list(parse_reason_codes)
    if not call_result.ok:
        reason_codes.append("issue_614_provider_call_failed")
    if token_cap_exceeded:
        reason_codes.append("issue_614_token_cap_exceeded")
    reason_codes.extend(validation.reason_codes)
    if observed_tokens is None:
        reason_codes.append("provider_usage_unknown")

    prepared_package_path = diagnostics_dir / "live_prepared_package.json"
    metadata_report = _live_metadata_report(
        config=config,
        diagnostics_dir=diagnostics_dir,
        reduction_payload=artifacts["reduction_payload"],
        selected_candidate_count=len(artifacts["candidates"]),
        fake_validation_metadata=fake_validation.metadata,
        validation_metadata=validation.metadata,
        call_result=call_result,
        estimated_prompt_tokens=estimated_prompt_tokens,
        reserved_tokens=reserved_tokens,
        observed_tokens=observed_tokens,
        reason_codes=reason_codes,
    )
    if not _metadata_report_is_safe(metadata_report):
        raise ValueError("metadata report contains unsafe raw or secret material")

    _write_json(diagnostics_dir / "raw_preflight_packet.json", artifacts["packet"])
    (diagnostics_dir / "fake_prompt.txt").write_text(
        artifacts["fake_prompt"],
        encoding="utf-8",
    )
    _write_json(
        diagnostics_dir / "fake_provider_response.json",
        artifacts["fake_response"],
    )
    (diagnostics_dir / "live_system_prompt.txt").write_text(
        system_prompt,
        encoding="utf-8",
    )
    (diagnostics_dir / "live_user_prompt.txt").write_text(
        user_prompt,
        encoding="utf-8",
    )
    _write_json(
        diagnostics_dir / "live_provider_diagnostic.json",
        _live_call_diagnostic(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            call_result=call_result,
            validation_metadata=validation.metadata,
        ),
    )
    if isinstance(package_payload, Mapping):
        _write_json(prepared_package_path, package_payload)
    else:
        _write_json(
            prepared_package_path,
            {"status": "invalid", "reason_codes": list(parse_reason_codes)},
        )
    metadata_report_path = diagnostics_dir / "metadata_report.json"
    _write_json(metadata_report_path, metadata_report)

    status = (
        "ready"
        if call_result.ok and validation.ready and not token_cap_exceeded
        else "failed"
    )
    return PreparedGlossaryPrepLiveResult(
        status=status,
        reason_codes=tuple(_dedupe(reason_codes)),
        diagnostics_dir=diagnostics_dir,
        metadata_report_path=metadata_report_path,
        prepared_package_path=prepared_package_path,
        selected_candidate_count=len(artifacts["candidates"]),
        validation_status=validation.status,
        validation_reason_codes=tuple(validation.reason_codes),
        calls_made=1,
        provider_tokens_total=observed_tokens,
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


def _validate_issue_614_boundary(
    config: PreparedGlossaryPrepLiveConfig,
    *,
    allow_test_diagnostic_root: bool,
) -> None:
    if config.input_path != APPROVED_INPUT:
        raise ValueError("issue_614_input_not_approved")
    if config.target_language != APPROVED_TARGET:
        raise ValueError("issue_614_target_not_approved")
    if config.max_candidates <= 0 or config.max_candidates > DEFAULT_MAX_CANDIDATES:
        raise ValueError("issue_614_candidate_bound_invalid")
    if (
        config.max_excerpt_chars <= 0
        or config.max_excerpt_chars > DEFAULT_MAX_EXCERPT_CHARS
    ):
        raise ValueError("issue_614_excerpt_bound_invalid")
    if config.provider_model != DEFAULT_PROVIDER_MODEL:
        raise ValueError("issue_614_provider_model_not_approved")
    if config.max_calls <= 0 or config.max_calls > DEFAULT_MAX_CALLS:
        raise ValueError("issue_614_call_cap_invalid")
    if (
        config.max_tokens_total <= 0
        or config.max_tokens_total > DEFAULT_MAX_TOKENS_TOTAL
    ):
        raise ValueError("issue_614_token_cap_invalid")
    if config.max_completion_tokens <= 0:
        raise ValueError("issue_614_completion_cap_invalid")
    if (
        not allow_test_diagnostic_root
        and config.diagnostic_root != ISSUE_614_DIAGNOSTIC_ROOT
    ):
        raise ValueError("issue_614_diagnostic_root_not_approved")


def _build_preflight_artifacts(
    config: PreparedGlossaryPrepPreflightConfig,
    *,
    issue_id: str,
) -> dict[str, Any]:
    source_bytes = config.input_path.read_bytes()
    plan = plan_epub_translation(
        content=source_bytes,
        max_fragment_chars=config.max_fragment_chars,
    )
    snapshot = scan_glossary_candidates(
        plan,
        source_language="en",
        target_language=config.target_language,
        snapshot_id=f"issue-{issue_id}-gutenberg-time-machine",
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
            "issue": issue_id,
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
    source_document_fingerprint = _document_fingerprint(source_bytes)
    packet = _prep_packet(
        config=config,
        source_document_fingerprint=source_document_fingerprint,
        reducer_signature=reduction.reducer_signature,
        candidates=candidates,
        plan_block_text_by_id=_plan_block_text_by_id(plan),
        evidence_by_id={
            evidence.evidence_id: evidence
            for evidence in reduction.retained_snapshot.evidence
        },
    )
    fake_prompt = _fake_prompt(packet)
    fake_prepared_package = _fake_prepared_package(
        config=config,
        packet=packet,
        reducer_signature=reduction.reducer_signature,
        source_document_fingerprint=source_document_fingerprint,
    )
    fake_response = {
        "schema_version": "fake-deepseek-pro-glossary-prep-response-v1",
        "metadata_only": False,
        "provider_model": config.provider_model,
        "content": fake_prepared_package,
    }
    return {
        "source_bytes": source_bytes,
        "reduction_payload": glossary_candidate_reduction_payload(reduction),
        "candidates": candidates,
        "packet": packet,
        "fake_prompt": fake_prompt,
        "fake_prepared_package": fake_prepared_package,
        "fake_response": fake_response,
    }


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


def _live_system_prompt() -> str:
    return "\n".join(
        [
            "You are the DeepSeek Pro glossary preparation role.",
            "Return only one JSON object matching schema glossary-prepared-package-v1.",
            "Use only the candidates and evidence ids from the provided packet.",
            "Do not invent source entries, evidence ids, or raw passages.",
            (
                "Do not include raw source excerpts, prompt text, provider request/"
                "response bodies, translated passages, API keys or auth material."
            ),
            (
                "For every entry, provide target_canonical or target_variants for "
                "the requested target language, plus confidence, needs_review and "
                "metadata-only reason_codes."
            ),
        ]
    )


def _live_user_prompt(packet: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "task": "prepare_target_backed_glossary_package",
            "output_schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
            "required_provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
            "packet": packet,
            "output_requirements": {
                "owner_approved": True,
                "glossary_mode": "with_glossary",
                "source_language": "en",
                "target_language": packet.get("target_language", APPROVED_TARGET),
                "provider_model": packet.get("provider_model", DEFAULT_PROVIDER_MODEL),
                "diagnostics_ref": "live_provider_diagnostic.json",
                "no_raw_excerpt_fields": True,
                "max_entries": packet.get("max_candidates", DEFAULT_MAX_CANDIDATES),
            },
        },
        ensure_ascii=False,
        sort_keys=True,
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


def _live_metadata_report(
    *,
    config: PreparedGlossaryPrepLiveConfig,
    diagnostics_dir: Path,
    reduction_payload: Mapping[str, Any],
    selected_candidate_count: int,
    fake_validation_metadata: Mapping[str, Any],
    validation_metadata: Mapping[str, Any],
    call_result: ChatCallResult,
    estimated_prompt_tokens: int,
    reserved_tokens: int,
    observed_tokens: int | None,
    reason_codes: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": ISSUE_614_SCHEMA_VERSION,
        "metadata_only": True,
        "raw_payload_included": False,
        "issue": "614",
        "input_path": str(config.input_path),
        "target_language": config.target_language,
        "provider_model": config.provider_model,
        "runtime_translation_model": "unchanged_configured_runtime_provider_model",
        "live_provider_calls": 1,
        "max_live_provider_calls": config.max_calls,
        "provider_tokens_total": _unknown_int(observed_tokens),
        "max_tokens_total": config.max_tokens_total,
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
        "status": (
            "ready"
            if call_result.ok
            and validation_metadata.get("status") == "ready"
            and (
                observed_tokens is None or observed_tokens <= config.max_tokens_total
            )
            else "failed"
        ),
        "reason_codes": list(_dedupe(reason_codes)),
        "fake_preflight_validation": dict(fake_validation_metadata),
        "live_validation": dict(validation_metadata),
        "call": {
            "status": (
                "validated"
                if call_result.ok and validation_metadata.get("status") == "ready"
                else "failed"
            ),
            "http_status": call_result.http_status,
            "elapsed_seconds": round(call_result.elapsed_seconds, 3),
            "finish_reason": call_result.finish_reason,
            "estimated_prompt_tokens": estimated_prompt_tokens,
            "reserved_tokens": reserved_tokens,
            "usage": dict(call_result.usage),
            "error_type": call_result.error_type,
            "error_message": call_result.error_message,
        },
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
            "live_system_prompt.txt",
            "live_user_prompt.txt",
            "live_provider_diagnostic.json",
            "live_prepared_package.json",
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


def _live_call_diagnostic(
    *,
    system_prompt: str,
    user_prompt: str,
    call_result: ChatCallResult,
    validation_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": ISSUE_614_SCHEMA_VERSION,
        "diagnostic_scope": "owner_only_deepseek_pro_prepared_glossary_prep",
        "raw_text_capture": True,
        "access_boundary": {
            "visibility": "owner_only",
            "ordinary_logs_allowed": False,
            "telemetry_allowed": False,
            "github_issue_or_pr_allowed": False,
            "release_artifact_allowed": False,
        },
        "secret_exclusion_policy": (
            "Provider auth headers, API keys, tokens and real .env* values "
            "are not stored."
        ),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "request_payload": call_result.request_payload,
        "response_payload": call_result.response_payload,
        "response_text": call_result.response_text,
        "model_content": call_result.content,
        "usage": dict(call_result.usage),
        "http_status": call_result.http_status,
        "finish_reason": call_result.finish_reason,
        "elapsed_seconds": round(call_result.elapsed_seconds, 3),
        "validation": dict(validation_metadata),
        "error_type": call_result.error_type,
        "error_message": call_result.error_message,
    }


def _provider_package_payload(content: str) -> tuple[Any, tuple[str, ...]]:
    text = _strip_json_fence(content)
    try:
        return json.loads(text), ()
    except json.JSONDecodeError:
        return {}, ("provider_response_invalid_package_json",)


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


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


def _decode_response(response_bytes: bytes) -> str:
    try:
        return response_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return response_bytes.decode("utf-8", errors="replace")


def _provider_usage(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    usage: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        item = value.get(key)
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            usage[key] = item
    return usage


def _usage_total_tokens(value: Any) -> int | None:
    if not isinstance(value, Mapping):
        return None
    total_tokens = value.get("total_tokens")
    if isinstance(total_tokens, bool):
        return None
    if isinstance(total_tokens, int):
        return total_tokens
    return None


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _unknown_int(value: int | None) -> int | str:
    return value if value is not None else "Unknown"


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return tuple(result)


def load_env_api_key() -> str:
    key_list = os.getenv("DEEPSEEK_API_KEYS", "")
    for candidate in key_list.split(","):
        api_key = candidate.strip()
        if api_key:
            return api_key
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


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
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument(
        "--max-tokens-total",
        type=int,
        default=DEFAULT_MAX_TOKENS_TOTAL,
    )
    parser.add_argument(
        "--max-completion-tokens",
        type=int,
        default=DEFAULT_MAX_COMPLETION_TOKENS,
    )
    parser.add_argument("--model", default=DEFAULT_PROVIDER_MODEL)
    parser.add_argument(
        "--base-url",
        default=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_PROVIDER_BASE_URL),
    )
    parser.add_argument(
        "--issue-614-live",
        action="store_true",
        help="Run the owner-approved #614 bounded live Pro-prep path.",
    )
    parser.add_argument("--timestamp")
    args = parser.parse_args(argv)
    if args.issue_614_live:
        api_key = load_env_api_key()
        if not api_key:
            raise SystemExit(
                "DEEPSEEK_API_KEY/DEEPSEEK_API_KEYS is not set in the "
                "process environment"
            )
        live_result = run_live_preparation(
            PreparedGlossaryPrepLiveConfig(
                input_path=Path(args.input),
                target_language=args.target,
                diagnostic_root=Path(args.diagnostic_root),
                max_candidates=args.max_candidates,
                max_excerpt_chars=args.max_excerpt_chars,
                provider_model=args.model,
                provider_base_url=args.base_url,
                max_calls=args.max_calls,
                max_tokens_total=args.max_tokens_total,
                max_completion_tokens=args.max_completion_tokens,
            ),
            provider=OpenAICompatibleProvider(
                api_key=api_key,
                base_url=args.base_url,
            ),
            timestamp=args.timestamp,
        )
        print(
            json.dumps(
                {
                    "status": live_result.status,
                    "validation_status": live_result.validation_status,
                    "selected_candidate_count": live_result.selected_candidate_count,
                    "metadata_report_path": str(live_result.metadata_report_path),
                    "diagnostics_dir": str(live_result.diagnostics_dir),
                    "live_provider_calls": live_result.calls_made,
                    "provider_tokens_total": _unknown_int(
                        live_result.provider_tokens_total
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

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
