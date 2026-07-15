# v2.0 架構說明

## UI 協調原則

`PortfolioApp` 只建立共享狀態與協調頁面。功能以 mixin 分拆，降低單檔修改衝突。

## 依賴方向

```text
UI mixins → services → api/db
```

UI 不直接解析 Yahoo HTML；API 層不直接操作 Tkinter；計算服務不依賴 GUI。

## 後續擴充建議

- AI API 自動化可新增 `app/api/ai_client.py` 與 `app/services/research_service.py`。
- 新聞頁可新增獨立 `news_page.py`，不必再修改主視窗。
- 若未來 mixin 仍過大，可進一步改為 Frame component composition。
