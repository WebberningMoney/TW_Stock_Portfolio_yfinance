# v2.1 Architecture

```text
app/
├── api/
│   ├── yfinance_client.py              # 商品清冊、行情、歷史股利／分割
│   └── yahoo_tw_dividend_scraper.py    # Yahoo 台灣已公告股利政策
├── db/
│   └── database.py                     # SQLite 與跨來源去重
├── services/
│   ├── sync_service.py                 # 來源選擇、同步、單筆診斷
│   ├── dividend_service.py
│   └── portfolio_service.py
├── ui/
│   ├── main_window.py
│   └── mixins/
│       ├── base.py
│       ├── layout.py
│       ├── holdings.py
│       ├── dividend_page.py
│       ├── loaded_data_page.py
│       ├── operations.py
│       ├── settings_page.py            # v2.1 新增
│       └── ai_workspace.py
├── settings.py                         # 執行階段參數與 JSON 保存
├── config.py
├── models.py
└── utils.py
```

## v2.1 原則

- 來源選擇只控制本次同步，不清除未選來源既有資料。
- 設定物件由 GUI、SyncService、YFinanceClient 與 Scraper 共用。
- 儲存設定後立即更新現有 Client，不必重啟程式。
- 單筆測試不寫入市場行情或公司行動資料。
- 配息頁採水平 PanedWindow，讓圖表與明細可各自獲得完整高度。
