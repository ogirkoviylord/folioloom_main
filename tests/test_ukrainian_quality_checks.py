import unittest

from translator_service.russian_quality import RussianQualityTrack
from translator_service.ukrainian_quality_checks import (
    UkrainianQualityIssue,
    check_ukrainian_translation_quality,
)


class UkrainianQualityChecksTest(unittest.TestCase):
    def test_passes_when_precision_invariants_and_natural_ukrainian_are_preserved(self):
        result = check_ukrainian_translation_quality(
            source_text=(
                "Acme B.V. shall deliver order ORD-2026-05 by 15 March 2026 "
                "for 1,234.50 € via https://example.com/v1/items/${API_TOKEN}."
            ),
            translated_text=(
                "Acme B.V. має доставити замовлення ORD-2026-05 до 15 березня 2026 "
                "на суму 1 234,50 € через https://example.com/v1/items/${API_TOKEN}."
            ),
            source_language="en",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.issues, ())

    def test_reports_missing_url_placeholder_and_identifier(self):
        result = check_ukrainian_translation_quality(
            source_text=(
                "Send ROW-001 to https://example.com/callback with ${API_TOKEN} "
                "and {{ customer_id }}."
            ),
            translated_text="Надішліть рядок до callback із токеном клієнта.",
            source_language="en",
            target_language="uk",
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
        result = check_ukrainian_translation_quality(
            source_text="Invoice INV-77 is due on 15 March 2026 for 1,234.50 € and 20%.",
            translated_text="Рахунок INV-77 треба оплатити 16 березня 2026 на суму 1 224,50 € і 20%.",
            source_language="en",
            target_language="uk",
            quality_track=RussianQualityTrack.PRECISION,
        )

        issue_codes = [issue.code for issue in result.issues]
        self.assertIn("missing_date", issue_codes)
        self.assertIn("missing_number", issue_codes)
        self.assertIn("missing_currency_amount", issue_codes)

    def test_reports_protected_marker_leakage_and_provider_commentary(self):
        result = check_ukrainian_translation_quality(
            source_text="The room held its breath.",
            translated_text="Ось переклад: Кімната затамувала подих ZXQPROTECTED0QXZ.",
            source_language="en",
            target_language="uk",
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertEqual(
            [issue.code for issue in result.issues],
            ["protected_marker_leaked", "provider_commentary"],
        )

    def test_reports_common_ukrainian_calques_and_surzhyk(self):
        result = check_ukrainian_translation_quality(
            source_text=(
                "He made a decision and participated in the project during the month. "
                "The following section is a high-level overview."
            ),
            translated_text=(
                "Він зробив рішення і прийняв участь у проєкті на протязі місяця. "
                "Слідуючий розділ являється високорівневим оглядом."
            ),
            source_language="en",
            target_language="uk",
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertEqual(
            [issue.source_fragment for issue in result.issues],
            [
                "зробив рішення",
                "прийняв участь",
                "на протязі",
                "слідуючий",
                "являється",
                "високорівневим оглядом",
            ],
        )
        self.assertTrue(all(issue.code == "ukrainian_calque" for issue in result.issues))

    def test_reports_obvious_untranslated_russian_residue(self):
        result = check_ukrainian_translation_quality(
            source_text="Она тихо закрыла дверь, и дом снова научился молчать.",
            translated_text="Она тихо закрыла дверь, і дім знову навчився мовчати.",
            source_language="ru",
            target_language="uk",
            quality_track=RussianQualityTrack.LITERARY,
        )

        self.assertEqual(
            [issue.code for issue in result.issues],
            ["untranslated_source_residue"],
        )

    def test_skips_ukrainian_quality_checks_for_non_ukrainian_target(self):
        result = check_ukrainian_translation_quality(
            source_text="Send ROW-001 to https://example.com/callback with ${API_TOKEN}.",
            translated_text="Send the row with the token.",
            source_language="en",
            target_language="de",
            quality_track=None,
        )

        self.assertTrue(result.passed)
        self.assertEqual(result.issues, ())

    def test_issue_objects_are_stable_value_objects(self):
        issue = UkrainianQualityIssue(
            code="ukrainian_calque",
            message="Avoid Russian calque in Ukrainian output.",
            severity="warning",
            source_fragment="приймати участь",
        )

        self.assertEqual(issue.code, "ukrainian_calque")
        self.assertEqual(issue.severity, "warning")
        self.assertEqual(issue.source_fragment, "приймати участь")


if __name__ == "__main__":
    unittest.main()
