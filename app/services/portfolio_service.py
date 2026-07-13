"""庫存市值、損益與報酬率計算。"""

from dataclasses import dataclass

from app.models import Holding


@dataclass(slots=True)
class HoldingView:
    symbol: str
    stock_code: str
    stock_name: str
    market_segment: str
    shares: int
    total_cost: float
    average_cost: float
    close: float
    market_value: float
    profit: float
    return_rate: float
    trade_date: str


@dataclass(slots=True)
class PortfolioSummary:
    total_cost: float
    total_market_value: float
    total_profit: float
    total_return_rate: float


def build_holding_views(
    holdings: list[Holding],
    quote_map: dict[str, dict],
) -> list[HoldingView]:
    result: list[HoldingView] = []
    for holding in holdings:
        quote = quote_map.get(holding.yahoo_symbol, {})
        close = float(quote.get('close') or 0.0)
        market_value = close * holding.shares
        profit = market_value - holding.total_cost
        return_rate = profit / holding.total_cost * 100 if holding.total_cost else 0.0
        result.append(
            HoldingView(
                symbol=holding.yahoo_symbol,
                stock_code=holding.stock_code,
                stock_name=holding.stock_name,
                market_segment=holding.market_segment,
                shares=holding.shares,
                total_cost=holding.total_cost,
                average_cost=holding.average_cost,
                close=close,
                market_value=market_value,
                profit=profit,
                return_rate=return_rate,
                trade_date=str(quote.get('trade_date') or ''),
            )
        )
    return result


def summarize_portfolio(views: list[HoldingView]) -> PortfolioSummary:
    total_cost = sum(item.total_cost for item in views)
    total_market_value = sum(item.market_value for item in views)
    total_profit = total_market_value - total_cost
    total_return_rate = total_profit / total_cost * 100 if total_cost else 0.0
    return PortfolioSummary(total_cost, total_market_value, total_profit, total_return_rate)
