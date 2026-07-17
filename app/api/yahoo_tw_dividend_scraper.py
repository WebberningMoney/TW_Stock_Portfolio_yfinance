"""Yahoo 台灣「股利政策」頁面補強器。

本模組只針對已登錄持股抓取公開股利政策頁，補入股利所屬期間、現金股利、
除息日及現金股利發放日。資料抓取範圍與 yfinance 股利／分割共用同一設定。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
import re
import threading
import time
from typing import Any

from bs4 import BeautifulSoup
import requests

from app.config import YAHOO_TW_DIVIDEND_PAGE
from app.models import CorporateAction, Instrument
from app.settings import RuntimeSettings

ProgressCallback = Callable[[str, int | None, int | None], None]

_PERIOD_RE = re.compile(
    r'^\d{4}(?:\s*[-/]?\s*(?:Q[1-4]|H[12]))?$',
    re.IGNORECASE,
)
_DATE_RE = re.compile(r'^\d{4}[/-]\d{1,2}[/-]\d{1,2}$')
_NUMBER_RE = re.compile(r'^-?\d+(?:,\d{3})*(?:\.\d+)?$')
_DASHES = {'-', '--', '–', '—'}


class YahooTwScraperError(RuntimeError):
    """Yahoo 台灣股利頁抓取或解析失敗。"""


def _clean_token(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _normalize_period(value: str) -> str:
    """將年度、季度與半年度格式統一，例如 2026-H1 → 2026H1。"""
    text = _clean_token(value).upper().replace(' ', '')
    text = text.replace('-', '').replace('/', '')
    match = re.fullmatch(r'(\d{4})(Q[1-4]|H[12])', text)
    if match:
        return f'{match.group(1)}{match.group(2)}'
    return text


def _normalize_date(value: str) -> str:
    text = _clean_token(value).replace('/', '-')
    try:
        parsed = datetime.strptime(text, '%Y-%m-%d').date()
    except ValueError:
        return ''
    return parsed.isoformat()


def _parse_number(value: str) -> float:
    text = _clean_token(value).replace(',', '')
    if text in {'', *_DASHES} or text.endswith('%'):
        return 0.0
    if not _NUMBER_RE.fullmatch(text):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _dedupe_consecutive(tokens: Iterable[str]) -> list[str]:
    result: list[str] = []
    for token in tokens:
        clean = _clean_token(token)
        if not clean:
            continue
        if result and result[-1] == clean:
            continue
        result.append(clean)
    return result


def _range_start_date(range_code: str, as_of: date | None = None) -> date | None:
    """將 1y／3y／5y 等設定轉成起始日；max 表示不限制。"""
    if range_code == 'max':
        return None
    match = re.fullmatch(r'(\d+)y', str(range_code).lower())
    if not match:
        return None
    years = int(match.group(1))
    today = as_of or date.today()
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 2/29
        return today.replace(year=today.year - years, day=28)


def filter_actions_by_range(
    actions: list[CorporateAction],
    range_code: str,
    as_of: date | None = None,
) -> list[CorporateAction]:
    """依除息日篩選爬蟲結果，與 yfinance 歷史範圍一致。"""
    start = _range_start_date(range_code, as_of)
    if start is None:
        return actions
    result: list[CorporateAction] = []
    for action in actions:
        try:
            event_date = datetime.strptime(action.action_date, '%Y-%m-%d').date()
        except ValueError:
            continue
        if event_date >= start:
            result.append(action)
    return result


def _announcement_status(
    ex_date: str,
    payment_date: str,
    as_of: date | None = None,
) -> str:
    today = as_of or date.today()

    def parse(value: str) -> date | None:
        try:
            return datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError:
            return None

    ex_day = parse(ex_date)
    pay_day = parse(payment_date)
    if pay_day:
        if pay_day <= today:
            return 'PAID'
        if ex_day and ex_day <= today:
            return 'EX_DATE_PASSED'
        return 'ANNOUNCED'
    if ex_day and ex_day <= today:
        return 'EX_DATE_PASSED'
    return 'ANNOUNCED'


def _date_or_dash_slots(tokens: list[str]) -> list[str]:
    """保留日期與「-」占位，讓欄位可依 Yahoo 表格順序精準對齊。"""
    return [
        _clean_token(token)
        for token in tokens
        if _DATE_RE.fullmatch(_clean_token(token))
        or _clean_token(token) in _DASHES
    ]


def _parse_candidate_tokens(
    tokens: list[str],
    instrument: Instrument,
) -> CorporateAction | None:
    """解析單一股利列，並按 Yahoo 欄位順序對齊日期。

    Yahoo 欄位順序：發放期間、所屬期間、現金股利、股票股利、殖利率、
    除息日昨收價、除息日、除權日、現金股利發放日、股票股利發放日、
    填息天數。
    """
    tokens = _dedupe_consecutive(tokens)
    if len(tokens) < 5:
        return None

    date_positions = [
        index for index, token in enumerate(tokens)
        if _DATE_RE.fullmatch(token)
    ]
    if not date_positions:
        return None
    first_date_index = date_positions[0]

    period_positions = [
        index for index, token in enumerate(tokens[:first_date_index])
        if _PERIOD_RE.fullmatch(token)
    ]
    if not period_positions:
        return None

    # 一列通常同時有「發放期間」與「所屬期間」，取日期前最後一個期間。
    period_index = period_positions[-1]
    period = _normalize_period(tokens[period_index])

    before_dates = tokens[period_index + 1:first_date_index]
    amount_fields = [
        token for token in before_dates
        if token in _DASHES
        or _NUMBER_RE.fullmatch(token.replace(',', ''))
        or token.endswith('%')
    ]
    if not amount_fields:
        return None

    cash_dividend = _parse_number(amount_fields[0])
    if cash_dividend <= 0:
        return None

    # 依欄位占位對齊：slot[0]=除息日、slot[1]=除權日、
    # slot[2]=現金股利發放日、slot[3]=股票股利發放日。
    date_slots = _date_or_dash_slots(tokens[first_date_index:])
    ex_dividend_date = (
        _normalize_date(date_slots[0]) if date_slots else ''
    )
    if not ex_dividend_date:
        return None

    payment_date = ''
    if len(date_slots) >= 3:
        payment_date = _normalize_date(date_slots[2])

    # 某些頁面容器會省略「-」占位；此時退回第二個實際日期。
    if not payment_date:
        real_dates = [
            _normalize_date(token)
            for token in tokens[first_date_index:]
            if _DATE_RE.fullmatch(token)
        ]
        real_dates = [value for value in real_dates if value]
        if len(real_dates) >= 2:
            payment_date = real_dates[1]

    return CorporateAction(
        symbol=instrument.symbol,
        stock_code=instrument.stock_code,
        stock_name=instrument.name,
        action_date=ex_dividend_date,
        action_type='DIVIDEND',
        value=cash_dividend,
        source='yahoo_tw_scraper',
        period=period,
        payment_date=payment_date,
        announcement_status=_announcement_status(
            ex_dividend_date,
            payment_date,
        ),
    )


def parse_dividend_html(
    html_text: str,
    instrument: Instrument,
) -> list[CorporateAction]:
    """從 Yahoo 台灣股利政策 HTML 解析現金股利。"""
    soup = BeautifulSoup(html_text, 'html.parser')
    candidate_token_lists: list[list[str]] = []

    for tag in soup.find_all(['tr', 'li']):
        tokens = list(tag.stripped_strings)
        if any(_PERIOD_RE.fullmatch(_clean_token(token)) for token in tokens):
            if any(_DATE_RE.fullmatch(_clean_token(token)) for token in tokens):
                candidate_token_lists.append(tokens)

    period_strings = soup.find_all(
        string=lambda value: bool(
            value and _PERIOD_RE.fullmatch(_clean_token(value))
        )
    )
    for text_node in period_strings:
        node = text_node.parent
        for _depth in range(8):
            if node is None:
                break
            tokens = list(node.stripped_strings)
            if (
                5 <= len(tokens) <= 28
                and any(
                    _DATE_RE.fullmatch(_clean_token(token))
                    for token in tokens
                )
            ):
                candidate_token_lists.append(tokens)
                break
            node = node.parent

    parsed: dict[tuple[str, str, float], CorporateAction] = {}
    for tokens in candidate_token_lists:
        action = _parse_candidate_tokens(tokens, instrument)
        if action is None:
            continue
        key = (action.action_date, action.period, round(action.value, 8))
        parsed[key] = action

    return sorted(
        parsed.values(),
        key=lambda item: (item.action_date, item.period, item.value),
    )


class YahooTwDividendScraper:
    """低頻率抓取已登錄持股的 Yahoo 台灣股利政策頁。"""

    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        self.settings = (settings or RuntimeSettings()).normalized()
        self._thread_local = threading.local()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0 Safari/537.36'
            ),
            'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.6',
            'Cache-Control': 'no-cache',
        })
        return session

    def _get_session(self) -> requests.Session:
        session = getattr(self._thread_local, 'session', None)
        if session is None:
            session = self._create_session()
            self._thread_local.session = session
        return session

    def update_settings(self, settings: RuntimeSettings) -> None:
        self.settings = settings.normalized()

    def fetch_dividends(
        self,
        instrument: Instrument,
        progress: ProgressCallback | None = None,
    ) -> list[CorporateAction]:
        """抓取一檔商品股利政策，失敗時依設定重試。"""
        url = YAHOO_TW_DIVIDEND_PAGE.format(symbol=instrument.symbol)
        last_error: Exception | None = None

        for attempt in range(1, self.settings.item_retries + 1):
            try:
                if progress:
                    progress(
                        f'[爬蟲／Yahoo 台灣] {instrument.symbol}：'
                        f'第 {attempt}/{self.settings.item_retries} 次嘗試',
                        attempt,
                        self.settings.item_retries,
                    )
                response = self._get_session().get(
                    url,
                    timeout=self.settings.scraper_timeout_seconds,
                )
                response.raise_for_status()
                actions = parse_dividend_html(response.text, instrument)

                if not actions and '歷年股利政策' not in response.text:
                    raise YahooTwScraperError(
                        '頁面內容不完整，可能被限流或頁面結構已改版'
                    )

                filtered = filter_actions_by_range(
                    actions,
                    self.settings.action_period,
                )
                if self.settings.scraper_delay_seconds > 0:
                    time.sleep(self.settings.scraper_delay_seconds)
                return filtered
            except Exception as exc:
                last_error = exc
                if progress:
                    progress(
                        f'[爬蟲／Yahoo 台灣] {instrument.symbol} '
                        f'第 {attempt} 次失敗：{exc}',
                        attempt,
                        self.settings.item_retries,
                    )
                if attempt < self.settings.item_retries:
                    time.sleep(self.settings.retry_backoff_seconds * attempt)

        raise YahooTwScraperError(
            f'{instrument.symbol} 股利政策頁重試 '
            f'{self.settings.item_retries} 次仍失敗：{last_error}'
        )
