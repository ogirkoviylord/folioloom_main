import hashlib
import unittest
from collections.abc import Callable
from dataclasses import dataclass

from translator_service.persistent_job_store import admit_strict_docx_job
from translator_service.persistent_jobs import (
    GLOSSARY_APPROVAL_SCHEMA_VERSION,
    GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
    StrictDocxAdmissionRequest,
    WorkUnitPlan,
)
from translator_service.scheduler import SchedulerLimits


@dataclass(frozen=True)
class StrictDocxStoreFactory:
    name: str
    create: Callable[[], SQLiteTranslationJobStore]


@dataclass(frozen=True)
class StrictDocxContractCase:
    name: str
    run: Callable[[unittest.TestCase, SQLiteTranslationJobStore], None]


class StrictDocxJobStoreContractTest(unittest.TestCase):
    def test_unsupported_backend_returns_typed_no_write_denial(self):
        store = _LegacyStore()

        result = admit_strict_docx_job(store, _request("approval-1"))

        self.assertFalse(result.admitted)
        self.assertEqual(result.denial_code, "strict_docx_unsupported_backend")
        self.assertEqual(store.create_job_calls, 0)

    def test_sqlite_selected_contract_cases(self):
        factory = StrictDocxStoreFactory(
            name="sqlite",
            create=lambda: SQLiteTranslationJobStore(":memory:"),
        )
        cases = (
            StrictDocxContractCase(
                "valid_ordered_immutable_binding", _assert_valid_admission
            ),
            StrictDocxContractCase(
                "exact_match_reuse_after_completion", _assert_reuse
            ),
            StrictDocxContractCase(
                "revocation_denies_future_claims", _assert_revoked_claims
            ),
            StrictDocxContractCase(
                "claimed_work_completes_after_revocation",
                _assert_claimed_completion,
            ),
            StrictDocxContractCase("legacy_docx_remains_unbound", _assert_legacy_docx),
        )

        for case in cases:
            with self.subTest(backend=factory.name, case=case.name):
                store = factory.create()
                self.addCleanup(store.close)
                case.run(self, store)


class _LegacyStore:
    def __init__(self) -> None:
        self.create_job_calls = 0

    def create_job(self, **kwargs):
        self.create_job_calls += 1
        raise AssertionError("strict admission must not use legacy create_job")


def _assert_valid_admission(
    test: unittest.TestCase, store: SQLiteTranslationJobStore
) -> None:
    approval = _approval(store)

    result = admit_strict_docx_job(store, _request(approval.approval_id, unit_count=2))

    test.assertTrue(result.admitted)
    test.assertEqual([unit.sequence for unit in result.work_units], [1, 2])
    binding = store._connection.execute(
        "SELECT approval_id, custody_id, snapshot_digest "
        "FROM strict_job_glossary_bindings"
    ).fetchone()
    test.assertEqual(
        tuple(binding),
        (approval.approval_id, approval.custody_id, approval.snapshot_digest),
    )


def _assert_reuse(test: unittest.TestCase, store: SQLiteTranslationJobStore) -> None:
    approval = _approval(store)
    first = admit_strict_docx_job(store, _request(approval.approval_id))
    second = admit_strict_docx_job(store, _request(approval.approval_id))
    test.assertIsNotNone(first.job)
    test.assertIsNotNone(second.job)
    if first.job is None:
        raise AssertionError("first strict admission unexpectedly denied")
    test.assertNotEqual(first.job.id, second.job.id)

    claimed = store.claim_next_scheduled_work_unit(
        worker_id="worker-a",
        lease_seconds=60,
        limits=SchedulerLimits(),
    )
    if claimed is None:
        raise AssertionError("strict work unit unexpectedly not claimed")
    store.complete_claimed_work_unit(
        work_unit_id=claimed.work_unit_id,
        claim_token=claimed.claim_token,
        translated_text="done",
        prompt_tokens=1,
        completion_tokens=1,
        cache_hit_tokens=0,
        cache_miss_tokens=0,
    )
    third = admit_strict_docx_job(store, _request(approval.approval_id))

    test.assertIsNotNone(third.job)
    test.assertEqual(
        store._connection.execute(
            "SELECT COUNT(*) FROM strict_job_glossary_bindings WHERE approval_id = ?",
            (approval.approval_id,),
        ).fetchone()[0],
        3,
    )


