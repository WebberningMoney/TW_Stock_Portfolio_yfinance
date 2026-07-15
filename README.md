# 台股庫存、損益與配息管理 v1.6

本版延續 v1.5 的 yfinance＋Yahoo 台灣股利政策頁架構，新增鍵盤輸入流程、表格排序、動態圖例，以及不需要 API Key 的 AI 手動研究工作區。

## v1.6 新增與修正

### 1. 股利圖例動態欄數

- 預設使用一欄。
- 程式依圖表實際高度、圖例項目數量自動計算一至四欄。
- 最多顯示 30 檔持股圖例，超出的部分以彙總項目表示。
- 圖例欄數增加時，會自動替右側圖例保留更多空間。

### 2. 持股輸入鍵盤流程

建議操作：

```text
股票代號 Enter／Tab
→ 自動帶入股票名稱
→ 游標移到持有股數
→ 股數 Enter／Tab
→ 游標移到持有總成本
→ 總成本 Enter
→ 顯示確認視窗
→ 再按 Enter 完成儲存
→ 游標回到股票代號
```

補充：

- Yahoo Symbol 改為內部欄位，不再佔用輸入畫面。
- 優先從本機商品清冊解析代號，只有查無資料時才連線 Yahoo。
- 股票名稱設為唯讀，避免代號與名稱不一致。
- 確認視窗會顯示股數、總成本及平均成本。
- 已存在的 Yahoo Symbol 會顯示為「更新持股」，而不是新增。

### 3. 所有下方表格支援標頭排序

點擊任一欄位標頭可排序：

- 第一次：升冪
- 第二次：降冪
- 標題旁顯示 ▲／▼

排序支援：

- 金額
- 百分比
- 數字
- 日期
- 中文或英文文字

空白、未更新及未提供的資料固定放在最後。

### 4. 右側 AI 研究工作區（不需 API Key）

「庫存與損益」分頁右側新增兩個直幅區塊：

1. 持有個股新聞研究
2. 加倉／減倉／操作研究

使用方式：

1. 在左側庫存表選取一檔持股。
2. 程式自動整理代號、名稱、持股、成本、損益與股利資料，產生提示詞。
3. 按「複製提示詞」。
4. 按「開啟 ChatGPT」或「開啟 Gemini」。
5. 將提示詞貼入 AI 網頁。
6. 可將 AI 回覆複製後，按「貼上 AI 回覆」放回程式內閱讀。

這是手動模式，不會：

- 自動登入 ChatGPT 或 Gemini。
- 讀取你的聊天紀錄。
- 自動取得 AI 回覆。
- 自動執行交易。

若日後需要全自動新聞與分析，仍需串接 OpenAI API、Gemini API 或其他正式資料來源。

## VSCode Debug 圖示

使用 VSCode Debug 或直接執行 `python main.py` 時，macOS Dock 顯示的是 Python 解譯器圖示，通常無法只靠 Tkinter 穩定改成正式程式圖示。

正式方式是將程式打包成 macOS `.app`，並在 PyInstaller 使用 `.icns` 圖示。例如：

```bash
python -m pip install pyinstaller

pyinstaller \
  --windowed \
  --name "台股投資組合" \
  --icon assets/app_icon.icns \
  main.py
```

打包前仍需進一步調整正式版資料庫儲存位置及測試套件收集，因此不建議直接把目前開發資料夾視為已完成的發行包。

## 安裝

```bash
cd /Users/whuang/Desktop/TW_Stock_Portfolio_yfinance_v1.6

/opt/anaconda3/envs/shopee-auto/bin/python \
-m pip install --upgrade -r requirements.txt
```

啟動：

```bash
/opt/anaconda3/envs/shopee-auto/bin/python main.py
```

## 保留舊資料

若使用新的專案資料夾，請將舊版：

```text
舊版/data/portfolio_yfinance.db
```

複製到：

```text
TW_Stock_Portfolio_yfinance_v1.6/data/
```

v1.6 沒有新增資料庫欄位，不需要重建資料庫。

## 資料與 AI 限制

- 行情與歷史公司行動主要來自 yfinance。
- 已公告未發放股利使用 Yahoo 台灣股利政策頁補強。
- AI 手動研究內容的準確度取決於使用者貼入的模型、是否開啟網路搜尋，以及來源品質。
- 加倉或減倉內容僅供研究，程式不會自動執行交易。
