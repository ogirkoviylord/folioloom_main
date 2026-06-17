from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from translator_service.deepseek_client import DeepSeekClient
from translator_service.documents import DocumentFormat
from translator_service.format_adapters.epub import plan_epub_translation
from translator_service.glossary_compliance import validate_glossary_compliance
from translator_service.glossary_persistent_runtime_resolver import (
    PersistentGlossaryResolverConfig,
    build_persistent_glossary_runtime_hook_from_prepared_package,
)
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
    validate_prepared_glossary_package,
)
from translator_service.glossary_prepared_prep_service import (
    DEFAULT_PREPARED_GLOSSARY_ESTIMATED_EDITOR_TOKENS,
    DEFAULT_PREPARED_GLOSSARY_MAX_CANDIDATES,
    DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
    PreparedGlossaryPackagePrepRequest,
    PreparedGlossaryPrepService,
    PreparedGlossaryPrepServiceConfig,
    PreparedGlossaryProviderResponse,
)
from translator_service.glossary_prepared_provider import (
    PreparedGlossaryDeepSeekProviderConfig,
    build_deepseek_prepared_glossary_provider,
)
from translator_service.output_contracts import (
    json_translation_batch_to_xml_contract,
    normalize_provider_translation_batch_contract,
)
from translator_service.persistent_jobs import (
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
)
from translator_service.provider_io_diagnostics import (
    ProviderIODiagnosticSink,
    capture_provider_io,
)
from translator_service.worker import (
    _persistent_work_unit_glossary_prompt_context,
    _translate_work_unit_text_with_provider_io,
)

ISSUE_ID = "675"
SCHEMA_VERSION = "glossary-effectiveness-smoke-v1"
APPROVED_INPUT = Path("test_samples/gutenberg_time_machine_noimages.en.epub")
APPROVED_TARGET = "ru"
APPROVED_DIAGNOSTIC_ROOT = Path("outputs/issue-675-glossary-effectiveness-smoke")
DEFAULT_PROVIDER_BASE_URL = "https://api.deepseek.com"
DEFAULT_RUNTIME_MODEL = "deepseek-v4-flash"
DEFAULT_MAX_CALLS = 4
DEFAULT_MAX_TOKENS_TOTAL = 60_000
DEFAULT_MAX_EXCERPT_CHARS = 1_200
DEFAULT_MAX_FRAGMENT_CHARS = 1_200

_SECRET_PATTERNS = (
    "Authorization",
    "Bearer ",
    "sk-",
    "BEGIN PRIVATE KEY",
    "API_KEY=",
    "TOKEN=",
    "PASSWORD=",
    "DSN=",
    "raw_source_text",
    "prompt_body",
    "provider_response_body",
    "translated_text",
)


@dataclass(frozen=True)
class GlossaryEffectivenessSmokeConfig:
    input_path: Path = APPROVED_INPUT
    target_language: str = APPROVED_TARGET
    diagnostic_root: Path = APPROVED_DIAGNOSTIC_ROOT
    source_language: str = "en"
    max_calls: int = DEFAULT_MAX_CALLS
    max_tokens_total: int = DEFAULT_MAX_TOKENS_TOTAL
    provider_model: str = DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL
    runtime_model: str = DEFAULT_RUNTIME_MODEL
    provider_base_url: str = DEFAULT_PROVIDER_BASE_URL
    max_candidates: int = DEFAULT_PREPARED_GLOSSARY_MAX_CANDIDATES
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS
    max_fragment_chars: int = DEFAULT_MAX_FRAGMENT_CHARS
    max_estimated_editor_tokens: int = (
        DEFAULT_PREPARED_GLOSSARY_ESTIMATED_EDITOR_TOKENS
    )


@dataclass(frozen=True)
class GlossaryEffectivenessSmokeResult:
    status: str
    reason_codes: tuple[str, ...]
    diagnostics_dir: Path
    metadata_report_path: Path
    prepared_package_path: Path | None
    selected_unit_sequence: int | None
    live_provider_calls: int
    provider_tokens_total: int | None


@dataclass(frozen=True)
class _SelectedRuntimeUnit:
    work_unit: PersistentWorkUnit
    source_text: str
    source_blocks: tuple[str, ...]
    metadata_event: Mapping[str, Any]
    glossary_context_text: str
    prompt_context_entries: tuple[Mapping[str, Any], ...]
    glossary_runtime_hook: Any


