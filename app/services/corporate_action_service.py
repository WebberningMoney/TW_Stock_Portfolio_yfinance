"""重複 Corporate Action（股利／分割事件）的合併決策，不碰資料庫。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.models import CorporateAction

_SOURCE_PRIORITY = {
    'yahoo_tw_scraper': 20,
    'yfinance': 10,
}

_SOURCE_LABELS = {
    'yahoo_tw_scraper': '爬蟲／Yahoo 台灣股利政策',
    'yfinance': 'API／yfinance 歷史',
}

_FILLABLE_FIELDS = ('period', 'payment_date', 'announcement_status')


@dataclass(slots=True)
class ConsolidatedActionGroup:
    """一組重複 Corporate Action 合併後的結果。"""

    merged: CorporateAction
    replaced_indices: list[int]
    message: str


def consolidate_duplicate_actions(
    actions: list[CorporateAction],
) -> list[ConsolidatedActionGroup]:
    """找出重複的 Corporate Action，決定該合併保留成什麼。

    重複判斷欄位：除息／事件日、symbol、股票代號、股票名稱、數值，
    以及事件類型（避免股利與分割誤合併）。

    若同時有多個來源，保留欄位較完整的紀錄；完整度相同時，優先保留
    Yahoo 台灣股利政策頁。`actions` 須依原始寫入順序（例如資料庫 id
    遞增）排序；分數仍相同時，清單位置較後者視為較新，等同於原本比
    對 id 的 tie-break。只回傳真的有重複（同一組 ≥2 筆）的組別。
    """
    grouped: dict[tuple, list[int]] = {}
    for index, action in enumerate(actions):
        key = (
            action.action_date,
            action.symbol,
            action.stock_code,
            action.stock_name,
            round(float(action.value), 8),
            action.action_type,
        )
        grouped.setdefault(key, []).append(index)

    def score(index: int) -> tuple[int, int, int]:
        action = actions[index]
        detail_count = sum(
            bool(getattr(action, field)) for field in _FILLABLE_FIELDS
        )
        return (
            detail_count,
            _SOURCE_PRIORITY.get(action.source, 0),
            index,
        )

    results: list[ConsolidatedActionGroup] = []
    for indices in grouped.values():
        if len(indices) <= 1:
            continue

        primary_index = max(indices, key=score)
        primary = actions[primary_index]
        ordered = sorted(indices, key=score, reverse=True)

        fields = {}
        for field in _FILLABLE_FIELDS:
            value = getattr(primary, field)
            if not value:
                value = next(
                    (
                        getattr(actions[i], field)
                        for i in ordered
                        if getattr(actions[i], field)
                    ),
                    '',
                )
            fields[field] = value
        merged = replace(primary, **fields)

        source_list = '＋'.join(sorted({
            _SOURCE_LABELS.get(actions[i].source, actions[i].source)
            for i in indices
        }))
        kept_source = _SOURCE_LABELS.get(merged.source, merged.source)
        message = (
            f'整合重複資料：{merged.symbol} '
            f'{merged.action_date} '
            f'{merged.action_type} {merged.value:g}；'
            f'{source_list} 共 {len(indices)} 筆 → 保留 {kept_source}'
        )

        results.append(ConsolidatedActionGroup(
            merged=merged,
            replaced_indices=indices,
            message=message,
        ))

    return results
