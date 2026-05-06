from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_jobs import (
    PersistentTranslationJobStatus,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
)
from translator_service.persistent_planner import create_persistent_txt_job_plan


class PersistentPlannerTest(unittest.TestCase):
    def test_creates_txt_job_and_stored_work_units_from_original_file(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="notes.txt",
                content_type="text/plain; charset=utf-8",
                content=b"One.\n\nTwo.",
            )

            plan = create_persistent_txt_job_plan(
                store=store,
                storage=storage,
                order_id="order-1",
                user_id="user-42",
                source_object_key=original.object_key,
                file_name="notes.txt",
                source_language="en",
                target_language="uk",
                max_fragment_chars=5,
            )

            persisted_job = store.get_job(plan.job.id)
            persisted_units = store.list_work_units(plan.job.id)
            self.assertEqual(
                persisted_job.status,
                PersistentTranslationJobStatus.QUEUED,
            )
            self.assertEqual(persisted_job.source_object_key, original.object_key)
            self.assertEqual(persisted_job.document_kind, "txt")
            self.assertEqual(len(persisted_units), 2)
            self.assertEqual(
                [unit.status for unit in persisted_units],
                [PersistentWorkUnitStatus.PENDING, PersistentWorkUnitStatus.PENDING],
            )
            self.assertEqual(
                storage.get_bytes(persisted_units[0].source_object_key).decode("utf-8"),
                "One.",
            )
            self.assertEqual(
                storage.get_bytes(persisted_units[1].source_object_key).decode("utf-8"),
                "Two.",
            )
            self.assertEqual(plan.work_units, persisted_units)


if __name__ == "__main__":
    unittest.main()
