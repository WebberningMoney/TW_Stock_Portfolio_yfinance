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


class AiWorkspaceMixin:
    def _build_ai_sidebar(self, parent) -> None:
        """
        建立不需 API Key 的 AI 手動研究工作區。

        程式只整理持股資料、產生提示詞及開啟網站；不會在背景自動登入、
        讀取 ChatGPT／Gemini 帳號，亦不會自動執行交易。
        """
        header = ttk.Frame(parent, style='Card.TFrame', padding=9)
        header.pack(fill='x', pady=(0, 8))
        ttk.Label(
            header,
            text='AI 研究工作區（手動模式）',
            style='Card.TLabel',
            font=('', 12, 'bold'),
        ).pack(anchor='w')
        ttk.Label(
            header,
            textvariable=self.ai_selected_var,
            style='Card.TLabel',
            foreground=self.colors['primary_dark'],
            wraplength=330,
        ).pack(anchor='w', pady=(4, 0))
        ttk.Label(
            header,
            text='選取左側持股後，複製提示詞並開啟 AI 網頁。',
            style='Card.TLabel',
            foreground=self.colors['muted'],
            wraplength=330,
        ).pack(anchor='w', pady=(3, 0))

        news_frame = ttk.LabelFrame(
            parent,
            text='持有個股新聞研究',
            padding=7,
        )
        news_frame.pack(fill='both', expand=True, pady=(0, 8))
        self.ai_news_text = scrolledtext.ScrolledText(
            news_frame,
            wrap='word',
            height=10,
            font=('', 10),
            background='#F8FAFC',
            foreground=self.colors['text'],
        )
        self.ai_news_text.pack(fill='both', expand=True)
        news_buttons = ttk.Frame(news_frame)
        news_buttons.pack(fill='x', pady=(6, 0))
        ttk.Button(
            news_buttons,
            text='複製提示詞',
            command=lambda: self._copy_ai_prompt('news'),
        ).pack(side='left', padx=(0, 4))
        ttk.Button(
            news_buttons,
            text='貼上 AI 回覆',
            command=lambda: self._paste_ai_response(self.ai_news_text),
        ).pack(side='left', padx=4)

        analysis_frame = ttk.LabelFrame(
            parent,
            text='加倉／減倉／操作研究',
            padding=7,
        )
        analysis_frame.pack(fill='both', expand=True)
        self.ai_analysis_text = scrolledtext.ScrolledText(
            analysis_frame,
            wrap='word',
            height=10,
            font=('', 10),
            background='#F8FAFC',
            foreground=self.colors['text'],
        )
        self.ai_analysis_text.pack(fill='both', expand=True)
        analysis_buttons = ttk.Frame(analysis_frame)
        analysis_buttons.pack(fill='x', pady=(6, 0))
        ttk.Button(
            analysis_buttons,
            text='複製提示詞',
            command=lambda: self._copy_ai_prompt('analysis'),
        ).pack(side='left', padx=(0, 4))
        ttk.Button(
            analysis_buttons,
            text='貼上 AI 回覆',
            command=lambda: self._paste_ai_response(self.ai_analysis_text),
        ).pack(side='left', padx=4)

        launch_frame = ttk.Frame(parent)
        launch_frame.pack(fill='x', pady=(8, 0))
        ttk.Button(
            launch_frame,
            text='開啟 ChatGPT',
            command=lambda: self._open_ai_site('chatgpt'),
            style='Accent.TButton',
        ).pack(side='left', fill='x', expand=True, padx=(0, 4))
        ttk.Button(
            launch_frame,
            text='開啟 Gemini',
            command=lambda: self._open_ai_site('gemini'),
        ).pack(side='left', fill='x', expand=True, padx=(4, 0))

        self._set_text_widget(
            self.ai_news_text,
            '請先在左側庫存表選取一檔持股。',
        )
        self._set_text_widget(
            self.ai_analysis_text,
            '請先在左側庫存表選取一檔持股。',
        )

    @staticmethod
    def _set_text_widget(widget: tk.Text, content: str) -> None:
        widget.delete('1.0', 'end')
        widget.insert('1.0', content)

    def _selected_holding_view(self):
        selected = self.holding_tree.selection()
        if not selected:
            return None
        values = self.holding_tree.item(selected[0], 'values')
        if not values:
            return None
        return self._holding_view_by_symbol.get(str(values[0]))

    def _build_news_prompt(self, view) -> str:
        today_text = date.today().isoformat()
        return (
            f'今天是 {today_text}。請使用網路搜尋，研究台灣證券 {view.stock_code} '
            f'{view.stock_name}（Yahoo Symbol：{view.symbol}）最近 30 天的重要新聞。\n\n'
            '請依序整理：\n'
            '1. 最新營收、財報、法說、接單、產業與重大訊息。\n'
            '2. 可能影響股價或股利能力的正面與負面因素。\n'
            '3. 每則資訊標示日期、來源與可開啟的引用。\n'
            '4. 明確區分已確認事實、媒體推測與你的推論。\n'
            '5. 最後列出未來 30～90 天值得追蹤的事件。\n\n'
            f'目前持有：{view.shares:,} 股；平均成本 NT$ {view.average_cost:,.2f}；'
            f'最近收盤 NT$ {view.close:,.2f}；未實現報酬率 {view.return_rate:,.2f}%。'
        )

    def _build_analysis_prompt(self, view) -> str:
        selected_dividends = [
            item for item in self._dividend_projections
            if item.symbol == view.symbol
        ]
        realized = sum(
            item.estimated_amount for item in selected_dividends
            if item.status == REALIZED
        )
        pending = sum(
            item.estimated_amount for item in selected_dividends
            if item.status == PENDING
        )
        return (
            '請以台股投資研究員角度，根據下列持股資料及最新可查證資訊，'
            '評估加倉、續抱、減倉或等待的條件。請勿只給單一結論，並避免保證報酬。\n\n'
            f'標的：{view.stock_code} {view.stock_name}（{view.symbol}）\n'
            f'市場：{self._market_label(view.market_segment)}\n'
            f'持有股數：{view.shares:,} 股\n'
            f'總成本：NT$ {view.total_cost:,.0f}\n'
            f'平均成本：NT$ {view.average_cost:,.2f}\n'
            f'最近收盤：NT$ {view.close:,.2f}\n'
            f'庫存市值：NT$ {view.market_value:,.0f}\n'
            f'未實現損益：NT$ {view.profit:,.0f}（{view.return_rate:,.2f}%）\n'
            f'目前分析年度股利：已實現約 NT$ {realized:,.0f}；未領／預估約 NT$ {pending:,.0f}。\n\n'
            '請輸出：\n'
            '1. 基本面、產業面、籌碼／估值與股利持續性的重點。\n'
            '2. 加倉、續抱、減倉三種情境各自的觸發條件。\n'
            '3. 需要避免加碼的風險訊號。\n'
            '4. 以小幅／中幅／大幅調整持股比例的方式說明，不要直接替我下單。\n'
            '5. 所有最新事實附日期與來源，並清楚標示推論。'
        )

    def _refresh_ai_prompts(self) -> None:
        view = self._selected_holding_view()
        if view is None:
            self.ai_selected_var.set('請先在庫存表選取一檔持股')
            return
        self.ai_selected_var.set(
            f'{view.stock_code} {view.stock_name}｜{view.shares:,} 股｜'
            f'報酬率 {view.return_rate:,.2f}%'
        )
        self._set_text_widget(self.ai_news_text, self._build_news_prompt(view))
        self._set_text_widget(
            self.ai_analysis_text,
            self._build_analysis_prompt(view),
        )

    def _copy_ai_prompt(self, prompt_type: str) -> None:
        view = self._selected_holding_view()
        if view is None:
            messagebox.showinfo('尚未選取', '請先在庫存表選取一檔持股。')
            return
        prompt = (
            self._build_news_prompt(view)
            if prompt_type == 'news'
            else self._build_analysis_prompt(view)
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        target = self.ai_news_text if prompt_type == 'news' else self.ai_analysis_text
        self._set_text_widget(target, prompt)
        self.status_var.set('提示詞已複製，可貼到 ChatGPT 或 Gemini。')

    def _paste_ai_response(self, widget: tk.Text) -> None:
        try:
            content = self.root.clipboard_get()
        except tk.TclError:
            messagebox.showinfo('剪貼簿為空', '請先複製 AI 回覆內容。')
            return
        self._set_text_widget(widget, str(content))

    @staticmethod
    def _open_ai_site(provider: str) -> None:
        url = (
            'https://chatgpt.com/'
            if provider == 'chatgpt'
            else 'https://gemini.google.com/app'
        )
        webbrowser.open_new_tab(url)

    def _toggle_ai_sidebar(self) -> None:
        """收合或顯示右側 AI 研究區，讓庫存表可使用完整寬度。"""
        pane = getattr(self, 'holding_pane', None)
        sidebar = getattr(self, 'ai_sidebar_frame', None)
        if pane is None or sidebar is None:
            return
        try:
            if self.ai_sidebar_visible:
                pane.forget(sidebar)
                self.ai_sidebar_visible = False
                self.ai_toggle_button.configure(text='顯示 AI 研究區')
            else:
                pane.add(sidebar, weight=2)
                self.ai_sidebar_visible = True
                self.ai_toggle_button.configure(text='隱藏 AI 研究區')
                self.root.after_idle(self._set_default_holding_sash)
        except tk.TclError:
            return

    def _set_default_holding_sash(self) -> None:
        """預設為 AI 工作區保留約 360px 寬度。"""
        pane = getattr(self, 'holding_pane', None)
        if pane is None:
            return
        pane.update_idletasks()
        width = pane.winfo_width()
        if width < 900:
            return
        if not getattr(self, 'ai_sidebar_visible', True):
            return
        try:
            pane.sashpos(0, max(width - 410, int(width * 0.72)))
        except tk.TclError:
            pass