def _assert_revoked_claims(
    test: unittest.TestCase, store: SQLiteTranslationJobStore
) -> None:
    for claim_path in ("direct", "scheduled"):
        with test.subTest(claim_path=claim_path):
            approval = _approval(store, payload=f"contract-{claim_path}".encode())
            admitted = admit_strict_docx_job(store, _request(approval.approval_id))
            test.assertIsNotNone(admitted.job)
            if admitted.job is None:
                raise AssertionError("strict admission unexpectedly denied")
            store.revoke_glossary_approval(approval_id=approval.approval_id)
            before = _claim_snapshot(store, admitted.job.id)

            if claim_path == "direct":
                claimed = store.claim_next_work_unit(
                    admitted.job.id, worker_id="worker-a"
                )
            else:
                claimed = store.claim_next_scheduled_work_unit(
                    worker_id="worker-a",
                    lease_seconds=60,
                    limits=SchedulerLimits(),
                )

            test.assertIsNone(claimed)
            test.assertEqual(_claim_snapshot(store, admitted.job.id), before)


def _assert_claimed_completion(
    test: unittest.TestCase, store: SQLiteTranslationJobStore
) -> None:
    approval = _approval(store)
    admitted = admit_strict_docx_job(store, _request(approval.approval_id))
    test.assertIsNotNone(admitted.job)
    if admitted.job is None:
        raise AssertionError("strict admission unexpectedly denied")
    claimed = store.claim_next_scheduled_work_unit(
        worker_id="worker-a",
        lease_seconds=60,
        limits=SchedulerLimits(),
    )
    if claimed is None:
        raise AssertionError("strict work unit unexpectedly not claimed")
    store.revoke_glossary_approval(approval_id=approval.approval_id)

    completed = store.complete_claimed_work_unit(
        work_unit_id=claimed.work_unit_id,
        claim_token=claimed.claim_token,
        translated_text="done",
        prompt_tokens=1,
        completion_tokens=1,
        cache_hit_tokens=0,
        cache_miss_tokens=0,
    )

    test.assertEqual(completed.status, PersistentWorkUnitStatus.TRANSLATED)
    test.assertEqual(completed.translated_text, "done")


def _assert_legacy_docx(
    test: unittest.TestCase, store: SQLiteTranslationJobStore
) -> None:
    job = store.create_job(
        order_id="legacy-order",
        user_id="legacy-user",
        file_id="legacy.docx",
        file_name="legacy.docx",
        document_kind="docx",
        source_language="en",
        target_language="uk",
        adapter_version="docx-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        source_object_key="original/legacy.docx",
        translation_policy='{"with_glossary": true}',
    )
    store.add_work_units(job.id, _work_units("original/legacy.docx", 1))

    claimed = store.claim_next_work_unit(job.id, worker_id="worker-a")
    binding_count = store._connection.execute(
        "SELECT COUNT(*) FROM strict_job_glossary_bindings WHERE job_id = ?", (job.id,)
    ).fetchone()[0]

    test.assertIsNotNone(claimed)
    test.assertEqual(binding_count, 0)


def _approval(
    store: SQLiteTranslationJobStore,
    *,
    payload: bytes = b"contract-snapshot",
):
    return store.create_glossary_approval(
        snapshot_payload=payload,
        snapshot_digest=hashlib.sha256(payload).hexdigest(),
        snapshot_schema_version=GLOSSARY_SNAPSHOT_SCHEMA_VERSION,
        approval_schema_version=GLOSSARY_APPROVAL_SCHEMA_VERSION,
    )


def _request(approval_id: str, *, unit_count: int = 1) -> StrictDocxAdmissionRequest:
    return StrictDocxAdmissionRequest(
        approval_id=approval_id,
        order_id="strict-order",
        user_id="strict-user",
        file_id="strict.docx",
        file_name="strict.docx",
        document_kind="docx",
        source_object_key="original/strict.docx",
        source_language="en",
        target_language="uk",
        adapter_version="docx-v1",
        prompt_version="plain-v1",
        pricing_snapshot_id="pricing-1",
        translation_policy=None,
        work_units=_work_units("original/strict.docx", unit_count),
    )


def _work_units(source_object_key: str, count: int) -> list[WorkUnitPlan]:
    return [
        WorkUnitPlan(
            sequence=sequence,
            source_block_ids=(f"docx:{sequence}",),
            source_text_hash=f"hash-{sequence}",
            prompt_tier="plain",
            source_language="en",
            target_language="uk",
            source_object_key=source_object_key,
        )
        for sequence in range(1, count + 1)
    ]


def _claim_snapshot(store: SQLiteTranslationJobStore, job_id: str) -> tuple:
    job = store.get_job(job_id)
    if job is None:
        raise AssertionError(f"expected job is missing: {job_id}")
    units = store.list_work_units(job_id)
    return job.status, tuple(
        (unit.status, unit.attempt_count, unit.claim_token) for unit in units
    )


if __name__ == "__main__":
    unittest.main()
