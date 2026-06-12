from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from translator_service.glossary_editor_chunk_outputs import (
    ChunkedGlossaryEditorFindingCode,
    ChunkedGlossaryEditorFindingSeverity,
    ChunkedGlossaryEditorMergeResult,
    ChunkedGlossaryEditorValidationCode,
    ChunkedGlossaryEditorValidationResult,
    merge_chunked_glossary_editor_outputs,
)
from translator_service.glossary_editor_packets import GlossaryEditorPacket

GLOSSARY_EDITOR_EVALUATION_SCHEMA_VERSION = "glossary-editor-evaluation-v1"


class GlossaryEditorReadinessStage(StrEnum):
    LOCAL_TO_PROVIDER_RETRY = "local_fake_to_provider_retry"
    PROVIDER_RETRY_TO_RUNTIME_ARCHITECTURE = (
        "provider_retry_to_runtime_architecture_review"
    )


class GlossaryEditorReadinessGateCode(StrEnum):
    HAS_CHUNKS = "has_chunks"
    SCHEMA_VALIDITY = "schema_validity"
    EVIDENCE_REF_COVERAGE = "evidence_ref_coverage"
    INVALID_CHUNK_RATE = "invalid_chunk_rate"
    BLOCKER_FINDINGS = "blocker_findings"
    WARNING_FINDINGS = "warning_findings"
    DUPLICATE_RATE = "duplicate_rate"
    CONFLICT_RATE = "conflict_rate"
    BUDGET_OVERRUNS = "budget_overruns"
    NEEDS_REVIEW_RATE = "needs_review_rate"
    PROVIDER_EVIDENCE = "provider_evidence"
    PROVIDER_TOKEN_CAP = "provider_token_cap"


@dataclass(frozen=True)
class GlossaryEditorEvaluationThresholds:
    min_schema_validity_rate: float = 1.0
    min_evidence_ref_coverage_rate: float = 1.0
    max_invalid_chunk_rate: float = 0.0
    max_blocker_findings: int = 0
    max_warning_findings: int = 0
    max_duplicate_rate: float = 0.0
    max_conflict_rate: float = 0.0
    max_budget_overruns: int = 0
    max_needs_review_rate: float = 0.25


DEFAULT_GLOSSARY_EDITOR_EVALUATION_THRESHOLDS = (
    GlossaryEditorEvaluationThresholds()
)


@dataclass(frozen=True)
class GlossaryEditorEvaluationMetrics:
    total_chunks: int
    valid_chunks: int
    invalid_chunks: int
    schema_validity_rate: float
    evidence_ref_coverage_rate: float
    invalid_chunk_rate: float
    proposed_entry_count: int
    needs_review_count: int
    needs_review_rate: float
    blocker_finding_count: int
    warning_finding_count: int
    duplicate_finding_count: int
    duplicate_rate: float
    conflict_finding_count: int
    conflict_rate: float
    budget_overrun_count: int
    max_packet_budget_utilization: float
    provider_observed_tokens: int | None
    provider_max_tokens_total: int | None
    provider_token_over_cap: bool


@dataclass(frozen=True)
class GlossaryEditorReadinessGate:
    stage: GlossaryEditorReadinessStage
    code: GlossaryEditorReadinessGateCode
    passed: bool
    actual: int | float | bool | str | None
    expected: str
    message: str


@dataclass(frozen=True)
class GlossaryEditorEvaluationResult:
    schema_version: str
    metrics: GlossaryEditorEvaluationMetrics
    gates: tuple[GlossaryEditorReadinessGate, ...]

    @property
    def provider_retry_ready(self) -> bool:
        return all(
            gate.passed
            for gate in self.gates
            if gate.stage is GlossaryEditorReadinessStage.LOCAL_TO_PROVIDER_RETRY
        )

    @property
    def runtime_architecture_review_ready(self) -> bool:
        return self.provider_retry_ready and all(
            gate.passed
            for gate in self.gates
            if (
                gate.stage
                is GlossaryEditorReadinessStage.PROVIDER_RETRY_TO_RUNTIME_ARCHITECTURE
            )
        )


