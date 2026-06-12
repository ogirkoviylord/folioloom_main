from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from translator_service.book_profile import detect_book_profile
from translator_service.format_adapters.epub import plan_epub_translation
from translator_service.format_adapters.txt import plan_txt_translation
from translator_service.glossary_candidate_reducer import (
    GlossaryCandidateReductionResult,
    glossary_candidate_reduction_payload,
    reduce_glossary_candidates,
)
from translator_service.glossary_editor_chunk_outputs import (
    CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION,
    ChunkedGlossaryEditorFindingCode,
    chunked_glossary_editor_merge_payload,
    merge_chunked_glossary_editor_outputs,
    validate_chunked_glossary_editor_output,
)
from translator_service.glossary_editor_packets import (
    GlossaryEditorPacket,
    GlossaryEditorPacketStatus,
    build_glossary_editor_packets,
    glossary_editor_packet_payload,
)
from translator_service.glossary_role_validators import GlossaryRoleId
from translator_service.glossary_scanner import scan_glossary_candidates

SPIKE_SCHEMA_VERSION = "chunked-deepseek-pro-glossary-editor-spike-v1"
ROLE_VERSION = "chunked-deepseek-pro-glossary-editor-spike-role-v1"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_CALLS = 3
DEFAULT_MAX_TOKENS_TOTAL = 30_000
DEFAULT_MAX_COMPLETION_TOKENS = 2_200
DEFAULT_PROMPT_TOKEN_RESERVATION_MULTIPLIER = 2.0
DEFAULT_MAX_FIXTURE_EXCERPT_CHARS = 2_400
DEFAULT_DIAGNOSTIC_ROOT = Path("outputs/issue-416-chunked-deepseek-pro-spike")
ISSUE_431_DIAGNOSTIC_ROOT = Path(
    "outputs/issue-431-bounded-chunked-glossary-editor-retry"
)
ISSUE_449_DIAGNOSTIC_ROOT = Path(
    "outputs/issue-449-reduced-glossary-editor-retry"
)
APPROVED_DIAGNOSTIC_ROOTS = (
    DEFAULT_DIAGNOSTIC_ROOT,
    ISSUE_431_DIAGNOSTIC_ROOT,
    ISSUE_449_DIAGNOSTIC_ROOT,
)
APPROVED_FIXTURES = (
    Path("test_samples/russian_profile_regression.en-ru.txt"),
    Path("test_samples/ukrainian_profile_regression.en-uk.txt"),
    Path("test_samples/sample_book.en.txt"),
)
ISSUE_449_APPROVED_INPUTS = (
    *APPROVED_FIXTURES,
    Path("/Users/yuriimedvediev/Downloads/pg78824-images-3.epub"),
)
ISSUE_449_MAX_CALLS = 4
ISSUE_449_MAX_TOKENS_TOTAL = 40_000
ISSUE_449_MAX_PACKETS_TOTAL = 4
ISSUE_449_PACKET_SELECTION_RULE = "first_ready_reduced_packet_per_approved_input"


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
class SpikeConfig:
    fixture_paths: tuple[Path, ...]
    diagnostic_root: Path
    provider_model: str = DEFAULT_MODEL
    provider_base_url: str = DEFAULT_BASE_URL
    max_calls: int = DEFAULT_MAX_CALLS
    max_tokens_total: int = DEFAULT_MAX_TOKENS_TOTAL
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS
    max_fixture_excerpt_chars: int = DEFAULT_MAX_FIXTURE_EXCERPT_CHARS
    prompt_token_reservation_multiplier: float = (
        DEFAULT_PROMPT_TOKEN_RESERVATION_MULTIPLIER
    )
    packet_selection_rule: str = "first_ready_packet_per_fixture"
    max_packets_total: int = 3
    raw_text_capture: bool = True
    fake: bool = False
    reduced_packets: bool = False


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
class ChunkedFixturePackage:
    fixture_path: Path
    fixture_id: str
    source_language: str
    target_language: str
    bounded_excerpt: str
    packet: GlossaryEditorPacket
    packet_count: int
    selected_packet_index: int
    glossary_entry_count: int
    glossary_evidence_count: int
    fragment_count: int
    character_count: int
    reduced_packets: bool
    reduction: GlossaryCandidateReductionResult | None


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
            response_text = _decode_response(response_bytes)
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
        except URLError as error:
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
        except TimeoutError as error:
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
                error_message="provider_response_timeout",
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


