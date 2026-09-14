"""sync_holding_actions 進度回報與錯誤處理路徑的測試。"""

import pytest

from app.db.database import Database
from app.models import CorporateAction, Holding, Instrument
from app.services.sync_service import SyncService, SyncStep
from app.settings import RuntimeSettings


class FakeYFinanceClient:
    def __init__(
        self,
        actions_by_symbol=None,
        missing_action_symbols=None,
        failed_action_symbols=None,
        resolve_instrument_results=None,
    ):
        self.actions_by_symbol = actions_by_symbol or {}
        self.missing_action_symbols = set(missing_action_symbols or ())
        self.failed_action_symbols = list(failed_action_symbols or ())
        self._resolve_instrument_results = {
            key: list(value)
            for key, value in (resolve_instrument_results or {}).items()
        }
        self.download_actions_calls = 0
        self.resolve_instrument_calls = []

    def download_actions(self, instruments, progress=None):
        self.download_actions_calls += 1
        if progress:
            progress(
                f'[假 yfinance] 下載 {len(instruments)} 檔',
                len(instruments),
                len(instruments),
            )
        action_map = {
            instrument.symbol: self.actions_by_symbol.get(instrument.symbol, [])
            for instrument in instruments
            if instrument.symbol not in self.missing_action_symbols
        }
        return action_map, list(self.failed_action_symbols)

    def resolve_instrument(self, stock_code, market_segment):
        self.resolve_instrument_calls.append((stock_code, market_segment))
        queue = self._resolve_instrument_results.get(stock_code)
        if not queue:
            raise AssertionError(
                f'resolve_instrument({stock_code!r}) 被呼叫的次數超過測試準備的結果數量'
            )
        result = queue.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def update_settings(self, settings):
        pass


class FakeDividendScraper:
    def __init__(self, announced_by_symbol=None, error_symbols=None):
        self.announced_by_symbol = announced_by_symbol or {}
        self.error_symbols = set(error_symbols or ())
        self.fetch_dividends_calls = 0

    def fetch_dividends(self, instrument, progress=None):
        self.fetch_dividends_calls += 1
        if progress:
            progress(f'[假爬蟲] {instrument.symbol}', None, None)
        if instrument.symbol in self.error_symbols:
            raise RuntimeError(f'{instrument.symbol} 爬蟲連線失敗')
        return self.announced_by_symbol.get(instrument.symbol, [])

    def update_settings(self, settings):
        pass


def _holding(symbol='0050.TW', code='0050'):
    return Holding(None, code, symbol, '元大台灣50', 'TWSE', 1000, 150000.0)


def _instrument(symbol='0050.TW', code='0050'):
    return Instrument(symbol=symbol, stock_code=code, name='元大台灣50')


def _action(symbol='0050.TW', code='0050', source='yfinance'):
    return CorporateAction(
        symbol=symbol,
        stock_code=code,
        stock_name='元大台灣50',
        action_date='2026-07-21',
        action_type='DIVIDEND',
        value=1.0,
        source=source,
    )


def _build_service(tmp_path, client, scraper, settings=None):
    database = Database(tmp_path / 'portfolio.db')
    database.initialize()
    for symbol, code in (('0050.TW', '0050'), ('0056.TW', '0056')):
        database.upsert_instruments([_instrument(symbol, code)])
        database.upsert_holding(_holding(symbol, code))
    return SyncService(
        database=database,
        settings=settings or RuntimeSettings(),
        client=client,
        dividend_scraper=scraper,
    )


def _build_service_missing_instrument(tmp_path, client, scraper, settings=None):
    """建立只有一筆持股、但商品清冊裡沒有對應 Instrument 的 SyncService。"""
    database = Database(tmp_path / 'portfolio.db')
    database.initialize()
    database.upsert_holding(_holding('0050.TW', '0050'))
    return SyncService(
        database=database,
        settings=settings or RuntimeSettings(),
        client=client,
        dividend_scraper=scraper,
    )


