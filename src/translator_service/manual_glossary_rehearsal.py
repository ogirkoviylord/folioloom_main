"""Manual glossary approval rehearsal.

Provider-free, in-process rehearsal that proves the approved fail-closed
approval boundary before glossary subset selection and before prompt-context
rendering. This module never invokes the translator, runner, cache, filesystem,
database, provider, Telegram, resolver/job/store/logger or archive.

The owner-approved boundary (parent card t_61676831) is:

    ManualGlossaryApproval binds an opaque ``document_ref`` plus the exact
    ``glossary_snapshot_signature`` of the GlossarySnapshot that was approved.
    Any selected-content mutation that changes ``glossary_snapshot_signature``,
    any document-ref mismatch, or a missing approval must fail closed before
    selection, rendering, or any runner integration.

This module deliberately exposes a small surface:

    * :class:`ManualGlossaryApproval` -- the opaque owner approval handle.
    * :class:`ManualGlossaryRehearsalBoundaryError` -- raised on the approved
      pre-render boundary violations (missing approval, document-ref mismatch,
      signature mismatch) before the selector or renderer is ever called.
    * :class:`ManualGlossaryRehearsalFailure` -- structured post-render
      fail-closed result for cases such as a selected hard/locked entry that the
      prompt context renderer dropped due to budget.
    * :class:`ManualGlossaryRehearsalResult` -- the metadata-safe success
      observation (structural identifiers/counts/signatures only).
    * :func:`rehearse_manual_glossary_approval` -- the rehearsal entrypoint.

No production behavior, configuration, or cache-key change is introduced. No
new dependency is required. Only existing, public source seams are imported:

    * :func:`glossary_snapshot_signature`
      (translator_service.glossary_contracts)
    * :func:`select_glossary_subset_for_work_unit`
      (translator_service.glossary_selection)
    * :func:`format_glossary_prompt_context`
      (translator_service.glossary_prompt_context)
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from translator_service.format_adapters.contracts import FormatTranslationUnit
from translator_service.glossary_contracts import (
    GlossarySnapshot,
    glossary_snapshot_signature,
)
from translator_service.glossary_prompt_context import (
    GlossaryPromptContextConfig,
    GlossaryPromptContextResult,
    format_glossary_prompt_context,
)
from translator_service.glossary_selection import (
    GlossarySelectionBudget,
    WorkUnitGlossarySelection,
    select_glossary_subset_for_work_unit,
)

__all__ = [
    "ManualGlossaryApproval",
    "ManualGlossaryRehearsalBoundaryError",
    "ManualGlossaryRehearsalFailure",
    "ManualGlossaryRehearsalFailureReason",
    "ManualGlossaryRehearsalResult",
    "rehearse_manual_glossary_approval",
]


class ManualGlossaryRehearsalFailureReason(StrEnum):
    """Reasons for a post-render fail-closed rehearsal failure.

    These are returned (not raised) so that a caller can keep rehearsal
    observation pure while still proving the boundary was violated. They are
    strictly the cases where the selector and renderer both ran but the
    resulting prompt context violates the approved invariants -- they are never
    used for the pre-render boundary (missing approval, document-ref mismatch,
    signature mismatch), which is handled by
    :class:`ManualGlossaryRehearsalBoundaryError`.
    """

    HARD_ENTRY_OMITTED_BY_PROMPT_BUDGET = "hard_entry_omitted_by_prompt_budget"


class ManualGlossaryRehearsalBoundaryError(Exception):
    """Raised before selector/renderer when the approved boundary is violated.

    The boundary reasons match the owner-approved invariants on the parent
    card: missing approval, document-ref mismatch, signature mismatch. The
    boundary is enforced *before* any call to
    :func:`select_glossary_subset_for_work_unit` or
    :func:`format_glossary_prompt_context`, so callers can spy on those
    functions to prove they were never invoked when a boundary violation is
    reported.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class ManualGlossaryApproval:
    """Opaque owner approval binding a document to a glossary signature.

    The ``document_ref`` is opaque to the rehearsal -- it is compared for
    string equality only and never parsed. The ``glossary_signature`` must
    match the exact return value of
    :func:`glossary_snapshot_signature` for the approved snapshot. Snapshot/
    entry ordering and the snapshot-id field are not part of the equality
    contract (see ``glossary_contracts.glossary_snapshot_signature``).
    """

    document_ref: str
    glossary_signature: str


