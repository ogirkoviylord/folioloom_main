import json
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from translator_service.admin.translation_logs import (
    build_effective_translation_run_archive,
    get_translation_run_details,
)
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.glossary_candidate_reducer import GlossaryCandidateReducerCaps
from translator_service.glossary_persistent_runtime_resolver import (
    PersistentEpubGlossaryResolverConfig,
    build_persistent_epub_glossary_runtime_hook_resolver,
)
from translator_service.glossary_target_metadata_overlay import (
    GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
)
from translator_service.persistent_jobs import (
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)
from translator_service.provider_io_diagnostics import record_provider_io_exchange
from translator_service.scheduler import SchedulerLimits
from translator_service.translation_run_logs import (
    TranslationRunLogger,
    TranslationRunMetadata,
)
from translator_service.worker import (
    ProviderUsage,
    run_next_scheduled_stored_text_work_unit,
)


class EpubGlossaryRehearsalArchiveTests(unittest.TestCase):
    def test_with_glossary_rehearsal_exports_owner_only_archive_evidence(self):
        result = _run_rehearsal(glossary_mode="with_glossary")

        self.assertEqual(result.completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertIn("<glossary_context", result.translator.calls[0])
        self.assertIn("Дарси", result.translator.calls[0])
        self.assertNotIn("Дарси", result.event_lines)
        self.assertNotIn("Darcy returns.", result.event_lines)

        sidecar = result.archive_sidecar
        self.assertEqual(sidecar["diagnostic_scope"], "owner_only_admin_download")
        self.assertEqual(sidecar["glossary_mode"], "with_glossary")
        self.assertTrue(sidecar["contains_raw_glossary_diagnostics"])
        self.assertEqual(
            sidecar["summary"]["cache_policy_behaviors"],
            ["bypass_glossary_injected_cache"],
        )
        self.assertEqual(
            sidecar["adapter_events"][0]["battle_test_preflight"]["status"],
            "ready",
        )
        context_text = sidecar["rendered_prompt_contexts"][0]["text"]
        self.assertIn("<source_canonical>Darcy</source_canonical>", context_text)
        self.assertIn("<target_canonical>Дарси</target_canonical>", context_text)
        sidecar_text = json.dumps(sidecar, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("Darcy returns.", sidecar_text)
        self.assertIn("provider_io_diagnostics.jsonl", sidecar_text)

    def test_with_glossary_fallback_rehearsal_records_metadata_only_reason(self):
        result = _run_rehearsal(
            glossary_mode="with_glossary",
            overlay_payload=_overlay_payload(target_language="uk"),
        )

        self.assertEqual(result.completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertNotIn("<glossary_context", result.translator.calls[0])
        sidecar = result.archive_sidecar
        self.assertTrue(sidecar["metadata_only"])
        self.assertFalse(sidecar["contains_raw_glossary_diagnostics"])
        self.assertEqual(sidecar["rendered_prompt_contexts"], [])
        self.assertEqual(
            sidecar["adapter_events"][0]["fallback_reason"],
            "persistent_epub_target_metadata_overlay_invalid",
        )
        self.assertEqual(
            sidecar["adapter_events"][0]["cache_policy"]["behavior"],
            "default_runtime_cache",
        )

    def test_without_glossary_rehearsal_omits_glossary_archive_sidecar(self):
        result = _run_rehearsal(glossary_mode="without_glossary")

        self.assertEqual(result.completed.status, PersistentWorkUnitStatus.TRANSLATED)
        self.assertNotIn("<glossary_context", result.translator.calls[0])
        self.assertNotIn("glossary_runtime_adapter", result.event_lines)
        self.assertNotIn("glossary_runtime_diagnostics.json", result.archive_names)


class _PromptIODiagnosticTranslator:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last_usage: ProviderUsage | None = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.calls.append(text)
        self.last_usage = ProviderUsage(prompt_tokens=17, completion_tokens=5)
        request_body = json.dumps(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": text,
                    }
                ]
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        record_provider_io_exchange(
            provider_id="fake-local-rehearsal",
            url="local://fake-provider",
            request_body=request_body,
            http_status=200,
            response_body=b'{"output":"fake"}',
            transport_attempt=1,
        )
        return (
            "<translation_batch>"
            f'<translation_block id="0">[{target_language}] '
            "Дарси возвращается.</translation_block>"
            "</translation_batch>"
        )


class _RehearsalResult:
    def __init__(
        self,
        *,
        completed: PersistentWorkUnit,
        translator: _PromptIODiagnosticTranslator,
        event_lines: str,
        archive_names: set[str],
        archive_sidecar: dict[str, object],
    ) -> None:
        self.completed = completed
        self.translator = translator
        self.event_lines = event_lines
        self.archive_names = archive_names
        self.archive_sidecar = archive_sidecar


def _run_rehearsal(
    *,
    glossary_mode: str,
    overlay_payload: dict[str, object] | None = None,
) -> _RehearsalResult:
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        storage = LocalObjectStorage(root / "objects")
        source = storage.put_bytes(
            kind=StoredFileKind.INTERMEDIATE,
            file_name="unit-1.txt",
            content_type="text/plain; charset=utf-8",
            content=b"Darcy returns.",
        )
        run_log_root = root / "run-logs"
        translation_policy = json.dumps(
            {"glossary_mode": glossary_mode},
            ensure_ascii=False,
        )
        store = SQLiteTranslationJobStore(":memory:")
        try:
            job_id = _create_epub_job(
                store,
                source_object_key=source.object_key,
                translation_policy=translation_policy,
            )
            logger = TranslationRunLogger.start(
                root=run_log_root,
                metadata=TranslationRunMetadata(
                    job_id=job_id,
                    order_id=None,
                    user_id="telegram:42",
                    file_name="book.epub",
                    document_kind="epub",
                    source_language="en",
                    target_language="ru",
                    translation_policy=translation_policy,
                ),
            )
            translator = _PromptIODiagnosticTranslator()
            resolver = build_persistent_epub_glossary_runtime_hook_resolver(
                source_text_loader=lambda work_unit: storage.get_bytes(
                    work_unit.source_object_key
                ).decode("utf-8"),
                target_metadata_overlay_payload=(
                    overlay_payload
                    if overlay_payload is not None
                    else _overlay_payload()
                ),
                config=_resolver_config(),
            )

            completed = run_next_scheduled_stored_text_work_unit(
                store=store,
                storage=storage,
                worker_id="worker-a",
                lease_seconds=300,
                limits=SchedulerLimits(),
                translator=translator,
                translation_run_log_root=run_log_root,
                glossary_runtime_hook_resolver=resolver,
            )
            assert completed is not None
        finally:
            store.close()

        details = get_translation_run_details(run_log_root, logger.run_dir.name)
        assert details is not None
        archive = build_effective_translation_run_archive(
            run_log_root,
            logger.run_dir.name,
            details=details,
        )
        assert archive is not None
        event_lines = logger.run_dir.joinpath("events.jsonl").read_text(
            encoding="utf-8",
        )
        archive_names, sidecar = _archive_sidecar(archive.content)
        return _RehearsalResult(
            completed=completed,
            translator=translator,
            event_lines=event_lines,
            archive_names=archive_names,
            archive_sidecar=sidecar,
        )


def _archive_sidecar(content: bytes) -> tuple[set[str], dict[str, object]]:
    with ZipFile(BytesIO(content)) as archive:
        names = set(archive.namelist())
        if "glossary_runtime_diagnostics.json" not in names:
            return names, {}
        return names, json.loads(archive.read("glossary_runtime_diagnostics.json"))


def _create_epub_job(
    store: SQLiteTranslationJobStore,
    *,
    source_object_key: str,
    translation_policy: str,
) -> str:
    job = store.create_job(
        order_id="order-1",
        user_id="user-42",
        file_id="file-1",
        file_name="book.epub",
        document_kind="epub",
        source_language="en",
        target_language="ru",
        adapter_version="epub-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        translation_policy=translation_policy,
    )
    store.add_work_units(
        job.id,
        [
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("chapter-1:p1",),
                source_text_hash="hash-1",
                prompt_tier="plain",
                source_language="en",
                target_language="ru",
                source_object_key=source_object_key,
            ),
        ],
    )
    return job.id


def _resolver_config() -> PersistentEpubGlossaryResolverConfig:
    return PersistentEpubGlossaryResolverConfig(
        enabled=True,
        owner_battle_test_enabled=True,
        reducer_caps=GlossaryCandidateReducerCaps(
            max_editor_entries=20,
            max_diagnostic_entries=20,
            max_estimated_editor_tokens=1000,
            min_editor_score=1,
            min_diagnostic_score=1,
        ),
    )


def _overlay_payload(*, target_language: str = "ru") -> dict[str, object]:
    return {
        "schema_version": GLOSSARY_TARGET_METADATA_OVERLAY_SCHEMA_VERSION,
        "overlay_id": "epub-rehearsal-overlay",
        "scope": "local_owner_only_real_book_battle_test",
        "owner_approved": True,
        "source_language": "en",
        "targets": {
            target_language: {
                "entries": [
                    {
                        "source_canonical": "Darcy",
                        "target_canonical": "Дарси",
                        "target_variants": ["мистер Дарси"],
                    }
                ]
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
