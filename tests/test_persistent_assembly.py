import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from translator_service.document_sandbox import SandboxTranslationUnit
from translator_service.documents import DocumentFormat
from translator_service.extractors import (
    MAX_XML_DEPTH,
    TextExtractionError,
    extract_text_from_docx,
    extract_text_from_epub,
)
from translator_service.file_storage import LocalObjectStorage, StoredFileKind
from translator_service.persistent_assembly import (
    assemble_persistent_docx_result,
    assemble_persistent_epub_result,
    assemble_persistent_txt_result,
)
from translator_service.persistent_jobs import SQLiteTranslationJobStore
from translator_service.persistent_planner import (
    create_persistent_docx_job_plan,
    create_persistent_epub_job_plan,
    create_persistent_txt_job_plan,
)
from translator_service.worker import ProviderUsage, run_stored_text_job_until_idle


class PersistentAssemblyTest(unittest.TestCase):
    def test_assembles_final_docx_from_completed_work_units(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _docx_plan(store=store, storage=storage)

            _complete_next(store, plan.job.id, "Вступний абзац.")
            _complete_next(store, plan.job.id, "Джерело\n\nЦіль")
            _complete_next(store, plan.job.id, "Фінальний абзац.")

            stored = assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.docx",
                partial=False,
            )

            persisted_job = store.get_job(plan.job.id)
            self.assertEqual(stored.kind, StoredFileKind.FINAL)
            self.assertEqual(persisted_job.final_object_key, stored.object_key)
            self.assertEqual(
                extract_text_from_docx(storage.get_bytes(stored.object_key)),
                "Вступний абзац.\n\nДжерело\n\nЦіль\n\nФінальний абзац.",
            )

    def test_assembles_partial_docx_and_preserves_untranslated_blocks(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _docx_plan(store=store, storage=storage)

            _complete_next(store, plan.job.id, "Вступний абзац.")

            stored = assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.partial.docx",
                partial=True,
            )

            persisted_job = store.get_job(plan.job.id)
            self.assertEqual(stored.kind, StoredFileKind.PARTIAL)
            self.assertEqual(persisted_job.partial_object_key, stored.object_key)
            self.assertEqual(
                extract_text_from_docx(storage.get_bytes(stored.object_key)),
                "Вступний абзац.\n\nSource\n\nTarget\n\nOutro paragraph.",
            )

    def test_assembles_partial_epub_preserving_nav_and_untranslated_body(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _epub_plan(store=store, storage=storage)

            _complete_next(store, plan.job.id, "Перший справжній абзац.")

            stored = assemble_persistent_epub_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.partial.epub",
                partial=True,
            )

            text = extract_text_from_epub(storage.get_bytes(stored.object_key))
            persisted_job = store.get_job(plan.job.id)
            self.assertEqual(stored.kind, StoredFileKind.PARTIAL)
            self.assertEqual(persisted_job.partial_object_key, stored.object_key)
            self.assertIn("Contents", text)
            self.assertIn("* * *", text)
            self.assertIn("Перший справжній абзац.", text)
            self.assertIn("Second real paragraph.", text)
            self.assertNotIn("[uk] Contents", text)

    def test_assembles_final_epub_with_translated_metadata_toc_and_title(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _epub_metadata_plan(store=store, storage=storage)

            _complete_all_with_prefixed_text(store, storage, plan.job.id)

            stored = assemble_persistent_epub_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.epub",
                partial=False,
            )

            with ZipFile(BytesIO(storage.get_bytes(stored.object_key))) as epub:
                opf = _parse_xml(epub.read("OPS/content.opf"))
                toc = _parse_xml(epub.read("OPS/toc.ncx"))
                chapter = _parse_xml(epub.read("OPS/chapter.xhtml"))

                self.assertEqual(epub.infolist()[0].filename, "mimetype")
                self.assertEqual(epub.read("mimetype"), b"application/epub+zip")
                self.assertEqual(
                    epub.read("OPS/style.css"),
                    b"body { font-family: serif; }",
                )

            self.assertEqual(_first_text(opf, "title"), "[uk] Original Book Title")
            self.assertEqual(
                _first_text(opf, "description"),
                "[uk] Original book description.",
            )
            self.assertEqual(_first_text(opf, "language"), "uk")
            self.assertEqual(
                [
                    _element_text(element)
                    for element in toc.iter()
                    if _local_name(element.tag) == "text"
                ],
                ["[uk] Original Book Title", "[uk] Chapter One"],
            )
            self.assertEqual(_first_text(chapter, "title"), "[uk] Original Book Title")
            self.assertEqual(
                extract_text_from_epub(storage.get_bytes(stored.object_key)),
                "[uk] Chapter One\n\n[uk] First paragraph.",
            )

    def test_assembles_final_epub_with_translated_nested_navigation_labels(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _epub_metadata_plan(
                store=store,
                storage=storage,
                content=_make_epub_with_metadata_and_toc(include_nested_nav=True),
            )

            _complete_all_with_prefixed_text(store, storage, plan.job.id)

            stored = assemble_persistent_epub_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.epub",
                partial=False,
            )

            with ZipFile(BytesIO(storage.get_bytes(stored.object_key))) as epub:
                navigation = _parse_xml(epub.read("OPS/nav.xhtml"))

            self.assertEqual(
                [
                    _element_text(element)
                    for element in navigation.iter()
                    if _local_name(element.tag) == "a"
                ],
                ["[uk] Part I", "[uk] Chapter 1"],
            )

    def test_assembles_partial_epub_without_metadata_toc_or_nav_translation(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _epub_metadata_plan(store=store, storage=storage)

            _complete_next(store, plan.job.id, "[uk] Chapter One")

            stored = assemble_persistent_epub_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.partial.epub",
                partial=True,
            )

            with ZipFile(BytesIO(storage.get_bytes(stored.object_key))) as epub:
                opf = _parse_xml(epub.read("OPS/content.opf"))
                toc = _parse_xml(epub.read("OPS/toc.ncx"))
                chapter = _parse_xml(epub.read("OPS/chapter.xhtml"))

                self.assertEqual(
                    epub.read("OPS/style.css"),
                    b"body { font-family: serif; }",
                )

            self.assertEqual(_first_text(opf, "title"), "Original Book Title")
            self.assertEqual(
                _first_text(opf, "description"),
                "Original book description.",
            )
            self.assertEqual(_first_text(opf, "language"), "en")
            self.assertEqual(
                [
                    _element_text(element)
                    for element in toc.iter()
                    if _local_name(element.tag) == "text"
                ],
                ["Original Book Title", "Chapter One"],
            )
            self.assertEqual(_first_text(chapter, "title"), "Original Book Title")
            self.assertEqual(
                extract_text_from_epub(storage.get_bytes(stored.object_key)),
                "[uk] Chapter One\n\nFirst paragraph.",
            )

    def test_assembles_partial_epub_ignoring_completed_auxiliary_units(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _epub_metadata_plan(store=store, storage=storage)

            _complete_next(store, plan.job.id, "[uk] Chapter One")
            _complete_next(store, plan.job.id, "[uk] First paragraph.")
            _complete_next(store, plan.job.id, "[uk] Original Book Title")

            stored = assemble_persistent_epub_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.partial.epub",
                partial=True,
            )

            with ZipFile(BytesIO(storage.get_bytes(stored.object_key))) as epub:
                opf = _parse_xml(epub.read("OPS/content.opf"))
                chapter = _parse_xml(epub.read("OPS/chapter.xhtml"))

            self.assertEqual(_first_text(opf, "title"), "Original Book Title")
            self.assertEqual(_first_text(opf, "language"), "en")
            self.assertEqual(_first_text(chapter, "title"), "Original Book Title")
            self.assertEqual(
                extract_text_from_epub(storage.get_bytes(stored.object_key)),
                "[uk] Chapter One\n\n[uk] First paragraph.",
            )

    def test_parses_persisted_translation_batch_for_multi_block_docx_unit(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _docx_plan(store=store, storage=storage)

            _complete_next(store, plan.job.id, "Вступний абзац.")
            _complete_next(
                store,
                plan.job.id,
                "<translation_batch>"
                '<translation_block id="1" source_language="en">'
                "Джерело"
                "</translation_block>"
                '<translation_block id="2" source_language="en">'
                "Ціль"
                "</translation_block>"
                "</translation_batch>",
            )
            _complete_next(store, plan.job.id, "Фінальний абзац.")

            stored = assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.docx",
                partial=False,
            )

            self.assertEqual(
                extract_text_from_docx(storage.get_bytes(stored.object_key)),
                "Вступний абзац.\n\nДжерело\n\nЦіль\n\nФінальний абзац.",
            )

    def test_assembles_docx_table_cells_by_translation_block_id_when_reordered(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            # Rights basis: synthetic minimal fixture authored for this test.
            plan = _docx_table_alignment_plan(store=store, storage=storage)

            _complete_next(store, plan.job.id, "Вступний абзац.")
            _complete_next(
                store,
                plan.job.id,
                "<translation_batch>"
                '<translation_block id="1" source_language="en">'
                "Опис A"
                "</translation_block>"
                '<translation_block id="0" source_language="en">'
                "Варіант A"
                "</translation_block>"
                "</translation_batch>",
            )
            _complete_next(store, plan.job.id, "Фінальний абзац.")

            stored = assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="options.uk.docx",
                partial=False,
            )

            self.assertEqual(
                extract_text_from_docx(storage.get_bytes(stored.object_key)),
                "Вступний абзац.\n\nВаріант A\n\nОпис A\n\nФінальний абзац.",
            )

    def test_assembles_docx_with_original_blocks_when_unit_parts_do_not_match(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _docx_plan(store=store, storage=storage)

            _complete_next(store, plan.job.id, "Вступний абзац.")
            _complete_next(store, plan.job.id, "Одна строка вместо двух")

            stored = assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.partial.docx",
                partial=True,
            )

            self.assertEqual(stored.kind, StoredFileKind.PARTIAL)
            self.assertEqual(
                extract_text_from_docx(storage.get_bytes(stored.object_key)),
                "Вступний абзац.\n\nSource\n\nTarget\n\nOutro paragraph.",
            )

    def test_assembles_docx_after_persistent_worker_execution(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _docx_plan(store=store, storage=storage)

            run_stored_text_job_until_idle(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                worker_id="test-worker",
                translator=BlockAwareTranslator(),
            )
            stored = assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.docx",
                partial=False,
            )

            self.assertEqual(
                extract_text_from_docx(storage.get_bytes(stored.object_key)),
                "uk:Intro paragraph.\n\nuk:Source\n\nuk:Target\n\nuk:Outro paragraph.",
            )

    def test_assembles_final_txt_from_completed_work_units_with_original_layout(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _txt_plan(
                store=store,
                storage=storage,
                content=b"# Chapter\n\nKEY=value\n- First item\nBody text.\n",
            )
            _complete_next(store, plan.job.id, "Глава")
            _complete_next(store, plan.job.id, "Первый пункт")
            _complete_next(store, plan.job.id, "Основной текст.")

            stored = assemble_persistent_txt_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="notes.ru.txt",
                partial=False,
            )

            self.assertEqual(stored.kind, StoredFileKind.FINAL)
            self.assertEqual(
                storage.get_bytes(stored.object_key).decode("utf-8"),
                "# Глава\n\nKEY=value\n- Первый пункт\nОсновной текст.\n",
            )

    def test_assembles_partial_txt_with_pending_segments_in_source_language(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _txt_plan(
                store=store,
                storage=storage,
                content=b"First paragraph.\nSecond paragraph.\n",
            )
            _complete_next(store, plan.job.id, "Перший абзац.")

            stored = assemble_persistent_txt_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="notes.uk.partial.txt",
                partial=True,
            )

            self.assertEqual(stored.kind, StoredFileKind.PARTIAL)
            self.assertEqual(
                storage.get_bytes(stored.object_key).decode("utf-8"),
                "Перший абзац.\nSecond paragraph.\n",
            )

    def test_assembles_docx_through_configured_document_sandbox(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _docx_plan(store=store, storage=storage)
            sandbox = RecordingAssemblySandbox(
                output=_make_docx(
                    """
                    <w:document
                      xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>Sandboxed result.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """
                )
            )

            _complete_next(store, plan.job.id, "Вступний абзац.")
            stored = assemble_persistent_docx_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.docx",
                partial=False,
                document_sandbox=sandbox,
            )

            self.assertEqual(
                extract_text_from_docx(storage.get_bytes(stored.object_key)),
                "Sandboxed result.",
            )
            self.assertEqual(len(sandbox.calls), 1)
            document_format, source_content, translated_units = sandbox.calls[0]
            self.assertEqual(document_format, DocumentFormat.DOCX)
            self.assertEqual(
                source_content,
                storage.get_bytes(plan.job.source_object_key),
            )
            self.assertEqual(
                translated_units,
                [
                    SandboxTranslationUnit(
                        source_block_ids=("docx:word/document.xml:0",),
                        translated_text="Вступний абзац.",
                    )
                ],
            )

    def test_assembles_epub_through_configured_document_sandbox(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            plan = _epub_plan(store=store, storage=storage)
            sandbox = RecordingAssemblySandbox(
                output=_make_epub(
                    {
                        "OPS/chapter.xhtml": """
                        <html xmlns="http://www.w3.org/1999/xhtml">
                          <body><p>Sandboxed result.</p></body>
                        </html>
                        """
                    }
                )
            )

            _complete_next(store, plan.job.id, "Перший справжній абзац.")
            stored = assemble_persistent_epub_result(
                store=store,
                storage=storage,
                job_id=plan.job.id,
                file_name="book.uk.epub",
                partial=False,
                document_sandbox=sandbox,
            )

            self.assertIn(
                "Sandboxed result.",
                extract_text_from_epub(storage.get_bytes(stored.object_key)),
            )
            self.assertEqual(len(sandbox.calls), 1)
            document_format, source_content, translated_units = sandbox.calls[0]
            self.assertEqual(document_format, DocumentFormat.EPUB)
            self.assertEqual(
                source_content,
                storage.get_bytes(plan.job.source_object_key),
            )
            self.assertEqual(
                translated_units,
                [
                    SandboxTranslationUnit(
                        source_block_ids=("epub:OPS/chapter.xhtml:0",),
                        translated_text="Перший справжній абзац.",
                    )
                ],
            )

    def test_rejects_deep_docx_xml_during_assembly(self):
        with TemporaryDirectory() as temp_dir:
            storage = LocalObjectStorage(Path(temp_dir) / "objects")
            store = SQLiteTranslationJobStore(Path(temp_dir) / "jobs.sqlite3")
            self.addCleanup(store.close)
            original = storage.put_bytes(
                kind=StoredFileKind.ORIGINAL,
                file_name="deep.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                content=_make_docx(_deep_docx_xml(MAX_XML_DEPTH + 1)),
            )
            job = store.create_job(
                order_id="order-deep",
                user_id="user-42",
                file_id=original.object_key,
                source_object_key=original.object_key,
                file_name="deep.docx",
                document_kind="docx",
                source_language="en",
                target_language="uk",
                adapter_version="test",
                prompt_version="test",
                pricing_snapshot_id="test",
            )

            with self.assertRaisesRegex(
                TextExtractionError,
                "XML nesting is too deep",
            ):
                assemble_persistent_docx_result(
                    store=store,
                    storage=storage,
                    job_id=job.id,
                    file_name="deep.uk.docx",
                    partial=False,
                )


def _docx_plan(*, store: SQLiteTranslationJobStore, storage: LocalObjectStorage):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="book.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        content=_make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Intro paragraph.</w:t></w:r></w:p>
                <w:tbl>
                  <w:tr>
                    <w:tc><w:p><w:r><w:t>Source</w:t></w:r></w:p></w:tc>
                    <w:tc><w:p><w:r><w:t>Target</w:t></w:r></w:p></w:tc>
                  </w:tr>
                </w:tbl>
                <w:p><w:r><w:t>Outro paragraph.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        ),
    )
    return create_persistent_docx_job_plan(
        store=store,
        storage=storage,
        order_id="order-docx",
        user_id="user-42",
        source_object_key=original.object_key,
        file_name="book.docx",
        source_language="en",
        target_language="uk",
        max_fragment_chars=1_000,
    )