def test_sync_holding_actions_tags_every_message_with_its_step(tmp_path):
    client = FakeYFinanceClient({'0050.TW': [_action('0050.TW', '0050')]})
    scraper = FakeDividendScraper({'0050.TW': [_action('0050.TW', '0050', source='yahoo_tw_scraper')]})
    service = _build_service(tmp_path, client, scraper)

    calls = []
    service.sync_holding_actions(
        source_mode='BOTH',
        progress=lambda message, current, total, step: calls.append((message, step)),
    )

    steps_in_order = []
    for _, step in calls:
        if not steps_in_order or steps_in_order[-1] != step:
            steps_in_order.append(step)
    assert steps_in_order == [
        SyncStep.RESOLVE_INSTRUMENTS,
        SyncStep.CLEAR_STALE_ACTIONS,
        SyncStep.FETCH_YFINANCE_HISTORY,
        SyncStep.SCRAPE_YAHOO_TW_ANNOUNCEMENTS,
        SyncStep.MERGE_DUPLICATE_ACTIONS,
        None,
    ]

    def step_for(prefix):
        matches = [step for message, step in calls if message.startswith(prefix)]
        assert matches, f'no message starts with {prefix!r}'
        return matches[0]

    assert step_for('[步驟 1/5') == SyncStep.RESOLVE_INSTRUMENTS
    assert step_for('[步驟 2/5') == SyncStep.CLEAR_STALE_ACTIONS
    assert step_for('[步驟 3/5') == SyncStep.FETCH_YFINANCE_HISTORY
    assert step_for('[假 yfinance]') == SyncStep.FETCH_YFINANCE_HISTORY
    assert step_for('[步驟 4/5') == SyncStep.SCRAPE_YAHOO_TW_ANNOUNCEMENTS
    assert step_for('[假爬蟲]') == SyncStep.SCRAPE_YAHOO_TW_ANNOUNCEMENTS
    assert step_for('[步驟 5/5') == SyncStep.MERGE_DUPLICATE_ACTIONS
    assert step_for('[結果]') is None


def test_sync_holding_actions_yfinance_only_skips_scrape_step(tmp_path):
    client = FakeYFinanceClient({'0050.TW': [_action('0050.TW', '0050')]})
    scraper = FakeDividendScraper()
    service = _build_service(tmp_path, client, scraper)

    calls = []
    service.sync_holding_actions(
        source_mode='YFINANCE',
        progress=lambda message, current, total, step: calls.append((message, step)),
    )

    assert scraper.fetch_dividends_calls == 0
    skip_messages = [
        (message, step) for message, step in calls
        if message.startswith('[步驟 4/5') or message == '略過完成'
    ]
    assert any(
        step == SyncStep.SCRAPE_YAHOO_TW_ANNOUNCEMENTS
        for _, step in skip_messages
    )


def test_sync_holding_actions_scraper_only_skips_yfinance_step(tmp_path):
    client = FakeYFinanceClient()
    scraper = FakeDividendScraper({'0050.TW': [_action('0050.TW', '0050', source='yahoo_tw_scraper')]})
    service = _build_service(tmp_path, client, scraper)

    calls = []
    service.sync_holding_actions(
        source_mode='SCRAPER',
        progress=lambda message, current, total, step: calls.append((message, step)),
    )

    assert client.download_actions_calls == 0
    skip_messages = [
        (message, step) for message, step in calls
        if message.startswith('[步驟 3/5')
    ]
    assert skip_messages
    assert all(
        step == SyncStep.FETCH_YFINANCE_HISTORY for _, step in skip_messages
    )


def test_sync_holding_actions_invalid_source_mode_raises_value_error(tmp_path):
    client = FakeYFinanceClient()
    scraper = FakeDividendScraper()
    service = _build_service(tmp_path, client, scraper)

    with pytest.raises(ValueError):
        service.sync_holding_actions(source_mode='NOT_A_MODE')


def test_sync_holding_actions_works_when_progress_is_none(tmp_path):
    client = FakeYFinanceClient({'0050.TW': [_action('0050.TW', '0050')]})
    scraper = FakeDividendScraper(
        {'0050.TW': [_action('0050.TW', '0050', source='yahoo_tw_scraper')]}
    )
    service = _build_service(tmp_path, client, scraper)

    result = service.sync_holding_actions(source_mode='BOTH', progress=None)

    assert result.failed_count == 0
    assert client.download_actions_calls == 1
    assert scraper.fetch_dividends_calls == 2


