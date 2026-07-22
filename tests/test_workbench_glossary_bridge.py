"""Tests for the UI-neutral Workbench glossary rehearsal bridge."""

from __future__ import annotations

import ast
import inspect
import unittest
from unittest import mock

from translator_service import workbench_glossary_bridge as bridge
from translator_service.manual_glossary_rehearsal import (
    ManualGlossaryRehearsalBoundaryError,
)


class WorkbenchGlossaryBridgeTests(unittest.TestCase):
    """The bridge only forwards opaque inputs to the Stage-1 rehearsal seam."""

    def test_delegates_inputs_and_returns_stage_one_result_unchanged(self):
        document_ref = "opaque-document-ref"
        approval = object()
        snapshot = object()
        work_unit = object()
        selection_budget = object()
        prompt_config = object()
        expected_result = object()

        with mock.patch.object(
            bridge,
            "rehearse_manual_glossary_approval",
            return_value=expected_result,
        ) as rehearsal:
            actual_result = bridge.rehearse_workbench_glossary(
                document_ref,
                approval,
                snapshot,
                work_unit,
                selection_budget=selection_budget,
                prompt_config=prompt_config,
            )

        self.assertIs(actual_result, expected_result)
        rehearsal.assert_called_once_with(
            document_ref,
            approval,
            snapshot,
            work_unit,
            selection_budget=selection_budget,
            prompt_config=prompt_config,
        )

    def test_propagates_stage_one_boundary_error_unchanged(self):
        expected_error = ManualGlossaryRehearsalBoundaryError(
            "missing_approval",
            "Stage-1 boundary failed closed.",
        )

        with mock.patch.object(
            bridge,
            "rehearse_manual_glossary_approval",
            side_effect=expected_error,
        ):
            with self.assertRaises(ManualGlossaryRehearsalBoundaryError) as caught:
                bridge.rehearse_workbench_glossary(
                    "opaque-document-ref",
                    None,
                    object(),
                    object(),
                    selection_budget=object(),
                    prompt_config=None,
                )

        self.assertIs(caught.exception, expected_error)

    def test_forwards_missing_approval_without_manufacturing_one(self):
        snapshot = object()
        work_unit = object()
        selection_budget = object()
        expected_result = object()

        with mock.patch.object(
            bridge,
            "rehearse_manual_glossary_approval",
            return_value=expected_result,
        ) as rehearsal:
            actual_result = bridge.rehearse_workbench_glossary(
                "opaque-document-ref",
                None,
                snapshot,
                work_unit,
                selection_budget=selection_budget,
                prompt_config=None,
            )

        self.assertIs(actual_result, expected_result)
        self.assertIsNone(rehearsal.call_args.args[1])

    def test_has_no_forbidden_service_imports(self):
        tree = ast.parse(inspect.getsource(bridge))
        imported_roots = {
            alias.name.split(".", maxsplit=1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".", maxsplit=1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }

        self.assertTrue(
            {
                "runner",
                "cache",
                "provider",
                "filesystem",
                "database",
                "db",
                "telegram",
            }.isdisjoint(imported_roots)
        )


if __name__ == "__main__":
    unittest.main()
