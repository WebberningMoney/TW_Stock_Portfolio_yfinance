"""app/utils.py 的行為測試：不需要 tkinter 或資料庫。"""

from datetime import datetime
import unittest

from app.utils import tree_sort_key


class TreeSortKeyTests(unittest.TestCase):
    def test_plain_number_parses_as_amount(self):
        self.assertEqual(tree_sort_key('1234'), (0, 1234.0))

    def test_nt_prefix_and_comma_parses_as_amount(self):
        self.assertEqual(tree_sort_key('NT$ 1,234'), (0, 1234.0))

    def test_percent_suffix_parses_as_amount(self):
        self.assertEqual(tree_sort_key('12.5%'), (0, 12.5))

    def test_yuan_suffix_parses_as_amount(self):
        self.assertEqual(tree_sort_key('1,234元'), (0, 1234.0))

    def test_negative_number_parses_as_amount(self):
        self.assertEqual(tree_sort_key('-56.7'), (0, -56.7))

    def test_full_date_format_parses_as_date(self):
        self.assertEqual(
            tree_sort_key('2026-03-15'),
            (1, datetime(2026, 3, 15)),
        )

    def test_slash_full_date_format_parses_as_date(self):
        self.assertEqual(
            tree_sort_key('2026/03/15'),
            (1, datetime(2026, 3, 15)),
        )

    def test_year_month_format_parses_as_date(self):
        self.assertEqual(
            tree_sort_key('2026-03'),
            (1, datetime(2026, 3, 1)),
        )

    def test_slash_year_month_format_parses_as_date(self):
        self.assertEqual(
            tree_sort_key('2026/03'),
            (1, datetime(2026, 3, 1)),
        )

    def test_blank_string_sorts_last(self):
        self.assertEqual(tree_sort_key(''), (9, ''))

    def test_dash_placeholder_sorts_last(self):
        self.assertEqual(tree_sort_key('-'), (9, ''))

    def test_not_updated_placeholder_sorts_last(self):
        self.assertEqual(tree_sort_key('未更新'), (9, ''))

    def test_not_provided_placeholder_sorts_last(self):
        self.assertEqual(tree_sort_key('未提供'), (9, ''))

    def test_plain_text_falls_back_to_casefolded_text(self):
        self.assertEqual(tree_sort_key('Apple'), (2, 'apple'))

    def test_plain_text_is_case_insensitive(self):
        self.assertEqual(tree_sort_key('APPLE'), tree_sort_key('apple'))

    def test_category_ordering_amount_before_date_before_text_before_blank(self):
        amount_key = tree_sort_key('100')
        date_key = tree_sort_key('2026-01-01')
        text_key = tree_sort_key('元大台灣50')
        blank_key = tree_sort_key('')
        self.assertLess(amount_key[0], date_key[0])
        self.assertLess(date_key[0], text_key[0])
        self.assertLess(text_key[0], blank_key[0])


if __name__ == '__main__':
    unittest.main()
