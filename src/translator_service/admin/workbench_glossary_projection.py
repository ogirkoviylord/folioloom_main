"""Pure Workbench projection for Stage-1 glossary rehearsal observations.

This module maps only the metadata-safe shape of a completed manual glossary
rehearsal into a local view model.  It neither creates approval nor executes
selection/rendering; it does not import the rehearsal implementation at runtime
so it remains a presentation-only seam.  In particular, it does not surface
raw glossary source/target strings or renderer payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "WorkbenchGlossaryProjection",
    "WorkbenchGlossaryProjectionState",
    "project_workbench_glossary_rehearsal",
]


class WorkbenchGlossaryProjectionState(StrEnum):
    """Local observation states, deliberately distinct from runtime approval."""

    FAIL_CLOSED = "fail_closed"
    LOCAL_STRUCTURAL_OBSERVATION = "local_structural_observation"


@dataclass(frozen=True)
class WorkbenchGlossaryProjection:
    """Metadata-only Workbench model for a Stage-1 rehearsal observation.

    ``runtime_authorized`` is permanently false: a structurally complete local
    rehearsal must never be presented as runtime authorization or execution
    readiness.
    """

    document_ref: str | None
    state: WorkbenchGlossaryProjectionState
    reason_code: str | None
    glossary_signature: str | None
    snapshot_id: str | None
    selection_signature: str | None
    selected_entry_ids: tuple[str, ...]
    rendered_entry_ids: tuple[str, ...]
    omitted_entry_ids: tuple[str, ...]
    selected_entry_count: int
    rendered_entry_count: int
    omitted_entry_count: int
    runtime_authorized: bool = False


_FAILURE_REASON = "hard_entry_omitted_by_prompt_budget"
_INVALID_OBSERVATION_REASON = "local_structural_rehearsal_unavailable"


def _safe_identifier(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_identifier_tuple(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, tuple) or not all(
        isinstance(identifier, str) and identifier for identifier in value
    ):
        return None
    return value


def _fail_closed(
    rehearsal: object,
    *,
    reason_code: str = _INVALID_OBSERVATION_REASON,
) -> WorkbenchGlossaryProjection:
    """Return the conservative view model without copying unknown payloads."""
    return WorkbenchGlossaryProjection(
        document_ref=_safe_identifier(getattr(rehearsal, "document_ref", None)),
        state=WorkbenchGlossaryProjectionState.FAIL_CLOSED,
        reason_code=reason_code,
        glossary_signature=_safe_identifier(
            getattr(rehearsal, "glossary_signature", None)
        ),
        snapshot_id=None,
        selection_signature=_safe_identifier(
            getattr(rehearsal, "selection_signature", None)
        ),
        selected_entry_ids=(),
        rendered_entry_ids=(),
        omitted_entry_ids=(),
        selected_entry_count=0,
        rendered_entry_count=0,
        omitted_entry_count=0,
    )


def project_workbench_glossary_rehearsal(
    rehearsal: object,
) -> WorkbenchGlossaryProjection:
    """Project a completed Stage-1 rehearsal result without invoking it.

    Unknown or incomplete observations fail closed.  The only accepted failure
    reason is the existing Stage-1 metadata-safe reason; all other failure
    objects receive a generic local-unavailable reason rather than copying
    arbitrary text into the view model.
    """
    failure_reason = getattr(getattr(rehearsal, "reason", None), "value", None)
    if failure_reason is not None:
        if failure_reason == _FAILURE_REASON:
            return _fail_closed(rehearsal, reason_code=_FAILURE_REASON)
        return _fail_closed(rehearsal)

    document_ref = _safe_identifier(getattr(rehearsal, "document_ref", None))
    glossary_signature = _safe_identifier(
        getattr(rehearsal, "glossary_signature", None)
    )
    snapshot_id = _safe_identifier(getattr(rehearsal, "snapshot_id", None))
    selection_signature = _safe_identifier(
        getattr(rehearsal, "selection_signature", None)
    )
    selected_entry_ids = _safe_identifier_tuple(
        getattr(rehearsal, "selected_entry_ids", None)
    )
    rendered_entry_ids = _safe_identifier_tuple(
        getattr(rehearsal, "included_entry_ids", None)
    )
    omitted_entry_ids = _safe_identifier_tuple(
        getattr(rehearsal, "omitted_entry_ids", None)
    )
    if None in (
        document_ref,
        glossary_signature,
        snapshot_id,
        selection_signature,
        selected_entry_ids,
        rendered_entry_ids,
        omitted_entry_ids,
    ):
        return _fail_closed(rehearsal)
    assert selected_entry_ids is not None
    assert rendered_entry_ids is not None
    assert omitted_entry_ids is not None

    return WorkbenchGlossaryProjection(
        document_ref=document_ref,
        state=WorkbenchGlossaryProjectionState.LOCAL_STRUCTURAL_OBSERVATION,
        reason_code=None,
        glossary_signature=glossary_signature,
        snapshot_id=snapshot_id,
        selection_signature=selection_signature,
        selected_entry_ids=selected_entry_ids,
        rendered_entry_ids=rendered_entry_ids,
        omitted_entry_ids=omitted_entry_ids,
        selected_entry_count=len(selected_entry_ids),
        rendered_entry_count=len(rendered_entry_ids),
        omitted_entry_count=len(omitted_entry_ids),
    )
