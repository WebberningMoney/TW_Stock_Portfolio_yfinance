"""持股檢視（HoldingView）快取與目前選取狀態，無 Tkinter 依賴。"""

from dataclasses import dataclass, field

from app.models import Holding
from app.services.portfolio_service import HoldingView, build_holding_views


@dataclass(slots=True)
class HoldingViewState:
    _views_by_symbol: dict[str, HoldingView] = field(default_factory=dict)
    _selected_symbol: str | None = None

    def refresh(self, holdings: list[Holding], quotes: dict[str, dict]) -> None:
        views = build_holding_views(holdings, quotes)
        self._views_by_symbol = {view.symbol: view for view in views}

    def select(self, symbol: str | None) -> None:
        self._selected_symbol = symbol

    def selected(self) -> HoldingView | None:
        if self._selected_symbol is None:
            return None
        return self._views_by_symbol.get(self._selected_symbol)

    def get(self, symbol: str) -> HoldingView | None:
        return self._views_by_symbol.get(symbol)

    def views(self) -> list[HoldingView]:
        return list(self._views_by_symbol.values())
