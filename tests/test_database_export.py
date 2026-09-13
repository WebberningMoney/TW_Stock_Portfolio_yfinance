"""Database.export_table_csv() 的匯出行為測試。"""

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.database import Database
from app.models import CorporateAction, Instrument, MarketQuote


class DatabaseExportTableCsvTests(unittest.TestCase):
    def _database(self, tmp: str) -> Database:
        database = Database(Path(tmp) / 'portfolio.db')
        database.initialize()
        return database

    def test_exports_instruments_table(self):
        with TemporaryDirectory() as tmp:
            database = self._database(tmp)
            database.upsert_instruments([
                Instrument(
                    symbol='0050.TW',
                    stock_code='0050',
                    name='元大台灣50',
                ),
            ])
            out_path = Path(tmp) / 'instruments.csv'

            count = database.export_table_csv('instruments', out_path)

            self.assertEqual(count, 1)
            with out_path.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['symbol'], '0050.TW')
            self.assertEqual(rows[0]['name'], '元大台灣50')

    def test_exports_quotes_table(self):
        with TemporaryDirectory() as tmp:
            database = self._database(tmp)
            database.upsert_quotes([
                MarketQuote(
                    symbol='0050.TW',
                    stock_code='0050',
                    name='元大台灣50',
                    close=160.0,
                    previous_close=157.5,
                    change=2.5,
                    change_percent=1.5,
                    volume=1000.0,
                    trade_date='2026-07-10',
                    currency='TWD',
                ),
            ])
            out_path = Path(tmp) / 'quotes.csv'

            count = database.export_table_csv('quotes', out_path)

            self.assertEqual(count, 1)
            with out_path.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['symbol'], '0050.TW')
            self.assertEqual(rows[0]['close'], '160.0')

    def test_exports_actions_table(self):
        with TemporaryDirectory() as tmp:
            database = self._database(tmp)
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
            out_path = Path(tmp) / 'actions.csv'

            count = database.export_table_csv('actions', out_path)

            self.assertEqual(count, 1)
            with out_path.open(encoding='utf-8-sig', newline='') as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['symbol'], '0056.TW')
            self.assertEqual(rows[0]['action_type'], 'DIVIDEND')

    def test_unknown_table_raises_value_error(self):
        with TemporaryDirectory() as tmp:
            database = self._database(tmp)
            out_path = Path(tmp) / 'unknown.csv'

            with self.assertRaises(ValueError) as ctx:
                database.export_table_csv('unknown', out_path)

            self.assertIn('unknown', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