class FakeChunkedProvider:
    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ) -> ChatCallResult:
        prompt = json.loads(user_prompt)
        packet = prompt["packet"]
        entry = packet["entries"][0]
        evidence_refs = list(entry["evidence_refs"])
        content = json.dumps(
            _fake_chunk_output(prompt, entry, evidence_refs),
            ensure_ascii=False,
            sort_keys=True,
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
                "response_format": {"type": "json_object"},
            },
            response_payload={"choices": [{"message": {"content": content}}]},
            response_text=json.dumps({"choices": [{"message": {"content": content}}]}),
        )


def run_spike(
    config: SpikeConfig,
    *,
    provider: ChatProvider,
    repo_root: Path | None = None,
    metadata_report_path: Path | None = None,
) -> dict[str, Any]:
    _validate_config(config)
    repo_root = (repo_root or Path.cwd()).resolve()
    diagnostic_dir = _timestamped_diagnostic_dir(config.diagnostic_root)
    diagnostic_dir.mkdir(parents=True, exist_ok=False)
    packages = select_fixture_packets(config, repo_root=repo_root)

    call_summaries: list[dict[str, Any]] = []
    validation_results = []
    calls_made = 0
    reserved_tokens = 0
    observed_tokens: int | None = 0

    for package in packages:
        if calls_made >= config.max_calls:
            call_summaries.append(_skipped_call_summary(package, "skipped_max_calls"))
            continue
        system_prompt, user_prompt = build_chunk_prompt(package)
        estimated_prompt_tokens = estimate_tokens(system_prompt + user_prompt)
        reservation = reserve_tokens(
            estimated_prompt_tokens=estimated_prompt_tokens,
            max_completion_tokens=config.max_completion_tokens,
            prompt_token_multiplier=config.prompt_token_reservation_multiplier,
        )
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
        if usage_tokens is None:
            observed_tokens = None
        elif observed_tokens is not None:
            observed_tokens += usage_tokens
        validation = validate_chunked_glossary_editor_output(
            result.content,
            packet=package.packet,
        )
        validation_results.append(validation)
        summary = _call_summary(
            package=package,
            call_index=call_index,
            estimated_prompt_tokens=estimated_prompt_tokens,
            reservation=reservation,
            result=result,
            validation=validation,
        )
        call_summaries.append(summary)
        _write_json(
            diagnostic_dir / f"call-{call_index:02d}-{package.fixture_id}.json",
            _call_diagnostic(
                package=package,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                result=result,
                validation_summary=summary["validation"],
                raw_text_capture=config.raw_text_capture,
            ),
        )

    merge = merge_chunked_glossary_editor_outputs(tuple(validation_results))
    merge_payload = chunked_glossary_editor_merge_payload(merge)
    merge_summary = _merge_summary(merge_payload)
    report = {
        "schema_version": SPIKE_SCHEMA_VERSION,
        "status": _spike_status(call_summaries, merge_summary),
        "created_at": datetime.now(UTC).isoformat(),
        "approval": _approval_payload(config),
        "diagnostic_dir": str(diagnostic_dir),
        "calls_made": calls_made,
        "reserved_tokens": reserved_tokens,
        "observed_tokens": _unknown_int(observed_tokens),
        "fixtures": [
            _fixture_summary(package, repo_root=repo_root)
            for package in packages
        ],
        "calls": call_summaries,
        "merge": merge_summary,
        "confirmed": _confirmed_items(call_summaries, merge_summary),
        "unknown": _unknown_items(call_summaries),
        "tbd": [
            "runtime translation integration remains TBD",
            "release-version diagnostics retention/deletion/consent remains TBD",
            (
                "semantic truth such as gender/name identity remains "
                "evidence/review-driven"
            ),
            "RU/UK morphology strategy remains TBD",
        ],
        "recommendation": _recommendation(call_summaries, merge_summary),
    }
    _write_json(diagnostic_dir / "manifest.json", report)
    _write_json(diagnostic_dir / "merge-metadata.json", merge_payload)
    _write_json(
        diagnostic_dir / "selected-packets.json",
        [_packet_diagnostic_summary(package) for package in packages],
    )
    if metadata_report_path is not None:
        metadata_report_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_report_path.write_text(
            render_metadata_report(report),
            encoding="utf-8",
        )
    return report


def select_fixture_packets(
    config: SpikeConfig,
    *,
    repo_root: Path,
) -> tuple[ChunkedFixturePackage, ...]:
    packages: list[ChunkedFixturePackage] = []
    for fixture_path in config.fixture_paths:
        if len(packages) >= config.max_packets_total:
            break
        package = build_fixture_package(
            fixture_path,
            repo_root=repo_root,
            max_fixture_excerpt_chars=config.max_fixture_excerpt_chars,
            config=config,
        )
        packages.append(package)
    return tuple(packages)