class _ProviderCallLedger:
    def __init__(self, *, max_calls: int, max_tokens_total: int) -> None:
        self.max_calls = max_calls
        self.max_tokens_total = max_tokens_total
        self.calls = 0
        self.tokens_total: int | None = 0

    def reserve_call(self) -> None:
        if self.calls >= self.max_calls:
            raise RuntimeError("issue_675_live_call_cap_exceeded")
        self.calls += 1

    def record_usage(self, usage: Mapping[str, Any] | object | None) -> None:
        total = _usage_total_tokens(usage)
        if total is None:
            self.tokens_total = None
            return
        if self.tokens_total is None:
            return
        self.tokens_total += total
        if self.tokens_total > self.max_tokens_total:
            raise RuntimeError("issue_675_token_cap_exceeded")


class _LedgerTransport:
    def __init__(self, *, api_key: str, ledger: _ProviderCallLedger) -> None:
        from translator_service.deepseek_client import _urllib_transport

        self._api_key = api_key
        self._ledger = ledger
        self._transport = _urllib_transport

    def __call__(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        self._ledger.reserve_call()
        return self._transport(
            url=url,
            headers={
                **headers,
                "Authorization": f"Bearer {self._api_key}",
            },
            body=body,
            timeout_seconds=timeout_seconds,
        )


def run_fake_dry_preflight(
    config: GlossaryEffectivenessSmokeConfig,
    *,
    timestamp: str | None = None,
) -> GlossaryEffectivenessSmokeResult:
    _validate_issue_boundary(config, live=False, allow_test_diagnostic_root=True)
    timestamp = timestamp or _timestamp()
    diagnostics_dir = config.diagnostic_root / timestamp
    diagnostics_dir.mkdir(parents=True, exist_ok=False)

    report, prepared_package, selected = _run_preflight_core(
        config,
        diagnostics_dir=diagnostics_dir,
        provider=_fake_prepared_glossary_provider,
    )
    report.update(
        {
            "status": (
                "ready"
                if selected is not None and prepared_package is not None
                else "blocked"
            ),
            "mode": "fake_dry",
            "live_provider_calls": 0,
            "provider_tokens_total": 0,
        }
    )
    reason_codes = _report_reason_codes(report)
    metadata_report_path = diagnostics_dir / "metadata_report.json"
    prepared_package_path = diagnostics_dir / "fake_prepared_package.json"
    if prepared_package is not None:
        _write_json(prepared_package_path, prepared_package)
    _assert_metadata_report_safe(report)
    _write_json(metadata_report_path, report)
    return GlossaryEffectivenessSmokeResult(
        status=str(report["status"]),
        reason_codes=reason_codes,
        diagnostics_dir=diagnostics_dir,
        metadata_report_path=metadata_report_path,
        prepared_package_path=prepared_package_path
        if prepared_package is not None
        else None,
        selected_unit_sequence=selected.work_unit.sequence if selected else None,
        live_provider_calls=0,
        provider_tokens_total=0,
    )


def run_live_smoke(
    config: GlossaryEffectivenessSmokeConfig,
    *,
    api_key: str,
    timestamp: str | None = None,
    allow_test_diagnostic_root: bool = False,
    prep_provider: Any | None = None,
    runtime_translator: Any | None = None,
) -> GlossaryEffectivenessSmokeResult:
    _validate_issue_boundary(
        config,
        live=True,
        allow_test_diagnostic_root=allow_test_diagnostic_root,
    )
    if not api_key.strip() and (prep_provider is None or runtime_translator is None):
        raise ValueError("issue_675_api_key_missing")
    timestamp = timestamp or _timestamp()
    diagnostics_dir = config.diagnostic_root / timestamp
    diagnostics_dir.mkdir(parents=True, exist_ok=False)
    provider_io_path = diagnostics_dir / "provider_io_diagnostics.jsonl"
    provider_io_sink = _jsonl_sink(provider_io_path)
    ledger = _ProviderCallLedger(
        max_calls=config.max_calls,
        max_tokens_total=config.max_tokens_total,
    )

    if prep_provider is None:
        prep_provider = _live_prepared_glossary_provider(
            config,
            api_key=api_key,
            ledger=ledger,
            provider_io_sink=provider_io_sink,
        )

    report, prepared_package, selected = _run_preflight_core(
        config,
        diagnostics_dir=diagnostics_dir,
        provider=prep_provider,
    )
    prep_usage = _prepared_package_provider_usage(report)
    ledger.record_usage(prep_usage)
    prepared_package_path = diagnostics_dir / "live_prepared_package.json"
    if prepared_package is not None:
        _write_json(prepared_package_path, prepared_package)
    else:
        _write_json(
            prepared_package_path,
            {
                "status": "invalid",
                "reason_codes": report.get("reason_codes", []),
            },
        )

    runtime_report: dict[str, Any] = {
        "status": "skipped",
        "reason_codes": [],
        "provider_call_observed": False,
    }
    translated_text: str | None = None
    if prepared_package is None:
        runtime_report["reason_codes"] = [
            "issue_675_prepared_package_not_ready"
        ]
    elif selected is None:
        runtime_report["reason_codes"] = [
            "issue_675_no_glossary_useful_pressure_safe_unit"
        ]
    else:
        if runtime_translator is None:
            runtime_translator = _live_runtime_translator(
                config,
                api_key=api_key,
                ledger=ledger,
            )
        runtime_report, translated_text = _run_runtime_unit(
            selected,
            translator=runtime_translator,
            provider_io_sink=provider_io_sink,
        )
        ledger.record_usage(runtime_report.get("provider_usage"))

    compliance = _compliance_summary(
        selected,
        translated_text=translated_text,
        structural_validation=runtime_report.get("structural_validation"),
        target_language=config.target_language,
    )
    report.update(
        {
            "mode": "live",
            "runtime": runtime_report,
            "glossary_compliance": compliance,
            "live_provider_calls": ledger.calls,
            "provider_tokens_total": (
                ledger.tokens_total if ledger.tokens_total is not None else "Unknown"
            ),
            "status": _overall_live_status(report, selected, runtime_report),
        }
    )
    report["reason_codes"] = list(
        _dedupe(
            [
                *report.get("reason_codes", []),
                *runtime_report.get("reason_codes", []),
                *compliance.get("reason_codes", []),
            ]
        )
    )
    if ledger.tokens_total is None:
        report["reason_codes"].append("provider_usage_unknown")
    metadata_report_path = diagnostics_dir / "metadata_report.json"
    _assert_metadata_report_safe(report)
    _write_json(metadata_report_path, report)
    return GlossaryEffectivenessSmokeResult(
        status=str(report["status"]),
        reason_codes=tuple(report["reason_codes"]),
        diagnostics_dir=diagnostics_dir,
        metadata_report_path=metadata_report_path,
        prepared_package_path=prepared_package_path,
        selected_unit_sequence=selected.work_unit.sequence if selected else None,
        live_provider_calls=ledger.calls,
        provider_tokens_total=ledger.tokens_total,
    )


def _run_preflight_core(
    config: GlossaryEffectivenessSmokeConfig,
    *,
    diagnostics_dir: Path,
    provider: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None, _SelectedRuntimeUnit | None]:
    content = config.input_path.read_bytes()
    source_sha256 = hashlib.sha256(content).hexdigest()
    request = PreparedGlossaryPackagePrepRequest(
        user_telegram_id=0,
        file_name=config.input_path.name,
        document_kind=DocumentFormat.EPUB.value,
        source_language=config.source_language,
        target_language=config.target_language,
        translation_mode="book_manuscript",
        glossary_mode="with_glossary",
        source_sha256=source_sha256,
        content=content,
    )
    service = PreparedGlossaryPrepService(
        provider=provider,
        config=PreparedGlossaryPrepServiceConfig(
            provider_model=config.provider_model,
            max_candidates=config.max_candidates,
            max_excerpt_chars=config.max_excerpt_chars,
            max_fragment_chars=config.max_fragment_chars,
            max_estimated_editor_tokens=config.max_estimated_editor_tokens,
            require_provider_usage=provider is not _fake_prepared_glossary_provider,
            max_provider_reported_total_tokens=config.max_tokens_total,
        ),
    )
    attachment = service.prepare(request)
    validation = validate_prepared_glossary_package(
        attachment.payload,
        target_language=config.target_language,
    )
    prepared_package = dict(attachment.payload) if validation.ready else None
    plan = plan_epub_translation(
        content=content,
        max_fragment_chars=config.max_fragment_chars,
    )
    selected = (
        _select_first_glossary_useful_unit(
            plan_units=plan.units,
            prepared_package=prepared_package,
            target_language=config.target_language,
        )
        if prepared_package is not None
        else None
    )
    _write_json(
        diagnostics_dir / "prepared_glossary_attachment_metadata.json",
        dict(attachment.metadata),
    )
    report = _metadata_report(
        config,
        diagnostics_dir=diagnostics_dir,
        source_sha256=source_sha256,
        attachment_metadata=attachment.metadata,
        validation_metadata=validation.metadata,
        selected=selected,
    )
    if selected is None:
        report["reason_codes"].append("issue_675_no_glossary_useful_pressure_safe_unit")
    return report, prepared_package, selected


def _select_first_glossary_useful_unit(
    *,
    plan_units: Sequence[Any],
    prepared_package: Mapping[str, Any],
    target_language: str,
) -> _SelectedRuntimeUnit | None:
    for unit in plan_units:
        work_unit = _work_unit_from_plan_unit(unit, target_language=target_language)
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=work_unit,
            source_text=unit.source_text,
            prepared_package_payload=prepared_package,
            document_kind=DocumentFormat.EPUB.value,
            config=PersistentGlossaryResolverConfig(
                enabled=True,
                owner_battle_test_enabled=True,
            ),
        )
        events: list[dict[str, object]] = []
        context_text = _persistent_work_unit_glossary_prompt_context(
            work_unit=work_unit,
            source_blocks=[block.text for block in unit.blocks],
            glossary_runtime_hook=hook,
            glossary_adapter_metadata_callback=events.append,
        )
        if not context_text or not events:
            continue
        event = events[-1]
        preflight = event.get("battle_test_preflight")
        prompt_context = event.get("prompt_context")
        cache_policy = event.get("cache_policy")
        if not isinstance(preflight, Mapping) or not isinstance(
            prompt_context,
            Mapping,
        ):
            continue
        if preflight.get("status") != "ready":
            continue
        if preflight.get("source_size_gate_status") != "within_limit":
            continue
        if (
            not isinstance(cache_policy, Mapping)
            or cache_policy.get("behavior") != "bypass_glossary_injected_cache"
        ):
            continue
        if not prompt_context.get("included_entry_ids"):
            continue
        return _SelectedRuntimeUnit(
            work_unit=work_unit,
            source_text=unit.source_text,
            source_blocks=tuple(block.text for block in unit.blocks),
            metadata_event=event,
            glossary_context_text=context_text,
            prompt_context_entries=tuple(
                dict(entry) for entry in hook.prompt_context_entries
            ),
            glossary_runtime_hook=hook,
        )
    return None


