import unittest

from translator_service.protected_text import protect_text, restore_protected_text


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
            'translated = llm.translate(chapter.text, target="nl"); print(f"{chapter.id}")'
        )

        self.assertIn("translated =", protected.replacements.values())
        self.assertIn('llm.translate(chapter.text, target="nl")', protected.replacements.values())
        self.assertIn('print(f"{chapter.id}")', protected.replacements.values())

    def test_does_not_globally_protect_note_terms_in_normal_prose(self):
        protected = protect_text(
            "Footnote marker lives here and endnote marker lives here."
        )

        self.assertNotIn("Footnote", protected.replacements.values())
        self.assertNotIn("endnote", protected.replacements.values())


if __name__ == "__main__":
    unittest.main()
