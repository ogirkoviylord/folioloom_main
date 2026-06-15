from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from translator_service.book_profile import detect_book_profile
from translator_service.format_adapters.epub import plan_epub_translation
from translator_service.format_adapters.txt import plan_txt_translation
from translator_service.glossary_candidate_reducer import (
    glossary_candidate_reduction_payload,
    reduce_glossary_candidates,
)
from translator_service.glossary_compliance import validate_glossary_compliance
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossarySnapshot,
    glossary_snapshot_signature,
)
from translator_service.glossary_prompt_context import (
    GlossaryPromptContextConfig,
    format_glossary_prompt_context,
    glossary_prompt_context_metadata_payload,
)
from translator_service.glossary_scanner import scan_glossary_candidates
from translator_service.glossary_selection import (
    GLOSSARY_SELECTION_POLICY_VERSION,
    GlossarySelectionBudget,
    glossary_selection_metadata_payload,
    select_glossary_subset_for_work_unit,
)
from translator_service.glossary_terminology_policy import (
    TerminologyPolicy,
    TerminologyPolicyRegistry,
    validate_terminology_policy,
)
from translator_service.model_output_safety import validate_model_output_safety
from translator_service.output_contracts import (
    normalize_provider_translation_batch_contract,
)
from translator_service.protected_text import protect_text
from translator_service.translation_contract_snapshot import (
    build_translation_contract_snapshot,
    translation_contract_snapshot_signature,
    translation_policy_signature_context_from_snapshot,
)
from translator_service.translation_policy import (
    GlossaryPromptPolicyAdapterConfig,
    GlossaryPromptPolicyAdapterStatus,
    ProviderOutputFormat,
    build_glossary_prompt_policy_adapter_decision,
    build_system_prompt,
    build_translation_policy,
    glossary_prompt_policy_adapter_decision_payload,
    translation_policy_signature_context_payload,
)

SMOKE_SCHEMA_VERSION = "glossary-runtime-provider-smoke-v1"
PRESSURE_SCHEMA_VERSION = "glossary-runtime-pressure-v1"
PRESSURE_FALLBACK_SCHEMA_VERSION = "glossary-runtime-pressure-fallback-v1"
PAIRED_REHEARSAL_SCHEMA_VERSION = "glossary-runtime-paired-rehearsal-v1"
PROVIDER_EVIDENCE_PROTOCOL_SCHEMA_VERSION = (
    "glossary-provider-evidence-protocol-v1"
)
POLICY_PROVIDER_EVIDENCE_PREFLIGHT_SCHEMA_VERSION = (
    "glossary-policy-provider-evidence-fake-dry-preflight-v1"
)
POLICY_PROVIDER_EVIDENCE_LIVE_SCHEMA_VERSION = (
    "glossary-policy-provider-evidence-live-smoke-v1"
)
EPUB_RUNTIME_UNIT_SELECTION_SCHEMA_VERSION = (
    "glossary-epub-runtime-unit-selection-v1"
)
EPUB_RUNTIME_UNIT_SELECTION_POLICY = (
    "local_owner_only_first_glossary_useful_pressure_safe_epub_unit_v1"
)
TARGET_METADATA_FIXTURE_SCHEMA_VERSION = (
    "glossary-runtime-target-metadata-fixture-v1"
)
TARGET_METADATA_FIXTURE_POLICY = (
    "local_owner_only_approved_epub_target_metadata_overlay_v1"
)
PRESSURE_FALLBACK_THRESHOLD_POLICY = (
    "conservative_local_test_path;runtime_rollout_thresholds=TBD"
)
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_CALLS = 5
DEFAULT_MAX_TOKENS_TOTAL = 50_000
DEFAULT_MAX_COMPLETION_TOKENS = 1_800
DEFAULT_PROMPT_TOKEN_RESERVATION_MULTIPLIER = 2.0
DEFAULT_MAX_FRAGMENT_CHARS = 2_400
DEFAULT_RUNTIME_SELECTION_PROMPT_TOKENS = 360
DEFAULT_RUNTIME_SELECTION_MAX_ENTRIES = 12
DEFAULT_RUNTIME_SELECTION_MAX_DIAGNOSTIC_ENTRIES = 2
DEFAULT_RUNTIME_CONTEXT_PROMPT_TOKENS = 1_200
DEFAULT_RUNTIME_CONTEXT_MAX_ENTRIES = 12
DEFAULT_RUNTIME_CONTEXT_MAX_CHARACTERS = 6_000
HIGH_PRESSURE_EPUB_CONTEXT_PROMPT_TOKEN_CAP = 420
HIGH_PRESSURE_EPUB_CONTEXT_MAX_ENTRIES = 4
HIGH_PRESSURE_EPUB_MIN_SELECTION_PROMPT_TOKENS = 120
DEFAULT_PRESSURE_FALLBACK_MAX_EPUB_SOURCE_BLOCKS = 12
DEFAULT_PRESSURE_FALLBACK_MAX_EPUB_PROTECTED_MARKERS = 80
DEFAULT_DIAGNOSTIC_ROOT = Path(
    "outputs/issue-477-bounded-glossary-runtime-provider-smoke"
)
ISSUE_507_ID = "507"
ISSUE_507_MAX_CALLS = 4
ISSUE_507_DIAGNOSTIC_ROOT = Path(
    "outputs/issue-507-post-505-control-epub-glossary-live"
)
ISSUE_534_ID = "534"
ISSUE_534_MAX_CALLS = 6
ISSUE_534_MAX_TOKENS_TOTAL = 60_000
ISSUE_534_DIAGNOSTIC_ROOT = Path(
    "outputs/issue-534-bounded-policy-provider-evidence-smoke"
)
ISSUE_559_ID = "559"
ISSUE_559_EFFECTIVE_MAX_CALLS = 2
ISSUE_559_ABSOLUTE_MAX_CALLS = 4
ISSUE_559_MAX_TOKENS_TOTAL = 60_000
ISSUE_559_DIAGNOSTIC_ROOT = Path(
    "outputs/issue-559-real-epub-glossary-live"
)
ISSUE_559_INPUT_TARGETS = (
    (
        Path(
            "outputs/gutenberg-control-candidates/"
            "wonderful_wizard_of_oz_gutenberg55_noimages.en.epub"
        ),
        "ru",
    ),
)
ISSUE_559_TARGET_METADATA_FIXTURE_PATH = Path(
    "outputs/issue-oz-gutenberg-epub-glossary-live/"
    "oz-scarecrow-target-metadata-fixture.json"
)
ISSUE_575_ID = "575"
ISSUE_575_MAX_CALLS = 4
ISSUE_575_MAX_TOKENS_TOTAL = 60_000
ISSUE_575_DIAGNOSTIC_ROOT = Path(
    "outputs/glossary-battle-test/issue-575-post-571-matrix"
)
ISSUE_586_ID = "586"
ISSUE_586_DIAGNOSTIC_ROOT = Path(
    "outputs/glossary-battle-test/issue-586-post-584-adversarial-live"
)
ISSUE_575_INPUT_TARGETS = (
    (Path("test_samples/glossary_adversarial_terms.en.txt"), "ru"),
    (Path("test_samples/glossary_adversarial_terms.en.txt"), "uk"),
)
ISSUE_575_TARGET_METADATA_FIXTURE_PATH = Path(
    "test_samples/glossary_targets/"
    "glossary_adversarial_terms.runtime-glossary-targets.json"
)
LANGUAGE_POLICY_PACKAGE_FIXTURES = (
    Path("test_samples/language_policy_packages/ru_uk_v1.json"),
    Path("test_samples/language_policy_packages/contrast_casefold_v1.json"),
)
DEFAULT_TARGET_METADATA_FIXTURE_PATH = Path(
    "test_samples/glossary_targets/"
    "gutenberg_time_machine_noimages.runtime-glossary-targets.json"
)
APPROVED_INPUT_TARGETS = (
    (Path("test_samples/russian_profile_regression.en-ru.txt"), "ru"),
    (Path("test_samples/ukrainian_profile_regression.en-uk.txt"), "uk"),
    (Path("test_samples/sample_book.en.txt"), "ru"),
    (Path("private_fixtures/pg78824-images-3.epub"), "ru"),
    (Path("private_fixtures/pg78824-images-3.epub"), "uk"),
)
APPROVED_OWNER_TEST_INPUT_TARGETS = (
    (Path("test_samples/gutenberg_time_machine_noimages.en.epub"), "ru"),
    (Path("test_samples/gutenberg_time_machine_noimages.en.epub"), "uk"),
)
TARGET_METADATA_FIXTURE_MAX_ENTRIES_PER_TARGET = 16
TARGET_METADATA_FIXTURE_MAX_ALIASES = 8
TARGET_METADATA_FIXTURE_MAX_TARGET_VARIANTS = 8
TARGET_METADATA_FIXTURE_MAX_FIELD_CHARS = 120
TARGET_METADATA_FIXTURE_RAW_KEYS = frozenset(
    {
        "api_key",
        "auth_material",
        "authorization",
        "bounded_source_excerpt",
        "prompt",
        "prompt_body",
        "provider_request",
        "provider_response",
        "raw_passage",
        "raw_source",
        "raw_source_text",
        "request_body",
        "response_body",
        "source_excerpt",
        "source_text",
        "target_text",
        "translated_excerpt",
        "translated_text",
        "translation_text",
    }
)
POLICY_EVIDENCE_RAW_KEYS = TARGET_METADATA_FIXTURE_RAW_KEYS | frozenset(
    {
        "api_key",
        "auth_material",
        "authorization",
        "bounded_source_excerpt",
        "prompt",
        "prompt_body",
        "provider_request",
        "provider_response",
        "raw_provider_response",
        "raw_source_passage",
        "raw_translation",
        "request_body",
        "response_body",
        "source_text",
        "system_prompt",
        "translated_passage",
        "translated_text",
        "user_prompt",
    }
)
TARGET_METADATA_FIXTURE_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "fixture_id",
        "input_path",
        "source_language",
        "scope",
        "owner_approved",
        "targets",
    }
)
TARGET_METADATA_FIXTURE_TARGET_KEYS = frozenset({"entries"})
TARGET_METADATA_FIXTURE_ENTRY_KEYS = frozenset(
    {
        "entry_id",
        "source_canonical",
        "aliases",
        "target_canonical",
        "target_variants",
        "strategy",
        "status",
        "confidence",
    }
)


class ChatProvider(Protocol):
    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ) -> ChatCallResult:
        pass


@dataclass(frozen=True)
class SmokeConfig:
    issue_id: str = "477"
    input_targets: tuple[tuple[Path, str], ...] = APPROVED_INPUT_TARGETS
    diagnostic_root: Path = DEFAULT_DIAGNOSTIC_ROOT
    provider_model: str = DEFAULT_MODEL
    provider_base_url: str = DEFAULT_BASE_URL
    max_calls: int = DEFAULT_MAX_CALLS
    max_tokens_total: int = DEFAULT_MAX_TOKENS_TOTAL
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS
    max_fragment_chars: int = DEFAULT_MAX_FRAGMENT_CHARS
    prompt_token_reservation_multiplier: float = (
        DEFAULT_PROMPT_TOKEN_RESERVATION_MULTIPLIER
    )
    raw_text_capture: bool = True
    fake: bool = False
    target_metadata_fixture_path: Path | None = None
    paired_glossary_off: bool = False


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
class RuntimeSmokePackage:
    input_path: Path
    input_id: str
    target_language: str
    document_format: str
    fragment_count: int
    character_count: int
    unit_sequence: int
    source_block_ids: tuple[str, ...]
    source_text: str
    protected_text: str
    required_markers: tuple[tuple[str, ...], ...]
    glossary_plan: Mapping[str, Any]
    adapter_metadata: Mapping[str, Any]
    prompt_context_text: str
    prompt_context_metadata: Mapping[str, Any]
    selection_metadata: Mapping[str, Any]
    glossary_entry_count: int
    glossary_evidence_count: int
    reducer_metadata: Mapping[str, Any]
    glossary_entries: tuple[GlossaryEntry | Mapping[str, Any], ...] = ()


class RuntimePackageSelectionError(ValueError):
    def __init__(self, code: str, *, metadata: Mapping[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.metadata = dict(metadata or {})


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
            "thinking": {"type": "disabled"},
        }
        body = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self._base_url}/chat/completions",
            data=body,
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
            response_bytes = error.read()
            elapsed = time.monotonic() - start
            return ChatCallResult(
                ok=False,
                content="",
                usage={},
                finish_reason=None,
                http_status=error.code,
                elapsed_seconds=elapsed,
                request_payload=request_payload,
                response_text=_decode_response(response_bytes),
                error_type=error.__class__.__name__,
                error_message=f"HTTP {error.code}",
            )
        except (TimeoutError, URLError) as error:
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
                error_message=error.__class__.__name__,
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


class FakeRuntimeProvider:
    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ) -> ChatCallResult:
        source_text = _first_translation_block_text(user_prompt)
        content = (
            "<translation_batch>"
            f'<translation_block id="0">'
            f"{html.escape(source_text, quote=False)}"
            "</translation_block>"
            "</translation_batch>"
        )
        return ChatCallResult(
            ok=True,
            content=content,
            usage={
                "prompt_tokens": estimate_tokens(system_prompt + user_prompt),
                "completion_tokens": estimate_tokens(content),
                "total_tokens": estimate_tokens(system_prompt + user_prompt + content),
            },
            finish_reason="stop",
            http_status=200,
            elapsed_seconds=0.0,
            request_payload={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_completion_tokens,
            },
            response_payload={"choices": [{"message": {"content": content}}]},
            response_text=json.dumps({"choices": [{"message": {"content": content}}]}),
        )


