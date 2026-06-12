from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from translator_service.book_profile import (
    detect_book_profile,
    validate_book_profile_detection,
)
from translator_service.format_adapters.txt import plan_txt_translation
from translator_service.glossary_contracts import (
    glossary_snapshot_signature,
    validate_glossary_snapshot,
)
from translator_service.glossary_role_validators import (
    GLOSSARY_ROLE_OUTPUT_SCHEMA_VERSION,
    GlossaryRoleId,
    validate_glossary_role_output,
    validate_glossary_role_output_set,
)
from translator_service.glossary_scanner import scan_glossary_candidates

SPIKE_SCHEMA_VERSION = "deepseek-pro-glossary-profile-spike-v1"
ROLE_VERSION = "deepseek-pro-spike-role-v1"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MAX_CALLS = 6
DEFAULT_MAX_TOKENS_TOTAL = 60_000
DEFAULT_MAX_COMPLETION_TOKENS = 2_500
DEFAULT_MAX_FIXTURE_EXCERPT_CHARS = 2_400
DEFAULT_MAX_CONTEXT_ENTRIES = 12
DEFAULT_MAX_CONTEXT_EVIDENCE = 18
DEFAULT_PROMPT_TOKEN_RESERVATION_MULTIPLIER = 2.0
APPROVED_FIXTURES = (
    Path("test_samples/russian_profile_regression.en-ru.txt"),
    Path("test_samples/ukrainian_profile_regression.en-uk.txt"),
    Path("test_samples/sample_book.en.txt"),
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
class SpikeConfig:
    fixture_paths: tuple[Path, ...]
    diagnostic_root: Path
    provider_model: str = DEFAULT_MODEL
    provider_base_url: str = DEFAULT_BASE_URL
    max_calls: int = DEFAULT_MAX_CALLS
    max_tokens_total: int = DEFAULT_MAX_TOKENS_TOTAL
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS
    max_fixture_excerpt_chars: int = DEFAULT_MAX_FIXTURE_EXCERPT_CHARS
    max_context_entries: int = DEFAULT_MAX_CONTEXT_ENTRIES
    max_context_evidence: int = DEFAULT_MAX_CONTEXT_EVIDENCE
    prompt_token_reservation_multiplier: float = (
        DEFAULT_PROMPT_TOKEN_RESERVATION_MULTIPLIER
    )
    raw_text_capture: bool = True
    dry_run: bool = False


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
class FixturePackage:
    fixture_path: Path
    fixture_id: str
    source_language: str
    target_language: str
    excerpt: str
    glossary_snapshot_id: str
    glossary_signature: str
    profile_id: str
    primary_profile: str
    evidence_ids: tuple[str, ...]
    entry_ids: tuple[str, ...]
    context_payload: Mapping[str, Any]


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
        usage = response_payload.get("usage") or {}
        return ChatCallResult(
            ok=http_status == 200,
            content=str(message.get("content") or ""),
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "total_tokens": int(usage.get("total_tokens") or 0),
            },
            finish_reason=choice.get("finish_reason"),
            http_status=http_status,
            elapsed_seconds=elapsed,
            request_payload=request_payload,
            response_payload=response_payload,
            response_text=response_text,
        )


