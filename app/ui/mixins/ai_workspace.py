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
from app.services.ai_prompt_service import build_analysis_prompt, build_news_prompt
from app.services.dividend_service import (
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
        return self.holding_view_state.selected()

    def refresh_prompts(self) -> None:
        view = self._selected_holding_view()
        if view is None:
            self.ai_selected_var.set('請先在庫存表選取一檔持股')
            return
        self.ai_selected_var.set(
            f'{view.stock_code} {view.stock_name}｜{view.shares:,} 股｜'
            f'報酬率 {view.return_rate:,.2f}%'
        )
        self._set_text_widget(
            self.ai_news_text, build_news_prompt(view, date.today())
        )
        self._set_text_widget(
            self.ai_analysis_text,
            build_analysis_prompt(view, self._dividend_projections),
        )

    def _copy_ai_prompt(self, prompt_type: str) -> None:
        view = self._selected_holding_view()
        if view is None:
            messagebox.showinfo('尚未選取', '請先在庫存表選取一檔持股。')
            return
        prompt = (
            build_news_prompt(view, date.today())
            if prompt_type == 'news'
            else build_analysis_prompt(view, self._dividend_projections)
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
