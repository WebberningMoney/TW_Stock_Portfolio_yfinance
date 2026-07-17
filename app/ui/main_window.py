"""主視窗協調器。

v2.0 將原本超過 2,400 行的單一類別拆成數個 mixin；本檔只保留狀態初始化、
跨頁協調與全域 UX。各功能可在 app/ui/mixins/ 中獨立維護。
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from app.config import DIVIDEND_SOURCE_CHOICES, MARKET_CHOICES
from app.db.database import Database
from app.services.sync_service import SyncService
from app.settings import SettingsStore
from app.ui.mixins.ai_workspace import AiWorkspaceMixin
from app.ui.mixins.base import StyleMixin
from app.ui.mixins.dividend_page import DividendPageMixin
from app.ui.mixins.holdings import HoldingsMixin
from app.ui.mixins.layout import LayoutMixin
from app.ui.mixins.loaded_data_page import LoadedDataPageMixin
from app.ui.mixins.operations import OperationsMixin
from app.ui.mixins.settings_page import SettingsPageMixin


class PortfolioApp(
    StyleMixin,
    LayoutMixin,
    HoldingsMixin,
    DividendPageMixin,
    LoadedDataPageMixin,
    OperationsMixin,
    SettingsPageMixin,
    AiWorkspaceMixin,
):
    def __init__(self, root: tk.Tk, database: Database) -> None:
        self.root = root
        self.database = database
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self.sync_service = SyncService(database, settings=self.settings)
        self.busy = False
        self.sync_buttons: list[ttk.Button] = []

        self.stock_code_var = tk.StringVar()
        self.yahoo_symbol_var = tk.StringVar()
        self.stock_name_var = tk.StringVar()
        self.market_var = tk.StringVar(value=MARKET_CHOICES['AUTO'])
        self.dividend_source_var = tk.StringVar(
            value=DIVIDEND_SOURCE_CHOICES[self.settings.dividend_source_mode]
        )
        self.shares_var = tk.StringVar()
        self.total_cost_var = tk.StringVar()
        self.dividend_year_var = tk.StringVar(value=str(date.today().year))
        self.dividend_month_var = tk.StringVar(
            value=f'{date.today().year}-{date.today().month:02d}'
        )
        self.status_var = tk.StringVar(value='就緒')

        self.summary_cost_var = tk.StringVar(value='NT$ 0')
        self.summary_value_var = tk.StringVar(value='NT$ 0')
        self.summary_profit_var = tk.StringVar(value='NT$ 0')
        self.summary_return_var = tk.StringVar(value='0.00%')

        self.dividend_realized_var = tk.StringVar(value='NT$ 0')
        self.dividend_pending_var = tk.StringVar(value='NT$ 0')
        self.dividend_total_var = tk.StringVar(value='NT$ 0')

        self.loaded_search_var = tk.StringVar()
        self.holding_search_var = tk.StringVar()
        self.holding_count_var = tk.StringVar(value='')
        self.ai_sidebar_visible = True
        self.loaded_count_var = tk.StringVar(value='')
        self.log_status_var = tk.StringVar(value='尚未執行下載作業')
        self.ai_selected_var = tk.StringVar(value='請先在庫存表選取一檔持股')

        self._loaded_instruments = []
        self._loaded_quotes: list[dict] = []
        self._loaded_actions = []
        self._dividend_projections = []
        self._dividend_month_groups = {}
        self._dividend_chart_annotation = None
        self._dividend_month_patches: dict[int, list] = {}
        self._holding_view_by_symbol: dict[str, object] = {}

        self._build_style()
        self._build_layout()
        self._configure_responsive_window()
        self._bind_global_shortcuts()
        self.loaded_search_var.trace_add(
            'write', lambda *_args: self._render_loaded_data()
        )
        self.holding_search_var.trace_add(
            'write', lambda *_args: self.refresh_holding_view()
        )
        self.refresh_all_views()

    def _configure_responsive_window(self) -> None:
        """依目前螢幕重新校正視窗，兼顧 13 吋筆電與大型外接螢幕。"""
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # 盡量使用螢幕可用空間，仍保留少量邊界避免遮到 macOS 選單列／Dock。
        width = min(1800, max(1180, int(screen_w * 0.96)))
        height = max(760, screen_h - 48)
        height = min(height, 1180)
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2, 0)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        # 筆電或窄螢幕預設收合 AI 研究區，優先保留庫存表寬度。
        if screen_w < 1500 and getattr(self, 'ai_sidebar_visible', False):
            self.root.after(350, self._toggle_ai_sidebar)

    def _bind_global_shortcuts(self) -> None:
        """提供 macOS 與 Windows/Linux 都可使用的高頻快捷鍵。"""
        for modifier in ('Command', 'Control'):
            self.root.bind_all(
                f'<{modifier}-l>',
                lambda _event: self._focus_stock_code_entry(),
            )
            self.root.bind_all(
                f'<{modifier}-s>',
                lambda _event: self.confirm_save_holding(),
            )
            self.root.bind_all(
                f'<{modifier}-k>',
                lambda _event: self._focus_loaded_search(),
            )
        self.root.bind_all('<Escape>', lambda _event: self.clear_form_and_focus())

    def _focus_loaded_search(self) -> None:
        """切換至已載入資料頁並聚焦搜尋框。"""
        try:
            self.main_notebook.select(2)
            self.loaded_search_entry.focus_set()
            self.loaded_search_entry.selection_range(0, 'end')
        except (AttributeError, tk.TclError):
            pass

    def _on_main_tab_changed(self, _event=None) -> None:
        """切換到配息分頁時，再依實際可用高度設定分隔位置。"""
        try:
            selected = self.main_notebook.nametowidget(
                self.main_notebook.select()
            )
        except (tk.TclError, KeyError):
            return
        if selected is getattr(self, 'dividend_tab', None):
            self.root.after(80, self._set_default_dividend_sash)
        elif selected is getattr(self, 'holding_tab', None):
            self.root.after(80, self._set_default_holding_sash)

    def refresh_all_views(self) -> None:
        self.refresh_holding_view()
        self.refresh_dividend_view()
        self.refresh_loaded_data_view()