def evaluate_glossary_editor_readiness(
    validation_results: Sequence[ChunkedGlossaryEditorValidationResult],
    *,
    merge_result: ChunkedGlossaryEditorMergeResult | None = None,
    packets: Sequence[GlossaryEditorPacket] = (),
    metadata_report: Mapping[str, Any] | None = None,
    provider_evidence_available: bool = False,
    thresholds: GlossaryEditorEvaluationThresholds = (
        DEFAULT_GLOSSARY_EDITOR_EVALUATION_THRESHOLDS
    ),
) -> GlossaryEditorEvaluationResult:
    """Evaluate local glossary-editor metadata without judging semantic truth."""

    validations = tuple(validation_results)
    merge = merge_result or merge_chunked_glossary_editor_outputs(validations)
    metrics = _metrics(
        validations,
        merge=merge,
        packets=tuple(packets),
        metadata_report=metadata_report,
    )
    gates = _local_gates(metrics, thresholds=thresholds) + _runtime_gates(
        metrics,
        provider_evidence_available=provider_evidence_available,
    )
    return GlossaryEditorEvaluationResult(
        schema_version=GLOSSARY_EDITOR_EVALUATION_SCHEMA_VERSION,
        metrics=metrics,
        gates=gates,
    )


def glossary_editor_evaluation_payload(
    result: GlossaryEditorEvaluationResult,
) -> dict[str, Any]:
    return {
        "schema_version": result.schema_version,
        "provider_retry_ready": result.provider_retry_ready,
        "runtime_architecture_review_ready": (
            result.runtime_architecture_review_ready
        ),
        "metrics": result.metrics.__dict__,
        "gates": [
            {
                "stage": gate.stage.value,
                "code": gate.code.value,
                "passed": gate.passed,
                "actual": gate.actual,
                "expected": gate.expected,
                "message": gate.message,
            }
            for gate in result.gates
        ],
    }