def _run_runtime_unit(
    selected: _SelectedRuntimeUnit,
    *,
    translator: Any,
    provider_io_sink: ProviderIODiagnosticSink | None,
) -> tuple[dict[str, Any], str | None]:
    records: list[dict[str, object]] = []

    def sink(record: dict[str, object]) -> None:
        records.append(record)
        if provider_io_sink is not None:
            provider_io_sink(record)

    try:
        result = _translate_work_unit_text_with_provider_io(
            work_unit=selected.work_unit,
            source_text=selected.source_text,
            translator=translator,
            provider_io_diagnostic_sink=sink,
            glossary_runtime_hook=selected.glossary_runtime_hook,
            glossary_adapter_metadata_callback=None,
        )
    except Exception as error:
        runtime_report = _runtime_report_from_records(
            selected,
            records=records,
            provider_usage=getattr(translator, "last_usage", None),
        )
        runtime_report["status"] = "failed"
        runtime_report["reason_codes"] = list(
            _dedupe(
                [
                    *runtime_report.get("reason_codes", []),
                    "issue_675_runtime_translation_failed",
                    error.__class__.__name__,
                ]
            )
        )
        return runtime_report, None

    runtime_report = _runtime_report_from_records(
        selected,
        records=records,
        provider_usage=result.usage,
    )
    return runtime_report, result.translated_text


