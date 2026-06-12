import json
import unittest
from pathlib import Path

from translator_service.documents import DocumentFormat
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.format_adapters.txt import plan_txt_translation
from translator_service.glossary_contracts import (
    GlossaryEntry,
    GlossaryEntryCategory,
    GlossaryEntryStatus,
    GlossaryGender,
    GlossaryLayer,
    GlossarySnapshot,
    GlossaryStrategy,
)
from translator_service.glossary_pressure_report import (
    GlossaryPressureFindingCode,
    GlossaryPressureFixtureMetadata,
    GlossaryPressureThresholds,
    build_glossary_pressure_report,
    serialize_glossary_pressure_report,
)
from translator_service.structure_optimizer import PromptTier, TextBlockKind


class GlossaryPressureReportTest(unittest.TestCase):
    def test_builds_metadata_only_report_from_adapter_plan(self):
        plan = _pressure_plan()

        first = build_glossary_pressure_report(
            plan,
            source_language="en",
            target_language="ru",
            fixture_metadata=GlossaryPressureFixtureMetadata(
                fixture_id="synthetic-pressure-fixture",
                rights_basis="authorized_test_fixture",
            ),
        )
        second = build_glossary_pressure_report(
            plan,
            source_language="en",
            target_language="ru",
            fixture_metadata=GlossaryPressureFixtureMetadata(
                fixture_id="synthetic-pressure-fixture",
                rights_basis="authorized_test_fixture",
            ),
        )
        serialized = serialize_glossary_pressure_report(first)
        payload = json.loads(serialized)

        self.assertEqual(first.report_signature, second.report_signature)
        self.assertEqual(payload["schema_version"], "glossary-pressure-report-v1")
        self.assertEqual(
            payload["fixture_metadata"]["rights_basis"],
            "authorized_test_fixture",
        )
        self.assertGreaterEqual(payload["candidates"]["candidate_count"], 3)
        self.assertIn("name", payload["candidates"]["category_counts"])
        self.assertIn("uncertain", payload["candidates"]["status_counts"])
        self.assertGreaterEqual(payload["profile"]["evidence_count"], 1)
        self.assertGreaterEqual(payload["packets"]["packet_count"], 1)
        self.assertIn("glossary-pressure-report:v1:", payload["report_signature"])
        self.assertNotIn("PRIVATE_SOURCE_SENTINEL", serialized)
        self.assertNotIn("Elizabeth Bennet", serialized)
        self.assertNotIn("quantum drive", serialized)
        self.assertNotIn("raw_excerpt", serialized)
        self.assertNotIn("system prompt", serialized.lower())
        self.assertNotIn("prompt body", serialized.lower())
        self.assertNotIn("provider", serialized.lower())

    def test_supports_txt_fixture_and_epub_docx_shaped_plans(self):
        fixture_text = Path("test_samples/sample_book.en.txt").read_text(
            encoding="utf-8"
        )
        txt_report = build_glossary_pressure_report(
            plan_txt_translation(
                content=fixture_text.encode("utf-8"),
                max_fragment_chars=2400,
            ),
            source_language="en",
            target_language="ru",
            fixture_metadata=GlossaryPressureFixtureMetadata(
                fixture_id="sample_book.en.txt",
                rights_basis="repo_fixture",
            ),
        )
        txt_serialized = serialize_glossary_pressure_report(txt_report)

        self.assertEqual(txt_report.plan.document_format, "txt")
        self.assertNotIn(fixture_text[:80], txt_serialized)

        for document_format in (DocumentFormat.DOCX, DocumentFormat.EPUB):
            with self.subTest(document_format=document_format.value):
                report = build_glossary_pressure_report(
                    _pressure_plan(document_format=document_format),
                    source_language="en",
                    target_language="uk",
                )

                self.assertEqual(report.plan.document_format, document_format.value)
                self.assertGreaterEqual(report.candidates.candidate_count, 1)
                self.assertIsNotNone(report.packets.packet_build_signature)

    def test_flags_candidate_packet_token_and_profile_pressure(self):
        report = build_glossary_pressure_report(
            _pressure_plan(),
            source_language="en",
            target_language="ru",
            thresholds=GlossaryPressureThresholds(
                max_candidate_count=1,
                max_packet_count=0,
                max_total_reserved_prompt_tokens=1,
                max_packet_budget_utilization=0.0,
                min_profile_confidence=0.99,
            ),
        )
        codes = {finding.code for finding in report.findings}

        self.assertIn(GlossaryPressureFindingCode.TOO_MANY_CANDIDATES, codes)
        self.assertIn(GlossaryPressureFindingCode.TOO_MANY_PACKETS, codes)
        self.assertIn(GlossaryPressureFindingCode.TOTAL_TOKEN_PRESSURE, codes)
        self.assertIn(GlossaryPressureFindingCode.PACKET_TOKEN_PRESSURE, codes)
        self.assertIn(GlossaryPressureFindingCode.PROFILE_UNCERTAIN, codes)
        self.assertGreaterEqual(report.blocker_count, 3)

    def test_flags_missing_evidence_without_serializing_entry_text(self):
        raw_candidate = "PRIVATE_SOURCE_SENTINEL Elizabeth Bennet"
        malformed_glossary = GlossarySnapshot(
            snapshot_id="glossary-snapshot:malformed",
            source_language="en",
            target_language="ru",
            entries=(
                GlossaryEntry(
                    entry_id="entry:malformed",
                    category=GlossaryEntryCategory.NAME,
                    layer=GlossaryLayer.SOFT,
                    status=GlossaryEntryStatus.UNCERTAIN,
                    source_canonical=raw_candidate,
                    evidence_refs=("ev:missing",),
                    confidence=0.52,
                    strategy=GlossaryStrategy.UNKNOWN,
                    grammatical_gender=GlossaryGender.UNKNOWN,
                ),
            ),
            evidence=(),
        )

        report = build_glossary_pressure_report(
            _pressure_plan(),
            source_language="en",
            target_language="ru",
            glossary_snapshot=malformed_glossary,
        )
        serialized = serialize_glossary_pressure_report(report)
        codes = {finding.code for finding in report.findings}

        self.assertEqual(report.candidates.entries_missing_evidence_count, 1)
        self.assertEqual(report.candidates.missing_evidence_ref_count, 1)
        self.assertEqual(report.packets.packet_build_error, "invalid_inputs")
        self.assertIn(GlossaryPressureFindingCode.INVALID_GLOSSARY, codes)
        self.assertIn(GlossaryPressureFindingCode.MISSING_EVIDENCE, codes)
        self.assertIn(GlossaryPressureFindingCode.PACKET_BUILD_FAILED, codes)
        self.assertNotIn(raw_candidate, serialized)
        self.assertNotIn("PRIVATE_SOURCE_SENTINEL", serialized)


