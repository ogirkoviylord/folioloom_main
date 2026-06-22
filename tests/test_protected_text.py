import unittest

from translator_service.protected_text import (
    count_protected_marker_residues,
    protect_text,
    restore_protected_text,
)


class ProtectedTextTest(unittest.TestCase):
    def test_url_protection_leaves_trailing_sentence_punctuation_outside_marker(self):
        protected = protect_text(
            "URLs like https://example.org/a/b?c=d, and punctuation."
        )

        self.assertEqual(
            protected.text,
            "URLs like ZXQPROTECTED0QXZ, and punctuation.",
        )

        restored = restore_protected_text(
            "URL-адреса, такие как ZXQPROTECTED0QXZ, и пунктуация.",
            protected.replacements,
        )

        self.assertEqual(
            restored,
            "URL-адреса, такие как https://example.org/a/b?c=d, и пунктуация.",
        )

    def test_protects_common_inline_code_expressions(self):
        protected = protect_text(
            'translated = llm.translate(chapter.text, target="nl"); '
            'print(f"{chapter.id}")'
        )

        self.assertIn("translated =", protected.replacements.values())
        self.assertIn(
            'llm.translate(chapter.text, target="nl")',
            protected.replacements.values(),
        )
        self.assertIn('print(f"{chapter.id}")', protected.replacements.values())

    def test_does_not_globally_protect_note_terms_in_normal_prose(self):
        protected = protect_text(
            "Footnote marker lives here and endnote marker lives here."
        )

        self.assertNotIn("Footnote", protected.replacements.values())
        self.assertNotIn("endnote", protected.replacements.values())

    def test_literary_heading_context_keeps_words_translatable_but_markers_stable(self):
        protected = protect_text("CHAPTER I API_TOKEN", literary_heading=True)

        self.assertIn("CHAPTER ", protected.text)
        self.assertNotIn("CHAPTER", protected.replacements.values())
        self.assertIn("I", protected.replacements.values())
        self.assertIn("API_TOKEN", protected.replacements.values())

    def test_literary_heading_context_preserves_technical_acronyms(self):
        protected = protect_text(
            "BOOK IV API URL HTTP JSON XML",
            literary_heading=True,
        )

        self.assertNotIn("", protected.replacements.values())
        self.assertNotIn("BOOK", protected.replacements.values())
        for token in ("IV", "API", "URL", "HTTP", "JSON", "XML"):
            self.assertIn(token, protected.replacements.values())

    def test_literary_heading_context_keeps_table_of_contents_translatable(self):
        protected = protect_text("TABLE OF CONTENTS API", literary_heading=True)

        self.assertIn("TABLE OF CONTENTS ", protected.text)
        for word in ("TABLE", "OF", "CONTENTS"):
            self.assertNotIn(word, protected.replacements.values())
        self.assertIn("API", protected.replacements.values())

    def test_literary_heading_context_keeps_ordinary_all_caps_titles_translatable(self):
        protected = protect_text(
            "A PHANTOM; MODERN PILGRIMS; SIGNS AND WONDERS; PARTING API_TOKEN",
            literary_heading=True,
        )

        self.assertIn("A PHANTOM", protected.text)
        self.assertIn("MODERN PILGRIMS", protected.text)
        self.assertIn("SIGNS AND WONDERS", protected.text)
        self.assertIn("PARTING ", protected.text)
        for word in (
            "PHANTOM",
            "MODERN",
            "PILGRIMS",
            "SIGNS",
            "AND",
            "WONDERS",
            "PARTING",
        ):
            self.assertNotIn(word, protected.replacements.values())
        self.assertIn("API_TOKEN", protected.replacements.values())

    def test_literary_heading_keeps_pg17460_short_title_words_translatable(self):
        labels = (
            "A BOY AND A GIRL",
            "JOHN IS BEWITCHED",
            "JOHN FRY'S ERRAND",
            "COLD COMFORT",
            "THE WAR-PATH OF THE DOONES",
            "QUO WARRANTO?",
        )

        for label in labels:
            with self.subTest(label=label):
                protected = protect_text(label, literary_heading=True)
                self.assertEqual(protected.text, label)
                self.assertEqual(protected.replacements, {})

    def test_literary_heading_preserves_hyphenated_technical_controls(self):
        protected = protect_text("API-KEY WAR-PATH", literary_heading=True)

        self.assertIn("API-KEY", protected.replacements.values())
        self.assertIn("WAR-PATH", protected.text)
        self.assertNotIn("WAR-PATH", protected.replacements.values())

    def test_literary_heading_rejects_mixed_case_source_for_short_words(self):
        protected = protect_text("Chapter title BOY", literary_heading=True)

        self.assertIn("BOY", protected.replacements.values())

    def test_literary_heading_rejects_technical_source_for_short_words(self):
        cases = (
            ("OPS/nav.xhtml BOY", ("OPS", "BOY")),
            ("config.json BOY", ("BOY",)),
            ("https://example.org/BOY BOY", ("https://example.org/BOY", "BOY")),
            ("BOY @ HOME", ("BOY", "HOME")),
        )

        for source_text, expected_protected in cases:
            with self.subTest(source_text=source_text):
                protected = protect_text(source_text, literary_heading=True)
                for token in expected_protected:
                    self.assertIn(token, protected.replacements.values())

    def test_literary_heading_rejects_code_like_source_for_short_words(self):
        cases = (
            ("print(BOY)", "print(BOY)"),
            ("`BOY`", "`BOY`"),
            ("return BOY", "BOY"),
            ("BOY=1", "BOY="),
        )

        for source_text, expected_protected in cases:
            with self.subTest(source_text=source_text):
                protected = protect_text(source_text, literary_heading=True)
                self.assertNotIn("BOY", protected.text)
                self.assertIn(expected_protected, protected.replacements.values())

    def test_literary_heading_context_keeps_short_title_controls_protected(self):
        protected = protect_text(
            "API URL HTTP JSON XML NCX OPF ISBN API_TOKEN I IV OPS/nav.xhtml",
            literary_heading=True,
        )

        for token in (
            "API",
            "URL",
            "HTTP",
            "JSON",
            "XML",
            "NCX",
            "OPF",
            "ISBN",
            "API_TOKEN",
            "I",
            "IV",
            "OPS",
        ):
            self.assertIn(token, protected.replacements.values())

    def test_literary_heading_context_never_creates_empty_replacements(self):
        protected = protect_text("XML", literary_heading=True)

        self.assertNotIn("", protected.replacements.values())
        self.assertEqual(protected.replacements, {"ZXQPROTECTED0QXZ": "XML"})

    def test_default_context_still_protects_all_caps_words(self):
        protected = protect_text("BOOK ONE: 1805")

        self.assertIn("BOOK", protected.replacements.values())
        self.assertIn("ONE", protected.replacements.values())

    def test_restore_repairs_hyphenated_protected_marker_variant(self):
        restored = restore_protected_text(
            "Название ZXQ-PROTECTED-0-QXZ",
            {"ZXQPROTECTED0QXZ": "API_TOKEN"},
        )

        self.assertEqual(restored, "Название API_TOKEN")
        self.assertNotIn("ZXQ", restored)

    def test_counts_exact_mutated_and_truncated_protected_marker_residue(self):
        cases = (
            "ZXQPROTECTED0QXZ",
            "ZXQ-PROTECTED-0-QXZ",
            "Заголовок ZXQPROTECTED0",
        )

        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(count_protected_marker_residues(text), 1)

        self.assertEqual(count_protected_marker_residues("Защищенный текст"), 0)


if __name__ == "__main__":
    unittest.main()
