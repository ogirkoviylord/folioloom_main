from __future__ import annotations

import importlib
import unittest
from types import SimpleNamespace

from translator_service.bot.runtime import _translation_progress_edit_allowed
from translator_service.job_runner import TranslationJobStatus


class StateSyncRegressionMatrixTest(unittest.TestCase):
    def test_progress_edit_policy_allows_only_active_durable_jobs(self):
        cases = (
            (TranslationJobStatus.QUEUED, True),
            (TranslationJobStatus.TRANSLATING, True),
            (TranslationJobStatus.PAUSED, False),
            (TranslationJobStatus.READY, False),
            (TranslationJobStatus.PARTIAL, False),
            (TranslationJobStatus.FAILED, False),
            (TranslationJobStatus.CANCELLED, False),
            (TranslationJobStatus.DELETED, False),
            (None, False),
        )
        for status, expected in cases:
            with self.subTest(status=status):
                service = _ProgressEditPolicyService(status)

                self.assertIs(
                    _translation_progress_edit_allowed(
                        service=service,
                        user_telegram_id=42,
                        job_id="job-1",
                    ),
                    expected,
                )

    def test_progress_edit_policy_blocks_when_user_is_cancelling(self):
        service = _ProgressEditPolicyService(
            TranslationJobStatus.TRANSLATING,
            cancelling=True,
        )

        self.assertFalse(
            _translation_progress_edit_allowed(
                service=service,
                user_telegram_id=42,
                job_id="job-1",
            )
        )

    def test_state_sync_regression_coverage_contract(self):
        coverage = {
            "tests.test_bot_runtime": (
                "test_confirm_deferred_translation_targets_cancel_after_job_exists",
                "test_stale_cancel_book_refreshes_terminal_job_state",
                "test_cancel_callback_sends_result_when_terminal_edit_fails",
                "test_resume_translation_sends_result_when_terminal_edit_fails",
                "test_translation_progress_edit_allows_only_active_durable_jobs",
                "test_text_cancel_cancels_single_cancellable_persistent_job",
                "test_text_cancel_does_not_guess_when_multiple_jobs_are_active",
                "test_text_cancel_after_terminal_job_shows_latest_book_state",
            ),
            "tests.test_admin_live_monitor": (
                "test_recent_runs_apply_durable_progress_snapshot",
            ),
            "tests.test_admin_routes": (
                "test_admin_surfaces_use_durable_progress_snapshot_for_stale_zero_run",
            ),
            "tests.test_admin_translation_trace": (
                "test_trace_job_facts_use_durable_progress_snapshot_without_operations",
            ),
            "tests.test_admin_translation_progress": (
                "test_snapshot_uses_durable_units_when_run_log_progress_is_stale_zero",
                "test_snapshot_handles_missing_store_and_job_without_leaking_exceptions",
            ),
        }

        missing: list[str] = []
        for module_name, test_names in coverage.items():
            module = importlib.import_module(module_name)
            test_case_classes = [
                value
                for value in vars(module).values()
                if isinstance(value, type) and issubclass(value, unittest.TestCase)
            ]
            available = {
                name
                for test_case in test_case_classes
                for name in dir(test_case)
                if name.startswith("test_")
            }
            for test_name in test_names:
                if test_name not in available:
                    missing.append(f"{module_name}.{test_name}")

        self.assertEqual(missing, [])


class _ProgressEditPolicyService:
    def __init__(
        self,
        status: TranslationJobStatus | None,
        *,
        cancelling: bool = False,
    ) -> None:
        self.status = status
        self.cancelling = cancelling

    def is_translation_cancelling(self, user_telegram_id: int) -> bool:
        return self.cancelling

    def get_user_book_translation_job(self, **kwargs):
        if self.status is None:
            return None
        return SimpleNamespace(status=self.status)


if __name__ == "__main__":
    unittest.main()