@dataclass(frozen=True)
class ManualGlossaryRehearsalFailure:
    """Structured fail-closed rehearsal failure observed after rendering.

    Returned (not raised) for post-render boundary violations such as a
    selected hard/locked entry that the prompt-context renderer dropped due to
    a too-small budget. The rehearsal refuses to surface a "success"
    observation in this case and never falls back to a no-glossary render.
    """

    reason: ManualGlossaryRehearsalFailureReason
    message: str
    document_ref: str
    glossary_signature: str
    selection_signature: str
    selected_hard_entry_ids: tuple[str, ...] = ()
    omitted_hard_entry_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualGlossaryRehearsalResult:
    """Metadata-safe success observation of a completed rehearsal.

    Only structural identifiers, counts, signatures, and pre-existing
    metadata-safe diagnostic reasons are surfaced. No source/target raw
    strings, ``prompt_body``, ``provider_request``/``provider_response``,
    ``raw_source_text``, cache keys or any other raw payload field is ever
    placed on this object. The ``renderer_observation`` mirrors the prompt
    context metadata payload returned by the existing renderer helper, which
    already strips raw material.
    """

    document_ref: str
    glossary_signature: str
    snapshot_id: str
    selection_signature: str
    selected_entry_ids: tuple[str, ...]
    included_entry_ids: tuple[str, ...]
    omitted_entry_ids: tuple[str, ...]
    selected_entry_count: int
    included_entry_count: int
    omitted_entry_count: int
    hard_entry_selected_ids: tuple[str, ...]
    hard_entry_included_ids: tuple[str, ...]
    hard_entry_omitted_ids: tuple[str, ...]
    hard_entry_count_in_selection: int
    renderer_observation: dict[str, Any] = field(default_factory=dict)


_BOUNDARY_REASON_BLANK_DOCUMENT_REF = "blank_document_ref"
_BOUNDARY_REASON_MISSING_APPROVAL = "missing_approval"
_BOUNDARY_REASON_DOCUMENT_REF_MISMATCH = "document_ref_mismatch"
_BOUNDARY_REASON_SIGNATURE_MISMATCH = "signature_mismatch"


def _validate_boundary(
    document_ref: str,
    approval: ManualGlossaryApproval | None,
    snapshot: GlossarySnapshot,
) -> str:
    """Validate the owner-approved boundary before any selector/renderer call.

    Returns the canonical glossary signature on success. Raises
    :class:`ManualGlossaryRehearsalBoundaryError` on the approved violations.

    The signature is computed against the *current* snapshot, so a selected-
    content mutation that changes ``glossary_snapshot_signature`` (e.g. adding
    or rewording a hard entry) will invalidate the approval here.
    """
    if not document_ref.strip():
        raise ManualGlossaryRehearsalBoundaryError(
            _BOUNDARY_REASON_BLANK_DOCUMENT_REF,
            "Document reference is blank; cannot proceed to selection or "
            "prompt-context rendering.",
        )
    if approval is None:
        raise ManualGlossaryRehearsalBoundaryError(
            _BOUNDARY_REASON_MISSING_APPROVAL,
            "Manual glossary approval is missing; cannot proceed to selection "
            "or prompt-context rendering.",
        )
    actual_signature = glossary_snapshot_signature(snapshot)
    if approval.document_ref != document_ref:
        raise ManualGlossaryRehearsalBoundaryError(
            _BOUNDARY_REASON_DOCUMENT_REF_MISMATCH,
            "Document reference does not match the approved approval; cannot "
            "proceed to selection or prompt-context rendering.",
        )
    if approval.glossary_signature != actual_signature:
        raise ManualGlossaryRehearsalBoundaryError(
            _BOUNDARY_REASON_SIGNATURE_MISMATCH,
            "Glossary snapshot signature does not match the approved approval; "
            "a selected-content mutation has invalidated the approval before "
            "selection or prompt-context rendering.",
        )
    return actual_signature


def _hard_entry_ids(selection: WorkUnitGlossarySelection) -> tuple[str, ...]:
    """Return the entry ids that were selected as hard constraints.

    ``SelectedGlossaryEntry`` does not expose the original glossary layer, so
    we re-derive the hard-layer signal from
    :class:`GlossarySelectionReason.HARD_CONSTRAINT`, which the selector adds to
    every Hard-layer entry (see ``glossary_selection._score_entry``).
    """
    from translator_service.glossary_selection import GlossarySelectionReason

    return tuple(
        selected.entry_id
        for selected in selection.selected_entries
        if GlossarySelectionReason.HARD_CONSTRAINT in selected.reasons
    )


