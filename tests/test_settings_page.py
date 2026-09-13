"""settings_page.py 的 _SETTING_FIELDS 表格一致性測試：不需要建立 Tk 視窗或 mainloop。"""

import dataclasses
import unittest

from app.settings import RuntimeSettings
from app.ui.mixins.settings_page import _SETTING_FIELDS


class SettingFieldsTests(unittest.TestCase):
    def test_setting_fields_cover_every_runtime_settings_field(self):
        table_names = {field.name for field in _SETTING_FIELDS}
        hand_written_names = {'dividend_source_mode', 'enable_price_repair'}
        runtime_settings_names = {
            field.name for field in dataclasses.fields(RuntimeSettings)
        }
        self.assertEqual(
            table_names | hand_written_names,
            runtime_settings_names,
        )

    def test_parse_and_format_round_trip_to_the_same_type_as_the_default(self):
        defaults = RuntimeSettings()
        for field in _SETTING_FIELDS:
            default_value = getattr(defaults, field.name)
            round_tripped = field.parse(field.format(default_value))
            self.assertIs(
                type(round_tripped),
                type(default_value),
                msg=(
                    f'{field.name}: parse/format 型別配對錯誤，'
                    f'預設值型別為 {type(default_value).__name__}，'
                    f'round-trip 後變成 {type(round_tripped).__name__}'
                ),
            )


if __name__ == '__main__':
    unittest.main()
