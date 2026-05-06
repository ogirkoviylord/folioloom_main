import unittest


from translator_service.config import Settings


class SettingsTest(unittest.TestCase):
    def test_settings_have_safe_development_defaults(self):
        settings = Settings()

        self.assertEqual(settings.service_name, "DeepSeek Document Translator")
        self.assertEqual(settings.environment, "development")
        self.assertEqual(settings.max_upload_mb, 50)
        self.assertEqual(settings.deepseek_model, "deepseek-v4-flash")
        self.assertEqual(settings.object_storage_root, "var/object-storage")
        self.assertEqual(settings.persistent_jobs_db_path, "var/jobs.sqlite3")


if __name__ == "__main__":
    unittest.main()
