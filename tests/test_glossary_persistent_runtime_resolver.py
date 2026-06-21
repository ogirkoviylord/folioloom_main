import json
import unittest
from datetime import UTC, datetime

from translator_service.glossary_candidate_reducer import GlossaryCandidateReducerCaps
from translator_service.glossary_persistent_runtime_resolver import (
    DEFAULT_PERSISTENT_GLOSSARY_MAX_SELECTED_ENTRIES,
    DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_BLOCKS,
    DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_CHARACTERS,
    DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_ENTRIES,
    DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_PROMPT_TOKENS,
    PersistentEpubGlossaryResolverConfig,
    PersistentGlossaryResolverConfig,
    build_persistent_epub_glossary_runtime_hook,
    build_persistent_epub_glossary_runtime_hook_from_prepared_package,
    build_persistent_glossary_runtime_hook_from_prepared_package,
)
from translator_service.glossary_prepared_package import (
    GLOSSARY_PREPARED_PACKAGE_PROVIDER_ROLE_ID,
    GLOSSARY_PREPARED_PACKAGE_SCHEMA_VERSION,
)
from translator_service.glossary_prompt_context import GlossaryPromptContextConfig
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
        self.assertEqual(
            hook.glossary_plan["resolver_caps"]["max_source_blocks"],
            DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_BLOCKS,
        )
        self.assertEqual(
            hook.glossary_plan["resolver_caps"]["max_source_characters"],
            DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_CHARACTERS,
        )
        self.assertEqual(
            hook.glossary_plan["resolver_caps"]["max_selected_entries"],
            DEFAULT_PERSISTENT_GLOSSARY_MAX_SELECTED_ENTRIES,
        )
        self.assertEqual(
            hook.glossary_plan["resolver_caps"]["selection_budget"][
                "max_prompt_tokens"
            ],
            DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_PROMPT_TOKENS,
        )
        self.assertEqual(
            hook.glossary_plan["resolver_caps"]["selection_budget"]["max_entries"],
            DEFAULT_PERSISTENT_GLOSSARY_SELECTION_MAX_ENTRIES,
        )

        serialized_plan = json.dumps(
            hook.glossary_plan,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn("Darcy returns.", serialized_plan)
        self.assertNotIn("Дарси", serialized_plan)
        self.assertIn("metadata_only", serialized_plan)

    def test_ready_hook_accepts_automatic_config_names(self):
        hook = build_persistent_epub_glossary_runtime_hook(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            target_metadata_overlay_payload=_overlay_payload(),
            config=PersistentEpubGlossaryResolverConfig(
                enabled=True,
                automatic_glossary_enabled=True,
                prompt_context_enabled=True,
                reducer_caps=GlossaryCandidateReducerCaps(
                    max_editor_entries=20,
                    max_diagnostic_entries=20,
                    max_estimated_editor_tokens=1000,
                    min_editor_score=1,
                    min_diagnostic_score=1,
                ),
            ),
        )

        self.assertTrue(hook.automatic_glossary_enabled)
        self.assertTrue(hook.owner_battle_test_enabled)
        self.assertTrue(hook.prompt_context_enabled)
        self.assertTrue(hook.prompt_rehearsal_enabled)
        self.assertEqual(hook.glossary_plan["status"], "planned")
        self.assertEqual(len(hook.prompt_context_entries), 1)

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

    def test_prepared_package_ready_hook_uses_validated_bridge(self):
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
        self.assertEqual(
            hook.glossary_plan["resolver_caps"]["max_source_characters"],
            DEFAULT_PERSISTENT_GLOSSARY_MAX_SOURCE_CHARACTERS,
        )
        self.assertEqual(len(hook.prompt_context_entries), 1)

    def test_prepared_package_entry_injects_when_scanner_does_not_rediscover_term(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(source_block_ids=("chapter-1:p1",)),
            source_text="The chrono-loom hummed once.",
            prepared_package_payload=_prepared_package_payload(
                source_entry_id="entry:chrono-loom",
                source_canonical="chrono-loom",
                aliases=(),
                evidence_refs=("evidence:chrono-loom",),
                source_unit_refs=(1,),
                source_block_refs=("chapter-1:p1",),
                target_canonical="хроно-станок",
                target_variants=("хроно-станок",),
            ),
            document_kind="epub",
            config=_generic_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "planned")
        self.assertEqual(
            hook.glossary_plan["prepared_package_runtime_bridge"]["status"],
            "applied",
        )
        self.assertEqual(
            hook.glossary_plan["prepared_package_runtime_bridge"][
                "applicable_entry_count"
            ],
            1,
        )
        self.assertEqual(len(hook.prompt_context_entries), 1)
        self.assertEqual(
            hook.glossary_plan["work_unit_plans"][0]["selected_entry_ids"],
            ["entry:chrono-loom"],
        )
        serialized_plan = json.dumps(
            hook.glossary_plan,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn("The chrono-loom hummed once.", serialized_plan)
        self.assertNotIn("хроно-станок", serialized_plan)

    def test_prepared_package_entry_for_other_unit_renders_with_ref_diagnostics(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(source_block_ids=("chapter-1:p1",)),
            source_text="The chrono-loom hummed once.",
            prepared_package_payload=_prepared_package_payload(
                source_entry_id="entry:chrono-loom",
                source_canonical="chrono-loom",
                aliases=(),
                evidence_refs=("evidence:chrono-loom",),
                source_unit_refs=(99,),
                source_block_refs=("chapter-9:p9",),
                target_canonical="хроно-станок",
                target_variants=("хроно-станок",),
            ),
            document_kind="epub",
            config=_generic_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "planned")
        self.assertEqual(
            hook.glossary_plan["prepared_package_runtime_bridge"]["status"],
            "applied",
        )
        self.assertEqual(
            hook.glossary_plan["prepared_package_runtime_bridge"][
                "source_ref_mismatch_count"
            ],
            1,
        )
        self.assertEqual(
            hook.glossary_plan["prepared_package_runtime_bridge"][
                "source_refs_required_when_present"
            ],
            False,
        )
        self.assertEqual(len(hook.prompt_context_entries), 1)
        self.assertEqual(
            hook.glossary_plan["work_unit_plans"][0]["selected_entry_ids"],
            ["entry:chrono-loom"],
        )

    def test_prepared_package_risky_alias_only_match_falls_back(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(source_block_ids=("chapter-1:p1",)),
            source_text="The river moved quickly.",
            prepared_package_payload=_prepared_package_payload(
                source_entry_id="entry:arcadian-society",
                source_canonical="Arcadian Society",
                aliases=("river",),
                evidence_refs=("evidence:arcadian",),
                source_unit_refs=(1,),
                source_block_refs=("chapter-1:p1",),
                target_canonical="Аркадийское общество",
                target_variants=("Аркадийское общество",),
            ),
            document_kind="epub",
            config=_generic_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "fallback")
        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_glossary_prepared_package_no_applicable_entries",
        )
        self.assertEqual(
            hook.glossary_plan["prepared_package_runtime_bridge"][
                "source_risky_alias_only_count"
            ],
            1,
        )
        self.assertTrue(
            hook.glossary_plan["prepared_package_runtime_bridge"][
                "risky_alias_only_skipped"
            ]
        )
        self.assertIn(
            "prepared_package_runtime_bridge_risky_alias_only",
            hook.glossary_plan["prepared_package_runtime_bridge"]["reason_codes"],
        )
        self.assertEqual(hook.prompt_context_entries, ())

    def test_prepared_package_ambiguous_canonical_token_alias_only_falls_back(self):
        # The applicability guard is intentionally local to the current work unit:
        # a shared single-token alias from a multi-token canonical term is unsafe
        # when only the alias appears in this unit and the canonical term is absent.
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(source_block_ids=("chapter-1:p1",)),
            source_text="Charlotte waited beside the gate.",
            prepared_package_payload=_prepared_package_payload(
                source_entry_id="entry:charlotte-winterbourne",
                source_canonical="Charlotte Winterbourne",
                aliases=("Charlotte",),
                evidence_refs=("evidence:charlotte-winterbourne",),
                source_unit_refs=(1,),
                source_block_refs=("chapter-1:p1",),
                target_canonical="Шарлотта Уинтерборн",
                target_variants=("Шарлотта Уинтерборн",),
            ),
            document_kind="epub",
            config=_generic_enabled_config(),
        )

        plan = hook.glossary_plan
        assert plan is not None
        self.assertEqual(plan["status"], "fallback")
        self.assertEqual(hook.prompt_context_entries, ())
        bridge = plan["prepared_package_runtime_bridge"]
        self.assertEqual(bridge["source_risky_alias_only_count"], 0)
        self.assertFalse(bridge["risky_alias_only_skipped"])
        self.assertEqual(bridge["source_term_missing_count"], 1)
        self.assertIn(
            "candidate_quality_canonical_component_alias_pruned",
            plan["prepared_package"]["quality"]["reason_codes"],
        )
        serialized_plan = json.dumps(
            plan,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertNotIn("Charlotte waited beside the gate.", serialized_plan)
        self.assertNotIn("Шарлотта Уинтерборн", serialized_plan)

    def test_prepared_package_canonical_presence_allows_entry_after_alias_pruning(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(source_block_ids=("chapter-1:p1",)),
            source_text="Alice Winterbourne waited beside the gate.",
            prepared_package_payload=_prepared_package_payload(
                source_entry_id="entry:alice-winterbourne",
                source_canonical="Alice Winterbourne",
                aliases=("Alice",),
                evidence_refs=("evidence:alice-winterbourne",),
                source_unit_refs=(1,),
                source_block_refs=("chapter-1:p1",),
                target_canonical="Алиса Уинтерборн",
                target_variants=("Алиса Уинтерборн",),
            ),
            document_kind="epub",
            config=_generic_enabled_config(),
        )

        plan = hook.glossary_plan
        assert plan is not None
        self.assertEqual(plan["status"], "planned")
        self.assertEqual(len(hook.prompt_context_entries), 1)
        bridge = plan["prepared_package_runtime_bridge"]
        self.assertEqual(bridge["source_canonical_match_count"], 1)
        self.assertEqual(bridge["source_risky_alias_only_count"], 0)
        self.assertEqual(
            plan["work_unit_plans"][0]["selected_entry_ids"],
            ["entry:alice-winterbourne"],
        )

    def test_prepared_package_unique_single_token_alias_still_matches(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(source_block_ids=("chapter-1:p1",)),
            source_text="Lizzy laughed softly.",
            prepared_package_payload=_prepared_package_payload(
                source_entry_id="entry:elizabeth-bennet",
                source_canonical="Elizabeth Bennet",
                aliases=("Lizzy",),
                evidence_refs=("evidence:elizabeth-bennet",),
                source_unit_refs=(1,),
                source_block_refs=("chapter-1:p1",),
                target_canonical="Элизабет Беннет",
                target_variants=("Элизабет Беннет",),
            ),
            document_kind="epub",
            config=_generic_enabled_config(),
        )

        plan = hook.glossary_plan
        assert plan is not None
        self.assertEqual(plan["status"], "planned")
        bridge = plan["prepared_package_runtime_bridge"]
        self.assertEqual(bridge["source_safe_alias_match_count"], 1)
        self.assertEqual(bridge["source_risky_alias_only_count"], 0)
        self.assertEqual(len(hook.prompt_context_entries), 1)

    def test_prepared_package_multi_token_alias_still_matches(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(source_block_ids=("chapter-1:p1",)),
            source_text="Mr. Collins arrived before breakfast.",
            prepared_package_payload=_prepared_package_payload(
                source_entry_id="entry:william-collins",
                source_canonical="William Collins",
                aliases=("Mr. Collins",),
                evidence_refs=("evidence:william-collins",),
                source_unit_refs=(1,),
                source_block_refs=("chapter-1:p1",),
                target_canonical="Уильям Коллинз",
                target_variants=("мистер Коллинз",),
            ),
            document_kind="epub",
            config=_generic_enabled_config(),
        )

        plan = hook.glossary_plan
        assert plan is not None
        self.assertEqual(plan["status"], "planned")
        bridge = plan["prepared_package_runtime_bridge"]
        self.assertEqual(bridge["source_safe_alias_match_count"], 1)
        self.assertEqual(bridge["source_risky_alias_only_count"], 0)
        self.assertEqual(len(hook.prompt_context_entries), 1)

    def test_prepared_package_oversized_source_can_render_small_context(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(source_block_ids=("chapter-1:p1",)),
            source_text="Darcy returns with a sentence longer than the old limit.",
            prepared_package_payload=_prepared_package_payload(),
            document_kind="epub",
            config=_generic_enabled_config(max_source_characters=8),
        )

        self.assertEqual(hook.glossary_plan["status"], "planned")
        self.assertEqual(
            hook.glossary_plan["resolver_caps"]["max_source_characters"],
            8,
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

    def test_generic_prepared_package_ready_hook_supports_txt_and_docx(self):
        for document_kind in ("txt", "docx"):
            with self.subTest(document_kind=document_kind):
                hook = build_persistent_glossary_runtime_hook_from_prepared_package(
                    work_unit=_work_unit(),
                    source_text="Darcy returns.",
                    prepared_package_payload=_prepared_package_payload(),
                    document_kind=document_kind,
                    config=_generic_enabled_config(),
                )

                self.assertEqual(hook.glossary_plan["status"], "planned")
                self.assertEqual(hook.glossary_plan["document_format"], document_kind)
                self.assertEqual(
                    hook.glossary_plan["schema_version"],
                    "persistent-glossary-runtime-resolver-v1",
                )
                self.assertEqual(
                    hook.glossary_plan["prepared_package"]["status"],
                    "ready",
                )
                self.assertEqual(len(hook.prompt_context_entries), 1)

                serialized_plan = json.dumps(
                    hook.glossary_plan,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                self.assertNotIn("Darcy returns.", serialized_plan)
                self.assertNotIn("Дарси", serialized_plan)

    def test_generic_prepared_package_unsupported_kind_falls_back(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            prepared_package_payload=_prepared_package_payload(),
            document_kind="pdf",
            config=_generic_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "fallback")
        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_glossary_unsupported_document_kind",
        )
        self.assertEqual(hook.prompt_context_entries, ())

    def test_generic_prepared_package_source_absent_falls_back(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(),
            source_text="No matching source term here.",
            prepared_package_payload=_prepared_package_payload(),
            document_kind="txt",
            config=_generic_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "fallback")
        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_glossary_prepared_package_no_applicable_entries",
        )
        self.assertEqual(hook.prompt_context_entries, ())

    def test_generic_prepared_package_target_metadata_missing_falls_back(self):
        payload = _prepared_package_payload(target_canonical="", target_variants=())

        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            prepared_package_payload=payload,
            document_kind="txt",
            config=_generic_enabled_config(),
        )

        self.assertEqual(hook.glossary_plan["status"], "fallback")
        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_glossary_prepared_package_invalid",
        )
        self.assertIn(
            "prepared_glossary_package_target_missing",
            hook.glossary_plan["prepared_package"]["reason_codes"],
        )
        self.assertEqual(hook.prompt_context_entries, ())

    def test_generic_prepared_package_prompt_budget_falls_back(self):
        hook = build_persistent_glossary_runtime_hook_from_prepared_package(
            work_unit=_work_unit(),
            source_text="Darcy returns.",
            prepared_package_payload=_prepared_package_payload(),
            document_kind="docx",
            config=_generic_enabled_config(
                prompt_context_config=GlossaryPromptContextConfig(max_prompt_tokens=1),
            ),
        )

        self.assertEqual(hook.glossary_plan["status"], "fallback")
        self.assertEqual(
            hook.glossary_plan["fallback_reason"],
            "persistent_glossary_prompt_context_budget_exhausted",
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


def _generic_enabled_config(
    *,
    prompt_context_config: GlossaryPromptContextConfig | None = None,
    max_source_characters: int = 2_400,
) -> PersistentGlossaryResolverConfig:
    return PersistentGlossaryResolverConfig(
        enabled=True,
        owner_battle_test_enabled=True,
        prompt_context_config=prompt_context_config or GlossaryPromptContextConfig(),
        max_source_characters=max_source_characters,
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
    source_entry_id: str = "entry:darcy",
    source_canonical: str = "Darcy",
    aliases: tuple[str, ...] = ("Mr. Darcy",),
    evidence_refs: tuple[str, ...] = ("evidence:darcy",),
    source_unit_refs: tuple[int, ...] = (1,),
    source_block_refs: tuple[str, ...] = ("chapter-1:p1",),
    target_canonical: str = "Дарси",
    target_variants: tuple[str, ...] = ("мистер Дарси",),
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
                "source_entry_id": source_entry_id,
                "source_canonical": source_canonical,
                "aliases": list(aliases),
                "evidence_refs": list(evidence_refs),
                "source_unit_refs": list(source_unit_refs),
                "source_block_refs": list(source_block_refs),
                "target_canonical": target_canonical,
                "target_variants": list(target_variants),
                "forbidden_variants": ["Дэрси"],
                "strategy": "transcribe",
                "confidence": 0.91,
                "needs_review": needs_review,
                "reason_codes": ["needs_human_review"] if needs_review else [],
            }
        ],
    }


def _work_unit(
    *,
    source_block_ids: tuple[str, ...] = ("chapter-1:p1",),
) -> PersistentWorkUnit:
    now = datetime(2026, 6, 14, tzinfo=UTC)
    return PersistentWorkUnit(
        id="job-1:unit-1",
        job_id="job-1",
        sequence=1,
        source_block_ids=source_block_ids,
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