class FakeProvider:
    def chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_completion_tokens: int,
    ) -> ChatCallResult:
        role_id = _extract_prompt_value(user_prompt, "role_id")
        evidence_id = _first_prompt_list_value(user_prompt, "allowed_evidence_ids")
        fixture_id = _fixture_id_from_prompt(user_prompt)
        content = _fake_role_output(role_id, evidence_id, fixture_id)
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
) -> dict[str, Any]:
    repo_root = (repo_root or Path.cwd()).resolve()
    diagnostic_dir = _timestamped_diagnostic_dir(config.diagnostic_root)
    diagnostic_dir.mkdir(parents=True, exist_ok=False)
    packages = tuple(
        build_fixture_package(
            fixture_path,
            repo_root=repo_root,
            max_fixture_excerpt_chars=config.max_fixture_excerpt_chars,
            max_context_entries=config.max_context_entries,
            max_context_evidence=config.max_context_evidence,
        )
        for fixture_path in config.fixture_paths
    )

    call_summaries: list[dict[str, Any]] = []
    validation_outputs_by_fixture: dict[str, list[str]] = {}
    calls_made = 0
    reserved_tokens = 0
    observed_tokens = 0

    for package in packages:
        validation_outputs_by_fixture[package.fixture_id] = []
        for role_id in (
            GlossaryRoleId.PRO_BOOK_PROFILE_ADVISOR,
            GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER,
        ):
            if calls_made >= config.max_calls:
                call_summaries.append(
                    {
                        "fixture_id": package.fixture_id,
                        "role_id": role_id.value,
                        "status": "skipped_max_calls",
                    }
                )
                continue
            system_prompt, user_prompt = build_role_prompt(
                package,
                role_id=role_id,
            )
            estimated_prompt_tokens = estimate_tokens(system_prompt + user_prompt)
            reservation = reserve_tokens(
                estimated_prompt_tokens=estimated_prompt_tokens,
                max_completion_tokens=config.max_completion_tokens,
                prompt_token_multiplier=config.prompt_token_reservation_multiplier,
            )
            if (
                reserved_tokens + reservation > config.max_tokens_total
                or observed_tokens + reservation > config.max_tokens_total
            ):
                call_summaries.append(
                    {
                        "fixture_id": package.fixture_id,
                        "role_id": role_id.value,
                        "status": "skipped_token_budget",
                        "estimated_prompt_tokens": estimated_prompt_tokens,
                        "reserved_tokens": reserved_tokens,
                        "observed_tokens_before_call": observed_tokens,
                        "reservation": reservation,
                    }
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
            observed_tokens += int(result.usage.get("total_tokens") or 0)
            validation = validate_glossary_role_output(
                result.content,
                allowed_evidence_ids=package.evidence_ids,
                allowed_entry_ids=package.entry_ids,
            )
            if result.ok and validation.valid:
                validation_outputs_by_fixture[package.fixture_id].append(result.content)
            summary = _call_summary(
                package=package,
                role_id=role_id,
                call_index=call_index,
                estimated_prompt_tokens=estimated_prompt_tokens,
                reservation=reservation,
                result=result,
                validation=validation,
            )
            call_summaries.append(summary)
            call_file = (
                diagnostic_dir
                / f"call-{call_index:02d}-{package.fixture_id}-{role_id.value}.json"
            )
            _write_json(
                call_file,
                _call_diagnostic(
                    package=package,
                    role_id=role_id,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    result=result,
                    validation_summary=summary["validation"],
                    raw_text_capture=config.raw_text_capture,
                ),
            )

    set_validations = []
    for package in packages:
        raw_outputs = validation_outputs_by_fixture[package.fixture_id]
        if len(raw_outputs) <= 1:
            continue
        validation = validate_glossary_role_output_set(
            raw_outputs,
            allowed_evidence_ids=package.evidence_ids,
            allowed_entry_ids=package.entry_ids,
        )
        set_validations.append(
            {
                "fixture_id": package.fixture_id,
                "valid": validation.valid,
                "issue_count": len(validation.issues),
                "issues": [
                    _validation_issue_payload(issue)
                    for issue in validation.issues
                ],
            }
        )

    report = {
        "schema_version": SPIKE_SCHEMA_VERSION,
        "status": _spike_status(call_summaries, set_validations),
        "created_at": datetime.now(UTC).isoformat(),
        "approval": {
            "fixtures": [str(path) for path in config.fixture_paths],
            "max_calls": config.max_calls,
            "max_tokens_total": config.max_tokens_total,
            "provider_model": config.provider_model,
            "prompt_token_reservation_multiplier": (
                config.prompt_token_reservation_multiplier
            ),
            "diagnostic_storage": str(config.diagnostic_root),
            "raw_text_capture": config.raw_text_capture,
        },
        "diagnostic_dir": str(diagnostic_dir),
        "calls_made": calls_made,
        "reserved_tokens": reserved_tokens,
        "observed_tokens": observed_tokens,
        "fixtures": [_fixture_summary(package) for package in packages],
        "calls": call_summaries,
        "set_validations": set_validations,
        "confirmed": _confirmed_items(call_summaries, set_validations),
        "unknown": _unknown_items(call_summaries),
        "tbd": [
            "runtime integration remains TBD",
            "release-version diagnostics retention/deletion/consent remains TBD",
            "RU/UK morphology strategy remains TBD",
        ],
        "recommendation": _recommendation(call_summaries, set_validations),
    }
    _write_json(diagnostic_dir / "manifest.json", report)
    _write_json(diagnostic_dir / "fixtures-compact-context.json", [
        package.context_payload for package in packages
    ])
    return report


def build_fixture_package(
    fixture_path: Path,
    *,
    repo_root: Path,
    max_fixture_excerpt_chars: int,
    max_context_entries: int,
    max_context_evidence: int,
) -> FixturePackage:
    path = _approved_fixture_path(fixture_path, repo_root=repo_root)
    target_language = _target_language_for_path(path)
    content = path.read_bytes()
    plan = plan_txt_translation(content=content, max_fragment_chars=1_500)
    glossary = scan_glossary_candidates(
        plan,
        source_language="en",
        target_language=target_language,
    )
    glossary_validation = validate_glossary_snapshot(glossary)
    if not glossary_validation.valid:
        raise ValueError(f"Invalid glossary snapshot for {fixture_path}")
    profile = detect_book_profile(
        plan,
        source_language="en",
        target_language=target_language,
        glossary_snapshot=glossary,
    )
    profile_validation = validate_book_profile_detection(profile)
    if not profile_validation.valid:
        raise ValueError(f"Invalid book profile detection for {fixture_path}")

    evidence = tuple(glossary.evidence) + tuple(profile.evidence)
    evidence_ids = tuple(sorted({item.evidence_id for item in evidence}))
    entry_ids = tuple(sorted(entry.entry_id for entry in glossary.entries))
    fixture_id = _fixture_id(path)
    entries_payload = [
        {
            "entry_id": entry.entry_id,
            "category": str(entry.category),
            "layer": str(entry.layer),
            "status": str(entry.status),
            "source_canonical": entry.source_canonical,
            "aliases": list(entry.aliases),
            "strategy": str(entry.strategy),
            "grammatical_gender": str(entry.grammatical_gender),
            "confidence": entry.confidence,
            "evidence_refs": list(entry.evidence_refs),
        }
        for entry in glossary.entries[:max_context_entries]
    ]
    evidence_payload = [
        {
            "evidence_id": item.evidence_id,
            "evidence_type": str(item.evidence_type),
            "unit_sequence": item.unit_sequence,
            "source_block_id": item.source_block_id,
            "surface": str(item.surface),
            "occurrence_count": item.occurrence_count,
            "offset_bucket": item.offset_bucket,
        }
        for item in evidence[:max_context_evidence]
    ]
    context_payload = {
        "fixture_id": fixture_id,
        "fixture_path": str(path.relative_to(repo_root)),
        "source_language": "en",
        "target_language": target_language,
        "plan": {
            "document_format": plan.document_format.value,
            "adapter_version": plan.adapter_version,
            "fragment_count": plan.fragment_count,
            "character_count": plan.character_count,
            "estimated_input_tokens": plan.estimated_input_tokens,
        },
        "glossary": {
            "snapshot_id": glossary.snapshot_id,
            "signature": glossary_snapshot_signature(glossary),
            "entry_count": len(glossary.entries),
            "evidence_count": len(glossary.evidence),
            "entries": entries_payload,
        },
        "profile": {
            "profile_id": profile.profile.profile_id,
            "primary_profile": str(profile.profile.primary_profile),
            "secondary_profiles": [
                str(item) for item in profile.profile.secondary_profiles
            ],
            "register": str(profile.profile.register),
            "domain_hints": list(profile.profile.domain_hints),
            "confidence": profile.profile.confidence,
            "evidence_count": len(profile.evidence),
            "rule_ids": [rule.rule_id for rule in profile.rules],
        },
        "evidence": evidence_payload,
    }
    return FixturePackage(
        fixture_path=path,
        fixture_id=fixture_id,
        source_language="en",
        target_language=target_language,
        excerpt=_bounded_excerpt(plan.units, max_fixture_excerpt_chars),
        glossary_snapshot_id=glossary.snapshot_id,
        glossary_signature=glossary_snapshot_signature(glossary),
        profile_id=profile.profile.profile_id,
        primary_profile=str(profile.profile.primary_profile),
        evidence_ids=evidence_ids,
        entry_ids=entry_ids,
        context_payload=context_payload,
    )


def build_role_prompt(
    package: FixturePackage,
    *,
    role_id: GlossaryRoleId,
) -> tuple[str, str]:
    system_prompt = (
        "You are running a bounded FolioLoom DeepSeek Pro glossary/profile "
        "spike. Return one JSON object only. Do not use markdown fences. "
        "Use only provided evidence ids. Do not include keys named raw_text, "
        "source_text, raw_excerpt, prompt, provider_request, or provider_response. "
        "Do not claim semantic certainty for gender/name identity; use unknown, "
        "needs_review, diagnostic_only, or low confidence when evidence is weak."
    )
    payload_shape = _payload_shape(role_id)
    user_prompt = json.dumps(
        {
            "task": "Return a JSON object that passes FolioLoom local role validation.",
            "output_schema_version": GLOSSARY_ROLE_OUTPUT_SCHEMA_VERSION,
            "role_id": role_id.value,
            "role_version": ROLE_VERSION,
            "diagnostics_ref": f"issue-413:{package.fixture_id}:{role_id.value}",
            "input_snapshot_ids": [
                package.glossary_snapshot_id,
                package.profile_id,
            ],
            "allowed_evidence_ids": list(package.evidence_ids),
            "allowed_entry_ids": list(package.entry_ids),
            "root_shape": {
                "output_schema_version": GLOSSARY_ROLE_OUTPUT_SCHEMA_VERSION,
                "role_id": role_id.value,
                "role_version": ROLE_VERSION,
                "status": (
                    "accepted | accepted_low_confidence | diagnostic_only | "
                    "downgraded | needs_review | rejected | failed"
                ),
                "diagnostics_ref": f"issue-413:{package.fixture_id}:{role_id.value}",
                "input_snapshot_ids": [
                    package.glossary_snapshot_id,
                    package.profile_id,
                ],
                "evidence_packet_ids": "array of allowed evidence ids",
                "may_affect_translation_snapshot": (
                    role_id is GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER
                ),
                "confidence": "number 0..1",
                "evidence_refs": "array of allowed evidence ids",
                "payload": payload_shape,
            },
            "fixture_context": package.context_payload,
            "bounded_source_excerpt": package.excerpt,
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    return system_prompt, user_prompt


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 4))


def reserve_tokens(
    *,
    estimated_prompt_tokens: int,
    max_completion_tokens: int,
    prompt_token_multiplier: float,
) -> int:
    multiplier = max(1.0, prompt_token_multiplier)
    prompt_reservation = math.ceil(estimated_prompt_tokens * multiplier)
    return prompt_reservation + max_completion_tokens


def load_env_api_key() -> str:
    key_list = os.getenv("DEEPSEEK_API_KEYS", "")
    for candidate in key_list.split(","):
        api_key = candidate.strip()
        if api_key:
            return api_key
    return os.getenv("DEEPSEEK_API_KEY", "").strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diagnostic-root",
        default="outputs/issue-413-deepseek-pro-spike",
    )
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
    args = parser.parse_args(argv)

    fixture_paths = (
        tuple(Path(item) for item in args.fixture)
        if args.fixture
        else APPROVED_FIXTURES
    )
    config = SpikeConfig(
        fixture_paths=fixture_paths,
        diagnostic_root=Path(args.diagnostic_root),
        provider_model=args.model,
        provider_base_url=args.base_url,
        max_calls=args.max_calls,
        max_tokens_total=args.max_tokens_total,
        max_completion_tokens=args.max_completion_tokens,
        dry_run=args.fake,
    )
    if args.fake:
        provider: ChatProvider = FakeProvider()
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

    report = run_spike(config, provider=provider)
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


