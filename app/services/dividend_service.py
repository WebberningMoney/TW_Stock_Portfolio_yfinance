"""
每月配息估算。

資料日期是 Yahoo 歷史 actions 的除息日，不是實際入帳日。
規則：
- 目標年度已有的股利事件標為「Yahoo 已發生」。
- 目標年度尚無事件的月份，使用最近一個有完整事件的年度作為模板，
  標為「歷史模式估算」。
- 同一 symbol、同一月份若已有目標年度實際事件，不再加上模板，避免重複。
"""

from dataclasses import dataclass
from datetime import date
from collections import defaultdict

from app.models import CorporateAction, Holding


@dataclass(slots=True)
class DividendProjection:
    month: str
    symbol: str
    stock_code: str
    stock_name: str
    shares: int
    dividend_per_share: float
    estimated_amount: float
    basis: str
    reference_date: str


def _year_month(date_text: str) -> tuple[int, int] | None:
    try:
        year, month, _day = map(int, date_text.split('-'))
        return year, month
    except (ValueError, AttributeError):
        return None


def build_dividend_projection(
    holdings: list[Holding],
    actions: list[CorporateAction],
    target_year: int | None = None,
) -> list[DividendProjection]:
    if target_year is None:
        target_year = date.today().year

    holding_map = {holding.yahoo_symbol: holding for holding in holdings}
    dividends = [a for a in actions if a.action_type == 'DIVIDEND' and a.symbol in holding_map]
    by_symbol_year: dict[str, dict[int, list[CorporateAction]]] = defaultdict(lambda: defaultdict(list))

    for action in dividends:
        parsed = _year_month(action.action_date)
        if parsed:
            by_symbol_year[action.symbol][parsed[0]].append(action)

    result: list[DividendProjection] = []
    for symbol, years in by_symbol_year.items():
        holding = holding_map[symbol]
        actual = years.get(target_year, [])
        actual_months: set[int] = set()

        for action in actual:
            parsed = _year_month(action.action_date)
            if not parsed:
                continue
            month = parsed[1]
            actual_months.add(month)
            result.append(
                DividendProjection(
                    month=f'{target_year}-{month:02d}',
                    symbol=symbol,
                    stock_code=holding.stock_code,
                    stock_name=holding.stock_name,
                    shares=holding.shares,
                    dividend_per_share=action.value,
                    estimated_amount=holding.shares * action.value,
                    basis='Yahoo 已發生（除息日）',
                    reference_date=action.action_date,
                )
            )

        # 優先使用目標年度之前最近的有股利年度；若沒有則使用資料中最近年度。
        prior_years = sorted((year for year in years if year < target_year), reverse=True)
        template_year = prior_years[0] if prior_years else (max(years) if years else None)
        if template_year is None:
            continue

        for action in years[template_year]:
            parsed = _year_month(action.action_date)
            if not parsed or parsed[1] in actual_months:
                continue
            month = parsed[1]
            result.append(
                DividendProjection(
                    month=f'{target_year}-{month:02d}',
                    symbol=symbol,
                    stock_code=holding.stock_code,
                    stock_name=holding.stock_name,
                    shares=holding.shares,
                    dividend_per_share=action.value,
                    estimated_amount=holding.shares * action.value,
                    basis=f'{template_year} 歷史模式估算',
                    reference_date=action.action_date,
                )
            )

    result.sort(key=lambda item: (item.month, item.symbol, item.reference_date))
    return result


def summarize_monthly(
    projections: list[DividendProjection],
    target_year: int,
) -> list[tuple[str, float]]:
    monthly = {f'{target_year}-{month:02d}': 0.0 for month in range(1, 13)}
    for item in projections:
        monthly[item.month] = monthly.get(item.month, 0.0) + item.estimated_amount
    return sorted(monthly.items())
