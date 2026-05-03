from dataclasses import dataclass

from translator_service.text_analysis import TextAnalysis


@dataclass(frozen=True)
class PricingRules:
    deepseek_input_usd_per_million_tokens: float
    expected_output_multiplier: float
    service_markup_multiplier: float
    minimum_price_usd: float


@dataclass(frozen=True)
class PriceEstimate:
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    price_usd: float


def estimate_price(
    analysis: TextAnalysis,
    rules: PricingRules,
) -> PriceEstimate:
    estimated_output_tokens = round(
        analysis.estimated_input_tokens * rules.expected_output_multiplier
    )
    estimated_cost_usd = round(
        (
            analysis.estimated_input_tokens
            * rules.deepseek_input_usd_per_million_tokens
            / 1_000_000
        )
        + (estimated_output_tokens * 0.42 / 1_000_000),
        6,
    )
    price_usd = max(
        rules.minimum_price_usd,
        round(estimated_cost_usd * rules.service_markup_multiplier, 2),
    )

    return PriceEstimate(
        estimated_input_tokens=analysis.estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        estimated_cost_usd=estimated_cost_usd,
        price_usd=price_usd,
    )

