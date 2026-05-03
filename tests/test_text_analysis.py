import unittest

from translator_service.text_analysis import (
    TextAnalysis,
    estimate_text_volume,
    split_text_into_fragments,
)


class TextAnalysisTest(unittest.TestCase):
    def test_estimates_characters_tokens_and_fragments(self):
        text = "Первый абзац.\n\nВторой абзац длиннее."

        analysis = estimate_text_volume(text, max_fragment_chars=20)

        self.assertEqual(
            analysis,
            TextAnalysis(
                character_count=36,
                estimated_input_tokens=9,
                fragment_count=2,
            ),
        )

    def test_ignores_surrounding_whitespace_when_estimating(self):
        analysis = estimate_text_volume("  текст  \n", max_fragment_chars=100)

        self.assertEqual(analysis.character_count, 5)
        self.assertEqual(analysis.estimated_input_tokens, 2)
        self.assertEqual(analysis.fragment_count, 1)

    def test_splits_text_without_breaking_paragraph_order(self):
        fragments = split_text_into_fragments(
            "Первый абзац.\n\nВторой абзац.\n\nТретий абзац.",
            max_fragment_chars=30,
        )

        self.assertEqual(
            fragments,
            [
                "Первый абзац.\n\nВторой абзац.",
                "Третий абзац.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