def _runtime_report_from_records(
    selected: _SelectedRuntimeUnit,
    *,
    records: Sequence[Mapping[str, object]],
    provider_usage: Any,
) -> dict[str, Any]:
    glossary_record = _first_glossary_provider_record(records)
    validation = {
        "status": "skipped",
        "reason_codes": ["issue_675_glossary_provider_call_missing"],
        "expected_count": len(selected.source_blocks),
    }
    finish_reason = "Unknown"
    if glossary_record is not None:
        content, finish_reason = _provider_response_content(glossary_record)
        validation = _validate_runtime_provider_content(
            content,
            expected_count=len(selected.source_blocks),
            request_record=glossary_record,
        )
    usage = _usage_payload(provider_usage)
    return {
        "status": "ready"
        if glossary_record is not None and validation.get("status") == "pass"
        else "no_go",
        "reason_codes": []
        if glossary_record is not None and validation.get("status") == "pass"
        else list(validation.get("reason_codes", [])),
        "provider_call_observed": glossary_record is not None,
        "provider_call_count": len(records),
        "glossary_provider_call_index": (
            records.index(glossary_record) if glossary_record in records else None
        ),
        "finish_reason": finish_reason,
        "provider_usage": usage,
        "structural_validation": validation,
    }


def _fake_prepared_glossary_provider(request: Any) -> PreparedGlossaryProviderResponse:
    packet = request.packet
    payload = _fake_package_from_packet(packet)
    return PreparedGlossaryProviderResponse(
        payload=payload,
        metadata={
            "provider_status": "fake_ready",
            "provider_model": packet.get("provider_model"),
            "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
            "provider_usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "finish_reason": "fake",
            "reason_codes": [],
        },
    )


