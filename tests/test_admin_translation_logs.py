from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from translator_service.admin.translation_logs import (
    build_effective_translation_run_archive,
    build_translation_run_archive,
    get_translation_run_details,
    list_translation_run_summaries,
)
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
)


class AdminTranslationLogsTest(unittest.TestCase):
    def test_lists_translation_runs_without_document_text(self):
        with TemporaryDirectory() as temp_dir:
            ready = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-ready",
                    order_id="order-1",
                    user_id="telegram:42",
                    file_name="novel.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                    translator_model="deepseek",
                ),
            )
            ready.finish(status="ready", result_file_name="novel.ru.txt")
            failed = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-failed",
                    order_id=None,
                    user_id="telegram:77",
                    file_name="contract.docx",
                    document_kind="docx",
                    source_language="en",
                    target_language="uk",
                ),
            )
            failed.finish(status="failed", error_message="provider timeout")

            rows = list_translation_run_summaries(temp_dir)

        self.assertEqual([row.job_id for row in rows], ["job-failed", "job-ready"])
        self.assertEqual(rows[0].status, "failed")
        self.assertEqual(rows[0].file_name, "contract.docx")
        self.assertEqual(rows[0].error_message, "provider timeout")
        self.assertIsNone(rows[0].order_id)
        self.assertEqual(rows[1].result_file_name, "novel.ru.txt")
        self.assertNotIn("source_text", repr(rows))
        self.assertNotIn("translated_text", repr(rows))

    def test_filters_by_status_and_date_range(self):
        with TemporaryDirectory() as temp_dir:
            first = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-ready",
                    order_id=None,
                    user_id=None,
                    file_name="first.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            first.finish(status="ready")
            second = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-failed",
                    order_id=None,
                    user_id=None,
                    file_name="second.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                ),
            )
            second.finish(status="failed")

            ready_rows = list_translation_run_summaries(temp_dir, status="ready")
            failed_day = second.run_dir.name[:10]
            failed_rows = list_translation_run_summaries(
                temp_dir,
                status="failed",
                date_from=failed_day,
                date_to=failed_day,
            )

        self.assertEqual([row.job_id for row in ready_rows], ["job-ready"])
        self.assertEqual([row.job_id for row in failed_rows], ["job-failed"])

    def test_missing_log_root_returns_empty_list(self):
        rows = list_translation_run_summaries("/tmp/does-not-exist-folioloom")

        self.assertEqual(rows, ())

    def test_active_eta_uses_wall_clock_elapsed_time(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-slow",
                    order_id=None,
                    user_id=None,
                    file_name="slow-book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                    total_fragment_count=4,
                ),
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="One",
                    translated_text="Один",
                    status="translated",
                    elapsed_seconds=10.0,
                    prompt_tokens=1,
                    completion_tokens=1,
                    total_tokens=2,
                )
            )
            run_json = logger.run_dir / "run.json"
            snapshot = json.loads(run_json.read_text(encoding="utf-8"))
            snapshot["started_at"] = "2026-05-10T10:00:00+00:00"
            run_json.write_text(json.dumps(snapshot), encoding="utf-8")

            rows = list_translation_run_summaries(
                temp_dir,
                now=datetime(2026, 5, 10, 10, 30, tzinfo=UTC),
            )

        self.assertEqual(rows[0].eta_seconds, 5400.0)

    def test_loads_translation_run_details_without_document_text(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-detail",
                    order_id="order-42",
                    user_id="telegram:42",
                    file_name="novel.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="uk",
                    translator_model="deepseek-test",
                    prompt_version="prompt-v2",
                    adapter_version="epub-adapter-v3",
                    translation_policy="policy-v1",
                    translation_quality_route="ukrainian-literary",
                    translation_stack={
                        "schema_version": "stack-v1",
                        "adapter": {
                            "name": "epub",
                            "version": "epub-adapter-v3",
                        },
                        "language_profiles": {
                            "target_language": {"signature": "uk-profile-v1"},
                            "source_pair": {"signature": "en-uk-v1"},
                            "quality_track": {"signature": "literary-v1"},
                        },
                    },
                ),
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="Original paragraph",
                    translated_text="Перекладений абзац",
                    status="ready",
                    elapsed_seconds=1.25,
                    prompt_tokens=100,
                    completion_tokens=70,
                    total_tokens=170,
                    source_block_ids=("chapter-1",),
                    prompt_tier="literary",
                    retry_count=1,
                )
            )
            logger.finish(status="ready", result_file_name="novel.uk.epub")

            details = get_translation_run_details(temp_dir, logger.run_dir.name)

        self.assertIsNotNone(details)
        assert details is not None
        self.assertEqual(details.summary.job_id, "job-detail")
        self.assertEqual(details.summary.status, "ready")
        self.assertEqual(details.totals["total_tokens"], 170)
        self.assertEqual(details.metadata["prompt_version"], "prompt-v2")
        self.assertEqual(details.metadata["adapter_version"], "epub-adapter-v3")
        self.assertEqual(details.translation_stack["schema_version"], "stack-v1")
        self.assertEqual(details.fragments[0].sequence, 1)
        self.assertEqual(details.fragments[0].source_text_chars, 18)
        self.assertEqual(details.fragments[0].translated_text_chars, 18)
        self.assertEqual(details.fragments[0].source_block_ids, ("chapter-1",))
        self.assertIn("run_started", [event.event_type for event in details.events])
        self.assertNotIn("Original paragraph", repr(details))
        self.assertNotIn("Перекладений абзац", repr(details))

    def test_translation_run_archive_keeps_book_audit_metadata_only(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-book-archive",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="novel.txt",
                    document_kind="txt",
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
            logger.record_event(
                "provider_failure",
                {
                    "prompt": "ARCHIVE PROMPT SENTINEL",
                    "error_message": (
                        "Traceback (most recent call last) provider diagnostics "
                        "api_key=sk-archive-secret"
                    ),
                },
            )
            logger.record_fragment(
                TranslationFragmentLog(
                    sequence=1,
                    source_text="ARCHIVE RAW SOURCE SENTINEL",
                    translated_text=(
                        "Вот перевод: Комната затихла, but he had reliable "
                        "information that the disease was serious."
                    ),
                    status="translated",
                    elapsed_seconds=1.0,
                    prompt_tokens=10,
                    completion_tokens=5,
                    total_tokens=15,
                )
            )
            logger.finish(status="ready", result_file_name="novel.ru.txt")

            archive = build_translation_run_archive(temp_dir, logger.run_dir.name)
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            assert details is not None
            effective_archive = build_effective_translation_run_archive(
                temp_dir,
                logger.run_dir.name,
                details=details,
            )

        self.assertIsNotNone(archive)
        self.assertIsNotNone(effective_archive)
        archive_text = _archive_text(archive.content) + _archive_text(
            effective_archive.content
        )
        self.assertIn("book_mode_audit", archive_text)
        self.assertIn("provider_commentary", archive_text)
        self.assertIn("untranslated_source_residue", archive_text)
        self.assertNotIn("ARCHIVE RAW SOURCE SENTINEL", archive_text)
        self.assertNotIn("ARCHIVE PROMPT SENTINEL", archive_text)
        self.assertNotIn("provider diagnostics", archive_text)
        self.assertNotIn("sk-archive-secret", archive_text)
        self.assertNotIn("Traceback", archive_text)
        self.assertNotIn("Вот перевод", archive_text)
        self.assertNotIn("disease was serious", archive_text)

    def test_effective_archive_includes_provider_io_diagnostics(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-provider-io-archive",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="novel.epub",
                    document_kind="epub",
                    source_language="auto",
                    target_language="ru",
                ),
            )
            (logger.run_dir / "provider_io_diagnostics.jsonl").write_text(
                json.dumps(
                    {
                        "schema_version": "provider-io-diagnostics-v1",
                        "diagnostic_scope": "owner_only_translation_run_archive",
                        "provider_id": "deepseek",
                        "request_body": {
                            "encoding": "utf-8",
                            "text": '{"messages":[{"content":"EXACT PROMPT"}]}',
                        },
                        "response_body": {
                            "encoding": "utf-8",
                            "text": (
                                '{"choices":[{"message":'
                                '{"content":"EXACT RESPONSE"}}]}'
                            ),
                        },
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            assert details is not None
            effective_archive = build_effective_translation_run_archive(
                temp_dir,
                logger.run_dir.name,
                details=details,
            )

        self.assertIsNotNone(effective_archive)
        archive_text = _archive_text(effective_archive.content)
        self.assertIn("EXACT PROMPT", archive_text)
        self.assertIn("EXACT RESPONSE", archive_text)
        self.assertIn(
            "`provider_io_diagnostics.jsonl`, when present, is an",
            archive_text,
        )
        self.assertIn("raw provider response bodies", archive_text)
        self.assertIn("excludes provider Authorization", archive_text)
        from io import BytesIO
        from zipfile import ZipFile

        with ZipFile(BytesIO(effective_archive.content)) as archive:
            self.assertIn("provider_io_diagnostics.jsonl", archive.namelist())

    def test_effective_archive_includes_glossary_runtime_diagnostics(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-archive",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            logger.record_event(
                "glossary_runtime_adapter",
                {
                    "status": "ready",
                    "fallback_reason": "none",
                    "work_unit_sequence": 1,
                    "selected_entry_ids": ["glossary-entry:v1:darcy"],
                    "cache_policy": {
                        "behavior": "bypass_glossary_injected_cache",
                        "cache_get_allowed": False,
                        "cache_put_allowed": False,
                    },
                    "battle_test_preflight": {
                        "status": "ready",
                        "useful_entry_ids": ["glossary-entry:v1:darcy"],
                    },
                    "prompt_context": {
                        "included_entry_ids": ["glossary-entry:v1:darcy"],
                    },
                },
            )
            _write_provider_io(
                logger.run_dir,
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "Before prompt.\n"
                                '<glossary_context role="untrusted_reference_data">\n'
                                "<entry role=\"terminology_contract\">\n"
                                "<source_canonical>Darcy</source_canonical>\n"
                                "<target_canonical>Дарси</target_canonical>\n"
                                "</entry>\n"
                                "</glossary_context>\n"
                                "<translation_batch>Darcy returns.</translation_batch>"
                            ),
                        }
                    ]
                },
            )
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            assert details is not None
            effective_archive = build_effective_translation_run_archive(
                temp_dir,
                logger.run_dir.name,
                details=details,
            )

        self.assertIsNotNone(effective_archive)
        from io import BytesIO
        from zipfile import ZipFile

        with ZipFile(BytesIO(effective_archive.content)) as archive:
            names = set(archive.namelist())
            self.assertIn("glossary_runtime_diagnostics.json", names)
            sidecar = json.loads(archive.read("glossary_runtime_diagnostics.json"))
            readme = archive.read("README.md").decode("utf-8")

        self.assertEqual(
            sidecar["schema_version"],
            "glossary-runtime-archive-diagnostics-v1",
        )
        self.assertEqual(sidecar["diagnostic_scope"], "owner_only_admin_download")
        self.assertTrue(sidecar["contains_raw_glossary_diagnostics"])
        self.assertEqual(sidecar["glossary_mode"], "with_glossary")
        self.assertEqual(
            sidecar["summary"]["selected_entry_ids"],
            ["glossary-entry:v1:darcy"],
        )
        self.assertEqual(
            sidecar["adapter_events"][0]["cache_policy"]["behavior"],
            "bypass_glossary_injected_cache",
        )
        context_text = sidecar["rendered_prompt_contexts"][0]["text"]
        self.assertIn("<source_canonical>Darcy</source_canonical>", context_text)
        self.assertIn("<target_canonical>Дарси</target_canonical>", context_text)
        sidecar_text = json.dumps(sidecar, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Darcy returns.", sidecar_text)
        self.assertIn("glossary_runtime_diagnostics.json", readme)
        self.assertIn("provider_io_diagnostics.jsonl", sidecar_text)

    def test_effective_archive_includes_glossary_fallback_diagnostics(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-fallback-archive",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            logger.record_event(
                "glossary_runtime_adapter",
                {
                    "status": "fallback",
                    "fallback_reason": "runtime_glossary_data_unavailable",
                    "work_unit_sequence": None,
                    "selected_entry_ids": [],
                    "cache_policy": {
                        "behavior": "default_runtime_cache",
                        "cache_get_allowed": True,
                        "cache_put_allowed": True,
                    },
                    "battle_test_preflight": {
                        "status": "skipped",
                        "fallback_reason": "adapter_not_ready",
                        "reason_codes": ["adapter_not_ready"],
                    },
                },
            )
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            assert details is not None
            effective_archive = build_effective_translation_run_archive(
                temp_dir,
                logger.run_dir.name,
                details=details,
            )

        self.assertIsNotNone(effective_archive)
        from io import BytesIO
        from zipfile import ZipFile

        with ZipFile(BytesIO(effective_archive.content)) as archive:
            sidecar = json.loads(archive.read("glossary_runtime_diagnostics.json"))

        self.assertFalse(sidecar["contains_raw_glossary_diagnostics"])
        self.assertTrue(sidecar["metadata_only"])
        self.assertEqual(sidecar["glossary_mode"], "with_glossary")
        self.assertEqual(sidecar["rendered_prompt_contexts"], [])
        self.assertEqual(
            sidecar["adapter_events"][0]["fallback_reason"],
            "runtime_glossary_data_unavailable",
        )
        self.assertEqual(
            sidecar["adapter_events"][0]["cache_policy"]["behavior"],
            "default_runtime_cache",
        )

    def test_effective_archive_omits_glossary_diagnostics_without_glossary_data(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-no-glossary-archive",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "without_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            logger.record_event("work_unit_finished", {"sequence": 1})
            _write_provider_io(
                logger.run_dir,
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "<translation_batch>"
                                "<glossary_context>"
                                "literal source text"
                                "</glossary_context>"
                                "</translation_batch>"
                            ),
                        }
                    ]
                },
            )
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            assert details is not None
            effective_archive = build_effective_translation_run_archive(
                temp_dir,
                logger.run_dir.name,
                details=details,
            )

        self.assertIsNotNone(effective_archive)
        from io import BytesIO
        from zipfile import ZipFile

        with ZipFile(BytesIO(effective_archive.content)) as archive:
            self.assertNotIn(
                "glossary_runtime_diagnostics.json",
                archive.namelist(),
            )

    def test_glossary_archive_diagnostics_reject_secret_material(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-secret-archive",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            logger.record_event(
                "glossary_runtime_adapter",
                {
                    "status": "ready",
                    "selected_entry_ids": ["glossary-entry:v1:secret"],
                    "api_key": "sk-event-secret-value",
                    "authorization": "Bearer event-secret-value",
                    "diagnostic": {
                        "prompt_body": "RAW PROMPT BODY MUST NOT COPY",
                        "source_text": "RAW SOURCE TEXT MUST NOT COPY",
                    },
                },
            )
            _write_provider_io(
                logger.run_dir,
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                '<glossary_context role="untrusted_reference_data">\n'
                                "<entry role=\"terminology_contract\">\n"
                                "<source_canonical>Secret</source_canonical>\n"
                                "<target_canonical>sk-context-secret-value</target_canonical>\n"
                                "</entry>\n"
                                "</glossary_context>"
                            ),
                        }
                    ]
                },
            )
            details = get_translation_run_details(temp_dir, logger.run_dir.name)
            assert details is not None
            effective_archive = build_effective_translation_run_archive(
                temp_dir,
                logger.run_dir.name,
                details=details,
            )

        self.assertIsNotNone(effective_archive)
        from io import BytesIO
        from zipfile import ZipFile

        with ZipFile(BytesIO(effective_archive.content)) as archive:
            sidecar = json.loads(archive.read("glossary_runtime_diagnostics.json"))

        sidecar_text = json.dumps(sidecar, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("sk-event-secret-value", sidecar_text)
        self.assertNotIn("Bearer event-secret-value", sidecar_text)
        self.assertNotIn("sk-context-secret-value", sidecar_text)
        self.assertNotIn("RAW PROMPT BODY MUST NOT COPY", sidecar_text)
        self.assertNotIn("RAW SOURCE TEXT MUST NOT COPY", sidecar_text)
        self.assertEqual(sidecar["rendered_prompt_contexts"], [])
        self.assertEqual(
            sidecar["rejected_prompt_contexts"][0]["reason"],
            "secret_material_detected",
        )
        self.assertTrue(sidecar["secret_material_rejected"])
        self.assertEqual(
            sidecar["adapter_events"][0]["raw_event_redactions"][0]["reason"],
            "raw_event_field_rejected",
        )


def _archive_text(content: bytes) -> str:
    from io import BytesIO
    from zipfile import ZipFile

    with ZipFile(BytesIO(content)) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
        )


def _write_provider_io(run_dir, request_payload: dict) -> None:
    (run_dir / "provider_io_diagnostics.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "provider-io-diagnostics-v1",
                "diagnostic_scope": "owner_only_translation_run_archive",
                "provider_id": "deepseek",
                "request_body": {
                    "encoding": "utf-8",
                    "text": json.dumps(request_payload, ensure_ascii=False),
                },
                "response_body": {
                    "encoding": "utf-8",
                    "text": '{"choices":[{"message":{"content":"OK"}}]}',
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