def _payload_shape(role_id: GlossaryRoleId) -> Mapping[str, Any]:
    if role_id is GlossaryRoleId.PRO_BOOK_PROFILE_ADVISOR:
        return {
            "profile_advice": {
                "primary_profile": "BookProfileKind enum",
                "secondary_profiles": [],
                "register": "BookRegister enum",
                "domain_hints": [],
                "confidence": "number 0..1",
                "evidence_refs": "allowed evidence ids",
            },
            "warnings": [
                {
                    "note_id": "short id",
                    "kind": "string",
                    "severity": "info | warning | blocker",
                    "message": "short diagnostic message",
                    "evidence_refs": "allowed evidence ids",
                }
            ],
            "mixed_section_notes": [],
        }
    return {
        "profile_context": {
            "profile_id": "provided profile id",
            "primary_profile": "BookProfileKind enum",
        },
        "entries": [
            {
                "entry_id": "stable id",
                "category": "name | term | entity | style_note | morphology_note",
                "layer": "soft | diagnostic",
                "status": "validator_accepted | uncertain | rejected | needs_review",
                "source_canonical": "candidate text",
                "aliases": [],
                "target_canonical": None,
                "target_variants": [],
                "forbidden_variants": [],
                "strategy": "transliterate | translate_meaning | contextual | unknown",
                "grammatical_gender": (
                    "unknown | not_applicable | masculine | feminine | "
                    "common | mixed"
                ),
                "confidence": "number 0..1",
                "evidence_refs": "allowed evidence ids",
                "profile_rule_ids": [],
            }
        ],
        "rejected_candidates": [
            {
                "candidate_id": "short id",
                "reason": "short reason code",
                "evidence_refs": "allowed evidence ids",
            }
        ],
    }


