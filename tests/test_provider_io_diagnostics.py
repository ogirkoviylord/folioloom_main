import unittest

from translator_service.provider_io_diagnostics import (
    _bytes_payload,
    _safe_error_payload,
    capture_provider_io,
    record_provider_io_exchange,
)


class CaptureProviderIOTest(unittest.TestCase):
    def test_no_op_when_sink_is_none(self):
        with capture_provider_io(None, job_id="job-1"):
            record_provider_io_exchange(
                provider_id="test",
                url="https://example.com",
                request_body=b"{}",
            )

    def test_captures_exchange_inside_context(self):
        records: list[dict] = []

        with capture_provider_io(
            records.append, job_id="job-1", work_unit_id="wu-1", sequence=0
        ):
            record_provider_io_exchange(
                provider_id="deepseek",
                url="https://api.deepseek.com/v1/chat",
                request_body=b'{"text": "hello"}',
                http_status=200,
                response_body=b'{"result": "translated"}',
            )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["provider_id"], "deepseek")
        self.assertEqual(record["job_id"], "job-1")
        self.assertEqual(record["work_unit_id"], "wu-1")
        self.assertEqual(record["sequence"], 0)
        self.assertEqual(record["http_status"], 200)
        self.assertEqual(record["schema_version"], "provider-io-diagnostics-v1")

    def test_exchange_not_captured_outside_context(self):
        records: list[dict] = []

        with capture_provider_io(records.append, job_id="job-1"):
            pass

        record_provider_io_exchange(
            provider_id="test",
            url="https://example.com",
            request_body=b"{}",
        )

        self.assertEqual(len(records), 0)

    def test_nested_capture_restores_previous_context(self):
        outer_records: list[dict] = []
        inner_records: list[dict] = []

        with capture_provider_io(outer_records.append, job_id="outer-job"):
            record_provider_io_exchange(
                provider_id="p1",
                url="https://example.com/1",
                request_body=b"outer-req",
            )

            with capture_provider_io(inner_records.append, job_id="inner-job"):
                record_provider_io_exchange(
                    provider_id="p2",
                    url="https://example.com/2",
                    request_body=b"inner-req",
                )

            record_provider_io_exchange(
                provider_id="p3",
                url="https://example.com/3",
                request_body=b"after-inner",
            )

        self.assertEqual(len(inner_records), 1)
        self.assertEqual(inner_records[0]["job_id"], "inner-job")
        self.assertEqual(len(outer_records), 2)
        self.assertEqual(outer_records[0]["job_id"], "outer-job")
        self.assertEqual(outer_records[1]["job_id"], "outer-job")

    def test_exchange_with_error(self):
        records: list[dict] = []

        with capture_provider_io(records.append, job_id="job-err"):
            record_provider_io_exchange(
                provider_id="test",
                url="https://example.com",
                request_body=b"{}",
                error=ConnectionError("connection reset"),
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["error"]["type"], "ConnectionError")
        self.assertIn("connection reset", records[0]["error"]["message"])

    def test_exchange_with_transport_attempt(self):
        records: list[dict] = []

        with capture_provider_io(records.append, job_id="job-1"):
            record_provider_io_exchange(
                provider_id="test",
                url="https://example.com",
                request_body=b"{}",
                transport_attempt=2,
            )

        self.assertEqual(records[0]["transport_attempt"], 2)

    def test_sink_failure_is_swallowed(self):
        def failing_sink(record):
            raise RuntimeError("sink broken")

        with capture_provider_io(failing_sink, job_id="job-1"):
            record_provider_io_exchange(
                provider_id="test",
                url="https://example.com",
                request_body=b"{}",
            )

    def test_no_op_when_job_id_empty(self):
        records: list[dict] = []

        with capture_provider_io(records.append, job_id=""):
            record_provider_io_exchange(
                provider_id="test",
                url="https://example.com",
                request_body=b"{}",
            )

        self.assertEqual(len(records), 0)


class BytesPayloadTest(unittest.TestCase):
    def test_utf8_payload(self):
        result = _bytes_payload(b"Hello world")
        self.assertEqual(result["text"], "Hello world")
        self.assertEqual(result["encoding"], "utf-8")
        self.assertEqual(result["byte_count"], 11)
        self.assertIn("sha256", result)

    def test_binary_payload_uses_base64(self):
        data = bytes(range(256))
        result = _bytes_payload(data)
        self.assertNotIn("text", result)
        self.assertEqual(result["encoding"], "base64")
        self.assertIn("base64", result)
        self.assertEqual(result["byte_count"], 256)
        self.assertIn("sha256", result)


class SafeErrorPayloadTest(unittest.TestCase):
    def test_captures_error_type_and_message(self):
        error = ValueError("invalid value")
        result = _safe_error_payload(error)
        self.assertEqual(result["type"], "ValueError")
        self.assertEqual(result["message"], "invalid value")

    def test_captures_custom_exception(self):
        class CustomError(Exception):
            pass

        result = _safe_error_payload(CustomError("custom msg"))
        self.assertEqual(result["type"], "CustomError")
        self.assertEqual(result["message"], "custom msg")


if __name__ == "__main__":
    unittest.main()
