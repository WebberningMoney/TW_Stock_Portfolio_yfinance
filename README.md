# 台股庫存、損益與配息管理 v2.0 Refactor

v2.0 以 v1.6 已完成的功能為基礎，重點是架構重整與 UI/UX 進化，沒有移除既有功能。

## 架構重整

原本 `app/ui/main_window.py` 超過 2,400 行；v2.0 將功能拆至：

```text
app/ui/
├── main_window.py                 # 狀態初始化、跨頁協調、全域快捷鍵
├── universe_dialog.py
└── mixins/
    ├── base.py                    # 主題與字型
    ├── layout.py                  # 頁首、輸入區、摘要、Notebook、共用表格
    ├── holdings.py                # 持股輸入、解析、儲存、庫存損益
    ├── dividend_page.py           # 年度股利、圖表、月份組成
    ├── loaded_data_page.py        # 已載入資料、搜尋、匯出
    ├── operations.py              # 背景下載、進度、LOG、錯誤處理
    └── ai_workspace.py            # 新聞與操作研究提示工作區
```

API、爬蟲、SQLite、股利計算與同步服務維持原本分層。

## UI/UX 改進

- 響應式視窗：依螢幕 92% 寬、88% 高自動置中。
- 新增產品頁首與快捷鍵提示。
- 狀態列固定顯示目前狀態及資料用途提醒。
- `⌘/Ctrl + L` 聚焦股票代號。
- `⌘/Ctrl + S` 確認儲存持股。
- `⌘/Ctrl + K` 切換至已載入資料搜尋。
- `Esc` 清空輸入並回到股票代號。
- 庫存列雙擊後直接聚焦持有股數，方便快速修改。
- 保留 v1.6 的 Enter／Tab 連續輸入、表格標頭排序、動態圖例及 AI 手動研究工作區。

## 安裝

```bash
/opt/anaconda3/envs/shopee-auto/bin/python -m pip install --upgrade -r requirements.txt
/opt/anaconda3/envs/shopee-auto/bin/python main.py
```

## 從 v1.6 升級

將舊版資料庫複製至：

```text
data/portfolio_yfinance.db
```

也可複製自訂名稱：

```text
data/name_overrides.csv
```

v2.0 沒有破壞性資料庫 Schema 變更。

## 資料來源與限制

- 歷史行情、股利與股票分割：yfinance。
- 已公告但尚未發放股利：Yahoo 台灣股利政策頁爬蟲。
- 網頁結構可能變更；資料僅供個人研究，不構成投資建議。