def _docx_table_alignment_plan(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="options.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        content=_make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Intro paragraph.</w:t></w:r></w:p>
                <w:tbl>
                  <w:tr>
                    <w:tc><w:p><w:r><w:t>Option A</w:t></w:r></w:p></w:tc>
                    <w:tc><w:p><w:r><w:t>Description A</w:t></w:r></w:p></w:tc>
                  </w:tr>
                </w:tbl>
                <w:p><w:r><w:t>Outro paragraph.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        ),
    )
    return create_persistent_docx_job_plan(
        store=store,
        storage=storage,
        order_id="order-docx-table-alignment",
        user_id="user-42",
        source_object_key=original.object_key,
        file_name="options.docx",
        source_language="en",
        target_language="uk",
        max_fragment_chars=1_000,
    )


def _txt_plan(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    content: bytes,
):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="notes.txt",
        content_type="text/plain; charset=utf-8",
        content=content,
    )
    return create_persistent_txt_job_plan(
        store=store,
        storage=storage,
        order_id="order-txt",
        user_id="user-42",
        source_object_key=original.object_key,
        file_name="notes.txt",
        source_language="en",
        target_language="uk",
        max_fragment_chars=1_000,
    )


def _epub_plan(*, store: SQLiteTranslationJobStore, storage: LocalObjectStorage):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="book.epub",
        content_type="application/epub+zip",
        content=_make_epub(
            {
                "OPS/front.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <h1>Contents</h1>
                    <p>Chapter 1</p>
                  </body>
                </html>
                """,
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <h1>Chapter 1</h1>
                    <p>* * *</p>
                    <p>First real paragraph.</p>
                    <p>Second real paragraph.</p>
                  </body>
                </html>
                """,
            },
        ),
    )
    return create_persistent_epub_job_plan(
        store=store,
        storage=storage,
        order_id="order-epub",
        user_id="user-42",
        source_object_key=original.object_key,
        file_name="book.epub",
        source_language="en",
        target_language="uk",
        max_fragment_chars=30,
    )


