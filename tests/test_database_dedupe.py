"""SQLite 股利／分割來源整合測試。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.database import Database
from app.models import CorporateAction


class DatabaseDedupeTests(unittest.TestCase):
    def test_same_action_keeps_richer_scraper_row(self):
        with TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / 'portfolio.db')
            database.initialize()

            database.replace_actions_for_symbol(
                '0056.TW',
                [CorporateAction(
                    symbol='0056.TW',
                    stock_code='0056',
                    stock_name='元大高股息',
                    action_date='2026-07-21',
                    action_type='DIVIDEND',
                    value=1.35,
                    source='yfinance',
                )],
            )
            database.replace_scraped_dividends_for_symbol(
                '0056.TW',
                [CorporateAction(
                    symbol='0056.TW',
                    stock_code='0056',
                    stock_name='元大高股息',
                    action_date='2026-07-21',
                    action_type='DIVIDEND',
                    value=1.35,
                    source='yahoo_tw_scraper',
                    period='2026Q2',
                    payment_date='2026-08-10',
                    announcement_status='ANNOUNCED',
                )],
            )

            messages = database.consolidate_duplicate_actions_for_symbol(
                '0056.TW'
            )
            actions = database.list_actions('DIVIDEND')

            self.assertEqual(len(messages), 1)
            self.assertEqual(len(actions), 1)
            self.assertEqual(actions[0].source, 'yahoo_tw_scraper')
            self.assertEqual(actions[0].period, '2026Q2')
            self.assertEqual(actions[0].payment_date, '2026-08-10')
            self.assertIn('保留 爬蟲／Yahoo 台灣股利政策', messages[0])


if __name__ == '__main__':
    unittest.main()


def test_clear_actions_for_selected_sources(tmp_path):
    database = Database(tmp_path / 'portfolio.db')
    database.initialize()
    actions = [
        CorporateAction(
            symbol='0050.TW', stock_code='0050', stock_name='元大台灣50',
            action_date='2025-01-01', action_type='DIVIDEND', value=1.0,
            source='yfinance',
        ),
        CorporateAction(
            symbol='0050.TW', stock_code='0050', stock_name='元大台灣50',
            action_date='2026-01-01', action_type='DIVIDEND', value=2.0,
            source='yahoo_tw_scraper',
        ),
    ]
    database.replace_actions_for_symbol('0050.TW', [actions[0]])
    database.replace_scraped_dividends_for_symbol('0050.TW', [actions[1]])

    deleted = database.clear_actions_for_symbols(
        ['0050.TW'], {'yfinance'}
    )
    assert deleted == 1
    remaining = database.list_actions()
    assert len(remaining) == 1
    assert remaining[0].source == 'yahoo_tw_scraper'


def test_id_tie_break_uses_insertion_order_not_raw_value_order(tmp_path):
    """兩筆重複資料完整度、來源都相同時，該保留較晚寫入（id 較大）的
    那一筆——即使它的原始（未四捨五入）value 剛好比較小，導致 SQL 依
    value 排序時會被排到較晚寫入的那一筆前面。"""
    database = Database(tmp_path / 'portfolio.db')
    database.initialize()

    database.replace_actions_for_symbol(
        '0050.TW',
        [
            CorporateAction(
                symbol='0050.TW', stock_code='0050', stock_name='元大台灣50',
                action_date='2026-07-21', action_type='DIVIDEND',
                value=1.350000004, source='yfinance',
            ),
            CorporateAction(
                symbol='0050.TW', stock_code='0050', stock_name='元大台灣50',
                action_date='2026-07-21', action_type='DIVIDEND',
                value=1.350000001, source='yfinance',
            ),
        ],
    )

    database.consolidate_duplicate_actions_for_symbol('0050.TW')
    actions = database.list_actions('DIVIDEND')

    assert len(actions) == 1
    assert actions[0].value == 1.350000001
