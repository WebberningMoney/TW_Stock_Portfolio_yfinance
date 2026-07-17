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
    DIVIDEND_SOURCE_CHOICES,
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


class LayoutMixin:
    def _build_layout(self) -> None:
        """建立主畫面：頁首、快速輸入、摘要、功能分頁與狀態列。"""
        outer = ttk.Frame(self.root, padding=(14, 12, 14, 10))
        outer.pack(fill='both', expand=True)
        self._build_app_header(outer)
        self._build_input_panel(outer)
        self._build_sync_panel(outer)
        self._build_summary(outer)
        self._build_notebook(outer)
        self._build_status_bar(outer)

    def _build_app_header(self, parent: ttk.Frame) -> None:
        """加入較清楚的產品識別與操作提示。"""
        header = ttk.Frame(parent, style='Card.TFrame', padding=(14, 9))
        header.pack(fill='x', pady=(0, 9))

        title_box = ttk.Frame(header, style='Card.TFrame')
        title_box.pack(side='left', fill='x', expand=True)
        ttk.Label(
            title_box,
            text='台股資產與股息儀表板',
            style='Header.Title.TLabel',
        ).pack(anchor='w')
        ttk.Label(
            title_box,
            text='持股、損益、yfinance 歷史資料、Yahoo 台灣股利政策與研究提示整合',
            style='Header.Subtitle.TLabel',
        ).pack(anchor='w', pady=(2, 0))

        ttk.Label(
            header,
            text='⌘/Ctrl+L  股票代號　⌘/Ctrl+S  儲存　Esc  清空',
            style='Header.Subtitle.TLabel',
        ).pack(side='right', padx=(15, 0))

    def _build_status_bar(self, parent: ttk.Frame) -> None:
        """建立固定狀態列，避免下載或輸入狀態被忽略。"""
        ttk.Separator(parent).pack(fill='x', pady=(8, 4))
        bar = ttk.Frame(parent)
        bar.pack(fill='x')
        ttk.Label(bar, textvariable=self.status_var).pack(side='left')
        ttk.Label(
            bar,
            text='v2.2｜多來源資料僅供研究，不構成投資建議',
            foreground=self.colors['muted'],
        ).pack(side='right')


    def _build_input_panel(self, parent: ttk.Frame) -> None:
        """建立單列鍵盤優先的持股輸入區，減少垂直空間占用。"""
        frame = ttk.LabelFrame(parent, text='快速新增／修改持股', padding=(9, 7))
        frame.pack(fill='x', pady=(0, 6))

        fields = [
            ('股票代號', 'code'),
            ('股票名稱', 'name'),
            ('持有股數', 'shares'),
            ('持有總成本', 'cost'),
            ('市場', 'market'),
        ]
        for index, (label, _key) in enumerate(fields):
            ttk.Label(frame, text=label).grid(
                row=0, column=index * 2, padx=(4, 3), sticky='e'
            )

        self.stock_code_entry = ttk.Entry(
            frame, textvariable=self.stock_code_var, width=11
        )
        self.stock_code_entry.grid(row=0, column=1, padx=(0, 8))

        self.stock_name_entry = ttk.Entry(
            frame, textvariable=self.stock_name_var, width=20, state='readonly'
        )
        self.stock_name_entry.grid(row=0, column=3, padx=(0, 8))

        self.shares_entry = ttk.Entry(
            frame, textvariable=self.shares_var, width=12
        )
        self.shares_entry.grid(row=0, column=5, padx=(0, 8))

        self.total_cost_entry = ttk.Entry(
            frame, textvariable=self.total_cost_var, width=15
        )
        self.total_cost_entry.grid(row=0, column=7, padx=(0, 8))

        self.market_combo = ttk.Combobox(
            frame,
            textvariable=self.market_var,
            values=list(MARKET_CHOICES.values()),
            width=24,
            state='readonly',
        )
        self.market_combo.grid(row=0, column=9, padx=(0, 8))

        button_specs = [
            ('解析', self.resolve_symbol, 'TButton'),
            ('確認並儲存', self.confirm_save_holding, 'Accent.TButton'),
            ('刪除選取', self.delete_selected_holding, 'TButton'),
            ('清空', self.clear_form_and_focus, 'TButton'),
        ]
        for offset, (text, command, style_name) in enumerate(button_specs):
            ttk.Button(
                frame,
                text=text,
                command=command,
                style=style_name,
            ).grid(row=0, column=10 + offset, padx=3)

        frame.columnconfigure(14, weight=1)
        ttk.Label(
            frame,
            text='Enter／Tab：代號 → 股數 → 總成本 → 確認',
            foreground=self.colors['muted'],
        ).grid(row=0, column=14, sticky='e', padx=(10, 3))

        self.stock_code_entry.bind('<Return>', self._on_stock_code_commit)
        self.stock_code_entry.bind('<Tab>', self._on_stock_code_commit)
        self.shares_entry.bind('<Return>', self._on_shares_commit)
        self.shares_entry.bind('<Tab>', self._on_shares_commit)
        self.total_cost_entry.bind('<Return>', self._on_total_cost_commit)

    def _build_sync_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(
            parent,
            text='資料來源與同步',
            padding=6,
        )
        frame.pack(fill='x', pady=(0, 6))

        first_row = ttk.Frame(frame)
        first_row.pack(fill='x')
        button_specs = [
            (
                '① 選擇類型並建立商品清冊',
                self.discover_universe_async,
            ),
            ('② 更新全部商品行情', self.sync_all_quotes_async),
            ('更新持股行情', self.sync_holding_quotes_async),
        ]
        for index, (text, command) in enumerate(button_specs):
            button = ttk.Button(
                first_row,
                text=text,
                command=command,
                style='Accent.TButton' if index == 0 else 'TButton',
            )
            button.pack(side='left', padx=4)
            self.sync_buttons.append(button)

        ttk.Separator(frame, orient='horizontal').pack(fill='x', pady=7)
        second_row = ttk.Frame(frame)
        second_row.pack(fill='x')
        ttk.Label(second_row, text='股利載入來源：').pack(side='left', padx=(4, 3))
        self.dividend_source_combo = ttk.Combobox(
            second_row,
            textvariable=self.dividend_source_var,
            values=list(DIVIDEND_SOURCE_CHOICES.values()),
            state='readonly',
            width=36,
        )
        self.dividend_source_combo.pack(side='left', padx=(0, 7))
        self.dividend_source_combo.bind(
            '<<ComboboxSelected>>',
            lambda _event: self.remember_dividend_source(),
        )
        action_button = ttk.Button(
            second_row,
            text='③ 更新持股股利資料',
            command=self.sync_actions_async,
            style='Accent.TButton',
        )
        action_button.pack(side='left', padx=4)
        self.sync_buttons.append(action_button)

        ttk.Label(
            second_row,
            text=(
                '同步前會清除選定來源舊資料；抓取範圍與效能參數可在設定頁調整。'
                '下載過程請查看 LOG。'
            ),
            foreground=self.colors['muted'],
        ).pack(side='left', padx=12)

    def _build_summary(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(
            parent,
            text='投資組合總覽',
            padding=8,
        )
        frame.pack(fill='x', pady=(0, 8))
        cards = [
            ('總投入成本', self.summary_cost_var, 'Summary.TLabel'),
            ('最新庫存總值', self.summary_value_var, 'Summary.TLabel'),
            ('未實現損益', self.summary_profit_var, 'Summary.TLabel'),
            ('預估報酬率', self.summary_return_var, 'Summary.TLabel'),
        ]
        self.summary_value_labels: list[ttk.Label] = []
        for index, (title, variable, style_name) in enumerate(cards):
            box = ttk.Frame(frame, padding=6, style='Card.TFrame')
            box.grid(row=0, column=index, sticky='nsew', padx=7)
            frame.columnconfigure(index, weight=1)
            ttk.Label(
                box, text=title, style='Card.TLabel'
            ).pack()
            value_label = ttk.Label(
                box,
                textvariable=variable,
                style=style_name,
            )
            value_label.pack(pady=(5, 0))
            self.summary_value_labels.append(value_label)

    def _build_notebook(self, parent: ttk.Frame) -> None:
        self.main_notebook = ttk.Notebook(parent)
        self.main_notebook.pack(fill='both', expand=True)

        holding_tab = ttk.Frame(self.main_notebook, padding=7)
        self.holding_tab = holding_tab
        dividend_tab = ttk.Frame(self.main_notebook, padding=7)
        self.dividend_tab = dividend_tab
        data_tab = ttk.Frame(self.main_notebook, padding=7)
        self.settings_tab = ttk.Frame(self.main_notebook, padding=7)
        self.log_tab = ttk.Frame(self.main_notebook, padding=7)

        self.main_notebook.add(holding_tab, text='庫存與損益')
        self.main_notebook.add(dividend_tab, text='每月配息估算')
        self.main_notebook.add(data_tab, text='已載入資料')
        self.main_notebook.add(self.settings_tab, text='抓取參數／單筆測試')
        self.main_notebook.add(self.log_tab, text='下載進度／LOG')

        holding_toolbar = ttk.Frame(holding_tab)
        holding_toolbar.pack(fill='x', pady=(0, 6))
        ttk.Label(holding_toolbar, text='搜尋持股：').pack(side='left')
        self.holding_search_entry = ttk.Entry(
            holding_toolbar,
            textvariable=self.holding_search_var,
            width=24,
        )
        self.holding_search_entry.pack(side='left', padx=(0, 8))
        ttk.Label(
            holding_toolbar,
            textvariable=self.holding_count_var,
            foreground=self.colors['muted'],
        ).pack(side='left')
        self.ai_toggle_button = ttk.Button(
            holding_toolbar,
            text='隱藏 AI 研究區',
            command=self._toggle_ai_sidebar,
        )
        self.ai_toggle_button.pack(side='right')
        ttk.Label(
            holding_toolbar,
            text='雙擊持股可快速修改股數；Yahoo Symbol 已隱藏但仍保留於資料庫。',
            foreground=self.colors['muted'],
        ).pack(side='right', padx=10)

        # 左側為庫存表，右側 AI 區可收合，讓小螢幕保留更多表格空間。
        self.holding_pane = ttk.Panedwindow(holding_tab, orient='horizontal')
        self.holding_pane.pack(fill='both', expand=True)
        self.holding_table_frame = ttk.Frame(self.holding_pane)
        self.ai_sidebar_frame = ttk.Frame(
            self.holding_pane, padding=(8, 0, 0, 0)
        )
        self.holding_pane.add(self.holding_table_frame, weight=5)
        self.holding_pane.add(self.ai_sidebar_frame, weight=2)

        self._build_holding_table(self.holding_table_frame)
        self._build_ai_sidebar(self.ai_sidebar_frame)
        self._build_dividend_tab(dividend_tab)
        self._build_loaded_data_tab(data_tab)
        self._build_settings_tab(self.settings_tab)
        self._build_log_tab(self.log_tab)
        self.main_notebook.bind(
            '<<NotebookTabChanged>>', self._on_main_tab_changed
        )
        self.root.after(250, self._set_default_holding_sash)

    def _create_tree(
        self,
        parent,
        columns,
        headings,
        widths,
        height=None,
    ):
        """建立含雙向捲軸與欄位排序功能的 Treeview。"""
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)

        tree = ttk.Treeview(
            frame,
            columns=columns,
            show='headings',
            height=height,
        )
        tree.grid(row=0, column=0, sticky='nsew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        # 將排序狀態及原始標題保存在 Treeview 物件上。
        tree._sort_reverse = {}  # type: ignore[attr-defined]
        tree._heading_labels = dict(headings)  # type: ignore[attr-defined]

        for column in columns:
            tree.heading(
                column,
                text=headings[column],
                command=lambda c=column, t=tree: self._sort_treeview(t, c),
            )
            tree.column(
                column,
                width=widths.get(column, 110),
                anchor='center',
            )

        y_scrollbar = ttk.Scrollbar(
            frame,
            orient='vertical',
            command=tree.yview,
        )
        y_scrollbar.grid(row=0, column=1, sticky='ns')
        x_scrollbar = ttk.Scrollbar(
            frame,
            orient='horizontal',
            command=tree.xview,
        )
        x_scrollbar.grid(row=1, column=0, sticky='ew')
        tree.configure(
            yscrollcommand=y_scrollbar.set,
            xscrollcommand=x_scrollbar.set,
        )
        return tree

    @staticmethod
    def _tree_sort_key(value: object) -> tuple[int, object]:
        """
        將表格顯示文字轉成適合排序的值。

        支援金額、百分比、一般數字、YYYY-MM-DD／YYYY-MM 日期與文字。
        """
        text = str(value).strip()
        if text in {'', '-', '未更新', '未提供'}:
            return (9, '')

        number_text = (
            text.replace('NT$', '')
            .replace(',', '')
            .replace('%', '')
            .replace('元', '')
            .strip()
        )
        if re.fullmatch(r'[-+]?\d+(?:\.\d+)?', number_text):
            return (0, float(number_text))

        for format_text in ('%Y-%m-%d', '%Y/%m/%d', '%Y-%m', '%Y/%m'):
            try:
                return (1, datetime.strptime(text, format_text))
            except ValueError:
                continue

        return (2, text.casefold())

    def _sort_treeview(self, tree: ttk.Treeview, column: str) -> None:
        """按欄位標題切換升冪／降冪，空白資料固定放在最後。"""
        reverse_map = getattr(tree, '_sort_reverse', {})
        reverse = bool(reverse_map.get(column, False))

        populated = []
        empty = []
        for item_id in tree.get_children(''):
            value = tree.set(item_id, column)
            key = self._tree_sort_key(value)
            if key[0] == 9:
                empty.append((key, item_id))
            else:
                populated.append((key, item_id))

        populated.sort(key=lambda item: item[0], reverse=reverse)
        ordered = populated + empty
        for index, (_key, item_id) in enumerate(ordered):
            tree.move(item_id, '', index)

        reverse_map[column] = not reverse
        tree._sort_reverse = reverse_map  # type: ignore[attr-defined]

        labels = getattr(tree, '_heading_labels', {})
        for other_column, label in labels.items():
            marker = ''
            if other_column == column:
                marker = ' ▼' if reverse else ' ▲'
            tree.heading(
                other_column,
                text=f'{label}{marker}',
                command=lambda c=other_column, t=tree: self._sort_treeview(t, c),
            )

    def _build_holding_table(self, parent) -> None:
        columns = (
            'symbol', 'code', 'name', 'market', 'shares', 'cost',
            'avg', 'close', 'value', 'profit', 'return', 'date',
        )
        headings = dict(zip(
            columns,
            (
                'Yahoo Symbol', '代號', '名稱', '市場', '股數', '總成本',
                '平均成本', '最近收盤', '庫存市值', '損益', '報酬率', '行情日',
            ),
        ))
        widths = {
            'symbol': 1, 'code': 72, 'name': 125, 'market': 155,
            'shares': 90, 'cost': 115, 'avg': 95, 'close': 90,
            'value': 120, 'profit': 115, 'return': 85, 'date': 100,
        }
        self.holding_tree = self._create_tree(
            parent, columns, headings, widths
        )
        self.holding_tree.configure(
            displaycolumns=tuple(column for column in columns if column != 'symbol')
        )
        self.holding_tree.bind(
            '<<TreeviewSelect>>', self.on_holding_selected
        )
        self.holding_tree.bind(
            '<Double-1>',
            lambda _event: self._focus_shares_entry(),
        )