def _epub_metadata_plan(
    *,
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    content: bytes | None = None,
):
    original = storage.put_bytes(
        kind=StoredFileKind.ORIGINAL,
        file_name="book.epub",
        content_type="application/epub+zip",
        content=content or _make_epub_with_metadata_and_toc(),
    )
    return create_persistent_epub_job_plan(
        store=store,
        storage=storage,
        order_id="order-epub",
        user_id="user-42",
        source_object_key=original.object_key,
        file_name="book.epub",
        source_language="en",
        target_language="uk",
        max_fragment_chars=15,
    )


def _complete_next(
    store: SQLiteTranslationJobStore,
    job_id: str,
    translated_text: str,
) -> None:
    unit = store.claim_next_work_unit(job_id, worker_id="test")
    store.complete_work_unit(
        unit.id,
        translated_text=translated_text,
        prompt_tokens=1,
        completion_tokens=1,
        cache_hit_tokens=0,
        cache_miss_tokens=1,
    )


def _complete_all_with_prefixed_text(
    store: SQLiteTranslationJobStore,
    storage: LocalObjectStorage,
    job_id: str,
) -> None:
    while unit := store.claim_next_work_unit(job_id, worker_id="test"):
        source_text = storage.get_bytes(unit.source_object_key).decode("utf-8")
        store.complete_work_unit(
            unit.id,
            translated_text=_prefixed_translation(source_text, unit.target_language),
            prompt_tokens=1,
            completion_tokens=1,
            cache_hit_tokens=0,
            cache_miss_tokens=1,
        )


