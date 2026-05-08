import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from translator_service.admin.settings import (
    AdminSettingDefinition,
    SettingApplyMode,
    SettingValueType,
    SQLiteAdminSettingsStore,
)


class AdminSettingsTest(unittest.TestCase):
    def test_setting_round_trip_preserves_apply_mode_metadata(self):
        definition = AdminSettingDefinition(
            key="translation.max_parallel_units",
            label="Max parallel translation units",
            value_type=SettingValueType.INTEGER,
            apply_mode=SettingApplyMode.RESTART_REQUIRED,
            default_value="1",
            minimum=1,
            maximum=8,
        )
        with TemporaryDirectory() as temp_dir:
            with SQLiteAdminSettingsStore(Path(temp_dir) / "admin.sqlite3") as store:
                saved = store.set_value(definition, "4", changed_by="bootstrap-owner")
                loaded = store.get_value(definition)

        self.assertEqual(saved.value, "4")
        self.assertEqual(loaded.value, "4")
        self.assertEqual(loaded.apply_mode, SettingApplyMode.RESTART_REQUIRED)
        self.assertEqual(loaded.changed_by, "bootstrap-owner")

    def test_rejects_out_of_range_integer(self):
        definition = AdminSettingDefinition(
            key="uploads.max_mb",
            label="Max upload MB",
            value_type=SettingValueType.INTEGER,
            apply_mode=SettingApplyMode.RESTART_REQUIRED,
            default_value="50",
            minimum=1,
            maximum=100,
        )
        with SQLiteAdminSettingsStore(":memory:") as store:
            with self.assertRaises(ValueError):
                store.set_value(definition, "500", changed_by="bootstrap-owner")


if __name__ == "__main__":
    unittest.main()
