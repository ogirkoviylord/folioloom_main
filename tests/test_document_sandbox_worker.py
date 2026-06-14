import base64
import io
import json
import os
import sys
import unittest
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from translator_service.document_sandbox_worker import (
    _adapter_plan_to_json,
    _assemble_document,
    _disable_network_if_configured,
    _extract_text,
    _handle_request,
    _plan_translation,
    _read_request_bytes,
    _text_block_to_json,
    _translated_units_from_json,
    _write_response,
    main,
)
from translator_service.documents import DocumentFormat
from translator_service.extractors import TextExtractionError
from translator_service.format_adapters.contracts import (
    FormatAdapterPlan,
    FormatTextBlock,
    FormatTranslationUnit,
)
from translator_service.structure_optimizer import PromptTier, TextBlockKind


def _make_docx(text: str) -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
        zf.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>')
    return buf.getvalue()


class ExtractTextTest(unittest.TestCase):
    def test_extracts_text_from_txt(self):
        result = _extract_text(
            document_format=DocumentFormat.TXT,
            content=b"Hello world",
        )
        self.assertEqual(result, "Hello world")

    def test_extracts_text_from_docx(self):
        content = _make_docx("Test document")
        result = _extract_text(
            document_format=DocumentFormat.DOCX,
            content=content,
        )
        self.assertEqual(result, "Test document")

    def test_raises_for_unsupported_format(self):
        with self.assertRaises(TextExtractionError):
            _extract_text(
                document_format=DocumentFormat.PDF,
                content=b"fake",
            )


class PlanTranslationTest(unittest.TestCase):
    def test_plans_txt_translation(self):
        plan = _plan_translation(
            document_format=DocumentFormat.TXT,
            content=b"Some text to translate",
            max_fragment_chars=5000,
        )
        self.assertEqual(plan.document_format, DocumentFormat.TXT)
        self.assertGreater(plan.fragment_count, 0)

    def test_plans_docx_translation(self):
        plan = _plan_translation(
            document_format=DocumentFormat.DOCX,
            content=_make_docx("Paragraph one"),
            max_fragment_chars=5000,
        )
        self.assertEqual(plan.document_format, DocumentFormat.DOCX)

    def test_raises_for_unsupported_format(self):
        with self.assertRaises(TextExtractionError):
            _plan_translation(
                document_format=DocumentFormat.PDF,
                content=b"fake",
                max_fragment_chars=5000,
            )


class AssembleDocumentTest(unittest.TestCase):
    def test_raises_for_unsupported_format(self):
        with self.assertRaises(TextExtractionError):
            _assemble_document(
                document_format=DocumentFormat.TXT,
                content=b"hello",
                translated_units=[],
            )


class HandleRequestTest(unittest.TestCase):
    def test_extract_text_operation(self):
        request = {
            "operation": "extract_text",
            "document_format": "txt",
            "content_b64": base64.b64encode(b"Hello world").decode("ascii"),
        }
        result = _handle_request(request)
        self.assertEqual(result["text"], "Hello world")

    def test_plan_translation_operation(self):
        request = {
            "operation": "plan_translation",
            "document_format": "txt",
            "content_b64": base64.b64encode(b"Hello world").decode("ascii"),
            "max_fragment_chars": 5000,
        }
        result = _handle_request(request)
        self.assertIn("units", result)
        self.assertIn("document_format", result)
        self.assertEqual(result["document_format"], "txt")

    def test_assemble_document_operation(self):
        docx_content = _make_docx("First paragraph")
        request = {
            "operation": "assemble_document",
            "document_format": "docx",
            "content_b64": base64.b64encode(docx_content).decode("ascii"),
            "translated_units": [
                {
                    "source_block_ids": ["docx:word/document.xml:0"],
                    "translated_text": "Translated paragraph",
                }
            ],
        }
        result = _handle_request(request)
        self.assertIn("content_b64", result)

    def test_unsupported_operation_raises(self):
        request = {
            "operation": "unknown_op",
            "document_format": "txt",
            "content_b64": base64.b64encode(b"data").decode("ascii"),
        }
        with self.assertRaises(ValueError):
            _handle_request(request)

    def test_plan_translation_with_translation_mode(self):
        request = {
            "operation": "plan_translation",
            "document_format": "txt",
            "content_b64": base64.b64encode(b"Hello world").decode("ascii"),
            "max_fragment_chars": 5000,
            "translation_mode": "book",
        }
        result = _handle_request(request)
        self.assertIn("units", result)


