"""consolidate_duplicate_actions 的合併決策測試：純函式，不碰資料庫。"""

from app.models import CorporateAction
from app.services.corporate_action_service import consolidate_duplicate_actions


def _action(
    symbol='0056.TW',
    stock_code='0056',
    stock_name='元大高股息',
    action_date='2026-07-21',
    action_type='DIVIDEND',
    value=1.35,
    source='yfinance',
    period='',
    payment_date='',
    announcement_status='',
):
    return CorporateAction(
        symbol=symbol,
        stock_code=stock_code,
        stock_name=stock_name,
        action_date=action_date,
        action_type=action_type,
        value=value,
        source=source,
        period=period,
        payment_date=payment_date,
        announcement_status=announcement_status,
    )


def test_non_duplicate_actions_are_not_returned():
    actions = [
        _action(action_date='2026-07-21', value=1.35),
        _action(action_date='2026-10-21', value=1.40),
    ]

    groups = consolidate_duplicate_actions(actions)

    assert groups == []


def test_more_complete_record_wins_even_if_source_priority_is_lower():
    actions = [
        _action(source='yahoo_tw_scraper', period='', payment_date='', announcement_status=''),
        _action(
            source='yfinance',
            period='2026Q2',
            payment_date='2026-08-10',
            announcement_status='ANNOUNCED',
        ),
    ]

    groups = consolidate_duplicate_actions(actions)

    assert len(groups) == 1
    assert groups[0].merged.source == 'yfinance'
    assert groups[0].merged.period == '2026Q2'


def test_source_breaks_tie_when_completeness_is_equal():
    actions = [
        _action(source='yfinance', period='', payment_date='', announcement_status=''),
        _action(source='yahoo_tw_scraper', period='', payment_date='', announcement_status=''),
    ]

    groups = consolidate_duplicate_actions(actions)

    assert len(groups) == 1
    assert groups[0].merged.source == 'yahoo_tw_scraper'


def test_later_index_breaks_tie_when_completeness_and_source_are_equal():
    actions = [
        _action(source='yfinance', period='2026Q2'),
        _action(source='yfinance', period='2026Q2'),
    ]

    groups = consolidate_duplicate_actions(actions)

    assert len(groups) == 1
    assert groups[0].replaced_indices == [0, 1]


def test_missing_fields_are_backfilled_from_other_duplicate():
    actions = [
        _action(
            source='yahoo_tw_scraper',
            period='',
            payment_date='2026-08-10',
            announcement_status='',
        ),
        _action(
            source='yfinance',
            period='2026Q2',
            payment_date='',
            announcement_status='',
        ),
    ]

    groups = consolidate_duplicate_actions(actions)

    assert len(groups) == 1
    merged = groups[0].merged
    assert merged.source == 'yahoo_tw_scraper'
    assert merged.period == '2026Q2'
    assert merged.payment_date == '2026-08-10'


def test_message_format_matches_existing_log_text():
    actions = [
        _action(source='yfinance'),
        _action(source='yahoo_tw_scraper'),
    ]

    groups = consolidate_duplicate_actions(actions)

    assert groups[0].message == (
        '整合重複資料：0056.TW 2026-07-21 DIVIDEND 1.35；'
        'API／yfinance 歷史＋爬蟲／Yahoo 台灣股利政策 共 2 筆 → '
        '保留 爬蟲／Yahoo 台灣股利政策'
    )


def test_dividend_and_split_with_same_date_and_value_are_not_merged():
    actions = [
        _action(action_type='DIVIDEND', value=1.0),
        _action(action_type='SPLIT', value=1.0),
    ]

    groups = consolidate_duplicate_actions(actions)

    assert groups == []


def test_replaced_indices_track_original_list_positions():
    actions = [
        _action(action_date='2026-01-01', value=1.0, source='yfinance'),
        _action(action_date='2026-07-21', value=1.35, source='yfinance'),
        _action(action_date='2026-07-21', value=1.35, source='yahoo_tw_scraper'),
    ]

    groups = consolidate_duplicate_actions(actions)

    assert len(groups) == 1
    assert groups[0].replaced_indices == [1, 2]
