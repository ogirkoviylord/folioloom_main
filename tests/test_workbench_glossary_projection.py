"""Tests for the pure Stage-3B Workbench glossary projection."""

from __future__ import annotations

import ast
import inspect
import unittest
from types import SimpleNamespace

from translator_service.admin import workbench_glossary_projection as projection_module
from translator_service.admin.workbench_glossary_projection import (
    WorkbenchGlossaryProjectionState,
    project_workbench_glossary_rehearsal,
)


class WorkbenchGlossaryProjectionTests(unittest.TestCase):
    def test_completed_structural_result_projects_counts_and_opaque_reference(self):
        rehearsal = SimpleNamespace(
            document_ref="owner://opaque-document-ref",
            glossary_signature="glossary-snapshot:v1:opaque-signature",
            snapshot_id="snapshot:opaque-id",
            selection_signature="glossary-selection:v1:opaque-signature",
            selected_entry_ids=("entry:one", "entry:two"),
            included_entry_ids=("entry:one",),
            omitted_entry_ids=("entry:two",),
        )

        projection = project_workbench_glossary_rehearsal(rehearsal)

        self.assertEqual(
            projection.state,
            WorkbenchGlossaryProjectionState.LOCAL_STRUCTURAL_OBSERVATION,
        )
        self.assertEqual(projection.document_ref, "owner://opaque-document-ref")
        self.assertEqual(projection.selected_entry_count, 2)
        self.assertEqual(projection.rendered_entry_count, 1)
        self.assertEqual(projection.omitted_entry_count, 1)
        self.assertEqual(projection.rendered_entry_ids, ("entry:one",))
        self.assertFalse(projection.runtime_authorized)

    def test_projection_state_name_does_not_imply_readiness(self):
        state = WorkbenchGlossaryProjectionState.LOCAL_STRUCTURAL_OBSERVATION
        self.assertNotIn("READY", state.name)
        self.assertNotIn("ready", state.value)

    def test_known_stage1_failure_is_fail_closed_not_runtime_authorized(self):
        rehearsal = SimpleNamespace(
            document_ref="owner://opaque-document-ref",
            glossary_signature="glossary-snapshot:v1:opaque-signature",
            selection_signature="glossary-selection:v1:opaque-signature",
            reason=SimpleNamespace(value="hard_entry_omitted_by_prompt_budget"),
            message="do not copy this arbitrary text",
        )

        projection = project_workbench_glossary_rehearsal(rehearsal)

        self.assertEqual(
            projection.state,
            WorkbenchGlossaryProjectionState.FAIL_CLOSED,
        )
        self.assertEqual(
            projection.reason_code,
            "hard_entry_omitted_by_prompt_budget",
        )
        self.assertFalse(projection.runtime_authorized)
        self.assertEqual(projection.rendered_entry_count, 0)
        self.assertNotIn("do not copy", repr(projection))

    def test_unknown_or_incomplete_observation_fails_closed(self):
        projection = project_workbench_glossary_rehearsal(
            SimpleNamespace(
                document_ref="owner://opaque-document-ref",
                reason=SimpleNamespace(value="untrusted raw reason"),
            )
        )

        self.assertEqual(
            projection.state,
            WorkbenchGlossaryProjectionState.FAIL_CLOSED,
        )
        self.assertEqual(
            projection.reason_code,
            "local_structural_rehearsal_unavailable",
        )
        self.assertFalse(projection.runtime_authorized)
        self.assertNotIn("untrusted raw reason", repr(projection))

    def test_projection_drops_raw_source_target_and_renderer_payload(self):
        raw_source = "DO_NOT_LEAK_SOURCE"
        raw_target = "DO_NOT_LEAK_TARGET"
        rehearsal = SimpleNamespace(
            document_ref="owner://opaque-document-ref",
            glossary_signature="glossary-snapshot:v1:opaque-signature",
            snapshot_id="snapshot:opaque-id",
            selection_signature="glossary-selection:v1:opaque-signature",
            selected_entry_ids=("entry:safe",),
            included_entry_ids=("entry:safe",),
            omitted_entry_ids=(),
            source_canonical=raw_source,
            target_canonical=raw_target,
            renderer_observation={
                "prompt_body": raw_source,
                "provider_request": raw_target,
            },
        )

        projection = project_workbench_glossary_rehearsal(rehearsal)

        rendered = repr(projection)
        self.assertNotIn(raw_source, rendered)
        self.assertNotIn(raw_target, rendered)
        self.assertNotIn("prompt_body", rendered)
        self.assertNotIn("provider_request", rendered)

    def test_module_does_not_import_or_invoke_runtime_collaborators(self):
        source = inspect.getsource(projection_module)
        imported_modules = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        forbidden_modules = {
            "translator_service.bot_translation_service",
            "translator_service.deepseek_client",
            "translator_service.glossary_persistent_runtime_resolver",
            "translator_service.persistent_jobs",
            "translator_service.worker",
        }

        self.assertFalse(imported_modules & forbidden_modules)


if __name__ == "__main__":
    unittest.main()