class TranslatedUnitsFromJsonTest(unittest.TestCase):
    def test_parses_valid_units(self):
        payload = [
            {
                "source_block_ids": ["block-1", "block-2"],
                "translated_text": "Translated text",
            }
        ]
        units = _translated_units_from_json(payload)
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].source_block_ids, ("block-1", "block-2"))
        self.assertEqual(units[0].translated_text, "Translated text")

    def test_rejects_non_list_payload(self):
        with self.assertRaises(ValueError):
            _translated_units_from_json("not-a-list")

    def test_rejects_non_dict_unit(self):
        with self.assertRaises(ValueError):
            _translated_units_from_json(["not-a-dict"])

    def test_rejects_missing_source_block_ids(self):
        with self.assertRaises(ValueError):
            _translated_units_from_json([{"translated_text": "text"}])


class AdapterPlanToJsonTest(unittest.TestCase):
    def test_serializes_plan_to_json(self):
        plan = FormatAdapterPlan(
            document_format=DocumentFormat.TXT,
            adapter_version="txt-v1",
            units=(
                FormatTranslationUnit(
                    sequence=0,
                    blocks=(
                        FormatTextBlock(
                            index=0,
                            source_block_id="txt:0",
                            text="Hello",
                            kind=TextBlockKind.PLAIN,
                            group_id=None,
                            metadata=(),
                        ),
                    ),
                    prompt_tier=PromptTier.PLAIN,
                ),
            ),
            character_count=5,
            estimated_input_tokens=10,
        )
        result = _adapter_plan_to_json(plan)
        self.assertEqual(result["document_format"], "txt")
        self.assertEqual(result["adapter_version"], "txt-v1")
        self.assertEqual(result["character_count"], 5)
        self.assertEqual(result["estimated_input_tokens"], 10)
        self.assertEqual(len(result["units"]), 1)
        unit = result["units"][0]
        self.assertEqual(unit["sequence"], 0)
        self.assertEqual(unit["prompt_tier"], "plain")
        self.assertEqual(len(unit["blocks"]), 1)
        block = unit["blocks"][0]
        self.assertEqual(block["index"], 0)
        self.assertEqual(block["source_block_id"], "txt:0")
        self.assertEqual(block["text"], "Hello")
        self.assertEqual(block["kind"], "plain")

    def test_text_block_metadata_is_list(self):
        block = FormatTextBlock(
            index=0,
            source_block_id="txt:0",
            text="Hello",
            metadata=(("key", "val"),),
        )
        result = _text_block_to_json(block)
        self.assertEqual(result["metadata"], [("key", "val")])


class ReadRequestBytesTest(unittest.TestCase):
    def test_reads_stdin_without_limit(self):
        fake_stdin = io.BytesIO(b'{"operation": "test"}')
        with patch.object(sys, "stdin", new=unittest.mock.MagicMock(buffer=fake_stdin)):
            with patch.dict("os.environ", {}, clear=False):
                result = _read_request_bytes()
        self.assertEqual(result, b'{"operation": "test"}')

    def test_reads_stdin_with_limit(self):
        payload = b'{"operation": "test"}'
        fake_stdin = io.BytesIO(payload)
        with patch.object(sys, "stdin", new=unittest.mock.MagicMock(buffer=fake_stdin)):
            with patch.dict(
                "os.environ",
                {"DOCUMENT_SANDBOX_MAX_STDIN_BYTES": "1000"},
            ):
                result = _read_request_bytes()
        self.assertEqual(result, payload)

    def test_rejects_oversized_stdin(self):
        fake_stdin = io.BytesIO(b"x" * 20)
        with patch.object(sys, "stdin", new=unittest.mock.MagicMock(buffer=fake_stdin)):
            with patch.dict(
                "os.environ",
                {"DOCUMENT_SANDBOX_MAX_STDIN_BYTES": "10"},
            ):
                with self.assertRaises(ValueError):
                    _read_request_bytes()


