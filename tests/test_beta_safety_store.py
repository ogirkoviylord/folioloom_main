import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from translator_service.beta_safety import (
    BETA_SAFETY_ALLOWED,
    BETA_SAFETY_GLOBAL_DAILY_CAP,
    BETA_SAFETY_KILL_SWITCH,
    BETA_SAFETY_RESERVATION_EXISTS,
    BetaSafetyLimits,
    BetaSafetyRates,
    JobCostEstimate,
)
from translator_service.beta_safety_store import (
    RESERVATION_ACTIVE,
    RESERVATION_CONSUMED,
    RESERVATION_RELEASED,
    ConfiguredBetaSafetyGuard,
    SQLiteBetaSafetyStore,
)
from translator_service.bot.runtime import BotRuntimeConfig, build_beta_safety_guard


class SQLiteBetaSafetyStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "beta-safety.sqlite3"
        self.store = SQLiteBetaSafetyStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_reserve_job_is_atomic_against_global_daily_cap(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        limits = BetaSafetyLimits(
            global_daily_cost_cap_usd=1.0,
            user_daily_cost_cap_usd=None,
            user_monthly_cost_cap_usd=None,
        )

        first = self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.75,
            ),
            limits=limits,
            rates=BetaSafetyRates(),
            now=now,
        )
        second = self.store.reserve_job(
            job_id="job-b",
            user_id="user-2",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.50,
            ),
            limits=limits,
            rates=BetaSafetyRates(),
            now=now,
        )

        self.assertEqual(first.reason_code, BETA_SAFETY_ALLOWED)
        self.assertEqual(second.reason_code, BETA_SAFETY_GLOBAL_DAILY_CAP)

    def test_release_job_removes_active_reservation_from_budget(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.75,
            ),
            limits=BetaSafetyLimits(),
            rates=BetaSafetyRates(),
            now=now,
        )

        self.store.release_job(job_id="job-a", reason="cancelled", now=now)

        reservation = self.store.get_reservation("job-a")
        summary = self.store.get_budget_summary(user_id="user-1", now=now)
        self.assertEqual(reservation.status, RESERVATION_RELEASED)
        self.assertEqual(summary.user_daily_reserved_usd, 0.0)

    def test_active_reservation_survives_reopened_store(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        self._reserve("job-a", "user-1", 0.75, now)
        self.store.close()

        self.store = SQLiteBetaSafetyStore(self.db_path)
        reservation = self.store.get_reservation("job-a")
        duplicate = self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.75,
            ),
            limits=BetaSafetyLimits(),
            rates=BetaSafetyRates(),
            now=now,
        )
        summary = self.store.get_budget_summary(user_id="user-1", now=now)

        assert reservation is not None
        self.assertEqual(reservation.status, RESERVATION_ACTIVE)
        self.assertEqual(duplicate.reason_code, BETA_SAFETY_RESERVATION_EXISTS)
        self.assertEqual(summary.user_daily_reserved_usd, 0.75)

    def test_released_reservation_survives_reopened_store(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        self._reserve("job-a", "user-1", 0.75, now)
        self.store.release_job(job_id="job-a", reason="cancelled", now=now)
        self.store.close()

        self.store = SQLiteBetaSafetyStore(self.db_path)
        reservation = self.store.get_reservation("job-a")
        summary = self.store.get_budget_summary(user_id="user-1", now=now)

        assert reservation is not None
        self.assertEqual(reservation.status, RESERVATION_RELEASED)
        self.assertEqual(reservation.reason, "cancelled")
        self.assertEqual(summary.user_daily_reserved_usd, 0.0)

    def test_release_job_only_mutates_active_reservations(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        later = datetime(2026, 5, 10, 13, 0, tzinfo=UTC)
        self._reserve("job-consumed", "user-1", 0.01, now)
        self._reserve("job-released", "user-1", 0.01, now)
        self.store.record_work_unit_usage(
            job_id="job-consumed",
            user_id="user-1",
            work_unit_id="unit-consumed",
            prompt_tokens=1000,
            completion_tokens=500,
            rates=BetaSafetyRates(),
            now=now,
        )
        self.store.mark_job_consumed(job_id="job-consumed", now=now)
        self.store.release_job(job_id="job-released", reason="cancelled", now=now)

        consumed_before = self.store.get_reservation("job-consumed")
        released_before = self.store.get_reservation("job-released")
        self.store.release_job(
            job_id="job-consumed",
            reason="late_cancel",
            now=later,
        )
        self.store.release_job(
            job_id="job-released",
            reason="late_cancel",
            now=later,
        )

        consumed_after = self.store.get_reservation("job-consumed")
        released_after = self.store.get_reservation("job-released")
        self.assertEqual(consumed_after.status, RESERVATION_CONSUMED)
        self.assertEqual(consumed_after.reason, consumed_before.reason)
        self.assertEqual(consumed_after.released_at, consumed_before.released_at)
        self.assertEqual(consumed_after.consumed_at, consumed_before.consumed_at)
        self.assertEqual(released_after.status, RESERVATION_RELEASED)
        self.assertEqual(released_after.reason, released_before.reason)
        self.assertEqual(released_after.released_at, released_before.released_at)
        self.assertEqual(released_after.consumed_at, released_before.consumed_at)

    def test_record_work_unit_usage_is_idempotent_by_work_unit_id(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=10_000,
                completion_tokens=5_000,
                estimated_cost_usd=0.01,
            ),
            limits=BetaSafetyLimits(),
            rates=BetaSafetyRates(),
            now=now,
        )

        self.store.record_work_unit_usage(
            job_id="job-a",
            user_id="user-1",
            work_unit_id="unit-1",
            prompt_tokens=1000,
            completion_tokens=500,
            rates=BetaSafetyRates(),
            now=now,
        )
        self.store.record_work_unit_usage(
            job_id="job-a",
            user_id="user-1",
            work_unit_id="unit-1",
            prompt_tokens=1000,
            completion_tokens=500,
            rates=BetaSafetyRates(),
            now=now,
        )

        reservation = self.store.get_reservation("job-a")
        summary = self.store.get_budget_summary(user_id="user-1", now=now)
        self.assertEqual(reservation.status, RESERVATION_ACTIVE)
        self.assertIsNone(reservation.consumed_at)
        self.assertEqual(summary.user_daily_completed_work_units, 1)
        self.assertGreater(summary.user_daily_consumed_usd, 0.0)
        self.assertEqual(summary.user_daily_reserved_usd, 0.01)

    def test_partial_usage_keeps_active_reservation_blocking_new_reservations(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        limits = BetaSafetyLimits(
            global_daily_cost_cap_usd=1.01,
            global_monthly_cost_cap_usd=None,
            user_daily_cost_cap_usd=None,
            user_monthly_cost_cap_usd=None,
            max_job_estimated_cost_usd=None,
        )
        self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=1.00,
            ),
            limits=limits,
            rates=BetaSafetyRates(),
            now=now,
        )
        self.store.record_work_unit_usage(
            job_id="job-a",
            user_id="user-1",
            work_unit_id="unit-1",
            prompt_tokens=1000,
            completion_tokens=500,
            rates=BetaSafetyRates(),
            now=now,
        )

        blocked = self.store.reserve_job(
            job_id="job-b",
            user_id="user-2",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.99,
            ),
            limits=limits,
            rates=BetaSafetyRates(),
            now=now,
        )

        self.assertEqual(blocked.reason_code, BETA_SAFETY_GLOBAL_DAILY_CAP)
        self.assertEqual(
            self.store.get_reservation("job-a").status,
            RESERVATION_ACTIVE,
        )

    def test_release_job_can_release_active_reservation_after_partial_usage(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        self._reserve("job-a", "user-1", 1.00, now)
        self.store.record_work_unit_usage(
            job_id="job-a",
            user_id="user-1",
            work_unit_id="unit-1",
            prompt_tokens=1000,
            completion_tokens=500,
            rates=BetaSafetyRates(),
            now=now,
        )

        self.store.release_job(job_id="job-a", reason="cancelled", now=now)

        reservation = self.store.get_reservation("job-a")
        summary = self.store.get_budget_summary(user_id="user-1", now=now)
        self.assertEqual(reservation.status, RESERVATION_RELEASED)
        self.assertEqual(reservation.reason, "cancelled")
        self.assertEqual(summary.user_daily_reserved_usd, 0.0)
        self.assertGreater(summary.user_daily_consumed_usd, 0.0)

    def test_mark_job_consumed_only_mutates_active_reservations(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        later = datetime(2026, 5, 10, 13, 0, tzinfo=UTC)
        self._reserve("job-active", "user-1", 0.01, now)
        self._reserve("job-released", "user-1", 0.01, now)
        self.store.release_job(job_id="job-released", reason="cancelled", now=now)

        self.store.mark_job_consumed(job_id="job-active", now=later)
        self.store.mark_job_consumed(job_id="job-released", now=later)

        active = self.store.get_reservation("job-active")
        released = self.store.get_reservation("job-released")
        self.assertEqual(active.status, RESERVATION_CONSUMED)
        self.assertEqual(active.consumed_at, later)
        self.assertEqual(released.status, RESERVATION_RELEASED)
        self.assertIsNone(released.consumed_at)

    def test_global_start_guard_blocks_when_paused_or_cap_reached(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        paused = self.store.can_start_new_work(
            limits=BetaSafetyLimits(translations_paused=True),
            now=now,
        )

        self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.10,
            ),
            limits=BetaSafetyLimits(global_daily_cost_cap_usd=1.0),
            rates=BetaSafetyRates(),
            now=now,
        )
        capped = self.store.can_start_new_work(
            limits=BetaSafetyLimits(global_daily_cost_cap_usd=0.10),
            now=now,
        )

        self.assertFalse(paused.allowed)
        self.assertEqual(paused.reason_code, BETA_SAFETY_KILL_SWITCH)
        self.assertFalse(capped.allowed)
        self.assertEqual(capped.reason_code, BETA_SAFETY_GLOBAL_DAILY_CAP)

    def test_duplicate_reservation_returns_reservation_exists(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.01,
            ),
            limits=BetaSafetyLimits(),
            rates=BetaSafetyRates(),
            now=now,
        )

        duplicate = self.store.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.01,
            ),
            limits=BetaSafetyLimits(),
            rates=BetaSafetyRates(),
            now=now,
        )

        self.assertFalse(duplicate.allowed)
        self.assertEqual(duplicate.reason_code, BETA_SAFETY_RESERVATION_EXISTS)

    def test_budget_summary_uses_utc_day_and_month_boundaries(self):
        prior_month = datetime(2026, 4, 30, 23, 59, tzinfo=UTC)
        start_of_month = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        prior_day = datetime(2026, 5, 9, 23, 59, tzinfo=UTC)
        today = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)

        self._reserve("job-prior-month", "user-1", 0.11, prior_month)
        self._reserve("job-month", "user-1", 0.22, start_of_month)
        self._reserve("job-prior-day", "user-1", 0.33, prior_day)
        self._reserve("job-today", "user-1", 0.44, today)
        self._reserve("job-today-active", "user-1", 0.44, today)
        self.store.record_work_unit_usage(
            job_id="job-prior-month",
            user_id="user-1",
            work_unit_id="unit-prior-month",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            rates=BetaSafetyRates(input_usd_per_million=0.11),
            now=prior_month,
        )
        self.store.record_work_unit_usage(
            job_id="job-prior-day",
            user_id="user-1",
            work_unit_id="unit-prior-day",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            rates=BetaSafetyRates(input_usd_per_million=0.33),
            now=prior_day,
        )
        self.store.record_work_unit_usage(
            job_id="job-today",
            user_id="user-1",
            work_unit_id="unit-today",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            rates=BetaSafetyRates(input_usd_per_million=0.44),
            now=today,
        )

        summary = self.store.get_budget_summary(user_id="user-1", now=today)

        self.assertEqual(summary.user_daily_reserved_usd, 0.88)
        self.assertEqual(summary.user_daily_consumed_usd, 0.44)
        self.assertEqual(summary.user_monthly_reserved_usd, 1.43)
        self.assertEqual(summary.user_monthly_consumed_usd, 0.77)

    def test_get_reservation_returns_none_when_missing(self):
        self.assertIsNone(self.store.get_reservation("missing"))

    def test_context_manager_closes_store(self):
        with SQLiteBetaSafetyStore(self.db_path) as store:
            decision = store.reserve_job(
                job_id="job-a",
                user_id="user-1",
                estimate=JobCostEstimate(
                    prompt_tokens=1000,
                    completion_tokens=1000,
                    estimated_cost_usd=0.01,
                ),
                limits=BetaSafetyLimits(),
                rates=BetaSafetyRates(),
                now=datetime(2026, 5, 10, 12, 0, tzinfo=UTC),
            )

        self.assertTrue(decision.allowed)

    def test_schema_does_not_include_raw_text_or_file_name_columns(self):
        forbidden_substrings = (
            "text",
            "file_name",
            "prompt_text",
            "source_text",
            "translated_text",
            "translation",
            "prompt",
        )
        with sqlite3.connect(self.db_path) as connection:
            for table_name in (
                "beta_safety_reservations",
                "beta_safety_usage_events",
            ):
                rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
                column_names = [row[1].lower() for row in rows]

                for column_name in column_names:
                    for forbidden in forbidden_substrings:
                        if forbidden == "prompt" and column_name.endswith(
                            "prompt_tokens"
                        ):
                            continue
                        self.assertNotIn(forbidden, column_name)

    def test_configured_guard_loads_limits_and_rates_per_call(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        limits_calls = []
        rates_calls = []

        def load_limits():
            limits_calls.append("limits")
            return BetaSafetyLimits(
                global_daily_cost_cap_usd=10.0,
                global_monthly_cost_cap_usd=None,
                user_daily_cost_cap_usd=None,
                user_monthly_cost_cap_usd=None,
                max_job_estimated_cost_usd=None,
            )

        def load_rates():
            rates_calls.append("rates")
            return BetaSafetyRates()

        guard = ConfiguredBetaSafetyGuard(
            store=self.store,
            limits_loader=load_limits,
            rates_loader=load_rates,
            now_provider=lambda: now,
        )
        self.addCleanup(guard.close)

        guard.can_start_new_work()
        guard.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.01,
            ),
        )
        guard.record_work_unit_usage(
            job_id="job-a",
            user_id="user-1",
            work_unit_id="unit-1",
            prompt_tokens=1000,
            completion_tokens=500,
        )

        self.assertEqual(limits_calls, ["limits", "limits"])
        self.assertEqual(rates_calls, ["rates", "rates"])
        self.assertEqual(
            self.store.get_reservation("job-a").status,
            RESERVATION_ACTIVE,
        )
        self.assertEqual(
            self.store.get_budget_summary(user_id="user-1", now=now)
            .user_daily_completed_work_units,
            1,
        )

    def test_configured_guard_delegates_release_to_store(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        guard = ConfiguredBetaSafetyGuard(
            store=self.store,
            limits_loader=lambda: BetaSafetyLimits(),
            rates_loader=lambda: BetaSafetyRates(),
            now_provider=lambda: now,
        )
        self.addCleanup(guard.close)
        guard.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.01,
            ),
        )

        guard.release_job(job_id="job-a", reason="cancelled")

        reservation = self.store.get_reservation("job-a")
        self.assertEqual(reservation.status, RESERVATION_RELEASED)
        self.assertEqual(reservation.reason, "cancelled")

    def test_configured_guard_delegates_mark_consumed_to_store(self):
        now = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
        guard = ConfiguredBetaSafetyGuard(
            store=self.store,
            limits_loader=lambda: BetaSafetyLimits(),
            rates_loader=lambda: BetaSafetyRates(),
            now_provider=lambda: now,
        )
        self.addCleanup(guard.close)
        guard.reserve_job(
            job_id="job-a",
            user_id="user-1",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.01,
            ),
        )

        guard.mark_job_consumed(job_id="job-a")

        reservation = self.store.get_reservation("job-a")
        self.assertEqual(reservation.status, RESERVATION_CONSUMED)
        self.assertIsNotNone(reservation.consumed_at)

    def test_runtime_guard_consumed_usage_survives_reopened_store(self):
        admin_db_path = self.db_path
        guard = build_beta_safety_guard(
            BotRuntimeConfig(
                admin_db_path=str(admin_db_path),
                beta_global_daily_cost_cap_usd=10.0,
                beta_global_monthly_cost_cap_usd=10.0,
                beta_user_daily_cost_cap_usd=10.0,
                beta_user_monthly_cost_cap_usd=10.0,
                beta_max_job_estimated_cost_usd=10.0,
            )
        )
        guard.reserve_job(
            job_id="job-a",
            user_id="telegram:42",
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=0.01,
            ),
        )
        guard.record_work_unit_usage(
            job_id="job-a",
            user_id="telegram:42",
            work_unit_id="unit-a",
            prompt_tokens=1000,
            completion_tokens=500,
        )
        guard.mark_job_consumed(job_id="job-a")
        guard.close()
        self.store.close()

        self.store = SQLiteBetaSafetyStore(admin_db_path)
        reservation = self.store.get_reservation("job-a")
        summary = self.store.get_budget_summary(user_id="telegram:42")

        assert reservation is not None
        self.assertEqual(reservation.status, RESERVATION_CONSUMED)
        self.assertEqual(summary.user_daily_reserved_usd, 0.0)
        self.assertEqual(summary.user_daily_completed_work_units, 1)
        self.assertGreater(summary.user_daily_consumed_usd, 0.0)

    def _reserve(
        self,
        job_id: str,
        user_id: str,
        estimated_cost_usd: float,
        now: datetime,
    ) -> None:
        decision = self.store.reserve_job(
            job_id=job_id,
            user_id=user_id,
            estimate=JobCostEstimate(
                prompt_tokens=1000,
                completion_tokens=1000,
                estimated_cost_usd=estimated_cost_usd,
            ),
            limits=BetaSafetyLimits(
                global_daily_cost_cap_usd=None,
                global_monthly_cost_cap_usd=None,
                user_daily_cost_cap_usd=None,
                user_monthly_cost_cap_usd=None,
                max_job_estimated_cost_usd=None,
            ),
            rates=BetaSafetyRates(),
            now=now,
        )
        self.assertEqual(decision.reason_code, BETA_SAFETY_ALLOWED)


if __name__ == "__main__":
    unittest.main()
