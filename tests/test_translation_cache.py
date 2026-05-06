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
        original_signature = translation_cache.target_language_policy_signature

        try:
            translation_cache.target_language_policy_signature = (
                lambda target_language: f"{target_language}:russian-v1"
            )
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            translation_cache.target_language_policy_signature = (
                lambda target_language: f"{target_language}:russian-v2"
            )

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.target_language_policy_signature = original_signature

    def test_misses_when_detected_text_type_policy_changes(self):
        cache = MemoryTranslationCache()
        original_detector = translation_cache.detect_text_type

        try:
            translation_cache.detect_text_type = lambda text: TextType.GENERAL
            cache.put(
                source_texts=("Set the API endpoint.",),
                translated_texts=("Укажите API endpoint.",),
                source_language="en",
                target_language="ru",
                prompt_tier=PromptTier.PLAIN,
            )

            translation_cache.detect_text_type = lambda text: TextType.TECHNICAL

            self.assertIsNone(
                cache.get(
                    source_texts=("Set the API endpoint.",),
                    source_language="en",
                    target_language="ru",
                    prompt_tier=PromptTier.PLAIN,
                )
            )
        finally:
            translation_cache.detect_text_type = original_detector

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
