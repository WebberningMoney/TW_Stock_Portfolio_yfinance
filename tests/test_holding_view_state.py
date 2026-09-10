"""HoldingViewState 的行為測試：不需要 tkinter 或資料庫。"""

import unittest

from app.models import Holding
from app.services.holding_view_state import HoldingViewState


class HoldingViewStateTests(unittest.TestCase):
    def _holding(self, symbol='0050.TW', code='0050'):
        return Holding(None, code, symbol, '元大台灣50', 'TWSE', 1000, 150000.0)

    def test_refresh_builds_cache_from_holdings_and_quotes(self):
        state = HoldingViewState()
        state.refresh(
            [self._holding()],
            {'0050.TW': {'close': 160.0, 'trade_date': '2026-07-10'}},
        )
        view = state.get('0050.TW')
        self.assertIsNotNone(view)
        self.assertEqual(view.market_value, 160000.0)

    def test_get_returns_none_for_unknown_symbol(self):
        state = HoldingViewState()
        state.refresh([self._holding()], {})
        self.assertIsNone(state.get('9999.TW'))

    def test_selected_returns_none_when_nothing_selected(self):
        state = HoldingViewState()
        state.refresh([self._holding()], {})
        self.assertIsNone(state.selected())

    def test_select_then_selected_returns_matching_view(self):
        state = HoldingViewState()
        state.refresh(
            [self._holding()],
            {'0050.TW': {'close': 160.0, 'trade_date': '2026-07-10'}},
        )
        state.select('0050.TW')
        view = state.selected()
        self.assertIsNotNone(view)
        self.assertEqual(view.symbol, '0050.TW')

    def test_select_none_clears_selection(self):
        state = HoldingViewState()
        state.refresh(
            [self._holding()],
            {'0050.TW': {'close': 160.0, 'trade_date': '2026-07-10'}},
        )
        state.select('0050.TW')
        state.select(None)
        self.assertIsNone(state.selected())

    def test_views_returns_all_cached_views_in_refresh_order(self):
        state = HoldingViewState()
        state.refresh(
            [self._holding('0050.TW', '0050'), self._holding('0056.TW', '0056')],
            {
                '0050.TW': {'close': 160.0, 'trade_date': '2026-07-10'},
                '0056.TW': {'close': 30.0, 'trade_date': '2026-07-10'},
            },
        )
        symbols = [view.symbol for view in state.views()]
        self.assertEqual(symbols, ['0050.TW', '0056.TW'])

    def test_refresh_drops_selection_target_if_symbol_no_longer_present(self):
        state = HoldingViewState()
        state.refresh(
            [self._holding()],
            {'0050.TW': {'close': 160.0, 'trade_date': '2026-07-10'}},
        )
        state.select('0050.TW')
        state.refresh([self._holding('0056.TW', '0056')], {})
        self.assertIsNone(state.selected())


if __name__ == '__main__':
    unittest.main()
