# v2.2 Architecture

```text
app/
├── api/
│   ├── yfinance_client.py              # 商品清冊、行情、批次股利／分割
│   └── yahoo_tw_dividend_scraper.py    # Yahoo 台灣股利政策與發放日期
├── db/database.py                      # SQLite、來源清除重建、去重
├── services/
│   ├── sync_service.py                 # 來源選擇、批次並行、清除後重建
│   ├── portfolio_service.py
│   └── dividend_service.py
├── settings.py                         # 分流程參數與安全邊界
└── ui/
    ├── main_window.py
    └── mixins/
        ├── layout.py                   # 緊湊輸入、持股搜尋、可收合 AI 區
        ├── settings_page.py            # 分組參數與單筆測試
        ├── operations.py               # 背景工作與重建確認
        └── ...
```

## v2.2 原則

- 股利同步以「清除選定來源 → 依範圍重建 → 跨來源去重」為單一流程。
- yfinance 歷史資料採批次下載；Yahoo 台灣爬蟲採受控的小型執行緒池。
- 下載範圍同時約束 API 與爬蟲資料。
- UI 參數名稱直接描述影響的資料流程。
