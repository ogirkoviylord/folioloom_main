from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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
    select_glossary_subsets_for_units,
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
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_CALLS = 5
DEFAULT_MAX_TOKENS_TOTAL = 50_000
DEFAULT_MAX_COMPLETION_TOKENS = 1_800
DEFAULT_PROMPT_TOKEN_RESERVATION_MULTIPLIER = 2.0
DEFAULT_MAX_FRAGMENT_CHARS = 2_400
DEFAULT_DIAGNOSTIC_ROOT = Path(
    "outputs/issue-477-bounded-glossary-runtime-provider-smoke"
)
APPROVED_INPUT_TARGETS = (
    (Path("test_samples/russian_profile_regression.en-ru.txt"), "ru"),
    (Path("test_samples/ukrainian_profile_regression.en-uk.txt"), "uk"),
    (Path("test_samples/sample_book.en.txt"), "ru"),
    (Path("private_fixtures/pg78824-images-3.epub"), "ru"),
    (Path("private_fixtures/pg78824-images-3.epub"), "uk"),
)


class ChatProvider(Protocol):
    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ) -> "ChatCallResult":
        pass


@dataclass(frozen=True)
class SmokeConfig:
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
        package = package_result
        system_prompt, user_prompt, request_text = build_runtime_prompt(package)
        estimated_prompt_tokens = estimate_tokens(system_prompt + user_prompt)
        reservation = reserve_tokens(
            estimated_prompt_tokens=estimated_prompt_tokens,
            max_completion_tokens=config.max_completion_tokens,
            prompt_token_multiplier=config.prompt_token_reservation_multiplier,
        )
        if calls_made >= config.max_calls:
            call_summaries.append(
                _skipped_call_summary(package, "skipped_max_calls")
            )
            continue
        if (
            reserved_tokens + reservation > config.max_tokens_total
            or (
                observed_tokens is not None
                and observed_tokens + reservation > config.max_tokens_total
            )
        ):
            call_summaries.append(
                _skipped_call_summary(
                    package,
                    "skipped_token_budget",
                    estimated_prompt_tokens=estimated_prompt_tokens,
                    reservation=reservation,
                    reserved_tokens=reserved_tokens,
                    observed_tokens_before_call=_unknown_int(observed_tokens),
                )
            )
            continue

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
        summary = _call_summary(
            package=package,
            call_index=call_index,
            estimated_prompt_tokens=estimated_prompt_tokens,
            reservation=reservation,
            result=result,
            validation=validation,
            observed_over_cap=observed_over_cap,
        )
        call_summaries.append(summary)
        _write_json(
            diagnostic_dir / f"call-{call_index:02d}-{package.input_id}.json",
            _call_diagnostic(
                package=package,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                request_text=request_text,
                result=result,
                validation_summary=summary["validation"],
                raw_text_capture=config.raw_text_capture,
            ),
        )
        if observed_over_cap:
            break

    report = {
        "schema_version": SMOKE_SCHEMA_VERSION,
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
        "unknown": _unknown_items(call_summaries),
        "tbd": [
            "runtime glossary rollout remains TBD",
            "glossary-aware cache reuse remains TBD",
            "release-version diagnostics retention/deletion/consent remains TBD",
            "semantic truth such as gender/name identity remains evidence-driven",
            "RU/UK morphology strategy remains TBD",
        ],
        "recommendation": _recommendation(call_summaries),
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


def build_runtime_package(
    input_path: Path,
    target_language: str,
    *,
    config: SmokeConfig,
    repo_root: Path,
) -> RuntimeSmokePackage:
    path = _approved_input_path(input_path, target_language, repo_root=repo_root)
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
            "issue": "477",
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
    selected_rule_ids = tuple(rule.rule_id for rule in profile.rules)
    policy = build_translation_policy(
        text=_policy_sample_text(plan),
        source_language="en",
        target_language=target_language,
    )
    snapshot = build_translation_contract_snapshot(
        policy,
        glossary_snapshot=reduction.retained_snapshot,
        profile_detection=profile,
        selected_rule_ids=selected_rule_ids,
        selection_policy_version=GLOSSARY_SELECTION_POLICY_VERSION,
        quality_route="runtime_provider_smoke",
    )
    selections = select_glossary_subsets_for_units(
        plan.units,
        reduction.retained_snapshot,
        budget=GlossarySelectionBudget(
            max_prompt_tokens=360,
            max_entries=12,
            max_diagnostic_entries=2,
        ),
        profile_rule_ids=selected_rule_ids,
    )
    reducer_metadata = _reducer_metadata(reduction)
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
            continue
        prompt_context = format_glossary_prompt_context(
            reduction.retained_snapshot.entries,
            selected_entry_ids=decision.selected_entry_ids,
            config=GlossaryPromptContextConfig(
                max_entries=12,
                max_prompt_tokens=1_200,
                max_characters=6_000,
            ),
        )
        if not prompt_context.included_entries:
            continue
        unit = _unit_by_sequence(plan.units, selection.work_unit_sequence)
        protected = protect_text(unit.source_text)
        return RuntimeSmokePackage(
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
            prompt_context_text=prompt_context.text,
            prompt_context_metadata=glossary_prompt_context_metadata_payload(
                prompt_context
            ),
            selection_metadata=selection_metadata,
            glossary_entry_count=len(reduction.retained_snapshot.entries),
            glossary_evidence_count=len(reduction.retained_snapshot.evidence),
            reducer_metadata=reducer_metadata,
        )
    raise ValueError("no_ready_glossary_injected_runtime_unit")


def render_metadata_report(report: Mapping[str, Any]) -> str:
    rows = "\n".join(_call_report_row(call) for call in report["calls"])
    if not rows:
        rows = (
            "| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown "
            "| Unknown |\n"
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
        "| Input | Target | Unit | Status | Finish reason | Usage tokens "
        "| Validation issue codes |\n"
        "| --- | --- | ---: | --- | --- | ---: | --- |\n"
        f"{rows}\n\n"
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
    parser.add_argument("--diagnostic-root", default=str(DEFAULT_DIAGNOSTIC_ROOT))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--base-url",
        default=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
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
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--metadata-report", default="")
    args = parser.parse_args(argv)
    config = SmokeConfig(
        diagnostic_root=Path(args.diagnostic_root),
        provider_model=args.model,
        provider_base_url=args.base_url,
        max_calls=args.max_calls,
        max_tokens_total=args.max_tokens_total,
        max_completion_tokens=args.max_completion_tokens,
        raw_text_capture=True,
        fake=args.fake,
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
    metadata_report_path = (
        Path(args.metadata_report) if args.metadata_report else None
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
    if config.provider_model != DEFAULT_MODEL:
        raise ValueError("provider_model does not match approved model.")
    if config.provider_base_url.rstrip("/") != DEFAULT_BASE_URL:
        raise ValueError("provider_base_url does not match approved provider boundary.")
    if not config.fake and config.diagnostic_root != DEFAULT_DIAGNOSTIC_ROOT:
        raise ValueError("diagnostic_root does not match approved boundary.")
    if config.max_calls > DEFAULT_MAX_CALLS:
        raise ValueError("max_calls exceeds approved cap.")
    if config.max_tokens_total > DEFAULT_MAX_TOKENS_TOTAL:
        raise ValueError("max_tokens_total exceeds approved cap.")
    if not config.raw_text_capture:
        raise ValueError("raw_text_capture must match approved yes boundary.")
    approved = set(APPROVED_INPUT_TARGETS)
    if any(item not in approved for item in config.input_targets):
        raise ValueError("input_targets must be a subset of approved inputs/targets.")


def _approval_payload(config: SmokeConfig) -> dict[str, Any]:
    return {
        "issue_id": "477",
        "input_targets": [f"{path}::{target}" for path, target in config.input_targets],
        "selection": "first READY glossary-injected runtime test-path unit",
        "max_calls": config.max_calls,
        "max_tokens_total": config.max_tokens_total,
        "provider_model": config.provider_model,
        "diagnostic_storage": str(config.diagnostic_root),
        "raw_text_capture": (
            "yes; only bounded fixture/book excerpts, prompts and provider "
            "responses inside the owner-only untracked diagnostics directory"
        ),
    }


def _approved_input_path(
    input_path: Path,
    target_language: str,
    *,
    repo_root: Path,
) -> Path:
    if (input_path, target_language) not in APPROVED_INPUT_TARGETS:
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


def _reducer_metadata(reduction: Any) -> dict[str, Any]:
    payload = glossary_candidate_reduction_payload(reduction)
    return {
        "policy_version": payload["policy_version"],
        "reducer_signature": payload["reducer_signature"],
        "source_glossary_signature": payload["source_glossary_signature"],
        "reduced_glossary_signature": payload["reduced_glossary_signature"],
        "profile_signature": payload["profile_signature"],
        "pressure_signature": payload["pressure_signature"],
        "retained_count": len(reduction.retained_entry_ids),
        "diagnostic_count": len(reduction.diagnostic_entry_ids),
        "dropped_count": len(reduction.dropped_entry_ids),
    }


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
    call_index: int,
    estimated_prompt_tokens: int,
    reservation: int,
    result: ChatCallResult,
    validation: Mapping[str, Any],
    observed_over_cap: bool,
) -> dict[str, Any]:
    return {
        "call_index": call_index,
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
        "error_type": result.error_type,
        "error_message": result.error_message,
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
    **extra: Any,
) -> dict[str, Any]:
    return {
        "input_id": package.input_id,
        "input_path": str(package.input_path),
        "target_language": package.target_language,
        "document_format": package.document_format,
        "unit_sequence": package.unit_sequence,
        "status": status,
        **extra,
    }


def _call_diagnostic(
    *,
    package: RuntimeSmokePackage,
    system_prompt: str,
    user_prompt: str,
    request_text: str,
    result: ChatCallResult,
    validation_summary: Mapping[str, Any],
    raw_text_capture: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SMOKE_SCHEMA_VERSION,
        "diagnostic_scope": "owner_only_glossary_runtime_provider_smoke",
        "input_id": package.input_id,
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
    if any(call.get("status") == "validated" for call in calls):
        items.append("at least one runtime smoke provider response passed validation")
    if not config.fake:
        items.append(
            "live mode used the approved DeepSeek-compatible provider boundary"
        )
    return items


def _unknown_items(calls: Sequence[Mapping[str, Any]]) -> list[str]:
    unknown: list[str] = []
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


def _recommendation(calls: Sequence[Mapping[str, Any]]) -> str:
    if any(call.get("observed_over_cap") is True for call in calls):
        return "stop: observed provider usage exceeded the approved token cap."
    if any(call.get("status") == "failed" for call in calls):
        return (
            "iterate_runtime_prompt_before_rollout: at least one response "
            "failed validation."
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
    return (
        f"| {call.get('input_id', 'Unknown')} "
        f"| {call.get('target_language', 'Unknown')} "
        f"| {call.get('unit_sequence', 'Unknown')} "
        f"| {call.get('status', 'Unknown')} "
        f"| {call.get('finish_reason', 'Unknown')} "
        f"| {usage.get('total_tokens', 'Unknown')} "
        f"| {', '.join(str(code) for code in issue_codes)} |"
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
