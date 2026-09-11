from datetime import date, timedelta

import pytest

from app.api.yahoo_tw_dividend_scraper import (
    YahooTwDividendScraper,
    YahooTwScraperError,
    filter_actions_by_range,
    parse_dividend_html,
)
from app.models import CorporateAction, Holding, Instrument
from app.services.dividend_service import (
    PENDING,
    build_dividend_projection,
)
from app.settings import RuntimeSettings


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



def test_parse_announced_etf_half_year_dividend_row():
    """0050 等半年配 ETF 的 2026H1 / 2026H2 必須能被解析。"""
    html = '''
    <html><body>
      <section id="main-2-QuoteDividend-Proxy">
        <ul>
          <li class="dividend-row">
            <span>2026</span><span>2026H1</span><span>0.36</span>
            <span>-</span><span>0.70%</span><span>51.45</span>
            <span>2026/07/21</span><span>-</span>
            <span>2026/08/10</span><span>-</span><span>9</span>
          </li>
        </ul>
      </section>
    </body></html>
    '''
    instrument = Instrument(
        symbol='0050.TW', stock_code='0050', name='元大台灣50'
    )
    actions = parse_dividend_html(html, instrument)
    assert len(actions) == 1
    action = actions[0]
    assert action.period == '2026H1'
    assert action.action_date == '2026-07-21'
    assert action.payment_date == '2026-08-10'
    assert action.value == 0.36
    assert action.source == 'yahoo_tw_scraper'


def test_parse_half_year_period_with_separator():
    """Yahoo 若輸出 2026-H1 或 2026/H2，也要正規化。"""
    html = '''
    <html><body>
      <ul>
        <li>
          <span>2026</span><span>2026-H1</span><span>1.25</span>
          <span>-</span><span>2.00%</span><span>62.50</span>
          <span>2026/07/17</span><span>-</span>
          <span>2026/08/14</span><span>-</span><span>-</span>
        </li>
      </ul>
    </body></html>
    '''
    instrument = Instrument(
        symbol='0050.TW', stock_code='0050', name='元大台灣50'
    )
    actions = parse_dividend_html(html, instrument)
    assert len(actions) == 1
    assert actions[0].period == '2026H1'

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
    # Q2 已公告資料應保留；所屬期間明確是 Q2，因此系統會視為季配，
    # 並用最近一季 1.35 元推估下一季，但不重複計算 Q2 本身。
    assert len(projections) == 2
    item = projections[0]
    assert item.month == '2026-08'
    assert item.status == PENDING
    assert item.estimated_amount == 1350
    assert item.payment_date == '2026-08-10'
    assert '已公告' in item.basis

    projected = projections[1]
    assert projected.month == '2026-11'
    assert projected.source == 'projection'
    assert projected.dividend_per_share == 1.35



def test_parse_2608_cash_payment_date_uses_yahoo_column_alignment():
    """2608 嘉里大榮：除息日與現金股利發放日必須對應 Yahoo 欄位。"""
    html = """
    <html><body><ul><li>
      <span>2025</span><span>2024</span><span>1.65</span>
      <span>-</span><span>4.52%</span><span>36.50</span>
      <span>2025/06/13</span><span>-</span>
      <span>2025/07/10</span><span>-</span><span>-</span>
    </li></ul></body></html>
    """
    instrument = Instrument(
        symbol='2608.TW', stock_code='2608', name='嘉里大榮'
    )
    actions = parse_dividend_html(html, instrument)
    assert len(actions) == 1
    assert actions[0].action_date == '2025-06-13'
    assert actions[0].payment_date == '2025-07-10'
    assert actions[0].period == '2024'
    assert actions[0].value == 1.65


def test_scraper_range_filter_uses_ex_dividend_date():
    instrument = Instrument(
        symbol='2608.TW', stock_code='2608', name='嘉里大榮'
    )
    actions = [
        CorporateAction(
            symbol=instrument.symbol, stock_code='2608', stock_name='嘉里大榮',
            action_date='2021-06-10', action_type='DIVIDEND', value=1.5,
            source='yahoo_tw_scraper',
        ),
        CorporateAction(
            symbol=instrument.symbol, stock_code='2608', stock_name='嘉里大榮',
            action_date='2025-06-13', action_type='DIVIDEND', value=1.65,
            source='yahoo_tw_scraper',
        ),
    ]
    filtered = filter_actions_by_range(actions, '3y', as_of=date(2026, 7, 18))
    assert [item.action_date for item in filtered] == ['2025-06-13']


def _sequenced_transport(*results):
    """依序回放 results：字串當作成功回應，例外實例則被丟出。

    呼叫次數超過 results 長度時明確報 AssertionError，避免 StopIteration
    被 fetch_dividends 的 `except Exception` 誤判成一般抓取失敗而悄悄吞掉。
    """
    iterator = iter(results)

    def transport(url: str, timeout: int) -> str:
        try:
            result = next(iterator)
        except StopIteration:
            raise AssertionError(
                'transport 被呼叫的次數超過測試準備的 results 數量'
            ) from None
        if isinstance(result, BaseException):
            raise result
        return result

    return transport


