from __future__ import annotations

import math
import logging
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


class StyleMixin:
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

        # Matplotlib 在部分 macOS 字型只有 Regular、沒有獨立 Bold 檔時，
        # 會把「找不到 bold、改用 600」印到 Terminal。這不是程式錯誤，
        # 但會讓使用者誤以為啟動失敗，因此只隱藏字型比對的非必要訊息。
        logging.getLogger('matplotlib.font_manager').setLevel(logging.ERROR)

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
        # 配息頁右側使用較緊湊的摘要字型，避免三張年度卡片佔用過多高度。
        style.configure(
            'Realized.CompactSummary.TLabel',
            font=('', 12, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['realized'],
        )
        style.configure(
            'Pending.CompactSummary.TLabel',
            font=('', 12, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['pending'],
        )
        style.configure(
            'Total.CompactSummary.TLabel',
            font=('', 12, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['total'],
        )
        style.configure(
            'Quarter.Title.TLabel',
            font=('', 9, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['muted'],
        )
        style.configure(
            'Quarter.Value.TLabel',
            font=('', 10, 'bold'),
            background=self.colors['surface'],
            foreground=self.colors['primary_dark'],
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
            'Header.Title.TLabel',
            background=self.colors['surface'],
            foreground=self.colors['primary_dark'],
            font=('', 17, 'bold'),
        )
        style.configure(
            'Header.Subtitle.TLabel',
            background=self.colors['surface'],
            foreground=self.colors['muted'],
            font=('', 10),
        )
        style.configure(
            'Compact.TButton',
            padding=(8, 4),
            background='#EEF3FA',
            foreground=self.colors['text'],
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
