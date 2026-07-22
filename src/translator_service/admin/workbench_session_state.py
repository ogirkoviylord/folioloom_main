"""Ephemeral Workbench glossary session state (Stage 1 / glossary-first slice).

Scope and non-claims (per UI packet §5.2, §6 and §11):

* Lives in an in-process :data:`WORKBENCH_SESSION_STATE` dict keyed by
  ``session_id``. Never persisted, never cached, never in DB.
* Resets on reload and on process restart.
* Never imports or builds a ``GlossarySnapshot``; the UI rehearsal must
  not become a glossary-builder. Save / provider / runner / cache /
  Telegram / resolver / job / archive / DB / filesystem are explicitly
  out of scope (packet §6, §11).
* ``ManualGlossaryApproval`` is still an owner-blocker (GATE1 audit C1).
  A locally-mutated ``Term`` whose status is ``APPROVED`` or ``LOCKED``
  is a rehearsal state only — the UI must not imply authoritative
  approval. The README/disclosure in the helper rail says so verbatim.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256

# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------


class ApprovalState(StrEnum):
    """Aggregate approval state of a workbench glossary session."""

    READY = "ready"
    NOT_READY = "not-ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
    CONFLICT = "conflict"


class TermStatus(StrEnum):
    """Lifecycle status of a single term row in the glossary rehearsal."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    LOCKED = "locked"
    REJECTED = "rejected"
    CONFLICT = "conflict"


#: Term-type placeholder vocabulary (packet §5.2). Kept small on purpose;
#: this slice does not invent new glossary semantics.
TERM_TYPES: tuple[str, ...] = ("name", "place", "phrase", "term")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_term_id() -> str:
    return uuid.uuid4().hex


def _document_signature(
    *,
    document_id: str,
    fmt: str,
    source_language: str,
    target_language: str,
) -> str:
    payload = f"{document_id}|{fmt}|{source_language}|{target_language}".encode()
    return sha256(payload).hexdigest()[:16]


def _term_signature(
    *,
    source: str,
    target: str,
    type_: str,
    notes: str,
    status: TermStatus,
) -> str:
    payload = f"{source}|{target}|{type_}|{notes}|{status.value}".encode()
    return sha256(payload).hexdigest()[:16]


@dataclass
class Term:
    """A single glossary term in the rehearsal state.

    Notes:
        * ``locked`` is denormalised to mirror the ``status == LOCKED``
          invariant; the component layer uses it directly for row
          affordances.
        * ``signature`` is recomputed on every status / content change
          (packet §5.2, transition ``lock-then-edit-blocked``).
    """

    id: str
    source: str
    target: str
    type: str
    notes: str
    status: TermStatus
    locked: bool
    last_edited_at: datetime
    signature: str

    @classmethod
    def new(
        cls,
        *,
        source: str,
        target: str,
        type_: str,
        notes: str,
        status: TermStatus = TermStatus.DRAFT,
    ) -> Term:
        return cls(
            id=_new_term_id(),
            source=source,
            target=target,
            type=type_,
            notes=notes,
            status=status,
            locked=status == TermStatus.LOCKED,
            last_edited_at=_utcnow(),
            signature=_term_signature(
                source=source,
                target=target,
                type_=type_,
                notes=notes,
                status=status,
            ),
        )

    def recompute_signature(self) -> None:
        self.signature = _term_signature(
            source=self.source,
            target=self.target,
            type_=self.type,
            notes=self.notes,
            status=self.status,
        )


@dataclass
class DocumentContext:
    """Caller-injected document reference; opaque to this slice.

    The contract is deliberately narrow (packet §3, §6 ``STALE`` row):
    the Admin caller is expected to supply ``document_id`` plus enough
    metadata for the UI to render a calm document context strip. If
    the signature drifts against ``initial_document_signature`` the
    session moves to :attr:`ApprovalState.STALE`.
    """

    document_id: str
    filename: str
    format: str  # "txt" | "docx" | "epub"
    source_language: str
    target_language: str
    signature: str
    provided_at: datetime

    @classmethod
    def from_query(
        cls,
        *,
        document_id: str,
        filename: str = "untitled.txt",
        fmt: str = "txt",
        source_language: str = "en",
        target_language: str = "uk",
    ) -> DocumentContext:
        return cls(
            document_id=document_id,
            filename=filename,
            format=fmt,
            source_language=source_language,
            target_language=target_language,
            signature=_document_signature(
                document_id=document_id,
                fmt=fmt,
                source_language=source_language,
                target_language=target_language,
            ),
            provided_at=_utcnow(),
        )