def run_smoke(
    config: SmokeConfig,
    *,
    provider: ChatProvider,
    repo_root: Path | None = None,
    metadata_report_path: Path | None = None,
) -> dict[str, Any]:
    _validate_config(config)
    repo_root = (repo_root or Path.cwd()).resolve()
    diagnostic_dir = _timestamped_diagnostic_dir(config.diagnostic_root)
    diagnostic_dir.mkdir(parents=True, exist_ok=False)
    package_results = [
        _build_package_or_skip(path, target, config=config, repo_root=repo_root)
        for path, target in config.input_targets
    ]

    call_summaries: list[dict[str, Any]] = []
    calls_made = 0
    reserved_tokens = 0
    observed_tokens: int | None = 0

    for package_result in package_results:
        if isinstance(package_result, Mapping):
            call_summaries.append(dict(package_result))
            continue
        package_pairs = [(package_result, "glossary_on")]
        if config.paired_glossary_off:
            package_pairs.append(
                (build_glossary_off_runtime_package(package_result), "glossary_off")
            )

        for package, side in package_pairs:
            call_state = _run_smoke_call(
                package=package,
                side=side,
                config=config,
                provider=provider,
                diagnostic_dir=diagnostic_dir,
                calls_made=calls_made,
                reserved_tokens=reserved_tokens,
                observed_tokens=observed_tokens,
            )
            call_summaries.append(call_state.summary)
            calls_made = call_state.calls_made
            reserved_tokens = call_state.reserved_tokens
            observed_tokens = call_state.observed_tokens
            if call_state.stop:
                break
        if call_summaries and call_summaries[-1].get("observed_over_cap") is True:
            break

    report = {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "pressure_schema_version": PRESSURE_SCHEMA_VERSION,
        "status": _smoke_status(call_summaries),
        "mode": "fake" if config.fake else "live",
        "created_at": datetime.now(UTC).isoformat(),
        "approval": _approval_payload(config),
        "diagnostic_dir": str(diagnostic_dir),
        "calls_made": calls_made,
        "reserved_tokens": reserved_tokens,
        "observed_tokens": _unknown_int(observed_tokens),
        "calls": call_summaries,
        "confirmed": _confirmed_items(config, call_summaries),
        "unknown": _unknown_items(config, call_summaries),
        "tbd": [
            "runtime glossary rollout remains TBD",
            "glossary-aware cache reuse remains TBD",
            "release-version diagnostics retention/deletion/consent remains TBD",
            "semantic truth such as gender/name identity remains evidence-driven",
            "RU/UK morphology strategy remains TBD",
        ],
        "recommendation": _recommendation(config, call_summaries),
    }
    _write_json(diagnostic_dir / "manifest.json", report)
    if metadata_report_path is not None:
        metadata_report_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_report_path.write_text(
            render_metadata_report(report),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": report["mode"],
                "diagnostic_dir": report["diagnostic_dir"],
                "calls_made": report["calls_made"],
                "observed_tokens": report["observed_tokens"],
                "recommendation": report["recommendation"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return report


@dataclass(frozen=True)
class SmokeCallState:
    summary: dict[str, Any]
    calls_made: int
    reserved_tokens: int
    observed_tokens: int | None
    stop: bool = False


def _run_smoke_call(
    *,
    package: RuntimeSmokePackage,
    side: str,
    config: SmokeConfig,
    provider: ChatProvider,
    diagnostic_dir: Path,
    calls_made: int,
    reserved_tokens: int,
    observed_tokens: int | None,
) -> SmokeCallState:
    system_prompt, user_prompt, request_text = build_runtime_prompt(package)
    estimated_prompt_tokens = estimate_tokens(system_prompt + user_prompt)
    reservation = reserve_tokens(
        estimated_prompt_tokens=estimated_prompt_tokens,
        max_completion_tokens=config.max_completion_tokens,
        prompt_token_multiplier=config.prompt_token_reservation_multiplier,
    )
    if calls_made >= config.max_calls:
        return SmokeCallState(
            _skipped_call_summary(
                package,
                "skipped_max_calls",
                side=side,
                config=config,
                estimated_prompt_tokens=estimated_prompt_tokens,
                reservation=reservation,
            ),
            calls_made,
            reserved_tokens,
            observed_tokens,
        )
    if (
        reserved_tokens + reservation > config.max_tokens_total
        or (
            observed_tokens is not None
            and observed_tokens + reservation > config.max_tokens_total
        )
    ):
        return SmokeCallState(
            _skipped_call_summary(
                package,
                "skipped_token_budget",
                side=side,
                config=config,
                estimated_prompt_tokens=estimated_prompt_tokens,
                reservation=reservation,
                reserved_tokens=reserved_tokens,
                observed_tokens_before_call=_unknown_int(observed_tokens),
            ),
            calls_made,
            reserved_tokens,
            observed_tokens,
        )

    calls_made += 1
    reserved_tokens += reservation
    call_index = calls_made
    result = provider.chat(
        model=config.provider_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_completion_tokens=config.max_completion_tokens,
    )
    usage_tokens = _usage_total_tokens(result.usage)
    observed_over_cap = False
    if usage_tokens is None:
        observed_tokens = None
    elif observed_tokens is not None:
        observed_tokens += usage_tokens
        observed_over_cap = observed_tokens > config.max_tokens_total
    validation = validate_runtime_response(result, package=package)
    glossary_compliance = _runtime_glossary_compliance_summary(
        result,
        package=package,
        validation=validation,
    )
    summary = _call_summary(
        package=package,
        side=side,
        config=config,
        call_index=call_index,
        estimated_prompt_tokens=estimated_prompt_tokens,
        reservation=reservation,
        result=result,
        validation=validation,
        glossary_compliance=glossary_compliance,
        observed_over_cap=observed_over_cap,
    )
    _write_json(
        diagnostic_dir / f"call-{call_index:02d}-{package.input_id}-{side}.json",
        _call_diagnostic(
            package=package,
            side=side,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            request_text=request_text,
            result=result,
            validation_summary=summary["validation"],
            glossary_compliance=summary["glossary_compliance"],
            raw_text_capture=config.raw_text_capture,
            pressure_summary=summary["pressure_summary"],
        ),
    )
    return SmokeCallState(
        summary,
        calls_made,
        reserved_tokens,
        observed_tokens,
        stop=observed_over_cap,
    )


def build_runtime_prompt(package: RuntimeSmokePackage) -> tuple[str, str, str]:
    request_text = _format_translation_request_text(
        [package.protected_text],
        source_language_hints=["en"],
        glossary_prompt_context=package.prompt_context_text,
    )
    policy = build_translation_policy(
        text=request_text,
        source_language="en",
        target_language=package.target_language,
        service_glossary_context_present=bool(package.prompt_context_text),
    )
    system_prompt = build_system_prompt(
        policy,
        provider_output_format=ProviderOutputFormat.DEFAULT,
        expected_batch_count=1,
    )
    return system_prompt, _wrap_untrusted_document_content(request_text), request_text


def validate_runtime_response(
    result: ChatCallResult,
    *,
    package: RuntimeSmokePackage,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if result.finish_reason in {"length", "max_tokens"}:
        issues.append(_issue("truncated_output", "finish_reason"))
    if not result.ok:
        issues.append(_issue("provider_error", "http_status"))
    if not result.content.strip():
        issues.append(_issue("empty_content", "content"))
    safety = validate_model_output_safety(result.content)
    if safety.reason is not None:
        issues.append(_issue("unsafe_model_output", "content"))
    batch_validation = normalize_provider_translation_batch_contract(
        result.content,
        expected_count=1,
        required_markers=package.required_markers,
    )
    if batch_validation.rejection_reason is not None:
        issues.append(
            _issue(batch_validation.rejection_reason.value, "translation_batch")
        )
    return {
        "valid": not issues,
        "issue_count": len(issues),
        "issue_codes": [issue["code"] for issue in issues],
        "issues": issues,
        "translated_block_count": (
            len(batch_validation.translated_texts)
            if batch_validation.translated_texts is not None
            else 0
        ),
    }


def build_glossary_off_runtime_package(
    package: RuntimeSmokePackage,
) -> RuntimeSmokePackage:
    return replace(
        package,
        glossary_plan={
            "schema_version": "glossary-runtime-shadow-plan-v1",
            "enabled": False,
            "status": "disabled",
            "fallback_reason": "glossary_off_baseline",
            "work_unit_plans": [],
            "runtime_integration": {
                "normal_translation_prompts_changed": False,
                "live_provider_calls_allowed": False,
                "durable_state_mutation_allowed": False,
                "cache_mutation_allowed": False,
                "fallback_action": "use_existing_translation_path",
            },
        },
        adapter_metadata={
            "status": "disabled",
            "selected_entry_ids": [],
            "cache_policy": {
                "behavior": "default_runtime_cache",
                "cache_get_allowed": True,
                "cache_put_allowed": True,
            },
            "work_unit_selection_signature": "glossary-selection:none",
        },
        prompt_context_text="",
        prompt_context_metadata=_empty_prompt_context_metadata(
            reason="glossary_off_baseline",
        ),
        selection_metadata={
            "source_block_ids": list(package.source_block_ids),
            "work_unit_sequence": package.unit_sequence,
            "prompt_budget_tokens": 0,
            "estimated_prompt_tokens": 0,
            "budget_exceeded": False,
            "selected_entries": [],
            "dropped_entries": [],
            "selection_signature": "glossary-selection:none",
        },
        glossary_entry_count=0,
        glossary_evidence_count=0,
        reducer_metadata={},
    )


def run_fake_paired_epub_rehearsal(
    glossary_on_package: RuntimeSmokePackage,
    *,
    config: SmokeConfig,
    provider: FakeRuntimeProvider | None = None,
) -> dict[str, Any]:
    if glossary_on_package.document_format != "epub":
        raise ValueError("paired rehearsal requires an EPUB runtime package")
    if provider is not None and not isinstance(provider, FakeRuntimeProvider):
        raise ValueError("paired rehearsal requires a fake provider stub")
    provider = provider or FakeRuntimeProvider()
    glossary_off_package = build_glossary_off_runtime_package(glossary_on_package)
    glossary_on = _fake_rehearsal_side_summary(
        glossary_on_package,
        side="glossary_on",
        config=config,
        provider=provider,
    )
    glossary_off = _fake_rehearsal_side_summary(
        glossary_off_package,
        side="glossary_off",
        config=config,
        provider=provider,
    )
    sides = [glossary_on, glossary_off]
    status = (
        "completed"
        if all(item["status"] == "validated" for item in sides)
        else "completed_with_failures"
    )
    return {
        "schema_version": PAIRED_REHEARSAL_SCHEMA_VERSION,
        "mode": "fake",
        "status": status,
        "input_id": glossary_on_package.input_id,
        "target_language": glossary_on_package.target_language,
        "document_format": glossary_on_package.document_format,
        "unit_sequence": glossary_on_package.unit_sequence,
        "source_block_id_count": len(glossary_on_package.source_block_ids),
        "provider_stub": provider.__class__.__name__,
        "live_provider_calls_allowed": False,
        "quality_claims_made": False,
        "raw_payload_included": False,
        "ordinary_artifact_safety": {
            "source_text_included": False,
            "prompt_body_included": False,
            "provider_body_included": False,
            "translated_body_included": False,
            "api_key_or_auth_material_included": False,
        },
        "pairs": {
            "glossary_on": glossary_on,
            "glossary_off": glossary_off,
        },
        "confirmed": [
            "fake paired rehearsal built glossary-on and glossary-off metadata",
            "glossary-on enabled/test-path cache policy bypass is visible",
            "glossary-off baseline default cache policy is visible",
            "metadata report omits raw source, prompt, provider and translation bodies",
        ],
        "unknown": [
            "provider compliance is Unknown because no live provider calls were made",
            (
                "translation quality is Unknown because fake outputs are not "
                "quality evidence"
            ),
        ],
        "tbd": [
            "owner go/no-go for bounded live paired EPUB smoke remains TBD",
            "runtime glossary rollout remains TBD",
            "glossary-aware cache reuse remains TBD",
        ],
    }


def _fake_rehearsal_side_summary(
    package: RuntimeSmokePackage,
    *,
    side: str,
    config: SmokeConfig,
    provider: ChatProvider,
) -> dict[str, Any]:
    system_text, user_text, _request_text = build_runtime_prompt(package)
    estimated_prompt_tokens = estimate_tokens(system_text + user_text)
    reservation = reserve_tokens(
        estimated_prompt_tokens=estimated_prompt_tokens,
        max_completion_tokens=config.max_completion_tokens,
        prompt_token_multiplier=config.prompt_token_reservation_multiplier,
    )
    result = provider.chat(
        model=config.provider_model,
        system_prompt=system_text,
        user_prompt=user_text,
        max_completion_tokens=config.max_completion_tokens,
    )
    validation = validate_runtime_response(result, package=package)
    glossary_compliance = _runtime_glossary_compliance_summary(
        result,
        package=package,
        validation=validation,
    )
    pressure_summary = build_runtime_pressure_summary(
        package,
        config=config,
        estimated_prompt_tokens=estimated_prompt_tokens,
        reserved_tokens=reservation,
    )
    cache_policy = package.adapter_metadata.get("cache_policy") or {}
    return {
        "side": side,
        "status": "validated" if result.ok and validation["valid"] else "failed",
        "finish_reason": result.finish_reason or "Unknown",
        "http_status": result.http_status,
        "usage": dict(result.usage),
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "reserved_tokens": reservation,
        "validation": dict(validation),
        "glossary_compliance": glossary_compliance,
        "cache_policy": {
            "behavior": cache_policy.get("behavior", "Unknown"),
            "cache_get_allowed": cache_policy.get("cache_get_allowed", "Unknown"),
            "cache_put_allowed": cache_policy.get("cache_put_allowed", "Unknown"),
        },
        "prompt_context": {
            "included_entry_count": len(
                package.prompt_context_metadata.get("included_entry_ids") or ()
            ),
            "omitted_entry_count": len(
                package.prompt_context_metadata.get("omitted_entries") or ()
            ),
            "pressure_fallback_action": pressure_summary["fallback"][
                "pressure_fallback_action"
            ],
            "pressure_fallback_reason_codes": pressure_summary["fallback"][
                "pressure_fallback_reason_codes"
            ],
            "budget_policy": pressure_summary["budget_tuning"]["policy"],
            "budget_reason_codes": pressure_summary["budget_tuning"][
                "reason_codes"
            ],
        },
        "pressure_summary": pressure_summary,
        "raw_payload_included": False,
    }


def provider_evidence_protocol_payload() -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_EVIDENCE_PROTOCOL_SCHEMA_VERSION,
        "issue_id": "533",
        "live_followup_issue_id": ISSUE_534_ID,
        "candidate_inputs": [
            {
                "fixture_path": str(path),
                "rights_basis": "committed authorized/local synthetic fixture",
                "raw_material_policy": "ordinary_artifacts_metadata_only",
            }
            for path in LANGUAGE_POLICY_PACKAGE_FIXTURES
        ],
        "targets": ["ru", "uk", "de"],
        "unit_selection_rules": [
            "first policy-aware glossary-useful unit per approved target",
            "source term or alias must be present in the synthetic dry unit",
            "target canonical or variant metadata must exist",
            "structural validation and glossary compliance stay separate",
        ],
        "pairing": "paired glossary_on and glossary_off for each selected target",
        "caps_placeholders": {
            "max_calls": ISSUE_534_MAX_CALLS,
            "max_tokens_total": ISSUE_534_MAX_TOKENS_TOTAL,
            "max_targets": 3,
        },
        "provider_placeholders": {
            "provider": "DeepSeek-compatible provider",
            "model": DEFAULT_MODEL,
            "provider_config_changes_allowed": False,
        },
        "diagnostic_storage_pattern": (
            f"{ISSUE_534_DIAGNOSTIC_ROOT}/<timestamp>/ local owner-only untracked"
        ),
        "raw_text_capture_boundary": (
            "yes for the live issue only, and only inside the approved "
            "owner-only diagnostics directory"
        ),
        "ordinary_report_shape": {
            "allowed": [
                "package ids",
                "policy ids",
                "entry ids",
                "target language codes",
                "counts",
                "statuses",
                "reason codes",
                "signatures",
                "Unknown",
                "TBD",
            ],
            "forbidden": [
                "raw source text",
                "prompt bodies",
                "translated text bodies",
                "provider request bodies",
                "provider response bodies",
                "API keys or auth material",
            ],
        },
        "stop_conditions": [
            "package descriptor missing or invalid",
            "raw/prompt/provider/secret field detected in ordinary fixture",
            "fake/dry structural validation fails",
            "glossary_on compliance does not pass locally",
            "selected live packet would exceed approved call or token caps",
            "live provider usage is Unknown or over cap",
            "live structural validation fails",
        ],
        "not_approved": [
            "live provider calls in #533",
            "runtime rollout",
            "normal/default prompt integration",
            "glossary-aware cache reuse",
            "provider config/key changes",
            "DB/schema/state/scheduler/work-unit/storage/admin/retention changes",
            "release/privacy/legal/support claims",
        ],
        "metadata_only": True,
        "raw_payload_included": False,
    }


def run_policy_provider_evidence_preflight(
    *,
    repo_root: Path | None = None,
    metadata_report_path: Path | None = None,
) -> dict[str, Any]:
    repo_root = (repo_root or Path.cwd()).resolve()
    cases = _policy_evidence_cases(repo_root=repo_root)
    pairs = [_fake_policy_pair_summary(case) for case in cases]
    failed_pairs = [
        pair for pair in pairs if pair["status"] != "passed_fake_dry_preflight"
    ]
    report = {
        "schema_version": POLICY_PROVIDER_EVIDENCE_PREFLIGHT_SCHEMA_VERSION,
        "protocol": provider_evidence_protocol_payload(),
        "status": "passed" if not failed_pairs else "failed",
        "mode": "fake_dry",
        "created_at": datetime.now(UTC).isoformat(),
        "live_provider_calls_allowed": False,
        "provider_behavior": "Unknown",
        "translation_quality": "Unknown",
        "planned_live_issue_id": ISSUE_534_ID,
        "planned_live_call_count": len(pairs) * 2,
        "max_calls": ISSUE_534_MAX_CALLS,
        "max_tokens_total": ISSUE_534_MAX_TOKENS_TOTAL,
        "provider_model": DEFAULT_MODEL,
        "diagnostic_storage": str(ISSUE_534_DIAGNOSTIC_ROOT / "<timestamp>"),
        "targets": [pair["target_language"] for pair in pairs],
        "package_fixture_count": len(LANGUAGE_POLICY_PACKAGE_FIXTURES),
        "pairs": pairs,
        "ordinary_artifact_safety": {
            "metadata_only": True,
            "raw_source_text_included": False,
            "prompt_bodies_included": False,
            "translated_text_bodies_included": False,
            "provider_request_bodies_included": False,
            "provider_response_bodies_included": False,
            "api_keys_or_auth_material_included": False,
            "release_privacy_legal_support_claim_made": False,
        },
        "recommended_live_approval_template": _issue_534_approval_template(pairs),
        "confirmed": [
            "policy package fixtures loaded from committed authorized/local inputs",
            "fake/dry preflight selected one policy-aware unit per target",
            "glossary_on and glossary_off summaries are paired per target",
            "structural validation and glossary compliance are reported separately",
            "ordinary report is metadata-only",
            "no live provider call was made by this preflight",
        ],
        "unknown": [
            "live provider behavior is Unknown until #534 runs within approval caps",
            "provider-reported usage is Unknown because this is fake/dry only",
            (
                "translation quality is Unknown because fake/dry output is not "
                "quality evidence"
            ),
        ],
        "tbd": [
            "owner go/no-go after #534 remains TBD",
            "runtime glossary rollout remains TBD",
            "glossary-aware cache reuse remains TBD",
            "release-version diagnostic retention/deletion/consent remains TBD",
        ],
    }
    if metadata_report_path is not None:
        metadata_report_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_report_path.write_text(
            render_policy_provider_evidence_preflight_report(report),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": report["mode"],
                "planned_live_call_count": report["planned_live_call_count"],
                "targets": report["targets"],
                "provider_behavior": report["provider_behavior"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return report


def run_policy_provider_evidence_live_smoke(
    *,
    provider: ChatProvider,
    repo_root: Path | None = None,
    metadata_report_path: Path | None = None,
    diagnostic_root: Path = ISSUE_534_DIAGNOSTIC_ROOT,
    raw_text_capture: bool = True,
    preflight_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = (repo_root or Path.cwd()).resolve()
    preflight = dict(
        preflight_report
        if preflight_report is not None
        else run_policy_provider_evidence_preflight(repo_root=repo_root)
    )
    if preflight.get("status") != "passed":
        return _policy_live_blocked_report(
            preflight=preflight,
            reason_code="fake_dry_preflight_not_passed",
        )

    diagnostic_dir = _timestamped_diagnostic_dir(diagnostic_root)
    diagnostic_dir.mkdir(parents=True, exist_ok=False)
    cases = _policy_evidence_cases(repo_root=repo_root)
    call_summaries: list[dict[str, Any]] = []
    calls_made = 0
    reserved_tokens = 0
    observed_tokens: int | None = 0

    for case in cases:
        for side in ("glossary_on", "glossary_off"):
            if calls_made >= ISSUE_534_MAX_CALLS:
                call_summaries.append(
                    _policy_live_skipped_call_summary(
                        case,
                        side=side,
                        reason_code="skipped_max_calls",
                    )
                )
                continue
            prompt = _policy_live_prompt(case, side=side)
            estimated_prompt_tokens = estimate_tokens(
                prompt["system_prompt"] + prompt["user_prompt"]
            )
            reservation = reserve_tokens(
                estimated_prompt_tokens=estimated_prompt_tokens,
                max_completion_tokens=DEFAULT_MAX_COMPLETION_TOKENS,
                prompt_token_multiplier=(
                    DEFAULT_PROMPT_TOKEN_RESERVATION_MULTIPLIER
                ),
            )
            if reserved_tokens + reservation > ISSUE_534_MAX_TOKENS_TOTAL:
                call_summaries.append(
                    _policy_live_skipped_call_summary(
                        case,
                        side=side,
                        reason_code="skipped_token_budget",
                        estimated_prompt_tokens=estimated_prompt_tokens,
                        reserved_tokens=reserved_tokens,
                    )
                )
                continue

            calls_made += 1
            reserved_tokens += reservation
            result = provider.chat(
                model=DEFAULT_MODEL,
                system_prompt=prompt["system_prompt"],
                user_prompt=prompt["user_prompt"],
                max_completion_tokens=DEFAULT_MAX_COMPLETION_TOKENS,
            )
            usage_tokens = _usage_total_tokens(result.usage)
            observed_over_cap = False
            if usage_tokens is None:
                observed_tokens = None
            elif observed_tokens is not None:
                observed_tokens += usage_tokens
                observed_over_cap = observed_tokens > ISSUE_534_MAX_TOKENS_TOTAL

            validation = _policy_live_structural_validation(result)
            compliance = _policy_live_glossary_compliance(
                case,
                result=result,
                validation=validation,
            )
            summary = _policy_live_call_summary(
                case,
                side=side,
                call_index=calls_made,
                estimated_prompt_tokens=estimated_prompt_tokens,
                reserved_tokens=reserved_tokens,
                reservation=reservation,
                result=result,
                validation=validation,
                glossary_compliance=compliance,
                observed_over_cap=observed_over_cap,
            )
            call_summaries.append(summary)
            diagnostic_name = (
                f"call-{calls_made:02d}-{case['target_language']}-{side}.json"
            )
            _write_json(
                diagnostic_dir / diagnostic_name,
                _policy_live_call_diagnostic(
                    case,
                    side=side,
                    prompt=prompt,
                    result=result,
                    validation=validation,
                    glossary_compliance=compliance,
                    raw_text_capture=raw_text_capture,
                ),
            )
            if observed_over_cap:
                break
        if call_summaries and call_summaries[-1].get("observed_over_cap") is True:
            break

    report = {
        "schema_version": POLICY_PROVIDER_EVIDENCE_LIVE_SCHEMA_VERSION,
        "protocol_schema_version": PROVIDER_EVIDENCE_PROTOCOL_SCHEMA_VERSION,
        "issue_id": ISSUE_534_ID,
        "status": _policy_live_status(call_summaries),
        "mode": "live",
        "created_at": datetime.now(UTC).isoformat(),
        "fake_dry_preflight_status": preflight.get("status", "Unknown"),
        "diagnostic_dir": str(diagnostic_dir),
        "calls_made": calls_made,
        "max_calls": ISSUE_534_MAX_CALLS,
        "reserved_tokens": reserved_tokens,
        "observed_tokens": _unknown_int(observed_tokens),
        "max_tokens_total": ISSUE_534_MAX_TOKENS_TOTAL,
        "provider_model": DEFAULT_MODEL,
        "input_fixtures": [
            str(path) for path in LANGUAGE_POLICY_PACKAGE_FIXTURES
        ],
        "targets": [str(case["target_language"]) for case in cases],
        "calls": call_summaries,
        "ordinary_artifact_safety": {
            "metadata_only": True,
            "raw_source_text_included": False,
            "prompt_bodies_included": False,
            "translated_text_bodies_included": False,
            "provider_request_bodies_included": False,
            "provider_response_bodies_included": False,
            "api_keys_or_auth_material_included": False,
            "release_privacy_legal_support_claim_made": False,
        },
        "confirmed": _policy_live_confirmed_items(call_summaries),
        "unknown": _policy_live_unknown_items(call_summaries),
        "tbd": [
            "owner go/no-go after reviewing #534 evidence remains TBD",
            "runtime glossary rollout remains TBD",
            "glossary-aware cache reuse remains TBD",
            "release-version diagnostic retention/deletion/consent remains TBD",
            "translation quality remains TBD until owner-only quality review",
        ],
        "recommendation": _policy_live_recommendation(call_summaries),
    }
    _write_json(diagnostic_dir / "manifest.json", report)
    if metadata_report_path is not None:
        metadata_report_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_report_path.write_text(
            render_policy_provider_evidence_live_report(report),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "mode": report["mode"],
                "diagnostic_dir": report["diagnostic_dir"],
                "calls_made": report["calls_made"],
                "observed_tokens": report["observed_tokens"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return report


def render_policy_provider_evidence_live_report(
    report: Mapping[str, Any],
) -> str:
    rows = "\n".join(_policy_live_call_report_row(call) for call in report["calls"])
    if not rows:
        rows = (
            "| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown "
            "| Unknown | Unknown | Unknown | Unknown | Unknown |\n"
        )
    return (
        "# Policy Provider Evidence Live Smoke Report\n\n"
        "## Confirmed\n"
        f"{_markdown_list(report['confirmed'])}\n\n"
        "## Unknown\n"
        f"{_markdown_list(report['unknown'])}\n\n"
        "## TBD\n"
        f"{_markdown_list(report['tbd'])}\n\n"
        "## Approval Boundary\n"
        f"- Issue: #{report['issue_id']}\n"
        f"- Fake/dry preflight status: {report['fake_dry_preflight_status']}\n"
        f"- Inputs: {', '.join(report['input_fixtures'])}\n"
        f"- Targets: {', '.join(report['targets'])}\n"
        f"- Max calls: {report['max_calls']}\n"
        f"- Max tokens total: {report['max_tokens_total']}\n"
        f"- Provider/model: {report['provider_model']}\n"
        f"- Diagnostic storage: {report['diagnostic_dir']}\n\n"
        "## Live Results\n"
        "| Target | Side | Policy | Entry | Status | Finish reason | Usage tokens "
        "| Validation issue codes | Compliance status | Hits | Misses | Forbidden |\n"
        "| --- | --- | --- | --- | --- | --- | ---: | --- | --- | ---: "
        "| ---: | ---: |\n"
        f"{rows}\n\n"
        "## Token Shape\n"
        f"- Calls made: {report['calls_made']}\n"
        f"- Reserved tokens: {report['reserved_tokens']}\n"
        f"- Observed tokens: {report['observed_tokens']}\n\n"
        "## Recommendation\n"
        f"{report['recommendation']}\n"
    )


def render_policy_provider_evidence_preflight_report(
    report: Mapping[str, Any],
) -> str:
    pair_rows = "\n".join(
        _policy_preflight_pair_report_row(pair) for pair in report["pairs"]
    )
    side_rows = "\n".join(
        _policy_preflight_side_report_row(pair, side_name, side)
        for pair in report["pairs"]
        for side_name, side in pair["sides"].items()
    )
    approval = report["recommended_live_approval_template"]
    approved_inputs = ", ".join(approval["approved_inputs"])
    approved_targets = ", ".join(approval["targets"])
    return (
        "# Policy Provider Evidence Fake/Dry Preflight\n\n"
        "## Confirmed\n"
        f"{_markdown_list(report['confirmed'])}\n\n"
        "## Unknown\n"
        f"{_markdown_list(report['unknown'])}\n\n"
        "## TBD\n"
        f"{_markdown_list(report['tbd'])}\n\n"
        "## Protocol Boundary\n"
        f"- Schema: {report['protocol']['schema_version']}\n"
        f"- Live follow-up issue: #{report['planned_live_issue_id']}\n"
        f"- Max calls: {report['max_calls']}\n"
        f"- Max tokens total: {report['max_tokens_total']}\n"
        f"- Provider/model: {report['provider_model']}\n"
        f"- Diagnostic storage: {report['diagnostic_storage']}\n"
        "- Live provider calls allowed here: "
        f"{report['live_provider_calls_allowed']}\n\n"
        "## Selected Policy Units\n"
        "| Package | Target | Policy | Entry | On status | Off status |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{pair_rows}\n\n"
        "## Fake/Dry Pair Summaries\n"
        "| Package | Target | Side | Structural status | Structural issue codes "
        "| Compliance status | Hits | Misses | Forbidden | Skipped "
        "| Compliance reason codes |\n"
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |\n"
        f"{side_rows}\n\n"
        "## Recommended Live Approval Packet\n"
        f"- Approved inputs: {approved_inputs}\n"
        f"- Targets: {approved_targets}\n"
        f"- Selection: {approval['selection']}\n"
        f"- Max calls: {approval['max_calls']}\n"
        f"- Max tokens total: {approval['max_tokens_total']}\n"
        f"- Provider/model: {approval['provider_model']}\n"
        f"- Diagnostic storage: {approval['diagnostic_storage']}\n\n"
        "## Recommendation\n"
        "Proceed to #534 only after this PR is merged/reviewed and the owner "
        "approval remains in force. Keep #534 metadata-only in ordinary artifacts.\n"
    )


def _policy_evidence_cases(*, repo_root: Path) -> tuple[dict[str, Any], ...]:
    cases: list[dict[str, Any]] = []
    for fixture_path in LANGUAGE_POLICY_PACKAGE_FIXTURES:
        payload = _load_language_policy_fixture(fixture_path, repo_root=repo_root)
        package_id = str(payload.get("package_id") or "Unknown")
        if package_id == "language_policy.ru_uk.variant_list.v1":
            cases.extend(
                _ru_uk_policy_evidence_cases(
                    payload,
                    fixture_path=fixture_path,
                )
            )
        elif package_id == "language_policy.de.casefold.contrast_v1":
            cases.append(
                _contrast_policy_evidence_case(
                    payload,
                    fixture_path=fixture_path,
                )
            )
        else:
            raise ValueError(f"unsupported language policy package: {package_id}")
    return tuple(cases)


def _load_language_policy_fixture(
    fixture_path: Path,
    *,
    repo_root: Path,
) -> Mapping[str, Any]:
    path = _resolve_input_path(fixture_path, repo_root=repo_root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("language policy package fixture must be an object")
    raw_key_violations = _policy_evidence_raw_key_violations(payload)
    if raw_key_violations:
        raise ValueError(
            "language policy package fixture contains forbidden raw fields: "
            + ",".join(raw_key_violations)
        )
    return payload


def _ru_uk_policy_evidence_cases(
    payload: Mapping[str, Any],
    *,
    fixture_path: Path,
) -> tuple[dict[str, Any], ...]:
    cases: list[dict[str, Any]] = []
    for descriptor in payload["policies"]:
        target_language = str(descriptor["target_language"])
        approved_case = _first_expected_case(
            descriptor["expected_cases"],
            "approved_variant",
        )
        forbidden_case = _first_expected_case(
            descriptor["expected_cases"],
            "forbidden_variant",
        )
        entry = _policy_entry_descriptor(
            descriptor["entries"],
            approved_case["entry_id"],
        )
        cases.append(
            _policy_evidence_case(
                payload,
                fixture_path=fixture_path,
                policy_descriptor=descriptor,
                entry=entry,
                approved_form=str(approved_case["form"]),
                glossary_off_form=str(forbidden_case["form"]),
                expected_off_reason="policy_forbidden_variant_present",
                target_language=target_language,
            )
        )
    return tuple(cases)


def _contrast_policy_evidence_case(
    payload: Mapping[str, Any],
    *,
    fixture_path: Path,
) -> dict[str, Any]:
    entry = payload["entries"][0]
    approved_case = _first_expected_case(entry["expected_cases"], "casefold_match")
    forbidden_case = _first_expected_case(
        entry["expected_cases"],
        "forbidden_variant",
    )
    return _policy_evidence_case(
        payload,
        fixture_path=fixture_path,
        policy_descriptor=payload["policy"],
        entry=entry,
        approved_form=str(approved_case["form"]),
        glossary_off_form=str(forbidden_case["form"]),
        expected_off_reason="policy_forbidden_variant_present",
        target_language=str(payload["target_language"]),
    )


def _policy_evidence_case(
    payload: Mapping[str, Any],
    *,
    fixture_path: Path,
    policy_descriptor: Mapping[str, Any],
    entry: Mapping[str, Any],
    approved_form: str,
    glossary_off_form: str,
    expected_off_reason: str,
    target_language: str,
) -> dict[str, Any]:
    policy = _terminology_policy_from_descriptor(policy_descriptor)
    validation = validate_terminology_policy(policy)
    if not validation.valid:
        first_issue = validation.issues[0]
        raise ValueError(
            f"invalid terminology policy for {target_language}: "
            f"{first_issue.path} {first_issue.message}"
        )
    source_text = _policy_evidence_source_text(entry)
    return {
        "fixture_path": str(fixture_path),
        "package_id": str(payload.get("package_id") or "Unknown"),
        "package_version": str(payload.get("package_version") or "Unknown"),
        "evidence_level": str(payload.get("evidence_level") or "Unknown"),
        "rights_basis": str(
            payload.get("rights_basis")
            or payload.get("evidence_basis")
            or payload.get("fixture_basis")
            or "Unknown"
        ),
        "target_language": target_language,
        "policy": policy,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "match_mode": str(policy.match_mode),
        "entry": entry,
        "entry_id": str(entry["entry_id"]),
        "approved_form": approved_form,
        "glossary_off_form": glossary_off_form,
        "expected_off_reason": expected_off_reason,
        "source_text": source_text,
    }


def _fake_policy_pair_summary(case: Mapping[str, Any]) -> dict[str, Any]:
    policy = case["policy"]
    registry = TerminologyPolicyRegistry((policy,))
    glossary_on = _fake_policy_side_summary(
        case,
        registry=registry,
        side="glossary_on",
        translated_form=str(case["approved_form"]),
        cache_behavior="bypass_glossary_injected_cache",
        prompt_context_entry_count=1,
    )
    glossary_off = _fake_policy_side_summary(
        case,
        registry=registry,
        side="glossary_off",
        translated_form=str(case["glossary_off_form"]),
        cache_behavior="default_runtime_cache",
        prompt_context_entry_count=0,
    )
    status = "passed_fake_dry_preflight"
    if glossary_on["glossary_compliance"]["status"] != "pass":
        status = "failed_fake_dry_preflight"
    if not glossary_on["structural_validation"]["valid"]:
        status = "failed_fake_dry_preflight"
    if not glossary_off["structural_validation"]["valid"]:
        status = "failed_fake_dry_preflight"
    return {
        "package_id": case["package_id"],
        "package_version": case["package_version"],
        "fixture_path": case["fixture_path"],
        "evidence_level": case["evidence_level"],
        "rights_basis": case["rights_basis"],
        "target_language": case["target_language"],
        "policy_id": case["policy_id"],
        "policy_version": case["policy_version"],
        "match_mode": case["match_mode"],
        "entry_id": case["entry_id"],
        "selection": {
            "status": "selected",
            "rule": "first policy-aware glossary-useful package unit",
            "source_term_or_alias_present": True,
            "target_metadata_present": True,
            "metadata_only": True,
            "raw_payload_included": False,
        },
        "status": status,
        "planned_live_calls": 2,
        "provider_reported_usage": "Unknown",
        "sides": {
            "glossary_on": glossary_on,
            "glossary_off": glossary_off,
        },
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _fake_policy_side_summary(
    case: Mapping[str, Any],
    *,
    registry: TerminologyPolicyRegistry,
    side: str,
    translated_form: str,
    cache_behavior: str,
    prompt_context_entry_count: int,
) -> dict[str, Any]:
    structural_validation = _fake_policy_structural_validation(translated_form)
    compliance = validate_glossary_compliance(
        [_policy_evidence_glossary_entry(case["entry"])],
        selected_entry_ids=(case["entry_id"],),
        included_entry_ids=(case["entry_id"],),
        source_text=str(case["source_text"]),
        translated_text=translated_form,
        target_language=str(case["target_language"]),
        terminology_policy_registry=registry,
        structural_validation_passed=structural_validation["valid"],
    )
    return {
        "side": side,
        "status": "validated" if structural_validation["valid"] else "failed",
        "finish_reason": "fake_dry",
        "http_status": "not_applicable",
        "usage": "Unknown",
        "structural_validation": structural_validation,
        "glossary_compliance": compliance,
        "cache_policy": {
            "behavior": cache_behavior,
            "cache_get_allowed": cache_behavior == "default_runtime_cache",
            "cache_put_allowed": cache_behavior == "default_runtime_cache",
        },
        "prompt_context": {
            "included_entry_count": prompt_context_entry_count,
            "raw_prompt_body_included": False,
        },
        "planned_live_call": True,
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _fake_policy_structural_validation(translated_form: str) -> dict[str, Any]:
    content = (
        "<translation_batch>"
        '<translation_block id="0">'
        f"{html.escape(translated_form, quote=False)}"
        "</translation_block>"
        "</translation_batch>"
    )
    validation = normalize_provider_translation_batch_contract(
        content,
        expected_count=1,
        required_markers=(),
    )
    issue_codes: list[str] = []
    if validation.rejection_reason is not None:
        issue_codes.append(validation.rejection_reason.value)
    return {
        "valid": not issue_codes,
        "issue_count": len(issue_codes),
        "issue_codes": issue_codes,
        "translated_block_count": (
            len(validation.translated_texts)
            if validation.translated_texts is not None
            else 0
        ),
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _terminology_policy_from_descriptor(
    descriptor: Mapping[str, Any],
) -> TerminologyPolicy:
    return TerminologyPolicy(
        policy_id=str(descriptor["policy_id"]),
        policy_version=str(descriptor["policy_version"]),
        target_language=descriptor.get("target_language"),
        language_family=descriptor.get("language_family"),
        match_mode=descriptor["match_mode"],
        normalization_mode=descriptor["normalization_mode"],
        allowed_variant_strategy=descriptor["allowed_variant_strategy"],
        forbidden_variant_strategy=descriptor["forbidden_variant_strategy"],
        unsupported_fallback=descriptor["unsupported_fallback"],
        reason_codes=tuple(descriptor["reason_codes"]),
    )


def _policy_evidence_glossary_entry(entry: Mapping[str, Any]) -> dict[str, object]:
    return {
        "entry_id": entry["entry_id"],
        "source_canonical": entry["source_canonical"],
        "aliases": tuple(entry.get("aliases", ())),
        "target_canonical": entry.get("target_canonical"),
        "target_variants": tuple(
            entry.get("approved_variants")
            or entry.get("target_variants")
            or ()
        ),
        "forbidden_variants": tuple(entry.get("forbidden_variants") or ()),
    }


def _policy_evidence_source_text(entry: Mapping[str, Any]) -> str:
    source_terms = _entry_source_terms(_policy_evidence_glossary_entry(entry))
    source_term = source_terms[0] if source_terms else "Unknown"
    return f"{source_term} synthetic local policy preflight unit."


def _first_expected_case(
    cases: Sequence[Any],
    expected_outcome: str,
) -> Mapping[str, Any]:
    for item in cases:
        if (
            isinstance(item, Mapping)
            and item.get("expected_outcome") == expected_outcome
        ):
            return item
    raise ValueError(f"missing expected case: {expected_outcome}")


def _policy_entry_descriptor(
    entries: Sequence[Any],
    entry_id: Any,
) -> Mapping[str, Any]:
    for entry in entries:
        if isinstance(entry, Mapping) and entry.get("entry_id") == entry_id:
            return entry
    raise ValueError(f"missing policy entry: {entry_id}")


def _policy_evidence_raw_key_violations(value: Any) -> tuple[str, ...]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().casefold()
            if normalized in POLICY_EVIDENCE_RAW_KEYS:
                violations.append(normalized)
            violations.extend(_policy_evidence_raw_key_violations(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            violations.extend(_policy_evidence_raw_key_violations(item))
    return tuple(sorted(dict.fromkeys(violations)))


def _issue_534_approval_template(
    pairs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "issue_id": ISSUE_534_ID,
        "approved_inputs": sorted({str(pair["fixture_path"]) for pair in pairs}),
        "targets": [str(pair["target_language"]) for pair in pairs],
        "selection": (
            "first policy-aware glossary-useful unit per approved target from "
            "#533 fake/dry preflight; paired glossary-on and glossary-off"
        ),
        "max_calls": ISSUE_534_MAX_CALLS,
        "max_tokens_total": ISSUE_534_MAX_TOKENS_TOTAL,
        "provider_model": f"DeepSeek-compatible provider / {DEFAULT_MODEL}",
        "diagnostic_storage": (
            f"{ISSUE_534_DIAGNOSTIC_ROOT}/<timestamp>/ local owner-only untracked"
        ),
        "raw_text_capture": (
            "yes, only bounded fixture excerpts, prompts and provider responses "
            "inside that diagnostics directory"
        ),
        "ordinary_artifacts": "metadata-only counts, statuses and reason codes",
        "not_approved": provider_evidence_protocol_payload()["not_approved"],
    }


def _policy_live_prompt(case: Mapping[str, Any], *, side: str) -> dict[str, str]:
    glossary_context = (
        _policy_live_glossary_context(case) if side == "glossary_on" else ""
    )
    request_text = _format_translation_request_text(
        [str(case["source_text"])],
        source_language_hints=["en"],
        glossary_prompt_context=glossary_context,
    )
    policy = build_translation_policy(
        text=request_text,
        source_language="en",
        target_language=str(case["target_language"]),
        service_glossary_context_present=bool(glossary_context),
    )
    system_prompt = build_system_prompt(
        policy,
        provider_output_format=ProviderOutputFormat.DEFAULT,
        expected_batch_count=1,
    )
    return {
        "system_prompt": system_prompt,
        "user_prompt": _wrap_untrusted_document_content(request_text),
        "request_text": request_text,
        "source_text": str(case["source_text"]),
        "glossary_context": glossary_context,
    }


def _policy_live_glossary_context(case: Mapping[str, Any]) -> str:
    entry = _policy_evidence_glossary_entry(case["entry"])
    variants = "".join(
        f'<target_variant value="{html.escape(str(variant))}" />'
        for variant in entry["target_variants"]
    )
    forbidden = "".join(
        f'<forbidden_variant value="{html.escape(str(variant))}" />'
        for variant in entry["forbidden_variants"]
    )
    return (
        '<glossary_context mode="terminology_policy_v1">'
        f'<term id="{html.escape(str(entry["entry_id"]))}" '
        f'policy_id="{html.escape(str(case["policy_id"]))}" '
        f'match_mode="{html.escape(str(case["match_mode"]))}">'
        f'<source>{html.escape(str(entry["source_canonical"]))}</source>'
        f'<target_canonical>{html.escape(str(entry["target_canonical"]))}'
        "</target_canonical>"
        f"{variants}{forbidden}"
        "</term>"
        "</glossary_context>"
    )


def _policy_live_structural_validation(result: ChatCallResult) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if result.finish_reason in {"length", "max_tokens"}:
        issues.append(_issue("truncated_output", "finish_reason"))
    if not result.ok:
        issues.append(_issue("provider_error", "http_status"))
    if not result.content.strip():
        issues.append(_issue("empty_content", "content"))
    safety = validate_model_output_safety(result.content)
    if safety.reason is not None:
        issues.append(_issue("unsafe_model_output", "content"))
    batch_validation = normalize_provider_translation_batch_contract(
        result.content,
        expected_count=1,
        required_markers=(),
    )
    if batch_validation.rejection_reason is not None:
        issues.append(
            _issue(batch_validation.rejection_reason.value, "translation_batch")
        )
    return {
        "valid": not issues,
        "issue_count": len(issues),
        "issue_codes": [issue["code"] for issue in issues],
        "issues": issues,
        "translated_block_count": (
            len(batch_validation.translated_texts)
            if batch_validation.translated_texts is not None
            else 0
        ),
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _policy_live_glossary_compliance(
    case: Mapping[str, Any],
    *,
    result: ChatCallResult,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    translated_text: str | None = None
    if validation.get("valid") is True:
        batch_validation = normalize_provider_translation_batch_contract(
            result.content,
            expected_count=1,
            required_markers=(),
        )
        if batch_validation.translated_texts is not None:
            translated_text = "\n\n".join(batch_validation.translated_texts)
    registry = TerminologyPolicyRegistry((case["policy"],))
    return validate_glossary_compliance(
        [_policy_evidence_glossary_entry(case["entry"])],
        selected_entry_ids=(case["entry_id"],),
        included_entry_ids=(case["entry_id"],),
        source_text=str(case["source_text"]),
        translated_text=translated_text,
        target_language=str(case["target_language"]),
        terminology_policy_registry=registry,
        structural_validation_passed=validation.get("valid") is True,
    )


def _policy_live_call_summary(
    case: Mapping[str, Any],
    *,
    side: str,
    call_index: int,
    estimated_prompt_tokens: int,
    reserved_tokens: int,
    reservation: int,
    result: ChatCallResult,
    validation: Mapping[str, Any],
    glossary_compliance: Mapping[str, Any],
    observed_over_cap: bool,
) -> dict[str, Any]:
    usage_tokens = _usage_total_tokens(result.usage)
    return {
        "call_index": call_index,
        "input_fixture": case["fixture_path"],
        "package_id": case["package_id"],
        "target_language": case["target_language"],
        "side": side,
        "policy_id": case["policy_id"],
        "policy_version": case["policy_version"],
        "match_mode": case["match_mode"],
        "entry_id": case["entry_id"],
        "status": "validated" if validation.get("valid") else "failed",
        "finish_reason": result.finish_reason or "Unknown",
        "http_status": (
            result.http_status if result.http_status is not None else "Unknown"
        ),
        "latency_seconds": round(result.elapsed_seconds, 3),
        "usage": dict(result.usage),
        "usage_total_tokens": _unknown_int(usage_tokens),
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "reserved_request_tokens": reservation,
        "reserved_tokens_after_call": reserved_tokens,
        "observed_over_cap": observed_over_cap,
        "validation": dict(validation),
        "glossary_compliance": dict(glossary_compliance),
        "cache_policy": {
            "behavior": (
                "bypass_glossary_injected_cache"
                if side == "glossary_on"
                else "default_runtime_cache"
            ),
            "cache_get_allowed": side != "glossary_on",
            "cache_put_allowed": side != "glossary_on",
        },
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _policy_live_skipped_call_summary(
    case: Mapping[str, Any],
    *,
    side: str,
    reason_code: str,
    estimated_prompt_tokens: int | str = "Unknown",
    reserved_tokens: int | str = "Unknown",
) -> dict[str, Any]:
    return {
        "input_fixture": case["fixture_path"],
        "package_id": case["package_id"],
        "target_language": case["target_language"],
        "side": side,
        "policy_id": case["policy_id"],
        "entry_id": case["entry_id"],
        "status": "skipped",
        "reason_codes": [reason_code],
        "finish_reason": "not_applicable",
        "http_status": "not_applicable",
        "usage_total_tokens": "Unknown",
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "reserved_tokens_before_skip": reserved_tokens,
        "validation": {
            "valid": False,
            "issue_count": 1,
            "issue_codes": [reason_code],
            "metadata_only": True,
            "raw_payload_included": False,
        },
        "glossary_compliance": {
            "status": "skipped",
            "reason_codes": [reason_code],
            "metadata_only": True,
            "raw_payload_included": False,
        },
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _policy_live_call_diagnostic(
    case: Mapping[str, Any],
    *,
    side: str,
    prompt: Mapping[str, str],
    result: ChatCallResult,
    validation: Mapping[str, Any],
    glossary_compliance: Mapping[str, Any],
    raw_text_capture: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": POLICY_PROVIDER_EVIDENCE_LIVE_SCHEMA_VERSION,
        "access_boundary": {
            "local_owner_only": True,
            "git_tracked_allowed": False,
            "github_issue_or_pr_allowed": False,
            "ordinary_logs_allowed": False,
            "release_or_support_artifact_allowed": False,
        },
        "input_fixture": case["fixture_path"],
        "package_id": case["package_id"],
        "target_language": case["target_language"],
        "side": side,
        "policy_id": case["policy_id"],
        "entry_id": case["entry_id"],
        "validation": dict(validation),
        "glossary_compliance": dict(glossary_compliance),
        "provider": {
            "model": DEFAULT_MODEL,
            "finish_reason": result.finish_reason or "Unknown",
            "http_status": (
                result.http_status if result.http_status is not None else "Unknown"
            ),
            "usage": dict(result.usage),
            "latency_seconds": round(result.elapsed_seconds, 3),
            "error_type": result.error_type or "none",
            "error_message": result.error_message or "none",
        },
        "secrets_included": False,
    }
    if raw_text_capture:
        payload.update(
            {
                "bounded_source_excerpt": prompt["source_text"][
                    :DEFAULT_MAX_FRAGMENT_CHARS
                ],
                "system_prompt": prompt["system_prompt"],
                "user_prompt": prompt["user_prompt"],
                "runtime_request_text": prompt["request_text"],
                "glossary_context": prompt["glossary_context"],
                "provider_request_payload": dict(result.request_payload),
                "provider_response_payload": (
                    dict(result.response_payload)
                    if isinstance(result.response_payload, Mapping)
                    else None
                ),
                "provider_response_text": result.response_text,
                "provider_content": result.content,
            }
        )
    return payload


def _policy_live_status(calls: Sequence[Mapping[str, Any]]) -> str:
    if any(call.get("observed_over_cap") is True for call in calls):
        return "completed_token_cap_exceeded"
    if any(call.get("status") == "failed" for call in calls):
        return "completed_with_failures"
    if any(call.get("status") == "skipped" for call in calls):
        return "completed_with_skips"
    return "completed"


def _policy_live_confirmed_items(
    calls: Sequence[Mapping[str, Any]],
) -> list[str]:
    items = [
        "fake/dry preflight ran before live calls",
        "live calls used only #533-selected committed policy package fixtures",
        "ordinary live report is metadata-only",
        "raw prompts and provider responses were confined to owner-only diagnostics",
        "runtime rollout, cache reuse and provider config were not changed",
    ]
    if calls:
        items.append("bounded live calls were attempted within the approved call cap")
    if calls and all(call.get("status") == "validated" for call in calls):
        items.append("all live provider responses passed structural validation")
    return items


def _policy_live_unknown_items(
    calls: Sequence[Mapping[str, Any]],
) -> list[str]:
    unknown: list[str] = []
    if any(call.get("usage_total_tokens") == "Unknown" for call in calls):
        unknown.append("provider-reported usage is Unknown for one or more calls")
    if any(call.get("status") == "failed" for call in calls):
        unknown.append("one or more live provider responses did not validate")
    if not calls:
        unknown.append("provider behavior is Unknown because no calls were made")
    unknown.append(
        "translation quality remains Unknown until owner-only quality review"
    )
    return unknown


def _policy_live_recommendation(
    calls: Sequence[Mapping[str, Any]],
) -> str:
    if any(call.get("observed_over_cap") is True for call in calls):
        return "stop: observed provider usage exceeded the approved token cap."
    if any(call.get("status") == "failed" for call in calls):
        return (
            "review_provider_failures_before_rollout: one or more live "
            "responses failed structural validation."
        )
    if any(
        (call.get("glossary_compliance") or {}).get("status") == "findings"
        for call in calls
    ):
        return (
            "review_glossary_compliance_findings: provider calls completed, "
            "but one or more policy-aware compliance summaries have findings."
        )
    return (
        "proceed_to_metadata_only_decision_packet: provider-boundary evidence "
        "completed without structural or compliance findings."
    )


def _policy_live_blocked_report(
    *,
    preflight: Mapping[str, Any],
    reason_code: str,
) -> dict[str, Any]:
    return {
        "schema_version": POLICY_PROVIDER_EVIDENCE_LIVE_SCHEMA_VERSION,
        "issue_id": ISSUE_534_ID,
        "status": "blocked",
        "reason_codes": [reason_code],
        "fake_dry_preflight_status": preflight.get("status", "Unknown"),
        "calls_made": 0,
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _policy_live_call_report_row(call: Mapping[str, Any]) -> str:
    validation = call.get("validation") or {}
    compliance = call.get("glossary_compliance") or {}
    validation_codes = validation.get("issue_codes") or ["none"]
    return (
        f"| {call.get('target_language', 'Unknown')} | "
        f"{call.get('side', 'Unknown')} | "
        f"{call.get('policy_id', 'Unknown')} | "
        f"{call.get('entry_id', 'Unknown')} | "
        f"{call.get('status', 'Unknown')} | "
        f"{call.get('finish_reason', 'Unknown')} | "
        f"{call.get('usage_total_tokens', 'Unknown')} | "
        f"{', '.join(str(code) for code in validation_codes)} | "
        f"{compliance.get('status', 'Unknown')} | "
        f"{compliance.get('target_form_present_count', 'Unknown')} | "
        f"{compliance.get('target_form_missing_count', 'Unknown')} | "
        f"{compliance.get('forbidden_variant_count', 'Unknown')} |"
    )


def _policy_preflight_pair_report_row(pair: Mapping[str, Any]) -> str:
    sides = pair["sides"]
    return (
        f"| {pair['package_id']} | {pair['target_language']} | "
        f"{pair['policy_id']} | {pair['entry_id']} | "
        f"{sides['glossary_on']['glossary_compliance']['status']} | "
        f"{sides['glossary_off']['glossary_compliance']['status']} |"
    )


def _policy_preflight_side_report_row(
    pair: Mapping[str, Any],
    side_name: str,
    side: Mapping[str, Any],
) -> str:
    structural = side["structural_validation"]
    compliance = side["glossary_compliance"]
    structural_codes = structural.get("issue_codes") or ["none"]
    compliance_codes = compliance.get("reason_codes") or ["none"]
    return (
        f"| {pair['package_id']} | {pair['target_language']} | {side_name} | "
        f"{'pass' if structural['valid'] else 'fail'} | "
        f"{', '.join(structural_codes)} | {compliance['status']} | "
        f"{compliance['target_form_present_count']} | "
        f"{compliance['target_form_missing_count']} | "
        f"{compliance['forbidden_variant_count']} | "
        f"{compliance['skipped_entry_count']} | {', '.join(compliance_codes)} |"
    )


def _empty_prompt_context_metadata(*, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "glossary-prompt-context-v1",
        "included_entry_ids": [],
        "included_entries": [],
        "omitted_entries": [],
        "estimated_prompt_tokens": 0,
        "character_count": 0,
        "entry_limit": 0,
        "prompt_budget_tokens": 0,
        "character_budget": 0,
        "runtime_budget": {
            "schema_version": "glossary-runtime-budget-tuning-v1",
            "policy": reason,
            "reason_codes": [reason],
            "selection": {
                "max_prompt_tokens": 0,
                "max_entries": 0,
                "max_diagnostic_entries": 0,
            },
            "prompt_context": {
                "max_prompt_tokens": 0,
                "max_entries": 0,
                "max_characters": 0,
            },
            "completion_safety": {
                "reserved_first": True,
                "estimated_completion_pressure_tokens": "Unknown",
                "max_completion_tokens": "Unknown",
            },
            "metadata_only": True,
            "raw_payload_included": False,
        },
    }


def build_runtime_package(
    input_path: Path,
    target_language: str,
    *,
    config: SmokeConfig,
    repo_root: Path,
) -> RuntimeSmokePackage:
    path = _approved_input_path(
        input_path,
        target_language,
        repo_root=repo_root,
        config=config,
    )
    plan = _plan_input(path, max_fragment_chars=config.max_fragment_chars)
    glossary = scan_glossary_candidates(
        plan,
        source_language="en",
        target_language=target_language,
    )
    profile = detect_book_profile(
        plan,
        source_language="en",
        target_language=target_language,
        glossary_snapshot=glossary,
    )
    reduction = reduce_glossary_candidates(
        glossary,
        profile_detection=profile,
        pressure_context={
            "issue": config.issue_id,
            "fixture_id": _input_id(path, target_language),
            "document_format": plan.document_format.value,
            "fragment_count": plan.fragment_count,
            "character_count": plan.character_count,
            "glossary_entry_count": len(glossary.entries),
            "glossary_evidence_count": len(glossary.evidence),
        },
    )
    if not reduction.retained_entry_ids:
        raise ValueError("no_reduced_candidates")
    retained_snapshot, target_metadata_fixture = (
        apply_target_metadata_fixture_overlay(
            reduction.retained_snapshot,
            config=config,
            repo_root=repo_root,
            input_path=path,
            target_language=target_language,
        )
    )
    selected_rule_ids = tuple(rule.rule_id for rule in profile.rules)
    policy = build_translation_policy(
        text=_policy_sample_text(plan),
        source_language="en",
        target_language=target_language,
    )
    snapshot = build_translation_contract_snapshot(
        policy,
        glossary_snapshot=retained_snapshot,
        profile_detection=profile,
        selected_rule_ids=selected_rule_ids,
        selection_policy_version=GLOSSARY_SELECTION_POLICY_VERSION,
        quality_route="runtime_provider_smoke",
    )
    selections = []
    protected_by_sequence: dict[int, Any] = {}
    budget_plan_by_sequence: dict[int, dict[str, Any]] = {}
    for unit in plan.units:
        protected = protect_text(unit.source_text)
        budget_plan = build_runtime_glossary_budget_plan(
            document_format=plan.document_format.value,
            source_block_count=len(unit.source_block_ids),
            protected_marker_count=len(protected.replacements),
            protected_text=protected.text,
            config=config,
        )
        protected_by_sequence[unit.sequence] = protected
        budget_plan_by_sequence[unit.sequence] = budget_plan
        selection_budget = budget_plan["selection"]
        selections.append(
            select_glossary_subset_for_work_unit(
                unit,
                retained_snapshot,
                budget=GlossarySelectionBudget(
                    max_prompt_tokens=selection_budget["max_prompt_tokens"],
                    max_entries=selection_budget["max_entries"],
                    max_diagnostic_entries=selection_budget[
                        "max_diagnostic_entries"
                    ],
                ),
                profile_rule_ids=selected_rule_ids,
            )
        )
    reducer_metadata = _reducer_metadata(
        reduction,
        retained_snapshot=retained_snapshot,
        target_metadata_fixture=target_metadata_fixture,
    )
    epub_candidate_packages: list[RuntimeSmokePackage] = []
    epub_skipped_candidates: list[dict[str, Any]] = []
    is_epub_plan = plan.document_format.value == "epub"
    for selection in selections:
        selection_metadata = glossary_selection_metadata_payload(selection)
        glossary_plan = _one_unit_glossary_plan(
            selection_metadata=selection_metadata,
            reducer_metadata=reducer_metadata,
            snapshot=snapshot,
            selected_rule_ids=selected_rule_ids,
            source_language="en",
            target_language=target_language,
        )
        decision = build_glossary_prompt_policy_adapter_decision(
            glossary_plan,
            config=GlossaryPromptPolicyAdapterConfig(
                enabled=True,
                work_unit_sequence=selection.work_unit_sequence,
            ),
        )
        if decision.status is not GlossaryPromptPolicyAdapterStatus.READY:
            if is_epub_plan:
                unit = _unit_by_sequence(plan.units, selection.work_unit_sequence)
                protected = protected_by_sequence[selection.work_unit_sequence]
                epub_skipped_candidates.append(
                    _epub_runtime_unit_selection_skip_payload(
                        unit,
                        protected,
                        config=config,
                        reason_codes=("adapter_not_ready",),
                        selection_metadata=selection_metadata,
                        adapter_metadata=(
                            glossary_prompt_policy_adapter_decision_payload(
                                decision
                            )
                        ),
                        budget_plan=budget_plan_by_sequence[
                            selection.work_unit_sequence
                        ],
                        target_metadata_fixture=target_metadata_fixture,
                    )
                )
            continue
        budget_plan = budget_plan_by_sequence[selection.work_unit_sequence]
        unit = _unit_by_sequence(plan.units, selection.work_unit_sequence)
        target_backed_source_present_only = (
            is_epub_plan or config.issue_id == ISSUE_575_ID
        )
        prompt_context_text, prompt_context_metadata = (
            format_runtime_glossary_prompt_context(
                retained_snapshot.entries,
                selected_entry_ids=decision.selected_entry_ids,
                budget_plan=budget_plan,
                source_text=(
                    unit.source_text if target_backed_source_present_only else None
                ),
                target_backed_source_present_only=target_backed_source_present_only,
            )
        )
        prompt_context_metadata["target_metadata_fixture"] = dict(
            target_metadata_fixture
        )
        if (
            not prompt_context_metadata["included_entry_ids"]
            and not budget_plan["reason_codes"]
        ):
            if is_epub_plan:
                unit = _unit_by_sequence(plan.units, selection.work_unit_sequence)
                protected = protected_by_sequence[selection.work_unit_sequence]
                epub_skipped_candidates.append(
                    _epub_runtime_unit_selection_skip_payload(
                        unit,
                        protected,
                        config=config,
                        reason_codes=("prompt_context_not_included",),
                        selection_metadata=selection_metadata,
                        adapter_metadata=(
                            glossary_prompt_policy_adapter_decision_payload(
                                decision
                            )
                        ),
                        prompt_context_metadata=prompt_context_metadata,
                        budget_plan=budget_plan,
                        target_metadata_fixture=target_metadata_fixture,
                    )
                )
            continue
        protected = protected_by_sequence[selection.work_unit_sequence]
        package = RuntimeSmokePackage(
            input_path=path,
            input_id=_input_id(path, target_language),
            target_language=target_language,
            document_format=plan.document_format.value,
            fragment_count=plan.fragment_count,
            character_count=plan.character_count,
            unit_sequence=selection.work_unit_sequence,
            source_block_ids=tuple(unit.source_block_ids),
            source_text=unit.source_text,
            protected_text=protected.text,
            required_markers=tuple((marker,) for marker in protected.replacements),
            glossary_plan=glossary_plan,
            adapter_metadata=glossary_prompt_policy_adapter_decision_payload(
                decision
            ),
            prompt_context_text=prompt_context_text,
            prompt_context_metadata=prompt_context_metadata,
            selection_metadata=selection_metadata,
            glossary_entry_count=len(retained_snapshot.entries),
            glossary_evidence_count=len(retained_snapshot.evidence),
            reducer_metadata=reducer_metadata,
            glossary_entries=tuple(retained_snapshot.entries),
        )
        if is_epub_plan:
            epub_candidate_packages.append(package)
            continue
        return apply_runtime_pressure_fallback(package, config=config)
    if is_epub_plan:
        return select_epub_runtime_unit_for_rehearsal(
            epub_candidate_packages,
            config=config,
            entries=retained_snapshot.entries,
            skipped_candidates=epub_skipped_candidates,
            input_id=_input_id(path, target_language),
            target_language=target_language,
            document_format=plan.document_format.value,
            target_metadata_fixture=target_metadata_fixture,
        )
    raise ValueError("no_ready_glossary_injected_runtime_unit")


def select_epub_runtime_unit_for_rehearsal(
    packages: Sequence[RuntimeSmokePackage],
    *,
    config: SmokeConfig,
    entries: Iterable[Any],
    skipped_candidates: Sequence[Mapping[str, Any]] = (),
    input_id: str = "Unknown",
    target_language: str = "Unknown",
    document_format: str = "epub",
    target_metadata_fixture: Mapping[str, Any] | None = None,
) -> RuntimeSmokePackage:
    safe_skips = [dict(item) for item in skipped_candidates]
    entry_tuple = tuple(entries)
    for package in packages:
        decision = build_epub_runtime_unit_selection_decision(
            package,
            config=config,
            entries=entry_tuple,
        )
        if decision["status"] == "selected":
            decision = dict(decision)
            decision["skipped_before_selected_count"] = len(safe_skips)
            decision["skipped_before_selected"] = safe_skips
            return _attach_epub_runtime_unit_selection(package, decision)
        safe_skips.append(decision)

    raise RuntimePackageSelectionError(
        "no_glossary_useful_pressure_safe_epub_unit",
        metadata=_epub_runtime_no_selection_metadata(
            input_id=input_id,
            target_language=target_language,
            document_format=document_format,
            skipped_candidates=safe_skips,
            target_metadata_fixture=target_metadata_fixture,
        ),
    )


def build_epub_runtime_unit_selection_decision(
    package: RuntimeSmokePackage,
    *,
    config: SmokeConfig,
    entries: Iterable[Any],
) -> dict[str, Any]:
    if package.document_format != "epub":
        return {
            "schema_version": EPUB_RUNTIME_UNIT_SELECTION_SCHEMA_VERSION,
            "policy": EPUB_RUNTIME_UNIT_SELECTION_POLICY,
            "status": "not_applicable",
            "reason_codes": ["not_epub_runtime_unit"],
            "metadata_only": True,
            "raw_payload_included": False,
        }

    pressure_summary = build_runtime_pressure_summary(package, config=config)
    pressure_fallback = build_runtime_pressure_fallback_decision(
        package,
        config=config,
        pressure_summary=pressure_summary,
    )
    useful = _glossary_useful_preflight_metadata(
        entries,
        selected_entry_ids=package.adapter_metadata.get("selected_entry_ids") or (),
        source_text=package.source_text,
    )
    reason_codes: list[str] = []
    if package.adapter_metadata.get("status") != "ready":
        reason_codes.append("adapter_not_ready")
    if not package.adapter_metadata.get("selected_entry_ids"):
        reason_codes.append("selected_glossary_entry_missing")
    if not package.prompt_context_metadata.get("included_entry_ids"):
        reason_codes.append("prompt_context_not_included")
    if useful["status"] != "ready":
        reason_codes.extend(str(item) for item in useful["reason_codes"])
    if pressure_fallback["action"] != "keep_glossary_prompt_context":
        reason_codes.extend(str(item) for item in pressure_fallback["reason_codes"])

    status = "selected" if not reason_codes else "skipped"
    cache_policy = package.adapter_metadata.get("cache_policy") or {}
    unit = pressure_summary["unit"]
    tokens = pressure_summary["tokens"]
    return {
        "schema_version": EPUB_RUNTIME_UNIT_SELECTION_SCHEMA_VERSION,
        "policy": EPUB_RUNTIME_UNIT_SELECTION_POLICY,
        "status": status,
        "reason_codes": sorted(dict.fromkeys(reason_codes)),
        "unit": {
            "sequence": package.unit_sequence,
            "source_block_id_count": unit["source_block_id_count"],
            "source_character_count": unit["source_character_count"],
            "protected_text_character_count": unit[
                "protected_text_character_count"
            ],
            "protected_marker_count": unit["protected_marker_count"],
        },
        "glossary": {
            "selected_entry_count": len(
                package.adapter_metadata.get("selected_entry_ids") or ()
            ),
            "prompt_context_included_entry_count": len(
                package.prompt_context_metadata.get("included_entry_ids") or ()
            ),
            "prompt_context_omitted_entry_count": len(
                package.prompt_context_metadata.get("omitted_entries") or ()
            ),
            "target_metadata_entry_count": useful["target_metadata_entry_count"],
            "source_match_entry_count": useful["source_match_entry_count"],
            "useful_entry_count": useful["useful_entry_count"],
            "useful_entry_ids": list(useful["useful_entry_ids"]),
        },
        "tokens": {
            "estimated_source_tokens": tokens["estimated_source_tokens"],
            "estimated_protected_text_tokens": tokens[
                "estimated_protected_text_tokens"
            ],
            "prompt_context_estimated_tokens": tokens[
                "prompt_context_estimated_tokens"
            ],
            "max_completion_tokens": config.max_completion_tokens,
            "max_tokens_total": config.max_tokens_total,
        },
        "cache_policy": {
            "behavior": cache_policy.get("behavior", "Unknown"),
            "cache_get_allowed": cache_policy.get("cache_get_allowed", "Unknown"),
            "cache_put_allowed": cache_policy.get("cache_put_allowed", "Unknown"),
        },
        "pressure_fallback": {
            "action": pressure_fallback["action"],
            "reason_codes": list(pressure_fallback["reason_codes"]),
            "thresholds": dict(pressure_fallback["thresholds"]),
        },
        "target_metadata_fixture": dict(
            package.prompt_context_metadata.get("target_metadata_fixture") or {}
        ),
        "thresholds": {
            "policy": PRESSURE_FALLBACK_THRESHOLD_POLICY,
            "max_epub_source_blocks": DEFAULT_PRESSURE_FALLBACK_MAX_EPUB_SOURCE_BLOCKS,
            "max_epub_protected_markers": (
                DEFAULT_PRESSURE_FALLBACK_MAX_EPUB_PROTECTED_MARKERS
            ),
            "max_estimated_completion_tokens": config.max_completion_tokens,
        },
        "normal_translation_prompts_changed": False,
        "live_provider_calls_allowed": False,
        "durable_state_mutation_allowed": False,
        "cache_mutation_allowed": False,
        "quality_claims_made": False,
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _attach_epub_runtime_unit_selection(
    package: RuntimeSmokePackage,
    selection_metadata: Mapping[str, Any],
) -> RuntimeSmokePackage:
    prompt_context_metadata = dict(package.prompt_context_metadata)
    prompt_context_metadata["epub_runtime_unit_selection"] = dict(
        selection_metadata
    )
    return replace(package, prompt_context_metadata=prompt_context_metadata)


def _epub_runtime_unit_selection_skip_payload(
    unit: Any,
    protected: Any,
    *,
    config: SmokeConfig,
    reason_codes: Sequence[str],
    selection_metadata: Mapping[str, Any] | None = None,
    adapter_metadata: Mapping[str, Any] | None = None,
    prompt_context_metadata: Mapping[str, Any] | None = None,
    budget_plan: Mapping[str, Any] | None = None,
    target_metadata_fixture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selection_metadata = selection_metadata or {}
    adapter_metadata = adapter_metadata or {}
    prompt_context_metadata = prompt_context_metadata or {}
    runtime_budget = (
        _runtime_budget_metadata_payload(budget_plan)
        if budget_plan is not None
        else {}
    )
    cache_policy = adapter_metadata.get("cache_policy") or {}
    return {
        "schema_version": EPUB_RUNTIME_UNIT_SELECTION_SCHEMA_VERSION,
        "policy": EPUB_RUNTIME_UNIT_SELECTION_POLICY,
        "status": "skipped",
        "reason_codes": sorted(dict.fromkeys(str(item) for item in reason_codes)),
        "unit": {
            "sequence": unit.sequence,
            "source_block_id_count": len(unit.source_block_ids),
            "source_character_count": len(unit.source_text),
            "protected_text_character_count": len(protected.text),
            "protected_marker_count": len(protected.replacements),
        },
        "glossary": {
            "selected_entry_count": len(
                adapter_metadata.get("selected_entry_ids") or ()
            ),
            "prompt_context_included_entry_count": len(
                prompt_context_metadata.get("included_entry_ids") or ()
            ),
            "prompt_context_omitted_entry_count": len(
                prompt_context_metadata.get("omitted_entries") or ()
            ),
        },
        "tokens": {
            "estimated_source_tokens": estimate_tokens(unit.source_text),
            "estimated_protected_text_tokens": estimate_tokens(protected.text),
            "selection_estimated_prompt_tokens": selection_metadata.get(
                "estimated_prompt_tokens",
                "Unknown",
            ),
            "prompt_context_estimated_tokens": prompt_context_metadata.get(
                "estimated_prompt_tokens",
                "Unknown",
            ),
            "max_completion_tokens": config.max_completion_tokens,
            "max_tokens_total": config.max_tokens_total,
        },
        "budget_tuning": {
            "policy": runtime_budget.get("policy", "Unknown"),
            "reason_codes": list(runtime_budget.get("reason_codes") or ()),
        },
        "cache_policy": {
            "behavior": cache_policy.get("behavior", "Unknown"),
            "cache_get_allowed": cache_policy.get("cache_get_allowed", "Unknown"),
            "cache_put_allowed": cache_policy.get("cache_put_allowed", "Unknown"),
        },
        "target_metadata_fixture": dict(target_metadata_fixture or {}),
        "normal_translation_prompts_changed": False,
        "live_provider_calls_allowed": False,
        "durable_state_mutation_allowed": False,
        "cache_mutation_allowed": False,
        "quality_claims_made": False,
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _epub_runtime_no_selection_metadata(
    *,
    input_id: str,
    target_language: str,
    document_format: str,
    skipped_candidates: Sequence[Mapping[str, Any]],
    target_metadata_fixture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reason_codes = sorted(
        {
            str(reason)
            for item in skipped_candidates
            for reason in item.get("reason_codes", ())
        }
    )
    return {
        "schema_version": EPUB_RUNTIME_UNIT_SELECTION_SCHEMA_VERSION,
        "policy": EPUB_RUNTIME_UNIT_SELECTION_POLICY,
        "input_id": input_id,
        "target_language": target_language,
        "document_format": document_format,
        "status": "skipped_selection",
        "skip_code": "no_glossary_useful_pressure_safe_epub_unit",
        "reason_codes": reason_codes or ["no_epub_runtime_unit_candidates"],
        "skipped_candidate_count": len(skipped_candidates),
        "skipped_candidates": [dict(item) for item in skipped_candidates],
        "target_metadata_fixture": dict(target_metadata_fixture or {}),
        "fallback_action": "use_glossary_off_local_rehearsal_metadata",
        "fallback_cache_policy": {
            "behavior": "default_runtime_cache",
            "cache_get_allowed": True,
            "cache_put_allowed": True,
        },
        "normal_translation_prompts_changed": False,
        "live_provider_calls_allowed": False,
        "durable_state_mutation_allowed": False,
        "cache_mutation_allowed": False,
        "quality_claims_made": False,
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _glossary_useful_preflight_metadata(
    entries: Iterable[Any],
    *,
    selected_entry_ids: Iterable[Any],
    source_text: str,
) -> dict[str, Any]:
    selected_ids = tuple(
        str(entry_id) for entry_id in selected_entry_ids if str(entry_id).strip()
    )
    entries_by_id = {
        str(entry_id): entry
        for entry in entries
        if (entry_id := _entry_value(entry, "entry_id"))
    }
    target_metadata_entry_count = 0
    source_match_entry_count = 0
    useful_entry_ids: list[str] = []
    for entry_id in selected_ids:
        entry = entries_by_id.get(entry_id)
        if entry is None:
            continue
        has_target_metadata = _entry_has_target_metadata(entry)
        source_matches = _entry_source_matches(entry, source_text)
        if has_target_metadata:
            target_metadata_entry_count += 1
        if source_matches:
            source_match_entry_count += 1
        if has_target_metadata and source_matches:
            useful_entry_ids.append(entry_id)

    reason_codes: list[str] = []
    if not useful_entry_ids:
        if target_metadata_entry_count == 0:
            reason_codes.append("target_metadata_missing")
        if source_match_entry_count == 0:
            reason_codes.append("source_term_or_alias_absent")
        if not reason_codes:
            reason_codes.append("useful_glossary_entry_missing")

    return {
        "schema_version": "glossary-runtime-battle-test-preflight-v1",
        "status": "ready" if useful_entry_ids else "skipped",
        "reason_codes": reason_codes,
        "selected_entry_count": len(selected_ids),
        "target_metadata_entry_count": target_metadata_entry_count,
        "source_match_entry_count": source_match_entry_count,
        "useful_entry_count": len(useful_entry_ids),
        "useful_entry_ids": useful_entry_ids,
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _entry_has_target_metadata(entry: Any) -> bool:
    target_canonical = _entry_value(entry, "target_canonical")
    if isinstance(target_canonical, str) and target_canonical.strip():
        return True
    target_variants = _entry_value(entry, "target_variants")
    if isinstance(target_variants, Sequence) and not isinstance(
        target_variants,
        (str, bytes),
    ):
        return any(
            isinstance(variant, str) and variant.strip()
            for variant in target_variants
        )
    return False


def _entry_source_matches(entry: Any, source_text: str) -> bool:
    if not source_text:
        return False
    return any(
        _source_term_present(term, source_text)
        for term in _entry_source_terms(entry)
    )


def _entry_source_terms(entry: Any) -> tuple[str, ...]:
    terms: list[str] = []
    source_canonical = _entry_value(entry, "source_canonical")
    if isinstance(source_canonical, str) and source_canonical.strip():
        terms.append(source_canonical.strip())
    aliases = _entry_value(entry, "aliases")
    if isinstance(aliases, Sequence) and not isinstance(aliases, (str, bytes)):
        terms.extend(
            alias.strip()
            for alias in aliases
            if isinstance(alias, str) and alias.strip()
        )
    return tuple(dict.fromkeys(terms))


def _source_term_present(term: str, source_text: str) -> bool:
    normalized_term = term.strip()
    if not normalized_term:
        return False
    pattern = re.escape(normalized_term)
    if normalized_term[0].isalnum():
        pattern = rf"(?<!\w){pattern}"
    if normalized_term[-1].isalnum():
        pattern = rf"{pattern}(?!\w)"
    return re.search(pattern, source_text, flags=re.IGNORECASE) is not None


def _entry_value(entry: Any, field_name: str) -> Any:
    if isinstance(entry, Mapping):
        return entry.get(field_name)
    return getattr(entry, field_name, None)


def apply_target_metadata_fixture_overlay(
    snapshot: GlossarySnapshot,
    *,
    config: SmokeConfig,
    repo_root: Path,
    input_path: Path,
    target_language: str,
) -> tuple[GlossarySnapshot, dict[str, Any]]:
    if config.target_metadata_fixture_path is None:
        return snapshot, _target_metadata_fixture_metadata(
            status="disabled",
            reason_codes=("target_metadata_fixture_disabled",),
            input_path=input_path,
            target_language=target_language,
            repo_root=repo_root,
        )

    fixture_path = _resolve_input_path(
        config.target_metadata_fixture_path,
        repo_root=repo_root,
    )
    if not fixture_path.is_file():
        return snapshot, _target_metadata_fixture_metadata(
            status="missing",
            reason_codes=("target_metadata_fixture_missing",),
            input_path=input_path,
            target_language=target_language,
            repo_root=repo_root,
            fixture_path=fixture_path,
        )

    try:
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return snapshot, _target_metadata_fixture_metadata(
            status="invalid",
            reason_codes=("target_metadata_fixture_unreadable",),
            input_path=input_path,
            target_language=target_language,
            repo_root=repo_root,
            fixture_path=fixture_path,
        )

    fixture_entries, reason_codes = _target_metadata_fixture_entries(
        payload,
        input_path=input_path,
        target_language=target_language,
        repo_root=repo_root,
    )
    if reason_codes:
        return snapshot, _target_metadata_fixture_metadata(
            status="invalid",
            reason_codes=reason_codes,
            input_path=input_path,
            target_language=target_language,
            repo_root=repo_root,
            fixture_path=fixture_path,
            fixture_id=_safe_fixture_identifier(payload.get("fixture_id"))
            if isinstance(payload, Mapping)
            else "Unknown",
        )

    overlaid_snapshot, matched_count = _overlay_target_metadata_entries(
        snapshot,
        fixture_entries,
    )
    status = "applied" if matched_count else "loaded_no_matches"
    reason_codes = (
        ()
        if matched_count
        else ("target_metadata_fixture_no_matching_retained_entries",)
    )
    return overlaid_snapshot, _target_metadata_fixture_metadata(
        status=status,
        reason_codes=reason_codes,
        input_path=input_path,
        target_language=target_language,
        repo_root=repo_root,
        fixture_path=fixture_path,
        fixture_id=str(payload.get("fixture_id") or "Unknown"),
        fixture_signature=_target_metadata_fixture_signature(
            payload,
            target_language=target_language,
        ),
        fixture_entry_count=len(fixture_entries),
        matched_entry_count=matched_count,
        unmatched_entry_count=max(0, len(fixture_entries) - matched_count),
    )


def _target_metadata_fixture_entries(
    payload: Any,
    *,
    input_path: Path,
    target_language: str,
    repo_root: Path,
) -> tuple[tuple[dict[str, Any], ...], tuple[str, ...]]:
    reason_codes: list[str] = []
    if not isinstance(payload, Mapping):
        return (), ("target_metadata_fixture_not_object",)
    reason_codes.extend(_raw_fixture_key_reason_codes(payload))
    if payload.get("schema_version") != TARGET_METADATA_FIXTURE_SCHEMA_VERSION:
        reason_codes.append("target_metadata_fixture_schema_invalid")
    if not payload.get("owner_approved"):
        reason_codes.append("target_metadata_fixture_owner_approval_missing")
    if payload.get("source_language") != "en":
        reason_codes.append("target_metadata_fixture_source_language_invalid")
    if set(payload) - TARGET_METADATA_FIXTURE_TOP_LEVEL_KEYS:
        reason_codes.append("target_metadata_fixture_unsupported_field")

    fixture_input_path = payload.get("input_path")
    if not isinstance(fixture_input_path, str) or not fixture_input_path.strip():
        reason_codes.append("target_metadata_fixture_input_path_missing")
    else:
        try:
            resolved_fixture_input = _resolve_input_path(
                Path(fixture_input_path),
                repo_root=repo_root,
            )
        except RuntimeError:
            resolved_fixture_input = Path()
        if resolved_fixture_input != input_path.resolve():
            reason_codes.append("target_metadata_fixture_input_mismatch")

    targets = payload.get("targets")
    if not isinstance(targets, Mapping):
        reason_codes.append("target_metadata_fixture_targets_invalid")
        return (), tuple(sorted(dict.fromkeys(reason_codes)))

    target_payload = targets.get(target_language)
    if not isinstance(target_payload, Mapping):
        reason_codes.append("target_metadata_fixture_target_missing")
        return (), tuple(sorted(dict.fromkeys(reason_codes)))
    if set(target_payload) - TARGET_METADATA_FIXTURE_TARGET_KEYS:
        reason_codes.append("target_metadata_fixture_unsupported_target_field")

    raw_entries = target_payload.get("entries")
    if isinstance(raw_entries, (str, bytes)) or not isinstance(raw_entries, Sequence):
        reason_codes.append("target_metadata_fixture_entries_invalid")
        return (), tuple(sorted(dict.fromkeys(reason_codes)))
    if not raw_entries:
        reason_codes.append("target_metadata_fixture_entries_empty")
    if len(raw_entries) > TARGET_METADATA_FIXTURE_MAX_ENTRIES_PER_TARGET:
        reason_codes.append("target_metadata_fixture_entry_limit_exceeded")

    entries: list[dict[str, Any]] = []
    for raw_entry in raw_entries:
        entry, entry_reasons = _target_metadata_fixture_entry(raw_entry)
        reason_codes.extend(entry_reasons)
        if entry is not None:
            entries.append(entry)

    return tuple(entries), tuple(sorted(dict.fromkeys(reason_codes)))


def _target_metadata_fixture_entry(
    raw_entry: Any,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    reason_codes: list[str] = []
    if not isinstance(raw_entry, Mapping):
        return None, ("target_metadata_fixture_entry_invalid",)
    if set(raw_entry) - TARGET_METADATA_FIXTURE_ENTRY_KEYS:
        reason_codes.append("target_metadata_fixture_unsupported_entry_field")

    source_canonical = _fixture_text_field(raw_entry.get("source_canonical"))
    aliases = _fixture_text_sequence(
        raw_entry.get("aliases"),
        limit=TARGET_METADATA_FIXTURE_MAX_ALIASES,
    )
    target_canonical = _fixture_text_field(raw_entry.get("target_canonical"))
    target_variants = _fixture_text_sequence(
        raw_entry.get("target_variants"),
        limit=TARGET_METADATA_FIXTURE_MAX_TARGET_VARIANTS,
    )

    if source_canonical is None:
        reason_codes.append("target_metadata_fixture_source_missing")
    if target_canonical is None and not target_variants:
        reason_codes.append("target_metadata_fixture_target_missing")
    if _fixture_sequence_over_limit(
        raw_entry.get("aliases"),
        limit=TARGET_METADATA_FIXTURE_MAX_ALIASES,
    ):
        reason_codes.append("target_metadata_fixture_alias_limit_exceeded")
    if _fixture_sequence_over_limit(
        raw_entry.get("target_variants"),
        limit=TARGET_METADATA_FIXTURE_MAX_TARGET_VARIANTS,
    ):
        reason_codes.append("target_metadata_fixture_variant_limit_exceeded")

    if reason_codes or source_canonical is None:
        return None, tuple(sorted(dict.fromkeys(reason_codes)))

    return {
        "source_canonical": source_canonical,
        "aliases": aliases,
        "target_canonical": target_canonical,
        "target_variants": target_variants,
    }, ()


def _overlay_target_metadata_entries(
    snapshot: GlossarySnapshot,
    fixture_entries: Sequence[Mapping[str, Any]],
) -> tuple[GlossarySnapshot, int]:
    fixture_by_source_key: dict[str, Mapping[str, Any]] = {}
    for fixture_entry in fixture_entries:
        for term in _fixture_entry_source_terms(fixture_entry):
            fixture_by_source_key.setdefault(_fixture_term_key(term), fixture_entry)

    matched_count = 0
    overlaid_entries: list[GlossaryEntry] = []
    for entry in snapshot.entries:
        fixture_entry = _matching_fixture_entry(entry, fixture_by_source_key)
        if fixture_entry is None:
            overlaid_entries.append(entry)
            continue
        matched_count += 1
        overlaid_entries.append(
            replace(
                entry,
                target_canonical=fixture_entry.get("target_canonical") or None,
                target_variants=tuple(fixture_entry.get("target_variants") or ()),
            )
        )
    if not matched_count:
        return snapshot, 0
    return replace(snapshot, entries=tuple(overlaid_entries)), matched_count


def _matching_fixture_entry(
    entry: GlossaryEntry,
    fixture_by_source_key: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    for term in _entry_source_terms(entry):
        match = fixture_by_source_key.get(_fixture_term_key(term))
        if match is not None:
            return match
    return None


def _fixture_entry_source_terms(entry: Mapping[str, Any]) -> tuple[str, ...]:
    terms = [str(entry["source_canonical"])]
    terms.extend(str(alias) for alias in entry.get("aliases") or ())
    return tuple(dict.fromkeys(term for term in terms if term.strip()))


def _fixture_term_key(term: str) -> str:
    return " ".join(term.casefold().split())


def _fixture_text_field(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text or len(text) > TARGET_METADATA_FIXTURE_MAX_FIELD_CHARS:
        return None
    if text in {"TBD", "Unknown"}:
        return None
    return text


def _fixture_text_sequence(value: Any, *, limit: int) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return ()
    result: list[str] = []
    for item in value[:limit]:
        text = _fixture_text_field(item)
        if text is not None:
            result.append(text)
    return tuple(dict.fromkeys(result))


def _fixture_sequence_over_limit(value: Any, *, limit: int) -> bool:
    return (
        not isinstance(value, (str, bytes))
        and isinstance(value, Sequence)
        and len(value) > limit
    )


def _raw_fixture_key_reason_codes(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        reasons: list[str] = []
        for key, item in value.items():
            if str(key).strip().casefold() in TARGET_METADATA_FIXTURE_RAW_KEYS:
                reasons.append("target_metadata_fixture_raw_field_present")
            reasons.extend(_raw_fixture_key_reason_codes(item))
        return reasons
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        reasons: list[str] = []
        for item in value:
            reasons.extend(_raw_fixture_key_reason_codes(item))
        return reasons
    return []


def _target_metadata_fixture_metadata(
    *,
    status: str,
    reason_codes: Sequence[str],
    input_path: Path,
    target_language: str,
    repo_root: Path,
    fixture_path: Path | None = None,
    fixture_id: str = "Unknown",
    fixture_signature: str = "Unknown",
    fixture_entry_count: int = 0,
    matched_entry_count: int = 0,
    unmatched_entry_count: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": TARGET_METADATA_FIXTURE_SCHEMA_VERSION,
        "policy": TARGET_METADATA_FIXTURE_POLICY,
        "status": status,
        "reason_codes": list(reason_codes),
        "fixture_id": _safe_fixture_identifier(fixture_id),
        "fixture_signature": fixture_signature,
        "fixture_path": (
            _display_path(fixture_path, repo_root=repo_root)
            if fixture_path is not None
            else "disabled"
        ),
        "input_id": _input_id(input_path, target_language),
        "target_language": target_language,
        "fixture_entry_count": fixture_entry_count,
        "matched_entry_count": matched_entry_count,
        "unmatched_entry_count": unmatched_entry_count,
        "metadata_only": True,
        "raw_payload_included": False,
        "normal_translation_prompts_changed": False,
        "live_provider_calls_allowed": False,
        "durable_state_mutation_allowed": False,
        "cache_mutation_allowed": False,
    }


def _target_metadata_fixture_signature(
    payload: Mapping[str, Any],
    *,
    target_language: str,
) -> str:
    target_payload = payload.get("targets", {})
    target_entries = (
        target_payload.get(target_language, {}).get("entries", ())
        if isinstance(target_payload, Mapping)
        else ()
    )
    digest_payload = {
        "schema_version": TARGET_METADATA_FIXTURE_SCHEMA_VERSION,
        "fixture_id": payload.get("fixture_id", "Unknown"),
        "target_language": target_language,
        "entries": target_entries,
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"target-metadata-fixture:v1:{digest}"


def _safe_fixture_identifier(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Unknown"
    return re.sub(r"[^A-Za-z0-9:._/-]+", "_", value.strip())[:128] or "Unknown"


def build_runtime_glossary_budget_plan(
    *,
    document_format: str,
    source_block_count: int,
    protected_marker_count: int,
    protected_text: str,
    config: SmokeConfig,
) -> dict[str, Any]:
    estimated_completion_pressure = estimate_tokens(protected_text)
    is_high_pressure_epub = document_format == "epub" and (
        source_block_count > 1
        or protected_marker_count > 0
        or estimated_completion_pressure > config.max_completion_tokens // 2
    )
    if not is_high_pressure_epub:
        return _runtime_glossary_budget_plan_payload(
            policy="default_runtime_smoke_budget",
            reason_codes=(),
            selection_prompt_tokens=DEFAULT_RUNTIME_SELECTION_PROMPT_TOKENS,
            selection_max_entries=DEFAULT_RUNTIME_SELECTION_MAX_ENTRIES,
            selection_max_diagnostic_entries=(
                DEFAULT_RUNTIME_SELECTION_MAX_DIAGNOSTIC_ENTRIES
            ),
            context_prompt_tokens=DEFAULT_RUNTIME_CONTEXT_PROMPT_TOKENS,
            context_max_entries=DEFAULT_RUNTIME_CONTEXT_MAX_ENTRIES,
            context_max_characters=DEFAULT_RUNTIME_CONTEXT_MAX_CHARACTERS,
            estimated_completion_pressure=estimated_completion_pressure,
            max_completion_tokens=config.max_completion_tokens,
        )

    completion_headroom = max(
        0,
        config.max_completion_tokens - estimated_completion_pressure,
    )
    context_prompt_tokens = min(
        DEFAULT_RUNTIME_CONTEXT_PROMPT_TOKENS,
        HIGH_PRESSURE_EPUB_CONTEXT_PROMPT_TOKEN_CAP,
        max(0, completion_headroom // 3),
    )
    context_max_entries = (
        0
        if context_prompt_tokens <= 0
        else min(
            DEFAULT_RUNTIME_CONTEXT_MAX_ENTRIES,
            HIGH_PRESSURE_EPUB_CONTEXT_MAX_ENTRIES,
        )
    )
    selection_prompt_tokens = min(
        DEFAULT_RUNTIME_SELECTION_PROMPT_TOKENS,
        max(HIGH_PRESSURE_EPUB_MIN_SELECTION_PROMPT_TOKENS, context_prompt_tokens),
    )
    selection_max_entries = min(
        DEFAULT_RUNTIME_SELECTION_MAX_ENTRIES,
        context_max_entries if context_max_entries else 1,
    )
    reason_codes = [
        "epub_completion_safety_reserved",
        "glossary_context_budget_reduced",
    ]
    if source_block_count > 1:
        reason_codes.append("epub_multi_source_block_unit")
    if protected_marker_count > 0:
        reason_codes.append("protected_markers_present")
    if estimated_completion_pressure > config.max_completion_tokens // 2:
        reason_codes.append("estimated_completion_pressure_high")
    if context_prompt_tokens <= 0:
        reason_codes.append("glossary_context_budget_omitted")

    return _runtime_glossary_budget_plan_payload(
        policy="epub_completion_first_pressure_budget",
        reason_codes=tuple(sorted(dict.fromkeys(reason_codes))),
        selection_prompt_tokens=selection_prompt_tokens,
        selection_max_entries=selection_max_entries,
        selection_max_diagnostic_entries=min(
            DEFAULT_RUNTIME_SELECTION_MAX_DIAGNOSTIC_ENTRIES,
            1 if context_max_entries else 0,
        ),
        context_prompt_tokens=context_prompt_tokens,
        context_max_entries=context_max_entries,
        context_max_characters=(
            0
            if context_prompt_tokens <= 0
            else min(
                DEFAULT_RUNTIME_CONTEXT_MAX_CHARACTERS,
                max(350, context_prompt_tokens * 4),
            )
        ),
        estimated_completion_pressure=estimated_completion_pressure,
        max_completion_tokens=config.max_completion_tokens,
    )


def format_runtime_glossary_prompt_context(
    entries: Iterable[Any],
    *,
    selected_entry_ids: Iterable[str],
    budget_plan: Mapping[str, Any],
    source_text: str | None = None,
    target_backed_source_present_only: bool = False,
) -> tuple[str, dict[str, Any]]:
    context_budget = budget_plan["prompt_context"]
    entries_tuple = tuple(entries)
    original_selected_ids = _compact_entry_ids(selected_entry_ids)
    context_selected_ids = original_selected_ids
    selection_filter = {
        "policy": "all_selected_entries",
        "input_selected_entry_count": len(original_selected_ids),
        "context_selected_entry_count": len(context_selected_ids),
        "useful_entry_ids": list(context_selected_ids),
        "reason_codes": [],
        "metadata_only": True,
        "raw_payload_included": False,
    }
    if target_backed_source_present_only:
        useful = _glossary_useful_preflight_metadata(
            entries_tuple,
            selected_entry_ids=original_selected_ids,
            source_text=source_text or "",
        )
        context_selected_ids = tuple(useful["useful_entry_ids"])
        selection_filter = {
            "policy": "target_backed_source_present_entries",
            "input_selected_entry_count": len(original_selected_ids),
            "context_selected_entry_count": len(context_selected_ids),
            "useful_entry_ids": list(context_selected_ids),
            "reason_codes": list(useful["reason_codes"]),
            "metadata_only": True,
            "raw_payload_included": False,
        }
    prompt_context = format_glossary_prompt_context(
        entries_tuple,
        selected_entry_ids=context_selected_ids,
        config=GlossaryPromptContextConfig(
            max_entries=context_budget["max_entries"],
            max_prompt_tokens=context_budget["max_prompt_tokens"],
            max_characters=context_budget["max_characters"],
        ),
    )
    metadata = glossary_prompt_context_metadata_payload(prompt_context)
    metadata["runtime_budget"] = _runtime_budget_metadata_payload(budget_plan)
    metadata["selection_filter"] = selection_filter
    text = prompt_context.text if prompt_context.included_entries else ""
    return text, metadata


def _compact_entry_ids(entry_ids: Iterable[Any]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(str(entry_id) for entry_id in entry_ids if str(entry_id).strip())
    )


def _runtime_glossary_budget_plan_payload(
    *,
    policy: str,
    reason_codes: Sequence[str],
    selection_prompt_tokens: int,
    selection_max_entries: int,
    selection_max_diagnostic_entries: int,
    context_prompt_tokens: int,
    context_max_entries: int,
    context_max_characters: int,
    estimated_completion_pressure: int,
    max_completion_tokens: int,
) -> dict[str, Any]:
    return {
        "schema_version": "glossary-runtime-budget-tuning-v1",
        "policy": policy,
        "reason_codes": list(reason_codes),
        "selection": {
            "max_prompt_tokens": selection_prompt_tokens,
            "max_entries": selection_max_entries,
            "max_diagnostic_entries": selection_max_diagnostic_entries,
        },
        "prompt_context": {
            "max_prompt_tokens": context_prompt_tokens,
            "max_entries": context_max_entries,
            "max_characters": context_max_characters,
        },
        "completion_safety": {
            "reserved_first": True,
            "estimated_completion_pressure_tokens": estimated_completion_pressure,
            "max_completion_tokens": max_completion_tokens,
        },
        "metadata_only": True,
        "raw_payload_included": False,
    }


def _runtime_budget_metadata_payload(
    budget_plan: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": budget_plan.get(
            "schema_version",
            "glossary-runtime-budget-tuning-v1",
        ),
        "policy": budget_plan.get("policy", "Unknown"),
        "reason_codes": list(budget_plan.get("reason_codes") or ()),
        "selection": dict(budget_plan.get("selection") or {}),
        "prompt_context": dict(budget_plan.get("prompt_context") or {}),
        "completion_safety": dict(budget_plan.get("completion_safety") or {}),
        "metadata_only": True,
        "raw_payload_included": False,
    }


def apply_runtime_pressure_fallback(
    package: RuntimeSmokePackage,
    *,
    config: SmokeConfig,
) -> RuntimeSmokePackage:
    decision = build_runtime_pressure_fallback_decision(package, config=config)
    if decision["action"] == "keep_glossary_prompt_context":
        return package
    return replace(
        package,
        prompt_context_text="",
        prompt_context_metadata=_pressure_degraded_prompt_context_metadata(
            package.prompt_context_metadata,
            decision=decision,
        ),
    )


def build_runtime_pressure_fallback_decision(
    package: RuntimeSmokePackage,
    *,
    config: SmokeConfig,
    pressure_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pressure_summary = pressure_summary or build_runtime_pressure_summary(
        package,
        config=config,
    )
    document = pressure_summary.get("document") or {}
    unit = pressure_summary.get("unit") or {}
    tokens = pressure_summary.get("tokens") or {}
    source_block_count = _optional_int(unit.get("source_block_id_count"))
    protected_marker_count = _optional_int(unit.get("protected_marker_count"))
    estimated_completion_pressure = _optional_int(
        tokens.get("estimated_protected_text_tokens")
    )

    reason_codes: list[str] = []
    if document.get("format") == "epub":
        if (
            source_block_count is not None
            and source_block_count > DEFAULT_PRESSURE_FALLBACK_MAX_EPUB_SOURCE_BLOCKS
        ):
            reason_codes.append("epub_source_block_count_exceeds_limit")
        if (
            protected_marker_count is not None
            and protected_marker_count
            > DEFAULT_PRESSURE_FALLBACK_MAX_EPUB_PROTECTED_MARKERS
        ):
            reason_codes.append("epub_protected_marker_count_exceeds_limit")
        if (
            estimated_completion_pressure is not None
            and estimated_completion_pressure > config.max_completion_tokens
        ):
            reason_codes.append("estimated_completion_pressure_exceeds_cap")

    action = (
        "omit_glossary_prompt_context"
        if reason_codes
        else "keep_glossary_prompt_context"
    )
    return {
        "schema_version": PRESSURE_FALLBACK_SCHEMA_VERSION,
        "action": action,
        "reason_codes": sorted(dict.fromkeys(reason_codes)),
        "thresholds": {
            "policy": PRESSURE_FALLBACK_THRESHOLD_POLICY,
            "max_epub_source_blocks": (
                DEFAULT_PRESSURE_FALLBACK_MAX_EPUB_SOURCE_BLOCKS
            ),
            "max_epub_protected_markers": (
                DEFAULT_PRESSURE_FALLBACK_MAX_EPUB_PROTECTED_MARKERS
            ),
            "max_estimated_completion_tokens": config.max_completion_tokens,
        },
        "metadata_only": True,
        "raw_payload_included": False,
        "normal_translation_prompts_changed": False,
        "live_provider_calls_allowed": False,
        "durable_state_mutation_allowed": False,
        "cache_mutation_allowed": False,
    }


def _pressure_degraded_prompt_context_metadata(
    metadata: Mapping[str, Any],
    *,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    included_entries = tuple(metadata.get("included_entries") or ())
    estimates_by_entry_id = {
        str(entry.get("entry_id")): _optional_int(entry.get("estimated_prompt_tokens"))
        for entry in included_entries
        if isinstance(entry, Mapping) and entry.get("entry_id")
    }
    omitted_entries = [dict(entry) for entry in metadata.get("omitted_entries") or ()]
    for entry_id in metadata.get("included_entry_ids") or ():
        omitted_entries.append(
            {
                "entry_id": str(entry_id),
                "reason": "high_pressure_epub_runtime_fallback",
                "estimated_prompt_tokens": _unknown_int(
                    estimates_by_entry_id.get(str(entry_id))
                ),
            }
        )
    degraded = dict(metadata)
    degraded.update(
        {
            "included_entry_ids": [],
            "included_entries": [],
            "omitted_entries": omitted_entries,
            "estimated_prompt_tokens": 0,
            "character_count": 0,
            "pressure_fallback": dict(decision),
        }
    )
    return degraded


def build_runtime_pressure_summary(
    package: RuntimeSmokePackage,
    *,
    config: SmokeConfig,
    estimated_prompt_tokens: int | None = None,
    reserved_tokens: int | None = None,
) -> dict[str, Any]:
    prompt_context_omitted = package.prompt_context_metadata.get(
        "omitted_entries",
        (),
    )
    pressure_fallback = package.prompt_context_metadata.get("pressure_fallback") or {}
    runtime_budget = package.prompt_context_metadata.get("runtime_budget") or {}
    runtime_budget_context = runtime_budget.get("prompt_context") or {}
    runtime_budget_completion = runtime_budget.get("completion_safety") or {}
    epub_runtime_unit_selection = package.prompt_context_metadata.get(
        "epub_runtime_unit_selection"
    )
    selected_entry_ids = package.adapter_metadata.get("selected_entry_ids") or ()
    selection_dropped = package.selection_metadata.get("dropped_entries") or ()
    cache_policy = package.adapter_metadata.get("cache_policy") or {}
    summary = {
        "schema_version": PRESSURE_SCHEMA_VERSION,
        "input_id": package.input_id,
        "target_language": package.target_language,
        "document": {
            "format": package.document_format,
            "fragment_count": package.fragment_count,
            "character_count": package.character_count,
        },
        "unit": {
            "sequence": package.unit_sequence,
            "source_block_id_count": len(package.source_block_ids),
            "source_character_count": len(package.source_text),
            "protected_text_character_count": len(package.protected_text),
            "protected_marker_count": _protected_marker_count(
                package.required_markers
            ),
        },
        "glossary": {
            "retained_entry_count": package.glossary_entry_count,
            "evidence_count": package.glossary_evidence_count,
            "selected_entry_count": len(selected_entry_ids),
            "prompt_context_included_entry_count": len(
                package.prompt_context_metadata.get("included_entry_ids") or ()
            ),
            "prompt_context_omitted_entry_count": len(prompt_context_omitted),
            "selection_dropped_entry_count": len(selection_dropped),
            "reducer_diagnostic_count": package.reducer_metadata.get(
                "diagnostic_count",
                "Unknown",
            ),
            "reducer_dropped_count": package.reducer_metadata.get(
                "dropped_count",
                "Unknown",
            ),
        },
        "tokens": {
            "estimated_source_tokens": estimate_tokens(package.source_text),
            "estimated_protected_text_tokens": estimate_tokens(
                package.protected_text
            ),
            "prompt_context_estimated_tokens": package.prompt_context_metadata.get(
                "estimated_prompt_tokens",
                "Unknown",
            ),
            "selection_estimated_prompt_tokens": package.selection_metadata.get(
                "estimated_prompt_tokens",
                "Unknown",
            ),
            "estimated_request_prompt_tokens": _unknown_int(
                estimated_prompt_tokens
            ),
            "reserved_request_tokens": _unknown_int(reserved_tokens),
            "max_completion_tokens": config.max_completion_tokens,
            "max_tokens_total": config.max_tokens_total,
        },
        "budget_tuning": {
            "policy": runtime_budget.get("policy", "default_runtime_smoke_budget"),
            "reason_codes": list(runtime_budget.get("reason_codes") or ()),
            "selection_prompt_budget_tokens": package.selection_metadata.get(
                "prompt_budget_tokens",
                "Unknown",
            ),
            "context_prompt_budget_tokens": runtime_budget_context.get(
                "max_prompt_tokens",
                package.prompt_context_metadata.get(
                    "prompt_budget_tokens",
                    "Unknown",
                ),
            ),
            "context_entry_limit": runtime_budget_context.get(
                "max_entries",
                package.prompt_context_metadata.get("entry_limit", "Unknown"),
            ),
            "estimated_completion_pressure_tokens": runtime_budget_completion.get(
                "estimated_completion_pressure_tokens",
                "Unknown",
            ),
            "completion_safety_reserved_first": runtime_budget_completion.get(
                "reserved_first",
                "Unknown",
            ),
        },
        "cache_policy": {
            "behavior": cache_policy.get("behavior", "Unknown"),
            "cache_get_allowed": cache_policy.get("cache_get_allowed", "Unknown"),
            "cache_put_allowed": cache_policy.get("cache_put_allowed", "Unknown"),
        },
        "fallback": {
            "glossary_plan_status": package.glossary_plan.get(
                "status",
                "Unknown",
            ),
            "glossary_plan_fallback_reason": package.glossary_plan.get(
                "fallback_reason",
                "Unknown",
            ),
            "work_unit_fallback_reason_codes": _work_unit_fallback_reason_codes(
                package.glossary_plan,
                package.unit_sequence,
            ),
            "selection_budget_exceeded": package.selection_metadata.get(
                "budget_exceeded",
                "Unknown",
            ),
            "prompt_context_omission_reasons": _prompt_context_omission_reasons(
                prompt_context_omitted
            ),
            "pressure_fallback_action": pressure_fallback.get(
                "action",
                "keep_glossary_prompt_context",
            ),
            "pressure_fallback_reason_codes": list(
                pressure_fallback.get("reason_codes") or ()
            ),
        },
        "output_contract": {
            "expected_translation_block_count": 1,
            "required_marker_group_count": len(package.required_markers),
            "risk_category": _output_contract_risk_category(package),
            "risk_reason_codes": _output_contract_risk_reasons(package),
            "threshold_policy": "TBD",
        },
        "raw_payload_included": False,
    }
    if isinstance(epub_runtime_unit_selection, Mapping):
        summary["epub_runtime_unit_selection"] = dict(epub_runtime_unit_selection)
    return summary


def _protected_marker_count(required_markers: Sequence[Sequence[str]]) -> int:
    return sum(len(group) for group in required_markers)


def _work_unit_fallback_reason_codes(
    glossary_plan: Mapping[str, Any],
    work_unit_sequence: int,
) -> list[str]:
    work_units = glossary_plan.get("work_unit_plans") or ()
    for item in work_units:
        if not isinstance(item, Mapping):
            continue
        if item.get("work_unit_sequence") != work_unit_sequence:
            continue
        reasons = item.get("fallback_reason_codes") or ()
        return sorted(str(reason) for reason in reasons)
    return []


def _prompt_context_omission_reasons(
    omitted_entries: Sequence[Any],
) -> list[str]:
    reasons: set[str] = set()
    for item in omitted_entries:
        if isinstance(item, Mapping):
            reason = item.get("reason")
            if reason:
                reasons.add(str(reason))
    return sorted(reasons)


def _output_contract_risk_category(package: RuntimeSmokePackage) -> str:
    source_block_count = len(package.source_block_ids)
    marker_count = _protected_marker_count(package.required_markers)
    is_epub = package.document_format == "epub"
    if is_epub and source_block_count > 1 and marker_count > 0:
        return "epub_multi_block_with_protected_markers"
    if is_epub and source_block_count > 1:
        return "epub_multi_block"
    if source_block_count > 1 and marker_count > 0:
        return "multi_block_with_protected_markers"
    if marker_count > 0:
        return "protected_marker"
    return "single_block_low_structural_pressure"


def _output_contract_risk_reasons(package: RuntimeSmokePackage) -> list[str]:
    reasons: list[str] = []
    if package.document_format == "epub":
        reasons.append("epub_adapter_unit")
    if len(package.source_block_ids) > 1:
        reasons.append("multiple_source_blocks")
    if _protected_marker_count(package.required_markers) > 0:
        reasons.append("protected_markers_present")
    if package.prompt_context_metadata.get("omitted_entries"):
        reasons.append("prompt_context_omissions_present")
    if package.selection_metadata.get("budget_exceeded"):
        reasons.append("selection_budget_exceeded")
    return reasons or ["single_source_block"]


def render_metadata_report(report: Mapping[str, Any]) -> str:
    rows = "\n".join(_call_report_row(call) for call in report["calls"])
    if not rows:
        rows = (
            "| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown "
            "| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown |\n"
        )
    pressure_rows = "\n".join(
        _pressure_report_row(call) for call in report["calls"]
    )
    if not pressure_rows:
        pressure_rows = (
            "| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown "
            "| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown "
            "| Unknown | Unknown | Unknown | Unknown |\n"
        )
    return (
        "# Glossary Runtime Provider Smoke Report\n\n"
        "## Confirmed\n"
        f"{_markdown_list(report['confirmed'])}\n\n"
        "## Unknown\n"
        f"{_markdown_list(report['unknown'] or ['None from this bounded run.'])}\n\n"
        "## TBD\n"
        f"{_markdown_list(report['tbd'])}\n\n"
        "## Approval Boundary\n"
        f"- Inputs/targets: {', '.join(report['approval']['input_targets'])}\n"
        f"- Selection: {report['approval']['selection']}\n"
        f"- Max calls: {report['approval']['max_calls']}\n"
        f"- Max tokens total: {report['approval']['max_tokens_total']}\n"
        f"- Provider/model: {report['approval']['provider_model']}\n"
        f"- Diagnostic storage: {report['approval']['diagnostic_storage']}\n"
        f"- Raw-text capture: {report['approval']['raw_text_capture']}\n\n"
        "## Runtime Smoke Results\n"
        "| Input | Target | Side | Unit | Status | Finish reason | Usage tokens "
        "| Validation issue codes | Glossary compliance | Target hits "
        "| Target misses | Skipped entries | Compliance reason codes |\n"
        "| --- | --- | --- | ---: | --- | --- | ---: | --- | --- | ---: "
        "| ---: | ---: | --- |\n"
        f"{rows}\n\n"
        "## Runtime Pressure Summary\n"
        "| Input | Target | Format | Unit | Source blocks | Source chars "
        "| Protected markers | Selected entries | Context tokens "
        "| Prompt tokens | Completion cap | Risk category | Fallback action "
        "| Fallback reason codes | Budget policy | Budget reason codes |\n"
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: "
        "| ---: | ---: | --- | --- | --- | --- | --- |\n"
        f"{pressure_rows}\n\n"
        "## Token And Latency Shape\n"
        f"- Mode: {report['mode']}\n"
        f"- Calls made: {report['calls_made']}\n"
        f"- Reserved tokens: {report['reserved_tokens']}\n"
        f"- Observed tokens: {report['observed_tokens']}\n"
        f"- Latency seconds: {_latency_shape(report['calls'])}\n\n"
        "## Recommendation\n"
        f"{report['recommendation']}\n"
    )


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def reserve_tokens(
    *,
    estimated_prompt_tokens: int,
    max_completion_tokens: int,
    prompt_token_multiplier: float,
) -> int:
    return math.ceil(estimated_prompt_tokens * max(1.0, prompt_token_multiplier)) + (
        max_completion_tokens
    )


def load_env_api_key() -> str:
    key_list = os.getenv("DEEPSEEK_API_KEYS", "")
    for candidate in key_list.split(","):
        api_key = candidate.strip()
        if api_key:
            return api_key
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnostic-root", default="")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--base-url",
        default=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument(
        "--max-tokens-total",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--max-completion-tokens",
        type=int,
        default=DEFAULT_MAX_COMPLETION_TOKENS,
    )
    parser.add_argument(
        "--target-metadata-fixture",
        default="",
        help=(
            "Optional owner-only local target-metadata fixture path for the "
            "default-off controlled EPUB glossary smoke path."
        ),
    )
    parser.add_argument(
        "--control-epub",
        action="store_true",
        help=(
            "Use the issue #507 committed control EPUB boundary: ru/uk targets, "
            "paired glossary-on/off calls, max 4 calls, and the approved local "
            "target-metadata fixture overlay."
        ),
    )
    parser.add_argument(
        "--policy-evidence-preflight",
        action="store_true",
        help=(
            "Run the issue #533 local-only policy-package fake/dry provider "
            "evidence preflight. No provider calls or API keys are used."
        ),
    )
    parser.add_argument(
        "--policy-evidence-live",
        action="store_true",
        help=(
            "Run the issue #534 bounded live policy-provider evidence smoke "
            "after the #533 fake/dry preflight. Requires DEEPSEEK_API_KEY or "
            "DEEPSEEK_API_KEYS in the temporary process environment."
        ),
    )
    parser.add_argument(
        "--issue-559-real-epub",
        action="store_true",
        help=(
            "Use the issue #559 real owner-approved EPUB boundary: ru target, "
            "paired glossary-on/off calls, effective max 2 calls, max 60000 "
            "tokens, and optional approved local target-metadata fixture overlay."
        ),
    )
    parser.add_argument(
        "--issue-575-adversarial-txt",
        action="store_true",
        help=(
            "Use the issue #575 adversarial TXT glossary matrix boundary: "
            "ru/uk targets, paired glossary-on/off calls, max 4 calls, and "
            "the approved committed target-metadata fixture overlay."
        ),
    )
    parser.add_argument(
        "--issue-586-post-584-adversarial-txt",
        action="store_true",
        help=(
            "Use the issue #586 post-#584 adversarial TXT glossary matrix "
            "boundary: the same approved #575 adversarial TXT inputs, pairing, "
            "caps, and target-metadata fixture, with the post-#584 diagnostics "
            "root."
        ),
    )
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--metadata-report", default="")
    args = parser.parse_args(argv)
    metadata_report_path = (
        Path(args.metadata_report) if args.metadata_report else None
    )
    if args.policy_evidence_preflight:
        run_policy_provider_evidence_preflight(
            metadata_report_path=metadata_report_path,
        )
        return 0
    if args.policy_evidence_live:
        api_key = load_env_api_key()
        if not api_key:
            raise SystemExit(
                "DEEPSEEK_API_KEY/DEEPSEEK_API_KEYS is not set in the "
                "process environment"
            )
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=args.base_url,
        )
        run_policy_provider_evidence_live_smoke(
            provider=provider,
            metadata_report_path=metadata_report_path,
        )
        return 0
    selected_boundaries = sum(
        bool(flag)
        for flag in (
            args.control_epub,
            args.issue_559_real_epub,
            args.issue_575_adversarial_txt,
            args.issue_586_post_584_adversarial_txt,
        )
    )
    if selected_boundaries > 1:
        raise SystemExit(
            "--control-epub, --issue-559-real-epub, "
            "--issue-575-adversarial-txt and "
            "--issue-586-post-584-adversarial-txt are mutually exclusive"
        )
    issue_id = (
        ISSUE_559_ID
        if args.issue_559_real_epub
        else (
            (
                ISSUE_586_ID
                if args.issue_586_post_584_adversarial_txt
                else ISSUE_575_ID
            )
            if args.issue_575_adversarial_txt
            or args.issue_586_post_584_adversarial_txt
            else (ISSUE_507_ID if args.control_epub else "477")
        )
    )
    diagnostic_root = (
        ISSUE_559_DIAGNOSTIC_ROOT
        if args.issue_559_real_epub
        else (
            (
                ISSUE_586_DIAGNOSTIC_ROOT
                if args.issue_586_post_584_adversarial_txt
                else ISSUE_575_DIAGNOSTIC_ROOT
            )
            if args.issue_575_adversarial_txt
            or args.issue_586_post_584_adversarial_txt
            else (
                ISSUE_507_DIAGNOSTIC_ROOT
                if args.control_epub
                else DEFAULT_DIAGNOSTIC_ROOT
            )
        )
    )
    target_metadata_fixture_path = (
        ISSUE_559_TARGET_METADATA_FIXTURE_PATH
        if args.issue_559_real_epub
        else (
            ISSUE_575_TARGET_METADATA_FIXTURE_PATH
            if args.issue_575_adversarial_txt
            or args.issue_586_post_584_adversarial_txt
            else (DEFAULT_TARGET_METADATA_FIXTURE_PATH if args.control_epub else None)
        )
    )
    if args.diagnostic_root:
        diagnostic_root = Path(args.diagnostic_root)
    if args.target_metadata_fixture:
        target_metadata_fixture_path = Path(args.target_metadata_fixture)
    max_calls = (
        args.max_calls
        if args.max_calls is not None
        else (
            ISSUE_559_EFFECTIVE_MAX_CALLS
            if args.issue_559_real_epub
            else (
                ISSUE_575_MAX_CALLS
                if args.issue_575_adversarial_txt
                or args.issue_586_post_584_adversarial_txt
                else (ISSUE_507_MAX_CALLS if args.control_epub else DEFAULT_MAX_CALLS)
            )
        )
    )
    max_tokens_total = (
        args.max_tokens_total
        if args.max_tokens_total is not None
        else (
            ISSUE_559_MAX_TOKENS_TOTAL
            if args.issue_559_real_epub
            else (
                ISSUE_575_MAX_TOKENS_TOTAL
                if args.issue_575_adversarial_txt
                or args.issue_586_post_584_adversarial_txt
                else DEFAULT_MAX_TOKENS_TOTAL
            )
        )
    )
    config = SmokeConfig(
        issue_id=issue_id,
        input_targets=(
            ISSUE_559_INPUT_TARGETS
            if args.issue_559_real_epub
            else (
                ISSUE_575_INPUT_TARGETS
                if args.issue_575_adversarial_txt
                or args.issue_586_post_584_adversarial_txt
                else (
                    APPROVED_OWNER_TEST_INPUT_TARGETS
                    if args.control_epub
                    else APPROVED_INPUT_TARGETS
                )
            )
        ),
        diagnostic_root=diagnostic_root,
        provider_model=args.model,
        provider_base_url=args.base_url,
        max_calls=max_calls,
        max_tokens_total=max_tokens_total,
        max_completion_tokens=args.max_completion_tokens,
        raw_text_capture=True,
        fake=args.fake,
        target_metadata_fixture_path=target_metadata_fixture_path,
        paired_glossary_off=(
            args.control_epub
            or args.issue_559_real_epub
            or args.issue_575_adversarial_txt
            or args.issue_586_post_584_adversarial_txt
        ),
    )
    provider: ChatProvider
    if args.fake:
        provider = FakeRuntimeProvider()
    else:
        api_key = load_env_api_key()
        if not api_key:
            raise SystemExit(
                "DEEPSEEK_API_KEY/DEEPSEEK_API_KEYS is not set in the "
                "process environment"
            )
        provider = OpenAICompatibleProvider(
            api_key=api_key,
            base_url=config.provider_base_url,
        )
    run_smoke(
        config,
        provider=provider,
        metadata_report_path=metadata_report_path,
    )
    return 0


def _build_package_or_skip(
    input_path: Path,
    target_language: str,
    *,
    config: SmokeConfig,
    repo_root: Path,
) -> RuntimeSmokePackage | dict[str, Any]:
    try:
        return build_runtime_package(
            input_path,
            target_language,
            config=config,
            repo_root=repo_root,
        )
    except RuntimePackageSelectionError as error:
        path = _resolve_input_path(input_path, repo_root=repo_root)
        return {
            "input_id": _input_id(path, target_language),
            "input_path": _display_path(path, repo_root=repo_root),
            "target_language": target_language,
            "document_format": error.metadata.get("document_format", "Unknown"),
            "status": "skipped_selection",
            "skip_reason": error.__class__.__name__,
            "skip_code": error.code,
            "epub_runtime_unit_selection": dict(error.metadata),
        }
    except Exception as error:
        path = _resolve_input_path(input_path, repo_root=repo_root)
        return {
            "input_id": _input_id(path, target_language),
            "input_path": _display_path(path, repo_root=repo_root),
            "target_language": target_language,
            "status": "skipped_selection",
            "skip_reason": error.__class__.__name__,
            "skip_code": str(error) or "Unknown",
        }


def _validate_config(config: SmokeConfig) -> None:
    if config.issue_id not in {
        "477",
        ISSUE_507_ID,
        ISSUE_559_ID,
        ISSUE_575_ID,
        ISSUE_586_ID,
    }:
        raise ValueError("issue_id does not match an approved smoke boundary.")
    if config.provider_model != DEFAULT_MODEL:
        raise ValueError("provider_model does not match approved model.")
    if config.provider_base_url.rstrip("/") != DEFAULT_BASE_URL:
        raise ValueError("provider_base_url does not match approved provider boundary.")
    if config.issue_id == ISSUE_507_ID:
        if config.target_metadata_fixture_path is None:
            raise ValueError("issue 507 requires target metadata fixture overlay.")
        if any(
            item not in APPROVED_OWNER_TEST_INPUT_TARGETS
            for item in config.input_targets
        ):
            raise ValueError("issue 507 input_targets must use the control EPUB only.")
        if not config.paired_glossary_off:
            raise ValueError("issue 507 requires paired glossary-off calls.")
        if config.max_calls > ISSUE_507_MAX_CALLS:
            raise ValueError("max_calls exceeds issue 507 approved cap.")
        if not config.fake and config.diagnostic_root != ISSUE_507_DIAGNOSTIC_ROOT:
            raise ValueError("diagnostic_root does not match issue 507 boundary.")
    elif config.issue_id == ISSUE_559_ID:
        if any(item not in ISSUE_559_INPUT_TARGETS for item in config.input_targets):
            raise ValueError(
                "issue 559 input_targets must use the approved real EPUB only."
            )
        if not config.paired_glossary_off:
            raise ValueError("issue 559 requires paired glossary-off calls.")
        if config.max_calls > ISSUE_559_EFFECTIVE_MAX_CALLS:
            raise ValueError("max_calls exceeds issue 559 effective approved cap.")
        if not config.fake and config.diagnostic_root != ISSUE_559_DIAGNOSTIC_ROOT:
            raise ValueError("diagnostic_root does not match issue 559 boundary.")
        if not config.fake and config.target_metadata_fixture_path is None:
            raise ValueError("issue 559 live requires target metadata fixture overlay.")
    elif config.issue_id in {ISSUE_575_ID, ISSUE_586_ID}:
        if config.target_metadata_fixture_path is None:
            raise ValueError(
                "adversarial TXT requires target metadata fixture overlay."
            )
        if any(item not in ISSUE_575_INPUT_TARGETS for item in config.input_targets):
            raise ValueError(
                "adversarial TXT input_targets must use the approved fixture only."
            )
        if not config.paired_glossary_off:
            raise ValueError("adversarial TXT requires paired glossary-off calls.")
        if config.max_calls > ISSUE_575_MAX_CALLS:
            raise ValueError("max_calls exceeds adversarial TXT approved cap.")
        approved_root = (
            ISSUE_586_DIAGNOSTIC_ROOT
            if config.issue_id == ISSUE_586_ID
            else ISSUE_575_DIAGNOSTIC_ROOT
        )
        if not config.fake and config.diagnostic_root != approved_root:
            raise ValueError(
                "diagnostic_root does not match adversarial TXT boundary."
            )
    else:
        if any(
            item in APPROVED_OWNER_TEST_INPUT_TARGETS
            for item in config.input_targets
        ):
            raise ValueError("control EPUB targets require issue 507 boundary.")
        if config.paired_glossary_off:
            raise ValueError("paired glossary-off calls require issue 507 boundary.")
        if not config.fake and config.diagnostic_root != DEFAULT_DIAGNOSTIC_ROOT:
            raise ValueError("diagnostic_root does not match approved boundary.")
        if config.max_calls > DEFAULT_MAX_CALLS:
            raise ValueError("max_calls exceeds approved cap.")
    if config.max_tokens_total > _max_tokens_total_cap(config):
        raise ValueError("max_tokens_total exceeds approved cap.")
    if not config.raw_text_capture:
        raise ValueError("raw_text_capture must match approved yes boundary.")
    approved = _approved_input_targets_for_config(config)
    if any(item not in approved for item in config.input_targets):
        raise ValueError("input_targets must be a subset of approved inputs/targets.")


def _approval_payload(config: SmokeConfig) -> dict[str, Any]:
    return {
        "issue_id": config.issue_id,
        "input_targets": [f"{path}::{target}" for path, target in config.input_targets],
        "selection": _selection_description(config),
        "max_calls": config.max_calls,
        "max_tokens_total": config.max_tokens_total,
        "provider_model": config.provider_model,
        "diagnostic_storage": str(config.diagnostic_root),
        "raw_text_capture": (
            "yes; only bounded fixture/book excerpts, prompts and provider "
            "responses inside the owner-only untracked diagnostics directory"
        ),
        "target_metadata_fixture": (
            str(config.target_metadata_fixture_path)
            if config.target_metadata_fixture_path is not None
            else "disabled"
        ),
        "paired_glossary_off": config.paired_glossary_off,
    }


def _approved_input_targets_for_config(config: SmokeConfig) -> set[tuple[Path, str]]:
    if config.issue_id == ISSUE_507_ID:
        return set(APPROVED_OWNER_TEST_INPUT_TARGETS)
    if config.issue_id == ISSUE_559_ID:
        return set(ISSUE_559_INPUT_TARGETS)
    if config.issue_id in {ISSUE_575_ID, ISSUE_586_ID}:
        return set(ISSUE_575_INPUT_TARGETS)
    approved = set(APPROVED_INPUT_TARGETS)
    if config.target_metadata_fixture_path is not None:
        approved.update(APPROVED_OWNER_TEST_INPUT_TARGETS)
    return approved


def _selection_description(config: SmokeConfig) -> str:
    if config.issue_id == ISSUE_507_ID:
        return (
            "first #505-selected glossary-useful, pressure-safe EPUB runtime "
            "unit per target; paired glossary-on and glossary-off"
        )
    if config.issue_id == ISSUE_559_ID:
        return (
            "first glossary-useful, pressure-safe real EPUB runtime unit with "
            "approved target metadata; paired glossary-on and glossary-off; "
            "max 1 ru target"
        )
    if config.issue_id in {ISSUE_575_ID, ISSUE_586_ID}:
        return (
            "first glossary-useful READY adversarial TXT runtime unit per target "
            "with approved target metadata; paired glossary-on and glossary-off"
        )
    return "first READY glossary-injected runtime test-path unit"


def _max_tokens_total_cap(config: SmokeConfig) -> int:
    if config.issue_id == ISSUE_559_ID:
        return ISSUE_559_MAX_TOKENS_TOTAL
    if config.issue_id in {ISSUE_575_ID, ISSUE_586_ID}:
        return ISSUE_575_MAX_TOKENS_TOTAL
    return DEFAULT_MAX_TOKENS_TOTAL


def _approved_input_path(
    input_path: Path,
    target_language: str,
    *,
    repo_root: Path,
    config: SmokeConfig,
) -> Path:
    if (input_path, target_language) not in _approved_input_targets_for_config(
        config
    ):
        raise ValueError(
            f"input target is not approved: {input_path}::{target_language}"
        )
    resolved = _resolve_input_path(input_path, repo_root=repo_root)
    if not resolved.is_file():
        raise FileNotFoundError(f"approved input is missing: {input_path}")
    return resolved


def _resolve_input_path(path: Path, *, repo_root: Path) -> Path:
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def _plan_input(path: Path, *, max_fragment_chars: int) -> Any:
    content = path.read_bytes()
    if path.suffix.lower() == ".epub":
        return plan_epub_translation(
            content=content,
            max_fragment_chars=max_fragment_chars,
        )
    return plan_txt_translation(content=content, max_fragment_chars=max_fragment_chars)


def _one_unit_glossary_plan(
    *,
    selection_metadata: Mapping[str, Any],
    reducer_metadata: Mapping[str, Any],
    snapshot: Any,
    selected_rule_ids: Sequence[str],
    source_language: str,
    target_language: str,
) -> dict[str, Any]:
    aggregate_selection_signature = _aggregate_selection_signature(
        [str(selection_metadata["selection_signature"])]
    )
    policy_context = translation_policy_signature_context_payload(
        translation_policy_signature_context_from_snapshot(
            snapshot,
            selection_signature=aggregate_selection_signature,
        )
    )
    work_unit = _work_unit_payload(selection_metadata, reducer_metadata)
    status = (
        "planned_with_budget_fallback"
        if work_unit["fallback_reason_codes"]
        else "planned"
    )
    fallback_reason = (
        "prompt_budget_exhausted" if work_unit["fallback_reason_codes"] else "none"
    )
    return {
        "schema_version": "glossary-runtime-shadow-plan-v1",
        "enabled": True,
        "status": status,
        "fallback_reason": fallback_reason,
        "source_language": source_language,
        "target_language": target_language,
        "translation_mode": "book",
        "planned_work_unit_count": 1,
        "source_glossary_signature": reducer_metadata["source_glossary_signature"],
        "glossary_signature": snapshot.glossary_signature,
        "reduced_glossary_signature": reducer_metadata["reduced_glossary_signature"],
        "profile_signature": snapshot.profile_signature,
        "translation_snapshot_signature": translation_contract_snapshot_signature(
            snapshot
        ),
        "aggregate_selection_signature": aggregate_selection_signature,
        "selected_rule_ids": list(selected_rule_ids),
        "policy_signature_context": policy_context,
        "work_unit_plans": [work_unit],
        "runtime_integration": {
            "normal_translation_prompts_changed": False,
            "live_provider_calls_allowed": False,
            "durable_state_mutation_allowed": False,
            "cache_mutation_allowed": False,
            "fallback_action": "omit_glossary_prompt_context",
        },
    }


def _work_unit_payload(
    selection: Mapping[str, Any],
    reducer_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    drop_reasons = sorted({entry["reason"] for entry in selection["dropped_entries"]})
    fallback_reasons = []
    if selection["budget_exceeded"]:
        fallback_reasons.append("selection_budget_exceeded")
    if "prompt_budget_exhausted" in drop_reasons:
        fallback_reasons.append("prompt_budget_exhausted")
    return {
        "work_unit_sequence": selection["work_unit_sequence"],
        "source_block_ids": list(selection["source_block_ids"]),
        "source_glossary_signature": reducer_metadata["source_glossary_signature"],
        "reduced_glossary_signature": reducer_metadata["reduced_glossary_signature"],
        "reducer_signature": reducer_metadata["reducer_signature"],
        "prompt_budget_tokens": selection["prompt_budget_tokens"],
        "estimated_prompt_tokens": selection["estimated_prompt_tokens"],
        "budget_exceeded": selection["budget_exceeded"],
        "budget_status": (
            "fallback_omitted" if fallback_reasons else "within_budget"
        ),
        "fallback_reason_codes": sorted(dict.fromkeys(fallback_reasons)),
        "selected_entry_ids": [
            entry["entry_id"] for entry in selection["selected_entries"]
        ],
        "dropped_entry_ids": [
            entry["entry_id"] for entry in selection["dropped_entries"]
        ],
        "drop_reasons": drop_reasons,
        "selection_signature": selection["selection_signature"],
        "policy_version": selection["policy_version"],
        "fallback_action": (
            "omit_glossary_prompt_context"
            if fallback_reasons
            else "shadow_metadata_only"
        ),
    }


def _reducer_metadata(
    reduction: Any,
    *,
    retained_snapshot: GlossarySnapshot | None = None,
    target_metadata_fixture: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = glossary_candidate_reduction_payload(reduction)
    reduced_glossary_signature = payload["reduced_glossary_signature"]
    if retained_snapshot is not None:
        reduced_glossary_signature = glossary_snapshot_signature(retained_snapshot)
    metadata = {
        "policy_version": payload["policy_version"],
        "reducer_signature": payload["reducer_signature"],
        "source_glossary_signature": payload["source_glossary_signature"],
        "reduced_glossary_signature": reduced_glossary_signature,
        "profile_signature": payload["profile_signature"],
        "pressure_signature": payload["pressure_signature"],
        "retained_count": len(reduction.retained_entry_ids),
        "diagnostic_count": len(reduction.diagnostic_entry_ids),
        "dropped_count": len(reduction.dropped_entry_ids),
    }
    if target_metadata_fixture is not None:
        metadata["target_metadata_fixture"] = dict(target_metadata_fixture)
    return metadata


def _unit_by_sequence(units: Sequence[Any], sequence: int) -> Any:
    for unit in units:
        if unit.sequence == sequence:
            return unit
    raise ValueError(f"missing selected unit sequence: {sequence}")


def _policy_sample_text(plan: Any) -> str:
    parts: list[str] = []
    remaining = 2_000
    for unit in plan.units:
        text = unit.source_text.strip()
        if not text:
            continue
        if len(text) > remaining:
            parts.append(text[:remaining])
            break
        parts.append(text)
        remaining -= len(text) + 2
        if remaining <= 0:
            break
    return "\n\n".join(parts) or "Unknown"


def _format_translation_request_text(
    texts: list[str],
    source_language_hints: list[str | None] | None = None,
    *,
    glossary_prompt_context: str | None = None,
) -> str:
    batch = _format_translation_batch(
        texts,
        source_language_hints=source_language_hints,
    )
    if not glossary_prompt_context:
        return batch
    return f"{glossary_prompt_context}\n\n{batch}"


def _format_translation_batch(
    texts: list[str],
    source_language_hints: list[str | None] | None = None,
) -> str:
    lines = ["<translation_batch>"]
    for index, text in enumerate(texts):
        source_language_hint = (
            source_language_hints[index]
            if source_language_hints is not None and index < len(source_language_hints)
            else None
        )
        attributes = f' id="{index}"'
        if source_language_hint:
            attributes += (
                f' source_language="{html.escape(source_language_hint, quote=True)}"'
            )
        lines.append(
            f"<translation_block{attributes}>"
            f"{html.escape(text, quote=False)}"
            "</translation_block>"
        )
    lines.append("</translation_batch>")
    return "\n".join(lines)


def _wrap_untrusted_document_content(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return (
        f"BEGIN_UNTRUSTED_DOCUMENT_CONTENT sha256={digest}\n"
        f"{text}\n"
        f"END_UNTRUSTED_DOCUMENT_CONTENT sha256={digest}"
    )


def _first_translation_block_text(user_prompt: str) -> str:
    start = user_prompt.index("<translation_batch>")
    end = user_prompt.index("</translation_batch>") + len("</translation_batch>")
    document = ElementTree.fromstring(user_prompt[start:end])
    block = next(iter(document))
    return block.text or ""


def _aggregate_selection_signature(selection_signatures: Iterable[str]) -> str:
    payload = {
        "schema_version": "glossary-runtime-provider-smoke-v1",
        "selection_signatures": sorted(str(item) for item in selection_signatures),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return f"glossary-shadow-selection:v1:{digest}"


def _call_summary(
    *,
    package: RuntimeSmokePackage,
    side: str,
    config: SmokeConfig,
    call_index: int,
    estimated_prompt_tokens: int,
    reservation: int,
    result: ChatCallResult,
    validation: Mapping[str, Any],
    glossary_compliance: Mapping[str, Any],
    observed_over_cap: bool,
) -> dict[str, Any]:
    return {
        "call_index": call_index,
        "side": side,
        "input_id": package.input_id,
        "input_path": str(package.input_path),
        "target_language": package.target_language,
        "document_format": package.document_format,
        "unit_sequence": package.unit_sequence,
        "source_block_id_count": len(package.source_block_ids),
        "selected_entry_count": len(package.adapter_metadata["selected_entry_ids"]),
        "status": "validated" if result.ok and validation["valid"] else "failed",
        "http_status": result.http_status,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "finish_reason": result.finish_reason or "Unknown",
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "reserved_tokens": reservation,
        "observed_over_cap": observed_over_cap,
        "usage": dict(result.usage),
        "validation": dict(validation),
        "glossary_compliance": dict(glossary_compliance),
        "error_type": result.error_type,
        "error_message": result.error_message,
        "pressure_summary": build_runtime_pressure_summary(
            package,
            config=config,
            estimated_prompt_tokens=estimated_prompt_tokens,
            reserved_tokens=reservation,
        ),
        "adapter": {
            "status": package.adapter_metadata["status"],
            "cache_policy": package.adapter_metadata["cache_policy"],
            "work_unit_selection_signature": (
                package.adapter_metadata["work_unit_selection_signature"]
            ),
        },
        "prompt_context": {
            "included_entry_count": len(
                package.prompt_context_metadata["included_entry_ids"]
            ),
            "omitted_entry_count": len(
                package.prompt_context_metadata["omitted_entries"]
            ),
            "estimated_prompt_tokens": (
                package.prompt_context_metadata["estimated_prompt_tokens"]
            ),
        },
    }


def _skipped_call_summary(
    package: RuntimeSmokePackage,
    status: str,
    *,
    side: str = "glossary_on",
    config: SmokeConfig,
    estimated_prompt_tokens: int | None = None,
    reservation: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "input_id": package.input_id,
        "side": side,
        "input_path": str(package.input_path),
        "target_language": package.target_language,
        "document_format": package.document_format,
        "unit_sequence": package.unit_sequence,
        "status": status,
        "pressure_summary": build_runtime_pressure_summary(
            package,
            config=config,
            estimated_prompt_tokens=estimated_prompt_tokens,
            reserved_tokens=reservation,
        ),
        **extra,
    }


def _call_diagnostic(
    *,
    package: RuntimeSmokePackage,
    side: str,
    system_prompt: str,
    user_prompt: str,
    request_text: str,
    result: ChatCallResult,
    validation_summary: Mapping[str, Any],
    glossary_compliance: Mapping[str, Any],
    raw_text_capture: bool,
    pressure_summary: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "diagnostic_scope": "owner_only_glossary_runtime_provider_smoke",
        "input_id": package.input_id,
        "side": side,
        "input_path": str(package.input_path),
        "target_language": package.target_language,
        "unit_sequence": package.unit_sequence,
        "raw_text_capture": raw_text_capture,
        "access_boundary": {
            "visibility": "owner_only",
            "ordinary_logs_allowed": False,
            "telemetry_allowed": False,
            "github_issue_or_pr_allowed": False,
            "release_artifact_allowed": False,
        },
        "secret_exclusion_policy": (
            "Provider Authorization headers, API keys, tokens and real .env* "
            "values are not stored."
        ),
        "request_payload": result.request_payload,
        "response_payload": result.response_payload,
        "response_text": result.response_text,
        "model_content": result.content,
        "usage": dict(result.usage),
        "http_status": result.http_status,
        "finish_reason": result.finish_reason,
        "validation": validation_summary,
        "glossary_compliance": dict(glossary_compliance),
        "pressure_summary": dict(pressure_summary),
        "adapter_metadata": dict(package.adapter_metadata),
        "prompt_context_metadata": dict(package.prompt_context_metadata),
        "selection_metadata": dict(package.selection_metadata),
        "reducer_metadata": dict(package.reducer_metadata),
    }
    if raw_text_capture:
        payload["system_prompt"] = system_prompt
        payload["user_prompt"] = user_prompt
        payload["runtime_request_text"] = request_text
        payload["bounded_source_excerpt"] = package.source_text[
            :DEFAULT_MAX_FRAGMENT_CHARS
        ]
    return payload


def _issue(code: str, path: str) -> dict[str, str]:
    return {"code": code, "path": path}


def _runtime_glossary_compliance_summary(
    result: ChatCallResult,
    *,
    package: RuntimeSmokePackage,
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    translated_text: str | None = None
    if validation.get("valid") is True:
        batch_validation = normalize_provider_translation_batch_contract(
            result.content,
            expected_count=1,
            required_markers=package.required_markers,
        )
        if batch_validation.translated_texts is not None:
            translated_text = "\n\n".join(batch_validation.translated_texts)
    return validate_glossary_compliance(
        package.glossary_entries,
        selected_entry_ids=_runtime_glossary_compliance_entry_ids(package),
        source_text=package.source_text,
        translated_text=translated_text,
        included_entry_ids=package.prompt_context_metadata.get(
            "included_entry_ids",
            (),
        ),
        structural_validation_passed=validation.get("valid") is True,
    )


def _runtime_glossary_compliance_entry_ids(
    package: RuntimeSmokePackage,
) -> tuple[str, ...]:
    selected_entry_ids = _compact_entry_ids(
        package.adapter_metadata.get("selected_entry_ids", ())
    )
    selection_filter = package.prompt_context_metadata.get("selection_filter", {})
    should_use_included_entries = package.document_format == "epub" or (
        isinstance(selection_filter, Mapping)
        and selection_filter.get("policy") == "target_backed_source_present_entries"
    )
    if not should_use_included_entries:
        return selected_entry_ids
    included_entry_ids = _compact_entry_ids(
        package.prompt_context_metadata.get("included_entry_ids", ())
    )
    if included_entry_ids:
        return included_entry_ids
    return selected_entry_ids


def _smoke_status(calls: Sequence[Mapping[str, Any]]) -> str:
    if any(call.get("observed_over_cap") is True for call in calls):
        return "completed_token_cap_exceeded"
    if any(str(call.get("status", "")).startswith("skipped") for call in calls):
        return "completed_with_skips"
    if any(call.get("status") == "failed" for call in calls):
        return "completed_with_failures"
    return "completed"


def _confirmed_items(
    config: SmokeConfig,
    calls: Sequence[Mapping[str, Any]],
) -> list[str]:
    items = [
        "fake/dry preflight is supported by the same bounded runner",
        "approved input/target/call/token/model/diagnostic bounds are enforced",
        (
            "ordinary metadata report excludes raw prompts, source text and "
            "provider bodies"
        ),
        "runtime translation/cache/storage/admin behavior was not changed",
    ]
    if any(call.get("glossary_compliance") for call in calls):
        items.append(
            "glossary compliance summaries are metadata-only and separate from "
            "structural validation"
        )
    if config.fake and any(call.get("status") == "validated" for call in calls):
        items.append("fake provider stub responses passed local validation")
    elif any(call.get("status") == "validated" for call in calls):
        items.append("at least one runtime smoke provider response passed validation")
    if not config.fake:
        items.append(
            "live mode used the approved DeepSeek-compatible provider boundary"
        )
    return items


def _unknown_items(
    config: SmokeConfig,
    calls: Sequence[Mapping[str, Any]],
) -> list[str]:
    unknown: list[str] = []
    if config.fake:
        unknown.append(
            "live provider behavior is Unknown because only fake provider "
            "stub calls were made"
        )
        unknown.append(
            "translation quality is Unknown because fake outputs are not "
            "quality evidence"
        )
    if not calls:
        unknown.append("provider behavior is Unknown because no calls were made")
    if any(
        "usage" in call and _usage_total_tokens(call.get("usage")) is None
        for call in calls
    ):
        unknown.append("provider-reported token usage is Unknown for one or more calls")
    if any(call.get("status") == "failed" for call in calls):
        unknown.append("one or more runtime smoke outputs did not validate")
    return unknown


def _recommendation(
    config: SmokeConfig,
    calls: Sequence[Mapping[str, Any]],
) -> str:
    if any(call.get("observed_over_cap") is True for call in calls):
        return "stop: observed provider usage exceeded the approved token cap."
    if any(call.get("status") == "failed" for call in calls):
        return (
            "iterate_runtime_prompt_before_rollout: at least one response "
            "failed validation."
        )
    if config.fake:
        return (
            "fake_preflight_passed_live_provider_behavior_unknown: request exact "
            "owner approval before live calls."
        )
    if any(
        (call.get("glossary_compliance") or {}).get("status") == "findings"
        for call in calls
    ):
        return (
            "review_glossary_compliance_findings_before_rollout: structural "
            "validation passed but target-form compliance has findings."
        )
    if any(str(call.get("status", "")).startswith("skipped") for call in calls):
        return (
            "review_skips_before_next_gate: smoke completed with metadata-only "
            "skips."
        )
    return (
        "proceed_to_owner_only_quality_review_candidate: provider-boundary smoke "
        "passed."
    )


def _call_report_row(call: Mapping[str, Any]) -> str:
    usage = call.get("usage") or {}
    validation = call.get("validation") or {}
    issue_codes = validation.get("issue_codes") or ["none"]
    compliance = call.get("glossary_compliance") or {}
    compliance_codes = compliance.get("reason_codes") or ["none"]
    return (
        f"| {call.get('input_id', 'Unknown')} "
        f"| {call.get('target_language', 'Unknown')} "
        f"| {call.get('side', 'Unknown')} "
        f"| {call.get('unit_sequence', 'Unknown')} "
        f"| {call.get('status', 'Unknown')} "
        f"| {call.get('finish_reason', 'Unknown')} "
        f"| {usage.get('total_tokens', 'Unknown')} "
        f"| {', '.join(str(code) for code in issue_codes)} "
        f"| {compliance.get('status', 'Unknown')} "
        f"| {compliance.get('target_form_present_count', 'Unknown')} "
        f"| {compliance.get('target_form_missing_count', 'Unknown')} "
        f"| {compliance.get('skipped_entry_count', 'Unknown')} "
        f"| {', '.join(str(code) for code in compliance_codes)} |"
    )


def _pressure_report_row(call: Mapping[str, Any]) -> str:
    pressure = call.get("pressure_summary") or {}
    document = pressure.get("document") or {}
    unit = pressure.get("unit") or {}
    glossary = pressure.get("glossary") or {}
    tokens = pressure.get("tokens") or {}
    budget_tuning = pressure.get("budget_tuning") or {}
    fallback = pressure.get("fallback") or {}
    output_contract = pressure.get("output_contract") or {}
    fallback_codes = fallback.get("pressure_fallback_reason_codes") or ["none"]
    budget_codes = budget_tuning.get("reason_codes") or ["none"]
    return (
        f"| {call.get('input_id', 'Unknown')} "
        f"| {call.get('target_language', 'Unknown')} "
        f"| {document.get('format', call.get('document_format', 'Unknown'))} "
        f"| {unit.get('sequence', call.get('unit_sequence', 'Unknown'))} "
        f"| {unit.get('source_block_id_count', 'Unknown')} "
        f"| {unit.get('source_character_count', 'Unknown')} "
        f"| {unit.get('protected_marker_count', 'Unknown')} "
        f"| {glossary.get('selected_entry_count', 'Unknown')} "
        f"| {tokens.get('prompt_context_estimated_tokens', 'Unknown')} "
        f"| {tokens.get('estimated_request_prompt_tokens', 'Unknown')} "
        f"| {tokens.get('max_completion_tokens', 'Unknown')} "
        f"| {output_contract.get('risk_category', 'Unknown')} "
        f"| {fallback.get('pressure_fallback_action', 'Unknown')} "
        f"| {', '.join(str(code) for code in fallback_codes)} "
        f"| {budget_tuning.get('policy', 'Unknown')} "
        f"| {', '.join(str(code) for code in budget_codes)} |"
    )


def _latency_shape(calls: Sequence[Mapping[str, Any]]) -> str:
    values = [
        float(call["elapsed_seconds"])
        for call in calls
        if isinstance(call.get("elapsed_seconds"), (int, float))
    ]
    if not values:
        return "Unknown"
    average = sum(values) / len(values)
    return f"min={min(values):.3f}; max={max(values):.3f}; avg={average:.3f}"


def _markdown_list(items: Sequence[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _display_path(path: Path, *, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _input_id(path: Path, target_language: str) -> str:
    stem = path.name.replace(".", "-").replace("_", "-")
    return f"{stem}-{target_language}"


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


def _unknown_int(value: int | None) -> int | str:
    return value if value is not None else "Unknown"


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _timestamped_diagnostic_dir(root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = root / timestamp
    suffix = 1
    while candidate.exists():
        candidate = root / f"{timestamp}-{suffix}"
        suffix += 1
    return candidate


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _decode_response(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