def _omitted_entry_ids(result: GlossaryPromptContextResult) -> tuple[str, ...]:
    """Compute the omitted entry ids from the prompt-context result.

    ``GlossaryPromptContextResult`` exposes ``included_entry_ids`` but not a
    matching ``omitted_entry_ids`` property, so we derive it locally.
    """
    return tuple(entry.entry_id for entry in result.omitted_entries)


def _renderer_metadata(result: GlossaryPromptContextResult) -> dict[str, Any]:
    """Return the metadata-safe renderer observation payload.

    This delegates to the existing public prompt-context metadata helper; it
    surfaces only structural identifiers, counts, signature-version, and
    pre-existing diagnostic reasons. It never includes raw source/target text,
    ``prompt_body``, provider payloads, or cache keys.
    """
    from translator_service.glossary_prompt_context import (
        glossary_prompt_context_metadata_payload,
    )

    return glossary_prompt_context_metadata_payload(result)


def rehearse_manual_glossary_approval(
    document_ref: str,
    approval: ManualGlossaryApproval | None,
    snapshot: GlossarySnapshot,
    work_unit: FormatTranslationUnit,
    *,
    selection_budget: GlossarySelectionBudget,
    prompt_config: GlossaryPromptContextConfig | None = None,
    profile_rule_ids: Iterable[str] = (),
) -> ManualGlossaryRehearsalResult | ManualGlossaryRehearsalFailure:
    """Run a provider-free manual glossary approval rehearsal.

    The rehearsal proves the approved fail-closed boundary:

    1. Missing approval, document-ref mismatch, or signature mismatch raises
       :class:`ManualGlossaryRehearsalBoundaryError` *before* any call to
       :func:`select_glossary_subset_for_work_unit` or
       :func:`format_glossary_prompt_context`.
    2. If the selector selects a hard/locked entry but the renderer drops that
       same entry due to a too-small prompt/character budget, a structured
       :class:`ManualGlossaryRehearsalFailure` is returned -- never a success
       observation and never a no-glossary fallback.
    3. On success, only structural identifiers/counts/signatures and the
       metadata-safe renderer observation are returned.

    This function never invokes the translator, runner, cache, filesystem,
    database, provider, Telegram, resolver, job store, logger, or archive.
    """
    canonical_signature = _validate_boundary(
        document_ref=document_ref,
        approval=approval,
        snapshot=snapshot,
    )

    selection = select_glossary_subset_for_work_unit(
        work_unit,
        snapshot,
        budget=selection_budget,
        profile_rule_ids=tuple(profile_rule_ids),
    )

    hard_selected_ids = _hard_entry_ids(selection)

    prompt_context = format_glossary_prompt_context(
        snapshot.entries,
        selected_entry_ids=selection.selected_entry_ids,
        config=prompt_config,
    )

    included_ids = set(prompt_context.included_entry_ids)
    omitted_ids = set(_omitted_entry_ids(prompt_context))

    hard_included = tuple(
        entry_id for entry_id in hard_selected_ids if entry_id in included_ids
    )
    hard_omitted = tuple(
        entry_id for entry_id in hard_selected_ids if entry_id in omitted_ids
    )
    if hard_omitted:
        # Any selected hard/locked entry omitted by the renderer is a
        # fail-closed rehearsal failure, not a success and not a no-glossary
        # fallback.
        return ManualGlossaryRehearsalFailure(
            reason=ManualGlossaryRehearsalFailureReason
            .HARD_ENTRY_OMITTED_BY_PROMPT_BUDGET,
            message=(
                "A selected hard/locked entry was absent from rendered prompt "
                "context due to budget; rehearsal refuses to emit a success "
                "observation."
            ),
            document_ref=document_ref,
            glossary_signature=canonical_signature,
            selection_signature=selection.selection_signature,
            selected_hard_entry_ids=hard_selected_ids,
            omitted_hard_entry_ids=hard_omitted,
        )

    return ManualGlossaryRehearsalResult(
        document_ref=document_ref,
        glossary_signature=canonical_signature,
        snapshot_id=snapshot.snapshot_id,
        selection_signature=selection.selection_signature,
        selected_entry_ids=selection.selected_entry_ids,
        included_entry_ids=prompt_context.included_entry_ids,
        omitted_entry_ids=_omitted_entry_ids(prompt_context),
        selected_entry_count=len(selection.selected_entries),
        included_entry_count=len(prompt_context.included_entries),
        omitted_entry_count=len(prompt_context.omitted_entries),
        hard_entry_selected_ids=hard_selected_ids,
        hard_entry_included_ids=hard_included,
        hard_entry_omitted_ids=hard_omitted,
        hard_entry_count_in_selection=len(hard_selected_ids),
        renderer_observation=_renderer_metadata(prompt_context),
    )
