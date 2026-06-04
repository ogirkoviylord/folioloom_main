from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from translator_service.admin.provider_runtime import (
    AIProviderRuntimeChannel,
    AIProviderRuntimeStatus,
)
from translator_service.admin.translation_logs import (
    TranslationProviderFailureAttempt,
    TranslationWorkUnitDiagnostic,
    get_translation_run_details,
)
from translator_service.admin.translation_trace import build_translation_trace
from translator_service.admin.views import translation_trace_body
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
)
from translator_service.user_activity import (
    ActivityActorType,
    ActivityOutcome,
    ActivitySurface,
    SQLiteUserActivityStore,
    UserActivityEventInput,
)


class AdminTranslationTraceTest(unittest.TestCase):
    def test_builds_provider_trace_without_raw_or_secret_values(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-trace-1",
                    order_id="order-trace-1",
                    user_id="telegram:42",
                    file_name="very-long-book-name-that-should-wrap-cleanly.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek",
                    total_fragment_count=1,
                ),
            )
            logger.record_event(
                "provider_failure",
                {
                    "status": "failed",
                    "source_text": "SECRET SOURCE TEXT",
                    "prompt": "SECRET PROMPT TEXT",
                    "error_message": (
                        "Bearer raw-bearer-token "
                        "api_key=sk-raw-secret "
                        "secret_id=deepseek.api_keys.trace-key"
                    ),
                },
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="SECRET SOURCE TEXT",
                    translated_text="SECRET TRANSLATED TEXT",
                    status="failed",
                    elapsed_seconds=0.5,
                    prompt_tokens=10,
                    completion_tokens=0,
                    total_tokens=10,
                    error_message="provider timeout for SECRET SOURCE TEXT",
                )
            )
            logger.finish(
                status="failed",
                error_message=(
                    "DeepSeek provider timeout with sk-finish-secret "
                    "and Traceback should be hidden"
                ),
            )
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            self.assertIsNotNone(details)
            assert details is not None

            trace = build_translation_trace(
                details,
                runtime_statuses=(
                    AIProviderRuntimeStatus(
                        provider_id="deepseek",
                        source="admin_store",
                        status="degraded",
                        reload_interval_seconds=30.0,
                        last_reloaded_at=datetime(2026, 5, 31, tzinfo=UTC),
                        active_channels=(
                            AIProviderRuntimeChannel(
                                label="primary",
                                weight=1,
                                max_parallel_requests=2,
                                health="degraded",
                                total_timeout_failures=1,
                                error_kind="timeout",
                                last_error_excerpt="Bearer provider-secret",
                            ),
                        ),
                        error="provider degraded",
                    ),
                ),
            )
            html = translation_trace_body(trace)

        self.assertEqual(trace.failure_category, "Provider")
        self.assertIn("Translation Failure Trace", html)
        self.assertIn("Open provider", html)
        self.assertIn("job-trace-1", html)
        self.assertIn("timeout", html)
        self.assertIn("[redacted]", html)
        for forbidden in (
            "SECRET SOURCE TEXT",
            "SECRET TRANSLATED TEXT",
            "SECRET PROMPT TEXT",
            "sk-raw-secret",
            "sk-finish-secret",
            "raw-bearer-token",
            "deepseek.api_keys.trace-key",
            "Traceback",
        ):
            self.assertNotIn(forbidden, html)

    def test_activity_timeline_uses_allowlisted_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-trace-activity",
                    order_id="order-trace-activity",
                    user_id="telegram:77",
                    file_name="activity.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            logger.finish(status="failed", error_message="failed")
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            self.assertIsNotNone(details)
            assert details is not None

            with SQLiteUserActivityStore(":memory:") as store:
                store.record_event(
                    UserActivityEventInput(
                        actor_type=ActivityActorType.USER,
                        actor_id="telegram:77",
                        surface=ActivitySurface.BOT,
                        event_type="translation.target_language.selected",
                        action="translation.target_language.selected",
                        outcome=ActivityOutcome.SUCCESS,
                        channel="telegram",
                        channel_user_id="77",
                        target_type="translation_job",
                        target_id="job-trace-activity",
                        job_id="job-trace-activity",
                        order_id="order-trace-activity",
                        metadata={
                            "target_language": "ru",
                            "source_text": "RAW ACTIVITY TEXT",
                            "api_key": "sk-activity-secret",
                        },
                    )
                )
                events = store.list_events(job_id="job-trace-activity")

            trace = build_translation_trace(details, activity_events=events)
            html = translation_trace_body(trace)

        self.assertIn("activity: translation.target_language.selected", html)
        self.assertIn("outcome=success", html)
        self.assertNotIn("RAW ACTIVITY TEXT", html)
        self.assertNotIn("sk-activity-secret", html)

    def test_failed_run_without_safe_cause_stays_unknown(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-trace-unknown",
                    order_id="order-trace-unknown",
                    user_id="telegram:99",
                    file_name="unknown.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )
            logger.finish(status="failed", error_message="opaque failure")
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            self.assertIsNotNone(details)
            assert details is not None

            trace = build_translation_trace(details)
            html = translation_trace_body(trace)

        self.assertEqual(trace.failure_category, "Unknown")
        self.assertEqual(trace.next_action.label, "Review advanced log")
        self.assertIn("Unknown", html)
        self.assertIn("Review advanced log", html)

    def test_trace_uses_persisted_provider_attempt_when_runtime_is_ok(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-trace-persisted-provider",
                    order_id="order-trace-persisted-provider",
                    user_id="telegram:42",
                    file_name="persisted.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek",
                    total_fragment_count=1,
                ),
            )
            logger.finish(status="failed", error_message="retryable provider failure")
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            self.assertIsNotNone(details)
            assert details is not None
            details = replace(
                details,
                work_unit_diagnostic=TranslationWorkUnitDiagnostic(
                    sequence=7,
                    status="failed_terminal",
                    source_block_ids=("block-secret",),
                    attempt_count=3,
                    max_attempts=3,
                    last_error="provider failure: rate_limited",
                    updated_at=datetime(2026, 5, 31, tzinfo=UTC),
                    provider_attempts=(
                        TranslationProviderFailureAttempt(
                            attempt_number=3,
                            status="failed_terminal",
                            failure_category="rate_limited",
                            provider_id="deepseek",
                            http_status_bucket="429",
                            retry_after_seconds=0,
                            latency_ms=842.0,
                            terminal_reason="max_attempts_reached",
                            channel_fingerprint="chan_safe123456",
                            channel_health="cooling_down",
                            circuit_state="open",
                        ),
                    ),
                ),
            )

            trace = build_translation_trace(
                details,
                runtime_statuses=(
                    AIProviderRuntimeStatus(
                        provider_id="deepseek",
                        source="admin_store",
                        status="ok",
                        reload_interval_seconds=30.0,
                        last_reloaded_at=datetime(2026, 5, 31, tzinfo=UTC),
                        active_channels=(
                            AIProviderRuntimeChannel(
                                label="primary",
                                weight=1,
                                max_parallel_requests=2,
                                health="healthy",
                            ),
                        ),
                    ),
                ),
            )
            html = translation_trace_body(trace)

        self.assertEqual(trace.failure_category, "Provider")
        self.assertIn("rate_limited", html)
        self.assertIn("max_attempts_reached", html)
        self.assertIn("chan_safe123456", html)
        self.assertIn("429", html)
        self.assertIn("open", html)
        self.assertNotIn("block-secret", html)
        self.assertNotIn("SECRET", html)


if __name__ == "__main__":
    unittest.main()
