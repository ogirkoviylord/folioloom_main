import unittest

from translator_service.beta_safety import (
    BETA_SAFETY_ALLOWED,
    BETA_SAFETY_GLOBAL_DAILY_CAP,
    BETA_SAFETY_GLOBAL_MONTHLY_CAP,
    BETA_SAFETY_JOB_ESTIMATE_CAP,
    BETA_SAFETY_KILL_SWITCH,
    BETA_SAFETY_USER_DAILY_CAP,
    BETA_SAFETY_USER_DAILY_JOB_LIMIT,
    BETA_SAFETY_USER_MONTHLY_CAP,
    BetaSafetyLimits,
    BetaSafetyRates,
    BudgetSnapshot,
    JobCostEstimate,
    decide_beta_safety,
    estimate_cost_usd,
)


class BetaSafetyDecisionTest(unittest.TestCase):
    def test_estimates_cost_from_prompt_and_completion_tokens(self):
        rates = BetaSafetyRates(
            input_usd_per_million=0.28,
            output_usd_per_million=1.10,
        )

        self.assertEqual(
            estimate_cost_usd(
                prompt_tokens=1_000_000,
                completion_tokens=500_000,
                rates=rates,
            ),
            0.83,
        )

    def test_allows_when_estimate_fits_remaining_budget(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.001,
            ),
            limits=BetaSafetyLimits(
                translations_paused=False,
                global_daily_cost_cap_usd=5.0,
                global_monthly_cost_cap_usd=50.0,
                user_daily_cost_cap_usd=1.0,
                user_monthly_cost_cap_usd=10.0,
                user_daily_job_limit=3,
                max_job_estimated_cost_usd=2.0,
                warning_fraction=0.8,
            ),
            budget=BudgetSnapshot(
                global_daily_reserved_usd=1.0,
                global_daily_consumed_usd=1.0,
                global_monthly_reserved_usd=10.0,
                global_monthly_consumed_usd=10.0,
                user_daily_reserved_usd=0.1,
                user_daily_consumed_usd=0.2,
                user_monthly_reserved_usd=1.0,
                user_monthly_consumed_usd=1.0,
                user_daily_active_jobs=1,
            ),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_ALLOWED)

    def test_allows_when_decimal_amounts_exactly_fit_cap(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.2,
            ),
            limits=BetaSafetyLimits(
                global_daily_cost_cap_usd=0.3,
                global_monthly_cost_cap_usd=None,
                user_daily_cost_cap_usd=None,
                user_monthly_cost_cap_usd=None,
                max_job_estimated_cost_usd=None,
            ),
            budget=BudgetSnapshot(global_daily_reserved_usd=0.1),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_ALLOWED)

    def test_none_cost_caps_are_disabled(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=100.0,
            ),
            limits=BetaSafetyLimits(
                global_daily_cost_cap_usd=None,
                global_monthly_cost_cap_usd=None,
                user_daily_cost_cap_usd=None,
                user_monthly_cost_cap_usd=None,
                max_job_estimated_cost_usd=None,
            ),
            budget=BudgetSnapshot(
                global_daily_reserved_usd=1000.0,
                global_daily_consumed_usd=1000.0,
                global_monthly_reserved_usd=1000.0,
                global_monthly_consumed_usd=1000.0,
                user_daily_reserved_usd=1000.0,
                user_daily_consumed_usd=1000.0,
                user_monthly_reserved_usd=1000.0,
                user_monthly_consumed_usd=1000.0,
            ),
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_ALLOWED)

    def test_blocks_when_kill_switch_is_active(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.001,
            ),
            limits=BetaSafetyLimits(translations_paused=True),
            budget=BudgetSnapshot(),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_KILL_SWITCH)

    def test_blocks_when_job_estimate_exceeds_max_job_cap(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1_000_000,
                completion_tokens=1_000_000,
                estimated_cost_usd=3.0,
            ),
            limits=BetaSafetyLimits(max_job_estimated_cost_usd=2.0),
            budget=BudgetSnapshot(),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_JOB_ESTIMATE_CAP)

    def test_blocks_when_user_daily_job_limit_is_reached(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.20,
            ),
            limits=BetaSafetyLimits(
                user_daily_job_limit=3,
                global_daily_cost_cap_usd=1.0,
            ),
            budget=BudgetSnapshot(
                user_daily_active_jobs=3,
                global_daily_reserved_usd=0.9,
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_USER_DAILY_JOB_LIMIT)

    def test_blocks_when_global_daily_budget_would_be_exceeded(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.20,
            ),
            limits=BetaSafetyLimits(global_daily_cost_cap_usd=5.0),
            budget=BudgetSnapshot(
                global_daily_reserved_usd=2.0,
                global_daily_consumed_usd=2.9,
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_GLOBAL_DAILY_CAP)

    def test_blocks_when_global_monthly_budget_would_be_exceeded(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.20,
            ),
            limits=BetaSafetyLimits(global_monthly_cost_cap_usd=50.0),
            budget=BudgetSnapshot(
                global_monthly_reserved_usd=10.0,
                global_monthly_consumed_usd=39.9,
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_GLOBAL_MONTHLY_CAP)

    def test_blocks_when_user_daily_budget_would_be_exceeded(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.20,
            ),
            limits=BetaSafetyLimits(user_daily_cost_cap_usd=1.0),
            budget=BudgetSnapshot(
                user_daily_reserved_usd=0.4,
                user_daily_consumed_usd=0.5,
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_USER_DAILY_CAP)

    def test_blocks_when_user_monthly_budget_would_be_exceeded(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=500,
                estimated_cost_usd=0.20,
            ),
            limits=BetaSafetyLimits(user_monthly_cost_cap_usd=10.0),
            budget=BudgetSnapshot(
                user_monthly_reserved_usd=1.0,
                user_monthly_consumed_usd=8.9,
            ),
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason_code, BETA_SAFETY_USER_MONTHLY_CAP)

    def test_safe_message_does_not_include_job_counts_or_cost_details(self):
        decision = decide_beta_safety(
            estimate=JobCostEstimate(
                prompt_tokens=1234,
                completion_tokens=5678,
                estimated_cost_usd=9.99,
            ),
            limits=BetaSafetyLimits(max_job_estimated_cost_usd=2.0),
            budget=BudgetSnapshot(),
        )

        self.assertNotIn("1234", decision.safe_message)
        self.assertNotIn("5678", decision.safe_message)
        self.assertNotIn("9.99", decision.safe_message)


if __name__ == "__main__":
    unittest.main()
