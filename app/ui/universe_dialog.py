"""建立 Yahoo 台灣商品清冊前的商品類型選擇視窗。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.config import (
    DEFAULT_UNIVERSE_CATEGORIES,
    UNIVERSE_CATEGORY_CHOICES,
)


class UniverseSelectionDialog:
    """Modal dialog，讓使用者選擇清冊下載範圍。"""

    def __init__(self, parent: tk.Tk) -> None:
        self.parent = parent
        self.result: dict | None = None
        self.window = tk.Toplevel(parent)
        self.window.title('選擇 Yahoo 台灣商品清冊範圍')
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol('WM_DELETE_WINDOW', self._cancel)

        self.category_vars = {
            key: tk.BooleanVar(value=key in DEFAULT_UNIVERSE_CATEGORIES)
            for key in UNIVERSE_CATEGORY_CHOICES
        }
        self.enrich_names_var = tk.BooleanVar(value=True)
        self.rebuild_var = tk.BooleanVar(value=True)

        self._build()
        self._center_over_parent()
        self.window.grab_set()

    def _build(self) -> None:
        outer = ttk.Frame(self.window, padding=16)
        outer.pack(fill='both', expand=True)

        ttk.Label(
            outer,
            text='請選擇要建立的台灣商品種類',
            font=('', 13, 'bold'),
        ).pack(anchor='w', pady=(0, 8))

        ttk.Label(
            outer,
            text=(
                '預設只建立公司股票與 ETF；權證、ETN 及其他商品不勾選，'
                '可大幅減少資料列數與行情下載時間。'
            ),
            wraplength=520,
            justify='left',
        ).pack(anchor='w', pady=(0, 10))

        category_frame = ttk.LabelFrame(
            outer,
            text='市場商品種類',
            padding=10,
        )
        category_frame.pack(fill='x')

        for index, (key, label) in enumerate(
            UNIVERSE_CATEGORY_CHOICES.items()
        ):
            ttk.Checkbutton(
                category_frame,
                text=label,
                variable=self.category_vars[key],
            ).grid(
                row=index // 2,
                column=index % 2,
                sticky='w',
                padx=8,
                pady=5,
            )

        option_frame = ttk.LabelFrame(
            outer,
            text='建立方式',
            padding=10,
        )
        option_frame.pack(fill='x', pady=(10, 0))

        ttk.Checkbutton(
            option_frame,
            text='完整補強繁中名稱（會增加下載時間）',
            variable=self.enrich_names_var,
        ).pack(anchor='w', pady=3)
        ttk.Checkbutton(
            option_frame,
            text='清除舊商品清冊與行情後重建（持股與股利紀錄保留）',
            variable=self.rebuild_var,
        ).pack(anchor='w', pady=3)

        buttons = ttk.Frame(outer)
        buttons.pack(fill='x', pady=(14, 0))
        ttk.Button(
            buttons,
            text='取消',
            command=self._cancel,
        ).pack(side='right', padx=(6, 0))
        ttk.Button(
            buttons,
            text='開始建立',
            command=self._confirm,
        ).pack(side='right')

    def _center_over_parent(self) -> None:
        self.window.update_idletasks()
        width = self.window.winfo_reqwidth()
        height = self.window.winfo_reqheight()
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()
        x = parent_x + max((parent_width - width) // 2, 0)
        y = parent_y + max((parent_height - height) // 2, 0)
        self.window.geometry(f'{width}x{height}+{x}+{y}')

    def _confirm(self) -> None:
        categories = {
            key
            for key, variable in self.category_vars.items()
            if variable.get()
        }
        if not categories:
            messagebox.showwarning(
                '尚未選擇',
                '請至少選擇一種商品類型。',
                parent=self.window,
            )
            return

        self.result = {
            'categories': categories,
            'enrich_names': self.enrich_names_var.get(),
            'rebuild': self.rebuild_var.get(),
        }
        self.window.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.window.destroy()

    def show(self) -> dict | None:
        self.parent.wait_window(self.window)
        return self.result
