import unittest

from translator_service.pricing import PriceEstimate, PricingRules, estimate_price
from translator_service.text_analysis import TextAnalysis


class PricingTest(unittest.TestCase):
    def test_estimates_price_from_token_volume_and_service_markup(self):
        estimate = estimate_price(
            TextAnalysis(
                character_count=4_000,
                estimated_input_tokens=1_000,
                fragment_count=3,
            ),
            PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
        )

        self.assertEqual(
            estimate,
            PriceEstimate(
                estimated_input_tokens=1_000,
                estimated_output_tokens=1_200,
                estimated_cost_usd=0.000784,
                price_usd=0.10,
            ),
        )

    def test_uses_markup_price_when_it_exceeds_minimum(self):
        estimate = estimate_price(
            TextAnalysis(
                character_count=4_000_000,
                estimated_input_tokens=1_000_000,
                fragment_count=500,
            ),
            PricingRules(
                deepseek_input_usd_per_million_tokens=0.28,
                expected_output_multiplier=1.2,
                service_markup_multiplier=3.0,
                minimum_price_usd=0.10,
            ),
        )

        self.assertEqual(estimate.estimated_output_tokens, 1_200_000)
        self.assertEqual(estimate.estimated_cost_usd, 0.784)
        self.assertEqual(estimate.price_usd, 2.35)


if __name__ == "__main__":
    unittest.main()
