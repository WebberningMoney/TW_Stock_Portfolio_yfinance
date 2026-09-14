# 台股資產與股息管理 v2.4

以 yfinance 歷史資料、Yahoo 台灣股利政策爬蟲與 SQLite 組成的台股持股、損益及配息管理工具。

## v2.4：macOS App 版本

本版將使用者可見名稱統一為：

```text
台股資產與股息管理
```

以下位置使用相同名稱：

- macOS `.app` 名稱
- Finder、Spotlight 與 Dock 顯示名稱
- Tkinter 視窗標題
- 畫面上方產品標題
- 狀態列版本文字

另外加入：

- PyInstaller macOS App Bundle 設定
- 雙擊式 `build_macos_app.command`
- 自訂 App 圖示
- 打包後專用的 Application Support、Caches、Logs 與匯出路徑
- 第一次建立 App 時沿用現有持股資料
- 啟動失敗時寫入檔案 LOG 並顯示錯誤位置

## 取得專案

沒有用過 GitHub 也沒關係，不需要安裝任何工具：

1. 用瀏覽器開啟本專案的 GitHub 頁面。
2. 頁面右上方有一個綠色的 **Code** 按鈕，點下去。
3. 選單裡點 **Download ZIP**，瀏覽器會下載一個 `.zip` 檔（通常在「下載」資料夾）。
4. 在 Finder 裡雙擊這個 `.zip` 檔，macOS 會自動解壓縮成一個資料夾。

接著繼續下面「直接建立 macOS App」的步驟。

## 直接建立 macOS App

在剛剛解壓縮出來的資料夾裡，雙擊：

```text
build_macos_app.command
```

建立完成後，App 會安裝至：

```text
~/Applications/台股資產與股息管理.app
```

之後直接雙擊 App 即可執行，不需要 VSCode 或 Terminal。

詳細說明見 [BUILD_MACOS.md](BUILD_MACOS.md)。

## 打包後的資料位置

```text
資料庫與設定：~/Library/Application Support/台股資產與股息管理/
快取：        ~/Library/Caches/台股資產與股息管理/
錯誤 LOG：    ~/Library/Logs/台股資產與股息管理/app.log
CSV 匯出：    ~/Documents/台股資產與股息管理匯出/
```

這樣更新或替換 `.app` 時，不會把持股資料一起刪除。

## 原始碼模式

仍可用原本方式執行：

```bash
cd /Users/whuang/Desktop/TW_Stock_Portfolio_yfinance
/opt/anaconda3/envs/shopee-auto/bin/python -m pip install --upgrade -r requirements.txt
/opt/anaconda3/envs/shopee-auto/bin/python main.py
```

原始碼模式會繼續使用專案內的 `data/` 與 `exports/`。

## 主要功能

- 建立可篩選商品類型的 Yahoo 台灣商品清冊
- 更新持股或全部商品行情
- 持股庫存市值、未實現損益與報酬率
- yfinance 歷史股利／股票分割
- Yahoo 台灣已公告股利政策爬蟲
- 年度、季度與每月股利分析
- 年配、半年配、季配與月配歷史模式估算
- API／爬蟲來源切換及單筆測試
- 進度、重試及白話中文 LOG
- 商品、行情及股利資料搜尋與 CSV 匯出

## 資料限制

- yfinance 與 Yahoo 台灣網頁都不是交易所正式結算資料。
- Yahoo 台灣爬蟲可能因網頁結構改版需要調整。
- 「已實現」依現金發放日或除息日估算，不等同券商實際入帳紀錄。
- 配息預估使用歷史政策，實際金額仍以正式公告為準。