def build_fixture_package(
    fixture_path: Path,
    *,
    repo_root: Path,
    max_fixture_excerpt_chars: int,
    config: SpikeConfig,
) -> ChunkedFixturePackage:
    path = _approved_fixture_path(fixture_path, repo_root=repo_root, config=config)
    target_language = _target_language_for_path(path)
    content = path.read_bytes()
    plan = _plan_input_translation(path, content=content)
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
    reduction = None
    if config.reduced_packets:
        reduction = reduce_glossary_candidates(
            glossary,
            profile_detection=profile,
            pressure_context=_pressure_context(
                fixture_path=path,
                plan=plan,
                glossary_entry_count=len(glossary.entries),
                glossary_evidence_count=len(glossary.evidence),
            ),
        )
    packet_result = build_glossary_editor_packets(
        glossary,
        profile,
        candidate_reduction=reduction,
    )
    ready_packets = [
        packet
        for packet in packet_result.packets
        if packet.status is GlossaryEditorPacketStatus.READY
    ]
    if not ready_packets:
        raise ValueError(f"No READY glossary editor packet for fixture: {fixture_path}")
    packet = ready_packets[0]
    return ChunkedFixturePackage(
        fixture_path=path,
        fixture_id=_fixture_id(path),
        source_language="en",
        target_language=target_language,
        bounded_excerpt=_bounded_excerpt(plan.units, max_fixture_excerpt_chars),
        packet=packet,
        packet_count=len(packet_result.packets),
        selected_packet_index=packet.packet_index,
        glossary_entry_count=len(glossary.entries),
        glossary_evidence_count=len(glossary.evidence),
        fragment_count=plan.fragment_count,
        character_count=plan.character_count,
        reduced_packets=config.reduced_packets,
        reduction=reduction,
    )