def test_sync_holding_actions_resolves_missing_instrument_after_retry(tmp_path):
    resolved = _instrument('0050.TW', '0050')
    client = FakeYFinanceClient(
        actions_by_symbol={'0050.TW': [_action('0050.TW', '0050')]},
        resolve_instrument_results={
            '0050': [RuntimeError('暫時查詢失敗'), resolved],
        },
    )
    scraper = FakeDividendScraper()
    settings = RuntimeSettings(item_retries=2, retry_backoff_seconds=0.0)
    service = _build_service_missing_instrument(tmp_path, client, scraper, settings)

    result = service.sync_holding_actions(source_mode='YFINANCE')

    assert result.failed_count == 0
    assert result.history_action_count == 1
    assert client.resolve_instrument_calls == [
        ('0050', 'TWSE'),
        ('0050', 'TWSE'),
    ]


def test_sync_holding_actions_reports_failure_when_instrument_resolution_retries_exhausted(
    tmp_path,
):
    client = FakeYFinanceClient(
        resolve_instrument_results={
            '0050': [RuntimeError('第一次失敗'), RuntimeError('第二次失敗')],
        },
    )
    scraper = FakeDividendScraper()
    settings = RuntimeSettings(item_retries=2, retry_backoff_seconds=0.0)
    service = _build_service_missing_instrument(tmp_path, client, scraper, settings)

    calls = []
    result = service.sync_holding_actions(
        source_mode='YFINANCE',
        progress=lambda message, current, total, step: calls.append((message, step)),
    )

    assert result.failed_count == 1
    assert client.resolve_instrument_calls == [
        ('0050', 'TWSE'),
        ('0050', 'TWSE'),
    ]
    # 商品解析失敗後不應該留在 instruments 清單裡，因此不會再嘗試下載行情。
    assert client.download_actions_calls == 0

    final_messages = [message for message, step in calls if step is None]
    assert final_messages
    assert '已重試仍失敗' in final_messages[-1]
    assert '0050.TW' in final_messages[-1]


def test_sync_holding_actions_skips_symbol_missing_from_action_map(tmp_path):
    client = FakeYFinanceClient(
        actions_by_symbol={'0050.TW': [_action('0050.TW', '0050')]},
        missing_action_symbols={'0056.TW'},
    )
    scraper = FakeDividendScraper()
    service = _build_service(tmp_path, client, scraper)

    calls = []
    result = service.sync_holding_actions(
        source_mode='YFINANCE',
        progress=lambda message, current, total, step: calls.append((message, step)),
    )

    assert result.history_action_count == 1
    completion_messages = [
        message for message, step in calls
        if message.startswith('[API／歷史] 完成：')
    ]
    assert any('0050.TW' in message for message in completion_messages)
    assert all('0056.TW' not in message for message in completion_messages)


def test_sync_holding_actions_records_yfinance_api_failed_symbols(tmp_path):
    client = FakeYFinanceClient(
        actions_by_symbol={'0050.TW': [_action('0050.TW', '0050')]},
        failed_action_symbols=['0056.TW'],
    )
    scraper = FakeDividendScraper()
    service = _build_service(tmp_path, client, scraper)

    calls = []
    result = service.sync_holding_actions(
        source_mode='YFINANCE',
        progress=lambda message, current, total, step: calls.append((message, step)),
    )

    assert result.failed_count == 1

    final_messages = [message for message, step in calls if step is None]
    assert final_messages
    assert '已重試仍失敗' in final_messages[-1]
    assert '0056.TW' in final_messages[-1]
    assert 'API／歷史股利／分割下載失敗' in final_messages[-1]


def test_sync_holding_actions_records_scraper_exception_as_failure(tmp_path):
    client = FakeYFinanceClient()
    scraper = FakeDividendScraper(error_symbols={'0056.TW'})
    service = _build_service(tmp_path, client, scraper)

    calls = []
    result = service.sync_holding_actions(
        source_mode='SCRAPER',
        progress=lambda message, current, total, step: calls.append((message, step)),
    )

    assert result.failed_count == 1
    failure_messages = [
        message for message, step in calls
        if message.startswith('[爬蟲／Yahoo 台灣] 最終失敗：')
    ]
    assert any('0056.TW' in message for message in failure_messages)
