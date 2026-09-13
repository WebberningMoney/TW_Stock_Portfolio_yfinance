"""資料抓取參數與單筆診斷頁。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from app.config import (
    DIVIDEND_SOURCE_CHOICES,
    DIVIDEND_SOURCE_LABEL_TO_KEY,
    SINGLE_TEST_CHOICES,
    SINGLE_TEST_LABEL_TO_KEY,
)
from app.settings import RuntimeSettings


def _format_float(value: object) -> str:
    return f'{value:g}'


@dataclass(frozen=True, slots=True)
class _SettingField:
    """RuntimeSettings 欄位跟表單變數之間的對應規則。"""

    name: str
    var_name: str
    parse: Callable[[str], object]
    format: Callable[[object], str]


_SETTING_FIELDS: tuple[_SettingField, ...] = (
    _SettingField('screener_page_size', 'setting_screener_page_size_var', int, str),
    _SettingField('screener_max_pages', 'setting_screener_max_pages_var', int, str),
    _SettingField('quote_batch_size', 'setting_quote_batch_var', int, str),
    _SettingField('quote_period', 'setting_quote_period_var', str, str),
    _SettingField('quote_interval', 'setting_quote_interval_var', str, str),
    _SettingField('download_threads', 'setting_threads_var', int, str),
    _SettingField(
        'yfinance_timeout_seconds', 'setting_yfinance_timeout_var', int, str
    ),
    _SettingField(
        'quote_batch_delay_seconds',
        'setting_quote_delay_var',
        float,
        _format_float,
    ),
    _SettingField('action_period', 'setting_action_period_var', str, str),
    _SettingField('action_batch_size', 'setting_action_batch_var', int, str),
    _SettingField(
        'action_download_threads', 'setting_action_threads_var', int, str
    ),
    _SettingField(
        'action_item_delay_seconds',
        'setting_action_delay_var',
        float,
        _format_float,
    ),
    _SettingField('scraper_workers', 'setting_scraper_workers_var', int, str),
    _SettingField(
        'scraper_delay_seconds',
        'setting_scraper_delay_var',
        float,
        _format_float,
    ),
    _SettingField(
        'scraper_timeout_seconds', 'setting_scraper_timeout_var', int, str
    ),
    _SettingField('item_retries', 'setting_retries_var', int, str),
    _SettingField(
        'retry_backoff_seconds',
        'setting_backoff_var',
        float,
        _format_float,
    ),
)


class SettingsPageMixin:
    def _build_settings_tab(self, parent) -> None:
        intro = ttk.Frame(parent, style='Card.TFrame', padding=(12, 9))
        intro.pack(fill='x', pady=(0, 8))
        ttk.Label(
            intro,
            text='資料抓取參數與診斷',
            style='Header.Title.TLabel',
        ).pack(anchor='w')
        ttk.Label(
            intro,
            text=(
                '參數依「商品清冊、行情、股利／分割、Yahoo 台灣爬蟲」分組；'
                '只有遇到限流、逾時或大量同步時才需要調整。'
            ),
            style='Header.Subtitle.TLabel',
        ).pack(anchor='w', pady=(2, 0))

        pane = ttk.Panedwindow(parent, orient='horizontal')
        pane.pack(fill='both', expand=True)
        left = ttk.Frame(pane, padding=(0, 0, 8, 0))
        right = ttk.Frame(pane, padding=(8, 0, 0, 0))
        pane.add(left, weight=3)
        pane.add(right, weight=2)

        self._init_settings_variables()
        self._build_universe_settings(left)
        self._build_quote_settings(left)
        self._build_dividend_settings(left)
        self._build_resilience_settings(left)
        self._build_settings_actions(left)
        self._build_single_test_panel(right)
        self._build_parameter_guidance(right)

    def _init_settings_variables(self) -> None:
        settings = self.settings
        for field in _SETTING_FIELDS:
            setattr(
                self,
                field.var_name,
                tk.StringVar(value=field.format(getattr(settings, field.name))),
            )
        self.setting_repair_var = tk.BooleanVar(
            value=settings.enable_price_repair
        )

        self.single_test_symbol_var = tk.StringVar(value='0050.TW')
        self.single_test_mode_var = tk.StringVar(value=SINGLE_TEST_CHOICES['ALL'])

    @staticmethod
    def _add_setting_row(
        frame,
        row: int,
        label: str,
        variable,
        hint: str,
        column_pair: int = 0,
        width: int = 9,
    ) -> None:
        column = column_pair * 2
        ttk.Label(frame, text=label).grid(
            row=row, column=column, sticky='e', padx=(4, 5), pady=4
        )
        box = ttk.Frame(frame)
        box.grid(row=row, column=column + 1, sticky='w', pady=4)
        ttk.Entry(box, textvariable=variable, width=width).pack(side='left')
        ttk.Label(box, text=hint, foreground='#64748B').pack(
            side='left', padx=(7, 0)
        )

    def _build_universe_settings(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text='A. 商品清冊建立', padding=9)
        frame.pack(fill='x', pady=(0, 7))
        for col in range(4):
            frame.columnconfigure(col, weight=1 if col in {1, 3} else 0)
        self._add_setting_row(
            frame, 0, 'Screener 每頁筆數',
            self.setting_screener_page_size_var, '只影響建立商品清冊', 0
        )
        self._add_setting_row(
            frame, 0, 'Screener 最大頁數',
            self.setting_screener_max_pages_var, '限制清冊最多翻頁數', 1
        )

    def _build_quote_settings(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text='B. 商品行情下載', padding=9)
        frame.pack(fill='x', pady=(0, 7))
        for col in range(4):
            frame.columnconfigure(col, weight=1 if col in {1, 3} else 0)

        self._add_setting_row(
            frame, 0, '每批商品數', self.setting_quote_batch_var,
            '建議 60～120', 0
        )
        self._add_setting_row(
            frame, 0, '同時下載執行緒', self.setting_threads_var,
            '建議 6～10', 1
        )
        self._add_setting_row(
            frame, 1, '請求逾時秒數', self.setting_yfinance_timeout_var,
            '網路不穩可提高', 0
        )
        self._add_setting_row(
            frame, 1, '批次間隔秒數', self.setting_quote_delay_var,
            '越低越快、限流風險較高', 1
        )

        ttk.Label(frame, text='行情回看期間').grid(
            row=2, column=0, sticky='e', padx=(4, 5), pady=4
        )
        ttk.Combobox(
            frame,
            textvariable=self.setting_quote_period_var,
            values=('5d', '1mo', '3mo', '6mo', '1y'),
            state='readonly',
            width=9,
        ).grid(row=2, column=1, sticky='w', pady=4)
        ttk.Label(frame, text='行情資料間隔').grid(
            row=2, column=2, sticky='e', padx=(4, 5), pady=4
        )
        ttk.Combobox(
            frame,
            textvariable=self.setting_quote_interval_var,
            values=('1d', '5d', '1wk', '1mo'),
            state='readonly',
            width=9,
        ).grid(row=2, column=3, sticky='w', pady=4)
        ttk.Checkbutton(
            frame,
            text='啟用 yfinance 價格修復（需要 SciPy；行情與歷史資料均會使用）',
            variable=self.setting_repair_var,
        ).grid(row=3, column=0, columnspan=4, sticky='w', pady=(5, 0))

    def _build_dividend_settings(self, parent) -> None:
        frame = ttk.LabelFrame(
            parent,
            text='C. 持股股利／股票分割同步',
            padding=9,
        )
        frame.pack(fill='x', pady=(0, 7))
        for col in range(4):
            frame.columnconfigure(col, weight=1 if col in {1, 3} else 0)

        ttk.Label(frame, text='兩來源共用抓取範圍').grid(
            row=0, column=0, sticky='e', padx=(4, 5), pady=4
        )
        ttk.Combobox(
            frame,
            textvariable=self.setting_action_period_var,
            values=('1y', '2y', '3y', '5y', '10y', 'max'),
            state='readonly',
            width=9,
        ).grid(row=0, column=1, sticky='w', pady=4)
        ttk.Label(
            frame,
            text='同步前會清除選定來源舊資料，再依此範圍重建',
            foreground=self.colors['muted'],
        ).grid(row=0, column=2, columnspan=2, sticky='w', pady=4)

        self._add_setting_row(
            frame, 1, 'API 每批持股數', self.setting_action_batch_var,
            'yfinance actions=True', 0
        )
        self._add_setting_row(
            frame, 1, 'API 同時下載執行緒', self.setting_action_threads_var,
            '建議 4～8', 1
        )
        self._add_setting_row(
            frame, 2, 'API 批次間隔秒數', self.setting_action_delay_var,
            '持股少可設 0～0.1', 0
        )
        self._add_setting_row(
            frame, 2, '爬蟲同時抓取檔數', self.setting_scraper_workers_var,
            '建議 2～4', 1
        )
        self._add_setting_row(
            frame, 3, '爬蟲單檔間隔秒數', self.setting_scraper_delay_var,
            '建議 0.3～0.8', 0
        )
        self._add_setting_row(
            frame, 3, '爬蟲逾時秒數', self.setting_scraper_timeout_var,
            '建議 20～40', 1
        )

    def _build_resilience_settings(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text='D. 通用重試與容錯', padding=9)
        frame.pack(fill='x', pady=(0, 7))
        for col in range(4):
            frame.columnconfigure(col, weight=1 if col in {1, 3} else 0)
        self._add_setting_row(
            frame, 0, '單一項目重試次數', self.setting_retries_var,
            '行情、API、爬蟲共用', 0
        )
        self._add_setting_row(
            frame, 0, '重試退避秒數', self.setting_backoff_var,
            '每次失敗逐步增加', 1
        )

    def _build_settings_actions(self, parent) -> None:
        frame = ttk.Frame(parent)
        frame.pack(fill='x')
        ttk.Button(
            frame,
            text='儲存並立即套用',
            command=self.save_runtime_settings,
            style='Accent.TButton',
        ).pack(side='left')
        ttk.Button(
            frame,
            text='恢復建議預設值',
            command=self.reset_runtime_settings,
        ).pack(side='left', padx=7)
        ttk.Label(
            frame,
            text='設定檔：data/app_settings.json',
            foreground=self.colors['muted'],
        ).pack(side='right')

    def _build_single_test_panel(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text='單筆資料測試（不寫入資料庫）', padding=10)
        frame.pack(fill='both', expand=True, pady=(0, 8))
        form = ttk.Frame(frame)
        form.pack(fill='x', pady=(0, 7))
        ttk.Label(form, text='代號／Symbol').grid(row=0, column=0, sticky='e')
        ttk.Entry(
            form,
            textvariable=self.single_test_symbol_var,
            width=16,
        ).grid(row=0, column=1, padx=6, sticky='w')
        ttk.Label(form, text='測試項目').grid(row=1, column=0, sticky='e', pady=(7, 0))
        ttk.Combobox(
            form,
            textvariable=self.single_test_mode_var,
            values=list(SINGLE_TEST_CHOICES.values()),
            state='readonly',
            width=31,
        ).grid(row=1, column=1, padx=6, pady=(7, 0), sticky='w')
        ttk.Button(
            form,
            text='執行單筆測試',
            command=self.run_single_test_async,
            style='Accent.TButton',
        ).grid(row=2, column=1, padx=6, pady=(9, 0), sticky='w')

        self.single_test_output = scrolledtext.ScrolledText(
            frame,
            wrap='word',
            height=12,
            font=('Menlo', 10),
            state='disabled',
            background='#F8FAFC',
            foreground=self.colors['text'],
            relief='flat',
        )
        self.single_test_output.pack(fill='both', expand=True, pady=(8, 0))

    def _build_parameter_guidance(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text='效能與穩定性建議', padding=10)
        frame.pack(fill='x')
        guidance = (
            '• 行情：優先增加每批商品數；執行緒超過 10 通常不會等比例加速。\n'
            '• 股利 API：新版採批次 actions=True；持股 10～50 檔通常 4～8 執行緒即可。\n'
            '• 爬蟲：建議 2～4 個並行工作，避免短時間對 Yahoo 台灣造成過多請求。\n'
            '• 抓取範圍：1y／3y／5y 同時套用 API 與爬蟲；max 最完整但最慢。\n'
            '• 清除重建：股利同步會先清除本次選定來源，再完整重建該範圍。\n'
            '• 單筆測試：大量同步前先測試 2608.TW、0050.TW 等代表性商品。'
        )
        ttk.Label(
            frame,
            text=guidance,
            justify='left',
            foreground=self.colors['muted'],
            wraplength=500,
        ).pack(anchor='w')

    def _settings_from_form(self) -> RuntimeSettings:
        source_mode = DIVIDEND_SOURCE_LABEL_TO_KEY.get(
            self.dividend_source_var.get(),
            'BOTH',
        )
        field_values = {
            field.name: field.parse(getattr(self, field.var_name).get())
            for field in _SETTING_FIELDS
        }
        return RuntimeSettings(
            dividend_source_mode=source_mode,
            enable_price_repair=bool(self.setting_repair_var.get()),
            **field_values,
        ).normalized()

    def remember_dividend_source(self) -> None:
        mode = DIVIDEND_SOURCE_LABEL_TO_KEY.get(
            self.dividend_source_var.get(),
            'BOTH',
        )
        self.settings.dividend_source_mode = mode
        self.settings = self.settings_store.save(self.settings)

    def save_runtime_settings(self) -> None:
        try:
            settings = self._settings_from_form()
        except ValueError:
            messagebox.showerror('設定錯誤', '請確認所有數字欄位均為有效數字。')
            return
        self.settings = self.settings_store.save(settings)
        self.sync_service.update_settings(self.settings)
        self.dividend_source_var.set(
            DIVIDEND_SOURCE_CHOICES[self.settings.dividend_source_mode]
        )
        self.status_var.set('抓取參數已儲存並立即套用')
        messagebox.showinfo('設定完成', '抓取參數已儲存並立即套用。')

    def reset_runtime_settings(self) -> None:
        if not messagebox.askyesno('恢復預設值', '確定恢復建議預設參數？'):
            return
        self.settings = self.settings_store.reset()
        self.sync_service.update_settings(self.settings)
        self.dividend_source_var.set(
            DIVIDEND_SOURCE_CHOICES[self.settings.dividend_source_mode]
        )
        self._reload_settings_form()
        self.status_var.set('已恢復建議預設參數')

    def _reload_settings_form(self) -> None:
        settings = self.settings
        for field in _SETTING_FIELDS:
            getattr(self, field.var_name).set(
                field.format(getattr(settings, field.name))
            )
        self.setting_repair_var.set(settings.enable_price_repair)

    def run_single_test_async(self) -> None:
        query = self.single_test_symbol_var.get().strip()
        mode = SINGLE_TEST_LABEL_TO_KEY.get(
            self.single_test_mode_var.get(),
            'ALL',
        )
        if not query:
            messagebox.showwarning('缺少代號', '請輸入股票代號或 Yahoo Symbol。')
            return
        self._run_background(
            f'正在執行單筆測試：{query}……',
            lambda: self.sync_service.test_single_item(
                query=query,
                test_mode=mode,
                progress=self._progress,
            ),
            self._after_single_test,
        )

    def _after_single_test(self, result) -> None:
        text = result.to_text()
        self.single_test_output.configure(state='normal')
        self.single_test_output.delete('1.0', 'end')
        self.single_test_output.insert('1.0', text)
        self.single_test_output.configure(state='disabled')
        self._finish_operation(f'單筆測試完成：{result.symbol}')
        self.main_notebook.select(self.settings_tab)
