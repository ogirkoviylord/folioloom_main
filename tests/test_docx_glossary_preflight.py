"""Focused contracts for the pure DOCX glossary authorization preflight."""

from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import replace
from unittest import mock

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
from translator_service.manual_glossary_rehearsal import ManualGlossaryApproval
from translator_service.structure_optimizer import PromptTier, TextBlockKind

_DOC_REF = "owner://document/approved-docx"


def _snapshot() -> GlossarySnapshot:
    evidence = GlossaryEvidenceRef(
        evidence_id="evidence:darcy",
        evidence_type=GlossaryEvidenceType.SOURCE_ANCHOR,
        unit_sequence=0,
        source_block_id="block:0",
        surface=GlossaryEvidenceSurface.BODY,
    )
    entry = GlossaryEntry(
        entry_id="entry:darcy",
        category=GlossaryEntryCategory.NAME,
        layer=GlossaryLayer.HARD,
        status=GlossaryEntryStatus.LOCKED,
        source_canonical="Darcy",
        target_canonical="Дарси",
        evidence_refs=(evidence.evidence_id,),
        confidence=0.9,
        strategy=GlossaryStrategy.TRANSCRIBE,
        grammatical_gender=GlossaryGender.UNKNOWN,
    )
    return GlossarySnapshot(
        snapshot_id="snapshot:docx",
        source_language="en",
        target_language="ru",
        entries=(entry,),
        evidence=(evidence,),
    )


def _unit() -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=0,
        blocks=(
            FormatTextBlock(
                index=0,
                source_block_id="block:0",
                text="Darcy returns.",
                kind=TextBlockKind.PLAIN,
            ),
        ),
        prompt_tier=PromptTier.PLAIN,
    )


class DocxGlossaryPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        from translator_service import docx_glossary_preflight as module

        self.module = module
        self.snapshot = _snapshot()
        self.approval = ManualGlossaryApproval(
            document_ref=_DOC_REF,
            glossary_signature=glossary_snapshot_signature(self.snapshot),
        )
        self.budget = GlossarySelectionBudget(max_prompt_tokens=120)

    def _run(self, **overrides):
        args = {
            "document_kind": "docx",
            "document_ref": _DOC_REF,
            "snapshot": self.snapshot,
            "approval": self.approval,
            "work_unit": _unit(),
            "selection_budget": self.budget,
        }
        args.update(overrides)
        return self.module.preflight_docx_manual_glossary_approval(**args)

    def test_exact_docx_approval_returns_metadata_only_effective_observation(self):
        result = self._run()

        self.assertIsInstance(result, self.module.DocxGlossaryPreflightApproved)
        self.assertEqual(result.status, "approved")
        self.assertEqual(result.effective_decision_status, "effective_observed")
        self.assertEqual(result.document_ref, _DOC_REF)
        self.assertTrue(result.selection_signature.startswith("glossary-selection:v1:"))
        serialized = repr(result)
        for forbidden in ("Darcy", "Дарси", "prompt_body", "provider", "cache", "raw_"):
            self.assertNotIn(forbidden, serialized)

    def test_unsupported_kind_denies_before_snapshot_or_lower_logic(self):
        with mock.patch.object(
            self.module, "validate_glossary_snapshot", side_effect=AssertionError
        ), mock.patch.object(
            self.module, "rehearse_manual_glossary_approval", side_effect=AssertionError
        ), mock.patch.object(
            self.module,
            "build_glossary_prompt_policy_adapter_decision",
            side_effect=AssertionError,
        ):
            result = self._run(document_kind="txt")

        self.assertEqual(result.reason, "unsupported_document_kind")

    def test_invalid_snapshot_denies_before_approval_and_effective_decision(self):
        invalid_entry = replace(self.snapshot.entries[0], source_canonical="")
        invalid = replace(self.snapshot, entries=(invalid_entry,))
        with mock.patch.object(
            self.module, "rehearse_manual_glossary_approval", side_effect=AssertionError
        ), mock.patch.object(
            self.module,
            "build_glossary_prompt_policy_adapter_decision",
            side_effect=AssertionError,
        ):
            result = self._run(snapshot=invalid)

        self.assertEqual(result.reason, "invalid_snapshot")

    def test_boundary_denials_are_typed_and_skip_effective_decision(self):
        cases = (
            ("missing_approval", {"approval": None}),
            (
                "document_ref_mismatch",
                {"approval": replace(self.approval, document_ref="other")},
            ),
            (
                "signature_mismatch",
                {"approval": replace(self.approval, glossary_signature="wrong")},
            ),
        )
        for reason, overrides in cases:
            with self.subTest(reason=reason), mock.patch.object(
                self.module,
                "build_glossary_prompt_policy_adapter_decision",
                side_effect=AssertionError,
            ):
                result = self._run(**overrides)
            self.assertEqual(result.reason, reason)

    def test_hard_entry_omission_is_a_typed_denial(self):
        from translator_service.glossary_prompt_context import (
            GlossaryPromptContextConfig,
        )

        result = self._run(
            prompt_config=GlossaryPromptContextConfig(
                max_entries=0,
                max_prompt_tokens=1,
                max_characters=1,
            )
        )
        self.assertEqual(result.reason, "required_hard_entry_omitted")

    def test_module_has_no_forbidden_direct_imports(self):
        source = inspect.getsource(self.module)
        imports = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        forbidden = (
            "translator_service.job_runner",
            "translator_service.translation_runner",
            "translator_service.bot_translation_service",
            "translator_service.translation_cache",
            "translator_service.deepseek_client",
            "translator_service.persistent_jobs",
            "translator_service.persistent_job_store",
        )
        for name in forbidden:
            self.assertNotIn(name, imports)


if __name__ == "__main__":
    unittest.main()
