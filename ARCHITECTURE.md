# v2.3 Architecture

## UI 模組

```text
app/ui/
├── main_window.py
├── universe_dialog.py
└── mixins/
    ├── base.py              # 顏色、字型、Treeview 樣式
    ├── layout.py            # 主畫面、同步工具列、分頁與共用表格
    ├── holdings.py          # 持股輸入、查詢、儲存與損益表
    ├── dividend_page.py     # 年／季／月股利摘要、圖表與明細
    ├── loaded_data_page.py  # 已載入資料、搜尋與匯出
    ├── operations.py        # 背景工作、進度條與白話 LOG
    ├── settings_page.py     # 抓取參數與單筆測試
    └── ai_workspace.py      # AI 研究提示詞工作區
```

## 股利資料流程

```text
持股清單
  ├─ yfinance：歷史股利／股票分割
  ├─ Yahoo 台灣爬蟲：所屬期間、除息日、現金發放日、未來公告
  └─ SQLite 去重整合
        ↓
年度實際／公告事件
        ↓
推測配息頻率（月／季／半年／年）
        ↓
只補足尚未公告的未來期次
        ↓
月份、季度、年度摘要與堆疊圖
```

## v2.3 原則

1. 真實歷史與公告資料永遠優先於預估。
2. 同一除息事件只計算一次，保留欄位較完整來源。
3. 月配／季配以最近一期政策延伸，不再只套用去年同月份。
4. 過去日期沒有公告時不硬補估，降低虛構現金流。
5. LOG 要能讓非工程背景使用者知道目前進度、失敗代號及下一步。
