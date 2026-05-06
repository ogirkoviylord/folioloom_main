import unittest

from translator_service.structure_optimizer import PromptTier
from translator_service.translation_cache import MemoryTranslationCache


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


if __name__ == "__main__":
    unittest.main()
