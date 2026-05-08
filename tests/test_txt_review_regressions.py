from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_service.extractors import TextExtractionError
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_assembly import assemble_persistent_txt_result
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.persistent_planner import create_persistent_txt_job_plan
from translator_service.translation_runner import translate_txt_document


class RecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.requests.append((text, source_language, target_language))
        return f"[{target_language}] {text}"


class TxtReviewRegressionTest(unittest.TestCase):
    def test_rejects_raw_only_txt_without_calling_translator(self):
        translator = RecordingTranslator()

        with self.assertRaisesRegex(
            TextExtractionError,
            "TXT file does not contain translatable text",
        ):
            translate_txt_document(
                file_name="config.txt",
                content=b"API_KEY=secret\nTIMEOUT=30\n",
                source_language="en",
                target_language="uk",
                max_fragment_chars=100,
                translator=translator,
            )

        self.assertEqual(translator.requests, [])

    def test_rejects_persistent_txt_assembly_when_adapter_version_mismatches(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph.\n",
            )
            plan = create_persistent_txt_job_plan(
                store=store,
                storage=storage,
                order_id="order-txt",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="notes.txt",
                source_language="en",
                target_language="uk",
                max_fragment_chars=100,
            )
            store._connection.execute(
                "UPDATE translation_jobs SET adapter_version = ? WHERE id = ?",
                ("txt-adapter-old", plan.job.id),
            )
            store._connection.commit()
            work_unit = store.claim_next_work_unit(plan.job.id, worker_id="test")
            assert work_unit is not None
            store.complete_work_unit(
                work_unit_id=work_unit.id,
                translated_text="Перший абзац.",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )

            with self.assertRaisesRegex(ValueError, "TXT adapter version mismatch"):
                assemble_persistent_txt_result(
                    store=store,
                    storage=storage,
                    job_id=plan.job.id,
                    file_name="notes.uk.txt",
                    partial=False,
                )

    def test_persistent_txt_partial_assembly_preserves_pending_source_segments(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"First paragraph.\n\nSecond paragraph.\n",
            )
            plan = create_persistent_txt_job_plan(
                store=store,
                storage=storage,
                order_id="order-txt",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="notes.txt",
                source_language="en",
                target_language="uk",
                max_fragment_chars=100,
            )
            work_unit = store.claim_next_work_unit(plan.job.id, worker_id="test")
            assert work_unit is not None
            store.complete_work_unit(
                work_unit_id=work_unit.id,
                translated_text="[uk] First paragraph.",
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit_tokens=0,
                cache_miss_tokens=10,
            )

            stored = assemble_persistent_txt_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="notes.uk.partial.txt",
                partial=True,
            )

            self.assertEqual(
                storage.get_bytes(stored.object_key).decode("utf-8"),
                "[uk] First paragraph.\n\nSecond paragraph.\n",
            )


if __name__ == "__main__":
    unittest.main()
