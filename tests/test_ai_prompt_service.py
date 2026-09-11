"""build_news_prompt／build_analysis_prompt 的提示詞內容測試。"""

from datetime import date

from app.services.ai_prompt_service import build_analysis_prompt, build_news_prompt
from app.services.dividend_service import PENDING, REALIZED, DividendProjection
from app.services.portfolio_service import HoldingView


def _view(**overrides):
    defaults = dict(
        symbol='0050.TW',
        stock_code='0050',
        stock_name='元大台灣50',
        market_segment='TWSE',
        shares=1000,
        total_cost=150000.0,
        average_cost=150.0,
        close=160.0,
        market_value=160000.0,
        profit=10000.0,
        return_rate=6.67,
        trade_date='2026-07-10',
    )
    defaults.update(overrides)
    return HoldingView(**defaults)


def _projection(symbol='0050.TW', estimated_amount=1000.0, status=REALIZED, **overrides):
    defaults = dict(
        month='2026-07',
        symbol=symbol,
        stock_code='0050',
        stock_name='元大台灣50',
        shares=1000,
        dividend_per_share=1.0,
        estimated_amount=estimated_amount,
        status=status,
        basis='ACTUAL',
        reference_date='2026-07-21',
    )
    defaults.update(overrides)
    return DividendProjection(**defaults)


def test_build_news_prompt_includes_holding_details_and_fixed_date():
    view = _view()

    prompt = build_news_prompt(view, date(2026, 7, 15))

    assert '2026-07-15' in prompt
    assert view.stock_code in prompt
    assert view.stock_name in prompt
    assert view.symbol in prompt
    assert '1,000 股' in prompt
    assert '150.00' in prompt
    assert '160.00' in prompt
    assert '6.67%' in prompt


def test_build_analysis_prompt_sums_realized_and_pending_dividends():
    view = _view(market_segment='TWSE')
    projections = [
        _projection(estimated_amount=1000.0, status=REALIZED),
        _projection(estimated_amount=500.0, status=REALIZED),
        _projection(estimated_amount=300.0, status=PENDING),
    ]

    prompt = build_analysis_prompt(view, projections)

    assert '已實現約 NT$ 1,500' in prompt
    assert '未領／預估約 NT$ 300' in prompt
    assert '上市' in prompt
    assert view.stock_code in prompt


def test_build_analysis_prompt_resolves_market_label_from_market_segment():
    view = _view(market_segment='TPEX')

    prompt = build_analysis_prompt(view, [])

    assert '上櫃' in prompt


def test_build_analysis_prompt_with_no_dividends_shows_zero():
    view = _view()

    prompt = build_analysis_prompt(view, [])

    assert '已實現約 NT$ 0' in prompt
    assert '未領／預估約 NT$ 0' in prompt


def test_build_analysis_prompt_ignores_other_symbols():
    view = _view(symbol='0050.TW')
    projections = [
        _projection(symbol='0050.TW', estimated_amount=1000.0, status=REALIZED),
        _projection(symbol='0056.TW', estimated_amount=9999.0, status=REALIZED),
    ]

    prompt = build_analysis_prompt(view, projections)

    assert '已實現約 NT$ 1,000' in prompt
    assert '9,999' not in prompt
