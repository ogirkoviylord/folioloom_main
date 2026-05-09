import json
import unittest
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.costs import CostRates, build_cost_analytics
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
)


class AdminCostAnalyticsTest(unittest.TestCase):
    def test_builds_token_windows_costs_top_runs_and_top_users(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run(
                root,
                run_id="run-today-expensive",
                job_id="job-today-expensive",
                user_id="telegram:42",
                started_at="2026-05-09T09:30:00+00:00",
                prompt_tokens=1_000_000,
                completion_tokens=2_000_000,
            )
            _write_run(
                root,
                run_id="run-today-small",
                job_id="job-today-small",
                user_id="telegram:42",
                started_at="2026-05-09T07:00:00+00:00",
                prompt_tokens=100,
                completion_tokens=200,
            )
            _write_run(
                root,
                run_id="run-last-7",
                job_id="job-last-7",
                user_id="telegram:7",
                started_at="2026-05-03T12:00:00+00:00",
                prompt_tokens=10,
                completion_tokens=20,
            )
            _write_run(
                root,
                run_id="run-month",
                job_id="job-month",
                user_id=None,
                started_at="2026-05-01T12:00:00+00:00",
                prompt_tokens=1,
                completion_tokens=2,
            )
            _write_run(
                root,
                run_id="run-old",
                job_id="job-old",
                user_id="telegram:old",
                started_at="2026-04-30T23:59:00+00:00",
                prompt_tokens=5_000_000,
                completion_tokens=5_000_000,
            )
            (root / "malformed" / "run.json").parent.mkdir()
            (root / "malformed" / "run.json").write_text("{bad json", encoding="utf-8")

            analytics = build_cost_analytics(
                root,
                now=datetime(2026, 5, 9, 15, 0, tzinfo=UTC),
                rates=CostRates(
                    input_usd_per_million=0.28,
                    output_usd_per_million=1.10,
                ),
                limit=3,
            )

        self.assertEqual(analytics.tokens_today, 3_000_300)
        self.assertEqual(analytics.tokens_last_7_days, 3_000_330)
        self.assertEqual(analytics.tokens_month_to_date, 3_000_333)
        self.assertEqual(analytics.estimated_cost_today_usd, 2.480248)
        self.assertEqual(analytics.estimated_cost_last_7_days_usd, 2.480273)
        self.assertEqual(analytics.estimated_cost_month_to_date_usd, 2.480275)
        self.assertEqual(
            [run.job_id for run in analytics.top_runs],
            ["job-old", "job-today-expensive", "job-today-small"],
        )
        self.assertEqual(analytics.top_runs[1].log_href, "/admin/logs")
        self.assertEqual(
            [(user.user_id, user.total_tokens) for user in analytics.top_users],
            [
                ("telegram:old", 10_000_000),
                ("telegram:42", 3_000_300),
                ("telegram:7", 30),
            ],
        )

    def test_uses_reporting_timezone_for_date_windows(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run(
                root,
                run_id="run-utc-evening",
                job_id="job-utc-evening",
                user_id="telegram:42",
                started_at="2026-05-08T22:30:00+00:00",
                prompt_tokens=100,
                completion_tokens=200,
            )

            analytics = build_cost_analytics(
                root,
                now=datetime(
                    2026,
                    5,
                    9,
                    0,
                    30,
                    tzinfo=timezone(timedelta(hours=2)),
                ),
            )

        self.assertEqual(analytics.tokens_today, 300)
        self.assertEqual(analytics.tokens_last_7_days, 300)
        self.assertEqual(analytics.tokens_month_to_date, 300)

    def test_rounds_cost_values_to_six_decimal_places(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run(
                root,
                run_id="run-small-cost",
                job_id="job-small-cost",
                user_id="telegram:42",
                started_at="2026-05-09T09:00:00+00:00",
                prompt_tokens=1_000,
                completion_tokens=2_000,
            )

            analytics = build_cost_analytics(
                root,
                now=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
            )

        self.assertEqual(analytics.estimated_cost_today_usd, 0.00248)
        self.assertEqual(analytics.estimated_cost_last_7_days_usd, 0.00248)
        self.assertEqual(analytics.estimated_cost_month_to_date_usd, 0.00248)
        self.assertEqual(analytics.top_runs[0].estimated_cost_usd, 0.00248)
        self.assertEqual(analytics.top_users[0].estimated_cost_usd, 0.00248)

    def test_limit_zero_returns_no_top_rows(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_run(
                root,
                run_id="run-one",
                job_id="job-one",
                user_id="telegram:42",
                started_at="2026-05-09T09:00:00+00:00",
                prompt_tokens=1_000,
                completion_tokens=2_000,
            )

            analytics = build_cost_analytics(
                root,
                now=datetime(2026, 5, 9, 12, 0, tzinfo=UTC),
                limit=0,
            )

        self.assertEqual(analytics.top_runs, ())
        self.assertEqual(analytics.top_users, ())

    def test_cost_model_does_not_include_raw_source_or_translated_text(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-private",
                    order_id="order-private",
                    user_id="telegram:42",
                    file_name="private.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek",
                ),
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="Sensitive original sentence.",
                    translated_text="Sensitive translated sentence.",
                    status="translated",
                    elapsed_seconds=0.5,
                    prompt_tokens=12,
                    completion_tokens=8,
                    total_tokens=20,
                )
            )
            logger.finish(status="ready", result_file_name="private.uk.txt")

            analytics = build_cost_analytics(temp_dir)

        serialized = json.dumps(asdict(analytics), default=str, sort_keys=True)
        self.assertIn("job-private", serialized)
        self.assertNotIn("Sensitive original sentence.", serialized)
        self.assertNotIn("Sensitive translated sentence.", serialized)


def _write_run(
    root: Path,
    *,
    run_id: str,
    job_id: str,
    user_id: str | None,
    started_at: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    run_dir = root / run_id
    run_dir.mkdir()
    total_tokens = prompt_tokens + completion_tokens
    payload = {
        "job_id": job_id,
        "order_id": f"order-{job_id}",
        "user_id": user_id,
        "file_name": f"{job_id}.txt",
        "started_at": started_at,
        "translator_model": "deepseek",
        "totals": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
    }
    (run_dir / "run.json").write_text(
        json.dumps(payload, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
