# 台股庫存、損益與配息管理（yfinance v1.2）

## v1.2 新增功能

### 1. 建立清冊前選擇商品種類

按下「① 選擇類型並建立商品清冊」後，可勾選：

- 上市公司股票
- 上櫃／興櫃公司股票（Yahoo `.TWO`）
- 上市 ETF／基金商品
- 上櫃 ETF／基金商品
- ETN／其他交易所商品
- 權證／衍生商品
- 其他無法分類商品

預設只勾選公司股票與 ETF，權證、ETN、其他商品預設關閉。

若勾選「清除舊商品清冊與行情後重建」：

- 清除舊 `instruments` 清冊資料
- 清除舊 `market_quotes` 行情快取
- 保留持股資料
- 保留既有股利／分割紀錄
- 為避免持股失去商品資料，既有持股對應的商品仍會保留

### 2. 即時下載進度與 LOG

新增「下載進度／LOG」分頁。執行以下工作時會自動切換過去：

- 建立商品清冊
- 補強繁中名稱
- 更新全部行情
- 更新持股行情
- 更新持股股利／分割
- 解析單一股票代號

LOG 會即時顯示時間、批次、目前進度、成功與失敗數量。

### 3. 繁體中文名稱四層補強

名稱優先順序：

1. `data/name_overrides.csv`
2. Yahoo 台灣批次繁中名稱
3. Yahoo 台灣逐檔搜尋
4. Yahoo 奇摩股市報價頁標題
5. 最後才保留 Yahoo 全球英文名稱或 symbol

已加入範例：

```csv
symbol,name
0050.TW,元大台灣50
0056.TW,元大高股息
00919.TW,群益台灣精選高息
4513.TWO,福裕
```

若仍有個別名稱缺漏，可直接編輯 `data/name_overrides.csv`，再重新建立清冊或重新解析代號。

### 4. 主視窗啟動置中

程式啟動後會依螢幕尺寸自動將視窗置中。

### 5. 已載入資料搜尋

「已載入資料」分頁新增搜尋框，可同時搜尋：

- Yahoo Symbol
- 股票代號
- 中文／英文名稱
- 市場分類
- 商品分類
- 行情日期
- 股利／分割日期與類型

輸入內容後會即時篩選商品清冊、行情及公司行動三個表格。

## 安裝或升級

```bash
cd /Users/whuang/Desktop/TW_Stock_Portfolio_yfinance

/opt/anaconda3/envs/shopee-auto/bin/python \
-m pip install --upgrade -r requirements.txt
```

啟動：

```bash
/opt/anaconda3/envs/shopee-auto/bin/python main.py
```

## 從 v1.1 升級並保留資料

舊資料庫位於：

```text
data/portfolio_yfinance.db
```

新版沒有內附資料庫。若採用全新資料夾：

1. 關閉舊程式。
2. 將舊版 `data/portfolio_yfinance.db` 複製到新版 `data/`。
3. 將舊版自行編輯過的 `data/name_overrides.csv` 一併複製。
4. 啟動新版；程式會自動新增 `product_category` 欄位。

## 建議操作順序

1. 按「① 選擇類型並建立商品清冊」。
2. 預設保留公司股票與 ETF，取消不需要的商品。
3. 查看「下載進度／LOG」。
4. 建立完成後，在「已載入資料」搜尋 `4513`，確認名稱為「福裕」。
5. 按「② 更新全部商品行情」。
6. 新增持股後按「更新持股股利／分割」。

## 資料限制

- yfinance／Yahoo Finance 不是台灣官方完整證券主檔。
- Yahoo 未收錄、新掛牌或部分興櫃商品可能查不到。
- `.TWO` 無法單靠 Yahoo 精準區分上櫃與興櫃。
- Yahoo 股利日期通常是除息日，不是實際入帳日。
- 完整補強繁中名稱需要逐檔查詢，建立清冊時間會較長，可在建立視窗取消勾選。
- 商品分類是依 Yahoo query 類型、quote type 與台灣代號格式做合理分類，特殊商品可能落入「其他」。

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
│   │   ├── dividend_service.py
│   │   ├── portfolio_service.py
│   │   └── sync_service.py
│   └── ui/
│       ├── main_window.py
│       └── universe_dialog.py
├── data/
│   ├── name_overrides.csv
│   └── portfolio_yfinance.db
├── exports/
└── tests/
```
