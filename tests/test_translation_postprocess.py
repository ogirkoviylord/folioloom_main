import unittest

from translator_service.translation_postprocess import (
    clean_inline_formatting_artifacts,
    normalize_python_like_code_layout,
)


class TranslationPostprocessTest(unittest.TestCase):
    def test_cleans_subscript_and_superscript_leaks_before_cyrillic_words(self):
        cleaned = clean_inline_formatting_artifacts(
            (
                "нижний индекс H2O subscript H2и верхний "
                "superscript x2индекс x2."
            ),
            target_language="ru",
        )

        self.assertEqual(
            cleaned,
            "нижний индекс H2O и верхний индекс x2.",
        )

    def test_does_not_change_non_cyrillic_targets(self):
        text = "subscript H2 and superscript x2 should stay in English."

        self.assertEqual(
            clean_inline_formatting_artifacts(text, target_language="en"),
            text,
        )

    def test_cleans_duplicated_formula_tail_after_protected_subscript_restore(self):
        cleaned = clean_inline_formatting_artifacts(
            "нижний индекс H2OO и верхний индекс x2.",
            target_language="ru",
        )

        self.assertEqual(cleaned, "нижний индекс H2O и верхний индекс x2.")

    def test_normalizes_german_oriented_guillemets_for_cyrillic_targets(self):
        cleaned = clean_inline_formatting_artifacts(
            (
                "»Воно ж відчинене«, почулося зсередини. "
                "Він сказав: »Я заблукав«."
            ),
            target_language="uk",
        )

        self.assertEqual(
            cleaned,
            (
                "«Воно ж відчинене», почулося зсередини. "
                "Він сказав: «Я заблукав»."
            ),
        )

    def test_keeps_german_oriented_guillemets_for_non_cyrillic_targets(self):
        text = "»It is open«, came the answer."

        self.assertEqual(
            clean_inline_formatting_artifacts(text, target_language="en"),
            text,
        )

    def test_keeps_adjacent_correct_ukrainian_quote_runs(self):
        text = "Він запитав: «Ну що?» «Я вже готовий», — відповів Карл."

        self.assertEqual(
            clean_inline_formatting_artifacts(text, target_language="uk"),
            text,
        )

    def test_localizes_standard_front_matter_labels_for_russian(self):
        cleaned = clean_inline_formatting_artifacts(
            (
                "Title: Звездный час\n"
                "Author: John W. Campbell, Jr.\n"
                "Illustrator: Jane Smith\n"
                "Language: English\n"
                "Credits: Distributed Proofreaders"
            ),
            target_language="ru",
        )

        self.assertEqual(
            cleaned,
            (
                "Название: Звездный час\n"
                "Автор: John W. Campbell, Jr.\n"
                "Иллюстратор: Jane Smith\n"
                "Язык: English\n"
                "Подготовка текста: Distributed Proofreaders"
            ),
        )

    def test_keeps_front_matter_labels_for_non_russian_targets(self):
        text = "Title: The Star\nAuthor: Someone"

        self.assertEqual(
            clean_inline_formatting_artifacts(text, target_language="uk"),
            text,
        )

    def test_localizes_footnotes_section_label_for_russian(self):
        self.assertEqual(
            clean_inline_formatting_artifacts("FOOTNOTES:", target_language="ru"),
            "Примечания:",
        )
        self.assertEqual(
            clean_inline_formatting_artifacts("Footnotes: 1", target_language="ru"),
            "Примечания: 1",
        )

    def test_keeps_footnotes_section_label_for_non_russian_targets(self):
        self.assertEqual(
            clean_inline_formatting_artifacts("FOOTNOTES:", target_language="uk"),
            "FOOTNOTES:",
        )

    def test_normalizes_squashed_python_like_pseudocode(self):
        normalized = normalize_python_like_code_layout(
            (
                "# Псевдокод в стиле Python: не должен переводиться как проза"
                "for chapter in book.chapters:    "
                "translated = llm.translate(chapter.text, target=\"nl\")    "
                "assert \"{{DO_NOT_TRANSLATE}}\" in translated    "
                "print(f\"{chapter.id}: {len(translated)} chars\")"
            )
        )

        self.assertEqual(
            normalized,
            (
                "# Псевдокод в стиле Python: не должен переводиться как проза\n"
                "for chapter in book.chapters:\n"
                "    translated = llm.translate(chapter.text, target=\"nl\")\n"
                "    assert \"{{DO_NOT_TRANSLATE}}\" in translated\n"
                "    print(f\"{chapter.id}: {len(translated)} chars\")"
            ),
        )


if __name__ == "__main__":
    unittest.main()
