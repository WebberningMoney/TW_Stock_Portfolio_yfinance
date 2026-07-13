"""不需網路即可執行的基本服務測試。"""

import unittest
from datetime import date

from app.models import CorporateAction, Holding
from app.services.dividend_service import (
    PENDING,
    REALIZED,
    build_dividend_projection,
    summarize_monthly,
    summarize_year,
)
from app.services.portfolio_service import (
    build_holding_views,
    summarize_portfolio,
)


class ServiceTests(unittest.TestCase):
    def test_portfolio_calculation(self):
        holding = Holding(
            None,
            '0050',
            '0050.TW',
            '元大台灣50',
            'TWSE',
            1000,
            150000.0,
        )
        views = build_holding_views(
            [holding],
            {'0050.TW': {'close': 160.0, 'trade_date': '2026-07-10'}},
        )
        self.assertEqual(views[0].market_value, 160000.0)
        self.assertAlmostEqual(views[0].return_rate, 6.666666, places=4)
        summary = summarize_portfolio(views)
        self.assertEqual(summary.total_profit, 10000.0)

    def test_dividend_projection_separates_realized_and_pending(self):
        holding = Holding(
            None,
            '0056',
            '0056.TW',
            '元大高股息',
            'TWSE',
            1000,
            35000.0,
        )
        actions = [
            CorporateAction(
                '0056.TW', '0056', '元大高股息',
                '2025-01-17', 'DIVIDEND', 1.0,
            ),
            CorporateAction(
                '0056.TW', '0056', '元大高股息',
                '2025-04-17', 'DIVIDEND', 1.0,
            ),
            CorporateAction(
                '0056.TW', '0056', '元大高股息',
                '2026-01-16', 'DIVIDEND', 1.1,
            ),
        ]
        result = build_dividend_projection(
            [holding],
            actions,
            2026,
            as_of_date=date(2026, 1, 20),
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].status, REALIZED)
        self.assertEqual(result[0].estimated_amount, 1100.0)
        self.assertEqual(result[1].status, PENDING)

        monthly = {item.month: item for item in summarize_monthly(result, 2026)}
        self.assertEqual(monthly['2026-01'].realized_amount, 1100.0)
        self.assertEqual(monthly['2026-04'].pending_amount, 1000.0)

        yearly = summarize_year(result)
        self.assertEqual(yearly.realized_amount, 1100.0)
        self.assertEqual(yearly.pending_amount, 1000.0)
        self.assertEqual(yearly.total_amount, 2100.0)

    def test_past_year_does_not_add_estimates(self):
        holding = Holding(
            None, '2330', '2330.TW', '台積電', 'TWSE', 100, 100000.0
        )
        actions = [
            CorporateAction(
                '2330.TW', '2330', '台積電',
                '2024-03-18', 'DIVIDEND', 3.0,
            ),
            CorporateAction(
                '2330.TW', '2330', '台積電',
                '2025-03-18', 'DIVIDEND', 4.0,
            ),
        ]
        result = build_dividend_projection(
            [holding], actions, 2024, as_of_date=date(2026, 7, 14)
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, REALIZED)
        self.assertEqual(result[0].estimated_amount, 300.0)


if __name__ == '__main__':
    unittest.main()
