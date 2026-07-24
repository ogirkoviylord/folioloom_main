"""Run a local, provider-free smoke for strict DOCX admission authority.

This is an owner-development harness, not a public/HTTP/Telegram entrypoint.
It creates temporary SQLite and object-storage state, never submits provider work,
and emits metadata only.
"""

from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from zipfile import ZipFile

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_job_store import PersistentJobStore
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    SQLiteTranslationJobStore,
)
from translator_service.persistent_planner import (
    StrictAdmissionDenied,
    StrictPersistentJobPlan,
)
from translator_service.strict_docx_admission_service import (
    StrictDocxAdmissionServiceRequest,
    admit_strict_docx_service_request,
)


def run_smoke() -> dict[str, object]:
    """Admit a synthetic strict DOCX, revoke its approval, and verify denial."""
    with TemporaryDirectory(prefix="folioloom-strict-docx-smoke-") as temp_dir:
        root = Path(temp_dir)
        store = SQLiteTranslationJobStore(root / "jobs.sqlite3")
        try:
            storage = LocalObjectStorage(root / "objects")
            source = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="strict-smoke.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                content=_synthetic_docx(),
            )
            payload = b"strict-docx-owner-smoke-snapshot-v1"
            approval = store.create_glossary_approval(
                snapshot_payload=payload,
                snapshot_digest=sha256(payload).hexdigest(),
                snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
                approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
            )
            request = StrictDocxAdmissionServiceRequest(
                store=cast(PersistentJobStore, store),
                storage=storage,
                approval_id=approval.approval_id,
                source_object_key=source.object_key,
                order_id="owner-smoke-order",
                user_id="owner-smoke-user",
                file_name="strict-smoke.docx",
                source_language="en",
                target_language="uk",
                max_fragment_chars=1_000,
            )
            admitted = admit_strict_docx_service_request(request)
            if not isinstance(admitted, StrictPersistentJobPlan):
                raise RuntimeError(
                    f"strict admission unexpectedly denied: {admitted.code}"
                )
            store.revoke_glossary_approval(approval_id=approval.approval_id)
            denied = admit_strict_docx_service_request(request)
            if not isinstance(denied, StrictAdmissionDenied):
                raise RuntimeError(
                    "revoked approval unexpectedly admitted a strict job"
                )
            return {
                "backend": "sqlite-temporary",
                "provider_calls": 0,
                "approval": {
                    "approval_id": approval.approval_id,
                    "custody_id": approval.custody_id,
                    "snapshot_digest_prefix": approval.snapshot_digest[:12],
                },
                "admission": {
                    "admitted": True,
                    "job_id": admitted.job.id,
                    "work_unit_count": len(admitted.work_units),
                },
                "after_revocation": {
                    "admitted": False,
                    "denial_code": denied.code,
                },
            }
        finally:
            store.close()


def _synthetic_docx() -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Synthetic strict source.</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        )
    return archive.getvalue()


def main() -> int:
    print(json.dumps(run_smoke(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
