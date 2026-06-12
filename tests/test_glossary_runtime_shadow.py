import json
import unittest
from pathlib import Path

from translator_service.glossary_candidate_reducer import GlossaryCandidateReducerCaps
from translator_service.glossary_runtime_shadow import (
    GLOSSARY_RUNTIME_SHADOW_SCHEMA_VERSION,
    GlossaryRuntimeShadowConfig,
    build_glossary_runtime_shadow_plan_for_txt,
)
from translator_service.glossary_selection import GlossarySelectionBudget


class GlossaryRuntimeShadowTest(unittest.TestCase):
    def test_default_is_disabled_and_keeps_runtime_unchanged(self):
        plan = build_glossary_runtime_shadow_plan_for_txt(
            content=b"Elizabeth spoke to Darcy.",
            source_language="en",
            target_language="ru",
        )

        self.assertEqual(plan["schema_version"], GLOSSARY_RUNTIME_SHADOW_SCHEMA_VERSION)
        self.assertFalse(plan["enabled"])
        self.assertEqual(plan["status"], "disabled")
        self.assertEqual(
            plan["fallback_reason"],
            "shadow_planning_disabled_by_default",
        )
        self.assertEqual(plan["work_unit_plans"], [])
        self.assertNotIn("reducer", plan)
        self.assertNotIn("policy_signature_context", plan)
        self.assertFalse(
            plan["runtime_integration"]["normal_translation_prompts_changed"]
        )
        self.assertFalse(plan["runtime_integration"]["live_provider_calls_allowed"])
        self.assertFalse(plan["runtime_integration"]["durable_state_mutation_allowed"])
        self.assertFalse(plan["runtime_integration"]["cache_mutation_allowed"])

    def test_enabled_shadow_plan_builds_compact_signatures_for_fixture(self):
        fixture = Path("test_samples/sample_book.en.txt")
        source_text = fixture.read_text(encoding="utf-8")

        plan = build_glossary_runtime_shadow_plan_for_txt(
            content=fixture.read_bytes(),
            source_language="en",
            target_language="ru",
            config=GlossaryRuntimeShadowConfig(enabled=True, max_work_units=2),
        )
        serialized = json.dumps(plan, ensure_ascii=False, sort_keys=True)

        self.assertTrue(plan["enabled"])
        self.assertIn(plan["status"], {"planned", "planned_with_drops"})
        self.assertIn("reducer", plan)
        self.assertEqual(
            plan["glossary_signature"],
            plan["reducer"]["reduced_glossary_signature"],
        )
        self.assertEqual(
            plan["reduced_glossary_signature"],
            plan["reducer"]["reduced_glossary_signature"],
        )
        self.assertTrue(plan["reducer"]["reducer_signature"].startswith(
            "glossary-candidate-reducer:v1:"
        ))
        self.assertGreater(plan["reducer"]["retained_count"], 0)
        self.assertTrue(plan["translation_snapshot_signature"].startswith(
            "translation-contract-snapshot:v1:"
        ))
        self.assertTrue(plan["aggregate_selection_signature"].startswith(
            "glossary-shadow-selection:v1:"
        ))
        self.assertEqual(
            plan["policy_signature_context"]["selection_signature"],
            plan["aggregate_selection_signature"],
        )
        self.assertGreaterEqual(plan["planned_work_unit_count"], 1)
        self.assertLessEqual(plan["planned_work_unit_count"], 2)
        self.assertTrue(
            all(
                item["reducer_signature"] == plan["reducer"]["reducer_signature"]
                for item in plan["work_unit_plans"]
            )
        )
        self.assertTrue(
            all(
                item["reduced_glossary_signature"]
                == plan["reducer"]["reduced_glossary_signature"]
                for item in plan["work_unit_plans"]
            )
        )
        self.assertFalse(
            plan["runtime_integration"]["normal_translation_prompts_changed"]
        )
        self.assertNotIn(source_text[:80], serialized)
        self.assertNotIn("bounded_source_excerpt", serialized)
        self.assertNotIn("raw_source", serialized)
        self.assertNotIn("prompt_body", serialized)
        self.assertNotIn("provider_response", serialized)
        self.assertNotIn("translated_text", serialized)

    def test_prompt_budget_exhaustion_falls_back_without_prompt_injection(self):
        fixture = Path("test_samples/russian_profile_regression.en-ru.txt")

        plan = build_glossary_runtime_shadow_plan_for_txt(
            content=fixture.read_bytes(),
            source_language="en",
            target_language="ru",
            config=GlossaryRuntimeShadowConfig(
                enabled=True,
                max_work_units=1,
                selection_budget=GlossarySelectionBudget(
                    max_prompt_tokens=0,
                    max_entries=1,
                    max_diagnostic_entries=0,
                ),
            ),
        )

        self.assertEqual(plan["status"], "planned_with_budget_fallback")
        self.assertEqual(plan["fallback_reason"], "prompt_budget_exhausted")
        self.assertEqual(
            plan["work_unit_plans"][0]["budget_status"],
            "fallback_omitted",
        )
        self.assertIn(
            "prompt_budget_exhausted",
            plan["work_unit_plans"][0]["fallback_reason_codes"],
        )
        self.assertEqual(
            plan["runtime_integration"]["fallback_action"],
            "omit_glossary_prompt_context",
        )
        self.assertFalse(
            plan["runtime_integration"]["normal_translation_prompts_changed"]
        )

    def test_invalid_fixture_content_falls_back_to_existing_translation_path(self):
        plan = build_glossary_runtime_shadow_plan_for_txt(
            content=b"",
            source_language="en",
            target_language="uk",
            config=GlossaryRuntimeShadowConfig(enabled=True),
        )

        self.assertEqual(plan["status"], "fallback")
        self.assertEqual(plan["fallback_reason"], "shadow_planning_failed")
        self.assertEqual(plan["work_unit_plans"], [])
        self.assertEqual(
            plan["runtime_integration"]["fallback_action"],
            "use_existing_translation_path",
        )
        self.assertFalse(plan["runtime_integration"]["durable_state_mutation_allowed"])

    def test_missing_reduced_candidates_falls_back_to_existing_translation_path(self):
        fixture = Path("test_samples/sample_book.en.txt")

        plan = build_glossary_runtime_shadow_plan_for_txt(
            content=fixture.read_bytes(),
            source_language="en",
            target_language="ru",
            config=GlossaryRuntimeShadowConfig(
                enabled=True,
                reducer_caps=GlossaryCandidateReducerCaps(
                    max_editor_entries=0,
                    max_diagnostic_entries=0,
                    max_estimated_editor_tokens=0,
                    min_editor_score=999_999,
                    min_diagnostic_score=999_999,
                ),
            ),
        )

        self.assertEqual(plan["status"], "fallback")
        self.assertEqual(plan["fallback_reason"], "no_reduced_candidates")
        self.assertEqual(plan["work_unit_plans"], [])
        self.assertEqual(
            plan["runtime_integration"]["fallback_action"],
            "use_existing_translation_path",
        )
        self.assertFalse(
            plan["runtime_integration"]["normal_translation_prompts_changed"]
        )

    def test_invalid_reducer_config_falls_back_without_state_mutation(self):
        fixture = Path("test_samples/sample_book.en.txt")

        plan = build_glossary_runtime_shadow_plan_for_txt(
            content=fixture.read_bytes(),
            source_language="en",
            target_language="uk",
            config=GlossaryRuntimeShadowConfig(
                enabled=True,
                reducer_caps=GlossaryCandidateReducerCaps(max_editor_entries=-1),
            ),
        )

        self.assertEqual(plan["status"], "fallback")
        self.assertEqual(plan["fallback_reason"], "shadow_planning_failed")
        self.assertEqual(plan["error_type"], "ValueError")
        self.assertEqual(
            plan["runtime_integration"]["fallback_action"],
            "use_existing_translation_path",
        )
        self.assertFalse(plan["runtime_integration"]["cache_mutation_allowed"])


if __name__ == "__main__":
    unittest.main()