def _approved_fixture_path(fixture_path: Path, *, repo_root: Path) -> Path:
    approved = {
        (repo_root / item).resolve()
        for item in APPROVED_FIXTURES
    }
    resolved = (repo_root / fixture_path).resolve()
    if resolved not in approved:
        raise ValueError(f"Fixture is not approved for issue #413: {fixture_path}")
    if not resolved.is_file():
        raise FileNotFoundError(f"Approved fixture is missing: {fixture_path}")
    return resolved


def _target_language_for_path(path: Path) -> str:
    text = path.name
    if ".en-uk" in text:
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
    package: FixturePackage,
    role_id: GlossaryRoleId,
    call_index: int,
    estimated_prompt_tokens: int,
    reservation: int,
    result: ChatCallResult,
    validation: Any,
) -> dict[str, Any]:
    return {
        "call_index": call_index,
        "fixture_id": package.fixture_id,
        "role_id": role_id.value,
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


def _call_diagnostic(
    *,
    package: FixturePackage,
    role_id: GlossaryRoleId,
    system_prompt: str,
    user_prompt: str,
    result: ChatCallResult,
    validation_summary: Mapping[str, Any],
    raw_text_capture: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SPIKE_SCHEMA_VERSION,
        "diagnostic_scope": "owner_only_deepseek_pro_glossary_profile_spike",
        "fixture_id": package.fixture_id,
        "fixture_path": str(package.fixture_path),
        "role_id": role_id.value,
        "raw_text_capture": raw_text_capture,
        "access_boundary": {
            "visibility": "owner_only",
            "ordinary_logs_allowed": False,
            "telemetry_allowed": False,
            "github_issue_or_pr_allowed": False,
            "release_artifact_allowed": False,
        },
        "secret_exclusion_policy": (
            "Authorization headers, API keys, tokens and real .env* values "
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
        payload["bounded_source_excerpt"] = package.excerpt
    return payload


def _fixture_summary(package: FixturePackage) -> dict[str, Any]:
    context = package.context_payload
    return {
        "fixture_id": package.fixture_id,
        "fixture_path": context["fixture_path"],
        "target_language": package.target_language,
        "fragment_count": context["plan"]["fragment_count"],
        "character_count": context["plan"]["character_count"],
        "glossary_entry_count": context["glossary"]["entry_count"],
        "glossary_evidence_count": context["glossary"]["evidence_count"],
        "profile_id": package.profile_id,
        "primary_profile": package.primary_profile,
        "profile_evidence_count": context["profile"]["evidence_count"],
    }


def _confirmed_items(
    call_summaries: Sequence[Mapping[str, Any]],
    set_validations: Sequence[Mapping[str, Any]],
) -> list[str]:
    items = [
        "approved fixtures were processed through local glossary/profile contracts",
        "provider outputs were captured only in the approved diagnostics directory",
    ]
    if any(item.get("status") == "validated" for item in call_summaries):
        items.append(
            "at least one live/fake provider role output passed local validation"
        )
    if set_validations:
        items.append(
            "cross-role validation was run for fixtures with two valid role outputs"
        )
    return items


def _unknown_items(call_summaries: Sequence[Mapping[str, Any]]) -> list[str]:
    unknown = []
    if any(item.get("status") != "validated" for item in call_summaries):
        unknown.append("one or more role outputs did not produce validated JSON")
    if not call_summaries:
        unknown.append("provider behavior is Unknown because no calls were made")
    return unknown


def _recommendation(
    call_summaries: Sequence[Mapping[str, Any]],
    set_validations: Sequence[Mapping[str, Any]],
) -> str:
    failed = [item for item in call_summaries if item.get("status") != "validated"]
    set_failed = [item for item in set_validations if not item.get("valid")]
    if failed or set_failed:
        return (
            "stop_or_iterate_prompts_before_runtime_integration: provider outputs "
            "or cross-role checks failed local validation."
        )
    return (
        "proceed_to_next_design_review_only: bounded outputs validated, but runtime "
        "integration, retention and release policy remain TBD."
    )


def _spike_status(
    call_summaries: Sequence[Mapping[str, Any]],
    set_validations: Sequence[Mapping[str, Any]],
) -> str:
    if any(item.get("status") == "failed" for item in call_summaries):
        return "completed_with_failures"
    if any(not item.get("valid") for item in set_validations):
        return "completed_with_cross_role_failures"
    if any(
        str(item.get("status", "")).startswith("skipped")
        for item in call_summaries
    ):
        return "completed_with_skips"
    return "completed"


def _validation_issue_payload(issue: Any) -> dict[str, str]:
    return {
        "code": str(issue.code),
        "path": issue.path,
        "message": issue.message,
    }


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


def _extract_prompt_value(prompt: str, key: str) -> str:
    payload = json.loads(prompt)
    return str(payload[key])


def _fixture_id_from_prompt(prompt: str) -> str:
    payload = json.loads(prompt)
    context = payload.get("fixture_context") or {}
    return str(context.get("fixture_id") or "fixture")


def _first_prompt_list_value(prompt: str, key: str) -> str:
    payload = json.loads(prompt)
    values = payload.get(key) or []
    return str(values[0]) if values else "ev:unknown"


def _fake_role_output(role_id: str, evidence_id: str, fixture_id: str) -> str:
    base = {
        "output_schema_version": GLOSSARY_ROLE_OUTPUT_SCHEMA_VERSION,
        "role_id": role_id,
        "role_version": ROLE_VERSION,
        "status": "accepted_low_confidence",
        "diagnostics_ref": f"issue-413:{fixture_id}:{role_id}",
        "input_snapshot_ids": ["glossary-snapshot:test", "book-profile:test"],
        "evidence_packet_ids": [evidence_id],
        "may_affect_translation_snapshot": (
            role_id == GlossaryRoleId.PRO_GLOSSARY_EDITOR_NORMALIZER.value
        ),
        "confidence": 0.62,
        "evidence_refs": [evidence_id],
        "payload": {},
    }
    if role_id == GlossaryRoleId.PRO_BOOK_PROFILE_ADVISOR.value:
        base["payload"] = {
            "profile_advice": {
                "primary_profile": "technical",
                "secondary_profiles": [],
                "register": "technical",
                "domain_hints": ["bounded_fixture"],
                "confidence": 0.62,
                "evidence_refs": [evidence_id],
            },
            "warnings": [],
            "mixed_section_notes": [],
        }
    else:
        base["payload"] = {
            "profile_context": {
                "profile_id": "book-profile:test",
                "primary_profile": "technical",
            },
            "entries": [
                {
                    "entry_id": "entry:bounded-fixture",
                    "category": "term",
                    "layer": "soft",
                    "status": "validator_accepted",
                    "source_canonical": "bounded fixture",
                    "aliases": [],
                    "target_canonical": None,
                    "target_variants": [],
                    "forbidden_variants": [],
                    "strategy": "contextual",
                    "grammatical_gender": "not_applicable",
                    "confidence": 0.62,
                    "evidence_refs": [evidence_id],
                    "profile_rule_ids": [],
                }
            ],
            "rejected_candidates": [],
        }
    return json.dumps(base, ensure_ascii=False, sort_keys=True)


if __name__ == "__main__":
    raise SystemExit(main())
