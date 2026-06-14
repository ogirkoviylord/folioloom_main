import json
import socketserver
import threading
import unittest
from io import StringIO
from unittest.mock import patch

from translator_service.clamd_runtime import (
    ClamdRuntimeCheckError,
    _parse_version,
    _sanitize_metadata_text,
    check_clamd_runtime,
    main,
    parse_args,
)


class _CommandClamdServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(
        self,
        responses: dict[bytes, bytes],
        *,
        instream_response: bytes = b"stream: OK\0",
    ):
        self.responses = responses
        self.instream_response = instream_response
        self.stream = b""
        super().__init__(("127.0.0.1", 0), _CommandClamdHandler)

    def __enter__(self):
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=1)


class _CommandClamdHandler(socketserver.BaseRequestHandler):
    def handle(self):
        command = bytearray()
        while not command.endswith(b"\0"):
            part = self.request.recv(1)
            if not part:
                return
            command.extend(part)
        if bytes(command) == b"zINSTREAM\0":
            self.server.stream = self._read_instream()
            self.request.sendall(self.server.instream_response)
            return
        self.request.sendall(self.server.responses.get(bytes(command), b"ERROR\0"))

    def _read_instream(self) -> bytes:
        stream = bytearray()
        while True:
            size_bytes = self._read_exact(4)
            if len(size_bytes) < 4:
                return bytes(stream)
            chunk_size = int.from_bytes(size_bytes, "big")
            if chunk_size == 0:
                return bytes(stream)
            stream.extend(self._read_exact(chunk_size))

    def _read_exact(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            part = self.request.recv(size - len(chunks))
            if not part:
                break
            chunks.extend(part)
        return bytes(chunks)


class ClamdRuntimeCheckTest(unittest.TestCase):
    def test_check_clamd_runtime_returns_safe_version_metadata(self):
        with _CommandClamdServer(
            {
                b"zPING\0": b"PONG\0",
                b"zVERSION\0": b"ClamAV 1.4.0/27500/Tue May 26 10:00:00 2026\0",
            }
        ) as server:
            status = check_clamd_runtime(
                host=server.server_address[0],
                port=server.server_address[1],
                timeout_seconds=0.5,
            )

        self.assertEqual(status.status, "ok")
        self.assertEqual(status.scanner_name, "clamd")
        self.assertEqual(status.scanner_version, "ClamAV 1.4.0")
        self.assertEqual(status.signature_database_version, "27500")
        metadata = status.safe_metadata()
        self.assertEqual(metadata["status"], "ok")
        self.assertNotIn("stream:", str(metadata))

    def test_check_clamd_runtime_can_verify_eicar_detection(self):
        with _CommandClamdServer(
            {
                b"zPING\0": b"PONG\0",
                b"zVERSION\0": b"ClamAV 1.4.0/27500/Tue May 26 10:00:00 2026\0",
            },
            instream_response=b"stream: Eicar-Test-Signature FOUND\0",
        ) as server:
            status = check_clamd_runtime(
                host=server.server_address[0],
                port=server.server_address[1],
                timeout_seconds=0.5,
                scan_eicar=True,
            )

        self.assertEqual(status.eicar_verdict, "infected")
        self.assertIn(b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE", server.stream)
        metadata = status.safe_metadata()
        self.assertEqual(metadata["eicar_verdict"], "infected")
        self.assertNotIn("Eicar-Test-Signature", str(metadata))
        self.assertNotIn("stream:", str(metadata))

    def test_check_clamd_runtime_rejects_missing_eicar_detection(self):
        with _CommandClamdServer(
            {
                b"zPING\0": b"PONG\0",
                b"zVERSION\0": b"ClamAV 1.4.0/27500/Tue May 26 10:00:00 2026\0",
            },
            instream_response=b"stream: OK\0",
        ) as server:
            with self.assertRaises(ClamdRuntimeCheckError):
                check_clamd_runtime(
                    host=server.server_address[0],
                    port=server.server_address[1],
                    timeout_seconds=0.5,
                    scan_eicar=True,
                )

    def test_check_clamd_runtime_rejects_non_pong_response(self):
        with _CommandClamdServer({b"zPING\0": b"NOPE\0"}) as server:
            with self.assertRaises(ClamdRuntimeCheckError):
                check_clamd_runtime(
                    host=server.server_address[0],
                    port=server.server_address[1],
                    timeout_seconds=0.5,
                )


    def test_check_clamd_runtime_raises_on_connection_refused(self):
        with self.assertRaises(ClamdRuntimeCheckError):
            check_clamd_runtime(
                host="127.0.0.1",
                port=1,
                timeout_seconds=0.1,
            )

    def test_check_clamd_runtime_raises_on_empty_response(self):
        with _CommandClamdServer({b"zPING\0": b""}) as server:
            with self.assertRaises(ClamdRuntimeCheckError):
                check_clamd_runtime(
                    host=server.server_address[0],
                    port=server.server_address[1],
                    timeout_seconds=0.5,
                )


class ParseVersionTest(unittest.TestCase):
    def test_parses_full_version_string(self):
        scanner, sig = _parse_version("ClamAV 1.4.0/27500/date")
        self.assertEqual(scanner, "ClamAV 1.4.0")
        self.assertEqual(sig, "27500")

    def test_parses_version_without_signature(self):
        scanner, sig = _parse_version("ClamAV 1.4.0")
        self.assertEqual(scanner, "ClamAV 1.4.0")
        self.assertIsNone(sig)

    def test_returns_none_for_empty_version(self):
        scanner, sig = _parse_version("")
        self.assertIsNone(scanner)
        self.assertIsNone(sig)


class SanitizeMetadataTextTest(unittest.TestCase):
    def test_strips_control_characters(self):
        result = _sanitize_metadata_text("hello\x00world\x01!")
        self.assertEqual(result, "helloworld!")

    def test_truncates_long_text(self):
        result = _sanitize_metadata_text("a" * 200, limit=50)
        self.assertEqual(len(result), 50)


class ParseArgsTest(unittest.TestCase):
    def test_default_args(self):
        args = parse_args([])
        self.assertEqual(args.host, "clamd")
        self.assertEqual(args.port, 3310)
        self.assertEqual(args.timeout, 10.0)
        self.assertEqual(args.response_limit_bytes, 4096)
        self.assertFalse(args.scan_eicar)

    def test_custom_args(self):
        args = parse_args([
            "--host", "localhost",
            "--port", "9999",
            "--timeout", "5.0",
            "--response-limit-bytes", "2048",
            "--scan-eicar",
        ])
        self.assertEqual(args.host, "localhost")
        self.assertEqual(args.port, 9999)
        self.assertEqual(args.timeout, 5.0)
        self.assertEqual(args.response_limit_bytes, 2048)
        self.assertTrue(args.scan_eicar)


class ClamdMainTest(unittest.TestCase):
    def test_main_returns_zero_on_success(self):
        with _CommandClamdServer(
            {
                b"zPING\0": b"PONG\0",
                b"zVERSION\0": b"ClamAV 1.4.0/27500/date\0",
            }
        ) as server:
            host, port = server.server_address
            result = main([
                "--host", host,
                "--port", str(port),
                "--timeout", "1.0",
            ])
        self.assertEqual(result, 0)

    def test_main_returns_one_on_failure(self):
        result = main(["--host", "127.0.0.1", "--port", "1", "--timeout", "0.1"])
        self.assertEqual(result, 1)

    def test_main_prints_json_on_success(self):
        with _CommandClamdServer(
            {
                b"zPING\0": b"PONG\0",
                b"zVERSION\0": b"ClamAV 1.4.0/27500/date\0",
            }
        ) as server:
            host, port = server.server_address
            buf = StringIO()
            with patch("sys.stdout", new=buf):
                main([
                    "--host", host,
                    "--port", str(port),
                    "--timeout", "1.0",
                ])
            output = json.loads(buf.getvalue())
            self.assertEqual(output["status"], "ok")
            self.assertEqual(output["scanner_name"], "clamd")


if __name__ == "__main__":
    unittest.main()
