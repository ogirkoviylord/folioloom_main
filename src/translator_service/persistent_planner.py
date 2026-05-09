from dataclasses import dataclass
from hashlib import sha256
import json

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import (
    DOCX_ADAPTER_VERSION,
    EPUB_ADAPTER_VERSION,
    TXT_ADAPTER_VERSION,
    FormatTranslationUnit,
    plan_docx_translation,
    plan_epub_translation,
    plan_txt_translation,
)
from translator_service.persistent_jobs import (
    PersistentTranslationJob,
    PersistentWorkUnit,
    SQLiteTranslationJobStore,
    WorkUnitPlan,
)
from translator_service.translation_policy import (
    build_translation_policy,
    translation_policy_signature,
)
from translator_service.translation_context import (
    build_initial_translation_context_memory,
    translation_context_to_payload,
)


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
    adapter_version: str = TXT_ADAPTER_VERSION,
    prompt_version: str = "plain-v1",
    pricing_snapshot_id: str = "prototype-pricing-v1",
    rights_confirmation: dict | None = None,
) -> PersistentJobPlan:
    content = storage.get_bytes(source_object_key)
    adapter_plan = plan_txt_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
        adapter_version=adapter_version,
    )
    if not adapter_plan.units:
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
        translation_policy=_translation_policy_snapshot(
            units=adapter_plan.units,
            source_language=source_language,
            target_language=target_language,
            rights_confirmation=rights_confirmation,
        ),
    )
    plans = [
        _stored_text_work_unit_plan(
            storage=storage,
            job_id=job.id,
            file_extension="txt",
            sequence=unit.sequence,
            source_block_ids=unit.source_block_ids,
            source_text=unit.source_text,
            prompt_tier=unit.prompt_tier.value,
            source_language=source_language,
            target_language=target_language,
        )
        for unit in adapter_plan.units
    ]
    return PersistentJobPlan(
        job=job,
        work_units=store.add_work_units(job.id, plans),
    )


def create_persistent_docx_job_plan(
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
    adapter_version: str = DOCX_ADAPTER_VERSION,
    prompt_version: str = "plain-v1",
    pricing_snapshot_id: str = "prototype-pricing-v1",
    rights_confirmation: dict | None = None,
) -> PersistentJobPlan:
    content = storage.get_bytes(source_object_key)
    adapter_plan = plan_docx_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
        adapter_version=adapter_version,
    )
    if not adapter_plan.units:
        raise ValueError("DOCX document does not contain translatable text")

    job = store.create_job(
        order_id=order_id,
        user_id=user_id,
        file_id=source_object_key,
        file_name=file_name,
        document_kind="docx",
        source_language=source_language,
        target_language=target_language,
        adapter_version=adapter_version,
        prompt_version=prompt_version,
        pricing_snapshot_id=pricing_snapshot_id,
        source_object_key=source_object_key,
        translation_policy=_translation_policy_snapshot(
            units=adapter_plan.units,
            source_language=source_language,
            target_language=target_language,
            rights_confirmation=rights_confirmation,
        ),
    )
    plans = [
        _stored_adapter_work_unit_plan(
            storage=storage,
            job_id=job.id,
            file_extension="txt",
            unit=unit,
            source_language=source_language,
            target_language=target_language,
        )
        for unit in adapter_plan.units
    ]
    return PersistentJobPlan(
        job=job,
        work_units=store.add_work_units(job.id, plans),
    )


def create_persistent_epub_job_plan(
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
    adapter_version: str = EPUB_ADAPTER_VERSION,
    prompt_version: str = "plain-v1",
    pricing_snapshot_id: str = "prototype-pricing-v1",
    rights_confirmation: dict | None = None,
) -> PersistentJobPlan:
    content = storage.get_bytes(source_object_key)
    adapter_plan = plan_epub_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
        adapter_version=adapter_version,
    )
    if not adapter_plan.units:
        raise ValueError("EPUB document does not contain translatable text")

    job = store.create_job(
        order_id=order_id,
        user_id=user_id,
        file_id=source_object_key,
        file_name=file_name,
        document_kind="epub",
        source_language=source_language,
        target_language=target_language,
        adapter_version=adapter_version,
        prompt_version=prompt_version,
        pricing_snapshot_id=pricing_snapshot_id,
        source_object_key=source_object_key,
        translation_policy=_translation_policy_snapshot(
            units=adapter_plan.units,
            source_language=source_language,
            target_language=target_language,
            rights_confirmation=rights_confirmation,
        ),
    )
    plans = [
        _stored_adapter_work_unit_plan(
            storage=storage,
            job_id=job.id,
            file_extension="txt",
            unit=unit,
            source_language=source_language,
            target_language=target_language,
        )
        for unit in adapter_plan.units
    ]
    return PersistentJobPlan(
        job=job,
        work_units=store.add_work_units(job.id, plans),
    )


def _stored_adapter_work_unit_plan(
    *,
    storage: LocalObjectStorage,
    job_id: str,
    file_extension: str,
    unit: FormatTranslationUnit,
    source_language: str,
    target_language: str,
) -> WorkUnitPlan:
    return _stored_text_work_unit_plan(
        storage=storage,
        job_id=job_id,
        file_extension=file_extension,
        sequence=unit.sequence,
        source_block_ids=unit.source_block_ids,
        source_text=unit.source_text,
        prompt_tier=unit.prompt_tier.value,
        source_language=source_language,
        target_language=target_language,
    )


def _translation_policy_snapshot(
    *,
    units: list[FormatTranslationUnit],
    source_language: str,
    target_language: str,
    rights_confirmation: dict | None = None,
) -> str:
    source_text = "\n\n".join(unit.source_text for unit in units if unit.source_text)
    translation_context = build_initial_translation_context_memory(
        source_text,
        target_language=target_language,
    )
    policy = build_translation_policy(
        text=source_text,
        source_language=source_language,
        target_language=target_language,
        translation_context=translation_context,
    )
    snapshot = json.loads(translation_policy_signature(policy))
    snapshot["translation_context_memory"] = translation_context_to_payload(
        translation_context
    )
    if rights_confirmation is not None:
        snapshot["rights_confirmation"] = rights_confirmation
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)


def _stored_text_work_unit_plan(
    *,
    storage: LocalObjectStorage,
    job_id: str,
    file_extension: str,
    sequence: int,
    source_block_ids: tuple[str, ...],
    source_text: str,
    prompt_tier: str,
    source_language: str,
    target_language: str,
) -> WorkUnitPlan:
    stored = storage.put_bytes(
        kind=StoredFileKind.INTERMEDIATE,
        file_name=f"{job_id}-unit-{sequence}.{file_extension}",
        content_type="text/plain; charset=utf-8",
        content=source_text.encode("utf-8"),
    )
    return WorkUnitPlan(
        sequence=sequence,
        source_block_ids=source_block_ids,
        source_text_hash=sha256(source_text.encode("utf-8")).hexdigest(),
        prompt_tier=prompt_tier,
        source_language=source_language,
        target_language=target_language,
        source_object_key=stored.object_key,
    )
