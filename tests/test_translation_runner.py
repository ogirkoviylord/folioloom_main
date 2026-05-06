import unittest
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

from translator_service.extractors import extract_text_from_docx
from translator_service.extractors import extract_text_from_epub
from translator_service.translation_cache import MemoryTranslationCache
from translator_service.translation_jobs import CancellationToken
from translator_service.translation_runner import (
    TranslatedDocument,
    translate_docx_document,
    translate_epub_document,
    translate_txt_document,
)


class RecordingTranslator:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str]] = []

    def translate(self, *, text: str, source_language: str, target_language: str) -> str:
        self.requests.append((text, source_language, target_language))
        if "<translation_block" in text:
            return _translate_marked_blocks(text, target_language)
        return f"[{target_language}] {text}"


class TranslationRunnerTest(unittest.TestCase):
    def test_translates_txt_document_into_downloadable_txt_result(self):
        translator = RecordingTranslator()

        result = translate_txt_document(
            file_name="notes.txt",
            content="Первый абзац.\n\nВторой абзац.".encode("utf-8"),
            source_language="ru",
            target_language="en",
            max_fragment_chars=20,
            translator=translator,
        )

        self.assertEqual(
            result,
            TranslatedDocument(
                file_name="notes.en.txt",
                content_type="text/plain; charset=utf-8",
                content=b"[en] \xd0\x9f\xd0\xb5\xd1\x80\xd0\xb2\xd1\x8b\xd0\xb9 "
                b"\xd0\xb0\xd0\xb1\xd0\xb7\xd0\xb0\xd1\x86.\n\n[en] "
                b"\xd0\x92\xd1\x82\xd0\xbe\xd1\x80\xd0\xbe\xd0\xb9 "
                b"\xd0\xb0\xd0\xb1\xd0\xb7\xd0\xb0\xd1\x86.",
                fragment_count=2,
            ),
        )
        self.assertEqual(
            translator.requests,
            [
                ("Первый абзац.", "ru", "en"),
                ("Второй абзац.", "ru", "en"),
            ],
        )

    def test_translated_txt_file_name_handles_names_without_extension(self):
        translator = RecordingTranslator()

        result = translate_txt_document(
            file_name="notes",
            content=b"Hello",
            source_language="en",
            target_language="uk",
            max_fragment_chars=100,
            translator=translator,
        )

        self.assertEqual(result.file_name, "notes.uk.txt")

    def test_translates_docx_document_into_downloadable_docx_result(self):
        translator = RecordingTranslator()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>First paragraph</w:t></w:r></w:p>
                <w:p><w:r><w:t>Second</w:t></w:r><w:r><w:t> paragraph</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="contract.docx",
            content=content,
            source_language="en",
            target_language="fr",
            translator=translator,
        )

        self.assertEqual(result.file_name, "contract.fr.docx")
        self.assertEqual(
            result.content_type,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(
            extract_text_from_docx(result.content),
            "[fr] First paragraph\n\n[fr] Second paragraph",
        )
        self.assertEqual(
            translator.requests,
            [
                (
                    "<translation_batch>\n"
                    '<translation_block id="0">First paragraph</translation_block>\n'
                    '<translation_block id="1">Second paragraph</translation_block>\n'
                    "</translation_batch>",
                    "en",
                    "fr",
                ),
            ],
        )

    def test_docx_translation_parses_marked_batch_without_leaking_xml(self):
        class XmlTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>\n"
                    '<translation_block id="0">Глава 1</translation_block>\n'
                    '<translation_block id="1">Источник</translation_block>\n'
                    '<translation_block id="2">Цель</translation_block>\n'
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Chapter 1</w:t></w:r></w:p>
                <w:p><w:r><w:t>Source</w:t></w:r></w:p>
                <w:p><w:r><w:t>Target</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="sample.docx",
            content=content,
            source_language="en",
            target_language="ru",
            translator=XmlTranslator(),
        )

        text = extract_text_from_docx(result.content)
        self.assertEqual(text, "Глава 1\n\nИсточник\n\nЦель")
        self.assertNotIn("translation_batch", text)

    def test_docx_translation_strips_model_service_prefaces_from_batch_blocks(self):
        class ChattyTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    '<translation_block id="0">Вот перевод:\nГлава 1</translation_block>'
                    '<translation_block id="1">```text\nИсточник\n```</translation_block>'
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Chapter 1</w:t></w:r></w:p>
                <w:p><w:r><w:t>Source</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="sample.docx",
            content=content,
            source_language="en",
            target_language="ru",
            translator=ChattyTranslator(),
        )

        text = extract_text_from_docx(result.content)
        self.assertEqual(text, "Глава 1\n\nИсточник")
        self.assertNotIn("Вот перевод", text)
        self.assertNotIn("```", text)

    def test_docx_translation_preserves_run_formatting_nodes(self):
        class XmlTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    '<translation_block id="0">Обычный и жирный текст</translation_block>'
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p>
                  <w:r><w:t>Plain and </w:t></w:r>
                  <w:r><w:rPr><w:b /></w:rPr><w:t>bold text</w:t></w:r>
                </w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="sample.docx",
            content=content,
            source_language="en",
            target_language="ru",
            translator=XmlTranslator(),
        )

        with ZipFile(BytesIO(result.content)) as docx:
            document = _parse_xml(docx.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        bold_runs = [
            run
            for run in document.findall(".//w:r", namespace)
            if run.find("w:rPr/w:b", namespace) is not None
        ]
        self.assertEqual(len(bold_runs), 1)
        bold_text = "".join(
            text_node.text or ""
            for text_node in bold_runs[0].findall(".//w:t", namespace)
        )
        self.assertIn("жирный", bold_text)

    def test_docx_translation_updates_headers_footers_notes_and_comments(self):
        translator = RecordingTranslator()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Main body text</w:t></w:r></w:p></w:body>
            </w:document>
            """,
            extra_parts={
                "word/header1.xml": _docx_part_xml("Header text"),
                "word/footer1.xml": _docx_part_xml("Footer text"),
                "word/footnotes.xml": _docx_part_xml("Footnote text"),
                "word/endnotes.xml": _docx_part_xml("Endnote text"),
                "word/comments.xml": _docx_part_xml("Comment text"),
            },
        )

        result = translate_docx_document(
            file_name="stress.docx",
            content=content,
            source_language="auto",
            target_language="uk",
            translator=translator,
        )

        with ZipFile(BytesIO(result.content)) as docx:
            self.assertEqual(
                _extract_docx_part_text(docx, "word/document.xml"),
                "[uk] Main body text",
            )
            self.assertEqual(
                _extract_docx_part_text(docx, "word/header1.xml"),
                "[uk] Header text",
            )
            self.assertEqual(
                _extract_docx_part_text(docx, "word/footer1.xml"),
                "[uk] Footer text",
            )
            self.assertEqual(
                _extract_docx_part_text(docx, "word/footnotes.xml"),
                "[uk] Footnote text",
            )
            self.assertEqual(
                _extract_docx_part_text(docx, "word/endnotes.xml"),
                "[uk] Endnote text",
            )
            self.assertEqual(
                _extract_docx_part_text(docx, "word/comments.xml"),
                "[uk] Comment text",
            )
        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(len(translator.requests), 1)

    def test_docx_translation_preserves_protected_tokens(self):
        class TokenBreakingTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                document = _parse_xml(text.encode("utf-8"))
                for block in document:
                    block.text = (
                        (block.text or "")
                        .replace("ROW-001", "СТРОКА-001")
                        .replace("inline_code", "встроенный_код")
                        .replace("COMMENT_TEST", "КОММЕНТАРИЙ_ТЕСТ")
                        .replace("{{PLACEHOLDER}}", "{{ЗАПОЛНИТЕЛЬ}}")
                        .replace("https://example.com/a", "https://example.ru/a")
                    )
                return ElementTree.tostring(document, encoding="unicode")

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>ROW-001 uses inline_code and COMMENT_TEST with {{PLACEHOLDER}} at https://example.com/a.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="tokens.docx",
            content=content,
            source_language="auto",
            target_language="ru",
            translator=TokenBreakingTranslator(),
        )

        text = extract_text_from_docx(result.content)
        self.assertIn("ROW-001", text)
        self.assertIn("inline_code", text)
        self.assertIn("COMMENT_TEST", text)
        self.assertIn("{{PLACEHOLDER}}", text)
        self.assertIn("https://example.com/a", text)
        self.assertNotIn("СТРОКА-001", text)
        self.assertNotIn("встроенный_код", text)
        self.assertNotIn("КОММЕНТАРИЙ_ТЕСТ", text)

    def test_docx_auto_batches_include_source_language_hints(self):
        translator = RecordingTranslator()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Русский текст.</w:t></w:r></w:p>
                <w:p><w:r><w:t>Nederlands: Ik fiets vandaag naar Zwolle.</w:t></w:r></w:p>
                <w:p><w:r><w:t>Polski: Zażółć gęślą jaźń.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        translate_docx_document(
            file_name="mixed.docx",
            content=content,
            source_language="auto",
            target_language="ru",
            translator=translator,
        )

        self.assertEqual(
            [request[1] for request in translator.requests],
            ["ru", "nl", "pl"],
        )

    def test_docx_auto_translates_labeled_language_blocks_with_explicit_source(self):
        class SourceAwareTranslator:
            def __init__(self) -> None:
                self.requests: list[tuple[str, str, str]] = []

            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                self.requests.append((text, source_language, target_language))
                document = _parse_xml(text.encode("utf-8"))
                translations = {
                    "uk": "Крыльцо, еж, енот и перья — проверка букв.",
                    "nl": "Сегодня я еду на велосипеде в Зволле.",
                    "fr": "Где находится отель? Это стоит 1 234,56 € — не так ли?",
                    "pl": "Пожелти гуслью душу.",
                    "he": "Привет, мир — текст справа налево внутри русского документа.",
                }
                for block in document:
                    block.text = translations.get(source_language, block.text or "")
                return ElementTree.tostring(document, encoding="unicode")

        translator = SourceAwareTranslator()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Українська: Ґанок, їжак, єнот і пір’я — перевірка літер.</w:t></w:r></w:p>
                <w:p><w:r><w:t>Nederlands: Ik fiets vandaag naar Zwolle.</w:t></w:r></w:p>
                <w:p><w:r><w:t>Français: Où est l’hôtel?</w:t></w:r></w:p>
                <w:p><w:r><w:t>Polski: Zażółć gęślą jaźń.</w:t></w:r></w:p>
                <w:p><w:r><w:t>עברית: שלום עולם — текст справа налево внутри русского документа.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="mixed.docx",
            content=content,
            source_language="auto",
            target_language="ru",
            translator=translator,
        )

        text = extract_text_from_docx(result.content)
        self.assertIn("Украинский: Крыльцо", text)
        self.assertIn("Нидерландский: Сегодня я еду на велосипеде", text)
        self.assertIn("Французский: Где находится отель?", text)
        self.assertIn("Польский: Проверка польских диакритических знаков", text)
        self.assertNotIn("Пожелти гуслью душу", text)
        self.assertIn("Иврит: Привет, мир", text)
        self.assertIn("Сегодня я еду на велосипеде", text)
        self.assertEqual(
            [request[1] for request in translator.requests],
            ["uk", "nl", "fr", "pl", "he"],
        )

    def test_docx_auto_translates_multiple_labeled_languages_inside_one_block(self):
        class SourceAwareTranslator:
            def __init__(self) -> None:
                self.requests: list[tuple[str, str, str]] = []

            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                self.requests.append((text, source_language, target_language))
                document = _parse_xml(text.encode("utf-8"))
                translations = {
                    "zh": "Это китайское предложение.",
                    "ja": "Это японское предложение.",
                    "ko": "Это корейское предложение.",
                }
                for block in document:
                    block.text = translations[source_language]
                return ElementTree.tostring(document, encoding="unicode")

        translator = SourceAwareTranslator()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>中文: 这是一个中文句子。日本語: これは日本語の文です。한국어: 이것은 한국어 문장입니다.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="mixed-inline.docx",
            content=content,
            source_language="auto",
            target_language="ru",
            translator=translator,
        )

        self.assertEqual(
            extract_text_from_docx(result.content),
            "Китайский: Это китайское предложение. "
            "Японский: Это японское предложение. "
            "Корейский: Это корейское предложение.",
        )
        self.assertEqual(
            [request[1] for request in translator.requests],
            ["zh", "ja", "ko"],
        )

    def test_docx_translation_preserves_hyperlink_anchor_text(self):
        class LinkBreakingTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                document = _parse_xml(text.encode("utf-8"))
                for block in document:
                    block.text = (
                        (block.text or "")
                        .replace("External link:", "Внешняя ссылка:")
                        .replace("OpenAI Example Link", "пример ссылки OpenAI")
                        .replace("check the address.", "проверьте адрес.")
                    )
                return ElementTree.tostring(document, encoding="unicode")

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p>
                  <w:r><w:t>External link: </w:t></w:r>
                  <w:hyperlink>
                    <w:r><w:t>OpenAI Example Link</w:t></w:r>
                  </w:hyperlink>
                  <w:r><w:t> — check the address.</w:t></w:r>
                </w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="links.docx",
            content=content,
            source_language="en",
            target_language="ru",
            translator=LinkBreakingTranslator(),
        )

        with ZipFile(BytesIO(result.content)) as docx:
            document = _parse_xml(docx.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        hyperlink = document.find(".//w:hyperlink", namespace)
        self.assertIsNotNone(hyperlink)
        hyperlink_text = "".join(
            text_node.text or "" for text_node in hyperlink.findall(".//w:t", namespace)
        )
        self.assertEqual(hyperlink_text, "OpenAI Example Link")
        self.assertIn("Внешняя ссылка:", extract_text_from_docx(result.content))
        self.assertNotIn("пример ссылки OpenAI", extract_text_from_docx(result.content))

    def test_docx_translation_preserves_subscript_and_superscript_runs(self):
        class FormulaTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                document = _parse_xml(text.encode("utf-8"))
                for block in document:
                    block.text = (
                        (block.text or "")
                        .replace("Formulas and indexes:", "Формулы и индексы:")
                        .replace(" units.", " единиц.")
                    )
                return ElementTree.tostring(document, encoding="unicode")

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p>
                  <w:r><w:t>Formulas and indexes: H</w:t></w:r>
                  <w:r><w:rPr><w:vertAlign w:val="subscript" /></w:rPr><w:t>2</w:t></w:r>
                  <w:r><w:t>O, CO</w:t></w:r>
                  <w:r><w:rPr><w:vertAlign w:val="subscript" /></w:rPr><w:t>2</w:t></w:r>
                  <w:r><w:t>, E = mc</w:t></w:r>
                  <w:r><w:rPr><w:vertAlign w:val="superscript" /></w:rPr><w:t>2</w:t></w:r>
                  <w:r><w:t>, 10</w:t></w:r>
                  <w:r><w:rPr><w:vertAlign w:val="superscript" /></w:rPr><w:t>−6</w:t></w:r>
                  <w:r><w:t> units.</w:t></w:r>
                </w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="formulas.docx",
            content=content,
            source_language="en",
            target_language="ru",
            translator=FormulaTranslator(),
        )

        with ZipFile(BytesIO(result.content)) as docx:
            document = _parse_xml(docx.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        aligned_runs = [
            run
            for run in document.findall(".//w:r", namespace)
            if run.find("w:rPr/w:vertAlign", namespace) is not None
        ]
        aligned_texts = [
            "".join(text_node.text or "" for text_node in run.findall(".//w:t", namespace))
            for run in aligned_runs
        ]
        self.assertEqual(aligned_texts, ["2", "2", "2", "−6"])
        self.assertIn(
            "Формулы и индексы: H2O, CO2, E = mc2, 10−6 единиц.",
            extract_text_from_docx(result.content),
        )

    def test_docx_translation_preserves_tabs_around_translated_text(self):
        class TabTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    "<translation_block id=\"0\">Працівник:\tЯ бачив файл.</translation_block>"
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p>
                  <w:r><w:t>Работник:</w:t><w:tab/><w:t>Я видел файл.</w:t></w:r>
                </w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="dialog.docx",
            content=content,
            source_language="ru",
            target_language="uk",
            translator=TabTranslator(),
        )

        with ZipFile(BytesIO(result.content)) as docx:
            document = _parse_xml(docx.read("word/document.xml"))
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraph = document.find(".//w:p", namespace)
        self.assertIsNotNone(paragraph.find(".//w:tab", namespace))
        self.assertEqual(
            [
                text_node.text
                for text_node in paragraph.findall(".//w:t", namespace)
            ],
            ["Працівник:", "Я бачив файл."],
        )

    def test_docx_translation_translates_fixed_width_pseudo_table_rows_without_shifting_columns(self):
        class PseudoTableTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    "<translation_block id=\"0\">Кава        2      €3,50      зберегти крапку</translation_block>"
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p>
                  <w:r>
                    <w:rPr><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New" /></w:rPr>
                    <w:t>Coffee        2      €3.50      keep decimal point</w:t>
                  </w:r>
                </w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="pseudo-table.docx",
            content=content,
            source_language="en",
            target_language="uk",
            translator=PseudoTableTranslator(),
        )

        line = extract_text_from_docx(result.content)
        self.assertIn("Кава", line)
        self.assertIn("зберегти крапку", line)
        self.assertEqual(line.index("2"), 14)
        self.assertEqual(line.index("€3,50"), 21)
        self.assertEqual(line.index("зберегти крапку"), 32)

    def test_docx_translation_uses_target_language_labels_for_ukrainian(self):
        class LabelTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    "<translation_block id=\"0\">тіло перекладу</translation_block>"
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Немецкий: Fußgängerübergang.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="labels.docx",
            content=content,
            source_language="auto",
            target_language="uk",
            translator=LabelTranslator(),
        )

        text = extract_text_from_docx(result.content)
        self.assertIn("Німецька:", text)
        self.assertNotIn("German:", text)

    def test_docx_translation_keeps_table_as_separate_structural_unit(self):
        translator = RecordingTranslator()
        content = _make_docx(
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
        )

        result = translate_docx_document(
            file_name="table.docx",
            content=content,
            source_language="en",
            target_language="fr",
            max_fragment_chars=1_000,
            translator=translator,
        )

        self.assertEqual(result.fragment_count, 3)
        self.assertEqual(
            [request[0] for request in translator.requests],
            [
                "<translation_batch>\n"
                '<translation_block id="0">Intro paragraph.</translation_block>\n'
                "</translation_batch>",
                "<translation_batch>\n"
                '<translation_block id="0">Source</translation_block>\n'
                '<translation_block id="1">Target</translation_block>\n'
                "</translation_batch>",
                "<translation_batch>\n"
                '<translation_block id="0">Outro paragraph.</translation_block>\n'
                "</translation_batch>",
            ],
        )

    def test_docx_translation_reuses_translation_memory_for_repeated_units(self):
        translator = RecordingTranslator()
        cache = MemoryTranslationCache()
        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>Repeated sentence.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        first = translate_docx_document(
            file_name="first.docx",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
            translation_cache=cache,
        )
        second = translate_docx_document(
            file_name="second.docx",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
            translation_cache=cache,
        )

        self.assertEqual(len(translator.requests), 1)
        self.assertEqual(extract_text_from_docx(first.content), "[uk] Repeated sentence.")
        self.assertEqual(extract_text_from_docx(second.content), "[uk] Repeated sentence.")

    def test_docx_translation_expands_vml_textbox_height_to_avoid_clipping(self):
        class TextboxTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    "<translation_block id=\"0\">Перший довгий рядок перекладу.</translation_block>"
                    "<translation_block id=\"1\">Другий довгий рядок перекладу, який займає більше місця.</translation_block>"
                    "<translation_block id=\"2\">Третій довгий рядок перекладу не повинен обрізатися.</translation_block>"
                    "</translation_batch>"
                )

        content = _make_docx(
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                        xmlns:v="urn:schemas-microsoft-com:vml">
              <w:body>
                <w:p><w:r><w:pict>
                  <v:shape id="TextBox" type="#_x0000_t202" style="width:430pt;height:40pt">
                    <v:textbox><w:txbxContent>
                      <w:p><w:r><w:t>Первая строка.</w:t></w:r></w:p>
                      <w:p><w:r><w:t>Вторая строка.</w:t></w:r></w:p>
                      <w:p><w:r><w:t>Третья строка.</w:t></w:r></w:p>
                    </w:txbxContent></v:textbox>
                  </v:shape>
                </w:pict></w:r></w:p>
              </w:body>
            </w:document>
            """
        )

        result = translate_docx_document(
            file_name="textbox.docx",
            content=content,
            source_language="ru",
            target_language="uk",
            translator=TextboxTranslator(),
        )

        with ZipFile(BytesIO(result.content)) as docx:
            document = _parse_xml(docx.read("word/document.xml"))
        shape = document.find(
            ".//v:shape",
            {"v": "urn:schemas-microsoft-com:vml"},
        )
        self.assertIn("Третій довгий рядок", extract_text_from_docx(result.content))
        self.assertIn("height:", shape.attrib["style"])
        self.assertNotIn("height:40pt", shape.attrib["style"])

    def test_translates_epub_document_into_downloadable_epub_result(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter1.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <h1>Chapter One</h1>
                    <p>First <em>paragraph</em>.</p>
                  </body>
                </html>
                """,
                "OPS/chapter2.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Second paragraph.</p></body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
        )

        self.assertEqual(result.file_name, "book.uk.epub")
        self.assertEqual(result.content_type, "application/epub+zip")
        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] Chapter One\n\n[uk] First paragraph.\n\n[uk] Second paragraph.",
        )
        with ZipFile(BytesIO(result.content)) as epub:
            self.assertEqual(epub.read("OPS/style.css"), b"body { font-family: serif; }")
        self.assertEqual(
            translator.requests,
            [
                (
                    "<translation_batch>\n"
                    '<translation_block id="0">Chapter One</translation_block>\n'
                    '<translation_block id="1">First paragraph.</translation_block>\n'
                    '<translation_block id="2">Second paragraph.</translation_block>\n'
                    "</translation_batch>",
                    "en",
                    "uk",
                ),
            ],
        )

    def test_translates_epub_div_text_without_duplicate_parent_blocks(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <section>
                      <h1>Chapter 1</h1>
                      <div class="body-text">This line is stored in a div.</div>
                      <div class="body-text">Another div paragraph with <span>inline text</span>.</div>
                    </section>
                  </body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
        )

        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] Chapter 1\n\n"
            "[uk] This line is stored in a div.\n\n"
            "[uk] Another div paragraph with inline text.",
        )
        self.assertEqual(
            [request[0] for request in translator.requests],
            [
                "<translation_batch>\n"
                '<translation_block id="0">Chapter 1</translation_block>\n'
                '<translation_block id="1">This line is stored in a div.</translation_block>\n'
                '<translation_block id="2">Another div paragraph with inline text.</translation_block>\n'
                "</translation_batch>",
            ],
        )

    def test_epub_translation_preserves_inline_formatting_nodes(self):
        class XmlTranslator:
            def translate(self, *, text: str, source_language: str, target_language: str) -> str:
                return (
                    "<translation_batch>"
                    '<translation_block id="0">Обычный и выделенный текст.</translation_block>'
                    "</translation_batch>"
                )

        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Plain and <strong>emphasized text</strong>.</p></body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="ru",
            translator=XmlTranslator(),
        )

        with ZipFile(BytesIO(result.content)) as epub:
            chapter = epub.read("OPS/chapter.xhtml").decode("utf-8")
        self.assertIn("<html:strong", chapter)
        self.assertIn("Обычный и", chapter)
        self.assertIn("выделенный", chapter)

    def test_translated_epub_keeps_mimetype_as_first_archive_item(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>First paragraph.</p></body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
        )

        with ZipFile(BytesIO(result.content)) as epub:
            self.assertEqual(epub.infolist()[0].filename, "mimetype")
            self.assertEqual(epub.read("mimetype"), b"application/epub+zip")

    def test_cancelled_epub_translation_returns_partial_epub_result(self):
        translator = RecordingTranslator()
        token = CancellationToken()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <p>First paragraph.</p>
                    <p>Second paragraph.</p>
                  </body>
                </html>
                """,
            }
        )

        def cancel_after_first(progress: tuple[int, int]) -> None:
            if progress == (1, 2):
                token.cancel()

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
            max_fragment_chars=30,
            progress_callback=cancel_after_first,
            cancellation_token=token,
        )

        self.assertEqual(result.file_name, "book.uk.partial.epub")
        self.assertTrue(result.is_partial)
        self.assertEqual(result.fragment_count, 1)
        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] First paragraph.\n\nSecond paragraph.",
        )

    def test_cancelled_epub_translation_uses_spine_reading_order(self):
        translator = RecordingTranslator()
        token = CancellationToken()
        content = _make_epub(
            {
                "OPS/chapter2.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>Second chapter.</p></body>
                </html>
                """,
                "OPS/chapter1.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body><p>First chapter.</p></body>
                </html>
                """,
            },
            spine=["OPS/chapter1.xhtml", "OPS/chapter2.xhtml"],
        )

        def cancel_after_first(progress: tuple[int, int]) -> None:
            if progress == (1, 2):
                token.cancel()

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            translator=translator,
            max_fragment_chars=20,
            progress_callback=cancel_after_first,
            cancellation_token=token,
        )

        self.assertEqual(
            extract_text_from_epub(result.content),
            "[uk] First chapter.\n\nSecond chapter.",
        )

    def test_epub_translation_groups_blocks_by_max_fragment_chars(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <p>One short paragraph.</p>
                    <p>Two short paragraph.</p>
                    <p>Three short paragraph.</p>
                  </body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            max_fragment_chars=50,
            translator=translator,
        )

        self.assertEqual(result.fragment_count, 2)
        self.assertEqual(len(translator.requests), 2)

    def test_epub_translation_keeps_table_as_separate_structural_unit(self):
        translator = RecordingTranslator()
        content = _make_epub(
            {
                "OPS/chapter.xhtml": """
                <html xmlns="http://www.w3.org/1999/xhtml">
                  <body>
                    <p>Intro paragraph.</p>
                    <table>
                      <tr><td>Source</td><td>Target</td></tr>
                    </table>
                    <p>Outro paragraph.</p>
                  </body>
                </html>
                """,
            }
        )

        result = translate_epub_document(
            file_name="book.epub",
            content=content,
            source_language="en",
            target_language="uk",
            max_fragment_chars=1_000,
            translator=translator,
        )

        self.assertEqual(result.fragment_count, 3)
        self.assertEqual(
            [request[0] for request in translator.requests],
            [
                "<translation_batch>\n"
                '<translation_block id="0">Intro paragraph.</translation_block>\n'
                "</translation_batch>",
                "<translation_batch>\n"
                '<translation_block id="0">Source</translation_block>\n'
                '<translation_block id="1">Target</translation_block>\n'
                "</translation_batch>",
                "<translation_batch>\n"
                '<translation_block id="0">Outro paragraph.</translation_block>\n'
                "</translation_batch>",
            ],
        )


