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
            self.assertIn('保留 爬蟲／Yahoo 台灣已公告', messages[0])


if __name__ == '__main__':
    unittest.main()
