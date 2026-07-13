"""不需網路即可執行的基本服務測試。"""

import unittest

from app.models import CorporateAction, Holding
from app.services.dividend_service import build_dividend_projection, summarize_monthly
from app.services.portfolio_service import build_holding_views, summarize_portfolio


class ServiceTests(unittest.TestCase):
    def test_portfolio_calculation(self):
        holding = Holding(None, '0050', '0050.TW', '元大台灣50', 'TWSE', 1000, 150000.0)
        views = build_holding_views([holding], {
            '0050.TW': {'close': 160.0, 'trade_date': '2026-07-10'}
        })
        self.assertEqual(views[0].market_value, 160000.0)
        self.assertAlmostEqual(views[0].return_rate, 6.666666, places=4)
        summary = summarize_portfolio(views)
        self.assertEqual(summary.total_profit, 10000.0)

    def test_dividend_projection_uses_actual_and_template(self):
        holding = Holding(None, '0056', '0056.TW', '元大高股息', 'TWSE', 1000, 35000.0)
        actions = [
            CorporateAction('0056.TW', '0056', '元大高股息', '2025-01-17', 'DIVIDEND', 1.0),
            CorporateAction('0056.TW', '0056', '元大高股息', '2025-04-17', 'DIVIDEND', 1.0),
            CorporateAction('0056.TW', '0056', '元大高股息', '2026-01-16', 'DIVIDEND', 1.1),
        ]
        result = build_dividend_projection([holding], actions, 2026)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].estimated_amount, 1100.0)
        monthly = dict(summarize_monthly(result, 2026))
        self.assertEqual(monthly['2026-04'], 1000.0)


if __name__ == '__main__':
    unittest.main()
