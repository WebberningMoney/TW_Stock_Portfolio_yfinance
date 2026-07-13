# 台股庫存、損益與配息管理（yfinance v1.3）

Python Tkinter 桌面程式，使用 yfinance / Yahoo Finance 作為商品清冊、行情、歷史現金股利及股票分割資料核心。

## v1.3 新增功能

### 1. 年度股利分成已實現、未領及年度總和

在「每月配息估算」分頁輸入西元年度後，程式會顯示：

- **已實現股利（估算）**：該年度 Yahoo 除息日已經到達的股利事件。
- **未領／預估股利**：除息日尚未到達的事件，或依最近歷史年度模式推估的未來股利。
- **當年度股利總和**：已實現加未領／預估。

重要限制：

- yfinance 的股利日期通常是除息日，不是實際入帳日。
- 程式目前只有「現在持有股數」，沒有逐筆買賣歷史。
- 金額均以現在持有股數乘以每股股利估算，不代表券商帳戶實際已入帳金額。
- 過去年度只顯示 Yahoo 實際存在的事件，不會用歷史模式補足缺漏月份。
- 本年度只估算今天之後的缺漏月份；未來年度以最近有股利的年度作為模板。

### 2. 每月彩色股利長條圖

新增 1 月至 12 月的堆疊長條圖：

- 每一種顏色代表一檔持有股票或 ETF。
- 實心區塊代表已實現股利。
- 半透明斜線區塊代表未領／歷史模式估算。
- 每根長條上方顯示該月份總金額。
- 圖例顯示持股代號與名稱。

### 3. 月份股利組成

- 滑鼠移到某個月份長條，可查看該月已實現、未領、總額及主要成分。
- 點擊某個月份長條，會切換到「選定月份組成」表。
- 表格會列出該月由哪些股票或 ETF 組成、持有股數、每股股利、預估金額與估算依據。
- 若持股很多，圖例只顯示年度股利金額最高的前 12 檔；完整內容仍可在月份組成表查看。

### 4. 庫存與損益顏色

依台股慣例：

- 正報酬／上漲：紅色。
- 負報酬／下跌：綠色。
- 無變化：灰色。

顏色套用於：

- 庫存與損益明細。
- 投資組合總損益及報酬率。
- 已載入行情的漲跌資料。

### 5. 市場名稱中文化

介面不再直接顯示內部代碼，改為：

| 內部代碼 | 中文顯示 |
|---|---|
| AUTO | 自動判斷 |
| TWSE | 上市／上市 ETF（.TW） |
| TPEX | 上櫃／上櫃 ETF（.TWO） |
| EMERGING | 興櫃（通常為 .TWO） |

資料庫仍保留英文內部代碼，避免影響既有資料與程式邏輯。

### 6. GUI 配色

- 藍灰色主題與卡片式摘要。
- 主要操作按鈕使用藍色強調。
- 股利已實現、未領及年度總和使用不同顏色。
- LOG 分頁改為深色閱讀區。
- Matplotlib 會優先使用 macOS `PingFang TC`、Windows `Microsoft JhengHei` 等系統繁中文字型。

## 延續 v1.2 功能

- 建立清冊前選擇上市股票、上櫃／興櫃股票、ETF、ETN、權證等商品類型。
- 預設不下載權證及其他不需要的衍生商品。
- 即時下載進度與 LOG 分頁。
- Yahoo 台灣繁中名稱補強與 `data/name_overrides.csv` 手動覆寫。
- 視窗啟動時置中，並依螢幕尺寸避免超出可見區域。
- 已載入商品、行情與股利／分割資料搜尋。
- CSV 匯出。

## 安裝或升級套件

進入解壓縮後的專案資料夾：

```bash
cd /Users/whuang/Desktop/TW_Stock_Portfolio_yfinance
```

使用目前的 Conda Python 安裝：

```bash
/opt/anaconda3/envs/shopee-auto/bin/python \
-m pip install --upgrade -r requirements.txt
```

v1.3 新增 `matplotlib`，完整 requirements 包含：

- yfinance
- pandas
- scipy
- requests
- matplotlib

啟動：

```bash
/opt/anaconda3/envs/shopee-auto/bin/python main.py
```

## 從 v1.2 升級並保留資料

資料庫位於：

```text
data/portfolio_yfinance.db
```

本 ZIP 不含資料庫。若使用全新資料夾：

1. 關閉舊程式。
2. 將舊版 `data/portfolio_yfinance.db` 複製到新版 `data/`。
3. 將自行修改過的 `data/name_overrides.csv` 一併複製。
4. 安裝新版 requirements。
5. 執行 `main.py`。

v1.3 不需要新增資料表或刪除舊資料庫。

## 建議操作順序

1. 選擇類型並建立商品清冊。
2. 更新全部商品行情，或只更新持股行情。
3. 新增或更新持股股數與總成本。
4. 更新持股股利／分割。
5. 進入「每月配息估算」。
6. 輸入分析年度並按「重新計算」。
7. 利用長條圖及月份組成表，找出股利較弱的月份與適合增加持有比例的商品。

## 資料限制

- yfinance／Yahoo Finance 不是台灣官方完整證券主檔。
- Yahoo 未收錄、新掛牌或部分興櫃商品可能查不到。
- `.TWO` 無法單靠 Yahoo 精準區分上櫃與興櫃。
- Yahoo 歷史股利資料可能缺漏或延遲。
- 股利日期通常是除息日，而不是實際發放或入帳日。
- 要精準計算真正已領股利，未來需增加交易明細、除息基準日持股數及實際入帳紀錄。

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

## 離線測試

```bash
/opt/anaconda3/envs/shopee-auto/bin/python \
-m unittest discover -s tests -v
```
