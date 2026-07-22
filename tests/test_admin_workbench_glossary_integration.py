"""HTTP integration tests for the provider-free Workbench glossary seam."""

from __future__ import annotations

import os
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from fastapi.testclient import TestClient

from translator_service import manual_glossary_rehearsal as rehearsal_module
from translator_service import workbench_glossary_bridge as bridge
from translator_service.admin import routes, workbench_views
from translator_service.admin.workbench_glossary_projection import (
    project_workbench_glossary_rehearsal,
)
from translator_service.admin.workbench_session_state import WORKBENCH_SESSION_STATE
from translator_service.api import create_app
from translator_service.config import Settings
from translator_service.format_adapters.contracts import (
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryEvidenceRef,
    GlossaryEvidenceSurface,
    GlossaryEvidenceType,
    GlossaryGender,
    GlossaryLayer,
    GlossarySnapshot,
    GlossaryStrategy,
    glossary_snapshot_signature,
)
from translator_service.glossary_selection import GlossarySelectionBudget
from translator_service.manual_glossary_rehearsal import (
    ManualGlossaryApproval,
    ManualGlossaryRehearsalBoundaryError,
)
from translator_service.structure_optimizer import PromptTier, TextBlockKind

_RAW_SOURCE = "DO_NOT_RENDER_SOURCE"
_RAW_TARGET = "DO_NOT_RENDER_TARGET"
_DOCUMENT_REF = "owner://opaque-document-ref"


def _snapshot() -> GlossarySnapshot:
    evidence = GlossaryEvidenceRef(
        evidence_id="evidence:one",
        evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
        unit_sequence=1,
        source_block_id="block:one",
        source_scope="chapter:one",
        surface=GlossaryEvidenceSurface.BODY,
    )
    entry = GlossaryEntry(
        entry_id="entry:opaque-id",
        category=GlossaryEntryCategory.NAME,
        layer=GlossaryLayer.HARD,
        status=GlossaryEntryStatus.OWNER_PINNED,
        source_canonical=_RAW_SOURCE,
        target_canonical=_RAW_TARGET,
        evidence_refs=(evidence.evidence_id,),
        confidence=1.0,
        strategy=GlossaryStrategy.TRANSLITERATE,
        grammatical_gender=GlossaryGender.UNKNOWN,
    )
    return GlossarySnapshot(
        snapshot_id="snapshot:opaque-id",
        source_language="en",
        target_language="ru",
        entries=(entry,),
        evidence=(evidence,),
    )


def _work_unit() -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=1,
        blocks=(
            FormatTextBlock(
                index=0,
                source_block_id="block:one",
                text=f"A mention of {_RAW_SOURCE}.",
                kind=TextBlockKind.PLAIN,
            ),
        ),
        prompt_tier=PromptTier.PLAIN,
    )


def _admin_login(client: TestClient) -> None:
    response = client.post(
        "/admin/login", data={"password": "owner-pass"}, follow_redirects=False
    )
    assert response.status_code in (302, 303), response.status_code


class WorkbenchGlossaryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        WORKBENCH_SESSION_STATE.clear()
        self.addCleanup(WORKBENCH_SESSION_STATE.clear)
        self.snapshot = _snapshot()
        self.work_unit = _work_unit()
        self.budget = GlossarySelectionBudget(max_prompt_tokens=200)
        self.approval = ManualGlossaryApproval(
            document_ref=_DOCUMENT_REF,
            glossary_signature=glossary_snapshot_signature(self.snapshot),
        )

    def _client_with_rehearsal(self, rehearsal: object) -> TestClient:
        original_factory = routes.create_workbench_router

        def fixture_router(settings, session_manager):
            return original_factory(
                settings,
                session_manager,
                glossary_rehearsal_fixture=rehearsal,
            )

        with mock.patch.object(routes, "create_workbench_router", fixture_router):
            client = TestClient(
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
        _admin_login(client)
        return client

    def test_protected_get_renders_only_metadata_for_injected_rehearsal(self):
        rehearsal = bridge.rehearse_workbench_glossary(
            _DOCUMENT_REF,
            self.approval,
            self.snapshot,
            self.work_unit,
            selection_budget=self.budget,
        )

        response = self._client_with_rehearsal(rehearsal).get(
            "/admin/workbench/glossary?document=opaque-1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'data-workbench-glossary-observation="local-structural-ready"',
            response.text,
        )
        self.assertIn("Selected: 1;", response.text)
        self.assertIn("rendered: 1;", response.text)
        self.assertNotIn("Runtime authorization", response.text)
        for forbidden in (
            _RAW_SOURCE,
            _RAW_TARGET,
            _DOCUMENT_REF,
            "entry:opaque-id",
            "snapshot:opaque-id",
            "prompt_body",
            "provider_request",
        ):
            self.assertNotIn(forbidden, response.text)

    def test_missing_approval_skips_all_downstream_work(self):
        with mock.patch.object(
            rehearsal_module,
            "select_glossary_subset_for_work_unit",
            wraps=rehearsal_module.select_glossary_subset_for_work_unit,
        ) as selection, mock.patch.object(
            rehearsal_module,
            "format_glossary_prompt_context",
            wraps=rehearsal_module.format_glossary_prompt_context,
        ) as prompt_render, mock.patch.object(
            routes,
            "project_workbench_glossary_rehearsal",
            wraps=project_workbench_glossary_rehearsal,
        ) as projection, mock.patch.object(
            workbench_views,
            "_workbench_glossary_observation",
            wraps=workbench_views._workbench_glossary_observation,
        ) as view_render:
            with self.assertRaises(ManualGlossaryRehearsalBoundaryError) as caught:
                bridge.rehearse_workbench_glossary(
                    _DOCUMENT_REF,
                    None,
                    self.snapshot,
                    self.work_unit,
                    selection_budget=self.budget,
                )

        self.assertEqual(caught.exception.reason, "missing_approval")
        selection.assert_not_called()
        prompt_render.assert_not_called()
        projection.assert_not_called()
        view_render.assert_not_called()

    def test_mismatched_approval_skips_all_downstream_work(self):
        mismatched = ManualGlossaryApproval(
            document_ref="owner://different-document",
            glossary_signature=self.approval.glossary_signature,
        )
        with mock.patch.object(
            rehearsal_module,
            "select_glossary_subset_for_work_unit",
            wraps=rehearsal_module.select_glossary_subset_for_work_unit,
        ) as selection, mock.patch.object(
            rehearsal_module,
            "format_glossary_prompt_context",
            wraps=rehearsal_module.format_glossary_prompt_context,
        ) as prompt_render, mock.patch.object(
            routes,
            "project_workbench_glossary_rehearsal",
            wraps=project_workbench_glossary_rehearsal,
        ) as projection, mock.patch.object(
            workbench_views,
            "_workbench_glossary_observation",
            wraps=workbench_views._workbench_glossary_observation,
        ) as view_render:
            with self.assertRaises(ManualGlossaryRehearsalBoundaryError) as caught:
                bridge.rehearse_workbench_glossary(
                    _DOCUMENT_REF,
                    mismatched,
                    self.snapshot,
                    self.work_unit,
                    selection_budget=self.budget,
                )

        self.assertEqual(caught.exception.reason, "document_ref_mismatch")
        selection.assert_not_called()
        prompt_render.assert_not_called()
        projection.assert_not_called()
        view_render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
