"""YFinanceClient 的行情／股利下載邏輯測試：透過 YFinanceTransport 假縫，不連真實網路。"""

import pandas as pd
import pytest

from app.api.yfinance_client import YFinanceApiError, YFinanceClient
from app.models import Instrument
from app.settings import RuntimeSettings


class FakeTransport:
    """依 tickers／symbol 分組、依序回放結果的假 YFinanceTransport。"""

    def __init__(self):
        self._download_results: dict[tuple, list] = {}
        self._history_results: dict[str, list] = {}
        self.download_calls: list[tuple] = []
        self.history_calls: list[tuple] = []

    def queue_download(self, tickers, result):
        self._download_results.setdefault(tuple(tickers), []).append(result)

    def queue_history(self, symbol, result):
        self._history_results.setdefault(symbol, []).append(result)

    def download(self, tickers, **kwargs):
        key = tuple(tickers)
        self.download_calls.append((key, kwargs))
        queue = self._download_results.get(key)
        if not queue:
            raise AssertionError(
                f'download({key}) 被呼叫的次數超過測試準備的結果數量'
            )
        result = queue.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def history(self, symbol, **kwargs):
        self.history_calls.append((symbol, kwargs))
        queue = self._history_results.get(symbol)
        if not queue:
            raise AssertionError(
                f'history({symbol!r}) 被呼叫的次數超過測試準備的結果數量'
            )
        result = queue.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _fast_settings(item_retries: int = 3) -> RuntimeSettings:
    return RuntimeSettings(
        item_retries=item_retries,
        retry_backoff_seconds=0.0,
        quote_batch_delay_seconds=0.0,
        action_item_delay_seconds=0.0,
    )


def _instrument(symbol='0050.TW', code='0050', name='元大台灣50'):
    return Instrument(symbol=symbol, stock_code=code, name=name)


def _date_index(n):
    return pd.date_range('2026-07-01', periods=n, freq='D')


def _price_frame(rows):
    """單檔（無 MultiIndex）欄位形狀，模擬 Ticker(...).history() 的回傳。"""
    return pd.DataFrame(rows, index=_date_index(len(rows)))


def _multi_ticker_frame(rows_by_symbol):
    """多檔 MultiIndex 欄位形狀，模擬 yf.download(group_by='ticker') 的回傳。"""
    frames = {
        symbol: pd.DataFrame(rows, index=_date_index(len(rows)))
        for symbol, rows in rows_by_symbol.items()
    }
    return pd.concat(frames, axis=1)


def _make_client(monkeypatch, tmp_path, transport, settings=None):
    monkeypatch.setattr(
        'app.api.yfinance_client.YFINANCE_CACHE_DIR', tmp_path / 'yfinance_cache'
    )
    monkeypatch.setattr(
        'app.api.yfinance_client.NAME_OVERRIDES_PATH', tmp_path / 'name_overrides.csv'
    )
    return YFinanceClient(settings=settings or _fast_settings(), transport=transport)


def test_download_quotes_batch_success(monkeypatch, tmp_path):
    transport = FakeTransport()
    transport.queue_download(
        ['0050.TW', '0056.TW'],
        _multi_ticker_frame({
            '0050.TW': [
                {'Close': 158.0, 'Volume': 1000.0},
                {'Close': 160.0, 'Volume': 1200.0},
            ],
            '0056.TW': [
                {'Close': 29.0, 'Volume': 500.0},
                {'Close': 30.0, 'Volume': 600.0},
            ],
        }),
    )
    client = _make_client(monkeypatch, tmp_path, transport)

    quotes, failed = client.download_quotes(
        [_instrument('0050.TW', '0050'), _instrument('0056.TW', '0056')]
    )

    assert failed == []
    by_symbol = {quote.symbol: quote for quote in quotes}
    assert by_symbol['0050.TW'].close == 160.0
    assert by_symbol['0050.TW'].previous_close == 158.0
    assert by_symbol['0050.TW'].change == 2.0
    assert by_symbol['0056.TW'].close == 30.0


