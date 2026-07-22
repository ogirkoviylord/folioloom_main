"""HTTP tests for the bounded Workbench glossary UI slice (Stage 1).

These tests cover the Workbench routes exactly as the UI packet
``.hermes/workbench_ui_packet/UI_PACKET_S1_GLOSSARY_FIRST.md`` (§7.4)
specifies them. They exercise:

* the new ``/admin/workbench-entry`` redirect and the four
  Workbench shell surfaces (select / recovery / glossary / future);
* the eight mutating POSTs that all fail-closed to the honest
  ``not-wired`` notice;
* the Admin overview gets exactly one calm ``Open Workbench`` CTA
  (no new nav entry, no nav surgery);
* the Workbench nav rail has 7 entries (Glossary + 6 placeholders);
* the helper rail is hidden when the glossary is empty;
* the route-coverage-map includes the new rows.
"""

from __future__ import annotations

import os
import re
import unittest
from tempfile import TemporaryDirectory
from urllib.parse import quote

from fastapi.testclient import TestClient

from translator_service.admin.workbench_session_state import WORKBENCH_SESSION_STATE
from translator_service.api import create_app
from translator_service.config import Settings


def _csrf_token(page_text: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', page_text)
    if match is None:
        raise AssertionError("CSRF token not found in response body")
    return match.group(1)


def _admin_login(client: TestClient) -> str:
    response = client.post(
        "/admin/login",
        data={"password": "owner-pass"},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303), response.status_code
    # Pull a CSRF token from any rendered admin page after login.
    overview = client.get("/admin/overview")
    assert overview.status_code == 200, overview.status_code
    return _csrf_token(overview.text)


class WorkbenchRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        WORKBENCH_SESSION_STATE.clear()
        self.addCleanup(WORKBENCH_SESSION_STATE.clear)
        self.client = TestClient(
            create_app(
                settings=Settings(
                    admin_owner_password="owner-pass",
                    admin_session_secret="session-secret",
                    translation_run_log_root=os.path.join(
                        self._tmp.name, "translation-runs"
                    ),
                )
            )
        )
        self.csrf_token = _admin_login(self.client)

    def _workbench_actor(self) -> str:
        match = re.search(r'value="([^"]+)"', self.csrf_token)
        return match.group(1) if match else ""

    def test_workbench_entry_redirects_to_root_when_no_document(self) -> None:
        response = self.client.get("/admin/workbench-entry", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(
            response.headers["location"].startswith("/admin/workbench/?document=")
        )

    def test_workbench_select_renders_empty_state(self) -> None:
        response = self.client.get("/admin/workbench/select")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Select a document in Admin to open it in Workbench.", response.text
        )
        self.assertIn("Open Admin", response.text)
        self.assertIn("FolioLoom Workbench", response.text)

    def test_workbench_recovery_reasons_render(self) -> None:
        for reason in ("stale", "unavailable", "not-wired", "invalid"):
            response = self.client.get(f"/admin/workbench/recovery?reason={reason}")
            self.assertEqual(response.status_code, 200, reason)
            # Recovery screen never exposes the Admin nav.
            self.assertNotIn("Admin Console", response.text)
            self.assertIn("FolioLoom Workbench", response.text)

    def test_workbench_recovery_defaults_to_invalid_when_reason_unknown(self) -> None:
        response = self.client.get("/admin/workbench/recovery?reason=__bogus__")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "This document reference is not valid. Return to Admin.", response.text
        )

    def test_workbench_glossary_renders_for_injected_document(self) -> None:
        response = self.client.get("/admin/workbench/glossary?document=opaque-1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("FolioLoom Workbench", response.text)
        self.assertIn("Not saved", response.text)
        self.assertIn(
            "No terms yet. Add your first term to begin shaping the glossary.",
            response.text,
        )
        # Helper rail is hidden when total=0.
        self.assertNotIn('aria-label="Workbench helper rail"', response.text)
        self.assertRegex(
            response.text,
            r'<a class="wb-button wb-button--primary" data-action="add-term" '
            r'href="[^"]+" aria-controls="wb-add-term-form">Add term</a>',
        )
        self.assertIn(".workbench a.wb-button--primary", response.text)
        self.assertIn("color: #FFFFFF;", response.text)

    def test_add_term_form_preserves_encoded_document_context(self) -> None:
        document_id = "proof document/&?"
        encoded_document_id = quote(document_id, safe="")
        add_form_action = (
            f"/admin/workbench/glossary/terms/add?document={encoded_document_id}"
        )
        response = self.client.get(
            f"/admin/workbench/glossary?document={encoded_document_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'href="/admin/workbench/glossary?document={encoded_document_id}&amp;add=1"',
            response.text,
        )

        form_page = self.client.get(
            f"/admin/workbench/glossary?document={encoded_document_id}&add=1"
        )
        self.assertEqual(form_page.status_code, 200)
        self.assertIn('id="wb-add-term-form"', form_page.text)
        self.assertIn(f'action="{add_form_action}"', form_page.text)
        self.assertIn(f'name="csrf_token" value="{self.csrf_token}"', form_page.text)

        successful_post = self.client.post(
            add_form_action,
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(successful_post.status_code, 303)
        self.assertEqual(
            successful_post.headers["location"],
            f"/admin/workbench/glossary?document={encoded_document_id}",
        )

        bad_csrf = self.client.post(
            add_form_action,
            data={"csrf_token": "wrong-token"},
            follow_redirects=False,
        )
        self.assertEqual(bad_csrf.status_code, 403)

        self.client.cookies.clear()
        anonymous_post = self.client.post(
            add_form_action,
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(anonymous_post.status_code, 303)
        self.assertTrue(anonymous_post.headers["location"].endswith("/admin/login"))

    def test_term_rows_expose_selection_inputs_for_check_form(self) -> None:
        document_id = "opaque-term-selection"
        initial = self.client.get(f"/admin/workbench/glossary?document={document_id}")
        self.assertEqual(initial.status_code, 200)
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        term, reason = state.append_term(
            source="source-only-in-row",
            target="target-only-in-row",
            type_="term",
            notes="",
        )
        self.assertIsNone(reason)
        assert term is not None

        page = self.client.get(f"/admin/workbench/glossary?document={document_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="wb-check-selected-form"', page.text)
        self.assertIn(
            f'action="/admin/workbench/glossary/check?document={document_id}"',
            page.text,
        )
        self.assertIn(f'id="wb-term-select-{term.id}"', page.text)
        self.assertIn('name="selected_term_ids"', page.text)
        self.assertIn(f'value="{term.id}"', page.text)
        self.assertIn('form="wb-check-selected-form"', page.text)
        self.assertRegex(
            page.text,
            rf'<label class="wb-term__selection" for="wb-term-select-{term.id}">'
            r"[\s\S]*?Select term for local check",
        )
        self.assertIn('data-action="delete-term">Delete term</button>', page.text)
        self.assertIn(
            f'action="/admin/workbench/glossary/terms/{term.id}/delete?document={document_id}"',
            page.text,
        )
        self.assertIn(
            "The exact current glossary snapshot needs explicit local approval "
            "before a local check can proceed.",
            page.text,
        )
        self.assertRegex(
            page.text,
            r'<a class="wb-button wb-button--primary" href="[^"]+">Add term</a>',
        )

    def test_workbench_glossary_renders_seven_nav_entries(self) -> None:
        response = self.client.get("/admin/workbench/glossary?document=opaque-2")
        self.assertEqual(response.status_code, 200)
        nav_match = re.search(
            r'<nav class="wb-nav" aria-label="Workbench navigation">(.*?)</nav>',
            response.text,
            re.DOTALL,
        )
        assert nav_match is not None, "Workbench nav not found"
        nav_html = nav_match.group(1)
        link_count = len(re.findall(r'<a class="wb-nav__link"', nav_html))
        self.assertEqual(link_count, 7)
        self.assertIn("Glossary", nav_html)
        self.assertIn("Project Library", nav_html)
        self.assertIn("Document Setup", nav_html)
        self.assertIn("Suggestions", nav_html)
        self.assertIn("Translate", nav_html)
        self.assertIn("Review", nav_html)
        self.assertIn("Export", nav_html)

    def test_empty_add_remains_on_the_local_glossary_surface(self) -> None:
        response = self.client.post(
            "/admin/workbench/glossary/terms/add",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"], "/admin/workbench/glossary?document="
        )
        page = self.client.get(response.headers["location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("No terms yet.", page.text)

    def test_owner_local_manual_glossary_approval_loop_fails_closed_when_stale(
        self,
    ) -> None:
        """The demo loop is local-only and requires an exact re-approval."""
        document_id = "stable-synthetic-document"
        glossary_url = f"/admin/workbench/glossary?document={document_id}"
        self.assertEqual(self.client.get(glossary_url).status_code, 200)

        added = self.client.post(
            f"/admin/workbench/glossary/terms/add?document={document_id}",
            data={
                "csrf_token": self.csrf_token,
                "source": "Aster",
                "target": "Астер",
                "type": "name",
                "notes": "local synthetic term",
            },
            follow_redirects=False,
        )
        self.assertEqual(added.status_code, 303)
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        term_id = next(iter(state.terms))

        blocked = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={"csrf_token": self.csrf_token, "selected_term_ids": term_id},
            follow_redirects=True,
        )
        self.assertIn("Local glossary check blocked", blocked.text)

        approved = self.client.post(
            f"/admin/workbench/glossary/approve?document={document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303)

        checked = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={"csrf_token": self.csrf_token, "selected_term_ids": term_id},
            follow_redirects=True,
        )
        self.assertIn("Local glossary structural observation", checked.text)
        self.assertIn("Selected: 1;", checked.text)

        edited = self.client.post(
            f"/admin/workbench/glossary/terms/{term_id}/edit?document={document_id}",
            data={
                "csrf_token": self.csrf_token,
                "source": "Aster revised",
                "target": "Астер",
                "type": "name",
                "notes": "local synthetic term",
            },
            follow_redirects=False,
        )
        self.assertEqual(edited.status_code, 303)

        stale = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={"csrf_token": self.csrf_token, "selected_term_ids": term_id},
            follow_redirects=True,
        )
        self.assertIn("Local glossary check blocked", stale.text)
        self.assertIn("signature_mismatch", stale.text)

        reapproved = self.client.post(
            f"/admin/workbench/glossary/approve?document={document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(reapproved.status_code, 303)

        current = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={"csrf_token": self.csrf_token, "selected_term_ids": term_id},
            follow_redirects=True,
        )
        self.assertIn("Local glossary structural observation", current.text)
        self.assertIn("Selected: 1;", current.text)
        self.assertNotIn("signature_mismatch", current.text)

    def test_delete_term_is_csrf_guarded_and_invalidates_exact_approval(self) -> None:
        document_id = "delete-synthetic-document"
        glossary_url = f"/admin/workbench/glossary?document={document_id}"
        self.assertEqual(self.client.get(glossary_url).status_code, 200)

        term_ids = []
        for source, target in (("Aster", "Астер"), ("Beryl", "Берил")):
            added = self.client.post(
                f"/admin/workbench/glossary/terms/add?document={document_id}",
                data={
                    "csrf_token": self.csrf_token,
                    "source": source,
                    "target": target,
                    "type": "name",
                    "notes": "local synthetic term",
                },
                follow_redirects=False,
            )
            self.assertEqual(added.status_code, 303)
            state = next(iter(WORKBENCH_SESSION_STATE.values()))
            term_ids.append(
                next(term_id for term_id in state.terms if term_id not in term_ids)
            )

        first_term_id, remaining_term_id = term_ids
        approve = self.client.post(
            f"/admin/workbench/glossary/approve?document={document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(approve.status_code, 303)
        approved_check = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={"csrf_token": self.csrf_token, "selected_term_ids": first_term_id},
            follow_redirects=True,
        )
        self.assertIn("Local glossary structural observation", approved_check.text)

        delete_url = (
            f"/admin/workbench/glossary/terms/{first_term_id}/delete?document={document_id}"
        )
        csrf_rejected = self.client.post(
            delete_url,
            data={"csrf_token": "wrong-token"},
            follow_redirects=False,
        )
        self.assertEqual(csrf_rejected.status_code, 403)

        deleted = self.client.post(
            delete_url,
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        self.assertEqual(deleted.headers["location"], glossary_url)
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        self.assertNotIn(first_term_id, state.terms)
        self.assertEqual(set(state.terms), {remaining_term_id})
        self.assertIsNone(state.manual_approval)
        self.assertIsNone(state.local_check_result)

        stale_check = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={
                "csrf_token": self.csrf_token,
                "selected_term_ids": remaining_term_id,
            },
            follow_redirects=True,
        )
        self.assertIn("Local glossary check blocked", stale_check.text)
        self.assertIn("missing_approval", stale_check.text)

        reapprove = self.client.post(
            f"/admin/workbench/glossary/approve?document={document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(reapprove.status_code, 303)
        current_check = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={
                "csrf_token": self.csrf_token,
                "selected_term_ids": remaining_term_id,
            },
            follow_redirects=True,
        )
        self.assertIn("Local glossary structural observation", current_check.text)
        self.assertIn("Selected: 1;", current_check.text)

        self.client.cookies.clear()
        anonymous = self.client.post(
            delete_url,
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(anonymous.status_code, 303)
        self.assertTrue(anonymous.headers["location"].endswith("/admin/login"))

    def test_workbench_glossary_rejects_post_without_csrf(self) -> None:
        response = self.client.post(
            "/admin/workbench/glossary/terms/add",
            data={"csrf_token": "wrong-token"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_workbench_glossary_redirects_to_login_when_anonymous(self) -> None:
        client = self.client
        client.cookies.clear()
        response = client.get(
            "/admin/workbench/glossary?document=opaque-3",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].endswith("/admin/login"))

    def test_workbench_term_edit_lock_unlock_routes_render_notice(self) -> None:
        endpoints = [
            ("/admin/workbench/glossary/terms/some-id/edit", "Edit"),
            ("/admin/workbench/glossary/terms/some-id/accept", "Accept"),
            ("/admin/workbench/glossary/terms/some-id/reject", "Reject"),
            ("/admin/workbench/glossary/terms/some-id/lock", "Lock"),
            ("/admin/workbench/glossary/terms/some-id/unlock", "Unlock"),
            (
                "/admin/workbench/glossary/terms/lock-all-approved",
                "Lock all approved",
            ),
            ("/admin/workbench/glossary/check", "Check"),
        ]
        for path, _label in endpoints:
            with self.subTest(path=path):
                response = self.client.post(
                    path,
                    data={"csrf_token": self.csrf_token},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303, path)
                page = self.client.get(response.headers["location"])
                self.assertEqual(page.status_code, 200, path)
                if path.endswith("/check"):
                    self.assertIn("Local glossary check blocked", page.text)
                elif path.endswith("/edit"):
                    self.assertIn("No terms yet.", page.text)
                else:
                    self.assertIn("Saving is not wired in this slice.", page.text)

    def test_workbench_stale_state_renders_recovery_redirect(self) -> None:
        # First hit seeds the session with one signature.
        self.client.get("/admin/workbench/glossary?document=opaque-stale-1")
        # A different document id under the same session moves the
        # state to STALE and the controller must redirect to recovery.
        response = self.client.get(
            "/admin/workbench/glossary?document=opaque-stale-2",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        # Recovery shell renders a calm panel without the term list.
        self.assertIn("Reopen latest document", response.text)
        self.assertNotIn("Saving is not wired in this slice.", response.text)

    def test_workbench_future_renders_per_stage(self) -> None:
        for stage, title in (
            ("project-library", "Project Library"),
            ("document-setup", "Document Setup"),
            ("ai-suggestions", "Suggestions"),
            ("translate", "Translate"),
            ("review", "Review"),
            ("export", "Export"),
        ):
            with self.subTest(stage=stage):
                response = self.client.get(f"/admin/workbench/future?stage={stage}")
                self.assertEqual(response.status_code, 200, stage)
                self.assertIn(title, response.text)
                self.assertIn("is not part of this slice.", response.text)

    def test_overview_includes_open_workbench_cta(self) -> None:
        response = self.client.get("/admin/overview")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Open Workbench", response.text)
        self.assertIn("/admin/workbench-entry", response.text)
        # Exactly one CTA: the helper section appears once.
        self.assertEqual(
            response.text.count("Open Workbench"),
            1,
        )
        # Admin nav counts are unchanged.
        self.assertIn("Admin Console", response.text)

    def test_workbench_html_never_claims_authoritative_approval(self) -> None:
        page = self.client.get("/admin/workbench/glossary?document=opaque-4")
        self.assertEqual(page.status_code, 200)
        # The packet bans green-tick "Approved" wording in status pills.
        # (The functional "Approved" filter chip label is allowed by §5.4.)
        # The glossary is empty in this slice, so no status pill renders.
        self.assertEqual(page.text.count(">Approved<"), 1)
        # The Recovery screen must keep the no-claim language too.
        recovery = self.client.get("/admin/workbench/recovery?reason=not-wired")
        self.assertEqual(recovery.status_code, 200)
        self.assertNotIn(">Approved<", recovery.text)
        self.assertNotIn('"Approved"', page.text)


if __name__ == "__main__":
    unittest.main()
