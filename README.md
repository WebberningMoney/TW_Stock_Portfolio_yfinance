# 台股庫存、損益與配息管理（yfinance 核心版）

## 這個版本改了什麼

所有網路資料抓取已改成 `yfinance`：

- Yahoo Screener：探索 Yahoo 可列舉的台灣上市、上櫃股票與 ETF。
- Yahoo Search／Ticker：解析單一台灣股票代號。
- `yf.download()`：批次下載最近行情。
- `Ticker.history(actions=True)`：下載完整可用歷史現金股利及股票分割資料。
- 不再呼叫 TWSE 或 TPEx OpenAPI。

## 重要限制

1. **yfinance 不是官方台灣證券主檔。** 它能查詢 Yahoo 已收錄的 symbol，但無法保證涵蓋每一檔新上市、新上櫃或興櫃商品。
2. Yahoo 使用 `.TW` 表示上市市場、`.TWO` 表示 Taipei Exchange。Yahoo 的欄位通常無法精準區分上櫃與興櫃，因此興櫃可在新增持股時手動選 `EMERGING`。
3. Yahoo 股利事件日期通常是除息日，不是股利實際入帳日。
4. `Stock Splits` 可能包含股票分割、面額調整或部分股票股利效果，不能直接當作台灣官方配股公告。
5. 全市場行情可批次更新；公司行動只對持股逐檔同步，避免數千次請求造成 Yahoo 限流。
6. 每月未來配息採最近歷史年度的月份及金額模式估算，畫面會明確標示，不代表已公告。

## 安裝（你目前的 Conda 環境）

```bash
cd /Users/whuang/Desktop/TW_Stock_Portfolio_yfinance

/opt/anaconda3/envs/shopee-auto/bin/python -m pip install -r requirements.txt
/opt/anaconda3/envs/shopee-auto/bin/python main.py
```

確認版本：

```bash
/opt/anaconda3/envs/shopee-auto/bin/python -c "import yfinance; print(yfinance.__version__)"
```

## 建議操作順序

1. 按「建立 Yahoo 台灣商品清冊」。
2. 按「更新全部商品行情」。
3. 輸入代號，例如 `0050`、`00919`、`2330` 或 `6488`，按「解析代號」。
4. 輸入股數與總成本並儲存。
5. 按「更新持股股利／分割」。
6. 在「每月配息估算」查看已發生及歷史模式預估。
7. 在「已載入資料」查看及匯出商品清冊、行情、公司行動 CSV。

## 專案結構

```text
TW_Stock_Portfolio_yfinance/
├── main.py
├── requirements.txt
├── README.md
├── app/
│   ├── config.py
│   ├── models.py
│   ├── utils.py
│   ├── api/
│   │   └── yfinance_client.py
│   ├── db/
│   │   └── database.py
│   ├── services/
│   │   ├── portfolio_service.py
│   │   ├── dividend_service.py
│   │   └── sync_service.py
│   └── ui/
│       └── main_window.py
├── data/
│   └── portfolio_yfinance.db   # 第一次執行自動建立
├── exports/                    # 匯出 CSV 時自動建立
└── tests/
    └── test_services.py
```
