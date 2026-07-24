import json
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_job_store import admit_strict_docx_v3_job
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    SQLiteTranslationJobStore,
    StrictDocxV3AdmissionRequest,
    WorkUnitPlan,
)
from translator_service.strict_docx_v3_authorization_service import (
    StrictDocxV3AuthorizationDenied,
    StrictDocxV3AuthorizationServiceRequest,
    seal_strict_docx_v3_authorization,
)


class StrictDocxV3OwnerLocalSmokeTest(unittest.TestCase):
    def test_temporary_sqlite_admits_only_exact_sealed_document_custody(self):
        with _smoke_context() as (store, storage):
            source = _put_docx(storage)
            approval = _approval(store)
            authorization = _seal(
                store, storage, approval.approval_id, source.object_key
            )

            admitted = admit_strict_docx_v3_job(
                store,
                _admission_request(authorization.authorization_id, source),
                storage=storage,
            )

            self.assertTrue(admitted.admitted)
            self.assertIsNone(admitted.denial_code)
            self.assertIsNotNone(admitted.job)
            if admitted.job is None:
                raise AssertionError("v3 admission unexpectedly has no job")
            binding = store._connection.execute(
                "SELECT authorization_id, source_object_key, source_sha256, "
                "source_size_bytes FROM strict_docx_v3_job_authorizations "
                "WHERE job_id = ?",
                (admitted.job.id,),
            ).fetchone()
            self.assertEqual(
                tuple(binding),
                (
                    authorization.authorization_id,
                    source.object_key,
                    source.sha256,
                    source.size_bytes,
                ),
            )

    def test_temporary_sqlite_denies_changed_source_without_authorization_write(self):
        with _smoke_context() as (store, storage):
            source = _put_docx(storage)
            approval = _approval(store)
            _source_path(storage, source.object_key).write_bytes(
                b"x" * source.size_bytes
            )

            result = _seal(store, storage, approval.approval_id, source.object_key)

            self.assertEqual(
                result,
                StrictDocxV3AuthorizationDenied(
                    code="strict_docx_v3_source_digest_mismatch"
                ),
            )
            self.assertEqual(_authorization_count(store), 0)

    def test_temporary_sqlite_denies_missing_source_without_authorization_write(self):
        with _smoke_context() as (store, storage):
            approval = _approval(store)

            result = _seal(
                store, storage, approval.approval_id, "original/missing.docx"
            )

            self.assertEqual(
                result,
                StrictDocxV3AuthorizationDenied(code="strict_docx_v3_source_missing"),
            )
            self.assertEqual(_authorization_count(store), 0)

    def test_temporary_sqlite_denies_metadata_mismatch_without_authorization_write(
        self,
    ):
        with _smoke_context() as (store, storage):
            source = _put_docx(storage)
            approval = _approval(store)
            metadata_path = _source_path(storage, f"{source.object_key}.metadata.json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["object_key"] = "original/not-the-sealed-source.docx"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            result = _seal(store, storage, approval.approval_id, source.object_key)

            self.assertEqual(
                result,
                StrictDocxV3AuthorizationDenied(
                    code="strict_docx_v3_source_metadata_mismatch"
                ),
            )
            self.assertEqual(_authorization_count(store), 0)

    def test_temporary_sqlite_denies_revoked_authorization_without_job_write(self):
        with _smoke_context() as (store, storage):
            source = _put_docx(storage)
            approval = _approval(store)
            authorization = _seal(
                store, storage, approval.approval_id, source.object_key
            )
            store.revoke_strict_docx_v3_authorization(
                authorization_id=authorization.authorization_id
            )

            denied = admit_strict_docx_v3_job(
                store,
                _admission_request(authorization.authorization_id, source),
                storage=storage,
            )

            self.assertFalse(denied.admitted)
            self.assertEqual(
                denied.denial_code,
                "strict_docx_v3_authorization_revoked",
            )
            self.assertEqual(_job_count(store), 0)

    def test_temporary_sqlite_rechecks_sealed_source_before_admission_without_writes(
        self,
    ):
        for mutation, expected_denial in (
            ("changed", "strict_docx_v3_source_size_mismatch"),
            ("deleted", "strict_docx_v3_source_missing"),
            ("sidecar", "strict_docx_v3_source_digest_mismatch"),
        ):
            with self.subTest(mutation=mutation), _smoke_context() as (store, storage):
                source = _put_docx(storage)
                approval = _approval(store)
                authorization = _seal(
                    store, storage, approval.approval_id, source.object_key
                )
                if mutation == "changed":
                    _source_path(storage, source.object_key).write_bytes(b"changed")
                elif mutation == "deleted":
                    _source_path(storage, source.object_key).unlink()
                else:
                    metadata_path = _source_path(
                        storage, f"{source.object_key}.metadata.json"
                    )
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                    metadata["sha256"] = "0" * 64
                    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

                denied = admit_strict_docx_v3_job(
                    store,
                    _admission_request(authorization.authorization_id, source),
                    storage=storage,
                )

                self.assertFalse(denied.admitted)
                self.assertEqual(denied.denial_code, expected_denial)
                self.assertEqual(_job_count(store), 0)
                self.assertEqual(_binding_count(store), 0)
                self.assertEqual(_job_authorization_count(store), 0)

    def test_temporary_sqlite_derives_admission_identity_from_sealed_storage(self):
        with _smoke_context() as (store, storage):
            source = _put_docx(storage)
            approval = _approval(store)
            authorization = _seal(
                store, storage, approval.approval_id, source.object_key
            )
            request = replace(
                _admission_request(authorization.authorization_id, source),
                source_object_key="original/request-substitute.docx",
                source_sha256="0" * 64,
                source_size_bytes=1,
                work_units=[
                    replace(
                        _admission_request(
                            authorization.authorization_id, source
                        ).work_units[0],
                        source_object_key="original/request-substitute.docx",
                    )
                ],
            )

            admitted = admit_strict_docx_v3_job(store, request, storage=storage)

            self.assertTrue(admitted.admitted)
            if admitted.job is None:
                raise AssertionError("v3 admission unexpectedly has no job")
            self.assertEqual(admitted.job.source_object_key, source.object_key)
            self.assertEqual(
                store.list_work_units(admitted.job.id)[0].source_object_key,
                source.object_key,
            )


def _smoke_context():
    temp_dir = TemporaryDirectory()
    store = SQLiteTranslationJobStore(Path(temp_dir.name) / "jobs.sqlite3")
    storage = LocalObjectStorage(Path(temp_dir.name) / "objects")

    class _Context:
        def __enter__(self):
            return store, storage

        def __exit__(self, *args):
            store.close()
            temp_dir.cleanup()

    return _Context()


def _approval(store: SQLiteTranslationJobStore):
    payload = b"owner-local-approved-snapshot"
    return store.create_glossary_approval(
        snapshot_payload=payload,
        snapshot_digest=sha256(payload).hexdigest(),
        snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
        approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
    )


def _put_docx(storage: LocalObjectStorage):
    return storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="owner-local-source.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=b"owner-local-strict-docx-source",
    )


