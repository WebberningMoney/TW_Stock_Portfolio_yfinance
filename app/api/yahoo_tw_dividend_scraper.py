"""
Yahoo 台灣「股利政策」頁面補強器。

用途
----
yfinance 的歷史股利資料通常只會在除息事件發生後出現；本模組只針對
使用者已登錄的持股，讀取 Yahoo 台灣公開股利政策頁，以補入：

- 股利所屬期間
- 已公告的每股現金股利
- 除息日
- 現金股利發放日

注意
----
1. 這是網頁擷取，不是 Yahoo 正式公開 API，頁面結構改版時可能需要更新。
2. 程式採低頻率、逐檔抓取、最多三次重試，不做全市場大量爬取。
3. 使用者應自行確認資料使用符合網站服務條款；資料僅供個人研究管理。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime
import re
import time
from typing import Any

from bs4 import BeautifulSoup
import requests

from app.config import (
    HTTP_ITEM_RETRIES,
    RETRY_BACKOFF_SECONDS,
    YAHOO_TW_DIVIDEND_PAGE,
    YAHOO_TW_REQUEST_DELAY_SECONDS,
)
from app.models import CorporateAction, Instrument

ProgressCallback = Callable[[str, int | None, int | None], None]

_PERIOD_RE = re.compile(
    r'^\d{4}(?:\s*[-/]?\s*(?:Q[1-4]|H[12]))?$',
    re.IGNORECASE,
)
_DATE_RE = re.compile(r'^\d{4}[/-]\d{1,2}[/-]\d{1,2}$')
_NUMBER_RE = re.compile(r'^-?\d+(?:,\d{3})*(?:\.\d+)?$')


class YahooTwScraperError(RuntimeError):
    """Yahoo 台灣股利頁抓取或解析失敗。"""


def _clean_token(value: Any) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _normalize_period(value: str) -> str:
    """
    將 Yahoo 的股利所屬期間統一成可比較格式。

    支援：
    - 年度：2026
    - 季度：2026Q1～2026Q4
    - 半年度：2026H1、2026H2

    Yahoo 頁面偶爾會在年份與期間代碼間加入空白、斜線或連字號，
    因此先移除這些分隔字元後再正規化。
    """
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
    if text in {'', '-', '--', '–', '—'} or text.endswith('%'):
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


def _parse_candidate_tokens(
    tokens: list[str],
    instrument: Instrument,
) -> CorporateAction | None:
    """
    解析單一股利列。

    Yahoo 頁面的視覺欄位順序通常是：
    發放期間、所屬期間、現金股利、股票股利、殖利率、除息前收盤、
    除息日、除權日、現金發放日、股票發放日、填息天數。
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
        if token in {'-', '--', '–', '—'}
        or _NUMBER_RE.fullmatch(token.replace(',', ''))
        or token.endswith('%')
    ]
    if not amount_fields:
        return None

    cash_dividend = _parse_number(amount_fields[0])
    stock_dividend = (
        _parse_number(amount_fields[1])
        if len(amount_fields) >= 2
        else 0.0
    )
    if cash_dividend <= 0:
        return None

    dates = [_normalize_date(tokens[index]) for index in date_positions]
    dates = [value for value in dates if value]
    if not dates:
        return None

    ex_dividend_date = dates[0]

    # 現金與股票股利同時存在時，日期順序可能為：除息、除權、現金發放、
    # 股票發放；只有現金股利時，日期清單通常為：除息、現金發放。
    payment_date = ''
    if stock_dividend > 0 and len(dates) >= 3:
        payment_date = dates[2]
    elif len(dates) >= 2:
        payment_date = dates[1]

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
    """
    從 Yahoo 台灣股利政策 HTML 解析現金股利。

    採多層容錯：
    1. 先掃描 tr/li 等常見列容器。
    2. 再由期間文字向上尋找最小、且含日期的列容器。
    """
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
            token_count = len(tokens)
            if (
                5 <= token_count <= 28
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

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0 Safari/537.36'
            ),
            'Accept-Language': 'zh-TW,zh;q=0.9,en;q=0.6',
            'Cache-Control': 'no-cache',
        })

    def fetch_dividends(
        self,
        instrument: Instrument,
        progress: ProgressCallback | None = None,
    ) -> list[CorporateAction]:
        """抓取一檔商品股利政策；每個項目最多嘗試三次。"""
        url = YAHOO_TW_DIVIDEND_PAGE.format(symbol=instrument.symbol)
        last_error: Exception | None = None

        for attempt in range(1, HTTP_ITEM_RETRIES + 1):
            try:
                if progress:
                    progress(
                        f'[爬蟲／Yahoo 台灣已公告] {instrument.symbol}：'
                        f'第 {attempt}/{HTTP_ITEM_RETRIES} 次嘗試',
                        attempt,
                        HTTP_ITEM_RETRIES,
                    )
                response = self.session.get(url, timeout=25)
                response.raise_for_status()
                actions = parse_dividend_html(response.text, instrument)

                # 股利頁存在但完全解析不到列時，視為解析失敗；重試後明確報告。
                if not actions and '歷年股利政策' not in response.text:
                    raise YahooTwScraperError(
                        '頁面內容不完整，可能被限流或頁面結構已改版'
                    )

                time.sleep(YAHOO_TW_REQUEST_DELAY_SECONDS)
                return actions
            except Exception as exc:  # requests 與解析錯誤統一重試
                last_error = exc
                if progress:
                    progress(
                        f'[爬蟲／Yahoo 台灣已公告] {instrument.symbol} 第 {attempt} 次失敗：'
                        f'{exc}',
                        attempt,
                        HTTP_ITEM_RETRIES,
                    )
                if attempt < HTTP_ITEM_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)

        raise YahooTwScraperError(
            f'{instrument.symbol} 已公告股利頁重試 '
            f'{HTTP_ITEM_RETRIES} 次仍失敗：{last_error}'
        )
