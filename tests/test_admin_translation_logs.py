from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from tempfile import TemporaryDirectory

from translator_service.admin.translation_logs import (
    _glossary_participation_status_from_payload,
    build_effective_translation_run_archive,
    build_translation_run_archive,
    get_translation_run_details,
    list_translation_run_summaries,
)
from translator_service.admin.views import log_detail_body
from translator_service.translation_run_logs import (
    TranslationFragmentLog,
    TranslationRunLogger,
    TranslationRunMetadata,
    append_translation_run_event_for_job,
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
        self.assertEqual(
            sidecar["adapter_events"][0]["automatic_glossary_preflight"],
            sidecar["adapter_events"][0]["battle_test_preflight"],
        )
        self.assertEqual(
            sidecar["adapter_events"][0]["automatic_glossary_preflight"]["status"],
            "ready",
        )
        context_text = sidecar["rendered_prompt_contexts"][0]["text"]
        self.assertIn("<source_canonical>Darcy</source_canonical>", context_text)
        self.assertIn("<target_canonical>Дарси</target_canonical>", context_text)
        sidecar_text = json.dumps(sidecar, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Darcy returns.", sidecar_text)
        self.assertIn("glossary_runtime_diagnostics.json", readme)
        self.assertIn("provider_io_diagnostics.jsonl", sidecar_text)

    def test_effective_archive_includes_automatic_glossary_policy_diagnostics(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-automatic-glossary-archive",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.txt",
                    document_kind="txt",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            logger.record_event(
                "prepared_glossary_package_attachment",
                {
                    "schema_version": "prepared-glossary-package-attachment-v1",
                    "attachment_status": "attached",
                    "attachment_reason_codes": ["ready"],
                    "attachment_source": "prep",
                    "fail_closed": False,
                    "metadata_only": True,
                    "raw_payload_included": False,
                    "document_kind": "txt",
                    "source_language": "en",
                    "target_language": "ru",
                    "translation_mode": "book",
                    "glossary_mode": "with_glossary",
                    "source_sha256_short": "abc123def456",
                    "status": "ready",
                    "reason_codes": ["ready"],
                    "package_id": "prepared:automatic:ru",
                    "package_signature": "prepared-signature",
                    "entry_count": 2,
                    "ready_entry_count": 2,
                    "needs_review_entry_count": 0,
                    "glossary_prep_beta_safety": {
                        "schema_version": "prepared-glossary-prep-beta-safety-v1",
                        "metadata_only": True,
                        "raw_payload_included": False,
                        "reservation_status": "consumed",
                        "reason_codes": [],
                        "reservation_job_id": "job-automatic:prepared_glossary_prep",
                        "estimated_prompt_tokens": 1200,
                        "estimated_completion_tokens": 600,
                        "estimated_cost_usd": 0.12,
                        "provider_reported_usage_status": "reported",
                        "accounting_usage_source": "provider_reported",
                        "accounted_prompt_tokens": 1100,
                        "accounted_completion_tokens": 500,
                    },
                },
            )
            append_translation_run_event_for_job(
                temp_dir,
                job_id="job-automatic-glossary-archive",
                event_type="glossary_runtime_adapter",
                payload={
                    "status": "planned",
                    "fallback_reason": "none",
                    "work_unit_sequence": 1,
                    "document_format": "txt",
                    "selected_entry_ids": ["glossary-entry:v1:darcy"],
                    "cache_policy": {
                        "behavior": "bypass_glossary_injected_cache",
                        "cache_get_allowed": False,
                        "cache_put_allowed": False,
                    },
                    "prompt_context": {
                        "included_entry_count": 1,
                        "included_entry_ids": ["glossary-entry:v1:darcy"],
                        "omitted_entries": [
                            {
                                "entry_id": "glossary-entry:v1:bingley",
                                "reason": "entry_limit_exceeded",
                                "estimated_prompt_tokens": 60,
                            }
                        ],
                        "estimated_prompt_tokens": 144,
                        "prompt_budget_tokens": 700,
                        "character_count": 480,
                        "character_budget": 2400,
                    },
                    "prepared_package": {
                        "schema_version": "prepared-glossary-package-v1",
                        "metadata_only": True,
                        "raw_payload_included": False,
                        "status": "ready",
                        "reason_codes": ["ready"],
                        "package_id": "prepared:automatic:ru",
                        "package_signature": "prepared-signature",
                        "target_language": "ru",
                        "entry_count": 2,
                        "ready_entry_count": 2,
                        "needs_review_entry_count": 0,
                    },
                    "glossary_compliance": {
                        "schema_version": "glossary-compliance-v2",
                        "policy": "glossary_compliance.target_forms",
                        "status": "pass",
                        "reason_codes": ["target_form_present"],
                        "selected_entry_count": 1,
                        "checked_entry_count": 1,
                        "target_form_present_count": 1,
                        "target_form_missing_count": 0,
                        "forbidden_variant_count": 0,
                        "needs_review_entry_count": 0,
                        "skipped_entry_count": 0,
                        "selected_entry_ids": ["glossary-entry:v1:darcy"],
                        "checked_entry_ids": ["glossary-entry:v1:darcy"],
                        "target_form_present_entry_ids": [
                            "glossary-entry:v1:darcy"
                        ],
                        "target_form_missing_entry_ids": [],
                        "forbidden_variant_entry_ids": [],
                        "needs_review_entry_ids": [],
                        "skipped_entry_ids": [],
                        "metadata_only": True,
                        "raw_payload_included": False,
                        "semantic_quality_claim_made": False,
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
                                "<source_canonical>Darcy</source_canonical>\n"
                                "<target_canonical>Дарси</target_canonical>\n"
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
            detail_html = log_detail_body(details)

        self.assertIsNotNone(effective_archive)
        from io import BytesIO
        from zipfile import ZipFile

        with ZipFile(BytesIO(effective_archive.content)) as archive:
            sidecar = json.loads(archive.read("glossary_runtime_diagnostics.json"))
            summary_md = archive.read("summary.md").decode("utf-8")

        self.assertEqual(
            sidecar["automatic_glossary_policy"]["policy_status"],
            "automatic_default_enabled",
        )
        self.assertFalse(
            sidecar["automatic_glossary_policy"]["user_facing_selector_required"],
        )
        self.assertEqual(sidecar["summary"]["attachment_event_count"], 1)
        self.assertEqual(sidecar["summary"]["attachment_statuses"], ["attached"])
        self.assertEqual(sidecar["summary"]["target_metadata_status"], "present")
        self.assertEqual(sidecar["summary"]["rendered_prompt_context_count"], 1)
        self.assertEqual(sidecar["summary"]["prompt_context_event_count"], 0)
        self.assertEqual(sidecar["summary"]["compliance_summary_count"], 1)
        self.assertEqual(sidecar["summary"]["compliance_statuses"], ["pass"])
        self.assertEqual(sidecar["attachment_events"][0]["attachment_source"], "prep")
        self.assertEqual(
            sidecar["attachment_events"][0]["glossary_prep_beta_safety"][
                "reservation_status"
            ],
            "consumed",
        )
        rendered_context_text = sidecar["rendered_prompt_contexts"][0]["text"]
        self.assertIn(
            "<target_canonical>Дарси</target_canonical>",
            rendered_context_text,
        )
        self.assertEqual(
            sidecar["compliance_summaries"][0]["target_form_present_count"],
            1,
        )
        self.assertEqual(
            sidecar["effectiveness_diagnostic"]["status"],
            "effective_observed",
        )
        self.assertEqual(
            sidecar["effectiveness_diagnostic"]["glossary_participation_status"],
            "requested_effective_observed",
        )
        self.assertEqual(
            sidecar["summary"]["glossary_participation_status"],
            "requested_effective_observed",
        )
        self.assertIn(
            "Glossary participation: `requested_effective_observed`",
            summary_md,
        )
        self.assertIn("Glossary participation", detail_html)
        self.assertIn("requested_effective_observed", detail_html)
        self.assertNotIn(
            "not_effective",
            sidecar["summary"]["glossary_effective_statuses"],
        )
        self.assertEqual(sidecar["summary"]["cache_bypass_event_count"], 1)

    def test_effective_archive_marks_ready_package_zero_contexts_not_effective(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-ready-zero-glossary-contexts",
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
                "prepared_glossary_package_attachment",
                {
                    "schema_version": "prepared-glossary-package-attachment-v1",
                    "attachment_status": "attached",
                    "attachment_reason_codes": ["ready"],
                    "attachment_source": "prep",
                    "fail_closed": False,
                    "metadata_only": True,
                    "raw_payload_included": False,
                    "document_kind": "epub",
                    "source_language": "en",
                    "target_language": "ru",
                    "translation_mode": "book",
                    "glossary_mode": "with_glossary",
                    "source_sha256_short": "abc123def456",
                    "status": "ready",
                    "reason_codes": ["ready"],
                    "package_id": "prepared:automatic:ru",
                    "package_signature": "prepared-signature",
                    "entry_count": 5,
                    "ready_entry_count": 5,
                    "needs_review_entry_count": 0,
                },
            )
            append_translation_run_event_for_job(
                temp_dir,
                job_id="job-ready-zero-glossary-contexts",
                event_type="glossary_runtime_adapter",
                payload={
                    "status": "fallback",
                    "fallback_reason": (
                        "persistent_glossary_prepared_package_no_applicable_entries"
                    ),
                    "work_unit_sequence": 1,
                    "document_format": "epub",
                    "selected_entry_ids": [],
                    "cache_policy": {
                        "behavior": "default_runtime_cache",
                        "cache_get_allowed": True,
                        "cache_put_allowed": True,
                    },
                    "prepared_package": {
                        "schema_version": "prepared-glossary-package-v1",
                        "metadata_only": True,
                        "raw_payload_included": False,
                        "status": "ready",
                        "reason_codes": ["ready"],
                        "package_id": "prepared:automatic:ru",
                        "package_signature": "prepared-signature",
                        "target_language": "ru",
                        "entry_count": 5,
                        "ready_entry_count": 5,
                        "needs_review_entry_count": 0,
                    },
                    "prepared_package_runtime_bridge": {
                        "schema_version": (
                            "prepared-glossary-package-runtime-bridge-v1"
                        ),
                        "status": "skipped",
                        "reason_codes": [
                            (
                                "prepared_package_runtime_bridge_"
                                "no_applicable_entries"
                            )
                        ],
                        "entry_count": 5,
                        "applicable_entry_count": 0,
                        "target_metadata_missing_count": 0,
                        "source_ref_mismatch_count": 5,
                        "source_term_missing_count": 5,
                        "metadata_only": True,
                        "raw_payload_included": False,
                    },
                    "battle_test_preflight": {
                        "status": "skipped",
                        "fallback_reason": "source_match_missing",
                        "reason_codes": ["source_match_missing"],
                    },
                    "raw_source_text": "Forbidden raw source sample",
                    "prompt_body": "Forbidden prompt body",
                    "provider_response": "Forbidden provider body",
                    "translated_text": "Forbidden translated text",
                    "api_key": "fake-key-for-redaction-test",
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
        self.assertEqual(
            sidecar["summary"]["glossary_effective_status"],
            "not_effective",
        )
        self.assertIn("error", sidecar["summary"]["diagnostic_severities"])
        self.assertIn(
            "not_effective",
            sidecar["summary"]["glossary_effective_statuses"],
        )
        self.assertIn(
            "ready_prepared_package_zero_rendered_contexts",
            sidecar["summary"]["glossary_effective_reason_codes"],
        )
        diagnostic = sidecar["effectiveness_diagnostic"]
        self.assertEqual(diagnostic["status"], "not_effective")
        self.assertEqual(
            diagnostic["glossary_participation_status"],
            "requested_not_effective",
        )
        self.assertEqual(
            sidecar["summary"]["glossary_participation_status"],
            "requested_not_effective",
        )
        self.assertEqual(diagnostic["diagnostic_severity"], "error")
        self.assertTrue(diagnostic["ready_prepared_package_attached"])
        self.assertEqual(diagnostic["prepared_package_entry_count"], 5)
        self.assertEqual(
            diagnostic["runtime_applicable_entry_observation_count"],
            0,
        )
        self.assertEqual(diagnostic["rendered_prompt_context_count"], 0)
        self.assertEqual(diagnostic["compliance_summary_count"], 0)
        self.assertEqual(diagnostic["cache_bypass_event_count"], 0)
        self.assertEqual(sidecar["summary"]["cache_bypass_event_count"], 0)
        self.assertEqual(
            sidecar["summary"]["diagnostic_reason_code_counts"][
                "persistent_glossary_prepared_package_no_applicable_entries"
            ],
            2,
        )
        self.assertEqual(
            sidecar["summary"]["diagnostic_reason_code_counts"][
                "prepared_package_runtime_bridge_no_applicable_entries"
            ],
            1,
        )
        sidecar_text = json.dumps(sidecar, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Forbidden raw source sample", sidecar_text)
        self.assertNotIn("Forbidden prompt body", sidecar_text)
        self.assertNotIn("Forbidden provider body", sidecar_text)
        self.assertNotIn("Forbidden translated text", sidecar_text)
        self.assertNotIn("fake-key-for-redaction-test", sidecar_text)

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
        self.assertEqual(
            sidecar["effectiveness_diagnostic"]["status"],
            "not_observed",
        )
        self.assertEqual(
            sidecar["effectiveness_diagnostic"]["glossary_participation_status"],
            "requested_not_observed",
        )

    def test_glossary_diagnostics_mark_unknown_policy_as_unknown(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-policy-unknown",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=None,
                ),
            )
            logger.record_event(
                "glossary_runtime_adapter",
                {
                    "status": "fallback",
                    "fallback_reason": "runtime_glossary_data_unavailable",
                    "work_unit_sequence": None,
                    "document_format": "epub",
                    "cache_policy": {
                        "behavior": "default_runtime_cache",
                        "cache_get_allowed": True,
                        "cache_put_allowed": True,
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

        self.assertEqual(sidecar["glossary_mode"], "Unknown")
        self.assertEqual(sidecar["effectiveness_diagnostic"]["status"], "unknown")
        self.assertEqual(
            sidecar["effectiveness_diagnostic"]["glossary_participation_status"],
            "unknown",
        )
        self.assertEqual(
            sidecar["summary"]["glossary_participation_status"],
            "unknown",
        )
        self.assertIn(
            "glossary_policy_unknown",
            sidecar["effectiveness_diagnostic"]["reason_codes"],
        )

    def test_glossary_diagnostics_mark_without_glossary_as_not_requested(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-not-requested",
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
            logger.record_event(
                "glossary_runtime_adapter",
                {
                    "status": "fallback",
                    "fallback_reason": "glossary_not_requested",
                    "work_unit_sequence": None,
                    "document_format": "epub",
                    "cache_policy": {
                        "behavior": "default_runtime_cache",
                        "cache_get_allowed": True,
                        "cache_put_allowed": True,
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

        self.assertEqual(sidecar["glossary_mode"], "without_glossary")
        self.assertEqual(
            sidecar["effectiveness_diagnostic"]["status"],
            "not_requested",
        )
        self.assertEqual(
            sidecar["effectiveness_diagnostic"]["glossary_participation_status"],
            "not_requested",
        )
        self.assertIn(
            "glossary_policy_not_requested",
            sidecar["effectiveness_diagnostic"]["reason_codes"],
        )
        self.assertNotIn(
            "not_requested",
            sidecar["summary"]["glossary_effective_statuses"],
        )

    def test_glossary_participation_status_from_payload_handles_edge_cases(self):
        cases = (
            (None, None),
            ({}, None),
            ({"effectiveness_diagnostic": {}}, None),
            (
                {"effectiveness_diagnostic": {"glossary_participation_status": ""}},
                None,
            ),
            (
                {
                    "effectiveness_diagnostic": {
                        "glossary_participation_status": "effective_observed"
                    }
                },
                "effective_observed",
            ),
            (
                {
                    "effectiveness_diagnostic": {
                        "glossary_participation_status": "not_requested"
                    }
                },
                "not_requested",
            ),
            (
                {
                    "effectiveness_diagnostic": {
                        "glossary_participation_status": "future_status"
                    }
                },
                "future_status",
            ),
        )
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(
                    _glossary_participation_status_from_payload(payload),
                    expected,
                )

    def test_effective_archive_summarizes_automatic_glossary_fallback_reasons(self):
        with TemporaryDirectory() as temp_dir:
            logger = TranslationRunLogger.start(
                root=temp_dir,
                metadata=TranslationRunMetadata(
                    job_id="job-glossary-fallback-reasons",
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.docx",
                    document_kind="docx",
                    source_language="en",
                    target_language="ru",
                    translation_policy=json.dumps(
                        {"glossary_mode": "with_glossary"},
                        ensure_ascii=False,
                    ),
                ),
            )
            logger.record_event(
                "prepared_glossary_package_attachment",
                {
                    "attachment_status": "skipped",
                    "attachment_reason_codes": [
                        "prepared_glossary_package_attachment_disabled"
                    ],
                    "attachment_source": "resolver",
                    "diagnostic_severity": "error",
                    "glossary_effective_status": "not_effective",
                    "metadata_only": True,
                    "raw_payload_included": False,
                },
            )
            logger.record_event(
                "glossary_runtime_adapter",
                {
                    "status": "fallback",
                    "fallback_reason": "persistent_glossary_no_useful_glossary_entries",
                    "work_unit_sequence": 1,
                    "document_format": "docx",
                    "cache_policy": {
                        "behavior": "default_runtime_cache",
                        "cache_get_allowed": True,
                        "cache_put_allowed": True,
                    },
                    "battle_test_preflight": {
                        "status": "skipped",
                        "fallback_reason": (
                            "persistent_glossary_prompt_context_budget_exhausted"
                        ),
                        "reason_codes": ["prompt_context_budget_exhausted"],
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

        self.assertEqual(
            sidecar["automatic_glossary_policy"]["runtime_intent"],
            "attempt_glossary_when_ready",
        )
        self.assertIn(
            "prepared_glossary_package_attachment_disabled",
            sidecar["summary"]["diagnostic_reason_codes"],
        )
        self.assertIn("error", sidecar["summary"]["diagnostic_severities"])
        self.assertIn(
            "not_effective",
            sidecar["summary"]["glossary_effective_statuses"],
        )
        self.assertEqual(
            sidecar["summary"]["glossary_effective_status"],
            "not_effective",
        )
        self.assertIn(
            "persistent_glossary_no_useful_glossary_entries",
            sidecar["summary"]["diagnostic_reason_codes"],
        )
        self.assertIn(
            "persistent_glossary_prompt_context_budget_exhausted",
            sidecar["summary"]["diagnostic_reason_codes"],
        )
        self.assertIn(
            "prompt_context_budget_exhausted",
            sidecar["summary"]["diagnostic_reason_codes"],
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
            logger.record_event(
                "prepared_glossary_package_attachment",
                {
                    "attachment_status": "skipped",
                    "attachment_reason_codes": ["prepared_glossary_package_invalid"],
                    "attachment_source": "prep",
                    "api_key": "sk-attachment-secret-value",
                    "authorization_header": "Bearer attachment-secret-value",
                    "raw_source_text": "RAW ATTACHMENT SOURCE MUST NOT COPY",
                    "glossary_prep_beta_safety": {
                        "reservation_status": "blocked",
                        "reason_codes": ["prepared_glossary_prep_beta_safety_blocked"],
                        "reservation_job_id": "postgres://secret:user@localhost/db",
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
        self.assertNotIn("sk-attachment-secret-value", sidecar_text)
        self.assertNotIn("Bearer attachment-secret-value", sidecar_text)
        self.assertNotIn("RAW ATTACHMENT SOURCE MUST NOT COPY", sidecar_text)
        self.assertNotIn("postgres://secret:user@localhost/db", sidecar_text)
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