def _live_prepared_glossary_provider(
    config: GlossaryEffectivenessSmokeConfig,
    *,
    api_key: str,
    ledger: _ProviderCallLedger,
    provider_io_sink: ProviderIODiagnosticSink | None,
):
    provider = build_deepseek_prepared_glossary_provider(
        api_key=api_key,
        base_url=config.provider_base_url,
        transport=_LedgerTransport(api_key=api_key, ledger=ledger),
        timeout_seconds=120.0,
        retry_attempts=1,
        retry_delay_seconds=0.0,
        config=PreparedGlossaryDeepSeekProviderConfig(
            provider_model=config.provider_model,
        ),
    )

    def call(request: Any) -> PreparedGlossaryProviderResponse:
        with capture_provider_io(
            provider_io_sink,
            job_id="issue-675-glossary-effectiveness-smoke",
            work_unit_id="prepared-glossary-prep",
            sequence=0,
        ):
            return provider(request)

    return call


def _live_runtime_translator(
    config: GlossaryEffectivenessSmokeConfig,
    *,
    api_key: str,
    ledger: _ProviderCallLedger,
) -> DeepSeekClient:
    return DeepSeekClient(
        api_key=api_key,
        model=config.runtime_model,
        base_url=config.provider_base_url,
        transport=_LedgerTransport(api_key=api_key, ledger=ledger),
        timeout_seconds=120.0,
        retry_attempts=1,
        retry_delay_seconds=0.0,
    )


def _fake_package_from_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    entries = []
    for index, candidate in enumerate(packet.get("candidates", [])):
        if not isinstance(candidate, Mapping):
            continue
        canonical = str(candidate.get("source_canonical") or "").strip()
        if not canonical:
            continue
        entry_id = str(candidate.get("entry_id") or f"entry:{index}")
        entries.append(
            {
                "source_entry_id": entry_id,
                "source_canonical": canonical,
                "aliases": list(_string_sequence(candidate.get("aliases"))),
                "evidence_refs": list(_string_sequence(candidate.get("evidence_refs"))),
                "source_unit_refs": list(
                    _int_sequence(candidate.get("source_unit_refs"))
                ),
                "source_block_refs": list(
                    _string_sequence(candidate.get("source_block_refs"))
                ),
                "target_canonical": "ru-glossary",
                "target_variants": ["ru-glossary-variant"],
                "forbidden_variants": [],
                "strategy": "metadata_only_fake",
                "confidence": 0.9,
                "needs_review": False,
                "reason_codes": [],
            }
        )
    return {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": "prepared:issue-675:fake",
        "source_language": packet.get("source_language", "en"),
        "target_language": packet.get("target_language", APPROVED_TARGET),
        "glossary_mode": "with_glossary",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": packet.get(
            "provider_model",
            DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL,
        ),
        "provider_run_id": "provider-run:issue-675-fake",
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


def _work_unit_from_plan_unit(unit: Any, *, target_language: str) -> PersistentWorkUnit:
    now = datetime(2026, 6, 17, tzinfo=UTC)
    source_text = unit.source_text
    return PersistentWorkUnit(
        id=f"issue-675:unit-{unit.sequence}",
        job_id="issue-675-glossary-effectiveness-smoke",
        sequence=int(unit.sequence),
        source_block_ids=tuple(unit.source_block_ids),
        source_object_key=f"issue-675/unit-{unit.sequence}.txt",
        source_text_hash=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        prompt_tier=str(getattr(unit.prompt_tier, "value", unit.prompt_tier)),
        source_language="en",
        target_language=target_language,
        status=PersistentWorkUnitStatus.TRANSLATING,
        translated_text=None,
        worker_id="issue-675",
        claim_token="issue-675",
        prompt_tokens=0,
        completion_tokens=0,
        cache_hit_tokens=0,
        cache_miss_tokens=0,
        attempt_count=0,
        max_attempts=1,
        retry_count=0,
        last_error=None,
        available_at=now,
        lease_until=None,
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=None,
    )