@dataclass
class WorkbenchSessionState:
    """In-process rehearsal state for a single owner session.

    The state is intentionally narrow: a document context, a terms
    dict keyed by :attr:`Term.id`, a precomputed health snapshot, the
    current :class:`ApprovalState`, and the last fail-closed reason.
    """

    session_id: str
    document: DocumentContext
    initial_document_signature: str
    terms: dict[str, Term] = field(default_factory=dict)
    health_snapshot: dict[str, int] = field(
        default_factory=lambda: _empty_health_snapshot()
    )
    approval_state: ApprovalState = ApprovalState.READY
    last_error: str | None = None
    manual_approval: object | None = None
    local_check_result: object | None = None
    local_check_block_reason: str | None = None

    # --- helpers ----------------------------------------------------------

    def is_stale(self) -> bool:
        return self.document.signature != self.initial_document_signature

    def refresh_approval_state(self) -> None:
        """Recompute :attr:`approval_state` from current terms + document.

        Implements the packet §5.2 transitions (priority order):

        1. ``last_error`` set by a backend seam short-circuits to
           :attr:`ApprovalState.UNAVAILABLE`.
        2. Signature drift moves to :attr:`ApprovalState.STALE`.
        3. Any term in :attr:`TermStatus.CONFLICT` moves to
           :attr:`ApprovalState.CONFLICT`.
        4. Otherwise ``>=1 approved+locked AND 0 conflict`` is
           :attr:`ApprovalState.READY`; everything else is
           :attr:`ApprovalState.NOT_READY`.
        """
        if self.last_error == "not-wired":
            # Per packet §6 ``UNAVAILABLE`` column: backend seam raised.
            # We collapse the "not wired yet" case here too because both
            # flows are fail-closed at this slice.
            self.approval_state = ApprovalState.UNAVAILABLE
            return
        if self.is_stale():
            self.approval_state = ApprovalState.STALE
            return
        if any(term.status == TermStatus.CONFLICT for term in self.terms.values()):
            self.approval_state = ApprovalState.CONFLICT
            return
        has_locked = any(
            term.status == TermStatus.LOCKED for term in self.terms.values()
        )
        has_approved = any(
            term.status == TermStatus.APPROVED for term in self.terms.values()
        )
        if not self.terms:
            # Packet §5.2 row 7: empty seed → READY-by-default.
            self.approval_state = ApprovalState.READY
            return
        if has_locked or has_approved:
            # Any approved or locked term (with 0 conflicts) is READY.
            # The strict "approved AND locked" gate is only relevant when
            # distinguishing READY from post-reject / post-edit decay
            # transitions; for the snapshot we treat both as positive
            # signals of progress.
            self.approval_state = ApprovalState.READY
        else:
            self.approval_state = ApprovalState.NOT_READY

    def refresh_health_snapshot(self) -> None:
        """Recompute :attr:`health_snapshot` from current terms."""
        snapshot = _empty_health_snapshot()
        snapshot["total"] = len(self.terms)
        for term in self.terms.values():
            snapshot[term.status.value] += 1
        self.health_snapshot = snapshot

    def glossary_snapshot(self):
        """Build the current local-only snapshot deterministically from terms."""
        from translator_service.glossary_contracts import (
            GlossaryEntry,
            GlossaryEntryCategory,
            GlossaryEntryStatus,
            GlossaryEvidenceRef,
            GlossaryEvidenceSurface,
            GlossaryEvidenceType,
            GlossaryLayer,
            GlossarySnapshot,
            GlossaryStrategy,
        )

        entries = []
        evidence = []
        for index, term in enumerate(self.terms.values(), start=1):
            evidence_id = f"workbench:{term.id}"
            evidence.append(
                GlossaryEvidenceRef(
                    evidence_id=evidence_id,
                    evidence_type=GlossaryEvidenceType.OWNER_PIN,
                    unit_sequence=index,
                    source_block_id=f"workbench-block:{term.id}",
                    surface=GlossaryEvidenceSurface.BODY,
                )
            )
            entries.append(
                GlossaryEntry(
                    entry_id=f"workbench-entry:{term.id}",
                    category=(
                        GlossaryEntryCategory.NAME
                        if term.type == "name"
                        else GlossaryEntryCategory.TERM
                    ),
                    layer=GlossaryLayer.HARD,
                    status=GlossaryEntryStatus.OWNER_PINNED,
                    source_canonical=term.source,
                    target_canonical=term.target,
                    evidence_refs=(evidence_id,),
                    confidence=1.0,
                    strategy=GlossaryStrategy.TRANSLITERATE,
                )
            )
        return GlossarySnapshot(
            snapshot_id=f"workbench:{self.document.signature}",
            source_language=self.document.source_language,
            target_language=self.document.target_language,
            entries=tuple(entries),
            evidence=tuple(evidence),
        )

    def approve_current_glossary(self) -> None:
        """Record explicit local approval for this exact document/snapshot."""
        from translator_service.glossary_contracts import glossary_snapshot_signature
        from translator_service.manual_glossary_rehearsal import ManualGlossaryApproval

        snapshot = self.glossary_snapshot()
        self.manual_approval = ManualGlossaryApproval(
            document_ref=self.document.document_id,
            glossary_signature=glossary_snapshot_signature(snapshot),
        )
        self.local_check_result = None
        self.local_check_block_reason = None

    def clear_local_check_observation(self) -> None:
        self.local_check_result = None
        self.local_check_block_reason = None

    # --- mutating actions (all fail-closed at this slice) ----------------

    def append_term(
        self,
        *,
        source: str,
        target: str,
        type_: str,
        notes: str,
    ) -> tuple[Term | None, str | None]:
        """Append a term. Returns ``(term, None)`` or ``(None, reason)``.

        Reasons (all fail-closed at this slice, packet §5.2 mutation row):
        ``"not-wired"`` when the seam is unavailable, ``"invalid_type"``
        for an out-of-vocabulary term type, ``"empty_fields"`` when
        source or target is blank.
        """
        if self.last_error == "not-wired":
            return None, "not-wired"
        if self.approval_state in (ApprovalState.STALE, ApprovalState.UNAVAILABLE):
            return None, "not-wired"
        if not source.strip() or not target.strip():
            return None, "empty_fields"
        if type_ not in TERM_TYPES:
            return None, "invalid_type"
        term = Term.new(
            source=source.strip(),
            target=target.strip(),
            type_=type_,
            notes=notes.strip(),
        )
        self.terms[term.id] = term
        self.clear_local_check_observation()
        self.refresh_health_snapshot()
        self.refresh_approval_state()
        return term, None

    def replace_term(
        self,
        term_id: str,
        *,
        source: str,
        target: str,
        type_: str,
        notes: str,
    ) -> tuple[Term | None, str | None]:
        """Replace a term in place. Same fail-closed envelope as :meth:`append_term`."""
        if self.last_error == "not-wired":
            return None, "not-wired"
        if self.approval_state in (ApprovalState.STALE, ApprovalState.UNAVAILABLE):
            return None, "not-wired"
        existing = self.terms.get(term_id)
        if existing is None:
            return None, "not_found"
        if existing.status == TermStatus.LOCKED:
            return None, "locked"
        if not source.strip() or not target.strip():
            return None, "empty_fields"
        if type_ not in TERM_TYPES:
            return None, "invalid_type"
        existing.source = source.strip()
        existing.target = target.strip()
        existing.type = type_
        existing.notes = notes.strip()
        existing.last_edited_at = _utcnow()
        # Editing after approval demotes the term back to DRAFT and
        # refreshes the signature. This implements packet §5.2 row 2
        # ("term edited after approval → NOT_READY"): the approved
        # content is no longer the current content, so it does not
        # contribute to the approved/locked tally until re-accepted.
        if existing.status in (TermStatus.APPROVED, TermStatus.LOCKED):
            existing.status = TermStatus.DRAFT
            existing.locked = False
        existing.recompute_signature()
        self.clear_local_check_observation()
        self.refresh_health_snapshot()
        self.refresh_approval_state()
        return existing, None

    def accept_term(self, term_id: str) -> tuple[Term | None, str | None]:
        """Accept a candidate / draft as locally-approved.

        Allowed from :attr:`TermStatus.DRAFT` or
        :attr:`TermStatus.CONFLICT`. Locked rows cannot be accepted.
        """
        existing, reason = self._mutating_precheck(term_id)
        if existing is None:
            return None, reason
        if existing.status in (TermStatus.APPROVED, TermStatus.LOCKED):
            return None, "already_approved"
        return self._apply_term_status(existing, target=TermStatus.APPROVED)

    def reject_term(self, term_id: str) -> tuple[Term | None, str | None]:
        """Reject a term. Allowed from any non-locked status."""
        existing, reason = self._mutating_precheck(term_id)
        if existing is None:
            return None, reason
        if existing.status == TermStatus.LOCKED:
            return None, "locked"
        return self._apply_term_status(existing, target=TermStatus.REJECTED)

    def lock_term(self, term_id: str) -> tuple[Term | None, str | None]:
        """Lock an approved term. Allowed only from :attr:`TermStatus.APPROVED`."""
        existing, reason = self._mutating_precheck(term_id)
        if existing is None:
            return None, reason
        if existing.status != TermStatus.APPROVED:
            return None, "not_approvable"
        return self._apply_term_status(existing, target=TermStatus.LOCKED)

    def unlock_term(self, term_id: str) -> tuple[Term | None, str | None]:
        """Unlock a locked term back to approved.

        Allowed only from :attr:`TermStatus.LOCKED`.
        """
        existing, reason = self._mutating_precheck(term_id)
        if existing is None:
            return None, reason
        if existing.status != TermStatus.LOCKED:
            return None, "not_locked"
        return self._apply_term_status(existing, target=TermStatus.APPROVED)

    def lock_all_approved(self) -> list[str]:
        """Bulk-lock every approved term. Returns the list of locked term ids.

        Used by the toolbar ``Lock all approved`` button. Disabled in the
        UI when there are zero approved terms (packet §5.3 row 2), so
        this method is the corresponding controller-side primitive.
        """
        locked_ids: list[str] = []
        for term in list(self.terms.values()):
            if term.status == TermStatus.APPROVED:
                updated, _ = self.lock_term(term.id)
                if updated is not None:
                    locked_ids.append(updated.id)
        return locked_ids

    def _mutating_precheck(self, term_id: str) -> tuple[Term | None, str | None]:
        if self.last_error == "not-wired":
            return None, "not-wired"
        if self.approval_state in (ApprovalState.STALE, ApprovalState.UNAVAILABLE):
            return None, "not-wired"
        existing = self.terms.get(term_id)
        if existing is None:
            return None, "not_found"
        return existing, None

    def _apply_term_status(
        self, existing: Term, *, target: TermStatus
    ) -> tuple[Term | None, str | None]:
        existing.status = target
        existing.locked = target == TermStatus.LOCKED
        existing.last_edited_at = _utcnow()
        existing.recompute_signature()
        if target == TermStatus.REJECTED:
            # Reject clears the "approved+locked AND 0 conflict" gate.
            if self.approval_state == ApprovalState.READY and not any(
                t.status == TermStatus.LOCKED for t in self.terms.values()
            ):
                self.approval_state = ApprovalState.NOT_READY
        self.refresh_health_snapshot()
        self.refresh_approval_state()
        return existing, None

    def check_selected(
        self,
        term_ids: Iterable[str],
    ) -> dict[str, list[str]]:
        """Local-only check shape, mirrors ``translation_runner.preflight`` keys.

        Returns a dict of ``reason_code -> [term_ids]``. No runner call.
        See packet §6 ``Check selected terms`` row.
        """
        reasons: dict[str, list[str]] = {
            "source_term_or_alias_absent": [],
            "signature_mismatch": [],
            "empty_fields": [],
        }
        for term_id in term_ids:
            term = self.terms.get(term_id)
            if term is None:
                continue
            if not term.source.strip() or not term.target.strip():
                reasons["empty_fields"].append(term_id)
            if term.status == TermStatus.CONFLICT:
                reasons["source_term_or_alias_absent"].append(term_id)
            if not term.signature:
                reasons["signature_mismatch"].append(term_id)
        return {reason: ids for reason, ids in reasons.items() if ids}

    # --- fail-closed bookkeeping -----------------------------------------

    def mark_not_wired(self) -> None:
        """Set the seam-level fail-closed reason used by all mutating POSTs."""
        self.last_error = "not-wired"
        self.approval_state = ApprovalState.UNAVAILABLE

    def clear_error(self) -> None:
        """Clear ``last_error`` and recompute state from terms + document."""
        self.last_error = None
        self.refresh_health_snapshot()
        self.refresh_approval_state()