def _pressure_plan(
    *,
    document_format: DocumentFormat = DocumentFormat.TXT,
) -> FormatAdapterPlan:
    units = (
        _unit(
            1,
            _block(
                0,
                f"{document_format.value}:segment:1",
                (
                    "Chapter One. PRIVATE_SOURCE_SENTINEL Elizabeth Bennet met "
                    "Mr Darcy near Longbourn. The quantum drive hummed."
                ),
                kind=TextBlockKind.HEADING,
            ),
        ),
        _unit(
            2,
            _block(
                1,
                f"{document_format.value}:segment:2",
                (
                    "Elizabeth spoke softly. Darcy answered Elizabeth. "
                    "Another quantum drive failed near Longbourn."
                ),
            ),
        ),
        _unit(
            3,
            _block(
                2,
                f"{document_format.value}:segment:3",
                (
                    "The methodology section says the quantum drive produced "
                    "statistically useful results."
                ),
            ),
        ),
    )
    return FormatAdapterPlan(
        document_format=document_format,
        adapter_version=f"{document_format.value}-adapter-test",
        units=units,
        character_count=sum(len(block.text) for unit in units for block in unit.blocks),
        estimated_input_tokens=240,
    )


def _unit(sequence: int, *blocks: FormatTextBlock) -> FormatTranslationUnit:
    return FormatTranslationUnit(
        sequence=sequence,
        blocks=blocks,
        prompt_tier=PromptTier.PLAIN,
    )


def _block(
    index: int,
    source_block_id: str,
    text: str,
    *,
    kind: TextBlockKind = TextBlockKind.PLAIN,
) -> FormatTextBlock:
    return FormatTextBlock(
        index=index,
        source_block_id=source_block_id,
        text=text,
        kind=kind,
    )


if __name__ == "__main__":
    unittest.main()
