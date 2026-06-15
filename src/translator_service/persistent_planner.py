import json
from dataclasses import dataclass
from hashlib import sha256

from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.format_adapters import (
    DOCX_ADAPTER_VERSION,
    DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE,
    EPUB_ADAPTER_VERSION,
    TRANSLATION_MODE_BOOK_MANUSCRIPT,
    TXT_ADAPTER_VERSION,
    FormatTranslationUnit,
    docx_translation_mode_profile_signature,
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
from translator_service.translation_context import (
    TranslationContextMemory,
    build_initial_translation_context_memory,
    translation_context_to_payload,
)
from translator_service.translation_policy import (
    build_translation_policy,
    translation_policy_signature,
)

BOOK_MANUSCRIPT_TRANSLATION_MODE_PROFILE = "book-manuscript-v1"
BOOK_MANUSCRIPT_STYLE_SUMMARY = (
    "Book/manuscript mode: preserve chapter, scene, paragraph, dialogue, "
    "narrator, speaker, and character continuity; allow natural prose flow "
    "where the source is narrative while keeping structured, technical, table, "
    "code, protected-marker, and output-contract content conservative and exact."
)


@dataclass(frozen=True)
class PersistentJobPlan:
    job: PersistentTranslationJob
    work_units: list[PersistentWorkUnit]
    estimated_input_tokens: int


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
    translation_mode: str | None = None,
    glossary_mode: str | None = None,
    prepared_glossary_package: dict | None = None,
    upload_safety_id: str | None = None,
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
            translation_mode=translation_mode,
            glossary_mode=glossary_mode,
            prepared_glossary_package=prepared_glossary_package,
            translation_mode_profile=_translation_mode_profile_for_document_kind(
                translation_mode,
                document_kind="txt",
            ),
            upload_safety_id=upload_safety_id,
            accepted_source_object_key=source_object_key,
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
        estimated_input_tokens=adapter_plan.estimated_input_tokens,
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
    translation_mode: str | None = None,
    glossary_mode: str | None = None,
    prepared_glossary_package: dict | None = None,
    upload_safety_id: str | None = None,
) -> PersistentJobPlan:
    content = storage.get_bytes(source_object_key)
    adapter_plan = plan_docx_translation(
        content=content,
        max_fragment_chars=max_fragment_chars,
        adapter_version=adapter_version,
        translation_mode=translation_mode,
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
            translation_mode=translation_mode,
            glossary_mode=glossary_mode,
            prepared_glossary_package=prepared_glossary_package,
            translation_mode_profile=_translation_mode_profile_for_document_kind(
                translation_mode,
                document_kind="docx",
            ),
            upload_safety_id=upload_safety_id,
            accepted_source_object_key=source_object_key,
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
        estimated_input_tokens=adapter_plan.estimated_input_tokens,
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
    translation_mode: str | None = None,
    glossary_mode: str | None = None,
    prepared_glossary_package: dict | None = None,
    upload_safety_id: str | None = None,
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
            translation_mode=translation_mode,
            glossary_mode=glossary_mode,
            prepared_glossary_package=prepared_glossary_package,
            translation_mode_profile=_translation_mode_profile_for_document_kind(
                translation_mode,
                document_kind="epub",
            ),
            upload_safety_id=upload_safety_id,
            accepted_source_object_key=source_object_key,
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
        estimated_input_tokens=adapter_plan.estimated_input_tokens,
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
    translation_mode: str | None = None,
    glossary_mode: str | None = None,
    prepared_glossary_package: dict | None = None,
    translation_mode_profile: "_TranslationModeProfile | None" = None,
    upload_safety_id: str | None = None,
    accepted_source_object_key: str | None = None,
) -> str:
    source_text = "\n\n".join(unit.source_text for unit in units if unit.source_text)
    translation_context = build_initial_translation_context_memory(
        source_text,
        target_language=target_language,
    )
    if translation_mode_profile is not None:
        translation_context = _translation_context_with_mode_profile(
            translation_context,
            translation_mode_profile,
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
    if translation_mode is not None:
        snapshot["translation_mode"] = translation_mode
    if glossary_mode is not None:
        snapshot["glossary_mode"] = glossary_mode
    if prepared_glossary_package is not None:
        snapshot["prepared_glossary_package"] = prepared_glossary_package
    if translation_mode_profile is not None:
        snapshot["translation_mode_profile"] = translation_mode_profile.signature
    if upload_safety_id is not None:
        snapshot["upload_safety"] = {
            "accepted_source_object_key": accepted_source_object_key,
            "source_gate": "upload_safety_ledger",
            "upload_safety_id": upload_safety_id,
        }
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class _TranslationModeProfile:
    signature: str
    style_summary: str


def _translation_mode_profile_for_document_kind(
    translation_mode: str | None,
    *,
    document_kind: str,
) -> _TranslationModeProfile | None:
    normalized_mode = translation_mode.strip().lower() if translation_mode else None
    if normalized_mode == TRANSLATION_MODE_BOOK_MANUSCRIPT:
        return _TranslationModeProfile(
            signature=BOOK_MANUSCRIPT_TRANSLATION_MODE_PROFILE,
            style_summary=BOOK_MANUSCRIPT_STYLE_SUMMARY,
        )
    if document_kind.strip().lower() == "docx":
        return _docx_translation_mode_profile(translation_mode)
    return None


def _docx_translation_mode_profile(
    translation_mode: str | None,
) -> _TranslationModeProfile | None:
    signature = docx_translation_mode_profile_signature(translation_mode)
    if signature == DOCX_TRANSLATION_MODE_DOCUMENT_FORM_PROFILE:
        return _TranslationModeProfile(
            signature=signature,
            style_summary=(
                "DOCX document/form mode: preserve structure, labels, tables, "
                "addresses, dates, numbers, signatures, and non-translatable "
                "fields; use conservative wording and avoid prose-style "
                "paraphrase."
            ),
        )
    return None


def _translation_context_with_mode_profile(
    translation_context: TranslationContextMemory | None,
    profile: _TranslationModeProfile,
) -> TranslationContextMemory:
    if translation_context is None:
        return TranslationContextMemory(style_summary=profile.style_summary)
    style_summary = translation_context.style_summary
    if profile.style_summary not in style_summary:
        style_summary = (
            f"{style_summary} {profile.style_summary}".strip()
            if style_summary
            else profile.style_summary
        )
    return TranslationContextMemory(
        style_summary=style_summary,
        term_choices=translation_context.term_choices,
        entity_choices=translation_context.entity_choices,
        recent_quality_issues=translation_context.recent_quality_issues,
    )


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