# ---------------------------------------------------------------------------
# Module-level guard + seed helpers
# ---------------------------------------------------------------------------


#: Module-level in-process dict (packet §5.2). NOT persisted, NOT cached.
#: This is a deliberate ephemeral rehearsal store; the gpt-coder follow-up
#: card must define the real adapter (packet §6 follow-up column).
WORKBENCH_SESSION_STATE: dict[str, WorkbenchSessionState] = {}


def _empty_health_snapshot() -> dict[str, int]:
    return {
        "total": 0,
        "approved": 0,
        "locked": 0,
        "pending": 0,
        "rejected": 0,
        "conflict": 0,
        "draft": 0,
    }


def _new_session_id() -> str:
    return secrets.token_urlsafe(24)


def seed_workbench_session(
    *,
    document_id: str | None,
    session_id: str | None = None,
) -> WorkbenchSessionState:
    """Seed (or reset) the rehearsal state for ``session_id``.

    Empty document (``None``) is allowed for the ``/workbench/select``
    screen; in that case the approval state is :attr:`ApprovalState.NOT_READY`
    but the helper rail is hidden (packet §5.3 row 1).
    """
    sid = session_id or _new_session_id()
    if document_id is None:
        # Placeholder document context — not injected yet.
        document = DocumentContext(
            document_id="",
            filename="",
            format="",
            source_language="",
            target_language="",
            signature="",
            provided_at=_utcnow(),
        )
        state = WorkbenchSessionState(
            session_id=sid,
            document=document,
            initial_document_signature="",
        )
        state.approval_state = ApprovalState.NOT_READY
        WORKBENCH_SESSION_STATE[sid] = state
        return state
    document = DocumentContext.from_query(document_id=document_id)
    state = WorkbenchSessionState(
        session_id=sid,
        document=document,
        initial_document_signature=document.signature,
    )
    state.refresh_health_snapshot()
    state.refresh_approval_state()
    WORKBENCH_SESSION_STATE[sid] = state
    return state


