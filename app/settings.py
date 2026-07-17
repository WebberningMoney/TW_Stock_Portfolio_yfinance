"""執行階段抓取參數與本機設定保存。

設定與程式碼分離，讓一般使用者可在 GUI 調整批次大小、重試、間隔等參數，
同時保留合理邊界，避免誤設造成 Yahoo 限流或下載過慢。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path
from typing import Any

from app.config import SETTINGS_PATH


@dataclass(slots=True)
class RuntimeSettings:
    """可由 GUI 調整的抓取參數。"""

    # 預設股利更新來源
    dividend_source_mode: str = 'BOTH'

    # 行情下載
    quote_batch_size: int = 50
    quote_period: str = '1mo'
    quote_interval: str = '1d'
    download_threads: int = 8
    yfinance_timeout_seconds: int = 15
    quote_batch_delay_seconds: float = 0.20
    enable_price_repair: bool = True

    # 歷史股利／分割
    action_period: str = 'max'
    action_item_delay_seconds: float = 0.20

    # 通用容錯
    item_retries: int = 3
    retry_backoff_seconds: float = 1.0

    # Yahoo 台灣股利頁爬蟲
    scraper_delay_seconds: float = 0.50
    scraper_timeout_seconds: int = 25

    # 商品清冊
    screener_page_size: int = 250
    screener_max_pages: int = 30

    def normalized(self) -> 'RuntimeSettings':
        """回傳套用安全邊界後的設定副本。"""
        source_mode = str(self.dividend_source_mode or 'BOTH').upper()
        if source_mode not in {'BOTH', 'YFINANCE', 'SCRAPER'}:
            source_mode = 'BOTH'
        return RuntimeSettings(
            dividend_source_mode=source_mode,
            quote_batch_size=min(max(int(self.quote_batch_size), 1), 200),
            quote_period=str(self.quote_period or '1mo'),
            quote_interval=str(self.quote_interval or '1d'),
            download_threads=min(max(int(self.download_threads), 1), 16),
            yfinance_timeout_seconds=min(
                max(int(self.yfinance_timeout_seconds), 5), 120
            ),
            quote_batch_delay_seconds=min(
                max(float(self.quote_batch_delay_seconds), 0.0), 10.0
            ),
            enable_price_repair=bool(self.enable_price_repair),
            action_period=str(self.action_period or 'max'),
            action_item_delay_seconds=min(
                max(float(self.action_item_delay_seconds), 0.0), 10.0
            ),
            item_retries=min(max(int(self.item_retries), 1), 8),
            retry_backoff_seconds=min(
                max(float(self.retry_backoff_seconds), 0.0), 30.0
            ),
            scraper_delay_seconds=min(
                max(float(self.scraper_delay_seconds), 0.0), 10.0
            ),
            scraper_timeout_seconds=min(
                max(int(self.scraper_timeout_seconds), 5), 120
            ),
            screener_page_size=min(
                max(int(self.screener_page_size), 25), 250
            ),
            screener_max_pages=min(
                max(int(self.screener_max_pages), 1), 100
            ),
        )


class SettingsStore:
    """以 JSON 保存執行階段設定。"""

    def __init__(self, path: Path = SETTINGS_PATH) -> None:
        self.path = path

    def load(self) -> RuntimeSettings:
        defaults = RuntimeSettings()
        if not self.path.exists():
            return defaults

        try:
            payload = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError, TypeError):
            return defaults

        if not isinstance(payload, dict):
            return defaults

        valid_names = {field.name for field in fields(RuntimeSettings)}
        values: dict[str, Any] = {
            key: value for key, value in payload.items() if key in valid_names
        }
        try:
            return RuntimeSettings(**values).normalized()
        except (TypeError, ValueError):
            return defaults

    def save(self, settings: RuntimeSettings) -> RuntimeSettings:
        normalized = settings.normalized()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(
            json.dumps(asdict(normalized), ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        temporary.replace(self.path)
        return normalized

    def reset(self) -> RuntimeSettings:
        settings = RuntimeSettings()
        return self.save(settings)
