"""Tkinter 主視窗。"""

from __future__ import annotations

import threading
import tkinter as tk
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
from app.db.database import Database
from app.models import Holding
from app.services.dividend_service import (
    PENDING,
    REALIZED,
    build_dividend_projection,
    group_month_components,
    summarize_monthly,
    summarize_year,
)
from app.services.portfolio_service import (
    build_holding_views,
    summarize_portfolio,
)
from app.services.sync_service import SyncService
from app.ui.universe_dialog import UniverseSelectionDialog
from app.utils import decimal, money, normalize_stock_code, percent


class PortfolioApp:
    def __init__(self, root: tk.Tk, database: Database) -> None:
        self.root = root
        self.database = database
        self.sync_service = SyncService(database)
        self.busy = False
        self.sync_buttons: list[ttk.Button] = []

        self.stock_code_var = tk.StringVar()
        self.yahoo_symbol_var = tk.StringVar()
        self.stock_name_var = tk.StringVar()
        self.market_var = tk.StringVar(value=MARKET_CHOICES['AUTO'])
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
        self.loaded_count_var = tk.StringVar(value='')
        self.log_status_var = tk.StringVar(value='尚未執行下載作業')

        self._loaded_instruments = []
        self._loaded_quotes: list[dict] = []
        self._loaded_actions = []
        self._dividend_projections = []
        self._dividend_month_groups = {}
        self._dividend_chart_annotation = None
        self._dividend_month_patches: dict[int, list] = {}

        self._build_style()
        self._build_layout()
        self.loaded_search_var.trace_add(
            'write', lambda *_args: self._render_loaded_data()
        )
        self.refresh_all_views()

    def _build_style(self) -> None:
        """建立較柔和的藍灰色介面，並保留台股紅漲綠跌慣例。"""
        self.colors = {
            'background': '#F3F6FA',
            'surface': '#FFFFFF',
            'primary': '#2563EB',
            'primary_dark': '#1D4ED8',
            'accent': '#0EA5E9',
            'text': '#1F2937',
            'muted': '#64748B',
            'border': '#D8E1EC',
            'positive': '#C62828',
            'negative': '#16803C',
            'neutral': '#475569',
            'realized': '#2563EB',
            'pending': '#F59E0B',
            'total': '#7C3AED',
        }

        # 優先使用作業系統內建的繁中文字型，避免 Matplotlib 中文亂碼。
        available_fonts = {
            font.name for font in font_manager.fontManager.ttflist
        }
        for candidate in (
            'PingFang TC',
            'Heiti TC',
            'Microsoft JhengHei',
            'Noto Sans CJK TC',
            'Arial Unicode MS',
        ):
            if candidate in available_fonts:
                rcParams['font.sans-serif'] = [
                    candidate,
                    *rcParams.get('font.sans-serif', []),
                ]
                break
        rcParams['axes.unicode_minus'] = False

        self.root.configure(background=self.colors['background'])
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        style.configure(
            '.',
            font=('', 11),
            background=self.colors['background'],
            foreground=self.colors['text'],
        )
        style.configure(
            'TFrame', background=self.colors['background']
        )
        style.configure(
            'Card.TFrame', background=self.colors['surface']
        )
        style.configure(
            'TLabel',
            background=self.colors['background'],
            foreground=self.colors['text'],
        )
        style.configure(
            'Card.TLabel',
            background=self.colors['surface'],
            foreground=self.colors['text'],
        )
        style.configure(
            'TLabelframe',
            background=self.colors['background'],
            bordercolor=self.colors['border'],
        )
        style.configure(
            'TLabelframe.Label',
            background=self.colors['background'],
            foreground=self.colors['primary_dark'],
            font=('', 11, 'bold'),
        )
        style.configure(
            'TButton',
            padding=(10, 6),
            background='#E8EEF8',
            foreground=self.colors['text'],
            bordercolor=self.colors['border'],
        )
        style.map(
            'TButton',
            background=[('active', '#DBE7F8')],
        )
        style.configure(
            'Accent.TButton',
            background=self.colors['primary'],
            foreground='#FFFFFF',
            bordercolor=self.colors['primary'],
            font=('', 11, 'bold'),
        )
        style.map(
            'Accent.TButton',
            background=[('active', self.colors['primary_dark'])],
            foreground=[('disabled', '#E5E7EB')],
        )
        style.configure(
            'Summary.TLabel',
            font=('', 15, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['text'],
        )
        style.configure(
            'Positive.Summary.TLabel',
            font=('', 15, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['positive'],
        )
        style.configure(
            'Negative.Summary.TLabel',
            font=('', 15, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['negative'],
        )
        style.configure(
            'Realized.Summary.TLabel',
            font=('', 15, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['realized'],
        )
        style.configure(
            'Pending.Summary.TLabel',
            font=('', 15, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['pending'],
        )
        style.configure(
            'Total.Summary.TLabel',
            font=('', 15, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['total'],
        )
        style.configure(
            'Treeview',
            rowheight=28,
            background=self.colors['surface'],
            fieldbackground=self.colors['surface'],
            foreground=self.colors['text'],
            bordercolor=self.colors['border'],
        )
        style.configure(
            'Treeview.Heading',
            font=('', 10, 'bold'),
            background='#E9EFF8',
            foreground=self.colors['primary_dark'],
        )
        style.map(
            'Treeview',
            background=[('selected', '#D9E8FF')],
            foreground=[('selected', self.colors['text'])],
        )
        style.configure(
            'Horizontal.TProgressbar',
            troughcolor='#DDE5F0',
            background=self.colors['primary'],
            bordercolor=self.colors['border'],
            lightcolor=self.colors['primary'],
            darkcolor=self.colors['primary_dark'],
        )
        style.configure(
            'TNotebook', background=self.colors['background']
        )
        style.configure(
            'TNotebook.Tab', padding=(14, 7)
        )
        style.map(
            'TNotebook.Tab',
            background=[('selected', '#DDEAFF')],
            foreground=[('selected', self.colors['primary_dark'])],
        )

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill='both', expand=True)
        self._build_input_panel(outer)
        self._build_sync_panel(outer)
        self._build_summary(outer)
        self._build_notebook(outer)
        ttk.Separator(outer).pack(fill='x', pady=(8, 4))
        ttk.Label(outer, textvariable=self.status_var).pack(anchor='w')

    def _build_input_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text='持股資料', padding=10)
        frame.pack(fill='x', pady=(0, 8))

        fields = [
            ('股票代號', self.stock_code_var, 10, 'normal'),
            ('Yahoo Symbol', self.yahoo_symbol_var, 13, 'readonly'),
            ('股票名稱', self.stock_name_var, 20, 'normal'),
            ('持有股數', self.shares_var, 12, 'normal'),
            ('持有總成本', self.total_cost_var, 15, 'normal'),
        ]
        for index, (label, variable, width, state) in enumerate(fields):
            ttk.Label(frame, text=label).grid(
                row=0,
                column=index * 2,
                padx=(3, 2),
                sticky='e',
            )
            entry = ttk.Entry(
                frame,
                textvariable=variable,
                width=width,
                state=state,
            )
            entry.grid(
                row=0,
                column=index * 2 + 1,
                padx=(0, 7),
            )
            if label == '股票代號':
                self.stock_code_entry = entry

        ttk.Label(frame, text='市場').grid(
            row=1, column=0, pady=(8, 0), sticky='e'
        )
        ttk.Combobox(
            frame,
            textvariable=self.market_var,
            values=list(MARKET_CHOICES.values()),
            width=37,
            state='readonly',
        ).grid(
            row=1,
            column=1,
            columnspan=3,
            pady=(8, 0),
            sticky='w',
        )

        ttk.Button(
            frame,
            text='解析代號',
            command=self.resolve_symbol,
        ).grid(row=1, column=6, pady=(8, 0), padx=4)
        ttk.Button(
            frame,
            text='儲存持股',
            command=self.save_holding,
        ).grid(row=1, column=7, pady=(8, 0), padx=4)
        ttk.Button(
            frame,
            text='刪除選取',
            command=self.delete_selected_holding,
        ).grid(row=1, column=8, pady=(8, 0), padx=4)
        ttk.Button(
            frame,
            text='清空欄位',
            command=self.clear_form,
        ).grid(row=1, column=9, pady=(8, 0), padx=4)

    def _build_sync_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(
            parent,
            text='yfinance 資料同步',
            padding=8,
        )
        frame.pack(fill='x', pady=(0, 8))

        button_specs = [
            (
                '① 選擇類型並建立商品清冊',
                self.discover_universe_async,
            ),
            ('② 更新全部商品行情', self.sync_all_quotes_async),
            ('更新持股行情', self.sync_holding_quotes_async),
            ('③ 更新持股股利／分割＋已公告股利', self.sync_actions_async),
        ]
        for index, (text, command) in enumerate(button_specs):
            button = ttk.Button(
                frame,
                text=text,
                command=command,
                style='Accent.TButton' if index == 0 else 'TButton',
            )
            button.pack(side='left', padx=4)
            self.sync_buttons.append(button)

        ttk.Label(
            frame,
            text='下載過程請查看「下載進度／LOG」分頁。',
        ).pack(side='left', padx=14)

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
            box = ttk.Frame(frame, padding=9, style='Card.TFrame')
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
        dividend_tab = ttk.Frame(self.main_notebook, padding=7)
        self.dividend_tab = dividend_tab
        data_tab = ttk.Frame(self.main_notebook, padding=7)
        self.log_tab = ttk.Frame(self.main_notebook, padding=7)

        self.main_notebook.add(holding_tab, text='庫存與損益')
        self.main_notebook.add(dividend_tab, text='每月配息估算')
        self.main_notebook.add(data_tab, text='已載入資料')
        self.main_notebook.add(self.log_tab, text='下載進度／LOG')

        self._build_holding_table(holding_tab)
        self._build_dividend_tab(dividend_tab)
        self._build_loaded_data_tab(data_tab)
        self._build_log_tab(self.log_tab)
        self.main_notebook.bind(
            '<<NotebookTabChanged>>', self._on_main_tab_changed
        )

    def _create_tree(
        self,
        parent,
        columns,
        headings,
        widths,
        height=None,
    ):
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

        for column in columns:
            tree.heading(column, text=headings[column])
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
            'symbol': 100, 'code': 75, 'name': 140, 'market': 220,
            'shares': 90, 'cost': 115, 'avg': 95, 'close': 90,
            'value': 120, 'profit': 115, 'return': 85, 'date': 100,
        }
        self.holding_tree = self._create_tree(
            parent, columns, headings, widths
        )
        self.holding_tree.bind(
            '<<TreeviewSelect>>', self.on_holding_selected
        )

    def _build_dividend_tab(self, parent) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill='x', pady=(0, 7))
        ttk.Label(controls, text='分析年度：').pack(side='left')
        ttk.Entry(
            controls,
            textvariable=self.dividend_year_var,
            width=8,
        ).pack(side='left', padx=(0, 5))
        ttk.Button(
            controls,
            text='重新計算',
            command=self.refresh_dividend_view,
            style='Accent.TButton',
        ).pack(side='left')
        ttk.Label(
            controls,
            text=(
                '已實現優先依現金發放日判定；未領包含已公告未發放與歷史模式估算。'
                '金額均依目前持股股數估算，不等同券商實際入帳。'
            ),
            foreground=self.colors['muted'],
        ).pack(side='left', padx=16)

        summary_frame = ttk.LabelFrame(
            parent,
            text='年度股利摘要',
            padding=7,
        )
        summary_frame.pack(fill='x', pady=(0, 7))
        dividend_cards = [
            ('已實現股利（估算）', self.dividend_realized_var,
             'Realized.Summary.TLabel'),
            ('未領／預估股利', self.dividend_pending_var,
             'Pending.Summary.TLabel'),
            ('當年度股利總和', self.dividend_total_var,
             'Total.Summary.TLabel'),
        ]
        for index, (title, variable, style_name) in enumerate(dividend_cards):
            card = ttk.Frame(
                summary_frame,
                padding=8,
                style='Card.TFrame',
            )
            card.grid(row=0, column=index, sticky='nsew', padx=7)
            summary_frame.columnconfigure(index, weight=1)
            ttk.Label(
                card,
                text=title,
                style='Card.TLabel',
            ).pack()
            ttk.Label(
                card,
                textvariable=variable,
                style=style_name,
            ).pack(pady=(4, 0))

        pane = ttk.Panedwindow(parent, orient='vertical')
        self.dividend_pane = pane
        pane.pack(fill='both', expand=True)

        chart_frame = ttk.LabelFrame(
            pane,
            text='每月股利金額與持股組成（滑鼠移到月份可查看明細；點擊可切換月份組成）',
            padding=5,
        )
        tables_frame = ttk.Frame(pane)
        pane.add(chart_frame, weight=5)
        pane.add(tables_frame, weight=2)

        self.dividend_figure = Figure(
            figsize=(13.6, 5.0),
            dpi=100,
            facecolor=self.colors['surface'],
        )
        self.dividend_ax = self.dividend_figure.add_subplot(111)
        self.dividend_canvas = FigureCanvasTkAgg(
            self.dividend_figure,
            master=chart_frame,
        )
        chart_widget = self.dividend_canvas.get_tk_widget()
        chart_widget.configure(height=470)
        chart_widget.pack(fill='both', expand=True)

        # 第一次顯示時給圖表較大的垂直空間，仍可由使用者拖曳分隔線調整。
        self.root.after_idle(self._set_default_dividend_sash)
        self.dividend_canvas.mpl_connect(
            'motion_notify_event', self._on_dividend_chart_hover
        )
        self.dividend_canvas.mpl_connect(
            'button_press_event', self._on_dividend_chart_click
        )

        self.dividend_table_tabs = ttk.Notebook(tables_frame)
        table_tabs = self.dividend_table_tabs
        table_tabs.pack(fill='both', expand=True)
        monthly_tab = ttk.Frame(table_tabs, padding=5)
        component_tab = ttk.Frame(table_tabs, padding=5)
        detail_tab = ttk.Frame(table_tabs, padding=5)
        table_tabs.add(monthly_tab, text='12 個月摘要')
        table_tabs.add(component_tab, text='選定月份組成')
        table_tabs.add(detail_tab, text='全年股利明細')

        self.monthly_tree = self._create_tree(
            monthly_tab,
            ('month', 'realized', 'pending', 'total'),
            {
                'month': '月份',
                'realized': '已實現股利',
                'pending': '未領／預估',
                'total': '月份合計',
            },
            {
                'month': 120,
                'realized': 170,
                'pending': 170,
                'total': 170,
            },
            height=7,
        )
        self.monthly_tree.tag_configure(
            'has_realized', foreground=self.colors['realized']
        )
        self.monthly_tree.tag_configure(
            'pending_only', foreground='#B45309'
        )

        month_controls = ttk.Frame(component_tab)
        month_controls.pack(fill='x', pady=(0, 5))
        ttk.Label(month_controls, text='查看月份：').pack(side='left')
        self.dividend_month_combo = ttk.Combobox(
            month_controls,
            textvariable=self.dividend_month_var,
            state='readonly',
            width=12,
        )
        self.dividend_month_combo.pack(side='left')
        self.dividend_month_combo.bind(
            '<<ComboboxSelected>>',
            lambda _event: self._render_dividend_month_components(),
        )
        ttk.Label(
            month_controls,
            text='長條圖中同一顏色代表同一檔持股；斜線區塊為未領／估算。',
            foreground=self.colors['muted'],
        ).pack(side='left', padx=12)

        self.dividend_component_tree = self._create_tree(
            component_tab,
            ('status', 'code', 'name', 'shares', 'dps', 'amount', 'basis'),
            {
                'status': '狀態',
                'code': '代號',
                'name': '名稱',
                'shares': '持有股數',
                'dps': '每股股利',
                'amount': '預估金額',
                'basis': '依據',
            },
            {
                'status': 110,
                'code': 90,
                'name': 160,
                'shares': 110,
                'dps': 110,
                'amount': 135,
                'basis': 210,
            },
            height=7,
        )
        self.dividend_component_tree.tag_configure(
            REALIZED, foreground=self.colors['realized']
        )
        self.dividend_component_tree.tag_configure(
            PENDING, foreground='#B45309'
        )

        columns = (
            'month', 'status', 'symbol', 'name', 'shares', 'dps',
            'amount', 'period', 'basis', 'reference', 'payment',
        )
        headings = dict(zip(
            columns,
            (
                '月份', '狀態', 'Yahoo Symbol', '名稱', '股數', '每股股利',
                '預估金額', '所屬期間', '依據', '除息日', '現金發放日',
            ),
        ))
        widths = {
            'month': 90, 'status': 105, 'symbol': 105, 'name': 145,
            'shares': 90, 'dps': 100, 'amount': 120, 'period': 95,
            'basis': 250, 'reference': 105, 'payment': 105,
        }
        self.dividend_tree = self._create_tree(
            detail_tab, columns, headings, widths
        )
        self.dividend_tree.tag_configure(
            REALIZED, foreground=self.colors['realized']
        )
        self.dividend_tree.tag_configure(
            PENDING, foreground='#B45309'
        )

    def _build_loaded_data_tab(self, parent) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill='x', pady=(0, 6))

        ttk.Label(controls, text='搜尋：').pack(side='left')
        search_entry = ttk.Entry(
            controls,
            textvariable=self.loaded_search_var,
            width=28,
        )
        search_entry.pack(side='left', padx=(0, 4))
        ttk.Button(
            controls,
            text='清除搜尋',
            command=lambda: self.loaded_search_var.set(''),
        ).pack(side='left', padx=(0, 10))
        ttk.Button(
            controls,
            text='重新整理',
            command=self.refresh_loaded_data_view,
        ).pack(side='left', padx=3)
        ttk.Button(
            controls,
            text='匯出商品清冊 CSV',
            command=lambda: self.export_table('instruments'),
        ).pack(side='left', padx=3)
        ttk.Button(
            controls,
            text='匯出行情 CSV',
            command=lambda: self.export_table('quotes'),
        ).pack(side='left', padx=3)
        ttk.Button(
            controls,
            text='匯出股利／分割 CSV',
            command=lambda: self.export_table('actions'),
        ).pack(side='left', padx=3)
        ttk.Label(
            controls,
            textvariable=self.loaded_count_var,
        ).pack(side='right')

        self.loaded_tabs = ttk.Notebook(parent)
        self.loaded_tabs.pack(fill='both', expand=True)
        instrument_tab = ttk.Frame(self.loaded_tabs, padding=5)
        quote_tab = ttk.Frame(self.loaded_tabs, padding=5)
        action_tab = ttk.Frame(self.loaded_tabs, padding=5)
        self.loaded_tabs.add(instrument_tab, text='商品清冊')
        self.loaded_tabs.add(quote_tab, text='行情')
        self.loaded_tabs.add(action_tab, text='股利／分割')

        columns = (
            'symbol', 'code', 'name', 'exchange', 'market',
            'category', 'type', 'currency',
        )
        headings = dict(zip(
            columns,
            (
                'Yahoo Symbol', '代號', '名稱', 'Yahoo 交易所',
                '市場分類', '商品分類', 'Yahoo 類型', '幣別',
            ),
        ))
        widths = {
            'symbol': 110, 'code': 80, 'name': 220,
            'exchange': 100, 'market': 230, 'category': 180,
            'type': 100, 'currency': 70,
        }
        self.instrument_tree = self._create_tree(
            instrument_tab, columns, headings, widths
        )

        columns = (
            'symbol', 'code', 'name', 'close', 'prev',
            'change', 'pct', 'volume', 'date',
        )
        headings = dict(zip(
            columns,
            (
                'Yahoo Symbol', '代號', '名稱', '收盤', '前收',
                '漲跌', '漲跌幅', '成交量', '行情日',
            ),
        ))
        widths = {
            'symbol': 105, 'code': 75, 'name': 180,
            'close': 90, 'prev': 90, 'change': 90,
            'pct': 85, 'volume': 120, 'date': 100,
        }
        self.quote_tree = self._create_tree(
            quote_tab, columns, headings, widths
        )
        self.quote_tree.tag_configure(
            'positive', foreground=self.colors['positive']
        )
        self.quote_tree.tag_configure(
            'negative', foreground=self.colors['negative']
        )
        self.quote_tree.tag_configure(
            'neutral', foreground=self.colors['neutral']
        )

        columns = (
            'date', 'payment', 'period', 'symbol', 'code', 'name',
            'type', 'value', 'status', 'source',
        )
        headings = dict(zip(
            columns,
            (
                '除息／事件日', '現金發放日', '所屬期間', 'Yahoo Symbol',
                '代號', '名稱', '類型', '數值', '公告狀態', '來源',
            ),
        ))
        widths = {
            'date': 105, 'payment': 105, 'period': 90, 'symbol': 110,
            'code': 80, 'name': 170, 'type': 145, 'value': 95,
            'status': 115, 'source': 135,
        }
        self.action_tree = self._create_tree(
            action_tab, columns, headings, widths
        )
        self.action_tree.tag_configure(
            'DIVIDEND', foreground=self.colors['realized']
        )
        self.action_tree.tag_configure(
            'SPLIT', foreground=self.colors['total']
        )

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
        self._run_background(
            '正在更新持股股利／分割與已公告股利……',
            lambda: self.sync_service.sync_holding_actions(self._progress),
            lambda result: self._after_sync(
                f'歷史股利／分割 {result[0]} 筆；'
                f'Yahoo 台灣股利政策 {result[1]} 筆；'
                f'最終失敗項目 {result[2]} 個'
            ),
        )

    def _after_sync(self, message: str) -> None:
        self.refresh_all_views()
        self._finish_operation(message)
        messagebox.showinfo('完成', message)

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

    def resolve_symbol(self) -> None:
        code = normalize_stock_code(self.stock_code_var.get())
        if not code:
            messagebox.showwarning('欄位不足', '請輸入股票代號。')
            return
        self._run_background(
            f'正在解析 {code}……',
            lambda: self.sync_service.resolve_and_save_instrument(
                code, self._selected_market_key()
            ),
            self._after_resolve,
        )

    def _after_resolve(self, instrument) -> None:
        self.stock_code_var.set(instrument.stock_code)
        self.yahoo_symbol_var.set(instrument.symbol)
        self.stock_name_var.set(instrument.name)
        if self._selected_market_key() == 'AUTO':
            self.market_var.set(
                self._market_label(instrument.market_segment)
            )
        message = f'已解析：{instrument.symbol} {instrument.name}'
        self.refresh_loaded_data_view()
        self._finish_operation(message)

    def save_holding(self) -> None:
        code = normalize_stock_code(self.stock_code_var.get())
        symbol = self.yahoo_symbol_var.get().strip().upper()
        name = self.stock_name_var.get().strip()
        if not symbol or not name:
            messagebox.showwarning('尚未解析', '請先按「解析代號」。')
            return
        try:
            shares = int(
                self.shares_var.get().replace(',', '').strip()
            )
            total_cost = float(
                self.total_cost_var.get().replace(',', '').strip()
            )
        except ValueError:
            messagebox.showerror(
                '輸入錯誤',
                '股數必須是整數，總成本必須是數字。',
            )
            return
        if shares <= 0 or total_cost < 0:
            messagebox.showerror(
                '輸入錯誤',
                '股數必須大於 0，總成本不可小於 0。',
            )
            return
        self.database.upsert_holding(
            Holding(
                None,
                code,
                symbol,
                name,
                self._selected_market_key(),
                shares,
                total_cost,
            )
        )
        self.status_var.set(f'已儲存 {symbol}')
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

    def _focus_stock_code_entry(self) -> None:
        """儲存完成後將輸入焦點移回股票代號，方便連續輸入。"""
        entry = getattr(self, 'stock_code_entry', None)
        if entry is not None:
            entry.focus_set()
            entry.icursor('end')

    def _set_default_dividend_sash(self) -> None:
        """提高圖表區預設高度，避免標題、數值及圖例被裁切。"""
        pane = getattr(self, 'dividend_pane', None)
        if pane is None:
            return
        pane.update_idletasks()
        height = pane.winfo_height()
        if height < 350:
            return
        try:
            # 圖表約使用 68% 高度，並至少為下方表格保留 190px。
            position = min(max(int(height * 0.68), 420), height - 190)
            pane.sashpos(0, position)
        except tk.TclError:
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

    def refresh_all_views(self) -> None:
        self.refresh_holding_view()
        self.refresh_dividend_view()
        self.refresh_loaded_data_view()

    def refresh_holding_view(self) -> None:
        holdings = self.database.list_holdings()
        views = build_holding_views(
            holdings, self.database.get_quote_map()
        )
        summary = summarize_portfolio(views)

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

        for view in views:
            row_tag = (
                'positive' if view.profit > 0
                else 'negative' if view.profit < 0
                else 'neutral'
            )
            self.holding_tree.insert(
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

    def refresh_dividend_view(self) -> None:
        try:
            target_year = int(self.dividend_year_var.get())
            if target_year < 1900 or target_year > 2200:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                '年度錯誤', '請輸入四位數西元年。'
            )
            return

        projections = build_dividend_projection(
            self.database.list_holdings(),
            self.database.list_actions('DIVIDEND'),
            target_year,
        )
        monthly = summarize_monthly(projections, target_year)
        year_summary = summarize_year(projections)

        self._dividend_projections = projections
        self._dividend_month_groups = group_month_components(projections)

        self.dividend_realized_var.set(
            f'NT$ {money(year_summary.realized_amount)}'
        )
        self.dividend_pending_var.set(
            f'NT$ {money(year_summary.pending_amount)}'
        )
        self.dividend_total_var.set(
            f'NT$ {money(year_summary.total_amount)}'
        )

        for tree in (self.monthly_tree, self.dividend_tree):
            for item in tree.get_children():
                tree.delete(item)

        for item in monthly:
            tag = (
                'has_realized'
                if item.realized_amount > 0
                else 'pending_only'
                if item.pending_amount > 0
                else ''
            )
            self.monthly_tree.insert(
                '',
                'end',
                values=(
                    item.month,
                    f'NT$ {money(item.realized_amount)}',
                    f'NT$ {money(item.pending_amount)}',
                    f'NT$ {money(item.total_amount)}',
                ),
                tags=(tag,) if tag else (),
            )

        for item in projections:
            self.dividend_tree.insert(
                '',
                'end',
                values=(
                    item.month,
                    item.status_text,
                    item.symbol,
                    item.stock_name,
                    f'{item.shares:,}',
                    decimal(item.dividend_per_share, 4),
                    f'NT$ {money(item.estimated_amount)}',
                    item.period or '-',
                    item.basis,
                    item.reference_date,
                    item.payment_date or '-',
                ),
                tags=(item.status,),
            )

        month_values = [item.month for item in monthly]
        self.dividend_month_combo.configure(values=month_values)
        selected_month = self.dividend_month_var.get()
        if selected_month not in month_values:
            selected_month = (
                f'{target_year}-{date.today().month:02d}'
                if target_year == date.today().year
                else next(
                    (
                        item.month for item in monthly
                        if item.total_amount > 0
                    ),
                    f'{target_year}-01',
                )
            )
            self.dividend_month_var.set(selected_month)

        self._render_dividend_month_components()
        self._render_dividend_chart(monthly, projections, target_year)

    def _render_dividend_month_components(self) -> None:
        """更新使用者目前選定月份的個股／ETF 組成表。"""
        if not hasattr(self, 'dividend_component_tree'):
            return

        for row in self.dividend_component_tree.get_children():
            self.dividend_component_tree.delete(row)

        month = self.dividend_month_var.get()
        for item in self._dividend_month_groups.get(month, []):
            self.dividend_component_tree.insert(
                '',
                'end',
                values=(
                    item.status_text,
                    item.stock_code,
                    item.stock_name,
                    f'{item.shares:,}',
                    decimal(item.dividend_per_share, 4),
                    f'NT$ {money(item.estimated_amount)}',
                    item.basis,
                ),
                tags=(item.status,),
            )

    def _render_dividend_chart(
        self,
        monthly,
        projections,
        target_year: int,
    ) -> None:
        """
        畫出 12 個月堆疊長條圖。

        - 每一種顏色代表一檔持股。
        - 實心代表已實現。
        - 半透明斜線代表已公告未發放或歷史模式估算。
        """
        ax = self.dividend_ax
        ax.clear()
        ax.set_facecolor(self.colors['surface'])
        self._dividend_month_patches = {index: [] for index in range(12)}

        month_keys = [item.month for item in monthly]
        x_values = list(range(12))

        symbol_totals: dict[str, float] = {}
        symbol_names: dict[str, str] = {}
        for item in projections:
            symbol_totals[item.symbol] = (
                symbol_totals.get(item.symbol, 0.0)
                + item.estimated_amount
            )
            symbol_names[item.symbol] = (
                f'{item.stock_code} {item.stock_name}'
            )
        symbols = sorted(
            symbol_totals,
            key=symbol_totals.get,
            reverse=True,
        )

        cmap = colormaps['tab20'].resampled(max(len(symbols), 1))
        symbol_colors = {
            symbol: cmap(index)
            for index, symbol in enumerate(symbols)
        }
        bottoms = [0.0] * 12

        for symbol in symbols:
            color = symbol_colors[symbol]
            for status in (REALIZED, PENDING):
                values = []
                for month in month_keys:
                    values.append(sum(
                        item.estimated_amount
                        for item in projections
                        if item.symbol == symbol
                        and item.month == month
                        and item.status == status
                    ))

                bars = ax.bar(
                    x_values,
                    values,
                    bottom=bottoms,
                    width=0.68,
                    color=color,
                    edgecolor='#475569',
                    linewidth=0.45,
                    alpha=1.0 if status == REALIZED else 0.58,
                    hatch=None if status == REALIZED else '///',
                )
                for month_index, (bar, value) in enumerate(zip(bars, values)):
                    if value > 0:
                        self._dividend_month_patches[month_index].append(bar)
                bottoms = [
                    bottom + value
                    for bottom, value in zip(bottoms, values)
                ]

        max_total = max(bottoms, default=0.0)
        for index, total in enumerate(bottoms):
            if total <= 0:
                continue
            ax.text(
                index,
                total + max(max_total * 0.018, 30),
                f'{total:,.0f}',
                ha='center',
                va='bottom',
                fontsize=8.5,
                color=self.colors['text'],
                fontweight='bold',
            )

        ax.set_title(
            f'{target_year} 年每月股利組成',
            loc='left',
            fontsize=13,
            fontweight='bold',
            color=self.colors['primary_dark'],
            pad=10,
        )
        ax.set_xticks(x_values)
        ax.set_xticklabels([f'{month}月' for month in range(1, 13)])
        ax.set_ylabel('股利金額（NT$）')
        ax.yaxis.set_major_formatter(
            FuncFormatter(lambda value, _pos: f'{value:,.0f}')
        )
        ax.grid(axis='y', linestyle='--', alpha=0.22)
        ax.set_axisbelow(True)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color(self.colors['border'])
        ax.spines['bottom'].set_color(self.colors['border'])
        ax.tick_params(colors=self.colors['text'])
        ax.margins(x=0.02)
        if max_total > 0:
            ax.set_ylim(0, max_total * 1.20)

        legend_symbols = symbols[:12]
        legend_handles = [
            Patch(
                facecolor=symbol_colors[symbol],
                edgecolor='#475569',
                label=symbol_names[symbol],
            )
            for symbol in legend_symbols
        ]
        if len(symbols) > len(legend_symbols):
            legend_handles.append(
                Patch(
                    facecolor='#CBD5E1',
                    edgecolor='#64748B',
                    label=(
                        f'另有 {len(symbols) - len(legend_symbols)} 檔'
                        '（詳見月份組成）'
                    ),
                )
            )
        if symbols:
            legend_handles.extend([
                Patch(
                    facecolor='#FFFFFF',
                    edgecolor='#475569',
                    label='實心＝已實現',
                ),
                Patch(
                    facecolor='#FFFFFF',
                    edgecolor='#475569',
                    hatch='///',
                    alpha=0.65,
                    label='斜線＝未領／公告／估算',
                ),
            ])
            legend_columns = 2 if len(legend_handles) > 9 else 1
            ax.legend(
                handles=legend_handles,
                loc='upper left',
                bbox_to_anchor=(1.005, 1.0),
                fontsize=8,
                frameon=False,
                ncol=legend_columns,
                columnspacing=0.9,
                handletextpad=0.5,
                labelspacing=0.55,
            )
            self.dividend_figure.subplots_adjust(
                left=0.065,
                right=0.70 if legend_columns == 2 else 0.79,
                top=0.90,
                bottom=0.14,
            )
        else:
            ax.text(
                0.5,
                0.5,
                '尚無股利資料，請先更新持股股利／分割。',
                transform=ax.transAxes,
                ha='center',
                va='center',
                color=self.colors['muted'],
                fontsize=12,
            )
            self.dividend_figure.subplots_adjust(
                left=0.065, right=0.97, top=0.90, bottom=0.14
            )

        self._dividend_chart_annotation = ax.annotate(
            '',
            xy=(0, 0),
            xytext=(14, 14),
            textcoords='offset points',
            bbox={
                'boxstyle': 'round,pad=0.5',
                'fc': '#FFFFFF',
                'ec': self.colors['border'],
                'alpha': 0.97,
            },
            arrowprops={'arrowstyle': '->', 'color': self.colors['muted']},
            fontsize=9,
        )
        self._dividend_chart_annotation.set_visible(False)
        self.dividend_canvas.draw_idle()

    def _dividend_tooltip_text(self, month_index: int) -> str:
        """組合某個月份的圖表提示文字。"""
        try:
            target_year = int(self.dividend_year_var.get())
        except ValueError:
            return ''
        month_key = f'{target_year}-{month_index + 1:02d}'
        items = self._dividend_month_groups.get(month_key, [])
        realized = sum(
            item.estimated_amount for item in items
            if item.status == REALIZED
        )
        pending = sum(
            item.estimated_amount for item in items
            if item.status == PENDING
        )
        lines = [
            f'{month_index + 1} 月',
            f'已實現：NT$ {realized:,.0f}',
            f'未領／預估：NT$ {pending:,.0f}',
            f'合計：NT$ {realized + pending:,.0f}',
        ]
        if items:
            lines.append('組成：')
            for item in items[:8]:
                marker = '已' if item.status == REALIZED else '未'
                lines.append(
                    f'  [{marker}] {item.stock_code} {item.stock_name} '
                    f'{item.estimated_amount:,.0f}'
                )
            if len(items) > 8:
                lines.append(f'  …另有 {len(items) - 8} 筆')
        else:
            lines.append('本月無股利資料')
        return '\n'.join(lines)

    def _on_dividend_chart_hover(self, event) -> None:
        if (
            event.inaxes != self.dividend_ax
            or event.xdata is None
            or self._dividend_chart_annotation is None
        ):
            if self._dividend_chart_annotation is not None:
                self._dividend_chart_annotation.set_visible(False)
                self.dividend_canvas.draw_idle()
            return

        month_index = int(round(event.xdata))
        if month_index < 0 or month_index > 11 or abs(event.xdata - month_index) > 0.46:
            self._dividend_chart_annotation.set_visible(False)
            self.dividend_canvas.draw_idle()
            return

        total = sum(
            patch.get_height()
            for patch in self._dividend_month_patches.get(month_index, [])
        )
        self._dividend_chart_annotation.xy = (month_index, total)
        self._dividend_chart_annotation.set_text(
            self._dividend_tooltip_text(month_index)
        )
        self._dividend_chart_annotation.set_visible(True)
        self.dividend_canvas.draw_idle()

    def _on_dividend_chart_click(self, event) -> None:
        """點擊月份長條後，同步切換「選定月份組成」表。"""
        if event.inaxes != self.dividend_ax or event.xdata is None:
            return
        month_index = int(round(event.xdata))
        if month_index < 0 or month_index > 11:
            return
        try:
            target_year = int(self.dividend_year_var.get())
        except ValueError:
            return
        self.dividend_month_var.set(
            f'{target_year}-{month_index + 1:02d}'
        )
        self._render_dividend_month_components()
        if hasattr(self, 'dividend_table_tabs'):
            self.dividend_table_tabs.select(1)

    @staticmethod
    def _matches_search(query: str, *values) -> bool:
        if not query:
            return True
        searchable = ' '.join(
            str(value or '').lower() for value in values
        )
        return query in searchable

    def refresh_loaded_data_view(self) -> None:
        self._loaded_instruments = self.database.list_instruments()
        self._loaded_quotes = self.database.list_quotes()
        self._loaded_actions = self.database.list_actions()
        self._render_loaded_data()

    def _render_loaded_data(self) -> None:
        if not hasattr(self, 'instrument_tree'):
            return

        query = self.loaded_search_var.get().strip().lower()
        for tree in (
            self.instrument_tree,
            self.quote_tree,
            self.action_tree,
        ):
            for item in tree.get_children():
                tree.delete(item)

        instrument_count = 0
        for item in self._loaded_instruments:
            category_text = UNIVERSE_CATEGORY_CHOICES.get(
                item.product_category,
                item.product_category,
            )
            market_text = self._market_label(item.market_segment)
            if not self._matches_search(
                query,
                item.symbol,
                item.stock_code,
                item.name,
                item.exchange,
                item.market_segment,
                market_text,
                category_text,
                item.quote_type,
                item.currency,
            ):
                continue
            instrument_count += 1
            self.instrument_tree.insert(
                '',
                'end',
                values=(
                    item.symbol,
                    item.stock_code,
                    item.name,
                    item.exchange,
                    market_text,
                    category_text,
                    item.quote_type,
                    item.currency,
                ),
            )

        quote_count = 0
        for row in self._loaded_quotes:
            if not self._matches_search(
                query,
                row['symbol'],
                row['stock_code'],
                row['name'],
                row['close'],
                row['trade_date'],
            ):
                continue
            quote_count += 1
            change_value = float(row.get('change_value') or 0.0)
            quote_tag = (
                'positive' if change_value > 0
                else 'negative' if change_value < 0
                else 'neutral'
            )
            self.quote_tree.insert(
                '',
                'end',
                values=(
                    row['symbol'],
                    row['stock_code'],
                    row['name'],
                    decimal(row['close']),
                    decimal(row['previous_close']),
                    decimal(row['change_value']),
                    percent(row['change_percent']),
                    f"{row['volume']:,.0f}",
                    row['trade_date'],
                ),
                tags=(quote_tag,),
            )

        action_count = 0
        source_labels = {
            'yfinance': 'yfinance 歷史資料',
            'yahoo_tw_scraper': 'Yahoo 台灣股利政策',
            'projection': '歷史模式估算',
        }
        status_labels = {
            'ANNOUNCED': '已公告待除息',
            'EX_DATE_PASSED': '已除息待發放',
            'PAID': '已發放',
        }
        for action in self._loaded_actions:
            type_text = (
                '現金股利'
                if action.action_type == 'DIVIDEND'
                else '股票分割'
            )
            source_text = source_labels.get(action.source, action.source)
            announcement_text = status_labels.get(
                action.announcement_status,
                action.announcement_status or '-',
            )
            if not self._matches_search(
                query,
                action.action_date,
                action.payment_date,
                action.period,
                action.symbol,
                action.stock_code,
                action.stock_name,
                type_text,
                action.value,
                source_text,
                announcement_text,
            ):
                continue
            action_count += 1
            self.action_tree.insert(
                '',
                'end',
                values=(
                    action.action_date,
                    action.payment_date or '-',
                    action.period or '-',
                    action.symbol,
                    action.stock_code,
                    action.stock_name,
                    type_text,
                    decimal(action.value, 4),
                    announcement_text,
                    source_text,
                ),
                tags=(action.action_type,),
            )

        self.loaded_count_var.set(
            f'符合：商品 {instrument_count}／行情 {quote_count}／'
            f'股利／分割 {action_count}'
        )
        self.status_var.set(
            f'已載入商品 {len(self._loaded_instruments)}、'
            f'行情 {len(self._loaded_quotes)}、'
            f'股利／分割 {len(self._loaded_actions)} 筆'
        )

    def export_table(self, table: str) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        defaults = {
            'instruments': (
                '商品清冊',
                'SELECT * FROM instruments ORDER BY symbol',
            ),
            'quotes': (
                '行情',
                'SELECT * FROM market_quotes ORDER BY symbol',
            ),
            'actions': (
                '股利／分割資料',
                'SELECT * FROM corporate_actions '
                'ORDER BY action_date DESC, symbol',
            ),
        }
        label, sql = defaults[table]
        suggested = EXPORT_DIR / f'{table}_{timestamp}.csv'
        path_text = filedialog.asksaveasfilename(
            title=f'匯出{label}',
            initialfile=suggested.name,
            initialdir=str(EXPORT_DIR),
            defaultextension='.csv',
            filetypes=[('CSV', '*.csv')],
        )
        if not path_text:
            return
        count = self.database.export_query_to_csv(
            sql, Path(path_text)
        )
        messagebox.showinfo(
            '匯出完成',
            f'已匯出 {count} 筆：\n{path_text}',
        )
