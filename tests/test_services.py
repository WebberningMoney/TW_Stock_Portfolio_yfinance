"""不需網路即可執行的基本服務測試。"""

import unittest
from datetime import date

from app.models import CorporateAction, Holding, MarketQuote
from app.services.dividend_service import (
    PENDING,
    REALIZED,
    DividendChartSeries,
    DividendProjection,
    build_dividend_chart_series,
    build_dividend_projection,
    select_legend_series,
    summarize_monthly,
    summarize_quarterly,
    summarize_year,
)
from app.services.portfolio_service import (
    build_holding_views,
    summarize_portfolio,
)


class ServiceTests(unittest.TestCase):
    def _quote(self, symbol='0050.TW', close=160.0, trade_date='2026-07-10', **overrides):
        defaults = dict(
            symbol=symbol,
            stock_code='0050',
            name='元大台灣50',
            close=close,
            previous_close=close,
            change=0.0,
            change_percent=0.0,
            volume=0.0,
            trade_date=trade_date,
            currency='TWD',
        )
        defaults.update(overrides)
        return MarketQuote(**defaults)

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
            {'0050.TW': self._quote()},
        )
        self.assertEqual(views[0].market_value, 160000.0)
        self.assertAlmostEqual(views[0].return_rate, 6.666666, places=4)
        summary = summarize_portfolio(views)
        self.assertEqual(summary.total_profit, 10000.0)

    def test_missing_quote_falls_back_to_zero_close(self):
        holding = Holding(
            None,
            '0050',
            '0050.TW',
            '元大台灣50',
            'TWSE',
            1000,
            150000.0,
        )
        views = build_holding_views([holding], {})
        self.assertEqual(views[0].close, 0.0)

    def test_missing_quote_falls_back_to_empty_trade_date(self):
        holding = Holding(
            None,
            '0050',
            '0050.TW',
            '元大台灣50',
            'TWSE',
            1000,
            150000.0,
        )
        views = build_holding_views([holding], {})
        self.assertEqual(views[0].trade_date, '')

    def test_zero_total_cost_holding_avoids_division_by_zero(self):
        holding = Holding(
            None,
            '0050',
            '0050.TW',
            '元大台灣50',
            'TWSE',
            1000,
            0.0,
        )
        views = build_holding_views([holding], {'0050.TW': self._quote()})
        self.assertEqual(views[0].return_rate, 0.0)

    def test_summarize_portfolio_zero_total_cost_avoids_division_by_zero(self):
        empty_summary = summarize_portfolio([])
        self.assertEqual(empty_summary.total_return_rate, 0.0)

        zero_cost_holding = Holding(
            None,
            '0050',
            '0050.TW',
            '元大台灣50',
            'TWSE',
            1000,
            0.0,
        )
        views = build_holding_views(
            [zero_cost_holding], {'0050.TW': self._quote()}
        )
        zero_cost_summary = summarize_portfolio(views)
        self.assertEqual(zero_cost_summary.total_return_rate, 0.0)

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


class DividendChartSeriesTests(unittest.TestCase):
    MONTH_KEYS = [f'2026-{month:02d}' for month in range(1, 13)]

    def _projection(
        self,
        symbol='0050.TW',
        stock_code='0050',
        stock_name='元大台灣50',
        month='2026-01',
        status=REALIZED,
        estimated_amount=1000.0,
    ):
        return DividendProjection(
            month=month,
            symbol=symbol,
            stock_code=stock_code,
            stock_name=stock_name,
            shares=1000,
            dividend_per_share=1.0,
            estimated_amount=estimated_amount,
            status=status,
            basis='test',
            reference_date=f'{month}-01',
        )

    def test_series_sorted_by_total_descending(self):
        projections = [
            self._projection(symbol='A.TW', stock_code='A', stock_name='A', estimated_amount=500.0),
            self._projection(symbol='B.TW', stock_code='B', stock_name='B', estimated_amount=1500.0),
        ]
        series = build_dividend_chart_series(projections, self.MONTH_KEYS)
        self.assertEqual([item.symbol for item in series], ['B.TW', 'A.TW'])

    def test_tie_break_preserves_first_seen_order(self):
        projections = [
            self._projection(symbol='A.TW', stock_code='A', stock_name='A', estimated_amount=500.0),
            self._projection(symbol='B.TW', stock_code='B', stock_name='B', estimated_amount=500.0),
        ]
        series = build_dividend_chart_series(projections, self.MONTH_KEYS)
        self.assertEqual([item.symbol for item in series], ['A.TW', 'B.TW'])

    def test_realized_and_pending_bucketed_and_aligned_to_month_keys(self):
        projections = [
            self._projection(month='2026-01', status=REALIZED, estimated_amount=100.0),
            self._projection(month='2026-03', status=PENDING, estimated_amount=50.0),
        ]
        series = build_dividend_chart_series(projections, self.MONTH_KEYS)
        item = series[0]
        self.assertEqual(item.label, '0050 元大台灣50')
        self.assertEqual(item.total, 150.0)
        self.assertEqual(item.realized_by_month[0], 100.0)
        self.assertEqual(item.realized_by_month[2], 0.0)
        self.assertEqual(item.pending_by_month[2], 50.0)
        self.assertEqual(item.pending_by_month[0], 0.0)

    def test_empty_projections_returns_empty_list(self):
        self.assertEqual(build_dividend_chart_series([], self.MONTH_KEYS), [])

    def _series(self, count):
        return [
            DividendChartSeries(
                symbol=f'S{index}',
                label=f'S{index}',
                total=float(count - index),
                realized_by_month=[0.0] * 12,
                pending_by_month=[0.0] * 12,
            )
            for index in range(count)
        ]

    def test_select_legend_series_no_overflow_at_exact_max(self):
        visible, overflow = select_legend_series(self._series(30), 30)
        self.assertEqual(len(visible), 30)
        self.assertEqual(overflow, 0)

    def test_select_legend_series_overflow_past_max(self):
        series = self._series(31)
        visible, overflow = select_legend_series(series, 30)
        self.assertEqual([item.symbol for item in visible], [item.symbol for item in series[:30]])
        self.assertEqual(overflow, 1)
