import unittest
from tempfile import TemporaryDirectory

from translator_service.api import health_payload, readiness_payload
from translator_service.config import Settings


class ApiTest(unittest.TestCase):
    def test_healthcheck_payload_returns_service_status(self):
        self.assertEqual(
            health_payload(),
            {
                "service": "DeepSeek Document Translator",
                "status": "ok",
            },
        )

    def test_health_payload_uses_supplied_service_name(self):
        self.assertEqual(
            health_payload(Settings(service_name="FolioLoom")),
            {
                "service": "FolioLoom",
                "status": "ok",
            },
        )

    def test_readiness_checks_object_storage_and_job_store(self):
        with TemporaryDirectory() as temp_dir:
            payload = readiness_payload(
                Settings(
                    service_name="FolioLoom",
                    object_storage_root=temp_dir,
                    job_store_backend="sqlite",
                    persistent_jobs_db_path=":memory:",
                )
            )

        self.assertEqual(
            payload,
            {
                "service": "FolioLoom",
                "status": "ready",
                "object_storage": "ok",
                "job_store": "ok",
            },
        )


if __name__ == "__main__":
    unittest.main()
