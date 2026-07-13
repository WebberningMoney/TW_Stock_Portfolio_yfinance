from datetime import date

from app.api.yahoo_tw_dividend_scraper import parse_dividend_html
from app.models import CorporateAction, Holding, Instrument
from app.services.dividend_service import (
    PENDING,
    build_dividend_projection,
)


def test_parse_announced_etf_dividend_row():
    html = '''
    <html><body>
      <section id="main-2-QuoteDividend-Proxy">
        <ul>
          <li class="dividend-row">
            <span>2026</span><span>2026Q2</span><span>1.35</span>
            <span>-</span><span>2.56%</span><span>52.70</span>
            <span>2026/07/21</span><span>-</span>
            <span>2026/08/10</span><span>-</span><span>-</span>
          </li>
        </ul>
      </section>
    </body></html>
    '''
    instrument = Instrument(
        symbol='0056.TW', stock_code='0056', name='元大高股息'
    )
    actions = parse_dividend_html(html, instrument)
    assert len(actions) == 1
    action = actions[0]
    assert action.period == '2026Q2'
    assert action.action_date == '2026-07-21'
    assert action.payment_date == '2026-08-10'
    assert action.value == 1.35
    assert action.source == 'yahoo_tw_scraper'


def test_scraped_dividend_overrides_yfinance_and_uses_payment_month():
    holding = Holding(
        id=None,
        stock_code='0056',
        yahoo_symbol='0056.TW',
        stock_name='元大高股息',
        market_segment='TWSE',
        shares=1000,
        total_cost=40000,
    )
    actions = [
        CorporateAction(
            symbol='0056.TW',
            stock_code='0056',
            stock_name='元大高股息',
            action_date='2026-07-21',
            action_type='DIVIDEND',
            value=1.35,
            source='yfinance',
        ),
        CorporateAction(
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
        ),
    ]

    projections = build_dividend_projection(
        [holding],
        actions,
        target_year=2026,
        as_of_date=date(2026, 7, 14),
    )
    assert len(projections) == 1
    item = projections[0]
    assert item.month == '2026-08'
    assert item.status == PENDING
    assert item.estimated_amount == 1350
    assert item.payment_date == '2026-08-10'
    assert '已公告' in item.basis
