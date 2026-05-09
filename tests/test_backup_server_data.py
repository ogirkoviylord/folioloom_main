import importlib.util
import json
import sys
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backup_server_data.py"
SPEC = importlib.util.spec_from_file_location("backup_server_data", SCRIPT_PATH)
backup_server_data = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["backup_server_data"] = backup_server_data
SPEC.loader.exec_module(backup_server_data)


class BackupServerDataTest(unittest.TestCase):
    def test_parse_env_file_supports_quotes_comments_and_blank_values(self):
        with TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "# local secrets",
                        "OBJECT_STORAGE_ROOT='data/object-storage'",
                        'POSTGRES_DSN=\"postgresql://writer:secret@postgres:5432/books\"',
                        "TELEGRAM_BOT_TOKEN=",
                        "INVALID_LINE",
                    ]
                ),
                encoding="utf-8",
            )

            values = backup_server_data.parse_env_file(env_file)

        self.assertEqual(values["OBJECT_STORAGE_ROOT"], "data/object-storage")
        self.assertEqual(
            values["POSTGRES_DSN"],
            "postgresql://writer:secret@postgres:5432/books",
        )
        self.assertEqual(values["TELEGRAM_BOT_TOKEN"], "")
        self.assertNotIn("INVALID_LINE", values)

    def test_database_settings_prefer_postgres_dsn(self):
        settings = backup_server_data.database_settings_from_env(
            {
                "POSTGRES_DSN": "postgresql://writer:secret@postgres:5432/books",
                "POSTGRES_USER": "ignored",
                "POSTGRES_DB": "ignored",
                "POSTGRES_PASSWORD": "ignored",
            }
        )

        self.assertEqual(settings.user, "writer")
        self.assertEqual(settings.database, "books")
        self.assertEqual(settings.password, "secret")

    def test_storage_archive_name_preserves_relative_nested_storage_path(self):
        self.assertEqual(
            backup_server_data.storage_archive_name(Path("data/object-storage")),
            "data/object-storage",
        )

    def test_container_runtime_paths_map_to_host_var_directory(self):
        self.assertEqual(
            backup_server_data.host_runtime_path(Path("/data/object-storage")),
            Path("var/object-storage"),
        )
        self.assertEqual(
            backup_server_data.host_runtime_path(Path("/data/runtime/admin.sqlite3")),
            Path("var/runtime/admin.sqlite3"),
        )
        self.assertEqual(
            backup_server_data.host_runtime_path(Path("/app/var/run-logs")),
            Path("var/run-logs"),
        )

    def test_validate_backup_rejects_files_with_empty_database_by_default(self):
        with self.assertRaisesRegex(RuntimeError, "database dump looks empty"):
            backup_server_data.validate_backup_counts(
                row_counts={"translation_jobs": 0, "work_units": 0},
                storage_file_count=12,
                allow_empty_database=False,
            )

    def test_validate_backup_allows_empty_database_when_requested(self):
        backup_server_data.validate_backup_counts(
            row_counts={"translation_jobs": 0, "work_units": 0},
            storage_file_count=12,
            allow_empty_database=True,
        )

    def test_verify_manifest_rejects_hash_mismatch(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_dump = root / "folioloom-db.sql"
            files_archive = root / "folioloom-files.tgz"
            db_dump.write_text("sql", encoding="utf-8")
            files_archive.write_bytes(b"archive")
            manifest = root / "manifest.json"
            manifest.write_text(
                """
{
  "row_counts": {"translation_jobs": 1},
  "storage_file_count": 2,
  "database_dump": {"path": "folioloom-db.sql", "size_bytes": 3, "sha256": "bad"},
  "files_archive": {"path": "folioloom-files.tgz", "size_bytes": 7, "sha256": "bad"}
}
""".strip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "sha256 mismatch"):
                backup_server_data.verify_backup_manifest(
                    manifest,
                    allow_empty_database=False,
                )

    def test_verify_manifest_accepts_matching_files(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_dump = root / "folioloom-db.sql"
            files_archive = root / "folioloom-files.tgz"
            db_dump.write_text("sql", encoding="utf-8")
            files_archive.write_bytes(b"archive")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "row_counts": {"translation_jobs": 1},
                        "storage_file_count": 2,
                        "database_dump": {
                            "path": "folioloom-db.sql",
                            "size_bytes": 3,
                            "sha256": backup_server_data.sha256_file(db_dump),
                        },
                        "files_archive": {
                            "path": "folioloom-files.tgz",
                            "size_bytes": 7,
                            "sha256": backup_server_data.sha256_file(files_archive),
                        },
                    }
                ),
                encoding="utf-8",
            )

            backup_server_data.verify_backup_manifest(
                manifest,
                allow_empty_database=False,
            )

    def test_archive_runtime_files_includes_admin_sqlite_next_to_object_storage(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_root = root / "var" / "object-storage"
            storage_root.mkdir(parents=True)
            (storage_root / "book.txt").write_text("translated", encoding="utf-8")
            admin_db_path = root / "var" / "admin.sqlite3"
            admin_db_path.write_bytes(b"sqlite")
            archive_path = root / "runtime-files.tgz"

            backup_server_data.archive_runtime_files(
                storage_root=storage_root,
                admin_db_path=admin_db_path,
                output_path=archive_path,
            )

            with tarfile.open(archive_path, "r:gz") as archive:
                names = set(archive.getnames())

        self.assertIn("var/object-storage/book.txt", names)
        self.assertIn("var/admin.sqlite3", names)

    def test_archive_runtime_files_preserves_var_root_for_runtime_subdirectories(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            storage_root = root / "var" / "object-storage"
            storage_root.mkdir(parents=True)
            (storage_root / "book.txt").write_text("translated", encoding="utf-8")
            run_log = root / "var" / "run-logs" / "run-1" / "run.json"
            run_log.parent.mkdir(parents=True)
            run_log.write_text("{}", encoding="utf-8")
            user_settings = root / "var" / "runtime" / "user-settings.sqlite3"
            admin_db_path = root / "var" / "runtime" / "admin.sqlite3"
            admin_db_path.parent.mkdir(parents=True)
            admin_db_path.write_bytes(b"sqlite")
            user_settings.write_bytes(b"settings")
            archive_path = root / "runtime-files.tgz"

            backup_server_data.archive_runtime_files(
                storage_root=storage_root,
                admin_db_path=admin_db_path,
                output_path=archive_path,
            )

            with tarfile.open(archive_path, "r:gz") as archive:
                names = set(archive.getnames())

        self.assertIn("var/object-storage/book.txt", names)
        self.assertIn("var/run-logs/run-1/run.json", names)
        self.assertIn("var/runtime/admin.sqlite3", names)
        self.assertIn("var/runtime/user-settings.sqlite3", names)

    def test_verify_manifest_rejects_runtime_archive_without_admin_sqlite(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_dump = root / "folioloom-db.sql"
            files_archive = root / "folioloom-files.tgz"
            db_dump.write_text("sql", encoding="utf-8")
            object_storage = root / "var" / "object-storage"
            object_storage.mkdir(parents=True)
            (object_storage / "book.txt").write_text("translated", encoding="utf-8")
            with tarfile.open(files_archive, "w:gz") as archive:
                archive.add(object_storage, arcname="var/object-storage")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "row_counts": {"translation_jobs": 1},
                        "storage_file_count": 1,
                        "admin_db_path": "var/admin.sqlite3",
                        "database_dump": {
                            "path": "folioloom-db.sql",
                            "size_bytes": 3,
                            "sha256": backup_server_data.sha256_file(db_dump),
                        },
                        "files_archive": {
                            "path": "folioloom-files.tgz",
                            "size_bytes": files_archive.stat().st_size,
                            "sha256": backup_server_data.sha256_file(files_archive),
                        },
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "admin.sqlite3"):
                backup_server_data.verify_backup_manifest(
                    manifest,
                    allow_empty_database=False,
                )


if __name__ == "__main__":
    unittest.main()
