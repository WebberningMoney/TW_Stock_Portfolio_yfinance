"""應用程式進入點。"""

import tkinter as tk

from app.config import APP_TITLE, WINDOW_SIZE
from app.db.database import Database
from app.ui.main_window import PortfolioApp


def center_window(root: tk.Tk, size: str) -> None:
    """依螢幕尺寸將主視窗置中。"""
    width_text, height_text = size.lower().split('x', maxsplit=1)
    width = int(width_text)
    height = int(height_text)

    root.update_idletasks()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = max((screen_width - width) // 2, 0)
    y = max((screen_height - height) // 2, 0)
    root.geometry(f'{width}x{height}+{x}+{y}')


def main() -> None:
    """初始化資料庫並啟動 Tkinter GUI。"""
    database = Database()
    database.initialize()

    root = tk.Tk()
    root.withdraw()
    root.title(APP_TITLE)
    root.minsize(1180, 720)
    center_window(root, WINDOW_SIZE)

    PortfolioApp(root=root, database=database)
    root.deiconify()
    root.mainloop()


if __name__ == '__main__':
    main()
