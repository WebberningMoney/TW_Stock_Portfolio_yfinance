# 台股庫存、損益與配息管理（yfinance v1.1）

## v1.1 修正內容

### 1. 繁體中文商品名稱

Yahoo Screener 的全球資料通常回傳英文 `longName`／`shortName`。新版建立清冊後會再透過 yfinance 的 Yahoo 傳輸層，批次要求 `zh-TW`、`region=TW` 的本地化名稱。名稱採以下優先序：

1. `data/name_overrides.csv` 手動覆寫。
2. Yahoo 台灣繁中名稱。
3. Yahoo 全球英文名稱。

若個別商品仍顯示英文，可編輯：

```text
data/name_overrides.csv
```

格式：

```csv
symbol,name
0050.TW,元大台灣50
0056.TW,元大高股息
00919.TW,群益台灣精選高息
```

存檔後再按一次「建立 Yahoo 台灣商品清冊／繁中名稱」。既有持股、行情及公司行動名稱也會同步更新。持股輸入區的股票名稱現在也可直接修改。

### 2. SciPy／repair 整批下載失敗

`yfinance` 的 `repair=True` 價格修復功能需要 SciPy。舊版 requirements 沒有安裝 SciPy，因此可能出現：

```text
ModuleNotFoundError: No module named 'scipy'
```

新版做了雙重修正：

- `requirements.txt` 已加入 SciPy。
- 程式啟動時會自動檢查 SciPy；若缺少，自動以 `repair=False` 下載，不再讓整批行情失敗。
- 全市場批次由 100 檔降為 50 檔，降低 Yahoo 限流及整批錯誤風險。

## 安裝或升級套件

```bash
cd /Users/whuang/Desktop/TW_Stock_Portfolio_yfinance

/opt/anaconda3/envs/shopee-auto/bin/python -m pip install --upgrade -r requirements.txt
```

若只想修正現有舊版的 SciPy 錯誤：

```bash
/opt/anaconda3/envs/shopee-auto/bin/python -m pip install --upgrade scipy
```

啟動：

```bash
/opt/anaconda3/envs/shopee-auto/bin/python main.py
```

## 建議操作順序

1. 按「建立 Yahoo 台灣商品清冊／繁中名稱」。
2. 確認「已載入資料 → 商品清冊」名稱。
3. 按「更新全部商品行情」。
4. 輸入代號並按「解析代號」。
5. 儲存持股。
6. 按「更新持股股利／分割」。

## 資料限制

- yfinance／Yahoo Finance 不是台灣官方證券主檔。Yahoo 沒有收錄的商品仍無法取得。
- Yahoo 的繁中名稱並非每檔都有，因此保留 `name_overrides.csv`。
- `.TWO` 不能可靠區分上櫃與興櫃。
- Yahoo 股利事件日期通常為除息日，不是實際入帳日。
- 即使安裝 SciPy，Yahoo 不存在、下市、代號錯誤或暫時限流的商品仍可能失敗；GUI 會以失敗檔數呈現，不會中止其他商品。

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
│   ├── api/yfinance_client.py
│   ├── db/database.py
│   ├── services/
│   └── ui/main_window.py
├── data/
│   ├── name_overrides.csv
│   └── portfolio_yfinance.db
├── exports/
└── tests/
```
