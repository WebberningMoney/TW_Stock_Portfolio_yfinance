"""不需網路即可執行的基本服務測試。"""

import unittest
from datetime import date

from app.models import CorporateAction, Holding
from app.services.dividend_service import (
    PENDING,
    REALIZED,
    build_dividend_projection,
    summarize_monthly,
    summarize_quarterly,
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
        # 由最近的季配間隔判斷為季配，因此會用 2026/01 最近一期的
        # 1.1 元，往後估算 4、7、10 月，而不是套用去年同季的 1.0 元。
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0].status, REALIZED)
        self.assertEqual(result[0].estimated_amount, 1100.0)
        self.assertTrue(all(item.status == PENDING for item in result[1:]))

        monthly = {item.month: item for item in summarize_monthly(result, 2026)}
        self.assertEqual(monthly['2026-01'].realized_amount, 1100.0)
        self.assertEqual(monthly['2026-04'].pending_amount, 1100.0)
        self.assertEqual(monthly['2026-07'].pending_amount, 1100.0)
        self.assertEqual(monthly['2026-10'].pending_amount, 1100.0)

        yearly = summarize_year(result)
        self.assertEqual(yearly.realized_amount, 1100.0)
        self.assertEqual(yearly.pending_amount, 3300.0)
        self.assertEqual(yearly.total_amount, 4400.0)

        quarters = summarize_quarterly(result, 2026)
        self.assertEqual([item.total_amount for item in quarters], [1100.0] * 4)

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


class DividendAnnouncementSuppressionTests(unittest.TestCase):
    def test_announced_annual_dividend_suppresses_adjacent_history_projection(self):
        """去年 8 月、今年公告 7 月，應視為同一次年度股利。"""
        holding = Holding(
            None,
            '6284',
            '6284.TWO',
            '佳邦',
            'TPEX',
            1000,
            70000.0,
        )
        actions = [
            CorporateAction(
                symbol='6284.TWO',
                stock_code='6284',
                stock_name='佳邦',
                action_date='2025-07-10',
                action_type='DIVIDEND',
                value=2.0,
                source='yahoo_tw_scraper',
                period='2024',
                payment_date='2025-08-08',
                announcement_status='PAID',
            ),
            CorporateAction(
                symbol='6284.TWO',
                stock_code='6284',
                stock_name='佳邦',
                action_date='2026-06-25',
                action_type='DIVIDEND',
                value=2.5,
                source='yahoo_tw_scraper',
                period='2025',
                payment_date='2026-07-24',
                announcement_status='ANNOUNCED',
            ),
        ]

        result = build_dividend_projection(
            [holding],
            actions,
            target_year=2026,
            as_of_date=date(2026, 7, 14),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].month, '2026-07')
        self.assertEqual(result[0].source, 'yahoo_tw_scraper')
        self.assertFalse(any(item.month == '2026-08' for item in result))


class DividendFrequencyForecastTests(unittest.TestCase):
    def test_annual_stock_uses_latest_annual_policy_once(self):
        holding = Holding(
            None, '2608', '2608.TW', '嘉里大榮', 'TWSE', 1000, 30000.0
        )
        actions = [
            CorporateAction(
                '2608.TW', '2608', '嘉里大榮',
                '2025-06-13', 'DIVIDEND', 1.3,
                source='yahoo_tw_scraper',
                period='2024',
                payment_date='2025-07-10',
            ),
        ]
        result = build_dividend_projection(
            [holding], actions, 2026, as_of_date=date(2026, 1, 1)
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].month, '2026-07')
        self.assertEqual(result[0].dividend_per_share, 1.3)
        self.assertIn('年配', result[0].basis)

    def test_monthly_product_uses_latest_month_amount_for_future_months(self):
        holding = Holding(
            None, '00929', '00929.TW', '復華台灣科技優息', 'TWSE',
            1000, 18000.0
        )
        actions = [
            CorporateAction(
                '00929.TW', '00929', '復華台灣科技優息',
                '2026-04-15', 'DIVIDEND', 0.7,
            ),
            CorporateAction(
                '00929.TW', '00929', '復華台灣科技優息',
                '2026-05-15', 'DIVIDEND', 0.75,
            ),
            CorporateAction(
                '00929.TW', '00929', '復華台灣科技優息',
                '2026-06-15', 'DIVIDEND', 0.8,
            ),
        ]
        result = build_dividend_projection(
            [holding], actions, 2026, as_of_date=date(2026, 6, 20)
        )
        projected = [item for item in result if item.source == 'projection']
        self.assertEqual([item.month for item in projected], [
            '2026-07', '2026-08', '2026-09',
            '2026-10', '2026-11', '2026-12',
        ])
        self.assertTrue(all(item.dividend_per_share == 0.8 for item in projected))
        self.assertTrue(all('月配' in item.basis for item in projected))
