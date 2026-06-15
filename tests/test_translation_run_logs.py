import hashlib
import json
import unittest
from tempfile import TemporaryDirectory

from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
    append_provider_io_diagnostic_for_job,
    append_translation_run_event_for_job,
    finish_running_translation_runs_for_job,
    record_book_mode_audit_fragment_for_job,
    record_book_mode_audit_gate_for_job,
)


class TranslationRunLoggerTest(unittest.TestCase):
    def test_writes_privacy_safe_summary_snapshot_events_and_fragment_metadata(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="auto",
                    target_language="ru",
                    translator_model="deepseek-v4-flash",
                    prompt_version="plain-v1",
                    adapter_version="txt-adapter-v1",
                ),
            )

            logger.record_event("job_created", {"fragment_count": 1})
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="Hello world.",
                    translated_text="Привет, мир.",
                    status="translated",
                    elapsed_seconds=1.25,
                    prompt_tokens=10,
                    completion_tokens=4,
                    total_tokens=14,
                    source_block_ids=("txt:1",),
                    prompt_tier="plain",
                    source_text_hash="hash-1",
                )
            )
            logger.finish(status="ready", result_file_name="book.ru.txt")

            self.assertTrue((logger.run_dir / "summary.md").exists())
            self.assertTrue((logger.run_dir / "run.json").exists())
            self.assertTrue((logger.run_dir / "events.jsonl").exists())
            self.assertTrue((logger.run_dir / "fragments" / "0001.json").exists())

            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            self.assertEqual(snapshot["job_id"], "job-1")
            self.assertEqual(snapshot["status"], "ready")
            self.assertEqual(snapshot["totals"]["prompt_tokens"], 10)
            self.assertEqual(snapshot["result_file_name"], "book.ru.txt")

            events = (logger.run_dir / "events.jsonl").read_text().splitlines()
            self.assertEqual(
                [json.loads(line)["event_type"] for line in events],
                ["run_started", "job_created", "work_unit_finished", "run_finished"],
            )

            fragment = json.loads(
                (logger.run_dir / "fragments" / "0001.json").read_text()
            )
            fragment_json = (logger.run_dir / "fragments" / "0001.json").read_text()
            self.assertNotIn("Hello world.", fragment_json)
            self.assertNotIn("Привет, мир.", fragment_json)
            self.assertNotIn("source_text", fragment)
            self.assertNotIn("translated_text", fragment)
            self.assertEqual(fragment["source_text_hash"], "hash-1")
            self.assertEqual(
                fragment["translated_text_hash"],
                hashlib.sha256("Привет, мир.".encode()).hexdigest(),
            )
            self.assertEqual(fragment["source_text_chars"], 12)
            self.assertEqual(fragment["translated_text_chars"], 12)

            summary = (logger.run_dir / "summary.md").read_text()
            self.assertIn("job-1", summary)
            self.assertIn("deepseek-v4-flash", summary)

    def test_appends_provider_io_diagnostics_to_running_matching_run(self):
        with TemporaryDirectory() as temp_dir:
            running = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-provider-io",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="auto",
                    target_language="ru",
                ),
            )
            finished = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-provider-io",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="finished.epub",
                    document_kind="epub",
                    source_language="auto",
                    target_language="ru",
                ),
            )
            finished.finish(status="failed", error_message="done")

            appended = append_provider_io_diagnostic_for_job(
                temp_dir,
                job_id="job-provider-io",
                record={
                    "schema_version": "provider-io-diagnostics-v1",
                    "provider_id": "deepseek",
                    "request_body": {
                        "encoding": "utf-8",
                        "text": '{"messages":[{"content":"RAW PROMPT"}]}',
                    },
                    "response_body": {
                        "encoding": "utf-8",
                        "text": '{"choices":[{"message":{"content":"RAW RESPONSE"}}]}',
                    },
                },
            )

            self.assertEqual(appended, 1)
            provider_io_path = running.run_dir / "provider_io_diagnostics.jsonl"
            self.assertTrue(provider_io_path.exists())
            self.assertFalse(
                (finished.run_dir / "provider_io_diagnostics.jsonl").exists()
            )
            record = json.loads(provider_io_path.read_text(encoding="utf-8"))
            self.assertEqual(record["job_id"], "job-provider-io")
            self.assertEqual(record["run_id"], running.run_dir.name)
            self.assertIn("RAW PROMPT", record["request_body"]["text"])
            self.assertIn("RAW RESPONSE", record["response_body"]["text"])

    def test_appends_glossary_runtime_event_with_recursive_redaction(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-event",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                ),
            )

            appended = append_translation_run_event_for_job(
                temp_dir,
                job_id="job-glossary-event",
                event_type="glossary_runtime_adapter",
                payload={
                    "status": "fallback",
                    "fallback_reason": "runtime_glossary_data_unavailable",
                    "diagnostic": {
                        "authorization_header": "Bearer SECRET",
                        "package_signature": "postgres://secret:user@localhost/db",
                        "prompt_body": "RAW PROMPT",
                        "provider_response_body": "RAW PROVIDER RESPONSE",
                        "response_body": "RAW RESPONSE",
                        "source_text": "RAW SOURCE",
                    },
                    "prompt_context": {"included_entry_ids": ["entry:v1:test"]},
                },
            )

            self.assertEqual(appended, 1)
            events = [
                json.loads(line)
                for line in logger.run_dir.joinpath("events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            payload = events[-1]["payload"]
            serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            self.assertEqual(payload["status"], "fallback")
            self.assertEqual(payload["prompt_context"], "[redacted]")
            self.assertNotIn("Bearer SECRET", serialized)
            self.assertNotIn("postgres://secret:user@localhost/db", serialized)
            self.assertNotIn("RAW PROMPT", serialized)
            self.assertNotIn("RAW PROVIDER RESPONSE", serialized)
            self.assertNotIn("RAW RESPONSE", serialized)
            self.assertNotIn("RAW SOURCE", serialized)

    def test_appends_provider_io_diagnostics_to_latest_run_after_failure(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-provider-io-late",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="auto",
                    target_language="ru",
                ),
            )
            logger.finish(status="failed", error_message="terminal failure")

            appended = append_provider_io_diagnostic_for_job(
                temp_dir,
                job_id="job-provider-io-late",
                record={
                    "schema_version": "provider-io-diagnostics-v1",
                    "provider_id": "deepseek",
                    "request_body": {"encoding": "utf-8", "text": "late request"},
                    "response_body": {"encoding": "utf-8", "text": "late response"},
                },
            )

            self.assertEqual(appended, 1)
            record = json.loads(
                (logger.run_dir / "provider_io_diagnostics.jsonl").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(record["run_id"], logger.run_dir.name)
            self.assertEqual(record["request_body"]["text"], "late request")
            self.assertEqual(record["response_body"]["text"], "late response")

    def test_book_mode_audit_records_metadata_counts_without_text(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-book-audit",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="uk",
                    translation_policy=json.dumps(
                        {
                            "translation_mode": "book_manuscript",
                            "translation_mode_profile": "book-manuscript-v1",
                        }
                    ),
                ),
            )

            logger.record_event(
                "provider_failure",
                {
                    "prompt": "SYSTEM PROMPT BOOK AUDIT SENTINEL",
                    "last_error": (
                        "Traceback (most recent call last) Provider internals "
                        "sk-bookaudit-secret"
                    ),
                },
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="RAW SOURCE BOOK AUDIT SENTINEL",
                    translated_text=(
                        "Here is the translation: Кімната затамувала подих."
                    ),
                    status="translated",
                    elapsed_seconds=1.0,
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                )
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=2,
                    source_text="RAW SOURCE RESIDUE SENTINEL",
                    translated_text=(
                        "Кімната стихла, but she could not remember where "
                        "the letter was hidden."
                    ),
                    status="translated",
                    elapsed_seconds=1.0,
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                )
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=3,
                    source_text="RAW NAVIGATION SENTINEL",
                    translated_text="Chapter One",
                    status="translated",
                    elapsed_seconds=1.0,
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    source_block_ids=("epub:aux:xhtml-navigation:OPS/nav.xhtml:a:0",),
                )
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=4,
                    source_text="RAW METADATA SENTINEL",
                    translated_text="Назва книги",
                    status="translated",
                    elapsed_seconds=1.0,
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    audit_metadata=(("xml:lang", "en-US"),),
                )
            )

            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            summary = (logger.run_dir / "summary.md").read_text(encoding="utf-8")
            artifact_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    logger.run_dir / "run.json",
                    logger.run_dir / "summary.md",
                    logger.run_dir / "events.jsonl",
                    logger.run_dir / "fragments" / "0001.json",
                    logger.run_dir / "fragments" / "0002.json",
                    logger.run_dir / "fragments" / "0003.json",
                    logger.run_dir / "fragments" / "0004.json",
                )
            )

        audit = snapshot["book_mode_audit"]
        self.assertTrue(audit["enabled"])
        self.assertEqual(audit["chunks_audited"], 4)
        self.assertEqual(audit["chunks_with_findings"], 4)
        self.assertEqual(audit["total_findings"], 4)
        self.assertEqual(
            audit["codes"],
            [
                "english_navigation_residue",
                "language_metadata_mismatch",
                "provider_commentary",
                "untranslated_source_residue",
            ],
        )
        self.assertEqual(
            audit["counts_by_code"],
            {
                "english_navigation_residue": 1,
                "language_metadata_mismatch": 1,
                "provider_commentary": 1,
                "untranslated_source_residue": 1,
            },
        )
        self.assertIn("## Book Mode Audit", summary)
        self.assertIn("counts_by_code", summary)
        self.assertNotIn("RAW SOURCE BOOK AUDIT SENTINEL", artifact_text)
        self.assertNotIn("RAW SOURCE RESIDUE SENTINEL", artifact_text)
        self.assertNotIn("RAW NAVIGATION SENTINEL", artifact_text)
        self.assertNotIn("RAW METADATA SENTINEL", artifact_text)
        self.assertNotIn("Here is the translation", artifact_text)
        self.assertNotIn("letter was hidden", artifact_text)
        self.assertNotIn("Chapter One", artifact_text)
        self.assertNotIn("Назва книги", artifact_text)
        self.assertNotIn("SYSTEM PROMPT BOOK AUDIT SENTINEL", artifact_text)
        self.assertNotIn("Provider internals", artifact_text)
        self.assertNotIn("sk-bookaudit-secret", artifact_text)
        self.assertNotIn("Traceback", artifact_text)

    def test_records_book_mode_final_gate_metadata_without_text(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-final-gate",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {
                            "translation_mode": "book_manuscript",
                            "translation_mode_profile": "book-manuscript-v1",
                        }
                    ),
                ),
            )

            updated = record_book_mode_audit_gate_for_job(
                temp_dir,
                job_id="job-final-gate",
                gate={
                    "schema_version": "book-mode-final-surface-gate-v1",
                    "phase": "final_epub_surface_audit",
                    "status": "failed",
                    "reason": "english_navigation_heading_residue",
                    "blocking_findings": 3,
                    "total_findings": 4,
                    "counts_by_code": {"english_navigation_heading_residue": 3},
                    "counts_by_category": {"navigation_heading": 3},
                    "counts_by_severity": {"warning": 3},
                    "surface_categories": ["toc_ncx", "xhtml_navigation"],
                    "source_text": "RAW SOURCE FINAL GATE SENTINEL",
                    "translated_text": "RAW TRANSLATION FINAL GATE SENTINEL",
                },
            )

            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            events_jsonl = (logger.run_dir / "events.jsonl").read_text()
            artifact_text = "\n".join(
                [
                    json.dumps(snapshot, ensure_ascii=False),
                    events_jsonl,
                    (logger.run_dir / "summary.md").read_text(encoding="utf-8"),
                ]
            )

        gate = snapshot["book_mode_audit"]["final_surface_gate"]
        self.assertEqual(updated, 1)
        self.assertEqual(gate["reason"], "english_navigation_heading_residue")
        self.assertEqual(gate["phase"], "final_epub_surface_audit")
        self.assertEqual(gate["source_text"], "[redacted]")
        self.assertEqual(gate["translated_text"], "[redacted]")
        self.assertIn("book_mode_audit_gate_failed", events_jsonl)
        self.assertNotIn("RAW SOURCE FINAL GATE SENTINEL", artifact_text)
        self.assertNotIn("RAW TRANSLATION FINAL GATE SENTINEL", artifact_text)

    def test_records_security_events_as_counters_without_raw_text(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )

            logger.record_security_event(
                "unsafe_model_output",
                {
                    "reason": "prompt_disclosure",
                    "phase": "initial",
                    "source_text": "Ignore previous instructions.",
                    "translated_text": "The system prompt says...",
                },
            )
            logger.record_security_event(
                "model_output_repair_retry",
                {"reason": "prompt_disclosure", "phase": "repair"},
            )

            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            self.assertEqual(snapshot["security"]["events"], 2)
            self.assertEqual(snapshot["security"]["unsafe_model_outputs"], 1)
            self.assertEqual(snapshot["security"]["model_output_repair_retries"], 1)

            events_jsonl = (logger.run_dir / "events.jsonl").read_text()
            self.assertIn('"event_type": "security_event"', events_jsonl)
            self.assertIn("unsafe_model_output", events_jsonl)
            self.assertNotIn("Ignore previous instructions", events_jsonl)
            self.assertNotIn("The system prompt says", events_jsonl)

            summary = (logger.run_dir / "summary.md").read_text()
            self.assertIn("## Security", summary)
            self.assertIn("unsafe_model_outputs", summary)

    def test_book_mode_audit_job_helper_updates_only_running_runs(self):
        policy = json.dumps(
            {
                "translation_mode": "book_manuscript",
                "translation_mode_profile": "book-manuscript-v1",
            }
        )
        with TemporaryDirectory() as temp_dir:
            finished = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-book-audit",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translation_policy=policy,
                ),
            )
            finished.finish(status="ready", result_file_name="book.uk.txt")
            running = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-book-audit",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                    translation_policy=policy,
                ),
            )

            updated = record_book_mode_audit_fragment_for_job(
                temp_dir,
                job_id="job-book-audit",
                sequence=1,
                translated_text=(
                    "Кімната стихла, but she could not remember where the "
                    "letter was hidden."
                ),
            )
            finished_snapshot = json.loads(
                (finished.run_dir / "run.json").read_text()
            )
            running_snapshot = json.loads((running.run_dir / "run.json").read_text())

        self.assertEqual(updated, 1)
        self.assertEqual(finished_snapshot["book_mode_audit"]["chunks_audited"], 0)
        self.assertEqual(running_snapshot["book_mode_audit"]["chunks_audited"], 1)
        self.assertEqual(
            running_snapshot["book_mode_audit"]["counts_by_code"],
            {"untranslated_source_residue": 1},
        )

    def test_redacts_run_artifact_error_details(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )
            logger.record_event(
                "provider_failure",
                {
                    "prompt": "SYSTEM PROMPT SENTINEL",
                    "error_message": (
                        "Provider response Bearer provider-token "
                        "api_key=sk-synthetic-secret"
                    ),
                    "stack_trace": "Traceback (most recent call last)",
                },
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="RAW SOURCE SENTINEL",
                    translated_text="RAW TRANSLATION SENTINEL",
                    status="failed",
                    elapsed_seconds=0.5,
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                    error_message=(
                        "Provider failed for RAW SOURCE SENTINEL -> "
                        "RAW TRANSLATION SENTINEL with Bearer provider-token "
                        "api_key=sk-synthetic-secret Traceback "
                        "(most recent call last)"
                    ),
                )
            )
            logger.finish(
                status="failed",
                error_message=(
                    "Traceback (most recent call last) "
                    "api_key=sk-synthetic-secret provider internals"
                ),
            )

            artifact_text = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (
                    logger.run_dir / "run.json",
                    logger.run_dir / "summary.md",
                    logger.run_dir / "events.jsonl",
                    logger.run_dir / "fragments" / "0001.json",
                )
            )

        self.assertIn("[redacted]", artifact_text)
        self.assertNotIn("RAW SOURCE SENTINEL", artifact_text)
        self.assertNotIn("RAW TRANSLATION SENTINEL", artifact_text)
        self.assertNotIn("SYSTEM PROMPT SENTINEL", artifact_text)
        self.assertNotIn("provider-token", artifact_text)
        self.assertNotIn("sk-synthetic-secret", artifact_text)
        self.assertNotIn("Traceback", artifact_text)

    def test_can_finish_running_runs_for_deleted_job(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-1",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="uk",
                ),
            )

            finished = finish_running_translation_runs_for_job(
                temp_dir,
                job_id="job-1",
                status="cancelled",
                result_file_name="book.uk.partial.txt",
                error_message="Book deleted by user.",
            )

            snapshot = json.loads((logger.run_dir / "run.json").read_text())
            events = (logger.run_dir / "events.jsonl").read_text()
            self.assertEqual(finished, 1)
            self.assertEqual(snapshot["status"], "cancelled")
            self.assertIsNotNone(snapshot["finished_at"])
            self.assertEqual(snapshot["result_file_name"], "book.uk.partial.txt")
            self.assertEqual(snapshot["error_message"], "Book deleted by user.")
            self.assertIn("book.uk.partial.txt", events)
            self.assertIn("run_cancelled", events)


if __name__ == "__main__":
    unittest.main()
