import unittest

from translator_service.russian_quality import RussianQualityTrack
from translator_service.russian_quality_checks import (
    RussianQualityIssue,
    check_russian_translation_quality,
)


class RussianQualityChecksTest(unittest.TestCase):
    def test_passes_when_precision_invariants_are_preserved(self):
        result = check_russian_translation_quality(
            source_text=(
                "Acme B.V. shall deliver order ORD-2026-05 by 15 March 2026 "
                "for 1,234.50 € via https://example.com/v1/items/${API_TOKEN}."
            ),
            translated_text=(
                "Acme B.V. должна доставить заказ ORD-2026-05 до 15 марта 2026 "
                "на сумму 1 234,50 € через https://example.com/v1/items/${API_TOKEN}."
            ),
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.issues, ())

    def test_reports_missing_url_placeholder_and_identifier(self):
        result = check_russian_translation_quality(
            source_text=(
                "Send ROW-001 to https://example.com/callback with ${API_TOKEN} "
                "and {{ customer_id }}."
            ),
            translated_text="Отправьте строку в callback с токеном клиента.",
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertEqual(
            [issue.code for issue in result.issues],
            [
                "missing_url",
                "missing_placeholder",
                "missing_placeholder",
                "missing_identifier",
            ],
        )
        self.assertFalse(result.passed)

    def test_reports_changed_numbers_dates_and_currency(self):
        result = check_russian_translation_quality(
            source_text="Invoice INV-77 is due on 15 March 2026 for 1,234.50 € and 20%.",
            translated_text="Счет INV-77 должен быть оплачен 16 марта 2026 на сумму 1 224,50 € и 20%.",
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
        )

        issue_codes = [issue.code for issue in result.issues]
        self.assertIn("missing_date", issue_codes)
        self.assertIn("missing_number", issue_codes)
        self.assertIn("missing_currency_amount", issue_codes)

    def test_reports_protected_marker_leakage(self):
        result = check_russian_translation_quality(
            source_text="The customer name should appear here.",
            translated_text="Имя клиента должно быть здесь: ZXQPROTECTED0QXZ.",
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertEqual([issue.code for issue in result.issues], ["protected_marker_leaked"])

    def test_reports_provider_commentary_wrappers(self):
        result = check_russian_translation_quality(
            source_text="The room held its breath.",
            translated_text="Вот перевод: Комната затаила дыхание.",
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertEqual([issue.code for issue in result.issues], ["provider_commentary"])

    def test_reports_obvious_untranslated_secondary_language_residue(self):
        result = check_russian_translation_quality(
            source_text="Українська: Вона тихо зачинила двері, і дім знову навчився мовчати.",
            translated_text="Вона тихо зачинила двері, і дім знову навчився мовчати.",
            source_language="uk",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertEqual(
            [issue.code for issue in result.issues],
            ["untranslated_source_residue"],
        )

    def test_reports_mixed_english_residue_for_russian_target(self):
        result = check_russian_translation_quality(
            source_text=(
                "Warger was to assert that he had reliable information that "
                "Mussolini had died of a serious disease."
            ),
            translated_text=(
                "Варгер должен был assert that he had reliable information that "
                "Mussolini had died of a serious disease."
            ),
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertEqual(
            [issue.code for issue in result.issues],
            ["untranslated_source_residue"],
        )

    def test_reports_english_drop_cap_residue_for_russian_target(self):
        result = check_russian_translation_quality(
            source_text="On the morning the streets of Vienna were lively.",
            translated_text="ON THE утром улицы Вены оживляло шествие.",
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertEqual(
            [issue.code for issue in result.issues],
            ["untranslated_source_residue"],
        )

    def test_allows_latin_names_and_acronyms_in_russian_translation(self):
        result = check_russian_translation_quality(
            source_text="Otto Skorzeny reported to FHQ with Waffen-SS officers.",
            translated_text="Отто Skorzeny доложил в FHQ вместе с офицерами Waffen-SS.",
            source_language="en",
            target_language="ru",
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.issues, ())

    def test_skips_russian_quality_checks_for_non_russian_target(self):
        result = check_russian_translation_quality(
            source_text="Send ROW-001 to https://example.com/callback with ${API_TOKEN}.",
            translated_text="Send the row with the token.",
            source_language="en",
            target_language="de",
            quality_track=None,
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.issues, ())

    def test_issue_objects_are_stable_value_objects(self):
        issue = RussianQualityIssue(
            code="missing_url",
            message="Required URL is missing.",
            severity="error",
            source_fragment="https://example.com",
        )

        self.assertEqual(issue.code, "missing_url")
        self.assertEqual(issue.severity, "error")
        self.assertEqual(issue.source_fragment, "https://example.com")


if __name__ == "__main__":
    unittest.main()
