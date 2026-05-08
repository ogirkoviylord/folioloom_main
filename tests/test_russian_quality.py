import unittest

from translator_service.russian_quality import (
    RussianQualityTrack,
    detect_russian_quality_track,
    russian_quality_track_signature,
)


class RussianQualityTest(unittest.TestCase):
    def test_detects_literary_track_for_imagery_and_dialogue(self):
        decision = detect_russian_quality_track(
            '"Where are you going?" she whispered while the rain traced silver lines across the window.',
            target_language="ru",
        )

        self.assertEqual(decision.track, RussianQualityTrack.LITERARY)
        self.assertGreater(decision.confidence, 0.5)
        self.assertIn("literary_signals", decision.reasons)

    def test_detects_precision_track_for_api_dates_and_obligations(self):
        decision = detect_russian_quality_track(
            "Acme B.V. shall deliver API materials by 15 March 2026 to https://example.com/v1/items.",
            target_language="ru",
        )

        self.assertEqual(decision.track, RussianQualityTrack.PRECISION)
        self.assertGreater(decision.confidence, 0.5)
        self.assertIn("precision_signals", decision.reasons)

    def test_uses_precision_track_for_ambiguous_russian_target(self):
        decision = detect_russian_quality_track(
            "This is a plain paragraph without strong genre signals.",
            target_language="ru",
        )

        self.assertEqual(decision.track, RussianQualityTrack.PRECISION)
        self.assertEqual(decision.reasons, ("conservative_fallback",))

    def test_non_russian_target_uses_no_russian_track(self):
        decision = detect_russian_quality_track(
            "The room held its breath.",
            target_language="uk",
        )

        self.assertIsNone(decision.track)
        self.assertEqual(decision.reasons, ())

    def test_signature_is_stable(self):
        self.assertEqual(
            russian_quality_track_signature(RussianQualityTrack.LITERARY),
            "russian-quality:literary-v1",
        )
        self.assertEqual(
            russian_quality_track_signature(RussianQualityTrack.PRECISION),
            "russian-quality:precision-v1",
        )
        self.assertEqual(
            russian_quality_track_signature(None),
            "russian-quality:none",
        )


if __name__ == "__main__":
    unittest.main()
