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


class LoadedDataPageMixin:
    def _build_loaded_data_tab(self, parent) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill='x', pady=(0, 6))

        ttk.Label(controls, text='搜尋：').pack(side='left')
        self.loaded_search_entry = ttk.Entry(
            controls,
            textvariable=self.loaded_search_var,
            width=28,
        )
        self.loaded_search_entry.pack(side='left', padx=(0, 4))
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
                '除息日／分割事件日', '現金股利發放日', '所屬期間', 'Yahoo Symbol',
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
            'yfinance': 'API／yfinance 歷史',
            'yahoo_tw_scraper': '爬蟲／Yahoo 台灣股利政策',
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