def serialize_glossary_editor_evaluation(
    result: GlossaryEditorEvaluationResult,
) -> str:
    return json.dumps(
        glossary_editor_evaluation_payload(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _metrics(
    validations: tuple[ChunkedGlossaryEditorValidationResult, ...],
    *,
    merge: ChunkedGlossaryEditorMergeResult,
    packets: tuple[GlossaryEditorPacket, ...],
    metadata_report: Mapping[str, Any] | None,
) -> GlossaryEditorEvaluationMetrics:
    total_chunks = len(validations)
    valid_chunks = sum(1 for result in validations if result.valid)
    invalid_chunks = total_chunks - valid_chunks
    proposed_entry_count = len(merge.proposed_entries)
    needs_review_count = sum(
        1 for entry in merge.proposed_entries if entry.needs_review
    )
    blocker_finding_count = _finding_count(
        merge,
        severity=ChunkedGlossaryEditorFindingSeverity.BLOCKER,
    )
    warning_finding_count = _finding_count(
        merge,
        severity=ChunkedGlossaryEditorFindingSeverity.WARNING,
    )
    duplicate_finding_count = _finding_code_count(
        merge,
        {ChunkedGlossaryEditorFindingCode.DUPLICATE_ENTRY_OUTPUT},
    )
    conflict_finding_count = _finding_code_count(
        merge,
        {
            ChunkedGlossaryEditorFindingCode.CONFLICTING_ALIASES,
            ChunkedGlossaryEditorFindingCode.CONFLICTING_TARGET_VARIANTS,
        },
    )
    budget_overrun_count = _budget_overrun_count(packets)
    provider_observed_tokens, provider_max_tokens_total = _provider_tokens(
        metadata_report
    )
    provider_token_over_cap = (
        provider_observed_tokens is not None
        and provider_max_tokens_total is not None
        and provider_observed_tokens > provider_max_tokens_total
    )
    covered_evidence, total_evidence = _evidence_ref_coverage(validations)
    return GlossaryEditorEvaluationMetrics(
        total_chunks=total_chunks,
        valid_chunks=valid_chunks,
        invalid_chunks=invalid_chunks,
        schema_validity_rate=_rate(valid_chunks, total_chunks, empty=0.0),
        evidence_ref_coverage_rate=_rate(
            covered_evidence,
            total_evidence,
            empty=1.0,
        ),
        invalid_chunk_rate=_rate(invalid_chunks, total_chunks, empty=1.0),
        proposed_entry_count=proposed_entry_count,
        needs_review_count=needs_review_count,
        needs_review_rate=_rate(needs_review_count, proposed_entry_count),
        blocker_finding_count=blocker_finding_count,
        warning_finding_count=warning_finding_count,
        duplicate_finding_count=duplicate_finding_count,
        duplicate_rate=_rate(duplicate_finding_count, proposed_entry_count),
        conflict_finding_count=conflict_finding_count,
        conflict_rate=_rate(conflict_finding_count, proposed_entry_count),
        budget_overrun_count=budget_overrun_count,
        max_packet_budget_utilization=_max_packet_budget_utilization(packets),
        provider_observed_tokens=provider_observed_tokens,
        provider_max_tokens_total=provider_max_tokens_total,
        provider_token_over_cap=provider_token_over_cap,
    )


def _local_gates(
    metrics: GlossaryEditorEvaluationMetrics,
    *,
    thresholds: GlossaryEditorEvaluationThresholds,
) -> tuple[GlossaryEditorReadinessGate, ...]:
    stage = GlossaryEditorReadinessStage.LOCAL_TO_PROVIDER_RETRY
    return (
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.HAS_CHUNKS,
            metrics.total_chunks > 0,
            metrics.total_chunks,
            "> 0",
            "At least one validated chunk result is required.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.SCHEMA_VALIDITY,
            metrics.schema_validity_rate >= thresholds.min_schema_validity_rate,
            metrics.schema_validity_rate,
            f">= {thresholds.min_schema_validity_rate}",
            "All evaluated chunks must pass local schema validation.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.EVIDENCE_REF_COVERAGE,
            (
                metrics.evidence_ref_coverage_rate
                >= thresholds.min_evidence_ref_coverage_rate
            ),
            metrics.evidence_ref_coverage_rate,
            f">= {thresholds.min_evidence_ref_coverage_rate}",
            "Outputs must cite packet evidence refs instead of omitting evidence.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.INVALID_CHUNK_RATE,
            metrics.invalid_chunk_rate <= thresholds.max_invalid_chunk_rate,
            metrics.invalid_chunk_rate,
            f"<= {thresholds.max_invalid_chunk_rate}",
            "Invalid chunks are excluded from merge and block readiness.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.BLOCKER_FINDINGS,
            metrics.blocker_finding_count <= thresholds.max_blocker_findings,
            metrics.blocker_finding_count,
            f"<= {thresholds.max_blocker_findings}",
            "Merge blocker findings must be resolved before retry readiness.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.WARNING_FINDINGS,
            metrics.warning_finding_count <= thresholds.max_warning_findings,
            metrics.warning_finding_count,
            f"<= {thresholds.max_warning_findings}",
            "Warnings are tracked as readiness risk, not semantic proof.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.DUPLICATE_RATE,
            metrics.duplicate_rate <= thresholds.max_duplicate_rate,
            metrics.duplicate_rate,
            f"<= {thresholds.max_duplicate_rate}",
            "Duplicate glossary proposals must stay within the readiness threshold.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.CONFLICT_RATE,
            metrics.conflict_rate <= thresholds.max_conflict_rate,
            metrics.conflict_rate,
            f"<= {thresholds.max_conflict_rate}",
            "Conflicting glossary proposals block readiness.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.BUDGET_OVERRUNS,
            metrics.budget_overrun_count <= thresholds.max_budget_overruns,
            metrics.budget_overrun_count,
            f"<= {thresholds.max_budget_overruns}",
            "Packets must remain within local prompt budget metadata.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.NEEDS_REVIEW_RATE,
            metrics.needs_review_rate <= thresholds.max_needs_review_rate,
            metrics.needs_review_rate,
            f"<= {thresholds.max_needs_review_rate}",
            "High needs_review rate means outputs are not ready to trust.",
        ),
    )


def _runtime_gates(
    metrics: GlossaryEditorEvaluationMetrics,
    *,
    provider_evidence_available: bool,
) -> tuple[GlossaryEditorReadinessGate, ...]:
    stage = GlossaryEditorReadinessStage.PROVIDER_RETRY_TO_RUNTIME_ARCHITECTURE
    token_cap_checked = metrics.provider_max_tokens_total is not None
    return (
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.PROVIDER_EVIDENCE,
            provider_evidence_available,
            provider_evidence_available,
            "True",
            "Runtime architecture review needs explicit provider-retry evidence.",
        ),
        _gate(
            stage,
            GlossaryEditorReadinessGateCode.PROVIDER_TOKEN_CAP,
            token_cap_checked and not metrics.provider_token_over_cap,
            metrics.provider_observed_tokens,
            "<= approved max_tokens_total",
            "Provider retry token usage must stay within the approved cap.",
        ),
    )


