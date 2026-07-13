"""Tkinter 主視窗。"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app.api.yfinance_client import YFinanceApiError
from app.config import EXPORT_DIR, MARKET_CHOICES
from app.db.database import Database
from app.models import Holding
from app.services.dividend_service import build_dividend_projection, summarize_monthly
from app.services.portfolio_service import build_holding_views, summarize_portfolio
from app.services.sync_service import SyncService
from app.utils import decimal, money, normalize_stock_code, percent


class PortfolioApp:
    def __init__(self, root: tk.Tk, database: Database) -> None:
        self.root = root
        self.database = database
        self.sync_service = SyncService(database)

        self.stock_code_var = tk.StringVar()
        self.yahoo_symbol_var = tk.StringVar()
        self.stock_name_var = tk.StringVar()
        self.market_var = tk.StringVar(value='AUTO')
        self.shares_var = tk.StringVar()
        self.total_cost_var = tk.StringVar()
        self.dividend_year_var = tk.StringVar(value=str(date.today().year))
        self.status_var = tk.StringVar(value='就緒')

        self.summary_cost_var = tk.StringVar(value='NT$ 0')
        self.summary_value_var = tk.StringVar(value='NT$ 0')
        self.summary_profit_var = tk.StringVar(value='NT$ 0')
        self.summary_return_var = tk.StringVar(value='0.00%')

        self._build_style()
        self._build_layout()
        self.refresh_all_views()

    def _build_style(self) -> None:
        style = ttk.Style()
        style.configure('Summary.TLabel', font=('', 14, 'bold'))
        style.configure('Treeview', rowheight=27)
        style.configure('Treeview.Heading', font=('', 10, 'bold'))

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
            ttk.Label(frame, text=label).grid(row=0, column=index * 2, padx=(3, 2), sticky='e')
            ttk.Entry(frame, textvariable=variable, width=width, state=state).grid(
                row=0, column=index * 2 + 1, padx=(0, 7)
            )

        ttk.Label(frame, text='市場').grid(row=1, column=0, pady=(8, 0), sticky='e')
        market_combo = ttk.Combobox(
            frame,
            textvariable=self.market_var,
            values=list(MARKET_CHOICES),
            width=12,
            state='readonly',
        )
        market_combo.grid(row=1, column=1, pady=(8, 0), sticky='w')
        ttk.Label(frame, text='AUTO／TWSE／TPEX／EMERGING').grid(
            row=1, column=2, columnspan=2, pady=(8, 0), sticky='w'
        )

        ttk.Button(frame, text='解析代號', command=self.resolve_symbol).grid(row=1, column=6, pady=(8, 0), padx=4)
        ttk.Button(frame, text='儲存持股', command=self.save_holding).grid(row=1, column=7, pady=(8, 0), padx=4)
        ttk.Button(frame, text='刪除選取', command=self.delete_selected_holding).grid(row=1, column=8, pady=(8, 0), padx=4)
        ttk.Button(frame, text='清空欄位', command=self.clear_form).grid(row=1, column=9, pady=(8, 0), padx=4)

    def _build_sync_panel(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text='yfinance 資料同步', padding=8)
        frame.pack(fill='x', pady=(0, 8))
        ttk.Button(frame, text='① 建立 Yahoo 台灣商品清冊／繁中名稱', command=self.discover_universe_async).pack(side='left', padx=4)
        ttk.Button(frame, text='② 更新全部商品行情', command=self.sync_all_quotes_async).pack(side='left', padx=4)
        ttk.Button(frame, text='更新持股行情', command=self.sync_holding_quotes_async).pack(side='left', padx=4)
        ttk.Button(frame, text='③ 更新持股股利／分割', command=self.sync_actions_async).pack(side='left', padx=4)
        ttk.Label(
            frame,
            text='繁中名稱優先使用 Yahoo 台灣資料；缺漏可編輯 data/name_overrides.csv。',
        ).pack(side='left', padx=14)

    def _build_summary(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text='投資組合總覽', padding=8)
        frame.pack(fill='x', pady=(0, 8))
        cards = [
            ('總投入成本', self.summary_cost_var),
            ('最新庫存總值', self.summary_value_var),
            ('未實現損益', self.summary_profit_var),
            ('預估報酬率', self.summary_return_var),
        ]
        for index, (title, variable) in enumerate(cards):
            box = ttk.Frame(frame, padding=5)
            box.grid(row=0, column=index, sticky='nsew', padx=12)
            frame.columnconfigure(index, weight=1)
            ttk.Label(box, text=title).pack()
            ttk.Label(box, textvariable=variable, style='Summary.TLabel').pack(pady=(4, 0))

    def _build_notebook(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.pack(fill='both', expand=True)
        holding_tab = ttk.Frame(notebook, padding=7)
        dividend_tab = ttk.Frame(notebook, padding=7)
        data_tab = ttk.Frame(notebook, padding=7)
        notebook.add(holding_tab, text='庫存與損益')
        notebook.add(dividend_tab, text='每月配息估算')
        notebook.add(data_tab, text='已載入資料')
        self._build_holding_table(holding_tab)
        self._build_dividend_tab(dividend_tab)
        self._build_loaded_data_tab(data_tab)

    def _create_tree(self, parent, columns, headings, widths, height=None):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=columns, show='headings', height=height)
        tree.pack(side='left', fill='both', expand=True)
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths.get(column, 110), anchor='center')
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        scrollbar.pack(side='right', fill='y')
        tree.configure(yscrollcommand=scrollbar.set)
        return tree

    def _build_holding_table(self, parent) -> None:
        columns = ('symbol', 'code', 'name', 'market', 'shares', 'cost', 'avg', 'close', 'value', 'profit', 'return', 'date')
        headings = dict(zip(columns, ('Yahoo Symbol', '代號', '名稱', '市場', '股數', '總成本', '平均成本', '最近收盤', '庫存市值', '損益', '報酬率', '行情日')))
        widths = {'symbol': 100, 'code': 75, 'name': 140, 'market': 90, 'shares': 90, 'cost': 115, 'avg': 95, 'close': 90, 'value': 120, 'profit': 115, 'return': 85, 'date': 100}
        self.holding_tree = self._create_tree(parent, columns, headings, widths)
        self.holding_tree.bind('<<TreeviewSelect>>', self.on_holding_selected)

    def _build_dividend_tab(self, parent) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill='x', pady=(0, 7))
        ttk.Label(controls, text='預估年度：').pack(side='left')
        ttk.Entry(controls, textvariable=self.dividend_year_var, width=8).pack(side='left', padx=(0, 5))
        ttk.Button(controls, text='重新計算', command=self.refresh_dividend_view).pack(side='left')
        ttk.Label(
            controls,
            text='Yahoo 股利日期通常為除息日；未來月份採最近歷史年度模式估算，不代表實際入帳日或已公告金額。',
        ).pack(side='left', padx=16)

        pane = ttk.Panedwindow(parent, orient='vertical')
        pane.pack(fill='both', expand=True)
        monthly_frame = ttk.LabelFrame(pane, text='每月合計', padding=5)
        detail_frame = ttk.LabelFrame(pane, text='估算明細', padding=5)
        pane.add(monthly_frame, weight=1)
        pane.add(detail_frame, weight=2)

        self.monthly_tree = self._create_tree(
            monthly_frame, ('month', 'amount'),
            {'month': '月份', 'amount': '預估可領'},
            {'month': 160, 'amount': 180}, height=6,
        )
        columns = ('month', 'symbol', 'name', 'shares', 'dps', 'amount', 'basis', 'reference')
        headings = dict(zip(columns, ('月份', 'Yahoo Symbol', '名稱', '股數', '每股股利', '預估可領', '依據', '參考除息日')))
        widths = {'month': 90, 'symbol': 100, 'name': 140, 'shares': 90, 'dps': 100, 'amount': 115, 'basis': 170, 'reference': 110}
        self.dividend_tree = self._create_tree(detail_frame, columns, headings, widths)

    def _build_loaded_data_tab(self, parent) -> None:
        controls = ttk.Frame(parent)
        controls.pack(fill='x', pady=(0, 6))
        ttk.Button(controls, text='重新整理', command=self.refresh_loaded_data_view).pack(side='left', padx=3)
        ttk.Button(controls, text='匯出商品清冊 CSV', command=lambda: self.export_table('instruments')).pack(side='left', padx=3)
        ttk.Button(controls, text='匯出行情 CSV', command=lambda: self.export_table('quotes')).pack(side='left', padx=3)
        ttk.Button(controls, text='匯出公司行動 CSV', command=lambda: self.export_table('actions')).pack(side='left', padx=3)

        tabs = ttk.Notebook(parent)
        tabs.pack(fill='both', expand=True)
        instrument_tab = ttk.Frame(tabs, padding=5)
        quote_tab = ttk.Frame(tabs, padding=5)
        action_tab = ttk.Frame(tabs, padding=5)
        tabs.add(instrument_tab, text='商品清冊')
        tabs.add(quote_tab, text='行情')
        tabs.add(action_tab, text='股利／分割')

        columns = ('symbol', 'code', 'name', 'exchange', 'market', 'type', 'currency')
        headings = dict(zip(columns, ('Yahoo Symbol', '代號', '名稱', 'Yahoo 交易所', '市場分類', '商品類型', '幣別')))
        widths = {'symbol': 110, 'code': 80, 'name': 220, 'exchange': 100, 'market': 100, 'type': 100, 'currency': 70}
        self.instrument_tree = self._create_tree(instrument_tab, columns, headings, widths)

        columns = ('symbol', 'code', 'name', 'close', 'prev', 'change', 'pct', 'volume', 'date')
        headings = dict(zip(columns, ('Yahoo Symbol', '代號', '名稱', '收盤', '前收', '漲跌', '漲跌幅', '成交量', '行情日')))
        widths = {'symbol': 105, 'code': 75, 'name': 180, 'close': 90, 'prev': 90, 'change': 90, 'pct': 85, 'volume': 120, 'date': 100}
        self.quote_tree = self._create_tree(quote_tab, columns, headings, widths)

        columns = ('date', 'symbol', 'code', 'name', 'type', 'value', 'source')
        headings = dict(zip(columns, ('日期', 'Yahoo Symbol', '代號', '名稱', '類型', '數值', '來源')))
        widths = {'date': 105, 'symbol': 110, 'code': 80, 'name': 180, 'type': 160, 'value': 110, 'source': 90}
        self.action_tree = self._create_tree(action_tab, columns, headings, widths)

    def _run_background(self, label: str, worker, success_handler) -> None:
        self.status_var.set(label)
        def task():
            try:
                result = worker()
            except Exception as exc:
                message = str(exc)
                self.root.after(0, lambda m=message: self._show_error(m))
            else:
                self.root.after(0, lambda r=result: success_handler(r))
        threading.Thread(target=task, daemon=True).start()

    def _progress(self, message: str) -> None:
        self.root.after(0, lambda m=message: self.status_var.set(m))

    def _show_error(self, message: str) -> None:
        self.status_var.set('操作失敗')
        messagebox.showerror('操作失敗', message)

    def discover_universe_async(self) -> None:
        self._run_background(
            '正在建立 Yahoo 台灣商品清冊……',
            lambda: self.sync_service.discover_universe(self._progress),
            lambda count: self._after_sync(f'商品清冊完成：{count} 檔'),
        )

    def sync_all_quotes_async(self) -> None:
        self._run_background(
            '正在更新全部商品行情……',
            lambda: self.sync_service.sync_all_quotes(self._progress),
            lambda result: self._after_sync(f'行情完成：成功 {result[0]}，失敗 {result[1]}'),
        )

    def sync_holding_quotes_async(self) -> None:
        self._run_background(
            '正在更新持股行情……',
            lambda: self.sync_service.sync_holding_quotes(self._progress),
            lambda result: self._after_sync(f'持股行情：成功 {result[0]}，失敗 {result[1]}'),
        )

    def sync_actions_async(self) -> None:
        self._run_background(
            '正在更新持股股利／分割……',
            lambda: self.sync_service.sync_holding_actions(self._progress),
            lambda result: self._after_sync(f'公司行動：{result[0]} 筆，失敗商品 {result[1]} 檔'),
        )

    def _after_sync(self, message: str) -> None:
        self.status_var.set(message)
        self.refresh_all_views()
        messagebox.showinfo('完成', message)

    def resolve_symbol(self) -> None:
        code = normalize_stock_code(self.stock_code_var.get())
        if not code:
            messagebox.showwarning('欄位不足', '請輸入股票代號。')
            return
        self._run_background(
            f'正在解析 {code}……',
            lambda: self.sync_service.resolve_and_save_instrument(code, self.market_var.get()),
            self._after_resolve,
        )

    def _after_resolve(self, instrument) -> None:
        self.stock_code_var.set(instrument.stock_code)
        self.yahoo_symbol_var.set(instrument.symbol)
        self.stock_name_var.set(instrument.name)
        # 使用者手動指定 EMERGING 時，不被 .TWO 自動分類覆蓋。
        if self.market_var.get() == 'AUTO':
            self.market_var.set(instrument.market_segment)
        self.status_var.set(f'已解析：{instrument.symbol} {instrument.name}')
        self.refresh_loaded_data_view()

    def save_holding(self) -> None:
        code = normalize_stock_code(self.stock_code_var.get())
        symbol = self.yahoo_symbol_var.get().strip().upper()
        name = self.stock_name_var.get().strip()
        if not symbol or not name:
            messagebox.showwarning('尚未解析', '請先按「解析代號」。')
            return
        try:
            shares = int(self.shares_var.get().replace(',', '').strip())
            total_cost = float(self.total_cost_var.get().replace(',', '').strip())
        except ValueError:
            messagebox.showerror('輸入錯誤', '股數必須是整數，總成本必須是數字。')
            return
        if shares <= 0 or total_cost < 0:
            messagebox.showerror('輸入錯誤', '股數必須大於 0，總成本不可小於 0。')
            return
        self.database.upsert_holding(
            Holding(None, code, symbol, name, self.market_var.get(), shares, total_cost)
        )
        self.status_var.set(f'已儲存 {symbol}')
        self.clear_form()
        self.refresh_all_views()

    def delete_selected_holding(self) -> None:
        selected = self.holding_tree.selection()
        if not selected:
            messagebox.showinfo('尚未選取', '請先選取持股。')
            return
        symbol = str(self.holding_tree.item(selected[0], 'values')[0])
        if messagebox.askyesno('確認刪除', f'確定刪除 {symbol}？'):
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
        self.market_var.set(values[3])
        self.shares_var.set(str(values[4]).replace(',', ''))
        self.total_cost_var.set(str(values[5]).replace(',', ''))

    def clear_form(self) -> None:
        for variable in (self.stock_code_var, self.yahoo_symbol_var, self.stock_name_var, self.shares_var, self.total_cost_var):
            variable.set('')
        self.market_var.set('AUTO')

    def refresh_all_views(self) -> None:
        self.refresh_holding_view()
        self.refresh_dividend_view()
        self.refresh_loaded_data_view()

    def refresh_holding_view(self) -> None:
        holdings = self.database.list_holdings()
        views = build_holding_views(holdings, self.database.get_quote_map())
        summary = summarize_portfolio(views)
        for item in self.holding_tree.get_children():
            self.holding_tree.delete(item)
        for view in views:
            self.holding_tree.insert('', 'end', values=(
                view.symbol, view.stock_code, view.stock_name, view.market_segment,
                f'{view.shares:,}', money(view.total_cost), decimal(view.average_cost),
                decimal(view.close), money(view.market_value), money(view.profit),
                percent(view.return_rate), view.trade_date or '未更新',
            ))
        self.summary_cost_var.set(f'NT$ {money(summary.total_cost)}')
        self.summary_value_var.set(f'NT$ {money(summary.total_market_value)}')
        self.summary_profit_var.set(f'NT$ {money(summary.total_profit)}')
        self.summary_return_var.set(percent(summary.total_return_rate))

    def refresh_dividend_view(self) -> None:
        try:
            target_year = int(self.dividend_year_var.get())
        except ValueError:
            messagebox.showerror('年度錯誤', '請輸入四位數西元年。')
            return
        projections = build_dividend_projection(
            self.database.list_holdings(), self.database.list_actions('DIVIDEND'), target_year
        )
        monthly = summarize_monthly(projections, target_year)
        for tree in (self.monthly_tree, self.dividend_tree):
            for item in tree.get_children():
                tree.delete(item)
        for month, amount in monthly:
            self.monthly_tree.insert('', 'end', values=(month, f'NT$ {money(amount)}'))
        for item in projections:
            self.dividend_tree.insert('', 'end', values=(
                item.month, item.symbol, item.stock_name, f'{item.shares:,}',
                decimal(item.dividend_per_share, 4), f'NT$ {money(item.estimated_amount)}',
                item.basis, item.reference_date,
            ))

    def refresh_loaded_data_view(self) -> None:
        for tree in (self.instrument_tree, self.quote_tree, self.action_tree):
            for item in tree.get_children():
                tree.delete(item)
        instruments = self.database.list_instruments()
        for item in instruments:
            self.instrument_tree.insert('', 'end', values=(
                item.symbol, item.stock_code, item.name, item.exchange,
                item.market_segment, item.quote_type, item.currency,
            ))
        quotes = self.database.list_quotes()
        for row in quotes:
            self.quote_tree.insert('', 'end', values=(
                row['symbol'], row['stock_code'], row['name'], decimal(row['close']),
                decimal(row['previous_close']), decimal(row['change_value']),
                percent(row['change_percent']), f"{row['volume']:,.0f}", row['trade_date'],
            ))
        actions = self.database.list_actions()
        for action in actions:
            type_text = '現金股利' if action.action_type == 'DIVIDEND' else '分割／股票股利'
            value_text = decimal(action.value, 4)
            self.action_tree.insert('', 'end', values=(
                action.action_date, action.symbol, action.stock_code, action.stock_name,
                type_text, value_text, action.source,
            ))
        self.status_var.set(
            f'已載入商品 {len(instruments)}、行情 {len(quotes)}、公司行動 {len(actions)} 筆'
        )

    def export_table(self, table: str) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        defaults = {
            'instruments': ('商品清冊', 'SELECT * FROM instruments ORDER BY symbol'),
            'quotes': ('行情', 'SELECT * FROM market_quotes ORDER BY symbol'),
            'actions': ('公司行動', 'SELECT * FROM corporate_actions ORDER BY action_date DESC, symbol'),
        }
        label, sql = defaults[table]
        suggested = EXPORT_DIR / f'{table}_{timestamp}.csv'
        path_text = filedialog.asksaveasfilename(
            title=f'匯出{label}', initialfile=suggested.name,
            initialdir=str(EXPORT_DIR), defaultextension='.csv',
            filetypes=[('CSV', '*.csv')],
        )
        if not path_text:
            return
        count = self.database.export_query_to_csv(sql, Path(path_text))
        messagebox.showinfo('匯出完成', f'已匯出 {count} 筆：\n{path_text}')