def _seal(
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    approval_id: str,
    source_object_key: str,
):
    return seal_strict_docx_v3_authorization(
        StrictDocxV3AuthorizationServiceRequest(
            store=store,
            storage=storage,
            approval_id=approval_id,
            source_object_key=source_object_key,
        )
    )


def _admission_request(authorization_id: str, source) -> StrictDocxV3AdmissionRequest:
    return StrictDocxV3AdmissionRequest(
        authorization_id=authorization_id,
        order_id="owner-local-order",
        user_id="owner-local-user",
        file_id="owner-local-source.docx",
        file_name="owner-local-source.docx",
        document_kind="docx",
        source_object_key=source.object_key,
        source_sha256=source.sha256,
        source_size_bytes=source.size_bytes,
        source_language="en",
        target_language="uk",
        adapter_version="docx-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        translation_policy=None,
        work_units=[
            WorkUnitPlan(
                sequence=1,
                source_block_ids=("docx:1",),
                source_text_hash="owner-local-source-hash",
                prompt_tier="plain",
                source_language="en",
                target_language="uk",
                source_object_key=source.object_key,
            )
        ],
    )


def _source_path(storage: LocalObjectStorage, object_key: str) -> Path:
    return storage._path_for_key(object_key)


def _authorization_count(store: SQLiteTranslationJobStore) -> int:
    return store._connection.execute(
        "SELECT COUNT(*) FROM strict_docx_v3_authorizations"
    ).fetchone()[0]


def _job_count(store: SQLiteTranslationJobStore) -> int:
    return store._connection.execute(
        "SELECT COUNT(*) FROM translation_jobs"
    ).fetchone()[0]


def _binding_count(store: SQLiteTranslationJobStore) -> int:
    return store._connection.execute(
        "SELECT COUNT(*) FROM strict_job_glossary_bindings"
    ).fetchone()[0]


def _job_authorization_count(store: SQLiteTranslationJobStore) -> int:
    return store._connection.execute(
        "SELECT COUNT(*) FROM strict_docx_v3_job_authorizations"
    ).fetchone()[0]


if __name__ == "__main__":
    unittest.main()
