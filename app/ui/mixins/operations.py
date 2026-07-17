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
    DIVIDEND_SOURCE_LABEL_TO_KEY,
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


class OperationsMixin:
    def _build_log_tab(self, parent) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill='x', pady=(0, 8))

        ttk.Label(
            controls,
            textvariable=self.log_status_var,
        ).pack(side='left')
        ttk.Button(
            controls,
            text='清除 LOG',
            command=self.clear_log,
        ).pack(side='right')

        self.progress_bar = ttk.Progressbar(
            parent,
            orient='horizontal',
            mode='determinate',
            maximum=100,
        )
        self.progress_bar.pack(fill='x', pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(
            parent,
            wrap='word',
            height=22,
            font=('Menlo', 11),
            state='disabled',
            background='#0F172A',
            foreground='#E2E8F0',
            insertbackground='#FFFFFF',
            relief='flat',
        )
        self.log_text.pack(fill='both', expand=True)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for button in self.sync_buttons:
            button.configure(state='disabled' if busy else 'normal')

    def _append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.configure(state='normal')
        self.log_text.insert('end', f'[{timestamp}] {message}\n')
        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def clear_log(self) -> None:
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.configure(state='disabled')

    def _begin_operation(self, label: str) -> None:
        self.main_notebook.select(self.log_tab)
        self.status_var.set(label)
        self.log_status_var.set(label)
        self.progress_bar.stop()
        self.progress_bar.configure(mode='indeterminate', maximum=100)
        self.progress_bar.start(10)
        self._append_log(f'開始：{label}')
        self._set_busy(True)

    def _finish_operation(self, message: str) -> None:
        self.progress_bar.stop()
        self.progress_bar.configure(mode='determinate', maximum=100)
        self.progress_bar['value'] = 100
        self.status_var.set(message)
        self.log_status_var.set(message)
        self._append_log(f'完成：{message}')
        self._set_busy(False)

    def _run_background(self, label: str, worker, success_handler) -> None:
        if self.busy:
            messagebox.showinfo(
                '作業進行中',
                '目前已有下載或更新作業正在執行，請先查看 LOG。',
            )
            self.main_notebook.select(self.log_tab)
            return

        self._begin_operation(label)

        def task():
            try:
                result = worker()
            except Exception as exc:
                message = str(exc)
                self.root.after(
                    0,
                    lambda m=message: self._show_error(m),
                )
            else:
                self.root.after(
                    0,
                    lambda r=result: success_handler(r),
                )

        threading.Thread(target=task, daemon=True).start()

    def _progress(
        self,
        message: str,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        self.root.after(
            0,
            lambda m=message, c=current, t=total: (
                self._apply_progress(m, c, t)
            ),
        )

    def _apply_progress(
        self,
        message: str,
        current: int | None,
        total: int | None,
    ) -> None:
        self.status_var.set(message)
        self.log_status_var.set(message)
        self._append_log(message)

        if current is not None and total and total > 0:
            self.progress_bar.stop()
            self.progress_bar.configure(
                mode='determinate', maximum=total
            )
            self.progress_bar['value'] = min(current, total)

    def _show_error(self, message: str) -> None:
        self.progress_bar.stop()
        self.progress_bar.configure(mode='determinate', maximum=100)
        self.progress_bar['value'] = 0
        self.status_var.set('操作失敗')
        self.log_status_var.set('操作失敗')
        self._append_log(f'錯誤：{message}')
        self._set_busy(False)
        self.main_notebook.select(self.log_tab)
        messagebox.showerror('操作失敗', message)

    def discover_universe_async(self) -> None:
        options = UniverseSelectionDialog(self.root).show()
        if not options:
            return

        category_names = [
            UNIVERSE_CATEGORY_CHOICES[key]
            for key in sorted(options['categories'])
        ]
        self._append_log('本次清冊範圍：' + '、'.join(category_names))

        self._run_background(
            '正在建立 Yahoo 台灣商品清冊……',
            lambda: self.sync_service.discover_universe(
                selected_categories=options['categories'],
                enrich_names=options['enrich_names'],
                rebuild=options['rebuild'],
                progress=self._progress,
            ),
            lambda count: self._after_sync(
                f'商品清冊完成：{count} 檔'
            ),
        )

    def sync_all_quotes_async(self) -> None:
        self._run_background(
            '正在更新全部商品行情……',
            lambda: self.sync_service.sync_all_quotes(self._progress),
            lambda result: self._after_sync(
                f'行情完成：成功 {result[0]}，失敗 {result[1]}'
            ),
        )

    def sync_holding_quotes_async(self) -> None:
        self._run_background(
            '正在更新持股行情……',
            lambda: self.sync_service.sync_holding_quotes(self._progress),
            lambda result: self._after_sync(
                f'持股行情：成功 {result[0]}，失敗 {result[1]}'
            ),
        )

    def sync_actions_async(self) -> None:
        source_mode = DIVIDEND_SOURCE_LABEL_TO_KEY.get(
            self.dividend_source_var.get(),
            'BOTH',
        )
        source_label = self.dividend_source_var.get()
        range_code = self.settings.action_period
        confirmed = messagebox.askokcancel(
            '確認重建股利資料',
            f'本次來源：{source_label}\n'
            f'抓取範圍：最近 {range_code}\n\n'
            '系統會先清除所選來源的既有股利／分割資料，'
            '再依目前參數完整重建。下載失敗的項目可能暫時沒有資料。\n\n'
            '是否繼續？',
            default='ok',
        )
        if not confirmed:
            return

        self._append_log(
            f'本次股利載入來源：{source_label}；抓取範圍：{range_code}'
        )
        self._run_background(
            f'正在重建持股股利資料（{source_label}／{range_code}）……',
            lambda: self.sync_service.sync_holding_actions(
                source_mode=source_mode,
                progress=self._progress,
            ),
            lambda result: self._after_sync(
                f'已清除舊資料 {result.cleared_count} 筆；'
                f'yfinance 股利／分割 {result.history_action_count} 筆；'
                f'Yahoo 台灣股利政策 {result.announced_dividend_count} 筆；'
                f'範圍 {result.range_code}；失敗 {result.failed_count} 個'
            ),
        )

    def _after_sync(self, message: str) -> None:
        self.refresh_all_views()
        self._finish_operation(message)
        messagebox.showinfo('完成', message)