if __name__ == "__main__":
    unittest.main()


def _make_docx(document_xml: str, extra_parts: dict[str, str] | None = None) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w") as docx:
        docx.writestr("word/document.xml", document_xml)
        docx.writestr("[Content_Types].xml", "<Types />")
        for file_name, content in (extra_parts or {}).items():
            docx.writestr(file_name, content)
    return archive.getvalue()


def _make_epub(xhtml_items: dict[str, str], spine: list[str] | None = None) -> bytes:
    archive = BytesIO()
    item_names = list(xhtml_items)
    spine = spine or item_names
    manifest_items = "\n".join(
        f'<item id="item{index}" href="{file_name}" media-type="application/xhtml+xml" />'
        for index, file_name in enumerate(item_names)
    )
    spine_items = "\n".join(
        f'<itemref idref="item{item_names.index(file_name)}" />'
        for file_name in spine
    )
    with ZipFile(archive, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "META-INF/container.xml",
            """
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles>
                <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml" />
              </rootfiles>
            </container>
            """,
        )
        epub.writestr(
            "OPS/content.opf",
            f"""
            <package xmlns="http://www.idpf.org/2007/opf">
              <manifest>{manifest_items}</manifest>
              <spine>{spine_items}</spine>
            </package>
            """,
        )
        for file_name, content in xhtml_items.items():
            epub.writestr(file_name, content)
        epub.writestr("OPS/style.css", "body { font-family: serif; }")
    return archive.getvalue()


def _translate_marked_blocks(text: str, target_language: str) -> str:
    from xml.etree import ElementTree

    document = ElementTree.fromstring(text)
    for block in document:
        block.text = f"[{target_language}] {block.text}"
    return ElementTree.tostring(document, encoding="unicode")


def _parse_xml(content: bytes):
    from xml.etree import ElementTree

    return ElementTree.fromstring(content)


def _docx_part_xml(text: str) -> str:
    return f"""
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
    </w:document>
    """


def _extract_docx_part_text(docx: ZipFile, file_name: str) -> str:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    document = _parse_xml(docx.read(file_name))
    return "\n\n".join(
        "".join(text_node.text or "" for text_node in paragraph.findall(".//w:t", namespace))
        for paragraph in document.findall(".//w:p", namespace)
    )
