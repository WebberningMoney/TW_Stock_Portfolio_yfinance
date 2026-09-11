"""市場報價（market_quotes）讀寫的 round-trip 測試。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.db.database import Database
from app.models import MarketQuote


class DatabaseQuoteMapTests(unittest.TestCase):
    def _quote(self, symbol='0050.TW', close=160.0, change=2.5, **overrides):
        defaults = dict(
            symbol=symbol,
            stock_code='0050',
            name='元大台灣50',
            close=close,
            previous_close=close - change,
            change=change,
            change_percent=1.5,
            volume=1000.0,
            trade_date='2026-07-10',
            currency='TWD',
        )
        defaults.update(overrides)
        return MarketQuote(**defaults)

    def test_get_quote_map_round_trips_as_market_quote(self):
        with TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / 'portfolio.db')
            database.initialize()

            database.upsert_quotes([self._quote()])
            quote_map = database.get_quote_map()

            quote = quote_map['0050.TW']
            self.assertIsInstance(quote, MarketQuote)
            self.assertEqual(quote.close, 160.0)
            self.assertEqual(quote.change, 2.5)
            self.assertEqual(quote.trade_date, '2026-07-10')


if __name__ == '__main__':
    unittest.main()
