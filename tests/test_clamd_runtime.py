import socketserver
import threading
import unittest

from translator_service.clamd_runtime import (
    ClamdRuntimeCheckError,
    check_clamd_runtime,
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


if __name__ == "__main__":
    unittest.main()