class DisableNetworkTest(unittest.TestCase):
    def test_noop_when_env_not_set(self):
        import socket as socket_module

        original_socket = socket_module.socket
        with patch.dict("os.environ", {}, clear=False):
            if "DOCUMENT_SANDBOX_DISABLE_NETWORK" in os.environ:
                del os.environ["DOCUMENT_SANDBOX_DISABLE_NETWORK"]
            _disable_network_if_configured()
        self.assertIs(socket_module.socket, original_socket)

    def test_disables_network_when_env_set(self):
        import socket as socket_module

        original_socket = socket_module.socket
        original_create_connection = socket_module.create_connection
        try:
            with patch.dict(
                "os.environ",
                {"DOCUMENT_SANDBOX_DISABLE_NETWORK": "1"},
            ):
                _disable_network_if_configured()
            with self.assertRaises(OSError):
                socket_module.socket()
            with self.assertRaises(OSError):
                socket_module.create_connection(("localhost", 80))
        finally:
            socket_module.socket = original_socket
            socket_module.create_connection = original_create_connection


class WriteResponseTest(unittest.TestCase):
    def test_writes_json_to_stdout(self):
        buf = io.StringIO()
        with patch.object(sys, "stdout", new=buf):
            _write_response({"ok": True, "key": "value"})
        output = buf.getvalue()
        parsed = json.loads(output)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["key"], "value")


class MainTest(unittest.TestCase):
    def test_main_returns_zero_on_success(self):
        request = {
            "operation": "extract_text",
            "document_format": "txt",
            "content_b64": base64.b64encode(b"Hello").decode("ascii"),
        }
        payload = json.dumps(request).encode("utf-8")
        fake_stdin = io.BytesIO(payload)
        stdout_buf = io.StringIO()

        with patch.object(sys, "stdin", new=unittest.mock.MagicMock(buffer=fake_stdin)):
            with patch.object(sys, "stdout", new=stdout_buf):
                with patch.dict("os.environ", {}, clear=False):
                    result = main()

        self.assertEqual(result, 0)
        response = json.loads(stdout_buf.getvalue())
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["text"], "Hello")

    def test_main_returns_zero_on_error_with_error_response(self):
        payload = b"not valid json"
        fake_stdin = io.BytesIO(payload)
        stdout_buf = io.StringIO()

        with patch.object(sys, "stdin", new=unittest.mock.MagicMock(buffer=fake_stdin)):
            with patch.object(sys, "stdout", new=stdout_buf):
                with patch.dict("os.environ", {}, clear=False):
                    result = main()

        self.assertEqual(result, 0)
        response = json.loads(stdout_buf.getvalue())
        self.assertFalse(response["ok"])
        self.assertIn("error_type", response)

    def test_main_returns_error_for_non_dict_request(self):
        payload = json.dumps([1, 2, 3]).encode("utf-8")
        fake_stdin = io.BytesIO(payload)
        stdout_buf = io.StringIO()

        with patch.object(sys, "stdin", new=unittest.mock.MagicMock(buffer=fake_stdin)):
            with patch.object(sys, "stdout", new=stdout_buf):
                with patch.dict("os.environ", {}, clear=False):
                    result = main()

        self.assertEqual(result, 0)
        response = json.loads(stdout_buf.getvalue())
        self.assertFalse(response["ok"])
        self.assertIn("must be an object", response["message"])


if __name__ == "__main__":
    unittest.main()
