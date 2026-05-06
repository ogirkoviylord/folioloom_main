import unittest

from translator_service.text_analysis import TextType, detect_text_type


class TextTypeDetectionTest(unittest.TestCase):
    def test_detects_technical_text(self):
        text_type = detect_text_type(
            "Set the API endpoint and pass the placeholder token to the callback handler."
        )

        self.assertEqual(text_type, TextType.TECHNICAL)

    def test_detects_business_legal_like_text(self):
        text_type = detect_text_type(
            "Acme B.V. shall deliver the materials by 15 March 2026 under this agreement."
        )

        self.assertEqual(text_type, TextType.BUSINESS_LEGAL_LIKE)

    def test_detects_scientific_academic_text(self):
        text_type = detect_text_type(
            "The results suggest a moderate correlation, but the sample size limits the conclusion."
        )

        self.assertEqual(text_type, TextType.SCIENTIFIC_ACADEMIC)

    def test_detects_journalistic_publicistic_text(self):
        text_type = detect_text_type(
            "Officials said the policy would be reviewed after public consultations."
        )

        self.assertEqual(text_type, TextType.JOURNALISTIC_PUBLICISTIC)

    def test_detects_literary_fiction_text(self):
        text_type = detect_text_type(
            "The room held its breath while the rain traced silver lines across the window."
        )

        self.assertEqual(text_type, TextType.LITERARY_FICTION)

    def test_detects_mixed_language_labeled_text(self):
        text_type = detect_text_type(
            "English: The endpoint failed. Polski: Zażółć gęślą jaźń. Nederlands: De klant bevestigde de bestelling."
        )

        self.assertEqual(text_type, TextType.MIXED_UNKNOWN)

    def test_falls_back_to_general_for_plain_text(self):
        text_type = detect_text_type("This chapter explains the main idea in simple terms.")

        self.assertEqual(text_type, TextType.GENERAL)


if __name__ == "__main__":
    unittest.main()
