"""執行階段參數與來源模式的離線測試。"""

from app.settings import RuntimeSettings


def test_runtime_settings_apply_safe_bounds() -> None:
    settings = RuntimeSettings(
        dividend_source_mode='invalid',
        quote_batch_size=999,
        download_threads=0,
        item_retries=99,
        retry_backoff_seconds=-1,
        scraper_delay_seconds=-5,
        scraper_timeout_seconds=1,
        screener_page_size=999,
        screener_max_pages=0,
    ).normalized()

    assert settings.dividend_source_mode == 'BOTH'
    assert settings.quote_batch_size == 200
    assert settings.download_threads == 1
    assert settings.item_retries == 8
    assert settings.retry_backoff_seconds == 0
    assert settings.scraper_delay_seconds == 0
    assert settings.scraper_timeout_seconds == 5
    assert settings.screener_page_size == 250
    assert settings.screener_max_pages == 1
