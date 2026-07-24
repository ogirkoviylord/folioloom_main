"""HTTP tests for the bounded Workbench glossary UI slice (Stage 1).

These tests cover the Workbench routes exactly as the UI packet
``.hermes/workbench_ui_packet/UI_PACKET_S1_GLOSSARY_FIRST.md`` (§7.4)
specifies them. They exercise:

* the new ``/admin/workbench-entry`` redirect and the four
  Workbench shell surfaces (select / recovery / glossary / future);
* the remaining unwired mutating POSTs that fail-closed to the honest
  ``not-wired`` notice, plus the two authenticated, CSRF-guarded glossary
  lock actions that make local, in-memory-only state changes;
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
from datetime import UTC, datetime, timedelta
from html import unescape
from tempfile import TemporaryDirectory
from unittest import mock
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
        helper_match = re.search(
            r'<aside class="wb-rail" aria-label="Workbench helper rail">(.*?)</aside>',
            page.text,
            re.DOTALL,
        )
        assert helper_match is not None, "Workbench helper rail not found"
        helper_html = helper_match.group(1)
        self.assertIn('data-workbench-not-ready-checklist="true"', helper_html)
        self.assertIn("Next step", helper_html)
        self.assertIn("Local approval", helper_html)
        self.assertIn("Missing", helper_html)
        self.assertIn(
            '<button type="submit" class="wb-button wb-button--primary" '
            'form="wb-check-selected-form" '
            'formaction="/admin/workbench/glossary/approve?document=opaque-term-selection">'
            "Approve current snapshot</button>",
            helper_html,
        )
        self.assertNotIn(
            '<a class="wb-button wb-button--primary" '
            'href="/admin/workbench/glossary">Add term</a>',
            helper_html,
        )

    def test_helper_approval_cta_submits_existing_approval_form(self) -> None:
        document_id = 'helper approval /&?"<'
        encoded_document_id = quote(document_id, safe="")
        expected_approval_action = (
            "/admin/workbench/glossary/approve?document="
            f"{encoded_document_id}"
        )
        self.assertEqual(
            self.client.get(
                f"/admin/workbench/glossary?document={encoded_document_id}"
            ).status_code,
            200,
        )
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        term, reason = state.append_term(
            source="Aster",
            target="Астер",
            type_="name",
            notes="local synthetic term",
        )
        self.assertIsNone(reason)
        self.assertIsNotNone(term)

        page = self.client.get(
            f"/admin/workbench/glossary?document={encoded_document_id}"
        )
        self.assertEqual(page.status_code, 200)
        toolbar_match = re.search(
            r'<form id="wb-check-selected-form" class="wb-toolbar" method="post"'
            r'[\s\S]*?</form>',
            page.text,
        )
        assert toolbar_match is not None, "Workbench check form not found"
        toolbar_html = toolbar_match.group(0)
        self.assertIn('method="post"', toolbar_html)
        self.assertIn(
            f'action="/admin/workbench/glossary/check?document={encoded_document_id}"',
            toolbar_html,
        )
        self.assertIn(
            f'name="csrf_token" value="{self.csrf_token}"',
            toolbar_html,
        )
        helper_match = re.search(
            r'<aside class="wb-rail" aria-label="Workbench helper rail">(.*?)</aside>',
            page.text,
            re.DOTALL,
        )
        assert helper_match is not None, "Workbench helper rail not found"
        escaped_approval_action = re.escape(expected_approval_action)
        self.assertRegex(
            helper_match.group(1),
            rf'<button type="submit" class="wb-button wb-button--primary" '
            rf'form="wb-check-selected-form" formaction="{escaped_approval_action}">'
            r'Approve current snapshot</button>',
        )

    def test_ready_helper_add_term_link_opens_document_scoped_form(self) -> None:
        document_id = 'ready helper /&?"<'
        encoded_document_id = quote(document_id, safe="")
        glossary_url = f"/admin/workbench/glossary?document={encoded_document_id}"
        self.assertEqual(self.client.get(glossary_url).status_code, 200)

        added = self.client.post(
            f"/admin/workbench/glossary/terms/add?document={encoded_document_id}",
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
        approved = self.client.post(
            f"/admin/workbench/glossary/approve?document={encoded_document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303)

        ready_page = self.client.get(glossary_url)
        self.assertEqual(ready_page.status_code, 200)
        helper_match = re.search(
            r'<aside class="wb-rail" aria-label="Workbench helper rail">(.*?)</aside>',
            ready_page.text,
            re.DOTALL,
        )
        assert helper_match is not None, "Workbench helper rail not found"
        add_link = re.search(
            r'<a class="wb-button wb-button--primary" href="([^"]+)">Add term</a>',
            helper_match.group(1),
        )
        assert add_link is not None, "Ready helper Add term link not found"

        form_page = self.client.get(unescape(add_link.group(1)))
        self.assertEqual(form_page.status_code, 200)
        self.assertIn('id="wb-add-term-form"', form_page.text)
        self.assertIn(
            f'action="/admin/workbench/glossary/terms/add?document={encoded_document_id}"',
            form_page.text,
        )

    def test_ready_helper_lock_all_submits_existing_toolbar_form(self) -> None:
        document_id = "ready helper lock"
        glossary_url = f"/admin/workbench/glossary?document={document_id}"
        self.assertEqual(self.client.get(glossary_url).status_code, 200)
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        term, reason = state.append_term(
            source="Aster",
            target="Астер",
            type_="name",
            notes="local synthetic term",
        )
        self.assertIsNone(reason)
        assert term is not None
        accepted, reason = state.accept_term(term.id)
        self.assertIsNone(reason)
        self.assertIsNotNone(accepted)

        ready_page = self.client.get(glossary_url)
        self.assertEqual(ready_page.status_code, 200)
        helper_match = re.search(
            r'<aside class="wb-rail" aria-label="Workbench helper rail">(.*?)</aside>',
            ready_page.text,
            re.DOTALL,
        )
        assert helper_match is not None, "Workbench helper rail not found"
        self.assertIn(
            '<button type="submit" class="wb-button wb-button--primary" '
            'form="wb-check-selected-form" '
            'formaction="/admin/workbench/glossary/terms/lock-all-approved'
            '?document=ready%20helper%20lock">Lock all approved</button>',
            helper_match.group(1),
        )

    def test_lock_all_approved_marks_local_terms_locked(self) -> None:
        """The visible local lock action must not claim a no-op succeeded."""
        document_id = "local-lock-state"
        glossary_url = f"/admin/workbench/glossary?document={document_id}"
        self.assertEqual(self.client.get(glossary_url).status_code, 200)
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        term, reason = state.append_term(
            source="Aster",
            target="Астер",
            type_="name",
            notes="local synthetic term",
        )
        self.assertIsNone(reason)
        assert term is not None
        approved, reason = state.accept_term(term.id)
        self.assertIsNone(reason)
        self.assertIsNotNone(approved)

        response = self.client.post(
            "/admin/workbench/glossary/terms/lock-all-approved"
            f"?document={document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(state.terms[term.id].status.value, "locked")
        self.assertIn('data-status="locked"', response.text)
        self.assertNotIn("Saving is not wired in this slice.", response.text)

    def test_lock_term_marks_only_that_local_term_locked(self) -> None:
        document_id = "local-single-lock-state"
        glossary_url = f"/admin/workbench/glossary?document={document_id}"
        self.assertEqual(self.client.get(glossary_url).status_code, 200)
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        selected_term, reason = state.append_term(
            source="Beryl",
            target="Берил",
            type_="name",
            notes="local synthetic term",
        )
        self.assertIsNone(reason)
        assert selected_term is not None
        untouched_term, reason = state.append_term(
            source="Citrine",
            target="Цитрин",
            type_="name",
            notes="another local synthetic term",
        )
        self.assertIsNone(reason)
        assert untouched_term is not None
        approved, reason = state.accept_term(selected_term.id)
        self.assertIsNone(reason)
        self.assertIsNotNone(approved)
        approved, reason = state.accept_term(untouched_term.id)
        self.assertIsNone(reason)
        self.assertIsNotNone(approved)

        response = self.client.post(
            f"/admin/workbench/glossary/terms/{selected_term.id}/lock",
            data={"csrf_token": self.csrf_token},
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(state.terms[selected_term.id].status.value, "locked")
        self.assertEqual(state.terms[untouched_term.id].status.value, "approved")
        self.assertIn(f'data-term-id="{selected_term.id}"', response.text)
        self.assertIn('data-status="locked"', response.text)

    def test_lock_routes_reject_csrf_and_anonymous_requests_without_mutation(
        self,
    ) -> None:
        document_id = "local-lock-guard-state"
        glossary_url = f"/admin/workbench/glossary?document={document_id}"
        self.assertEqual(self.client.get(glossary_url).status_code, 200)
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        first_term, reason = state.append_term(
            source="Garnet",
            target="Гранат",
            type_="name",
            notes="first local synthetic term",
        )
        self.assertIsNone(reason)
        assert first_term is not None
        second_term, reason = state.append_term(
            source="Jasper",
            target="Яшма",
            type_="name",
            notes="second local synthetic term",
        )
        self.assertIsNone(reason)
        assert second_term is not None
        for term in (first_term, second_term):
            approved, reason = state.accept_term(term.id)
            self.assertIsNone(reason)
            self.assertIsNotNone(approved)

        endpoints = (
            f"/admin/workbench/glossary/terms/{first_term.id}/lock?document={document_id}",
            "/admin/workbench/glossary/terms/lock-all-approved"
            f"?document={document_id}",
        )
        for endpoint in endpoints:
            rejected = self.client.post(
                endpoint,
                data={"csrf_token": "invalid-token"},
                follow_redirects=False,
            )
            self.assertEqual(rejected.status_code, 403, endpoint)
            self.assertEqual(state.terms[first_term.id].status.value, "approved")
            self.assertEqual(state.terms[second_term.id].status.value, "approved")

        self.client.cookies.clear()
        for endpoint in endpoints:
            rejected = self.client.post(
                endpoint,
                data={"csrf_token": self.csrf_token},
                follow_redirects=False,
            )
            self.assertEqual(rejected.status_code, 303, endpoint)
            self.assertTrue(rejected.headers["location"].endswith("/admin/login"))
            self.assertEqual(state.terms[first_term.id].status.value, "approved")
            self.assertEqual(state.terms[second_term.id].status.value, "approved")

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
        self.assertIn("missing_approval", stale.text)

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
        self.assertNotIn("missing_approval", current.text)

    def test_exact_snapshot_helper_requires_current_manual_approval(self) -> None:
        document_id = "helper-synthetic-document"
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

        approved = self.client.post(
            f"/admin/workbench/glossary/approve?document={document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303)
        approved_page = self.client.get(glossary_url)
        self.assertIn(
            "This exact current glossary snapshot has explicit local approval.",
            approved_page.text,
        )
        self.assertNotIn(
            'data-workbench-not-ready-checklist="true"', approved_page.text
        )
        approved_helper = re.search(
            r'<aside class="wb-rail" aria-label="Workbench helper rail">(.*?)</aside>',
            approved_page.text,
            re.DOTALL,
        )
        assert approved_helper is not None, "Workbench helper rail not found"
        self.assertNotIn("Approve current snapshot", approved_helper.group(1))

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
        self.assertIsNone(state.manual_approval)
        edited_page = self.client.get(glossary_url)
        self.assertNotIn(
            "This exact current glossary snapshot has explicit local approval.",
            edited_page.text,
        )
        self.assertIn(
            "The exact current glossary snapshot needs explicit local approval ",
            edited_page.text,
        )
        self.assertIn(
            'data-workbench-not-ready-checklist="true"', edited_page.text
        )
        edited_helper = re.search(
            r'<aside class="wb-rail" aria-label="Workbench helper rail">(.*?)</aside>',
            edited_page.text,
            re.DOTALL,
        )
        assert edited_helper is not None, "Workbench helper rail not found"
        self.assertIn("Approve current snapshot", edited_helper.group(1))

    def test_add_after_approval_invalidates_helper_and_local_check(self) -> None:
        document_id = "add-invalidation-synthetic-document"
        glossary_url = f"/admin/workbench/glossary?document={document_id}"
        self.assertEqual(self.client.get(glossary_url).status_code, 200)

        first_added = self.client.post(
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
        self.assertEqual(first_added.status_code, 303)
        state = next(iter(WORKBENCH_SESSION_STATE.values()))
        first_term_id = next(iter(state.terms))

        approved = self.client.post(
            f"/admin/workbench/glossary/approve?document={document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303)
        self.assertIn(
            "This exact current glossary snapshot has explicit local approval.",
            self.client.get(glossary_url).text,
        )
        approved_page = self.client.get(glossary_url)
        self.assertNotIn(
            'data-workbench-not-ready-checklist="true"', approved_page.text
        )
        approved_helper = re.search(
            r'<aside class="wb-rail" aria-label="Workbench helper rail">(.*?)</aside>',
            approved_page.text,
            re.DOTALL,
        )
        assert approved_helper is not None, "Workbench helper rail not found"
        self.assertNotIn("Approve current snapshot", approved_helper.group(1))

        added_after_approval = self.client.post(
            f"/admin/workbench/glossary/terms/add?document={document_id}",
            data={
                "csrf_token": self.csrf_token,
                "source": "Beryl",
                "target": "Берил",
                "type": "name",
                "notes": "local synthetic term",
            },
            follow_redirects=False,
        )
        self.assertEqual(added_after_approval.status_code, 303)
        self.assertIsNone(state.manual_approval)
        stale_page = self.client.get(glossary_url)
        self.assertNotIn(
            "This exact current glossary snapshot has explicit local approval.",
            stale_page.text,
        )
        self.assertIn(
            "The exact current glossary snapshot needs explicit local approval ",
            stale_page.text,
        )
        self.assertIn(
            'data-workbench-not-ready-checklist="true"', stale_page.text
        )
        stale_helper = re.search(
            r'<aside class="wb-rail" aria-label="Workbench helper rail">(.*?)</aside>',
            stale_page.text,
            re.DOTALL,
        )
        assert stale_helper is not None, "Workbench helper rail not found"
        self.assertIn("Approve current snapshot", stale_helper.group(1))

        blocked = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={"csrf_token": self.csrf_token, "selected_term_ids": first_term_id},
            follow_redirects=True,
        )
        self.assertIn("Local glossary check blocked", blocked.text)
        self.assertIn("missing_approval", blocked.text)

        reapproved = self.client.post(
            f"/admin/workbench/glossary/approve?document={document_id}",
            data={"csrf_token": self.csrf_token},
            follow_redirects=False,
        )
        self.assertEqual(reapproved.status_code, 303)
        current = self.client.post(
            f"/admin/workbench/glossary/check?document={document_id}",
            data={"csrf_token": self.csrf_token, "selected_term_ids": first_term_id},
            follow_redirects=True,
        )
        self.assertIn("Local glossary structural observation", current.text)
        self.assertNotIn("missing_approval", current.text)

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

    def test_workbench_unwired_actions_render_notice_but_local_lock_actions_do_not(
        self,
    ) -> None:
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
                elif path.endswith("/lock") or path.endswith("lock-all-approved"):
                    self.assertNotIn("Saving is not wired in this slice.", page.text)
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

    def test_workbench_entry_reopens_local_demo_without_stale_recovery(self) -> None:
        first_now = datetime(2026, 7, 22, 17, 0, tzinfo=UTC)
        with mock.patch("translator_service.admin.routes.datetime") as clock:
            clock.now.side_effect = (first_now, first_now + timedelta(seconds=1))
            first = self.client.get("/admin/workbench-entry")
            self.assertEqual(first.status_code, 200)
            self.assertNotIn("Reopen latest document", first.text)
            second = self.client.get("/admin/workbench-entry")
        self.assertEqual(second.status_code, 200)
        self.assertNotIn("Reopen latest document", second.text)
        self.assertIn("No terms yet.", second.text)

    def test_workbench_entry_reseeds_local_demo_after_external_document_stales_it(
        self,
    ) -> None:
        first_entry = self.client.get("/admin/workbench-entry")
        self.assertEqual(first_entry.status_code, 200)
        canonical_document_id = re.search(
            r'data-document-id="([^"]+)"', first_entry.text
        )
        assert canonical_document_id is not None
        seeded_state = next(iter(WORKBENCH_SESSION_STATE.values()))
        added_term, reason = seeded_state.append_term(
            source="Local only",
            target="Локально",
            type_="term",
            notes="discard on Admin re-entry",
        )
        self.assertIsNone(reason)
        self.assertIsNotNone(added_term)

        stale = self.client.get(
            "/admin/workbench/glossary?document=external-opaque-document"
        )
        self.assertEqual(stale.status_code, 200)
        self.assertIn("Reopen latest document", stale.text)
        stale_state = next(iter(WORKBENCH_SESSION_STATE.values()))
        self.assertEqual(stale_state.approval_state.value, "stale")
        self.assertEqual(
            stale_state.document.document_id, "external-opaque-document"
        )

        reentered = self.client.get("/admin/workbench-entry")
        self.assertEqual(reentered.status_code, 200)
        self.assertNotIn("Reopen latest document", reentered.text)
        self.assertIn("No terms yet.", reentered.text)
        self.assertIn(
            f'data-document-id="{canonical_document_id.group(1)}"',
            reentered.text,
        )
        reentered_state = next(iter(WORKBENCH_SESSION_STATE.values()))
        self.assertEqual(
            reentered_state.document.document_id,
            canonical_document_id.group(1),
        )
        self.assertEqual(reentered_state.approval_state.value, "ready")
        self.assertEqual(reentered_state.terms, {})
        self.assertIsNone(reentered_state.manual_approval)

    def test_workbench_entry_generated_add_term_url_renders_form(self) -> None:
        entry = self.client.get("/admin/workbench-entry")
        self.assertEqual(entry.status_code, 200)
        add_term_url = re.search(
            r'data-action="add-term" href="([^"]+)"', entry.text
        )
        assert add_term_url is not None

        form_page = self.client.get(unescape(add_term_url.group(1)))
        self.assertEqual(form_page.status_code, 200)
        self.assertIn('id="wb-add-term-form"', form_page.text)

    def test_workbench_primary_link_keeps_visible_white_text(self) -> None:
        response = self.client.get("/admin/workbench/recovery?reason=stale")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            ".workbench a.wb-button--primary { color: #FFFFFF; }",
            response.text,
        )

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