def test_download_quotes_batch_failure_retries_then_succeeds(monkeypatch, tmp_path):
    transport = FakeTransport()
    transport.queue_download(['0050.TW'], RuntimeError('批次下載失敗'))
    transport.queue_download(
        ['0050.TW'],
        _multi_ticker_frame({
            '0050.TW': [
                {'Close': 158.0, 'Volume': 1000.0},
                {'Close': 160.0, 'Volume': 1200.0},
            ],
        }),
    )
    client = _make_client(monkeypatch, tmp_path, transport, _fast_settings(item_retries=2))

    quotes, failed = client.download_quotes([_instrument('0050.TW', '0050')])

    assert failed == []
    assert quotes[0].close == 160.0


def test_download_quotes_retry_exhausted_reports_failure(monkeypatch, tmp_path):
    transport = FakeTransport()
    transport.queue_download(['0050.TW'], RuntimeError('批次下載失敗'))
    transport.queue_download(['0050.TW'], RuntimeError('重試第 1 次失敗'))
    transport.queue_download(['0050.TW'], RuntimeError('重試第 2 次失敗'))
    client = _make_client(monkeypatch, tmp_path, transport, _fast_settings(item_retries=2))

    quotes, failed = client.download_quotes([_instrument('0050.TW', '0050')])

    assert quotes == []
    assert failed == ['0050.TW']


def test_download_quotes_missing_close_treated_as_failure_then_retry_succeeds(
    monkeypatch, tmp_path
):
    transport = FakeTransport()
    transport.queue_download(
        ['0050.TW'], _multi_ticker_frame({'0050.TW': [{'Volume': 100.0}]})
    )
    transport.queue_download(
        ['0050.TW'],
        _multi_ticker_frame({
            '0050.TW': [
                {'Close': 158.0, 'Volume': 1000.0},
                {'Close': 160.0, 'Volume': 1200.0},
            ],
        }),
    )
    client = _make_client(monkeypatch, tmp_path, transport, _fast_settings(item_retries=1))

    quotes, failed = client.download_quotes([_instrument('0050.TW', '0050')])

    assert failed == []
    assert quotes[0].close == 160.0


def test_download_actions_batch_success(monkeypatch, tmp_path):
    transport = FakeTransport()
    transport.queue_download(
        ['0050.TW'],
        _multi_ticker_frame({
            '0050.TW': [
                {'Close': 158.0, 'Dividends': 0.0, 'Stock Splits': 0.0},
                {'Close': 160.0, 'Dividends': 1.35, 'Stock Splits': 0.0},
            ],
        }),
    )
    client = _make_client(monkeypatch, tmp_path, transport)

    action_map, failed = client.download_actions([_instrument('0050.TW', '0050')])

    assert failed == []
    actions = action_map['0050.TW']
    assert len(actions) == 1
    assert actions[0].action_type == 'DIVIDEND'
    assert actions[0].value == 1.35


def test_download_actions_batch_failure_retries_via_fetch_actions(monkeypatch, tmp_path):
    transport = FakeTransport()
    transport.queue_download(['0050.TW'], RuntimeError('批次下載失敗'))
    transport.queue_history(
        '0050.TW',
        _price_frame([
            {'Close': 158.0, 'Dividends': 0.0, 'Stock Splits': 0.0},
            {'Close': 160.0, 'Dividends': 1.35, 'Stock Splits': 0.0},
        ]),
    )
    client = _make_client(monkeypatch, tmp_path, transport)

    action_map, failed = client.download_actions([_instrument('0050.TW', '0050')])

    assert failed == []
    assert action_map['0050.TW'][0].value == 1.35


def test_fetch_actions_parses_dividends_and_splits(monkeypatch, tmp_path):
    transport = FakeTransport()
    transport.queue_history(
        '0050.TW',
        _price_frame([
            {'Close': 100.0, 'Dividends': 0.0, 'Stock Splits': 0.0},
            {'Close': 100.0, 'Dividends': 0.0, 'Stock Splits': 4.0},
        ]),
    )
    client = _make_client(monkeypatch, tmp_path, transport)

    actions = client.fetch_actions(_instrument('0050.TW', '0050'))

    assert len(actions) == 1
    assert actions[0].action_type == 'SPLIT'
    assert actions[0].value == 4.0


def test_fetch_actions_wraps_transport_error(monkeypatch, tmp_path):
    transport = FakeTransport()
    transport.queue_history('0050.TW', RuntimeError('連線失敗'))
    client = _make_client(monkeypatch, tmp_path, transport)

    with pytest.raises(YFinanceApiError):
        client.fetch_actions(_instrument('0050.TW', '0050'))
