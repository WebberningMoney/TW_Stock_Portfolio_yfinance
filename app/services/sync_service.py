"""協調 yfinance、SQLite 與 GUI 的同步流程。"""

from collections.abc import Callable

from app.api.yfinance_client import YFinanceClient
from app.db.database import Database
from app.models import Instrument

ProgressCallback = Callable[[str, int | None, int | None], None]


class SyncService:
    def __init__(
        self,
        database: Database,
        client: YFinanceClient | None = None,
    ) -> None:
        self.database = database
        self.client = client or YFinanceClient()

    def discover_universe(
        self,
        selected_categories: set[str],
        enrich_names: bool,
        rebuild: bool,
        progress: ProgressCallback | None = None,
    ) -> int:
        instruments = self.client.discover_taiwan_universe(
            selected_categories=selected_categories,
            enrich_names=enrich_names,
            progress=progress,
        )

        if rebuild:
            if progress:
                progress('清除舊商品清冊與行情快取後重建……', None, None)
            self.database.replace_universe(
                instruments,
                preserve_holding_instruments=True,
            )
        else:
            self.database.upsert_instruments(instruments)

        self.database.add_sync_log(
            'UNIVERSE',
            'SUCCESS',
            f'categories={sorted(selected_categories)}, '
            f'count={len(instruments)}, rebuild={rebuild}',
        )
        return len(instruments)

    def resolve_and_save_instrument(
        self,
        stock_code: str,
        market_segment: str,
    ) -> Instrument:
        instrument = self.client.resolve_instrument(
            stock_code, market_segment
        )
        self.database.upsert_instruments([instrument])
        return instrument

    def sync_all_quotes(
        self,
        progress: ProgressCallback | None = None,
    ) -> tuple[int, int]:
        instruments = self.database.list_instruments()
        if not instruments:
            raise RuntimeError(
                '商品清冊是空的，請先建立 Yahoo 台灣商品清冊或新增持股。'
            )
        quotes, failed = self.client.download_quotes(
            instruments, progress
        )
        self.database.upsert_quotes(quotes)
        self.database.add_sync_log(
            'QUOTES',
            'SUCCESS' if quotes else 'FAILED',
            f'success={len(quotes)}, failed={len(failed)}',
        )
        return len(quotes), len(failed)

    def sync_holding_quotes(
        self,
        progress: ProgressCallback | None = None,
    ) -> tuple[int, int]:
        holdings = self.database.list_holdings()
        instruments: list[Instrument] = []
        for holding in holdings:
            instrument = self.database.get_instrument(
                holding.yahoo_symbol
            )
            if instrument:
                instruments.append(instrument)
        if not instruments:
            return 0, 0

        quotes, failed = self.client.download_quotes(
            instruments, progress
        )
        self.database.upsert_quotes(quotes)
        return len(quotes), len(failed)

    def sync_holding_actions(
        self,
        progress: ProgressCallback | None = None,
    ) -> tuple[int, int]:
        holdings = self.database.list_holdings()
        action_count = 0
        failed_count = 0
        total = len(holdings)

        for index, holding in enumerate(holdings, start=1):
            if progress:
                progress(
                    f'公司行動 {index}/{total}：{holding.yahoo_symbol}',
                    index,
                    total,
                )
            instrument = self.database.get_instrument(
                holding.yahoo_symbol
            )
            if not instrument:
                try:
                    instrument = self.resolve_and_save_instrument(
                        holding.stock_code,
                        holding.market_segment,
                    )
                except Exception:
                    failed_count += 1
                    continue

            try:
                actions = self.client.fetch_actions(instrument)
                self.database.replace_actions_for_symbol(
                    instrument.symbol, actions
                )
                action_count += len(actions)
            except Exception:
                failed_count += 1

        self.database.add_sync_log(
            'ACTIONS',
            'SUCCESS',
            f'actions={action_count}, failed_symbols={failed_count}',
        )
        return action_count, failed_count
