"""Pure-Python tests for the Workbench glossary session state.

These tests do not import FastAPI or any HTTP stack. They exercise the
state machine defined in ``workbench_session_state.py`` against the
packet §5.2 transition table:

* empty seed → ``READY`` (no terms yet, READY-by-default per row 7)
* append with signature recompute
* lock-then-edit-blocked
* conflict insert
* stale detection (signature drift)
* unavailability short-circuit
* session-id rotation reseeds (reset on reload)
"""

from __future__ import annotations

import unittest

from translator_service.admin.workbench_session_state import (
    TERM_TYPES,
    WORKBENCH_SESSION_STATE,
    ApprovalState,
    DocumentContext,
    Term,
    TermStatus,
    WorkbenchSessionState,
    empty_workbench_session,
    get_or_seed_workbench_session,
    reset_workbench_session,
    seed_workbench_session,
)


def _fresh_state() -> WorkbenchSessionState:
    return seed_workbench_session(document_id="doc-test")


def _wipe_globals() -> None:
    WORKBENCH_SESSION_STATE.clear()


def _seed_locked(state: WorkbenchSessionState) -> Term:
    """Append a draft, accept it (→ APPROVED), then lock it (→ LOCKED)."""
    term, _ = state.append_term(
        source="Hobbit",
        target="Хобіт",
        type_="term",
        notes="",
    )
    assert term is not None
    state.accept_term(term.id)
    state.lock_term(term.id)
    return state.terms[term.id]


class WorkbenchSessionStateSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_empty_seed_uses_ready_by_default(self) -> None:
        state = _fresh_state()
        self.assertEqual(state.approval_state, ApprovalState.READY)
        self.assertEqual(state.health_snapshot["total"], 0)
        self.assertEqual(state.health_snapshot["locked"], 0)
        self.assertEqual(state.terms, {})
        # Seed populates initial_document_signature from document.signature.
        self.assertEqual(
            state.initial_document_signature, state.document.signature
        )

    def test_no_document_seed_is_not_ready(self) -> None:
        state = seed_workbench_session(document_id=None)
        self.assertEqual(state.approval_state, ApprovalState.NOT_READY)

    def test_document_signature_is_stable_for_same_inputs(self) -> None:
        a = DocumentContext.from_query(document_id="doc-1")
        b = DocumentContext.from_query(document_id="doc-1")
        self.assertEqual(a.signature, b.signature)

    def test_document_signature_changes_with_format(self) -> None:
        a = DocumentContext.from_query(document_id="doc-1")
        b = DocumentContext.from_query(document_id="doc-1", fmt="docx")
        self.assertNotEqual(a.signature, b.signature)


class WorkbenchSessionStateAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_append_term_assigns_uuid_and_signature(self) -> None:
        term, reason = self.state.append_term(
            source="Hobbit",
            target="Хобіт",
            type_="term",
            notes="",
        )
        self.assertIsNone(reason)
        self.assertIsNotNone(term)
        assert term is not None
        self.assertEqual(len(term.id), 32)  # uuid4 hex
        self.assertEqual(len(term.signature), 16)
        self.assertEqual(term.status, TermStatus.DRAFT)
        self.assertFalse(term.locked)
        self.assertEqual(self.state.health_snapshot["total"], 1)
        self.assertEqual(self.state.health_snapshot["draft"], 1)

    def test_append_term_recomputes_signature_on_status_change(self) -> None:
        term, _ = self.state.append_term(
            source="Hobbit",
            target="Хобіт",
            type_="term",
            notes="",
        )
        assert term is not None
        original = term.signature
        self.state.accept_term(term.id)
        self.assertNotEqual(self.state.terms[term.id].signature, original)

    def test_append_term_rejects_blank_source(self) -> None:
        term, reason = self.state.append_term(
            source="  ",
            target="X",
            type_="term",
            notes="",
        )
        self.assertIsNone(term)
        self.assertEqual(reason, "empty_fields")

    def test_append_term_rejects_blank_target(self) -> None:
        term, reason = self.state.append_term(
            source="X",
            target="",
            type_="term",
            notes="",
        )
        self.assertEqual(reason, "empty_fields")

    def test_append_term_rejects_unknown_type(self) -> None:
        term, reason = self.state.append_term(
            source="X",
            target="Y",
            type_="not-a-type",
            notes="",
        )
        self.assertEqual(reason, "invalid_type")
        self.assertNotIn("not-a-type", TERM_TYPES)

    def test_append_moves_ready_to_not_ready(self) -> None:
        self.assertEqual(self.state.approval_state, ApprovalState.READY)
        self.state.append_term(
            source="A",
            target="B",
            type_="term",
            notes="",
        )
        # No approved term yet → NOT_READY.
        self.assertEqual(self.state.approval_state, ApprovalState.NOT_READY)


class WorkbenchSessionStateLockUnlockTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_lock_then_edit_is_blocked(self) -> None:
        term = _seed_locked(self.state)
        self.assertTrue(term.locked)
        edited, reason = self.state.replace_term(
            term.id,
            source="Hobbits",
            target="Хобіти",
            type_="term",
            notes="",
        )
        self.assertIsNone(edited)
        self.assertEqual(reason, "locked")

    def test_unlock_returns_to_approved(self) -> None:
        term = _seed_locked(self.state)
        updated, reason = self.state.unlock_term(term.id)
        self.assertIsNone(reason)
        assert updated is not None
        self.assertFalse(updated.locked)
        self.assertEqual(updated.status, TermStatus.APPROVED)

    def test_unlocking_last_locked_term_keeps_state_ready(self) -> None:
        # Packet §5.2 transitions: unlocking returns the term to APPROVED,
        # which is still a positive signal. The §5.4 helper copy treats
        # approved-only as "ready to lock"; only losing all approved
        # terms (or introducing conflicts) moves out of READY.
        _seed_locked(self.state)
        # 1 approved+locked → READY.
        self.assertEqual(self.state.approval_state, ApprovalState.READY)
        term = next(
            t for t in self.state.terms.values() if t.status == TermStatus.LOCKED
        )
        self.state.unlock_term(term.id)
        # Still 1 approved term (now unlocked) → READY.
        self.assertEqual(self.state.approval_state, ApprovalState.READY)

    def test_lock_all_approved_locks_every_approved_term(self) -> None:
        # Seed two approved terms (not yet locked).
        a, _ = self.state.append_term(source="A", target="B", type_="term", notes="")
        b, _ = self.state.append_term(source="C", target="D", type_="term", notes="")
        assert a is not None and b is not None
        self.state.accept_term(a.id)
        self.state.accept_term(b.id)
        locked_ids = self.state.lock_all_approved()
        self.assertEqual(set(locked_ids), {a.id, b.id})
        for tid in (a.id, b.id):
            self.assertEqual(self.state.terms[tid].status, TermStatus.LOCKED)

    def test_lock_all_approved_is_noop_when_zero_approved(self) -> None:
        self.state.append_term(source="A", target="B", type_="term", notes="")
        self.assertEqual(self.state.lock_all_approved(), [])

    def test_accept_term_rejects_already_approved(self) -> None:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        self.state.accept_term(term.id)
        again, reason = self.state.accept_term(term.id)
        self.assertIsNone(again)
        self.assertEqual(reason, "already_approved")

    def test_lock_term_rejects_non_approved(self) -> None:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        out, reason = self.state.lock_term(term.id)
        self.assertIsNone(out)
        self.assertEqual(reason, "not_approvable")

    def test_reject_term_rejects_locked(self) -> None:
        term = _seed_locked(self.state)
        out, reason = self.state.reject_term(term.id)
        self.assertIsNone(out)
        self.assertEqual(reason, "locked")


class WorkbenchSessionStateConflictTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_conflict_status_moves_state_to_conflict(self) -> None:
        term, _ = self.state.append_term(
            source="Hobbit",
            target="Хобіт",
            type_="term",
            notes="",
        )
        assert term is not None
        # Force a CONFLICT status via dataclass — the matrix does not allow
        # a UI button to enter CONFLICT directly; this tests the
        # refresh_approval_state priority for CONFLICT > READY.
        self.state.terms[term.id].status = TermStatus.CONFLICT
        self.state.refresh_health_snapshot()
        self.state.refresh_approval_state()
        self.assertEqual(self.state.approval_state, ApprovalState.CONFLICT)

    def test_health_snapshot_counts_conflicts(self) -> None:
        term, _ = self.state.append_term(
            source="A",
            target="B",
            type_="term",
            notes="",
        )
        assert term is not None
        self.state.terms[term.id].status = TermStatus.CONFLICT
        self.state.refresh_health_snapshot()
        self.assertEqual(self.state.health_snapshot["conflict"], 1)


class WorkbenchSessionStateStaleTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_signature_drift_moves_to_stale(self) -> None:
        original_signature = self.state.document.signature
        self.state.document = DocumentContext.from_query(
            document_id=self.state.document.document_id,
            fmt="docx",  # different format → different signature
        )
        self.assertNotEqual(self.state.document.signature, original_signature)
        self.assertTrue(self.state.is_stale())
        self.state.refresh_approval_state()
        self.assertEqual(self.state.approval_state, ApprovalState.STALE)


class WorkbenchSessionStateUnavailabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_mark_not_wired_short_circuits_to_unavailable(self) -> None:
        self.state.mark_not_wired()
        self.assertEqual(self.state.approval_state, ApprovalState.UNAVAILABLE)
        # All mutating POSTs must short-circuit.
        term, reason = self.state.append_term(
            source="X", target="Y", type_="term", notes=""
        )
        self.assertIsNone(term)
        self.assertEqual(reason, "not-wired")

    def test_clear_error_returns_state_to_normal(self) -> None:
        self.state.mark_not_wired()
        self.state.clear_error()
        self.assertIsNone(self.state.last_error)
        # After clear, refresh_approval_state picks READY for empty seed
        # (packet §5.2 row 7).
        self.assertEqual(self.state.approval_state, ApprovalState.READY)


class WorkbenchSessionStateCheckSelectedTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_check_selected_returns_local_only_preflight_shape(self) -> None:
        term, _ = self.state.append_term(
            source="Hobbit",
            target="Хобіт",
            type_="term",
            notes="",
        )
        assert term is not None
        self.state.terms[term.id].status = TermStatus.CONFLICT
        report = self.state.check_selected([term.id, "missing-id"])
        # Conflict term trips the preflight-shape key.
        self.assertIn("source_term_or_alias_absent", report)
        self.assertIn(term.id, report["source_term_or_alias_absent"])
        # Unknown id is silently dropped (UI is local-only, no I/O).
        self.assertNotIn("missing-id", report["source_term_or_alias_absent"])


class WorkbenchSessionStateAppendEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_append_blocked_when_not_wired(self) -> None:
        self.state.mark_not_wired()
        term, reason = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        self.assertIsNone(term)
        self.assertEqual(reason, "not-wired")

    def test_append_blocked_when_stale(self) -> None:
        self.state.document = DocumentContext.from_query(
            document_id=self.state.document.document_id, fmt="docx"
        )
        self.state.refresh_approval_state()
        self.assertEqual(self.state.approval_state, ApprovalState.STALE)
        term, reason = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        self.assertIsNone(term)
        self.assertEqual(reason, "not-wired")

    def test_append_blank_source_or_target_branch(self) -> None:
        # Both empty fields are tested elsewhere; this asserts the path
        # that returns "empty_fields" is reachable with mixed input.
        term, reason = self.state.append_term(
            source="   ", target="\t\n", type_="term", notes=""
        )
        self.assertIsNone(term)
        self.assertEqual(reason, "empty_fields")


class WorkbenchSessionStateReplaceEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_replace_blocked_when_not_wired(self) -> None:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        self.state.mark_not_wired()
        out, reason = self.state.replace_term(
            term.id, source="X", target="Y", type_="term", notes=""
        )
        self.assertIsNone(out)
        self.assertEqual(reason, "not-wired")

    def test_replace_blocked_when_stale(self) -> None:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        self.state.document = DocumentContext.from_query(
            document_id=self.state.document.document_id, fmt="epub"
        )
        self.state.refresh_approval_state()
        out, reason = self.state.replace_term(
            term.id, source="X", target="Y", type_="term", notes=""
        )
        self.assertIsNone(out)
        self.assertEqual(reason, "not-wired")

    def test_replace_unknown_term(self) -> None:
        out, reason = self.state.replace_term(
            "missing-id", source="X", target="Y", type_="term", notes=""
        )
        self.assertIsNone(out)
        self.assertEqual(reason, "not_found")

    def test_replace_rejects_blank_target(self) -> None:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        out, reason = self.state.replace_term(
            term.id, source="X", target="  ", type_="term", notes=""
        )
        self.assertEqual(reason, "empty_fields")
        self.assertIsNone(out)

    def test_replace_rejects_invalid_type(self) -> None:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        out, reason = self.state.replace_term(
            term.id, source="X", target="Y", type_="bogus", notes=""
        )
        self.assertEqual(reason, "invalid_type")

    def test_replace_after_approval_moves_ready_to_not_ready(self) -> None:
        # Seed an APPROVED term so we are in READY.
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        self.state.accept_term(term.id)
        self.assertEqual(self.state.approval_state, ApprovalState.READY)
        # Editing after approval drops back to NOT_READY.
        out, reason = self.state.replace_term(
            term.id, source="A", target="B!", type_="term", notes="clarify"
        )
        self.assertIsNone(reason)
        self.assertEqual(self.state.approval_state, ApprovalState.NOT_READY)


class WorkbenchSessionStateTransitionEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def _add_draft(self) -> Term:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        return term

    def test_accept_unknown_term(self) -> None:
        out, reason = self.state.accept_term("missing-id")
        self.assertIsNone(out)
        self.assertEqual(reason, "not_found")

    def test_accept_blocked_when_not_wired(self) -> None:
        term = self._add_draft()
        self.state.mark_not_wired()
        out, reason = self.state.accept_term(term.id)
        self.assertEqual(reason, "not-wired")

    def test_accept_blocked_when_stale(self) -> None:
        term = self._add_draft()
        self.state.document = DocumentContext.from_query(
            document_id=self.state.document.document_id, fmt="epub"
        )
        self.state.refresh_approval_state()
        out, reason = self.state.accept_term(term.id)
        self.assertEqual(reason, "not-wired")

    def test_reject_unknown_term(self) -> None:
        out, reason = self.state.reject_term("missing-id")
        self.assertEqual(reason, "not_found")

    def test_reject_blocked_when_not_wired(self) -> None:
        term = self._add_draft()
        self.state.mark_not_wired()
        out, reason = self.state.reject_term(term.id)
        self.assertEqual(reason, "not-wired")

    def test_reject_draft_term_moves_to_rejected(self) -> None:
        term = self._add_draft()
        out, reason = self.state.reject_term(term.id)
        self.assertIsNone(reason)
        assert out is not None
        self.assertEqual(out.status, TermStatus.REJECTED)

    def test_reject_already_rejected_preserves_local_state(self) -> None:
        term = self._add_draft()
        self.state.reject_term(term.id)
        self.state.approve_current_glossary()
        approval = self.state.manual_approval
        observation = object()
        self.state.local_check_result = observation
        self.state.local_check_block_reason = "local-check-blocked"
        rejected = self.state.terms[term.id]
        last_edited_at = rejected.last_edited_at
        signature = rejected.signature

        updated, reason = self.state.reject_term(term.id)

        self.assertIsNone(updated)
        self.assertEqual(reason, "already_rejected")
        self.assertEqual(rejected.status, TermStatus.REJECTED)
        self.assertEqual(rejected.last_edited_at, last_edited_at)
        self.assertEqual(rejected.signature, signature)
        self.assertIs(self.state.manual_approval, approval)
        self.assertIs(self.state.local_check_result, observation)
        self.assertEqual(self.state.local_check_block_reason, "local-check-blocked")

    def test_reject_from_ready_with_no_locked_moves_to_not_ready(self) -> None:
        # Seed an approved-only term (no locked) so we are in READY but
        # the post-reject rule applies.
        term = self._add_draft()
        self.state.accept_term(term.id)
        self.assertEqual(self.state.approval_state, ApprovalState.READY)
        # Reject it: no more approved terms AND no locked terms.
        self.state.reject_term(term.id)
        self.assertEqual(self.state.approval_state, ApprovalState.NOT_READY)

    def test_lock_unknown_term(self) -> None:
        out, reason = self.state.lock_term("missing-id")
        self.assertEqual(reason, "not_found")

    def test_lock_blocked_when_not_wired(self) -> None:
        term = self._add_draft()
        self.state.accept_term(term.id)
        self.state.mark_not_wired()
        out, reason = self.state.lock_term(term.id)
        self.assertEqual(reason, "not-wired")

    def test_unlock_unknown_term(self) -> None:
        out, reason = self.state.unlock_term("missing-id")
        self.assertEqual(reason, "not_found")

    def test_unlock_non_locked_term(self) -> None:
        term = self._add_draft()
        out, reason = self.state.unlock_term(term.id)
        self.assertEqual(reason, "not_locked")

    def test_successful_status_transition_invalidates_local_approval_and_check(
        self,
    ) -> None:
        cases = (
            ("accept", lambda term: self.state.accept_term(term.id)),
            ("reject", lambda term: self.state.reject_term(term.id)),
            ("lock", lambda term: self.state.lock_term(term.id)),
            ("unlock", lambda term: self.state.unlock_term(term.id)),
        )
        for label, transition in cases:
            with self.subTest(label=label):
                self.state = _fresh_state()
                term = self._add_draft()
                if label in {"lock", "unlock"}:
                    self.state.accept_term(term.id)
                if label == "unlock":
                    self.state.lock_term(term.id)
                self.state.approve_current_glossary()
                self.state.local_check_result = object()
                self.state.local_check_block_reason = "local-check-blocked"

                updated, reason = transition(term)

                self.assertIsNotNone(updated)
                self.assertIsNone(reason)
                self.assertIsNone(self.state.manual_approval)
                self.assertIsNone(self.state.local_check_result)
                self.assertIsNone(self.state.local_check_block_reason)

    def test_bulk_lock_invalidates_local_approval_and_check(self) -> None:
        first = self._add_draft()
        second, reason = self.state.append_term(
            source="C", target="D", type_="term", notes=""
        )
        assert second is not None
        self.assertIsNone(reason)
        self.state.accept_term(first.id)
        self.state.accept_term(second.id)
        self.state.approve_current_glossary()
        self.state.local_check_result = object()
        self.state.local_check_block_reason = "local-check-blocked"

        locked_ids = self.state.lock_all_approved()

        self.assertEqual(set(locked_ids), {first.id, second.id})
        self.assertIsNone(self.state.manual_approval)
        self.assertIsNone(self.state.local_check_result)
        self.assertIsNone(self.state.local_check_block_reason)

    def test_failed_status_transition_preserves_local_approval_and_check(self) -> None:
        term = self._add_draft()
        self.state.accept_term(term.id)
        self.state.approve_current_glossary()
        observation = object()
        self.state.local_check_result = observation
        self.state.local_check_block_reason = "local-check-blocked"

        updated, reason = self.state.accept_term(term.id)

        self.assertIsNone(updated)
        self.assertEqual(reason, "already_approved")
        self.assertIsNotNone(self.state.manual_approval)
        self.assertIs(self.state.local_check_result, observation)
        self.assertEqual(self.state.local_check_block_reason, "local-check-blocked")


class WorkbenchSessionStateCheckSelectedBranchesTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_check_selected_flags_empty_fields(self) -> None:
        # Append a term, then force an empty field by mutating the term.
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        self.state.terms[term.id].source = "   "
        report = self.state.check_selected([term.id])
        self.assertIn("empty_fields", report)
        self.assertIn(term.id, report["empty_fields"])

    def test_check_selected_flags_signature_mismatch(self) -> None:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        self.state.terms[term.id].signature = ""
        report = self.state.check_selected([term.id])
        self.assertIn("signature_mismatch", report)
        self.assertIn(term.id, report["signature_mismatch"])

    def test_check_selected_skips_unknown_ids_silently(self) -> None:
        # Unknown ids must not raise; no entry in any bucket.
        report = self.state.check_selected(["nope-1", "nope-2"])
        self.assertEqual(report, {})


class WorkbenchSessionStateLockAllBranchesTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_lock_all_approved_skips_draft_terms(self) -> None:
        # Only draft and locked terms present; nothing to lock.
        a, _ = self.state.append_term(source="A", target="B", type_="term", notes="")
        b, _ = self.state.append_term(source="C", target="D", type_="term", notes="")
        assert a is not None and b is not None
        # No accept; both stay DRAFT.
        self.assertEqual(self.state.lock_all_approved(), [])

    def test_lock_all_approved_skips_locked_terms(self) -> None:
        # Seed one approved and one already-locked; lock_all should only
        # touch the approved one.
        a, _ = self.state.append_term(source="A", target="B", type_="term", notes="")
        b, _ = self.state.append_term(source="C", target="D", type_="term", notes="")
        assert a is not None and b is not None
        self.state.accept_term(a.id)
        self.state.accept_term(b.id)
        self.state.lock_term(b.id)
        locked = self.state.lock_all_approved()
        self.assertEqual(locked, [a.id])


class WorkbenchEmptySessionTests(unittest.TestCase):
    def test_empty_workbench_session_is_not_registered(self) -> None:
        before = set(WORKBENCH_SESSION_STATE)
        state = empty_workbench_session()
        after = set(WORKBENCH_SESSION_STATE)
        self.assertEqual(before, after)
        self.assertEqual(state.session_id, "")
        self.assertEqual(state.document.document_id, "")
        self.assertEqual(state.approval_state, ApprovalState.NOT_READY)


class WorkbenchSessionRotationTests(unittest.TestCase):
    def setUp(self) -> None:
        _wipe_globals()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_get_or_seed_returns_existing_session(self) -> None:
        seeded = seed_workbench_session(document_id="doc-1")
        seeded.append_term(source="A", target="B", type_="term", notes="")
        again = get_or_seed_workbench_session(
            document_id="doc-1", session_id=seeded.session_id
        )
        self.assertIs(again, seeded)
        self.assertEqual(again.health_snapshot["total"], 1)

    def test_rotation_with_new_session_id_reseeds_empty(self) -> None:
        seeded = seed_workbench_session(document_id="doc-1")
        seeded.append_term(source="A", target="B", type_="term", notes="")
        fresh = get_or_seed_workbench_session(
            document_id="doc-1", session_id=None
        )
        self.assertIsNot(fresh, seeded)
        self.assertEqual(fresh.health_snapshot["total"], 0)

    def test_reset_workbench_session_drops_entry(self) -> None:
        seeded = seed_workbench_session(document_id="doc-1")
        reset_workbench_session(seeded.session_id)
        self.assertNotIn(seeded.session_id, WORKBENCH_SESSION_STATE)


class WorkbenchSessionStateApprovalStatePriorityTests(unittest.TestCase):
    """Pin the priority order from packet §5.2 transitions.

    Priority (highest first): UNAVAILABLE > STALE > CONFLICT > READY/NOT_READY.
    """

    def setUp(self) -> None:
        _wipe_globals()
        self.state = _fresh_state()

    def tearDown(self) -> None:
        _wipe_globals()

    def test_unavailable_beats_stale(self) -> None:
        self.state.document = DocumentContext.from_query(
            document_id=self.state.document.document_id,
            fmt="docx",
        )
        self.state.mark_not_wired()
        self.state.refresh_approval_state()
        self.assertEqual(self.state.approval_state, ApprovalState.UNAVAILABLE)

    def test_stale_beats_conflict(self) -> None:
        term, _ = self.state.append_term(
            source="A", target="B", type_="term", notes=""
        )
        assert term is not None
        self.state.terms[term.id].status = TermStatus.CONFLICT
        self.state.document = DocumentContext.from_query(
            document_id=self.state.document.document_id,
            fmt="epub",
        )
        self.state.refresh_health_snapshot()
        self.state.refresh_approval_state()
        self.assertEqual(self.state.approval_state, ApprovalState.STALE)

    def test_conflict_beats_ready(self) -> None:
        term = _seed_locked(self.state)
        # 1 approved+locked → READY.
        self.assertEqual(self.state.approval_state, ApprovalState.READY)
        # Now introduce a conflict term.
        self.state.terms[term.id].status = TermStatus.CONFLICT
        self.state.refresh_health_snapshot()
        self.state.refresh_approval_state()
        self.assertEqual(self.state.approval_state, ApprovalState.CONFLICT)


if __name__ == "__main__":
    unittest.main()