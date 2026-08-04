# 建立 macOS App

應用程式統一名稱：**台股資產與股息管理**

## 最簡單方式

1. 在 Finder 解壓縮本專案。
2. 雙擊 `build_macos_app.command`。
3. 等待套件安裝與打包完成。
4. 建立完成後會自動安裝並開啟：

```text
~/Applications/台股資產與股息管理.app
```

之後可由 Finder、Spotlight 或 Launchpad 雙擊啟動，不需要再開 Terminal。

## 使用的 Python

建立工具依序尋找：

1. 環境變數 `PYTHON_BIN`
2. `/opt/anaconda3/envs/shopee-auto/bin/python`
3. 系統可找到的 `python3`

指定其他 Python：

```bash
PYTHON_BIN="/你的/python/路徑" ./build_macos_app.command
```

## 使用者資料位置

App 不會把可變資料寫進 `.app`。資料分別保存於：

```text
~/Library/Application Support/台股資產與股息管理/
~/Library/Caches/台股資產與股息管理/
~/Library/Logs/台股資產與股息管理/app.log
~/Documents/台股資產與股息管理匯出/
```

第一次建立 App 時，工具會在目的地尚無資料的前提下，自動沿用專案 `data/` 中的：

```text
portfolio_yfinance.db
app_settings.json
name_overrides.csv
```

## 更新 App

取得新版專案後，再次雙擊 `build_macos_app.command`。程式本體會更新，Application Support 中的持股與設定不會被刪除。

## 簽章說明

建立工具會套用本機 ad-hoc 簽章，適合自己的 Mac 使用。若要把 App 公開提供其他使用者下載，仍需 Apple Developer ID 簽章及 Apple 公證。
