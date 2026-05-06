from dataclasses import dataclass
from hashlib import sha256

from translator_service.extractors import extract_text_from_txt
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_jobs import (
    PersistentTranslationJob,
    PersistentWorkUnit,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)
from translator_service.text_analysis import split_text_into_fragments


@dataclass(frozen=True)
class PersistentJobPlan:
    job: PersistentTranslationJob
    work_units: list[PersistentWorkUnit]


def create_persistent_txt_job_plan(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    order_id: str,
    user_id: str,
    source_object_key: str,
    file_name: str,
    source_language: str,
    target_language: str,
    max_fragment_chars: int,
    adapter_version: str = "txt-v1",
    prompt_version: str = "plain-v1",
    pricing_snapshot_id: str = "prototype-pricing-v1",
) -> PersistentJobPlan:
    content = storage.get_bytes(source_object_key)
    text = extract_text_from_txt(content)
    fragments = split_text_into_fragments(
        text,
        max_fragment_chars=max_fragment_chars,
    )
    if not fragments:
        raise ValueError("TXT document does not contain translatable text")

    job = store.create_job(
        order_id=order_id,
        user_id=user_id,
        file_id=source_object_key,
        file_name=file_name,
        document_kind="txt",
        source_language=source_language,
        target_language=target_language,
        adapter_version=adapter_version,
        prompt_version=prompt_version,
        pricing_snapshot_id=pricing_snapshot_id,
        source_object_key=source_object_key,
    )
    plans = [
        _stored_txt_work_unit_plan(
            storage=storage,
            job_id=job.id,
            sequence=sequence,
            fragment=fragment,
            source_language=source_language,
            target_language=target_language,
        )
        for sequence, fragment in enumerate(fragments, start=1)
    ]
    return PersistentJobPlan(
        job=job,
        work_units=store.add_work_units(job.id, plans),
    )


def _stored_txt_work_unit_plan(
    *,
    storage: LocalObjectStorage,
    job_id: str,
    sequence: int,
    fragment: str,
    source_language: str,
    target_language: str,
) -> WorkUnitPlan:
    stored = storage.put_bytes(
        kind=StoredFileKind.INTERMEDIATE,
        file_name=f"{job_id}-unit-{sequence}.txt",
        content_type="text/plain; charset=utf-8",
        content=fragment.encode("utf-8"),
    )
    return WorkUnitPlan(
        sequence=sequence,
        source_block_ids=(f"txt:{sequence}",),
        source_text_hash=sha256(fragment.encode("utf-8")).hexdigest(),
        prompt_tier="plain",
        source_language=source_language,
        target_language=target_language,
        source_object_key=stored.object_key,
    )
