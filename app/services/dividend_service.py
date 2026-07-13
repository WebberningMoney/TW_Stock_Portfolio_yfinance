"""
年度股利分析與每月現金流預估。

資料來源優先順序
----------------
1. Yahoo 台灣股利政策頁爬蟲：可取得所屬期間、除息日、現金發放日，並可
   補入已公告但尚未出現在 yfinance 歷史序列的未來股利。
2. yfinance：補足歷史現金股利與股票分割。
3. 歷史模式估算：只有未來仍缺公告時才使用。

「已實現／未領」判定
--------------------
- 有現金發放日：發放日已到才列為已實現；未到列為未領。
- 沒有發放日（純 yfinance 歷史事件）：以除息日是否已到作為替代判定。
- 金額仍以目前持有股數估算，並非券商實際入帳紀錄。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from calendar import monthrange

from app.models import CorporateAction, Holding

REALIZED = 'REALIZED'
PENDING = 'PENDING'

_SOURCE_PRIORITY = {
    'yahoo_tw_scraper': 30,
    'yfinance': 20,
}


@dataclass(slots=True)
class DividendProjection:
    """單一持股的一次年度股利事件或預估事件。"""

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
class DividendYearSummary:
    """年度股利三項摘要。"""

    realized_amount: float
    pending_amount: float

    @property
    def total_amount(self) -> float:
        return self.realized_amount + self.pending_amount


def _parse_date(date_text: str) -> date | None:
    try:
        year, month, day = map(int, date_text.split('-'))
        return date(year, month, day)
    except (ValueError, AttributeError):
        return None


def _safe_date(year: int, month: int, day: int) -> date:
    """建立模板日期；2/29 等日期會自動縮至該月最後一天。"""
    return date(year, month, min(day, monthrange(year, month)[1]))


def _cashflow_date(action: CorporateAction) -> date | None:
    """優先使用現金發放日，沒有時退回除息日。"""
    return _parse_date(action.payment_date) or _parse_date(action.action_date)


def _dedupe_dividends(actions: list[CorporateAction]) -> list[CorporateAction]:
    """
    同一代號、同一除息日可能同時存在 yfinance 與網頁爬蟲資料。

    Yahoo 台灣股利政策頁有發放日與所屬期間，因此優先於 yfinance；避免同一
    筆股利被重複計算。
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
    payment_day = _parse_date(action.payment_date)
    if payment_day:
        return REALIZED if payment_day <= as_of else PENDING
    ex_day = _parse_date(action.action_date)
    return REALIZED if ex_day and ex_day <= as_of else PENDING


def _event_basis(action: CorporateAction, status: str) -> str:
    if action.source == 'yahoo_tw_scraper':
        if action.payment_date:
            return (
                'Yahoo 台灣股利政策：已發放'
                if status == REALIZED
                else f'Yahoo 台灣已公告；預計 {action.payment_date} 發放'
            )
        return (
            'Yahoo 台灣股利政策（除息日已到）'
            if status == REALIZED
            else 'Yahoo 台灣已公告（尚無發放日）'
        )
    return (
        'yfinance 歷史股利（除息日已到）'
        if status == REALIZED
        else 'yfinance 已知未來事件'
    )


def build_dividend_projection(
    holdings: list[Holding],
    actions: list[CorporateAction],
    target_year: int | None = None,
    as_of_date: date | None = None,
) -> list[DividendProjection]:
    """建立目標年度的股利分析清單。"""
    as_of = as_of_date or date.today()
    if target_year is None:
        target_year = as_of.year

    holding_map = {holding.yahoo_symbol: holding for holding in holdings}
    dividends = _dedupe_dividends([
        action
        for action in actions
        if action.symbol in holding_map
    ])

    # 依實際／預計現金發放年度分組；沒有發放日才使用除息年度。
    by_symbol_year: dict[str, dict[int, list[CorporateAction]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for action in dividends:
        flow_date = _cashflow_date(action)
        if flow_date:
            by_symbol_year[action.symbol][flow_date.year].append(action)

    result: list[DividendProjection] = []

    for symbol, years in by_symbol_year.items():
        holding = holding_map[symbol]
        actual_events = sorted(
            years.get(target_year, []),
            key=lambda item: _cashflow_date(item) or date.min,
        )
        actual_months: set[int] = set()

        for action in actual_events:
            flow_date = _cashflow_date(action)
            if not flow_date:
                continue
            actual_months.add(flow_date.month)
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

        # 過去年度只顯示已存在的資料，不使用模板補估。
        if target_year < as_of.year:
            continue

        prior_years = sorted(
            (year for year in years if year < target_year),
            reverse=True,
        )
        if not prior_years:
            continue
        template_year = prior_years[0]

        for action in sorted(
            years[template_year],
            key=lambda item: _cashflow_date(item) or date.min,
        ):
            template_date = _cashflow_date(action)
            if not template_date or template_date.month in actual_months:
                continue

            projected_date = _safe_date(
                target_year,
                template_date.month,
                template_date.day,
            )
            if target_year == as_of.year and projected_date <= as_of:
                continue

            result.append(
                DividendProjection(
                    month=f'{target_year}-{projected_date.month:02d}',
                    symbol=symbol,
                    stock_code=holding.stock_code,
                    stock_name=holding.stock_name,
                    shares=holding.shares,
                    dividend_per_share=action.value,
                    estimated_amount=holding.shares * action.value,
                    status=PENDING,
                    basis=f'{template_year} 年歷史發放模式估算',
                    reference_date=projected_date.isoformat(),
                    payment_date=projected_date.isoformat(),
                    period='歷史模式估算',
                    source='projection',
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
    """將明細彙總成 12 個月份。"""
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
    """依月份分組，供 GUI 長條圖 tooltip 與月份組成表使用。"""
    grouped: dict[str, list[DividendProjection]] = defaultdict(list)
    for item in projections:
        grouped[item.month].append(item)
    for items in grouped.values():
        items.sort(key=lambda item: item.estimated_amount, reverse=True)
    return dict(grouped)