def _metadata_report(
    config: GlossaryEffectivenessSmokeConfig,
    *,
    diagnostics_dir: Path,
    source_sha256: str,
    attachment_metadata: Mapping[str, Any],
    validation_metadata: Mapping[str, Any],
    selected: _SelectedRuntimeUnit | None,
) -> dict[str, Any]:
    selection = _selection_metadata(selected)
    return {
        "schema_version": SCHEMA_VERSION,
        "issue": ISSUE_ID,
        "metadata_only": True,
        "raw_payload_included": False,
        "ordinary_report_raw_material_included": False,
        "release_readiness_claim_made": False,
        "input": {
            "path": str(config.input_path),
            "source": (
                "committed Project Gutenberg public-domain/permissive "
                "control fixture"
            ),
            "source_sha256_short": source_sha256[:12],
            "document_kind": DocumentFormat.EPUB.value,
        },
        "target_language": config.target_language,
        "provider": {
            "glossary_prep_model": config.provider_model,
            "runtime_model": config.runtime_model,
            "provider_base_url": config.provider_base_url,
            "max_calls": config.max_calls,
            "max_provider_reported_tokens_total": config.max_tokens_total,
            "provider_config_changed": False,
            "provider_key_material_included": False,
        },
        "diagnostics": {
            "diagnostics_dir": str(diagnostics_dir),
            "owner_only": True,
            "untracked_expected": True,
            "raw_capture_boundary": "owner_only_diagnostics_dir_only",
        },
        "prepared_package": {
            "attachment": dict(attachment_metadata),
            "validation": dict(validation_metadata),
        },
        "selection": selection,
        "cache": {
            "bypass_observed": bool(selection.get("cache_bypass_observed")),
            "cache_reuse_enabled": False,
        },
        "reason_codes": [],
    }


def _selection_metadata(selected: _SelectedRuntimeUnit | None) -> dict[str, Any]:
    if selected is None:
        return {
            "status": "missing",
            "reason_codes": ["issue_675_no_glossary_useful_pressure_safe_unit"],
        }
    event = selected.metadata_event
    prompt_context = event.get("prompt_context") if isinstance(event, Mapping) else None
    preflight = (
        event.get("battle_test_preflight") if isinstance(event, Mapping) else None
    )
    cache_policy = event.get("cache_policy") if isinstance(event, Mapping) else None
    return {
        "status": "ready",
        "unit_sequence": selected.work_unit.sequence,
        "source_block_count": len(selected.source_blocks),
        "source_character_count": sum(len(block) for block in selected.source_blocks),
        "battle_test_preflight": (
            dict(preflight) if isinstance(preflight, Mapping) else {}
        ),
        "prompt_context": (
            dict(prompt_context) if isinstance(prompt_context, Mapping) else {}
        ),
        "included_entry_ids": list(
            prompt_context.get("included_entry_ids", [])
            if isinstance(prompt_context, Mapping)
            else []
        ),
        "cache_policy": dict(cache_policy) if isinstance(cache_policy, Mapping) else {},
        "cache_bypass_observed": (
            isinstance(cache_policy, Mapping)
            and cache_policy.get("behavior") == "bypass_glossary_injected_cache"
        ),
        "glossary_context_rendered": True,
    }


def _validate_runtime_provider_content(
    content: str | None,
    *,
    expected_count: int,
    request_record: Mapping[str, object],
) -> dict[str, Any]:
    if not content:
        return {
            "status": "fail",
            "reason_codes": ["empty_provider_response_content"],
            "expected_count": expected_count,
        }
    request_payload = _provider_record_body_json(request_record, "request_body")
    uses_json = isinstance(request_payload, Mapping) and isinstance(
        request_payload.get("response_format"),
        Mapping,
    )
    if uses_json:
        result = json_translation_batch_to_xml_contract(
            content,
            expected_count=expected_count,
        )
    else:
        result = normalize_provider_translation_batch_contract(
            content,
            expected_count=expected_count,
        )
    if result.translated_texts is None:
        reason = (
            result.rejection_reason.value
            if result.rejection_reason is not None
            else "unknown_structural_validation_failure"
        )
        return {
            "status": "fail",
            "reason_codes": [reason],
            "expected_count": expected_count,
            "translated_count": 0,
        }
    return {
        "status": "pass",
        "reason_codes": [],
        "expected_count": expected_count,
        "translated_count": len(result.translated_texts),
        "normalized": result.normalized_text is not None,
    }


