import socket
import socketserver
import threading
import time
import unittest
from hashlib import sha256

from translator_service import document_scanner
from translator_service.documents import DocumentFormat


class _FakeClamdServer(socketserver.TCPServer):
    allow_reuse_address = True

    def __init__(self, response: bytes, *, response_delay_seconds: float = 0.0):
        self.response = response
        self.response_delay_seconds = response_delay_seconds
        self.command = b""
        self.stream = b""
        self.chunk_sizes: list[int] = []
        super().__init__(("127.0.0.1", 0), _FakeClamdHandler)

    def __enter__(self):
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=1)


class _FakeClamdHandler(socketserver.BaseRequestHandler):
    def handle(self):
        command = bytearray()
        while not command.endswith(b"\0"):
            next_byte = self.request.recv(1)
            if not next_byte:
                return
            command.extend(next_byte)

        stream = bytearray()
        chunk_sizes: list[int] = []
        while True:
            size_bytes = self._read_exact(4)
            if len(size_bytes) < 4:
                return
            chunk_size = int.from_bytes(size_bytes, "big")
            if chunk_size == 0:
                break
            chunk = self._read_exact(chunk_size)
            if len(chunk) < chunk_size:
                return
            chunk_sizes.append(chunk_size)
            stream.extend(chunk)

        self.server.command = bytes(command)
        self.server.stream = bytes(stream)
        self.server.chunk_sizes = chunk_sizes

        if self.server.response_delay_seconds:
            time.sleep(self.server.response_delay_seconds)
        self.request.sendall(self.server.response)

    def _read_exact(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            part = self.request.recv(size - len(chunks))
            if not part:
                break
            chunks.extend(part)
        return bytes(chunks)


class ClamdDocumentScannerTest(unittest.TestCase):
    def _scanner_cls(self):
        scanner_cls = getattr(document_scanner, "ClamdDocumentScanner", None)
        self.assertIsNotNone(scanner_cls, "ClamdDocumentScanner should exist")
        return scanner_cls

    def _scanner_for_server(self, server: _FakeClamdServer, **kwargs):
        return self._scanner_cls()(
            host=server.server_address[0],
            port=server.server_address[1],
            timeout_seconds=kwargs.pop("timeout_seconds", 0.5),
            **kwargs,
        )

    def test_clean_response_uses_instream_and_returns_clean_contract_verdict(self):
        content = b"safe upload bytes"
        with _FakeClamdServer(b"stream: OK\0") as server:
            scanner = self._scanner_for_server(server, chunk_size=4)

            result = scanner.scan(
                file_name="../private-notes.txt",
                content=content,
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(result.verdict, document_scanner.ScannerVerdict.CLEAN)
        self.assertEqual(result.scanner_name, "clamd")
        self.assertEqual(result.scanner_version, None)
        self.assertEqual(result.signature_database_version, None)
        self.assertEqual(result.content_sha256, sha256(content).hexdigest())
        self.assertEqual(result.size_bytes, len(content))
        self.assertEqual(result.document_format, DocumentFormat.TXT)
        self.assertEqual(result.safe_error_class, None)
        self.assertEqual(server.command, b"zINSTREAM\0")
        self.assertEqual(server.stream, content)
        self.assertEqual(server.chunk_sizes, [4, 4, 4, 4, 1])
        self.assertNotIn(b"private-notes.txt", server.command)

    def test_infected_response_fails_closed_without_exposing_raw_signature(self):
        with _FakeClamdServer(b"stream: Eicar-Test-Signature FOUND\0") as server:
            scanner = self._scanner_for_server(server)

            result = scanner.scan(
                file_name="eicar.txt",
                content=b"safe eicar placeholder",
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(result.verdict, document_scanner.ScannerVerdict.INFECTED)
        self.assertEqual(result.safe_error_class, "infected")
        metadata = result.safe_metadata()
        self.assertNotIn("Eicar-Test-Signature", str(metadata))
        self.assertNotIn("stream:", str(metadata))
        self.assertEqual(server.stream, b"safe eicar placeholder")

    def test_unavailable_connection_fails_closed(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            unused_port = sock.getsockname()[1]

        scanner = self._scanner_cls()(
            host="127.0.0.1",
            port=unused_port,
            timeout_seconds=0.1,
        )

        result = scanner.scan(
            file_name="notes.txt",
            content=b"safe bytes",
            document_format=DocumentFormat.TXT,
        )

        self.assertEqual(
            result.verdict,
            document_scanner.ScannerVerdict.SCANNER_UNAVAILABLE,
        )
        self.assertEqual(result.safe_error_class, "scanner_unavailable")

    def test_timeout_fails_closed(self):
        with _FakeClamdServer(
            b"stream: OK\0",
            response_delay_seconds=0.25,
        ) as server:
            scanner = self._scanner_for_server(server, timeout_seconds=0.05)

            result = scanner.scan(
                file_name="slow.txt",
                content=b"safe bytes",
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(
            result.verdict,
            document_scanner.ScannerVerdict.SCANNER_TIMEOUT,
        )
        self.assertEqual(result.safe_error_class, "scanner_timeout")

    def test_malformed_response_fails_closed_with_safe_error_class(self):
        with _FakeClamdServer(b"unexpected raw response\0") as server:
            scanner = self._scanner_for_server(server)

            result = scanner.scan(
                file_name="notes.txt",
                content=b"safe bytes",
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(result.verdict, document_scanner.ScannerVerdict.SCANNER_ERROR)
        self.assertEqual(result.safe_error_class, "malformed_response")
        self.assertNotIn("unexpected raw response", str(result.safe_metadata()))

    def test_unterminated_z_response_fails_closed(self):
        with _FakeClamdServer(b"stream: OK") as server:
            scanner = self._scanner_for_server(server)

            result = scanner.scan(
                file_name="notes.txt",
                content=b"safe bytes",
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(result.verdict, document_scanner.ScannerVerdict.SCANNER_ERROR)
        self.assertEqual(result.safe_error_class, "malformed_response")

    def test_scanner_error_response_fails_closed(self):
        with _FakeClamdServer(
            b"stream: INSTREAM size limit exceeded ERROR\0"
        ) as server:
            scanner = self._scanner_for_server(server)

            result = scanner.scan(
                file_name="large.txt",
                content=b"safe bytes",
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(result.verdict, document_scanner.ScannerVerdict.SCANNER_ERROR)
        self.assertEqual(result.safe_error_class, "scanner_error")
        self.assertNotIn("INSTREAM size limit exceeded", str(result.safe_metadata()))

    def test_unsupported_response_fails_closed(self):
        with _FakeClamdServer(b"stream: unsupported file type UNSUPPORTED\0") as server:
            scanner = self._scanner_for_server(server)

            result = scanner.scan(
                file_name="notes.txt",
                content=b"safe bytes",
                document_format=DocumentFormat.TXT,
            )

        self.assertEqual(result.verdict, document_scanner.ScannerVerdict.UNSUPPORTED)
        self.assertEqual(result.safe_error_class, "unsupported")


class LimitedConcurrencyDocumentScannerTest(unittest.TestCase):
    def test_backpressure_returns_fail_closed_scanner_unavailable(self):
        blocker = threading.Event()
        entered = threading.Event()
        scanner = document_scanner.LimitedConcurrencyDocumentScanner(
            _BlockingScanner(blocker=blocker, entered=entered),
            max_concurrent_scans=1,
            acquire_timeout_seconds=0.01,
            scanner_name="clamd",
        )
        thread = threading.Thread(
            target=lambda: scanner.scan(
                file_name="first.txt",
                content=b"first",
                document_format=DocumentFormat.TXT,
            ),
            daemon=True,
        )
        thread.start()
        self.assertTrue(entered.wait(timeout=1))

        result = scanner.scan(
            file_name="second.txt",
            content=b"second",
            document_format=DocumentFormat.TXT,
        )

        blocker.set()
        thread.join(timeout=1)
        self.assertEqual(
            result.verdict,
            document_scanner.ScannerVerdict.SCANNER_UNAVAILABLE,
        )
        self.assertEqual(result.scanner_name, "clamd")
        self.assertEqual(result.safe_error_class, "scanner_backpressure")
        self.assertNotIn("second", str(result.safe_metadata()))


class _BlockingScanner:
    def __init__(self, *, blocker: threading.Event, entered: threading.Event):
        self._blocker = blocker
        self._entered = entered

    def scan(self, *, file_name, content, document_format):
        del file_name
        self._entered.set()
        self._blocker.wait(timeout=1)
        return document_scanner.ScanResult(
            verdict=document_scanner.ScannerVerdict.CLEAN,
            scanner_name="blocking",
            scanner_version=None,
            signature_database_version=None,
            content_sha256=sha256(content).hexdigest(),
            size_bytes=len(content),
            document_format=document_format,
        )


if __name__ == "__main__":
    unittest.main()