def get_or_seed_workbench_session(
    *,
    document_id: str | None,
    session_id: str | None,
) -> WorkbenchSessionState:
    """Look up the session by id, or seed a fresh one.

    On reload (no ``session_id``), the state is reseeded. This is the
    explicit reset-on-reload behaviour from packet §5.2 row 7.
    """
    if session_id and session_id in WORKBENCH_SESSION_STATE:
        return WORKBENCH_SESSION_STATE[session_id]
    return seed_workbench_session(document_id=document_id, session_id=session_id)


def reset_workbench_session(session_id: str) -> None:
    """Drop a session from the in-process dict (helper for tests)."""
    WORKBENCH_SESSION_STATE.pop(session_id, None)


def empty_workbench_session() -> WorkbenchSessionState:
    """Return a fresh, no-document session state for non-Glossary screens.

    Used by the Workbench view layer to render placeholders that need a
    state object for the shared header/nav shell without touching the
    global :data:`WORKBENCH_SESSION_STATE`.
    """
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    doc = DocumentContext(
        document_id="",
        filename="",
        format="",
        source_language="",
        target_language="",
        signature="",
        provided_at=now,
    )
    return WorkbenchSessionState(
        session_id="",
        document=doc,
        initial_document_signature="",
        approval_state=ApprovalState.NOT_READY,
    )


__all__ = [
    "ApprovalState",
    "DocumentContext",
    "TERM_TYPES",
    "Term",
    "TermStatus",
    "WORKBENCH_SESSION_STATE",
    "WorkbenchSessionState",
    "empty_workbench_session",
    "get_or_seed_workbench_session",
    "reset_workbench_session",
    "seed_workbench_session",
]
