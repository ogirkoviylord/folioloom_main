import unittest

from io import BytesIO
from zipfile import ZipFile

from translator_service.job_runner import (
    DocumentKind,
    InMemoryTranslationJobRepository,
    TranslationJobStatus,
    run_translation_job,
    run_txt_translation_job,
)


class RecordingTranslator:
    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        return f"[{target_language}] {text}"


class FailingTranslator:
    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        raise RuntimeError("provider failed")


class JobRunnerTest(unittest.TestCase):
    def test_runs_txt_job_and_stores_ready_result(self):
        repository = InMemoryTranslationJobRepository()
        job = repository.create_txt_job(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.\n\nTwo.",
            source_language="en",
            target_language="uk",
        )

        result = run_txt_translation_job(
            repository=repository,
            job_id=job.id,
            max_fragment_chars=5,
            translator=RecordingTranslator(),
        )

        stored_job = repository.get(job.id)
        self.assertEqual(stored_job.status, TranslationJobStatus.READY)
        self.assertEqual(stored_job.result_file_name, "notes.uk.txt")
        self.assertEqual(stored_job.error_message, None)
        self.assertEqual(result.content.decode("utf-8"), "[uk] One.\n\n[uk] Two.")

    def test_runs_docx_job_and_stores_ready_docx_result(self):
        repository = InMemoryTranslationJobRepository()
        job = repository.create_job(
            document_kind=DocumentKind.DOCX,
            user_telegram_id=42,
            file_name="contract.docx",
            content=_make_docx(
                """
                <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                  <w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p></w:body>
                </w:document>
                """
            ),
            source_language="en",
            target_language="fr",
        )

        result = run_translation_job(
            repository=repository,
            job_id=job.id,
            max_fragment_chars=20,
            translator=RecordingTranslator(),
        )

        stored_job = repository.get(job.id)
        self.assertEqual(stored_job.status, TranslationJobStatus.READY)
        self.assertEqual(stored_job.result_file_name, "contract.fr.docx")
        self.assertEqual(
            result.content_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_marks_job_as_failed_when_translation_raises(self):
        repository = InMemoryTranslationJobRepository()
        job = repository.create_txt_job(
            user_telegram_id=42,
            file_name="notes.txt",
            content=b"One.",
            source_language="en",
            target_language="uk",
        )

        with self.assertRaises(RuntimeError):
            run_txt_translation_job(
                repository=repository,
                job_id=job.id,
                max_fragment_chars=20,
                translator=FailingTranslator(),
            )

        stored_job = repository.get(job.id)
        self.assertEqual(stored_job.status, TranslationJobStatus.FAILED)
        self.assertEqual(stored_job.error_message, "provider failed")


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("[Content_Types].xml", "<Types />")
    return archive.getvalue()