def _fast_settings(item_retries: int = 3, action_period: str = 'max') -> RuntimeSettings:
    return RuntimeSettings(
        item_retries=item_retries,
        retry_backoff_seconds=0.0,
        scraper_delay_seconds=0.0,
        scraper_timeout_seconds=5,
        action_period=action_period,
    )


def _dividend_row_html(period: str, ex_date: str, payment_date: str, value: str = '1.35') -> str:
    return f'''
    <li class="dividend-row">
      <span>{ex_date[:4]}</span><span>{period}</span><span>{value}</span>
      <span>-</span><span>2.56%</span><span>52.70</span>
      <span>{ex_date}</span><span>-</span>
      <span>{payment_date}</span><span>-</span><span>-</span>
    </li>
    '''


def _dividend_page_html(*rows: str) -> str:
    return f'''
    <html><body>
      <section id="main-2-QuoteDividend-Proxy">
        <ul>{''.join(rows)}</ul>
      </section>
    </body></html>
    '''


def test_fetch_dividends_succeeds_on_first_attempt():
    instrument = Instrument(symbol='0056.TW', stock_code='0056', name='元大高股息')
    html = _dividend_page_html(
        _dividend_row_html('2026Q2', '2026/07/21', '2026/08/10')
    )
    scraper = YahooTwDividendScraper(
        settings=_fast_settings(),
        transport=_sequenced_transport(html),
    )

    actions = scraper.fetch_dividends(instrument)

    assert len(actions) == 1
    assert actions[0].symbol == '0056.TW'
    assert actions[0].action_date == '2026-07-21'


def test_fetch_dividends_retries_then_succeeds():
    instrument = Instrument(symbol='0056.TW', stock_code='0056', name='元大高股息')
    html = _dividend_page_html(
        _dividend_row_html('2026Q2', '2026/07/21', '2026/08/10')
    )
    attempts: list[int] = []

    def progress(message, attempt, total):
        attempts.append(attempt)

    scraper = YahooTwDividendScraper(
        settings=_fast_settings(item_retries=3),
        transport=_sequenced_transport(
            ConnectionError('第一次連線失敗'),
            TimeoutError('第二次逾時'),
            html,
        ),
    )

    actions = scraper.fetch_dividends(instrument, progress=progress)

    assert len(actions) == 1
    # 每次 attempt 開頭會回報一次「正在連線」，失敗時再回報一次「讀取失敗」；
    # 最後一次成功則再回報一次「解析成功」。
    assert attempts == [1, 1, 2, 2, 3, 3]


def test_fetch_dividends_raises_after_exhausting_retries():
    instrument = Instrument(symbol='2330.TW', stock_code='2330', name='台積電')
    scraper = YahooTwDividendScraper(
        settings=_fast_settings(item_retries=2),
        transport=_sequenced_transport(
            ConnectionError('第一次失敗'),
            ConnectionError('第二次失敗'),
        ),
    )

    with pytest.raises(YahooTwScraperError) as excinfo:
        scraper.fetch_dividends(instrument)

    message = str(excinfo.value)
    assert '2330.TW' in message
    assert '2' in message
    assert excinfo.value.__cause__ is not None


def test_fetch_dividends_rejects_incomplete_page_content():
    instrument = Instrument(symbol='2330.TW', stock_code='2330', name='台積電')
    scraper = YahooTwDividendScraper(
        settings=_fast_settings(item_retries=1),
        transport=_sequenced_transport('<html><body>暫無資料</body></html>'),
    )

    with pytest.raises(YahooTwScraperError):
        scraper.fetch_dividends(instrument)


def test_fetch_dividends_reports_progress_with_symbol_and_attempt_numbers():
    instrument = Instrument(symbol='0056.TW', stock_code='0056', name='元大高股息')
    html = _dividend_page_html(
        _dividend_row_html('2026Q2', '2026/07/21', '2026/08/10')
    )
    messages: list[tuple[str, int | None, int | None]] = []

    def progress(message, attempt, total):
        messages.append((message, attempt, total))

    scraper = YahooTwDividendScraper(
        settings=_fast_settings(item_retries=3),
        transport=_sequenced_transport(html),
    )
    scraper.fetch_dividends(instrument, progress=progress)

    assert len(messages) >= 1
    first_message, first_attempt, first_total = messages[0]
    assert '0056.TW' in first_message
    assert first_attempt == 1
    assert first_total == 3


def test_fetch_dividends_applies_action_period_from_settings():
    instrument = Instrument(symbol='2608.TW', stock_code='2608', name='嘉里大榮')
    today = date.today()
    recent = today - timedelta(days=10)
    old = today.replace(year=today.year - 5)
    html = _dividend_page_html(
        _dividend_row_html(
            f'{recent.year}Q1',
            recent.strftime('%Y/%m/%d'),
            (recent + timedelta(days=20)).strftime('%Y/%m/%d'),
            value='1.10',
        ),
        _dividend_row_html(
            f'{old.year}Q1',
            old.strftime('%Y/%m/%d'),
            (old + timedelta(days=20)).strftime('%Y/%m/%d'),
            value='0.90',
        ),
    )
    scraper = YahooTwDividendScraper(
        settings=_fast_settings(action_period='1y'),
        transport=_sequenced_transport(html),
    )

    actions = scraper.fetch_dividends(instrument)

    assert [action.action_date for action in actions] == [recent.isoformat()]
