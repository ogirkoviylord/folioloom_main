import json
import unittest
from dataclasses import replace

from tests.test_glossary_editor_chunk_outputs import (
    _json,
    _test_packet,
    _valid_output,
)
from translator_service.glossary_contracts import GlossaryGender
from translator_service.glossary_editor_chunk_outputs import (
    merge_chunked_glossary_editor_outputs,
    validate_chunked_glossary_editor_output,
)
from translator_service.glossary_evaluation import (
    GlossaryEditorReadinessGateCode,
    GlossaryEditorReadinessStage,
    evaluate_glossary_editor_readiness,
    serialize_glossary_editor_evaluation,
)


class GlossaryEvaluationTest(unittest.TestCase):
    def test_valid_fake_output_passes_provider_retry_gate_only(self):
        packet = _test_packet()
        validation = validate_chunked_glossary_editor_output(
            _json(_valid_output(packet)),
            packet=packet,
        )
        merge = merge_chunked_glossary_editor_outputs((validation,))

        evaluation = evaluate_glossary_editor_readiness(
            (validation,),
            merge_result=merge,
            packets=(packet,),
        )
        serialized = serialize_glossary_editor_evaluation(evaluation)

        self.assertTrue(evaluation.provider_retry_ready)
        self.assertFalse(evaluation.runtime_architecture_review_ready)
        self.assertEqual(evaluation.metrics.schema_validity_rate, 1.0)
        self.assertEqual(evaluation.metrics.evidence_ref_coverage_rate, 1.0)
        self.assertEqual(evaluation.metrics.invalid_chunk_rate, 0.0)
        self.assertNotIn("Elizabeth Bennet", serialized)
        self.assertNotIn("raw_excerpt", serialized)

        failed_runtime_gates = {
            gate.code
            for gate in evaluation.gates
            if (
                gate.stage
                is GlossaryEditorReadinessStage.PROVIDER_RETRY_TO_RUNTIME_ARCHITECTURE
            )
            and not gate.passed
        }
        self.assertEqual(
            failed_runtime_gates,
            {
                GlossaryEditorReadinessGateCode.PROVIDER_EVIDENCE,
                GlossaryEditorReadinessGateCode.PROVIDER_TOKEN_CAP,
            },
        )

    def test_missing_evidence_invalid_chunk_fails_structured_gates(self):
        packet = _test_packet()
        document = _valid_output(packet)
        document["evidence_refs"] = []
        document["proposed_entries"][0]["evidence_refs"] = []
        validation = validate_chunked_glossary_editor_output(
            json.dumps(document, ensure_ascii=False, sort_keys=True),
            packet=packet,
        )
        merge = merge_chunked_glossary_editor_outputs((validation,))

        evaluation = evaluate_glossary_editor_readiness(
            (validation,),
            merge_result=merge,
            packets=(packet,),
        )
        failed_local_gates = _failed_local_gate_codes(evaluation)

        self.assertFalse(evaluation.provider_retry_ready)
        self.assertEqual(evaluation.metrics.schema_validity_rate, 0.0)
        self.assertEqual(evaluation.metrics.invalid_chunk_rate, 1.0)
        self.assertEqual(evaluation.metrics.evidence_ref_coverage_rate, 0.0)
        self.assertGreaterEqual(evaluation.metrics.blocker_finding_count, 1)
        self.assertIn(
            GlossaryEditorReadinessGateCode.EVIDENCE_REF_COVERAGE,
            failed_local_gates,
        )
        self.assertIn(
            GlossaryEditorReadinessGateCode.INVALID_CHUNK_RATE,
            failed_local_gates,
        )
        self.assertIn(
            GlossaryEditorReadinessGateCode.BLOCKER_FINDINGS,
            failed_local_gates,
        )

    def test_duplicate_conflict_and_needs_review_rates_fail_readiness(self):
        packet = _test_packet()
        first = validate_chunked_glossary_editor_output(
            _json(_valid_output(packet)),
            packet=packet,
        )
        second = validate_chunked_glossary_editor_output(
            _json(
                _valid_output(
                    packet,
                    aliases=["Different Alias"],
                    target_canonical="Target B",
                    target_variants=["Target Bee"],
                    confidence=0.51,
                    grammatical_gender=GlossaryGender.FEMININE.value,
                )
            ),
            packet=packet,
        )
        merge = merge_chunked_glossary_editor_outputs((first, second))

        evaluation = evaluate_glossary_editor_readiness(
            (first, second),
            merge_result=merge,
            packets=(packet,),
        )
        failed_local_gates = _failed_local_gate_codes(evaluation)

        self.assertFalse(evaluation.provider_retry_ready)
        self.assertEqual(evaluation.metrics.duplicate_rate, 1.0)
        self.assertEqual(evaluation.metrics.conflict_rate, 2.0)
        self.assertEqual(evaluation.metrics.needs_review_rate, 1.0)
        self.assertIn(
            GlossaryEditorReadinessGateCode.WARNING_FINDINGS,
            failed_local_gates,
        )
        self.assertIn(GlossaryEditorReadinessGateCode.CONFLICT_RATE, failed_local_gates)
        self.assertIn(
            GlossaryEditorReadinessGateCode.NEEDS_REVIEW_RATE,
            failed_local_gates,
        )

    def test_budget_and_provider_token_overrun_fail_readiness(self):
        packet = _test_packet()
        validation = validate_chunked_glossary_editor_output(
            _json(_valid_output(packet)),
            packet=packet,
        )
        over_budget_packet = replace(
            packet,
            estimated_prompt_tokens=packet.max_estimated_prompt_tokens + 1,
        )
        merge = merge_chunked_glossary_editor_outputs((validation,))

        evaluation = evaluate_glossary_editor_readiness(
            (validation,),
            merge_result=merge,
            packets=(over_budget_packet,),
            metadata_report={
                "approval": {"max_tokens_total": 1000},
                "observed_tokens": 1001,
            },
            provider_evidence_available=True,
        )

        self.assertFalse(evaluation.provider_retry_ready)
        self.assertFalse(evaluation.runtime_architecture_review_ready)
        self.assertEqual(evaluation.metrics.budget_overrun_count, 1)
        self.assertTrue(evaluation.metrics.provider_token_over_cap)
        self.assertIn(
            GlossaryEditorReadinessGateCode.BUDGET_OVERRUNS,
            _failed_local_gate_codes(evaluation),
        )
        runtime_stage = (
            GlossaryEditorReadinessStage.PROVIDER_RETRY_TO_RUNTIME_ARCHITECTURE
        )
        self.assertIn(
            GlossaryEditorReadinessGateCode.PROVIDER_TOKEN_CAP,
            {
                gate.code
                for gate in evaluation.gates
                if not gate.passed and gate.stage is runtime_stage
            },
        )


def _failed_local_gate_codes(evaluation):
    return {
        gate.code
        for gate in evaluation.gates
        if gate.stage is GlossaryEditorReadinessStage.LOCAL_TO_PROVIDER_RETRY
        and not gate.passed
    }


if __name__ == "__main__":
    unittest.main()
