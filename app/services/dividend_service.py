"""
年度股利分析與未來現金流預估。

這個模組刻意把「已經抓到的真實資料」與「尚未公告的推估資料」分開：

1. Yahoo 台灣股利政策爬蟲
   可取得所屬期間、除息日、現金發放日，最適合補足「公司／ETF 已公告，
   但 yfinance 歷史資料還看不到」的股利。
2. yfinance
   主要提供已經發生的歷史股利與股票分割。
3. 歷史模式估算
   只有目標年度仍有尚未公告的期次時才產生，而且會依商品近年的配息頻率
   選擇不同方式：
   - 年配：沿用最近一次年度股利。
   - 半年配：沿用最近一期金額，每 6 個月往後推估。
   - 季配：沿用最近一季金額，每 3 個月往後推估。
   - 月配：沿用最近一個月金額，每 1 個月往後推估。

重要提醒：所有金額均以「目前持有股數」估算，不等同券商實際入帳紀錄。
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median
import re

from app.models import CorporateAction, Holding

REALIZED = 'REALIZED'
PENDING = 'PENDING'

_SOURCE_PRIORITY = {
    'yahoo_tw_scraper': 30,
    'yfinance': 20,
}


@dataclass(slots=True)
class DividendProjection:
    """單一持股的一次實際、已公告或歷史模式估算股利。"""

    month: str
    symbol: str
    stock_code: str
    stock_name: str
    shares: int
    dividend_per_share: float
    estimated_amount: float
    status: str
    basis: str
    reference_date: str
    payment_date: str = ''
    period: str = ''
    source: str = ''

    @property
    def status_text(self) -> str:
        return '已實現' if self.status == REALIZED else '未領／預估'


@dataclass(slots=True)
class MonthlyDividendSummary:
    """單月已實現、未領與合計。"""

    month: str
    realized_amount: float
    pending_amount: float

    @property
    def total_amount(self) -> float:
        return self.realized_amount + self.pending_amount


@dataclass(slots=True)
class QuarterlyDividendSummary:
    """單季已實現、未領與合計。"""

    quarter: str
    realized_amount: float
    pending_amount: float

    @property
    def total_amount(self) -> float:
        return self.realized_amount + self.pending_amount


@dataclass(slots=True)
class DividendYearSummary:
    """年度股利三項摘要。"""

    realized_amount: float
    pending_amount: float

    @property
    def total_amount(self) -> float:
        return self.realized_amount + self.pending_amount


@dataclass(frozen=True, slots=True)
class DistributionPattern:
    """由歷史資料推測出的配息週期。"""

    months: int
    label: str


_DISTRIBUTION_PATTERNS = {
    1: DistributionPattern(1, '月配'),
    3: DistributionPattern(3, '季配'),
    6: DistributionPattern(6, '半年配'),
    12: DistributionPattern(12, '年配'),
}


def _parse_date(date_text: str) -> date | None:
    try:
        year, month, day = map(int, date_text.split('-'))
        return date(year, month, day)
    except (ValueError, AttributeError):
        return None


def _safe_date(year: int, month: int, day: int) -> date:
    """建立合法日期；例如 2/29 遇到平年會自動改成 2/28。"""
    return date(year, month, min(day, monthrange(year, month)[1]))


def _add_months(source: date, months: int) -> date:
    """將日期往後推指定月數，同時處理月底天數不同的情況。"""
    zero_based = source.year * 12 + source.month - 1 + months
    year, month_index = divmod(zero_based, 12)
    month = month_index + 1
    return _safe_date(year, month, source.day)


def _cashflow_date(action: CorporateAction) -> date | None:
    """現金流月份優先使用發放日；沒有發放日才使用除息日。"""
    return _parse_date(action.payment_date) or _parse_date(action.action_date)


def _dedupe_dividends(actions: list[CorporateAction]) -> list[CorporateAction]:
    """
    合併同一代號、同一除息日的重複股利。

    同一事件可能同時存在於 yfinance 與 Yahoo 台灣爬蟲；爬蟲通常多出
    「所屬期間、現金發放日、公告狀態」，因此欄位較完整時優先保留爬蟲。
    """
    chosen: dict[tuple[str, str], CorporateAction] = {}
    for action in actions:
        if action.action_type != 'DIVIDEND' or action.value <= 0:
            continue
        key = (action.symbol, action.action_date)
        current = chosen.get(key)
        if current is None:
            chosen[key] = action
            continue

        action_score = _SOURCE_PRIORITY.get(action.source, 0)
        current_score = _SOURCE_PRIORITY.get(current.source, 0)
        if action.payment_date:
            action_score += 2
        if current.payment_date:
            current_score += 2
        if action.period:
            action_score += 1
        if current.period:
            current_score += 1
        if action_score >= current_score:
            chosen[key] = action

    return sorted(
        chosen.values(),
        key=lambda item: (
            item.symbol,
            _cashflow_date(item) or date.min,
            item.action_date,
        ),
    )


def _event_status(action: CorporateAction, as_of: date) -> str:
    """有發放日就以發放日判斷；否則以除息日代替。"""
    payment_day = _parse_date(action.payment_date)
    if payment_day:
        return REALIZED if payment_day <= as_of else PENDING
    ex_day = _parse_date(action.action_date)
    return REALIZED if ex_day and ex_day <= as_of else PENDING


def _event_basis(action: CorporateAction, status: str) -> str:
    """用白話描述該筆資料為何被歸類為已實現或未領。"""
    if action.source == 'yahoo_tw_scraper':
        if action.payment_date:
            return (
                'Yahoo 台灣股利政策：現金發放日已到'
                if status == REALIZED
                else f'Yahoo 台灣已公告：預計 {action.payment_date} 發放'
            )
        return (
            'Yahoo 台灣股利政策：除息日已到，但頁面未提供發放日'
            if status == REALIZED
            else 'Yahoo 台灣已公告：頁面尚未提供現金發放日'
        )
    return (
        'yfinance 歷史股利：除息日已到'
        if status == REALIZED
        else 'yfinance 已提供未來股利事件'
    )


def _infer_distribution_pattern(
    events: list[CorporateAction],
) -> DistributionPattern:
    """
    由最近的所屬期間與發放間隔推測月配、季配、半年配或年配。

    判斷順序：
    1. Yahoo 所屬期間若明確含 Q1～Q4，直接視為季配。
    2. 所屬期間若明確含 H1／H2，直接視為半年配。
    3. 其餘用最近幾次現金流日期的間隔中位數判斷。
    4. 資料只有一筆時，保守視為年配，避免憑空產生過多預估。
    """
    recent_events = sorted(
        (event for event in events if _cashflow_date(event)),
        key=lambda item: _cashflow_date(item) or date.min,
    )[-10:]

    recent_periods = [str(event.period or '').upper() for event in recent_events]
    if any(re.search(r'Q[1-4]', value) for value in recent_periods):
        return _DISTRIBUTION_PATTERNS[3]
    if any(re.search(r'H[12]', value) for value in recent_periods):
        return _DISTRIBUTION_PATTERNS[6]

    dates = sorted({
        flow_date
        for event in recent_events
        if (flow_date := _cashflow_date(event)) is not None
    })
    if len(dates) < 2:
        return _DISTRIBUTION_PATTERNS[12]

    intervals = [
        (current - previous).days
        for previous, current in zip(dates, dates[1:])
        if current > previous
    ]
    if not intervals:
        return _DISTRIBUTION_PATTERNS[12]

    # 歷史資料可能因抓取期間較短而漏掉中間幾期，例如只看到 1 月、4 月、
    # 隔年 1 月。此時 9 個月的長間隔其實是「漏了兩季」，所以用最近資料中
    # 最短的正常間隔當作基礎週期，比直接取中位數更不容易把季配誤判成半年配。
    typical_days = float(min(intervals[-8:]))
    if typical_days <= 50:
        return _DISTRIBUTION_PATTERNS[1]
    if typical_days <= 150:
        return _DISTRIBUTION_PATTERNS[3]
    if typical_days <= 250:
        return _DISTRIBUTION_PATTERNS[6]
    return _DISTRIBUTION_PATTERNS[12]


def _forecast_future_events(
    symbol: str,
    holding: Holding,
    events: list[CorporateAction],
    target_year: int,
    as_of: date,
) -> list[DividendProjection]:
    """
    依最近一期配息政策補出尚未公告的未來期次。

    年配商品只會補下一次年度股利；季配與月配則會從最近一筆已知資料往後
    逐期推算，金額沿用「最近一回」而不是去年同一月份。這能更貼近配息型
    ETF 在配息政策調整後的實際狀況。
    """
    if target_year < as_of.year:
        return []

    dated_events = sorted(
        (
            (flow_date, event)
            for event in events
            if (flow_date := _cashflow_date(event)) is not None
            and flow_date <= date(target_year, 12, 31)
        ),
        key=lambda pair: pair[0],
    )
    if not dated_events:
        return []

    pattern = _infer_distribution_pattern(events)
    seed_date, seed_event = dated_events[-1]
    projected_date = _add_months(seed_date, pattern.months)

    # 若最近資料停留在更早年度，持續往後推到目標年度。
    while projected_date.year < target_year:
        projected_date = _add_months(projected_date, pattern.months)

    actual_dates = [
        flow_date
        for flow_date, _event in dated_events
        if flow_date.year == target_year
    ]
    tolerance_days = {1: 18, 3: 45, 6: 75, 12: 120}[pattern.months]
    result: list[DividendProjection] = []

    while projected_date.year == target_year:
        # 目標年度為今年時，已經過去卻沒有任何公告／歷史事件的日期不補估，
        # 避免把「實際沒有配息」誤當成遺漏資料。
        is_past_without_event = target_year == as_of.year and projected_date <= as_of
        overlaps_actual = any(
            abs((actual_date - projected_date).days) <= tolerance_days
            for actual_date in actual_dates
        )

        if not is_past_without_event and not overlaps_actual:
            result.append(
                DividendProjection(
                    month=f'{target_year}-{projected_date.month:02d}',
                    symbol=symbol,
                    stock_code=holding.stock_code,
                    stock_name=holding.stock_name,
                    shares=holding.shares,
                    dividend_per_share=seed_event.value,
                    estimated_amount=holding.shares * seed_event.value,
                    status=PENDING,
                    basis=(
                        f'最近一期配息模式估算（{pattern.label}）：'
                        f'沿用 {seed_date.isoformat()} 每股 '
                        f'{seed_event.value:g} 元'
                    ),
                    reference_date=projected_date.isoformat(),
                    payment_date=projected_date.isoformat(),
                    period=f'{pattern.label}歷史模式估算',
                    source='projection',
                )
            )

        projected_date = _add_months(projected_date, pattern.months)

    return result


def build_dividend_projection(
    holdings: list[Holding],
    actions: list[CorporateAction],
    target_year: int | None = None,
    as_of_date: date | None = None,
) -> list[DividendProjection]:
    """建立目標年度的實際、已公告與歷史模式估算股利清單。"""
    as_of = as_of_date or date.today()
    if target_year is None:
        target_year = as_of.year

    holding_map = {holding.yahoo_symbol: holding for holding in holdings}
    dividends = _dedupe_dividends([
        action
        for action in actions
        if action.symbol in holding_map
    ])

    by_symbol: dict[str, list[CorporateAction]] = defaultdict(list)
    for action in dividends:
        by_symbol[action.symbol].append(action)

    result: list[DividendProjection] = []

    for symbol, events in by_symbol.items():
        holding = holding_map[symbol]
        events.sort(key=lambda item: _cashflow_date(item) or date.min)

        # 第一階段：先放入目標年度確實存在的歷史／公告資料。
        for action in events:
            flow_date = _cashflow_date(action)
            if not flow_date or flow_date.year != target_year:
                continue
            status = _event_status(action, as_of)
            result.append(
                DividendProjection(
                    month=f'{target_year}-{flow_date.month:02d}',
                    symbol=symbol,
                    stock_code=holding.stock_code,
                    stock_name=holding.stock_name,
                    shares=holding.shares,
                    dividend_per_share=action.value,
                    estimated_amount=holding.shares * action.value,
                    status=status,
                    basis=_event_basis(action, status),
                    reference_date=action.action_date,
                    payment_date=action.payment_date,
                    period=action.period,
                    source=action.source,
                )
            )

        # 第二階段：對今年或未來年度，依最近一期政策補足尚未公告的期次。
        result.extend(
            _forecast_future_events(
                symbol=symbol,
                holding=holding,
                events=events,
                target_year=target_year,
                as_of=as_of,
            )
        )

    result.sort(
        key=lambda item: (
            item.month,
            item.status != REALIZED,
            item.symbol,
            item.payment_date or item.reference_date,
        )
    )
    return result


def summarize_monthly(
    projections: list[DividendProjection],
    target_year: int,
) -> list[MonthlyDividendSummary]:
    """將股利明細彙總成固定 12 個月份。"""
    realized = {f'{target_year}-{month:02d}': 0.0 for month in range(1, 13)}
    pending = {f'{target_year}-{month:02d}': 0.0 for month in range(1, 13)}

    for item in projections:
        if item.status == REALIZED:
            realized[item.month] = realized.get(item.month, 0.0) + item.estimated_amount
        else:
            pending[item.month] = pending.get(item.month, 0.0) + item.estimated_amount

    return [
        MonthlyDividendSummary(
            month=month,
            realized_amount=realized[month],
            pending_amount=pending[month],
        )
        for month in sorted(realized)
    ]


def summarize_quarterly(
    projections: list[DividendProjection],
    target_year: int,
) -> list[QuarterlyDividendSummary]:
    """彙總 Q1～Q4 的已實現、未領與合計。"""
    realized = {quarter: 0.0 for quarter in range(1, 5)}
    pending = {quarter: 0.0 for quarter in range(1, 5)}

    for item in projections:
        try:
            year_text, month_text = item.month.split('-', maxsplit=1)
            if int(year_text) != target_year:
                continue
            quarter = (int(month_text) - 1) // 3 + 1
        except (ValueError, AttributeError):
            continue
        if item.status == REALIZED:
            realized[quarter] += item.estimated_amount
        else:
            pending[quarter] += item.estimated_amount

    return [
        QuarterlyDividendSummary(
            quarter=f'Q{quarter}',
            realized_amount=realized[quarter],
            pending_amount=pending[quarter],
        )
        for quarter in range(1, 5)
    ]


def summarize_year(
    projections: list[DividendProjection],
) -> DividendYearSummary:
    """計算目標年度已實現、未領與總和。"""
    realized_amount = sum(
        item.estimated_amount
        for item in projections
        if item.status == REALIZED
    )
    pending_amount = sum(
        item.estimated_amount
        for item in projections
        if item.status == PENDING
    )
    return DividendYearSummary(realized_amount, pending_amount)


def group_month_components(
    projections: list[DividendProjection],
) -> dict[str, list[DividendProjection]]:
    """依月份分組，提供圖表提示與右側月份組成表使用。"""
    grouped: dict[str, list[DividendProjection]] = defaultdict(list)
    for item in projections:
        grouped[item.month].append(item)
    for items in grouped.values():
        items.sort(key=lambda item: item.estimated_amount, reverse=True)
    return dict(grouped)
