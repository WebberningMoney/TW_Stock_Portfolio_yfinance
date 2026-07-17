from __future__ import annotations

import math
import re
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from matplotlib import colormaps, font_manager, rcParams
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

from app.config import (
    EXPORT_DIR,
    MARKET_CHOICES,
    MARKET_LABEL_TO_KEY,
    UNIVERSE_CATEGORY_CHOICES,
)
from app.models import Holding
from app.services.dividend_service import (
    PENDING,
    REALIZED,
    build_dividend_projection,
    group_month_components,
    summarize_monthly,
    summarize_year,
)
from app.services.portfolio_service import build_holding_views, summarize_portfolio
from app.ui.universe_dialog import UniverseSelectionDialog
from app.utils import decimal, money, normalize_stock_code, percent


class HoldingsMixin:
    @staticmethod
    def _market_label(market_key: str) -> str:
        """將資料庫內部市場代碼轉成中文顯示。"""
        return MARKET_CHOICES.get(market_key, market_key or MARKET_CHOICES['AUTO'])

    def _selected_market_key(self) -> str:
        """將下拉選單中文顯示值轉回內部代碼。"""
        value = self.market_var.get().strip()
        if value in MARKET_CHOICES:
            return value
        return MARKET_LABEL_TO_KEY.get(value, 'AUTO')

    def _find_local_instrument(self, code: str):
        """優先使用本機商品清冊，避免輸入持股時每次都連線 Yahoo。"""
        candidates = self.database.find_instruments_by_code(code)
        if not candidates:
            return None

        selected_market = self._selected_market_key()
        if selected_market != 'AUTO':
            matched = [
                item for item in candidates
                if item.market_segment == selected_market
                or (
                    selected_market == 'TWSE'
                    and item.symbol.endswith('.TW')
                )
                or (
                    selected_market in {'TPEX', 'EMERGING'}
                    and item.symbol.endswith('.TWO')
                )
            ]
            if matched:
                candidates = matched

        category_priority = {
            'TWSE_STOCK': 0,
            'TPEX_STOCK': 0,
            'TWSE_ETF': 1,
            'TPEX_ETF': 1,
            'ETN': 2,
            'OTHER': 3,
            'WARRANT': 4,
        }
        candidates.sort(
            key=lambda item: (
                category_priority.get(item.product_category, 9),
                0 if item.symbol.endswith('.TW') else 1,
                item.symbol,
            )
        )
        return candidates[0]

    def _apply_resolved_instrument(
        self,
        instrument,
        focus_shares: bool = True,
    ) -> None:
        self.stock_code_var.set(instrument.stock_code)
        self.yahoo_symbol_var.set(instrument.symbol)
        self.stock_name_var.set(instrument.name)
        if self._selected_market_key() == 'AUTO':
            self.market_var.set(
                self._market_label(instrument.market_segment)
            )
        self.status_var.set(
            f'已辨識：{instrument.stock_code} {instrument.name}'
        )
        if focus_shares:
            self.root.after_idle(self._focus_shares_entry)

    def _resolve_input_async(self, code: str) -> None:
        """輸入流程專用解析：不切換到 LOG 分頁。"""
        if self.busy:
            messagebox.showinfo(
                '作業進行中',
                '目前有資料同步作業進行中，請稍後再解析代號。',
            )
            self._focus_stock_code_entry()
            return

        self.status_var.set(f'正在解析 {code}……')
        self._set_busy(True)

        def task():
            try:
                instrument = self.sync_service.resolve_and_save_instrument(
                    code,
                    self._selected_market_key(),
                )
            except Exception as exc:
                message = str(exc)
                self.root.after(
                    0,
                    lambda m=message: self._finish_input_resolve_error(m),
                )
            else:
                self.root.after(
                    0,
                    lambda item=instrument: self._finish_input_resolve(item),
                )

        threading.Thread(target=task, daemon=True).start()

    def _finish_input_resolve(self, instrument) -> None:
        self._set_busy(False)
        self._apply_resolved_instrument(instrument, focus_shares=True)
        self.refresh_loaded_data_view()

    def _finish_input_resolve_error(self, message: str) -> None:
        self._set_busy(False)
        self.status_var.set('代號解析失敗')
        messagebox.showerror('代號解析失敗', message)
        self._focus_stock_code_entry()

    def _on_stock_code_commit(self, _event=None):
        code = normalize_stock_code(self.stock_code_var.get())
        if not code:
            self.root.bell()
            self._focus_stock_code_entry()
            return 'break'

        # 使用者改了代號時，清除上一檔解析結果。
        current_symbol = self.yahoo_symbol_var.get().strip()
        if current_symbol and not current_symbol.startswith(code):
            self.yahoo_symbol_var.set('')
            self.stock_name_var.set('')

        local_instrument = self._find_local_instrument(code)
        if local_instrument is not None:
            self._apply_resolved_instrument(local_instrument, focus_shares=True)
        else:
            self._resolve_input_async(code)
        return 'break'

    def _on_shares_commit(self, _event=None):
        try:
            shares = int(self.shares_var.get().replace(',', '').strip())
            if shares <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror('輸入錯誤', '持有股數必須是大於 0 的整數。')
            self._focus_shares_entry()
            return 'break'
        self.root.after_idle(self._focus_total_cost_entry)
        return 'break'

    def _on_total_cost_commit(self, _event=None):
        self.confirm_save_holding()
        return 'break'

    def resolve_symbol(self) -> None:
        code = normalize_stock_code(self.stock_code_var.get())
        if not code:
            messagebox.showwarning('欄位不足', '請輸入股票代號。')
            self._focus_stock_code_entry()
            return

        local_instrument = self._find_local_instrument(code)
        if local_instrument is not None:
            self._apply_resolved_instrument(local_instrument, focus_shares=True)
            return

        self._run_background(
            f'正在解析 {code}……',
            lambda: self.sync_service.resolve_and_save_instrument(
                code, self._selected_market_key()
            ),
            self._after_resolve,
        )

    def _after_resolve(self, instrument) -> None:
        self._apply_resolved_instrument(instrument, focus_shares=True)
        message = f'已解析：{instrument.symbol} {instrument.name}'
        self.refresh_loaded_data_view()
        self._finish_operation(message)

    def _holding_from_form(self) -> Holding | None:
        code = normalize_stock_code(self.stock_code_var.get())
        symbol = self.yahoo_symbol_var.get().strip().upper()
        name = self.stock_name_var.get().strip()
        if not symbol or not name:
            messagebox.showwarning(
                '尚未解析',
                '請先輸入股票代號並按 Enter 或 Tab，讓程式帶入股票名稱。',
            )
            self._focus_stock_code_entry()
            return None
        try:
            shares = int(self.shares_var.get().replace(',', '').strip())
            total_cost = float(
                self.total_cost_var.get().replace(',', '').strip()
            )
        except ValueError:
            messagebox.showerror(
                '輸入錯誤',
                '股數必須是整數，總成本必須是數字。',
            )
            return None
        if shares <= 0 or total_cost < 0:
            messagebox.showerror(
                '輸入錯誤',
                '股數必須大於 0，總成本不可小於 0。',
            )
            return None
        return Holding(
            None,
            code,
            symbol,
            name,
            self._selected_market_key(),
            shares,
            total_cost,
        )

    def confirm_save_holding(self) -> None:
        """
        顯示確認視窗；messagebox 預設按鈕可直接再按一次 Enter 完成。
        """
        holding = self._holding_from_form()
        if holding is None:
            return

        average_cost = (
            holding.total_cost / holding.shares
            if holding.shares > 0
            else 0.0
        )
        existing_symbols = {
            item.yahoo_symbol for item in self.database.list_holdings()
        }
        action_text = '更新' if holding.yahoo_symbol in existing_symbols else '新增'
        confirmed = messagebox.askokcancel(
            f'確認{action_text}持股',
            f'{holding.stock_code} {holding.stock_name}\n'
            f'持有股數：{holding.shares:,} 股\n'
            f'持有總成本：NT$ {holding.total_cost:,.0f}\n'
            f'平均成本：NT$ {average_cost:,.2f}\n\n'
            f'按 Enter 或「確定」完成{action_text}。',
            default='ok',
        )
        if not confirmed:
            self._focus_total_cost_entry()
            return
        self.save_holding(holding)

    def save_holding(self, holding: Holding | None = None) -> None:
        """寫入資料庫；可由確認流程傳入已驗證的 Holding。"""
        if holding is None:
            holding = self._holding_from_form()
            if holding is None:
                return
        self.database.upsert_holding(holding)
        self.status_var.set(
            f'已儲存 {holding.stock_code} {holding.stock_name}'
        )
        self.clear_form()
        self.refresh_all_views()
        self.root.after_idle(self._focus_stock_code_entry)

    def delete_selected_holding(self) -> None:
        selected = self.holding_tree.selection()
        if not selected:
            messagebox.showinfo('尚未選取', '請先選取持股。')
            return
        symbol = str(
            self.holding_tree.item(selected[0], 'values')[0]
        )
        if messagebox.askyesno(
            '確認刪除', f'確定刪除 {symbol}？'
        ):
            self.database.delete_holding(symbol)
            self.clear_form()
            self.refresh_all_views()

    def on_holding_selected(self, _event=None) -> None:
        selected = self.holding_tree.selection()
        if not selected:
            return
        values = self.holding_tree.item(selected[0], 'values')
        self.yahoo_symbol_var.set(values[0])
        self.stock_code_var.set(values[1])
        self.stock_name_var.set(values[2])
        market_value = str(values[3])
        self.market_var.set(
            market_value
            if market_value in MARKET_LABEL_TO_KEY
            else self._market_label(market_value)
        )
        self.shares_var.set(str(values[4]).replace(',', ''))
        self.total_cost_var.set(str(values[5]).replace(',', ''))
        self._refresh_ai_prompts()

    def clear_form(self) -> None:
        variables = (
            self.stock_code_var,
            self.yahoo_symbol_var,
            self.stock_name_var,
            self.shares_var,
            self.total_cost_var,
        )
        for variable in variables:
            variable.set('')
        self.market_var.set(MARKET_CHOICES['AUTO'])

    def clear_form_and_focus(self) -> None:
        self.clear_form()
        self.root.after_idle(self._focus_stock_code_entry)

    def _focus_stock_code_entry(self) -> None:
        """儲存完成後將輸入焦點移回股票代號，方便連續輸入。"""
        entry = getattr(self, 'stock_code_entry', None)
        if entry is not None:
            entry.focus_set()
            entry.selection_range(0, 'end')
            entry.icursor('end')

    def _focus_shares_entry(self) -> None:
        entry = getattr(self, 'shares_entry', None)
        if entry is not None:
            entry.focus_set()
            entry.selection_range(0, 'end')
            entry.icursor('end')

    def _focus_total_cost_entry(self) -> None:
        entry = getattr(self, 'total_cost_entry', None)
        if entry is not None:
            entry.focus_set()
            entry.selection_range(0, 'end')
            entry.icursor('end')

    def refresh_holding_view(self) -> None:
        selected_symbol = ''
        current_selection = self.holding_tree.selection()
        if current_selection:
            values = self.holding_tree.item(current_selection[0], 'values')
            if values:
                selected_symbol = str(values[0])

        holdings = self.database.list_holdings()
        views = build_holding_views(
            holdings, self.database.get_quote_map()
        )
        self._holding_view_by_symbol = {item.symbol: item for item in views}
        summary = summarize_portfolio(views)

        query = self.holding_search_var.get().strip().casefold()
        visible_views = views
        if query:
            visible_views = [
                item for item in views
                if query in item.symbol.casefold()
                or query in item.stock_code.casefold()
                or query in item.stock_name.casefold()
                or query in self._market_label(item.market_segment).casefold()
            ]
        if hasattr(self, 'holding_count_var'):
            self.holding_count_var.set(
                f'顯示 {len(visible_views)}／{len(views)} 檔'
            )

        self.holding_tree.tag_configure(
            'positive', foreground=self.colors['positive']
        )
        self.holding_tree.tag_configure(
            'negative', foreground=self.colors['negative']
        )
        self.holding_tree.tag_configure(
            'neutral', foreground=self.colors['neutral']
        )

        for item in self.holding_tree.get_children():
            self.holding_tree.delete(item)

        selected_item_id = None
        for view in visible_views:
            row_tag = (
                'positive' if view.profit > 0
                else 'negative' if view.profit < 0
                else 'neutral'
            )
            item_id = self.holding_tree.insert(
                '',
                'end',
                values=(
                    view.symbol,
                    view.stock_code,
                    view.stock_name,
                    self._market_label(view.market_segment),
                    f'{view.shares:,}',
                    money(view.total_cost),
                    decimal(view.average_cost),
                    decimal(view.close),
                    money(view.market_value),
                    money(view.profit),
                    percent(view.return_rate),
                    view.trade_date or '未更新',
                ),
                tags=(row_tag,),
            )
            if view.symbol == selected_symbol:
                selected_item_id = item_id

        if selected_item_id is not None:
            self.holding_tree.selection_set(selected_item_id)
            self.holding_tree.focus(selected_item_id)
            self._refresh_ai_prompts()
        elif not views:
            self.ai_selected_var.set('請先在庫存表選取一檔持股')

        self.summary_cost_var.set(
            f'NT$ {money(summary.total_cost)}'
        )
        self.summary_value_var.set(
            f'NT$ {money(summary.total_market_value)}'
        )
        self.summary_profit_var.set(
            f'NT$ {money(summary.total_profit)}'
        )
        self.summary_return_var.set(
            percent(summary.total_return_rate)
        )

        if hasattr(self, 'summary_value_labels'):
            result_style = (
                'Positive.Summary.TLabel'
                if summary.total_profit > 0
                else 'Negative.Summary.TLabel'
                if summary.total_profit < 0
                else 'Summary.TLabel'
            )
            self.summary_value_labels[2].configure(style=result_style)
            self.summary_value_labels[3].configure(style=result_style)
