import json
import unittest
from datetime import UTC, datetime

from translator_service.glossary_candidate_reducer import GlossaryCandidateReducerCaps
from translator_service.glossary_persistent_runtime_resolver import (
    PersistentEpubGlossaryResolverConfig,
    build_persistent_epub_glossary_runtime_hook,
    build_persistent_epub_glossary_runtime_hook_from_prepared_package,
)
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.glossary_target_metadata_overlay import (
    GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
)
from translator_service.persistent_jobs import (
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
)


class PersistentEpubGlossaryResolverTests(unittest.TestCase):
    def test_resolver_is_disabled_by_default(self):
        hook = build_persistent_epub_glossary_runtime_hook(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            target_metadata_overlay_payload=_overlay_payload(),
        )

        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_epub_glossary_resolver_disabled",
        )
        self.assertEqual(hook.prompt_context_entries, ())

    def test_ready_hook_uses_overlay_without_serializing_raw_source_in_plan(self):
        hook = build_persistent_epub_glossary_runtime_hook(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            target_metadata_overlay_payload=_overlay_payload(),
            config=_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "planned")
        self.assertEqual(hook.glossary_plan["target_language"], "ru")
        self.assertEqual(
            hook.glossary_plan["target_metadata_overlay"]["status"],
            "applied",
        )
        selected_entry_ids = hook.glossary_plan["work_unit_plans"][0][
            "selected_entry_ids"
        ]
        self.assertEqual(len(selected_entry_ids), 1)
        self.assertTrue(selected_entry_ids[0].startswith("glossary-scan:name:"))
        self.assertEqual(hook.owner_battle_test_enabled, True)
        self.assertEqual(hook.prompt_rehearsal_enabled, True)
        self.assertEqual(len(hook.prompt_context_entries), 1)

        serialized_plan = json.dumps(
            hook.glossary_plan,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn("Darcy returns.", serialized_plan)
        self.assertNotIn("Дарси", serialized_plan)
        self.assertIn("metadata_only", serialized_plan)

    def test_missing_target_metadata_falls_back_safely(self):
        payload = dict(_overlay_payload())
        payload["targets"] = {"uk": {"entries": []}}

        hook = build_persistent_epub_glossary_runtime_hook(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            target_metadata_overlay_payload=payload,
            config=_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "fallback")
        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_epub_target_metadata_overlay_invalid",
        )
        self.assertEqual(hook.prompt_context_entries, ())

    def test_non_epub_document_kind_falls_back_without_context(self):
        hook = build_persistent_epub_glossary_runtime_hook(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            target_metadata_overlay_payload=_overlay_payload(),
            document_kind="docx",
            config=_enabled_config(),
        )

        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_epub_unsupported_document_kind",
        )
        self.assertEqual(hook.prompt_context_entries, ())

    def test_prepared_package_ready_hook_uses_validated_overlay(self):
        hook = build_persistent_epub_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            prepared_package_payload=_prepared_package_payload(),
            config=_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "planned")
        self.assertEqual(
            hook.glossary_plan["prepared_package"]["status"],
            "ready",
        )
        self.assertEqual(
            hook.glossary_plan["prepared_package"]["ready_entry_count"],
            1,
        )
        self.assertEqual(len(hook.prompt_context_entries), 1)

    def test_prepared_package_target_mismatch_falls_back(self):
        payload = _prepared_package_payload(target_language="uk")

        hook = build_persistent_epub_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            prepared_package_payload=payload,
            config=_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "fallback")
        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_epub_prepared_package_target_mismatch",
        )
        self.assertEqual(
            hook.glossary_plan["prepared_package"]["status"],
            "invalid",
        )
        self.assertEqual(hook.prompt_context_entries, ())

    def test_prepared_package_needs_review_falls_back(self):
        payload = _prepared_package_payload(needs_review=True)

        hook = build_persistent_epub_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            prepared_package_payload=payload,
            config=_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "fallback")
        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_epub_prepared_package_not_ready",
        )
        self.assertEqual(
            hook.glossary_plan["prepared_package"]["status"],
            "needs_review",
        )
        self.assertEqual(hook.prompt_context_entries, ())


def _enabled_config() -> PersistentEpubGlossaryResolverConfig:
    return PersistentEpubGlossaryResolverConfig(
        enabled=True,
        owner_battle_test_enabled=True,
        reducer_caps=GlossaryCandidateReducerCaps(
            max_editor_entries=20,
            max_diagnostic_entries=20,
            max_estimated_editor_tokens=1000,
            min_editor_score=1,
            min_diagnostic_score=1,
        ),
    )


def _overlay_payload() -> dict[str, object]:
    return {
        "schema_version": GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
        "overlay_id": "resolver-test-overlay",
        "scope": "local_owner_only_real_book_battle_test",
        "owner_approved": True,
        "source_language": "en",
        "targets": {
            "ru": {
                "entries": [
                    {
                        "source_canonical": "Darcy",
                        "target_canonical": "Дарси",
                        "target_variants": ["мистер Дарси"],
                    }
                ]
            }
        },
    }


def _prepared_package_payload(
    *,
    target_language: str = "ru",
    needs_review: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
        "package_id": "prepared:resolver-test:ru",
        "source_language": "en",
        "target_language": target_language,
        "glossary_mode": "with_glossary",
        "provider_role_id": GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
        "provider_model": "deepseek-v4-pro",
        "provider_run_id": "provider-run:fake",
        "candidate_selector_signature": "selector:fake",
        "owner_approved": True,
        "entries": [
            {
                "source_entry_id": "entry:darcy",
                "source_canonical": "Darcy",
                "aliases": ["Mr. Darcy"],
                "evidence_refs": ["evidence:darcy"],
                "target_canonical": "Дарси",
                "target_variants": ["мистер Дарси"],
                "forbidden_variants": ["Дэрси"],
                "strategy": "transcribe",
                "confidence": 0.91,
                "needs_review": needs_review,
                "reason_codes": ["needs_human_review"] if needs_review else [],
            }
        ],
    }


def _work_unit() -> PersistentWorkUnit:
    now = datetime(2026, 6, 14, tzinfo=UTC)
    return PersistentWorkUnit(
        id="job-1:unit-1",
        job_id="job-1",
        sequence=1,
        source_block_ids=("chapter-1:p1",),
        source_object_key="intermediate/job-1-unit-1.txt",
        source_text_hash="hash-1",
        prompt_tier="plain",
        source_language="en",
        target_language="ru",
        status=PersistentWorkUnitStatus.TRANSLATING,
        translated_text=None,
        worker_id="worker-a",
        claim_token="claim-1",
        prompt_tokens=0,
        completion_tokens=0,
        cache_hit_tokens=0,
        cache_miss_tokens=0,
        attempt_count=0,
        max_attempts=3,
        retry_count=0,
        last_error=None,
        available_at=now,
        lease_until=None,
        created_at=now,
        updated_at=now,
        started_at=now,
        completed_at=None,
    )


if __name__ == "__main__":
    unittest.main()
