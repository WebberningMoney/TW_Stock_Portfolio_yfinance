"""應用程式進入點。"""

import tkinter as tk

from app.config import APP_TITLE, WINDOW_SIZE
from app.db.database import Database
from app.ui.main_window import PortfolioApp


def main() -> None:
    """初始化資料庫並啟動 Tkinter GUI。"""
    database = Database()
    database.initialize()

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry(WINDOW_SIZE)
    root.minsize(1180, 720)

    PortfolioApp(root=root, database=database)
    root.mainloop()


if __name__ == '__main__':
    main()
