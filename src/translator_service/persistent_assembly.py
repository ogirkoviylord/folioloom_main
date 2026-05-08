import logging
from collections.abc import Sequence
from xml.etree import ElementTree

from translator_service.documents import DocumentFormat
from translator_service.document_sandbox import SandboxTranslationUnit
from translator_service.file_storage import LocalObjectStorage, StoredFile, StoredFileKind
from translator_service.format_adapters.txt_layout import (
    assemble_txt_document,
    parse_txt_document,
)
from translator_service.format_adapters.txt import TXT_ADAPTER_VERSION
from translator_service.format_adapters.epub import (
    assemble_epub_content_from_block_translations,
)
from translator_service.persistent_jobs import (
    PersistentWorkUnit,
    PersistentWorkUnitStatus,
    SQLiteTranslationJobStore,
)
from translator_service.translation_runner import (
    _extract_docx_blocks,
    _replace_docx_blocks,
)


_DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_EPUB_CONTENT_TYPE = "application/epub+zip"
_TXT_CONTENT_TYPE = "text/plain; charset=utf-8"
logger = logging.getLogger(__name__)


def assemble_persistent_txt_result(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    file_name: str,
    partial: bool,
) -> StoredFile:
    job = _require_job(store, job_id)
    if job.adapter_version != TXT_ADAPTER_VERSION:
        raise ValueError(
            "TXT adapter version mismatch: "
            f"job={job.adapter_version} current={TXT_ADAPTER_VERSION}"
        )
    source_content = storage.get_bytes(job.source_object_key)
    document = parse_txt_document(source_content)
    translated_by_segment_id = _translated_text_by_block_id(store.list_work_units(job_id))
    assembled_text = assemble_txt_document(
        document,
        translated_by_segment_id=translated_by_segment_id,
        translated_only=False,
    )
    return _store_assembled_result(
        store=store,
        storage=storage,
        job_id=job_id,
        file_name=file_name,
        content_type=_TXT_CONTENT_TYPE,
        content=assembled_text.encode("utf-8"),
        partial=partial,
    )


def assemble_persistent_docx_result(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    file_name: str,
    partial: bool,
    document_sandbox=None,
) -> StoredFile:
    job = _require_job(store, job_id)
    source_content = storage.get_bytes(job.source_object_key)
    translated_units = _translated_units_from_work_units(store.list_work_units(job_id))
    if document_sandbox is not None:
        content = document_sandbox.assemble_document(
            document_format=DocumentFormat.DOCX,
            content=source_content,
            translated_units=translated_units,
        )
    else:
        content = assemble_docx_content_from_translated_units(
            source_content=source_content,
            translated_units=translated_units,
        )
    return _store_assembled_result(
        store=store,
        storage=storage,
        job_id=job_id,
        file_name=file_name,
        content_type=_DOCX_CONTENT_TYPE,
        content=content,
        partial=partial,
    )


def assemble_persistent_epub_result(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    file_name: str,
    partial: bool,
    document_sandbox=None,
) -> StoredFile:
    job = _require_job(store, job_id)
    source_content = storage.get_bytes(job.source_object_key)
    translated_units = _translated_units_from_work_units(store.list_work_units(job_id))
    assembly_units = (
        _epub_body_translated_units(translated_units)
        if partial
        else translated_units
    )
    if document_sandbox is not None:
        content = document_sandbox.assemble_document(
            document_format=DocumentFormat.EPUB,
            content=source_content,
            translated_units=assembly_units,
        )
    else:
        content = assemble_epub_content_from_translated_units(
            source_content=source_content,
            translated_units=assembly_units,
            target_language=None if partial else job.target_language,
        )
    return _store_assembled_result(
        store=store,
        storage=storage,
        job_id=job_id,
        file_name=file_name,
        content_type=_EPUB_CONTENT_TYPE,
        content=content,
        partial=partial,
    )


def assemble_docx_content_from_translated_units(
    *,
    source_content: bytes,
    translated_units: Sequence[SandboxTranslationUnit],
) -> bytes:
    blocks = _extract_docx_blocks(source_content)
    translated_by_block_id = _translated_text_by_sandbox_block_id(translated_units)
    translated_blocks = [
        translated_by_block_id.get(_docx_block_id(block), block.text)
        for block in blocks
    ]
    return _replace_docx_blocks(source_content, blocks, translated_blocks)


def assemble_epub_content_from_translated_units(
    *,
    source_content: bytes,
    translated_units: Sequence[SandboxTranslationUnit],
    target_language: str | None = None,
) -> bytes:
    translated_by_block_id = _translated_text_by_sandbox_block_id(translated_units)
    return assemble_epub_content_from_block_translations(
        source_content=source_content,
        translated_by_block_id=translated_by_block_id,
        target_language=target_language,
    )


def count_unassembled_work_units(work_units: list[PersistentWorkUnit]) -> int:
    return sum(
        1
        for work_unit in work_units
        if _should_consider_work_unit_for_assembly(work_unit)
        and not _split_work_unit_translation(work_unit, log_malformed=False)
    )


