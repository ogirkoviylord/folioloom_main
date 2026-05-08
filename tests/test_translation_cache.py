from dataclasses import replace
import unittest

from translator_service.structure_optimizer import PromptTier
from translator_service.text_analysis import TextType
from translator_service.translation_cache import MemoryTranslationCache
import translator_service.translation_cache as translation_cache


class TranslationCacheTest(unittest.TestCase):
    def test_returns_cached_translation_for_same_language_pair_and_prompt_tier(self):
        cache = MemoryTranslationCache()

        cache.put(
            source_texts=("Repeated sentence.",),
            translated_texts=("Повторене речення.",),
            source_language="en",
            target_language="uk",
            prompt_tier=PromptTier.PLAIN,
        )

        self.assertEqual(
            cache.get(
                source_texts=("Repeated sentence.",),
                source_language="en",
                target_language="uk",
                prompt_tier=PromptTier.PLAIN,
            ),
            ("Повторене речення.",),
        )

    def test_misses_when_target_language_or_prompt_tier_changes(self):
        cache = MemoryTranslationCache()

        cache.put(
            source_texts=("Repeated sentence.",),
            translated_texts=("Повторене речення.",),
            source_language="en",
            target_language="uk",
            prompt_tier=PromptTier.PLAIN,
        )

        self.assertIsNone(
            cache.get(
                source_texts=("Repeated sentence.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )
        )
        self.assertIsNone(
            cache.get(
                source_texts=("Repeated sentence.",),
                source_language="en",
                target_language="uk",
                prompt_tier=PromptTier.STRICT,
            )
        )

    def test_evicts_oldest_entry_when_max_entries_is_reached(self):
        cache = MemoryTranslationCache(max_entries=1)
        cache.put(
            source_texts=("First sentence.",),
            translated_texts=("Перше речення.",),
            source_language="en",
            target_language="uk",
            prompt_tier=PromptTier.PLAIN,
        )
        cache.put(
            source_texts=("Second sentence.",),
            translated_texts=("Друге речення.",),
            source_language="en",
            target_language="uk",
            prompt_tier=PromptTier.PLAIN,
        )

        self.assertIsNone(
            cache.get(
                source_texts=("First sentence.",),
                source_language="en",
                target_language="uk",
                prompt_tier=PromptTier.PLAIN,
            )
        )
        self.assertEqual(
            cache.get(
                source_texts=("Second sentence.",),
                source_language="en",
                target_language="uk",
                prompt_tier=PromptTier.PLAIN,
            ),
            ("Друге речення.",),
        )

    def test_misses_when_target_language_policy_signature_changes(self):
        cache = MemoryTranslationCache()
        original_policy_builder = translation_cache.build_translation_policy

        try:
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            def changed_target_policy(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    target_language_policy="target-profile:ru:russian-v3",
                )

            translation_cache.build_translation_policy = changed_target_policy

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.build_translation_policy = original_policy_builder

    def test_misses_when_russian_quality_track_signature_changes(self):
        cache = MemoryTranslationCache()
        original_policy_builder = translation_cache.build_translation_policy

        try:
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            def changed_russian_quality_track(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    russian_quality_track_signature="russian-quality:literary-v1",
                )

            translation_cache.build_translation_policy = changed_russian_quality_track

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.build_translation_policy = original_policy_builder

    def test_misses_when_source_pair_policy_signature_changes(self):
        cache = MemoryTranslationCache()
        original_policy_builder = translation_cache.build_translation_policy

        try:
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            def changed_source_pair_policy(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    source_pair_policy="source-pair:en-ru:v2",
                )

            translation_cache.build_translation_policy = changed_source_pair_policy

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.build_translation_policy = original_policy_builder

    def test_ukrainian_target_language_policy_signature_is_in_cache_key(self):
        policy = translation_cache.build_translation_policy(
            text="Set the API endpoint.",
            source_language="en",
            target_language="uk",
        )

        signature = translation_cache.translation_policy_signature(policy)

        self.assertIn("target-profile:uk:ukrainian-v1", signature)
        self.assertIn("source-pair:en-uk:v1", signature)

    def test_misses_when_entity_ledger_signature_changes(self):
        cache = MemoryTranslationCache()
        original_policy_builder = translation_cache.build_translation_policy

        try:
            cache.put(
                source_texts=("Acme B.V. signed the agreement.",),
                translated_texts=("Acme B.V. подписала соглашение.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            def changed_entity_ledger(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    entity_ledger_signature="entity-ledger:v1:test-changed",
                )

            translation_cache.build_translation_policy = changed_entity_ledger

            self.assertIsNone(
                cache.get(
                    source_texts=("Acme B.V. signed the agreement.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.build_translation_policy = original_policy_builder

    def test_misses_when_detected_text_type_policy_changes(self):
        cache = MemoryTranslationCache()
        original_policy_builder = translation_cache.build_translation_policy

        try:
            def general_policy(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    text_type=TextType.GENERAL,
                )

            translation_cache.build_translation_policy = general_policy
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            def technical_policy(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    text_type=TextType.TECHNICAL,
                )

            translation_cache.build_translation_policy = technical_policy

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.build_translation_policy = original_policy_builder

    def test_misses_when_prompt_policy_version_changes(self):
        cache = MemoryTranslationCache()
        original_policy_builder = translation_cache.build_translation_policy

        try:
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            def changed_prompt_policy(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    prompt_policy_version="prompt-policy-test-changed",
                )

            translation_cache.build_translation_policy = changed_prompt_policy

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.build_translation_policy = original_policy_builder

    def test_misses_when_protection_policy_version_changes(self):
        cache = MemoryTranslationCache()
        original_policy_builder = translation_cache.build_translation_policy

        try:
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            def changed_protection_policy(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    protection_policy_version="protection-policy-test-changed",
                )

            translation_cache.build_translation_policy = changed_protection_policy

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.build_translation_policy = original_policy_builder

    def test_misses_when_output_contract_changes(self):
        cache = MemoryTranslationCache()
        original_policy_builder = translation_cache.build_translation_policy

        try:
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            def changed_output_contract(**kwargs):
                return replace(
                    original_policy_builder(**kwargs),
                    output_contract_signature="translation-batch-v2",
                )

            translation_cache.build_translation_policy = changed_output_contract

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.build_translation_policy = original_policy_builder

    def test_returns_cached_translation_when_detected_text_type_policy_is_same(self):
        cache = MemoryTranslationCache()

        cache.put(
            source_texts=("Set the API endpoint.",),
            translated_texts=("Укажите API endpoint.",),
            source_language="en",
            target_language="ru",
            prompt_tier=PromptTier.PLAIN,
        )

        self.assertEqual(
            cache.get(
                source_texts=("Set the API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            ),
            ("Укажите API endpoint.",),
        )


if __name__ == "__main__":
    unittest.main()