def _gate(
    stage: GlossaryEditorReadinessStage,
    code: GlossaryEditorReadinessGateCode,
    passed: bool,
    actual: int | float | bool | str | None,
    expected: str,
    message: str,
) -> GlossaryEditorReadinessGate:
    return GlossaryEditorReadinessGate(
        stage=stage,
        code=code,
        passed=passed,
        actual=actual,
        expected=expected,
        message=message,
    )


def _evidence_ref_coverage(
    validations: tuple[ChunkedGlossaryEditorValidationResult, ...],
) -> tuple[int, int]:
    covered = 0
    total = 0
    for result in validations:
        for issue in result.issues:
            if issue.code is ChunkedGlossaryEditorValidationCode.MISSING_EVIDENCE:
                total += 1
        if result.document is None:
            continue
        document_covered, document_total = _document_evidence_ref_coverage(
            result.document
        )
        covered += document_covered
        total += document_total
    return covered, total


def _document_evidence_ref_coverage(document: Mapping[str, Any]) -> tuple[int, int]:
    covered = 0
    total = 0
    for value in (document.get("evidence_refs"),):
        total += 1
        if _has_evidence_refs(value):
            covered += 1
    for key in ("proposed_entries", "rejected_entries", "findings"):
        items = document.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping):
                continue
            total += 1
            if _has_evidence_refs(item.get("evidence_refs")):
                covered += 1
    return covered, total


def _has_evidence_refs(value: Any) -> bool:
    return isinstance(value, list) and any(
        isinstance(item, str) and item.strip() for item in value
    )


def _finding_count(
    merge: ChunkedGlossaryEditorMergeResult,
    *,
    severity: ChunkedGlossaryEditorFindingSeverity,
) -> int:
    return sum(1 for finding in merge.findings if finding.severity is severity)


def _finding_code_count(
    merge: ChunkedGlossaryEditorMergeResult,
    codes: set[ChunkedGlossaryEditorFindingCode],
) -> int:
    return sum(1 for finding in merge.findings if finding.code in codes)


def _budget_overrun_count(packets: tuple[GlossaryEditorPacket, ...]) -> int:
    return sum(
        1
        for packet in packets
        if (
            packet.estimated_prompt_tokens > packet.max_estimated_prompt_tokens
            or packet.reserved_prompt_tokens > packet.max_reserved_prompt_tokens
        )
    )


def _max_packet_budget_utilization(
    packets: tuple[GlossaryEditorPacket, ...],
) -> float:
    utilizations: list[float] = []
    for packet in packets:
        if packet.max_estimated_prompt_tokens > 0:
            utilizations.append(
                packet.estimated_prompt_tokens / packet.max_estimated_prompt_tokens
            )
        if packet.max_reserved_prompt_tokens > 0:
            utilizations.append(
                packet.reserved_prompt_tokens / packet.max_reserved_prompt_tokens
            )
    return round(max(utilizations), 6) if utilizations else 0.0


def _provider_tokens(
    metadata_report: Mapping[str, Any] | None,
) -> tuple[int | None, int | None]:
    if metadata_report is None:
        return None, None
    observed = _optional_int(metadata_report.get("observed_tokens"))
    max_tokens_total = _optional_int(
        (metadata_report.get("approval") or {}).get("max_tokens_total")
        if isinstance(metadata_report.get("approval"), Mapping)
        else None
    )
    return observed, max_tokens_total


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _rate(numerator: int, denominator: int, *, empty: float = 0.0) -> float:
    if denominator <= 0:
        return empty
    return round(numerator / denominator, 6)
