import json
import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    SQLiteTranslationJobStore,
)
from translator_service.strict_docx_v3_authorization_service import (
    StrictDocxV3AuthorizationDenied,
    StrictDocxV3AuthorizationServiceRequest,
    seal_strict_docx_v3_authorization,
)


class StrictDocxV3AuthorizationServiceTest(unittest.TestCase):
    def test_seals_explicit_v3_authorization_from_server_resolved_original_bytes(self):
        with _service_context() as (store, storage):
            source = _put_docx(storage)
            approval = _approval(store)

            result = seal_strict_docx_v3_authorization(
                StrictDocxV3AuthorizationServiceRequest(
                    store=store,
                    storage=storage,
                    approval_id=approval.approval_id,
                    source_object_key=source.object_key,
                )
            )

            self.assertNotIsInstance(result, StrictDocxV3AuthorizationDenied)
            self.assertEqual(result.source_object_key, source.object_key)
            self.assertEqual(result.source_sha256, sha256(_DOCX_BYTES).hexdigest())
            self.assertEqual(result.source_size_bytes, len(_DOCX_BYTES))
            self.assertEqual(result.document_kind, "docx")

    def test_denies_missing_storage_without_authorization_write(self):
        with _service_context() as (store, storage):
            approval = _approval(store)

            result = seal_strict_docx_v3_authorization(
                StrictDocxV3AuthorizationServiceRequest(
                    store=store,
                    storage=storage,
                    approval_id=approval.approval_id,
                    source_object_key="original/missing.docx",
                )
            )

            self.assertEqual(
                result,
                StrictDocxV3AuthorizationDenied(code="strict_docx_v3_source_missing"),
            )
            self.assertEqual(_authorization_count(store), 0)

    def test_denies_metadata_kind_size_or_digest_mismatch_without_write(self):
        cases = ("metadata", "kind", "size", "digest")

        for mismatch in cases:
            with (
                self.subTest(mismatch=mismatch),
                _service_context() as (store, storage),
            ):
                source = _put_docx(storage)
                approval = _approval(store)
                _tamper_metadata(storage, source.object_key, mismatch)

                result = seal_strict_docx_v3_authorization(
                    StrictDocxV3AuthorizationServiceRequest(
                        store=store,
                        storage=storage,
                        approval_id=approval.approval_id,
                        source_object_key=source.object_key,
                    )
                )

                self.assertEqual(
                    result,
                    StrictDocxV3AuthorizationDenied(
                        code=f"strict_docx_v3_source_{mismatch}_mismatch"
                    ),
                )
                self.assertEqual(_authorization_count(store), 0)

    def test_denies_changed_bytes_without_authorization_write(self):
        with _service_context() as (store, storage):
            source = _put_docx(storage)
            approval = _approval(store)
            _source_path(storage, source.object_key).write_bytes(
                b"alterd docx source bytes"
            )

            result = seal_strict_docx_v3_authorization(
                StrictDocxV3AuthorizationServiceRequest(
                    store=store,
                    storage=storage,
                    approval_id=approval.approval_id,
                    source_object_key=source.object_key,
                )
            )

            self.assertEqual(
                result,
                StrictDocxV3AuthorizationDenied(
                    code="strict_docx_v3_source_digest_mismatch"
                ),
            )
            self.assertEqual(_authorization_count(store), 0)

    def test_denies_missing_or_revoked_snapshot_approval_without_writing(self):
        for authority in ("missing", "revoked"):
            with (
                self.subTest(authority=authority),
                _service_context() as (store, storage),
            ):
                source = _put_docx(storage)
                approval = _approval(store)
                approval_id = approval.approval_id
                if authority == "missing":
                    approval_id = "missing-snapshot-approval"
                else:
                    store.revoke_glossary_approval(approval_id=approval_id)

                result = seal_strict_docx_v3_authorization(
                    StrictDocxV3AuthorizationServiceRequest(
                        store=store,
                        storage=storage,
                        approval_id=approval_id,
                        source_object_key=source.object_key,
                    )
                )

                self.assertEqual(
                    result,
                    StrictDocxV3AuthorizationDenied(
                        code="strict_docx_v3_source_approval_unavailable"
                    ),
                )
                self.assertEqual(_authorization_count(store), 0)


def _service_context():
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
    payload = b"approved glossary snapshot"
    return store.create_glossary_approval(
        snapshot_payload=payload,
        snapshot_digest=sha256(payload).hexdigest(),
        snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
        approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
    )


def _put_docx(storage: LocalObjectStorage):
    return storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="source.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=_DOCX_BYTES,
    )


def _tamper_metadata(
    storage: LocalObjectStorage,
    object_key: str,
    mismatch: str,
) -> None:
    metadata_path = _source_path(storage, f"{object_key}.metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if mismatch == "metadata":
        metadata["object_key"] = "original/different.docx"
    elif mismatch == "kind":
        metadata["kind"] = StoredFileKind.QUARANTINE.value
    elif mismatch == "size":
        metadata["size_bytes"] += 1
    else:
        metadata["sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")


def _source_path(storage: LocalObjectStorage, object_key: str) -> Path:
    return storage._path_for_key(object_key)


def _authorization_count(store: SQLiteTranslationJobStore) -> int:
    return store._connection.execute(
        "SELECT COUNT(*) FROM strict_docx_v3_authorizations"
    ).fetchone()[0]


_DOCX_BYTES = b"strict docx source bytes"


if __name__ == "__main__":
    unittest.main()