def _compliance_summary(
    selected: _SelectedRuntimeUnit | None,
    *,
    translated_text: str | None,
    structural_validation: Any,
    target_language: str,
) -> dict[str, Any]:
    if selected is None:
        return {
            "status": "skipped",
            "reason_codes": ["issue_675_no_selected_unit"],
            "metadata_only": True,
            "raw_payload_included": False,
        }
    prompt_context = selected.metadata_event.get("prompt_context")
    included_ids = (
        prompt_context.get("included_entry_ids", [])
        if isinstance(prompt_context, Mapping)
        else []
    )
    structural_passed = (
        isinstance(structural_validation, Mapping)
        and structural_validation.get("status") == "pass"
    )
    return validate_glossary_compliance(
        selected.prompt_context_entries,
        selected_entry_ids=included_ids,
        included_entry_ids=included_ids,
        source_text=selected.source_text,
        translated_text=translated_text,
        structural_validation_passed=structural_passed,
        target_language=target_language,
    )


def _overall_live_status(
    report: Mapping[str, Any],
    selected: _SelectedRuntimeUnit | None,
    runtime_report: Mapping[str, Any],
) -> str:
    validation = report.get("prepared_package", {}).get("validation", {})
    if not isinstance(validation, Mapping) or validation.get("status") != "ready":
        return "no_go"
    if selected is None:
        return "no_go"
    if runtime_report.get("status") != "ready":
        return "no_go"
    return "pass"


def _first_glossary_provider_record(
    records: Sequence[Mapping[str, object]],
) -> Mapping[str, object] | None:
    for record in records:
        request_payload = _provider_record_body_json(record, "request_body")
        if not isinstance(request_payload, Mapping):
            continue
        text = json.dumps(request_payload, ensure_ascii=False)
        if "<glossary_context" in text:
            return record
    return None


def _provider_response_content(
    record: Mapping[str, object],
) -> tuple[str | None, str]:
    response_payload = _provider_record_body_json(record, "response_body")
    if not isinstance(response_payload, Mapping):
        return None, "Unknown"
    choices = response_payload.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        return None, "Unknown"
    first = choices[0]
    if not isinstance(first, Mapping):
        return None, "Unknown"
    message = first.get("message")
    content = message.get("content") if isinstance(message, Mapping) else None
    finish_reason = first.get("finish_reason")
    return (
        str(content) if isinstance(content, str) else None,
        str(finish_reason) if isinstance(finish_reason, str) else "Unknown",
    )


