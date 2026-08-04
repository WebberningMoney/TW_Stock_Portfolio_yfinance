"""應用程式進入點。"""

from __future__ import annotations

import logging
import multiprocessing
import sys
import tkinter as tk
from tkinter import messagebox

from app.branding import APP_NAME
from app.config import LOG_FILE_PATH, WINDOW_SIZE
from app.db.database import Database
from app.paths import ensure_runtime_directories
from app.ui.main_window import PortfolioApp


def configure_file_logging() -> None:
    """將打包後看不到的錯誤寫入 macOS 使用者 Logs 資料夾。"""
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE_PATH, encoding='utf-8'),
        ],
        force=True,
    )


def center_window(root: tk.Tk, size: str) -> None:
    """依螢幕尺寸將主視窗置中。"""
    width_text, height_text = size.lower().split('x', maxsplit=1)
    requested_width = int(width_text)
    requested_height = int(height_text)

    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()

    width = min(requested_width, max(screen_width - 70, 1180))
    height = min(requested_height, max(screen_height - 55, 760))
    x = max((screen_width - width) // 2, 0)
    y = max((screen_height - height) // 2, 0)
    root.geometry(f'{width}x{height}+{x}+{y}')


def main() -> None:
    """初始化資料夾、資料庫與 Tkinter GUI。"""
    multiprocessing.freeze_support()
    ensure_runtime_directories()
    configure_file_logging()

    root: tk.Tk | None = None
    try:
        database = Database()
        database.initialize()

        root = tk.Tk()
        root.withdraw()
        root.title(APP_NAME)

        # 讓 Tk 的應用程式名稱、macOS 選單列與視窗標題盡量保持一致。
        try:
            root.tk.call('tk', 'appname', APP_NAME)
        except tk.TclError:
            pass

        root.minsize(1160, 740)
        center_window(root, WINDOW_SIZE)

        PortfolioApp(root=root, database=database)
        root.deiconify()
        root.mainloop()
    except Exception as exc:  # 啟動階段最後一道保護，避免雙擊後毫無反應。
        logging.exception('應用程式啟動失敗')
        try:
            if root is None:
                root = tk.Tk()
                root.withdraw()
            messagebox.showerror(
                f'{APP_NAME}－啟動失敗',
                f'程式無法啟動：\n\n{exc}\n\n'
                f'詳細紀錄已寫入：\n{LOG_FILE_PATH}',
                parent=root,
            )
        except Exception:
            pass
        raise


if __name__ == '__main__':
    main()
