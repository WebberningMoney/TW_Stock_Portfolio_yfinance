"""
年度股利分析與每月配息預估。

資料限制
--------
yfinance 的歷史股利日期通常是「除息日」，不是實際入帳日；而本程式目前
只儲存使用者的「現在持有股數」，沒有逐筆交易歷史。因此：

- 已實現股利：目標年度中，除息日已到的 Yahoo 股利事件，依目前持股股數估算。
- 未領股利：除息日尚未到的已知事件，或依最近歷史年度配息模式推估的未來事件。
- 過去年度不補歷史模式估算，避免把從未發生的股利誤列為已實現。
- 目前年度只估算今天之後的缺漏月份；未來年度則以最近歷史年度作模板。

若未來加入「交易明細／實際入帳紀錄」，便可進一步做到精準的實領股利統計。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from calendar import monthrange

from app.models import CorporateAction, Holding

REALIZED = 'REALIZED'
PENDING = 'PENDING'


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


def build_dividend_projection(
    holdings: list[Holding],
    actions: list[CorporateAction],
    target_year: int | None = None,
    as_of_date: date | None = None,
) -> list[DividendProjection]:
    """
    建立目標年度的股利分析清單。

    as_of_date 可在測試時指定；GUI 省略時使用今天。
    """
    as_of = as_of_date or date.today()
    if target_year is None:
        target_year = as_of.year

    holding_map = {holding.yahoo_symbol: holding for holding in holdings}
    dividends = [
        action
        for action in actions
        if action.action_type == 'DIVIDEND'
        and action.symbol in holding_map
        and action.value > 0
    ]

    by_symbol_year: dict[str, dict[int, list[CorporateAction]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for action in dividends:
        event_date = _parse_date(action.action_date)
        if event_date:
            by_symbol_year[action.symbol][event_date.year].append(action)

    result: list[DividendProjection] = []

    for symbol, years in by_symbol_year.items():
        holding = holding_map[symbol]
        actual_events = sorted(
            years.get(target_year, []),
            key=lambda item: item.action_date,
        )
        actual_months: set[int] = set()

        # 目標年度 Yahoo 已有的真實股利事件。
        for action in actual_events:
            event_date = _parse_date(action.action_date)
            if not event_date:
                continue
            actual_months.add(event_date.month)
            status = REALIZED if event_date <= as_of else PENDING
            result.append(
                DividendProjection(
                    month=f'{target_year}-{event_date.month:02d}',
                    symbol=symbol,
                    stock_code=holding.stock_code,
                    stock_name=holding.stock_name,
                    shares=holding.shares,
                    dividend_per_share=action.value,
                    estimated_amount=holding.shares * action.value,
                    status=status,
                    basis=(
                        'Yahoo 已發生（除息日已到）'
                        if status == REALIZED
                        else 'Yahoo 已知事件（除息日未到）'
                    ),
                    reference_date=action.action_date,
                )
            )

        # 過去年度只顯示真實事件，不做補估。
        if target_year < as_of.year:
            continue

        # 使用目標年度之前最近一個有股利的年度作為模板。
        prior_years = sorted(
            (year for year in years if year < target_year),
            reverse=True,
        )
        if not prior_years:
            continue
        template_year = prior_years[0]

        for action in sorted(
            years[template_year], key=lambda item: item.action_date
        ):
            template_date = _parse_date(action.action_date)
            if not template_date or template_date.month in actual_months:
                continue

            projected_date = _safe_date(
                target_year,
                template_date.month,
                template_date.day,
            )

            # 當年度缺漏的過去日期不補估，避免把「沒有發生」當成已領。
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
                    basis=f'{template_year} 歷史模式估算',
                    reference_date=projected_date.isoformat(),
                )
            )

    result.sort(
        key=lambda item: (
            item.month,
            item.status != REALIZED,
            item.symbol,
            item.reference_date,
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