def _provider_record_body_json(
    record: Mapping[str, object],
    key: str,
) -> Any:
    payload = record.get(key)
    if not isinstance(payload, Mapping):
        return None
    text = payload.get("text")
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _prepared_package_provider_usage(
    report: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    prepared = report.get("prepared_package")
    if not isinstance(prepared, Mapping):
        return None
    attachment = prepared.get("attachment")
    if not isinstance(attachment, Mapping):
        return None
    provider_usage = attachment.get("provider_usage")
    return provider_usage if isinstance(provider_usage, Mapping) else None


def _usage_total_tokens(usage: Mapping[str, Any] | object | None) -> int | None:
    if usage is None:
        return None
    total = (
        usage.get("total_tokens")
        if isinstance(usage, Mapping)
        else getattr(usage, "total_tokens", None)
    )
    if isinstance(total, bool):
        return None
    if isinstance(total, int):
        return total
    prompt = (
        usage.get("prompt_tokens")
        if isinstance(usage, Mapping)
        else getattr(usage, "prompt_tokens", None)
    )
    completion = (
        usage.get("completion_tokens")
        if isinstance(usage, Mapping)
        else getattr(usage, "completion_tokens", None)
    )
    if isinstance(prompt, int) and isinstance(completion, int):
        return prompt + completion
    return None


def _usage_payload(usage: Mapping[str, Any] | object | None) -> dict[str, int] | None:
    total = _usage_total_tokens(usage)
    if total is None:
        return None
    return {
        "prompt_tokens": int(
            usage.get("prompt_tokens")
            if isinstance(usage, Mapping)
            else getattr(usage, "prompt_tokens", 0)
            or 0
        ),
        "completion_tokens": int(
            usage.get("completion_tokens")
            if isinstance(usage, Mapping)
            else getattr(usage, "completion_tokens", 0)
            or 0
        ),
        "total_tokens": total,
    }


def _jsonl_sink(path: Path) -> ProviderIODiagnosticSink:
    def append(record: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")

    return append


def _validate_issue_boundary(
    config: GlossaryEffectivenessSmokeConfig,
    *,
    live: bool,
    allow_test_diagnostic_root: bool,
) -> None:
    if config.input_path != APPROVED_INPUT:
        raise ValueError("issue_675_input_not_approved")
    if config.target_language != APPROVED_TARGET:
        raise ValueError("issue_675_target_not_approved")
    if config.provider_model != DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL:
        raise ValueError("issue_675_provider_model_not_approved")
    if config.max_calls <= 0 or config.max_calls > DEFAULT_MAX_CALLS:
        raise ValueError("issue_675_call_cap_invalid")
    if (
        config.max_tokens_total <= 0
        or config.max_tokens_total > DEFAULT_MAX_TOKENS_TOTAL
    ):
        raise ValueError("issue_675_token_cap_invalid")
    if (
        config.max_candidates <= 0
        or config.max_candidates > DEFAULT_PREPARED_GLOSSARY_MAX_CANDIDATES
    ):
        raise ValueError("issue_675_candidate_cap_invalid")
    if (
        config.max_excerpt_chars <= 0
        or config.max_excerpt_chars > DEFAULT_MAX_EXCERPT_CHARS
    ):
        raise ValueError("issue_675_excerpt_bound_invalid")
    if (
        live
        and not allow_test_diagnostic_root
        and config.diagnostic_root != APPROVED_DIAGNOSTIC_ROOT
    ):
        raise ValueError("issue_675_diagnostic_root_not_approved")


def _assert_metadata_report_safe(report: Mapping[str, Any]) -> None:
    text = json.dumps(report, ensure_ascii=False, sort_keys=True)
    for pattern in _SECRET_PATTERNS:
        if pattern in text:
            raise ValueError("issue_675_metadata_report_unsafe")


def _report_reason_codes(report: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(code) for code in report.get("reason_codes", []) if str(code))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _dedupe(values: Sequence[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value) for value in values if str(value)))


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item.strip())


def _int_sequence(value: Any) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    result: list[int] = []
    for item in value:
        if isinstance(item, int) and not isinstance(item, bool):
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
        description="Run the #675 bounded glossary effectiveness smoke.",
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timestamp")
    parser.add_argument("--input", default=str(APPROVED_INPUT))
    parser.add_argument("--target", default=APPROVED_TARGET)
    parser.add_argument("--diagnostic-root", default=str(APPROVED_DIAGNOSTIC_ROOT))
    parser.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS)
    parser.add_argument(
        "--max-tokens-total",
        type=int,
        default=DEFAULT_MAX_TOKENS_TOTAL,
    )
    parser.add_argument("--model", default=DEFAULT_PREPARED_GLOSSARY_PROVIDER_MODEL)
    parser.add_argument(
        "--runtime-model",
        default=os.getenv("DEEPSEEK_MODEL", DEFAULT_RUNTIME_MODEL),
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_PROVIDER_BASE_URL),
    )
    args = parser.parse_args(argv)
    config = GlossaryEffectivenessSmokeConfig(
        input_path=Path(args.input),
        target_language=args.target,
        diagnostic_root=Path(args.diagnostic_root),
        max_calls=args.max_calls,
        max_tokens_total=args.max_tokens_total,
        provider_model=args.model,
        runtime_model=args.runtime_model,
        provider_base_url=args.base_url,
    )
    if args.live:
        api_key = load_env_api_key()
        result = run_live_smoke(
            config,
            api_key=api_key,
            timestamp=args.timestamp,
        )
    else:
        result = run_fake_dry_preflight(config, timestamp=args.timestamp)
    print(
        json.dumps(
            {
                "status": result.status,
                "reason_codes": list(result.reason_codes),
                "diagnostics_dir": str(result.diagnostics_dir),
                "metadata_report_path": str(result.metadata_report_path),
                "selected_unit_sequence": result.selected_unit_sequence,
                "live_provider_calls": result.live_provider_calls,
                "provider_tokens_total": (
                    result.provider_tokens_total
                    if result.provider_tokens_total is not None
                    else "Unknown"
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.status in {"ready", "pass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
