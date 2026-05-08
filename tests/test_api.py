import unittest

from translator_service.api import health_payload


class ApiTest(unittest.TestCase):
    def test_healthcheck_payload_returns_service_status(self):
        self.assertEqual(
            health_payload(),
            {
                "service": "DeepSeek Document Translator",
                "status": "ok",
            },
        )


if __name__ == "__main__":
    unittest.main()
