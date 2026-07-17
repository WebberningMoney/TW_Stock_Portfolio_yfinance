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


class DividendPageMixin:
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
                '金額均依目前持股股數估算。'
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

        # v2.2：維持左右切版。左側專注圖表，右側完整呈現摘要與明細。
        pane = ttk.Panedwindow(parent, orient='horizontal')
        self.dividend_pane = pane
        pane.pack(fill='both', expand=True)

        chart_frame = ttk.LabelFrame(
            pane,
            text='每月股利金額與持股組成（滑鼠移到月份可查看明細；點擊可切換月份）',
            padding=5,
        )
        tables_frame = ttk.LabelFrame(
            pane,
            text='月份與全年明細',
            padding=5,
        )
        pane.add(chart_frame, weight=3)
        pane.add(tables_frame, weight=2)

        self.dividend_figure = Figure(
            figsize=(10.0, 7.2),
            dpi=100,
            facecolor=self.colors['surface'],
        )
        self.dividend_ax = self.dividend_figure.add_subplot(111)
        self.dividend_canvas = FigureCanvasTkAgg(
            self.dividend_figure,
            master=chart_frame,
        )
        chart_widget = self.dividend_canvas.get_tk_widget()
        chart_widget.configure(height=650)
        chart_widget.pack(fill='both', expand=True)

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
                'month': 105,
                'realized': 135,
                'pending': 135,
                'total': 135,
            },
            height=14,
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
            text='實心＝已實現；斜線＝未領／估算。',
            foreground=self.colors['muted'],
        ).pack(side='left', padx=10)

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
                'status': 100,
                'code': 80,
                'name': 145,
                'shares': 100,
                'dps': 100,
                'amount': 120,
                'basis': 210,
            },
            height=14,
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
            'month': 80, 'status': 95, 'symbol': 100, 'name': 130,
            'shares': 80, 'dps': 90, 'amount': 110, 'period': 85,
            'basis': 220, 'reference': 100, 'payment': 100,
        }
        self.dividend_tree = self._create_tree(
            detail_tab, columns, headings, widths, height=14
        )
        self.dividend_tree.tag_configure(
            REALIZED, foreground=self.colors['realized']
        )
        self.dividend_tree.tag_configure(
            PENDING, foreground='#B45309'
        )

    def _set_default_dividend_sash(self) -> None:
        """左右切版預設讓圖表約占 58%，右側表格保留足夠寬度。"""
        pane = getattr(self, 'dividend_pane', None)
        if pane is None:
            return
        pane.update_idletasks()
        width = pane.winfo_width()
        if width < 900:
            return
        try:
            position = min(max(int(width * 0.58), 650), width - 520)
            pane.sashpos(0, position)
        except tk.TclError:
            pass

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
        if self.holding_tree.selection():
            self._refresh_ai_prompts()

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
            pad=7,
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

        # 預設使用單欄；只有實際可用高度不足時才自動增加欄數。
        # 最多顯示 30 檔，其餘以一個彙總項目表示。
        legend_symbols = symbols[:30]
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

            canvas_widget = self.dividend_canvas.get_tk_widget()
            canvas_widget.update_idletasks()
            canvas_height = max(canvas_widget.winfo_height(), 420)

            # 每列圖例約需要 21px，再保留標題與上下空間。
            available_rows = max(7, int((canvas_height - 115) / 21))
            legend_columns = max(
                1,
                math.ceil(len(legend_handles) / available_rows),
            )
            legend_columns = min(legend_columns, 4)

            # 欄數越多，為右側圖例保留越多水平空間。
            chart_right = max(0.54, 0.81 - 0.075 * (legend_columns - 1))
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
                right=chart_right,
                top=0.83,
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
                left=0.065, right=0.97, top=0.83, bottom=0.14
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