def _prefixed_translation(source_text: str, target_language: str) -> str:
    from xml.etree import ElementTree

    if source_text.strip() == "en":
        return target_language
    try:
        document = ElementTree.fromstring(source_text)
    except ElementTree.ParseError:
        return f"[{target_language}] {source_text}"

    for block in document:
        if block.text == "en":
            block.text = target_language
        else:
            block.text = f"[{target_language}] {block.text}"
    return ElementTree.tostring(document, encoding="unicode")


def _make_docx(document_xml: str) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
    return archive.getvalue()


def _deep_docx_xml(nesting_depth: int) -> str:
    open_tags = "<w:sdt>" * nesting_depth
    close_tags = "</w:sdt>" * nesting_depth
    return f"""
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>{open_tags}<w:p><w:r><w:t>Deep text</w:t></w:r></w:p>{close_tags}</w:body>
    </w:document>
    """


def _make_epub(xhtml_items: dict[str, str]) -> bytes:
    from io import BytesIO
    from zipfile import ZipFile

    archive = BytesIO()
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr("META-INF/container.xml", "<container />")
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
    return archive.getvalue()


def _make_epub_with_metadata_and_toc(*, include_nested_nav: bool = False) -> bytes:
    archive = BytesIO()
    nav_manifest_item = (
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
        'properties="nav" />'
        if include_nested_nav
        else ""
    )
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile
                  full-path="OPS/content.opf"
                  media-type="application/oebps-package+xml" />
              </rootfiles>
            </container>
            """,
        )
        epub.writestr(
            "OPS/content.opf",
            f"""
            <package xmlns="http://www.idpf.org/2007/opf"
                     xmlns:dc="http://purl.org/dc/elements/1.1/"
                     unique-identifier="bookid">
              <metadata>
                <dc:identifier id="bookid">urn:uuid:test-book</dc:identifier>
                <dc:title>Original Book Title</dc:title>
                <dc:language>en</dc:language>
                <dc:description>Original book description.</dc:description>
              </metadata>
              <manifest>
                <item
                  id="chapter"
                  href="chapter.xhtml"
                  media-type="application/xhtml+xml" />
                <item id="style" href="style.css" media-type="text/css" />
                <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml" />
                {nav_manifest_item}
              </manifest>
              <spine toc="ncx"><itemref idref="chapter" /></spine>
            </package>
            """,
        )
        epub.writestr(
            "OPS/toc.ncx",
            """
            <ncx xmlns="http://www.daisy.org/z3986/2005/ncx/">
              <docTitle><text>Original Book Title</text></docTitle>
              <navMap>
                <navPoint id="chapter" playOrder="1">
                  <navLabel><text>Chapter One</text></navLabel>
                  <content src="chapter.xhtml" />
                </navPoint>
              </navMap>
            </ncx>
            """,
        )
        epub.writestr(
            "OPS/chapter.xhtml",
            """
            <html xmlns="http://www.w3.org/1999/xhtml">
              <head>
                <title>Original Book Title</title>
                <link href="style.css" rel="stylesheet" type="text/css" />
              </head>
              <body><h1>Chapter One</h1><p>First paragraph.</p></body>
            </html>
            """,
        )
        if include_nested_nav:
            epub.writestr(
                "OPS/nav.xhtml",
                """
                <html xmlns="http://www.w3.org/1999/xhtml"
                      xmlns:epub="http://www.idpf.org/2007/ops">
                  <body>
                    <nav epub:type="toc">
                      <ol>
                        <li>
                          <a href="part.xhtml">Part I</a>
                          <ol>
                            <li><a href="chapter.xhtml">Chapter 1</a></li>
                          </ol>
                        </li>
                      </ol>
                    </nav>
                  </body>
                </html>
                """,
            )
        epub.writestr("OPS/style.css", "body { font-family: serif; }")
    return archive.getvalue()


def _parse_xml(content: bytes):
    from xml.etree import ElementTree

    return ElementTree.fromstring(content)


def _first_text(document, local_name: str) -> str:
    for element in document.iter():
        if _local_name(element.tag) == local_name:
            return _element_text(element)
    raise AssertionError(f"Missing element: {local_name}")


def _element_text(element) -> str:
    return "".join(element.itertext()).strip()


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


class BlockAwareTranslator:
    def __init__(self) -> None:
        self.last_usage: ProviderUsage | None = None

    def translate(
        self,
        *,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
        self.last_usage = ProviderUsage(prompt_tokens=1, completion_tokens=1)
        return "\n\n".join(
            f"{target_language}:{part}" for part in text.split("\n\n")
        )


class RecordingAssemblySandbox:
    def __init__(self, *, output: bytes) -> None:
        self._output = output
        self.calls: list[
            tuple[DocumentFormat, bytes, list[SandboxTranslationUnit]]
        ] = []

    def assemble_document(
        self,
        *,
        document_format: DocumentFormat,
        content: bytes,
        translated_units: list[SandboxTranslationUnit],
    ) -> bytes:
        self.calls.append((document_format, content, translated_units))
        return self._output


if __name__ == "__main__":
    unittest.main()
