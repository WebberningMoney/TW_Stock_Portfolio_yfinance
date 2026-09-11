"""sync_holding_actions 進度回報的 SyncStep 標記測試。"""

from app.db.database import Database
from app.models import CorporateAction, Holding, Instrument
from app.services.sync_service import SyncService, SyncStep
from app.settings import RuntimeSettings


class FakeYFinanceClient:
    def __init__(self, actions_by_symbol=None):
        self.actions_by_symbol = actions_by_symbol or {}
        self.download_actions_calls = 0

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
        }
        return action_map, []

    def update_settings(self, settings):
        pass


class FakeDividendScraper:
    def __init__(self, announced_by_symbol=None):
        self.announced_by_symbol = announced_by_symbol or {}
        self.fetch_dividends_calls = 0

    def fetch_dividends(self, instrument, progress=None):
        self.fetch_dividends_calls += 1
        if progress:
            progress(f'[假爬蟲] {instrument.symbol}', None, None)
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


def _build_service(tmp_path, client, scraper):
    database = Database(tmp_path / 'portfolio.db')
    database.initialize()
    for symbol, code in (('0050.TW', '0050'), ('0056.TW', '0056')):
        database.upsert_instruments([_instrument(symbol, code)])
        database.upsert_holding(_holding(symbol, code))
    return SyncService(
        database=database,
        settings=RuntimeSettings(),
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