def build_chunk_prompt(package: ChunkedFixturePackage) -> tuple[str, str]:
    system_prompt = (
        "You are running a bounded FolioLoom DeepSeek Pro chunked glossary "
        "editor spike. Return exactly one JSON object and no markdown fences. "
        "Use only the provided packet_id, packet_signature, entry ids and "
        "evidence ids. Do not include source_canonical, raw_text, source_text, "
        "raw_excerpt, prompt, system_prompt, provider_request or provider_response "
        "keys. Do not claim semantic certainty for gender/name identity; use "
        "unknown, not_applicable, needs_review or low confidence when evidence "
        "is weak."
    )
    packet_payload = _prompt_packet_payload(package.packet)
    user_prompt = json.dumps(
        {
            "task": (
                "Return a JSON object that passes FolioLoom local chunked "
                "glossary editor validation for this one packet."
            ),
            "output_schema_version": CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION,
            "role_id": GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER.value,
            "role_version": ROLE_VERSION,
            "fixture_id": package.fixture_id,
            "packet_selection": "first READY packet for this approved fixture",
            "packet_reduction": (
                "reduced glossary candidate packet"
                if package.reduced_packets
                else "full glossary snapshot packet"
            ),
            "allowed_entry_ids": list(package.packet.entry_ids),
            "allowed_evidence_ids": list(package.packet.evidence_ids),
            "root_shape": _root_shape(package.packet),
            "evidence_contract": _evidence_contract(package.packet),
            "packet": packet_payload,
            "bounded_source_excerpt": package.bounded_excerpt,
            "constraints": [
                "proposed_entries may be empty when evidence is insufficient",
                "do not invent owner_pinned, locked, or hard layer entries",
                (
                    "every root, proposed_entries, rejected_entries and findings "
                    "evidence_refs array must be non-empty when that object exists"
                ),
                (
                    "use only evidence ids from top-level allowed_evidence_ids; "
                    "do not omit evidence_refs for accepted, low-confidence, rejected "
                    "or diagnostic claims"
                ),
                "do not include raw/source text fields in the output object",
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return system_prompt, user_prompt


def render_metadata_report(report: Mapping[str, Any]) -> str:
    call_rows = "\n".join(_call_report_row(call) for call in report["calls"])
    if not call_rows:
        call_rows = "| Unknown | Unknown | Unknown | Unknown | Unknown | Unknown |\n"
    merge = report["merge"]
    finding_rows = "\n".join(
        f"| {item['code']} | {item['severity']} | {item['count']} |"
        for item in merge["finding_counts"]
    )
    if not finding_rows:
        finding_rows = "| none | none | 0 |"
    failure_modes = report.get("unknown") or ["none observed"]
    return (
        "# Chunked DeepSeek Pro Glossary Editor Spike Report\n\n"
        "## Confirmed\n"
        f"{_markdown_list(report['confirmed'])}\n\n"
        "## Unknown\n"
        f"{_markdown_list(report['unknown'] or ['None from this bounded run.'])}\n\n"
        "## TBD\n"
        f"{_markdown_list(report['tbd'])}\n\n"
        "## Approval Boundary\n"
        f"- Fixtures: {', '.join(report['approval']['fixtures'])}\n"
        f"- Packet selection: {report['approval']['packet_selection_rule']}\n"
        f"- Max calls: {report['approval']['max_calls']}\n"
        f"- Max tokens total: {report['approval']['max_tokens_total']}\n"
        f"- Provider/model: {report['approval']['provider_model']}\n"
        f"- Diagnostic storage: {report['approval']['diagnostic_storage']}\n"
        f"- Raw-text capture: {report['approval']['raw_text_capture']}\n\n"
        "## Validation Results\n"
        "| Fixture | Packet index | Status | Finish reason | Validation | "
        "Usage tokens |\n"
        "| --- | ---: | --- | --- | --- | ---: |\n"
        f"{call_rows}\n\n"
        "## Merge And Conflict Findings\n"
        f"- Proposed entries: {merge['proposed_entry_count']}\n"
        f"- Invalid packets: {merge['invalid_packet_count']}\n"
        f"- Conflict rate: {merge['conflict_rate']}\n"
        f"- Has blockers: {merge['has_blockers']}\n\n"
        "| Finding code | Severity | Count |\n"
        "| --- | --- | ---: |\n"
        f"{finding_rows}\n\n"
        "## Token And Latency Shape\n"
        f"- Calls made: {report['calls_made']}\n"
        f"- Reserved tokens: {report['reserved_tokens']}\n"
        f"- Observed tokens: {report['observed_tokens']}\n"
        f"- Latency seconds: {_latency_shape(report['calls'])}\n\n"
        "## Failure Modes\n"
        f"{_markdown_list(failure_modes)}\n\n"
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
    multiplier = max(1.0, prompt_token_multiplier)
    return math.ceil(estimated_prompt_tokens * multiplier) + max_completion_tokens


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
    parser.add_argument("--fixture", action="append", default=[])
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--metadata-report", default="")
    parser.add_argument(
        "--issue-449-reduced",
        action="store_true",
        help="Use the approved #449 reduced-packet retry boundary.",
    )
    args = parser.parse_args(argv)

    fixture_paths = (
        tuple(Path(item) for item in args.fixture)
        if args.fixture
        else (
            ISSUE_449_APPROVED_INPUTS
            if args.issue_449_reduced
            else APPROVED_FIXTURES
        )
    )
    diagnostic_root = (
        ISSUE_449_DIAGNOSTIC_ROOT
        if (
            args.issue_449_reduced
            and args.diagnostic_root == str(DEFAULT_DIAGNOSTIC_ROOT)
        )
        else Path(args.diagnostic_root)
    )
    max_calls = (
        ISSUE_449_MAX_CALLS
        if args.issue_449_reduced and args.max_calls == DEFAULT_MAX_CALLS
        else args.max_calls
    )
    max_tokens_total = (
        ISSUE_449_MAX_TOKENS_TOTAL
        if (
            args.issue_449_reduced
            and args.max_tokens_total == DEFAULT_MAX_TOKENS_TOTAL
        )
        else args.max_tokens_total
    )
    config = SpikeConfig(
        fixture_paths=fixture_paths,
        diagnostic_root=diagnostic_root,
        provider_model=args.model,
        provider_base_url=args.base_url,
        max_calls=max_calls,
        max_tokens_total=max_tokens_total,
        max_completion_tokens=args.max_completion_tokens,
        packet_selection_rule=(
            ISSUE_449_PACKET_SELECTION_RULE
            if args.issue_449_reduced
            else "first_ready_packet_per_fixture"
        ),
        max_packets_total=(
            ISSUE_449_MAX_PACKETS_TOTAL if args.issue_449_reduced else 3
        ),
        raw_text_capture=True,
        fake=args.fake,
        reduced_packets=args.issue_449_reduced,
    )
    if args.fake:
        provider: ChatProvider = FakeChunkedProvider()
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
        Path(args.metadata_report)
        if args.metadata_report
        else None
    )
    report = run_spike(
        config,
        provider=provider,
        metadata_report_path=metadata_report_path,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "diagnostic_dir": report["diagnostic_dir"],
                "calls_made": report["calls_made"],
                "observed_tokens": report["observed_tokens"],
                "recommendation": report["recommendation"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _validate_config(config: SpikeConfig) -> None:
    if config.provider_model != DEFAULT_MODEL:
        raise ValueError("provider_model does not match approved model.")
    if not config.fake and config.diagnostic_root not in APPROVED_DIAGNOSTIC_ROOTS:
        raise ValueError(
            "diagnostic_root does not match approved diagnostics boundary."
        )
    max_calls = ISSUE_449_MAX_CALLS if config.reduced_packets else DEFAULT_MAX_CALLS
    max_tokens_total = (
        ISSUE_449_MAX_TOKENS_TOTAL
        if config.reduced_packets
        else DEFAULT_MAX_TOKENS_TOTAL
    )
    max_packets_total = (
        ISSUE_449_MAX_PACKETS_TOTAL if config.reduced_packets else 3
    )
    if config.max_calls > max_calls:
        raise ValueError("max_calls exceeds approved cap.")
    if config.max_tokens_total > max_tokens_total:
        raise ValueError("max_tokens_total exceeds approved cap.")
    if config.max_packets_total > max_packets_total:
        raise ValueError("max_packets_total exceeds approved cap.")
    if not config.raw_text_capture:
        raise ValueError("approved run expects raw_text_capture=True.")
    expected_packet_selection = (
        ISSUE_449_PACKET_SELECTION_RULE
        if config.reduced_packets
        else "first_ready_packet_per_fixture"
    )
    if config.packet_selection_rule != expected_packet_selection:
        raise ValueError("packet_selection_rule does not match approval.")
    if config.reduced_packets and not config.fake:
        if config.diagnostic_root != ISSUE_449_DIAGNOSTIC_ROOT:
            raise ValueError(
                "diagnostic_root does not match issue #449 diagnostics boundary."
            )
    if (
        not config.reduced_packets
        and not config.fake
        and config.diagnostic_root == ISSUE_449_DIAGNOSTIC_ROOT
    ):
        raise ValueError(
            "issue #449 diagnostics boundary requires reduced_packets=True."
        )


def _approval_payload(config: SpikeConfig) -> dict[str, Any]:
    return {
        "fixtures": [str(path) for path in config.fixture_paths],
        "packet_selection_rule": config.packet_selection_rule,
        "max_packets_total": config.max_packets_total,
        "max_calls": config.max_calls,
        "max_tokens_total": config.max_tokens_total,
        "provider_model": config.provider_model,
        "diagnostic_storage": str(config.diagnostic_root),
        "reduced_packets": config.reduced_packets,
        "raw_text_capture": (
            "yes; bounded fixture excerpts, prompts and provider responses only "
            "inside the owner-only untracked diagnostics directory"
        ),
    }


def _root_shape(packet: GlossaryEditorPacket) -> Mapping[str, Any]:
    return {
        "output_schema_version": CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION,
        "role_id": GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER.value,
        "role_version": ROLE_VERSION,
        "status": (
            "accepted | accepted_low_confidence | diagnostic_only | "
            "needs_review | rejected | failed"
        ),
        "packet_id": packet.packet_id,
        "packet_signature": packet.packet_signature,
        "glossary_signature": packet.glossary_signature,
        "profile_signature": packet.profile_signature,
        "confidence": "number 0..1",
        "evidence_refs": "non-empty array of allowed evidence ids used by output",
        "proposed_entries": [
            {
                "entry_id": "one allowed entry id from this packet",
                "category": "name | term | entity | style_note | morphology_note",
                "layer": "soft | diagnostic",
                "status": "validator_accepted | uncertain | rejected | unknown",
                "aliases": [],
                "target_canonical": None,
                "target_variants": [],
                "forbidden_variants": [],
                "strategy": (
                    "transliterate | transcribe | translate_meaning | contextual | "
                    "do_not_translate | unknown"
                ),
                "grammatical_gender": "unknown | not_applicable",
                "confidence": "number 0..1",
                "evidence_refs": "non-empty array of allowed evidence ids",
                "profile_rule_ids": [],
            }
        ],
        "rejected_entries": [
            {
                "entry_id": "one allowed entry id from this packet",
                "reason": "short reason code",
                "confidence": "number 0..1",
                "evidence_refs": "non-empty array of allowed evidence ids",
            }
        ],
        "findings": [
            {
                "finding_id": "stable short id",
                "kind": "short finding kind",
                "severity": "info | warning | blocker",
                "entry_ids": "array of allowed entry ids",
                "evidence_refs": "non-empty array of allowed evidence ids",
                "message": "short metadata-only message",
            }
        ],
    }


def _evidence_contract(packet: GlossaryEditorPacket) -> Mapping[str, Any]:
    return {
        "allowed_evidence_ids_source": "allowed_evidence_ids",
        "entry_evidence_refs_source": "packet.entries[].evidence_refs",
        "packet_evidence_count": len(packet.evidence_ids),
        "required_paths": [
            "evidence_refs",
            "proposed_entries[].evidence_refs",
            "rejected_entries[].evidence_refs",
            "findings[].evidence_refs",
        ],
        "minimum_refs_per_required_path": 1,
        "missing_refs_validation_code": "missing_evidence",
        "missing_refs_merge_finding_code": "missing_evidence_refs",
        "raw_text_policy": (
            "cite evidence ids only; do not copy source text, prompt text or "
            "provider bodies into output"
        ),
    }


def _fake_chunk_output(
    prompt: Mapping[str, Any],
    entry: Mapping[str, Any],
    evidence_refs: Sequence[str],
) -> dict[str, Any]:
    return {
        "output_schema_version": CHUNKED_GLOSSARY_EDITOR_OUTPUT_SCHEMA_VERSION,
        "role_id": GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER.value,
        "role_version": ROLE_VERSION,
        "status": "accepted_low_confidence",
        "packet_id": prompt["packet"]["packet_id"],
        "packet_signature": prompt["packet"]["packet_signature"],
        "glossary_signature": prompt["packet"]["glossary_signature"],
        "profile_signature": prompt["packet"]["profile_signature"],
        "confidence": 0.61,
        "evidence_refs": list(evidence_refs),
        "proposed_entries": [
            {
                "entry_id": entry["entry_id"],
                "category": entry["category"],
                "layer": "diagnostic",
                "status": "uncertain",
                "aliases": [],
                "target_canonical": None,
                "target_variants": [],
                "forbidden_variants": [],
                "strategy": "unknown",
                "grammatical_gender": "unknown",
                "confidence": 0.61,
                "evidence_refs": list(evidence_refs),
                "profile_rule_ids": list(entry.get("profile_rule_ids", [])),
            }
        ],
        "rejected_entries": [],
        "findings": [],
    }


def _approved_fixture_path(
    fixture_path: Path,
    *,
    repo_root: Path,
    config: SpikeConfig,
) -> Path:
    approved_inputs = (
        ISSUE_449_APPROVED_INPUTS
        if config.reduced_packets
        else APPROVED_FIXTURES
    )
    approved = {(repo_root / item).resolve() for item in approved_inputs}
    resolved = (repo_root / fixture_path).resolve()
    if resolved not in approved:
        issue = "#449" if config.reduced_packets else "#416"
        raise ValueError(f"Fixture is not approved for issue {issue}: {fixture_path}")
    if not resolved.is_file():
        raise FileNotFoundError(f"Approved fixture is missing: {fixture_path}")
    return resolved


def _plan_input_translation(path: Path, *, content: bytes) -> Any:
    if path.suffix.lower() == ".epub":
        return plan_epub_translation(content=content, max_fragment_chars=2_400)
    return plan_txt_translation(content=content, max_fragment_chars=2_400)


def _pressure_context(
    *,
    fixture_path: Path,
    plan: Any,
    glossary_entry_count: int,
    glossary_evidence_count: int,
) -> Mapping[str, Any]:
    return {
        "fixture_id": _fixture_id(fixture_path),
        "document_format": getattr(
            plan.document_format,
            "value",
            str(plan.document_format),
        ),
        "fragment_count": plan.fragment_count,
        "character_count": plan.character_count,
        "glossary_entry_count": glossary_entry_count,
        "glossary_evidence_count": glossary_evidence_count,
        "selection": ISSUE_449_PACKET_SELECTION_RULE,
    }


def _target_language_for_path(path: Path) -> str:
    if ".en-uk" in path.name:
        return "uk"
    return "ru"


def _fixture_id(path: Path) -> str:
    return path.name.replace(".", "-").replace("_", "-")


def _bounded_excerpt(units: Sequence[Any], max_chars: int) -> str:
    parts: list[str] = []
    remaining = max_chars
    for unit in units:
        text = unit.source_text.strip()
        if not text:
            continue
        if len(text) > remaining:
            parts.append(text[:remaining].rstrip())
            break
        parts.append(text)
        remaining -= len(text) + 2
        if remaining <= 0:
            break
    return "\n\n".join(parts)


def _timestamped_diagnostic_dir(root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = root / timestamp
    suffix = 1
    while candidate.exists():
        candidate = root / f"{timestamp}-{suffix}"
        suffix += 1
    return candidate


def _call_summary(
    *,
    package: ChunkedFixturePackage,
    call_index: int,
    estimated_prompt_tokens: int,
    reservation: int,
    result: ChatCallResult,
    validation: Any,
) -> dict[str, Any]:
    return {
        "call_index": call_index,
        "fixture_id": package.fixture_id,
        "fixture_path": str(package.fixture_path),
        "packet_id": package.packet.packet_id,
        "packet_index": package.selected_packet_index,
        "status": "validated" if result.ok and validation.valid else "failed",
        "http_status": result.http_status,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "finish_reason": result.finish_reason,
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "reserved_tokens": reservation,
        "usage": dict(result.usage),
        "validation": {
            "valid": validation.valid,
            "issue_count": len(validation.issues),
            "issues": [_validation_issue_payload(issue) for issue in validation.issues],
        },
        "error_type": result.error_type,
        "error_message": result.error_message,
    }


def _skipped_call_summary(
    package: ChunkedFixturePackage,
    status: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "fixture_id": package.fixture_id,
        "fixture_path": str(package.fixture_path),
        "packet_id": package.packet.packet_id,
        "packet_index": package.selected_packet_index,
        "status": status,
        **extra,
    }


def _call_diagnostic(
    *,
    package: ChunkedFixturePackage,
    system_prompt: str,
    user_prompt: str,
    result: ChatCallResult,
    validation_summary: Mapping[str, Any],
    raw_text_capture: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SPIKE_SCHEMA_VERSION,
        "diagnostic_scope": "owner_only_chunked_deepseek_pro_glossary_editor_spike",
        "fixture_id": package.fixture_id,
        "fixture_path": str(package.fixture_path),
        "packet_id": package.packet.packet_id,
        "packet_signature": package.packet.packet_signature,
        "raw_text_capture": raw_text_capture,
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
        "request_payload": result.request_payload,
        "response_payload": result.response_payload,
        "response_text": result.response_text,
        "model_content": result.content,
        "usage": dict(result.usage),
        "http_status": result.http_status,
        "finish_reason": result.finish_reason,
        "validation": validation_summary,
    }
    if raw_text_capture:
        payload["system_prompt"] = system_prompt
        payload["user_prompt"] = user_prompt
        payload["bounded_source_excerpt"] = package.bounded_excerpt
    return payload


def _fixture_summary(
    package: ChunkedFixturePackage,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    return {
        "fixture_id": package.fixture_id,
        "fixture_path": _display_path(package.fixture_path, repo_root=repo_root),
        "target_language": package.target_language,
        "fragment_count": package.fragment_count,
        "character_count": package.character_count,
        "glossary_entry_count": package.glossary_entry_count,
        "glossary_evidence_count": package.glossary_evidence_count,
        "packet_count": package.packet_count,
        "selected_packet_index": package.selected_packet_index,
        "selected_packet_entry_count": len(package.packet.entries),
        "selected_packet_evidence_count": len(package.packet.evidence_refs),
        "selected_packet_status": package.packet.status.value,
        "selected_packet_estimated_prompt_tokens": (
            package.packet.estimated_prompt_tokens
        ),
        "selected_packet_reserved_prompt_tokens": package.packet.reserved_prompt_tokens,
        "reduced_packets": package.reduced_packets,
        "reducer": _reducer_summary(package.reduction),
    }


def _packet_diagnostic_summary(package: ChunkedFixturePackage) -> dict[str, Any]:
    return {
        "fixture_id": package.fixture_id,
        "packet": glossary_editor_packet_payload(package.packet),
        "reduction": _reducer_summary(package.reduction),
    }


def _display_path(path: Path, *, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _prompt_packet_payload(packet: GlossaryEditorPacket) -> dict[str, Any]:
    payload = {
        "packet_id": packet.packet_id,
        "packet_signature": packet.packet_signature,
        "packet_index": packet.packet_index,
        "source_language": packet.source_language,
        "target_language": packet.target_language,
        "glossary_signature": packet.glossary_signature,
        "profile_signature": packet.profile_signature,
        "entries": [
            {
                "entry_id": entry.entry_id,
                "category": entry.category,
                "layer": entry.layer,
                "status": entry.status,
                "strategy": entry.strategy,
                "grammatical_gender": entry.grammatical_gender,
                "confidence": entry.confidence,
                "evidence_refs": list(entry.evidence_refs),
                "profile_rule_ids": list(entry.profile_rule_ids),
                "needs_review": entry.needs_review,
                "reducer_decision_status": entry.reducer_decision_status,
                "reducer_decision_reasons": list(entry.reducer_decision_reasons),
            }
            for entry in packet.entries
        ],
        "evidence_ids": list(packet.evidence_ids),
    }
    if packet.reducer_context is not None:
        payload["reducer_context"] = {
            "policy_version": packet.reducer_context.policy_version,
            "reducer_signature": packet.reducer_context.reducer_signature,
            "source_glossary_signature": (
                packet.reducer_context.source_glossary_signature
            ),
            "reduced_glossary_signature": (
                packet.reducer_context.reduced_glossary_signature
            ),
            "profile_signature": packet.reducer_context.profile_signature,
            "pressure_signature": packet.reducer_context.pressure_signature,
            "retained_count": packet.reducer_context.retained_count,
            "diagnostic_count": packet.reducer_context.diagnostic_count,
            "dropped_count": packet.reducer_context.dropped_count,
        }
    return payload


def _reducer_summary(
    reduction: GlossaryCandidateReductionResult | None,
) -> dict[str, Any] | None:
    if reduction is None:
        return None
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
        "caps": payload["caps"],
    }


def _merge_summary(merge_payload: Mapping[str, Any]) -> dict[str, Any]:
    finding_counts = Counter(
        (finding["code"], finding["severity"])
        for finding in merge_payload["findings"]
    )
    conflict_codes = {
        ChunkedGlossaryEditorFindingCode.DUPLICATE_ENTRY_OUTPUT.value,
        ChunkedGlossaryEditorFindingCode.CONFLICTING_ALIASES.value,
        ChunkedGlossaryEditorFindingCode.CONFLICTING_TARGET_VARIANTS.value,
    }
    conflict_count = sum(
        1 for finding in merge_payload["findings"] if finding["code"] in conflict_codes
    )
    proposed_count = len(merge_payload["proposed_entries"])
    denominator = max(1, proposed_count)
    return {
        "merge_signature": merge_payload["merge_signature"],
        "proposed_entry_count": proposed_count,
        "finding_count": len(merge_payload["findings"]),
        "finding_counts": [
            {"code": code, "severity": severity, "count": count}
            for (code, severity), count in sorted(finding_counts.items())
        ],
        "invalid_packet_count": len(merge_payload["invalid_packet_ids"]),
        "invalid_packet_ids": list(merge_payload["invalid_packet_ids"]),
        "has_blockers": merge_payload["has_blockers"],
        "conflict_rate": round(conflict_count / denominator, 4),
    }


def _confirmed_items(
    call_summaries: Sequence[Mapping[str, Any]],
    merge_payload: Mapping[str, Any],
) -> list[str]:
    items = [
        "approved fixtures were packetized with the first READY packet selection rule",
        (
            "raw prompts/provider outputs were confined to the approved "
            "diagnostics directory"
        ),
        "runtime translation/cache/storage/admin behavior was not changed",
    ]
    if any(call.get("status") == "validated" for call in call_summaries):
        items.append("at least one chunked glossary-editor output passed validation")
    if merge_payload["proposed_entry_count"] or merge_payload["finding_count"]:
        items.append("merge/adjudication contract was run on validated chunk outputs")
    return items


def _unknown_items(call_summaries: Sequence[Mapping[str, Any]]) -> list[str]:
    unknown: list[str] = []
    if not call_summaries:
        unknown.append("provider behavior is Unknown because no calls were made")
    if any(
        "usage" in call and _usage_total_tokens(call.get("usage")) is None
        for call in call_summaries
    ):
        unknown.append("provider-reported token usage is Unknown for one or more calls")
    if any(call.get("status") != "validated" for call in call_summaries):
        unknown.append("one or more chunk outputs did not validate")
    return unknown


def _recommendation(
    call_summaries: Sequence[Mapping[str, Any]],
    merge_payload: Mapping[str, Any],
) -> str:
    if any(call.get("status") != "validated" for call in call_summaries):
        return (
            "pivot_or_iterate_prompt_before_runtime_integration: at least one "
            "provider output failed local chunk validation."
        )
    if merge_payload["has_blockers"]:
        return (
            "stop_before_runtime_integration: merge/adjudication produced blocker "
            "findings."
        )
    return (
        "proceed_to_design_review_only: bounded chunk outputs validated, but runtime "
        "integration, retention and release privacy remain TBD."
    )


def _spike_status(
    call_summaries: Sequence[Mapping[str, Any]],
    merge_payload: Mapping[str, Any],
) -> str:
    if any(call.get("status") == "failed" for call in call_summaries):
        return "completed_with_failures"
    if any(
        str(call.get("status", "")).startswith("skipped")
        for call in call_summaries
    ):
        return "completed_with_skips"
    if merge_payload["has_blockers"]:
        return "completed_with_merge_blockers"
    return "completed"


def _call_report_row(call: Mapping[str, Any]) -> str:
    validation = call.get("validation") or {}
    usage = call.get("usage") or {}
    return (
        f"| {call.get('fixture_id', 'Unknown')} "
        f"| {call.get('packet_index', 'Unknown')} "
        f"| {call.get('status', 'Unknown')} "
        f"| {call.get('finish_reason', 'Unknown')} "
        f"| valid={validation.get('valid', 'Unknown')}; "
        f"issues={validation.get('issue_count', 'Unknown')} "
        f"| {usage.get('total_tokens', 'Unknown')} |"
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


def _validation_issue_payload(issue: Any) -> dict[str, str]:
    return {
        "code": str(issue.code),
        "path": issue.path,
        "message": issue.message,
    }


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
