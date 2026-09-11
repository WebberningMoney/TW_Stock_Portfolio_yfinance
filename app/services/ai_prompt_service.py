"""AI 研究提示詞產生邏輯，不依賴 Tkinter。"""

from __future__ import annotations

from datetime import date

from app.services.dividend_service import PENDING, REALIZED, DividendProjection
from app.services.portfolio_service import HoldingView
from app.utils import market_label


def build_news_prompt(view: HoldingView, today: date) -> str:
    today_text = today.isoformat()
    return (
        f'今天是 {today_text}。請使用網路搜尋，研究台灣證券 {view.stock_code} '
        f'{view.stock_name}（Yahoo Symbol：{view.symbol}）最近 30 天的重要新聞。\n\n'
        '請依序整理：\n'
        '1. 最新營收、財報、法說、接單、產業與重大訊息。\n'
        '2. 可能影響股價或股利能力的正面與負面因素。\n'
        '3. 每則資訊標示日期、來源與可開啟的引用。\n'
        '4. 明確區分已確認事實、媒體推測與你的推論。\n'
        '5. 最後列出未來 30～90 天值得追蹤的事件。\n\n'
        f'目前持有：{view.shares:,} 股；平均成本 NT$ {view.average_cost:,.2f}；'
        f'最近收盤 NT$ {view.close:,.2f}；未實現報酬率 {view.return_rate:,.2f}%。'
    )


def build_analysis_prompt(
    view: HoldingView,
    dividend_projections: list[DividendProjection],
) -> str:
    selected_dividends = [
        item for item in dividend_projections
        if item.symbol == view.symbol
    ]
    realized = sum(
        item.estimated_amount for item in selected_dividends
        if item.status == REALIZED
    )
    pending = sum(
        item.estimated_amount for item in selected_dividends
        if item.status == PENDING
    )
    return (
        '請以台股投資研究員角度，根據下列持股資料及最新可查證資訊，'
        '評估加倉、續抱、減倉或等待的條件。請勿只給單一結論，並避免保證報酬。\n\n'
        f'標的：{view.stock_code} {view.stock_name}（{view.symbol}）\n'
        f'市場：{market_label(view.market_segment)}\n'
        f'持有股數：{view.shares:,} 股\n'
        f'總成本：NT$ {view.total_cost:,.0f}\n'
        f'平均成本：NT$ {view.average_cost:,.2f}\n'
        f'最近收盤：NT$ {view.close:,.2f}\n'
        f'庫存市值：NT$ {view.market_value:,.0f}\n'
        f'未實現損益：NT$ {view.profit:,.0f}（{view.return_rate:,.2f}%）\n'
        f'目前分析年度股利：已實現約 NT$ {realized:,.0f}；未領／預估約 NT$ {pending:,.0f}。\n\n'
        '請輸出：\n'
        '1. 基本面、產業面、籌碼／估值與股利持續性的重點。\n'
        '2. 加倉、續抱、減倉三種情境各自的觸發條件。\n'
        '3. 需要避免加碼的風險訊號。\n'
        '4. 以小幅／中幅／大幅調整持股比例的方式說明，不要直接替我下單。\n'
        '5. 所有最新事實附日期與來源，並清楚標示推論。'
    )