def _translated_text_by_block_id(
    work_units: list[PersistentWorkUnit],
) -> dict[str, str]:
    return _translated_text_by_sandbox_block_id(
        _translated_units_from_work_units(work_units)
    )


def _translated_units_from_work_units(
    work_units: list[PersistentWorkUnit],
) -> list[SandboxTranslationUnit]:
    translated_units: list[SandboxTranslationUnit] = []
    for work_unit in work_units:
        if not _should_consider_work_unit_for_assembly(work_unit):
            continue
        for block_id, block_text in _split_work_unit_translation(work_unit):
            translated_units.append(
                SandboxTranslationUnit(
                    source_block_ids=(block_id,),
                    translated_text=block_text,
                )
            )
    return translated_units


def _translated_text_by_sandbox_block_id(
    translated_units: Sequence[SandboxTranslationUnit],
) -> dict[str, str]:
    translated: dict[str, str] = {}
    for unit in translated_units:
        block_ids = unit.source_block_ids
        translated_text = unit.translated_text
        if len(block_ids) == 1:
            translated[block_ids[0]] = translated_text
            continue

        split = _split_translation_unit_text(
            block_ids=block_ids,
            translated_text=translated_text,
        )
        for block_id, block_text in split:
            translated[block_id] = block_text
    return translated


def _epub_body_translated_units(
    translated_units: Sequence[SandboxTranslationUnit],
) -> list[SandboxTranslationUnit]:
    return [
        unit
        for unit in translated_units
        if not any(
            block_id.startswith("epub:aux:")
            for block_id in unit.source_block_ids
        )
    ]


def _split_translation_unit_text(
    *,
    block_ids: tuple[str, ...],
    translated_text: str,
) -> list[tuple[str, str]]:
    batch_parts = _parse_lenient_translation_batch(
        translated_text,
        expected_count=len(block_ids),
    )
    if batch_parts is not None:
        return list(zip(block_ids, batch_parts, strict=True))

    parts = [part.strip() for part in translated_text.split("\n\n")]
    if len(parts) != len(block_ids):
        logger.warning(
            "Skipping malformed sandbox translation unit during assembly: "
            "translated_parts=%s source_blocks=%s",
            len(parts),
            len(block_ids),
        )
        return []
    return list(zip(block_ids, parts, strict=True))


def _should_consider_work_unit_for_assembly(work_unit: PersistentWorkUnit) -> bool:
    return (
        work_unit.status
        in {
            PersistentWorkUnitStatus.TRANSLATED,
            PersistentWorkUnitStatus.CACHED,
        }
        and bool(work_unit.translated_text)
    )


def _split_work_unit_translation(
    work_unit: PersistentWorkUnit,
    *,
    log_malformed: bool = True,
) -> list[tuple[str, str]]:
    block_ids = work_unit.source_block_ids
    translated_text = work_unit.translated_text or ""
    if len(block_ids) == 1:
        return [(block_ids[0], translated_text)]

    batch_parts = _parse_lenient_translation_batch(
        translated_text,
        expected_count=len(block_ids),
    )
    if batch_parts is not None:
        return list(zip(block_ids, batch_parts, strict=True))

    parts = [part.strip() for part in translated_text.split("\n\n")]
    if len(parts) != len(block_ids):
        if log_malformed:
            logger.warning(
                "Skipping malformed persistent work unit during assembly: "
                "work_unit_id=%s translated_parts=%s source_blocks=%s",
                work_unit.id,
                len(parts),
                len(block_ids),
            )
        return []
    return list(zip(block_ids, parts, strict=True))


def _parse_lenient_translation_batch(
    translated_text: str,
    *,
    expected_count: int,
) -> list[str] | None:
    stripped = translated_text.strip()
    if not (
        stripped.startswith("<translation_batch")
        and stripped.endswith("</translation_batch>")
    ):
        return None

    try:
        document = ElementTree.fromstring(stripped)
    except ElementTree.ParseError:
        return None

    if _local_name(document.tag) != "translation_batch":
        return None

    blocks = [
        child
        for child in list(document)
        if _local_name(child.tag) == "translation_block"
    ]
    if len(blocks) != expected_count:
        return None

    return ["".join(block.itertext()).strip() for block in blocks]


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _store_assembled_result(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
    file_name: str,
    content_type: str,
    content: bytes,
    partial: bool,
) -> StoredFile:
    stored = storage.put_bytes(
        kind=StoredFileKind.PARTIAL if partial else StoredFileKind.FINAL,
        file_name=file_name,
        content_type=content_type,
        content=content,
    )
    store.attach_job_output(
        job_id,
        partial_object_key=stored.object_key if partial else None,
        final_object_key=None if partial else stored.object_key,
    )
    return stored


def _require_job(store: SQLiteTranslationJobStore, job_id: str):
    job = store.get_job(job_id)
    if job is None:
        raise ValueError(f"Translation job does not exist: {job_id}")
    return job


def _docx_block_id(block) -> str:
    return f"docx:{block.file_name}:{block.block_index}"


def _epub_block_id(block) -> str:
    return f"epub:{block.file_name}:{block.block_index}"
