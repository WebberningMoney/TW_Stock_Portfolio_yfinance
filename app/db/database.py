'''SQLite 資料庫與 CSV 匯出。'''

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from app.config import DATA_DIR, DATABASE_PATH
from app.models import CorporateAction, Holding, Instrument, MarketQuote


class Database:
    def __init__(self, path: Path = DATABASE_PATH) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        return connection

    @staticmethod
    def _column_exists(
        connection: sqlite3.Connection,
        table: str,
        column: str,
    ) -> bool:
        rows = connection.execute(f'PRAGMA table_info({table})').fetchall()
        return any(row['name'] == column for row in rows)

    def initialize(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                '''
                CREATE TABLE IF NOT EXISTS instruments (
                    symbol TEXT PRIMARY KEY,
                    stock_code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    exchange TEXT NOT NULL DEFAULT '',
                    market_segment TEXT NOT NULL DEFAULT 'AUTO',
                    quote_type TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL DEFAULT 'TWD',
                    product_category TEXT NOT NULL DEFAULT 'OTHER',
                    source TEXT NOT NULL DEFAULT 'yfinance',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_instruments_code
                ON instruments(stock_code);

                CREATE TABLE IF NOT EXISTS holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_code TEXT NOT NULL,
                    yahoo_symbol TEXT NOT NULL UNIQUE,
                    stock_name TEXT NOT NULL,
                    market_segment TEXT NOT NULL DEFAULT 'AUTO',
                    shares INTEGER NOT NULL CHECK (shares > 0),
                    total_cost REAL NOT NULL CHECK (total_cost >= 0),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS market_quotes (
                    symbol TEXT PRIMARY KEY,
                    stock_code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    close REAL NOT NULL,
                    previous_close REAL NOT NULL,
                    change_value REAL NOT NULL,
                    change_percent REAL NOT NULL,
                    volume REAL NOT NULL,
                    trade_date TEXT NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'TWD',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS corporate_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    stock_code TEXT NOT NULL,
                    stock_name TEXT NOT NULL,
                    action_date TEXT NOT NULL,
                    action_type TEXT NOT NULL CHECK (action_type IN ('DIVIDEND', 'SPLIT')),
                    value REAL NOT NULL,
                    source TEXT NOT NULL DEFAULT 'yfinance',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, action_date, action_type, value, source)
                );

                CREATE INDEX IF NOT EXISTS idx_actions_symbol_date
                ON corporate_actions(symbol, action_date);

                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                '''
            )

            # 相容 v1.0/v1.1 已存在的資料庫。
            if not self._column_exists(
                connection, 'instruments', 'product_category'
            ):
                connection.execute(
                    "ALTER TABLE instruments ADD COLUMN "
                    "product_category TEXT NOT NULL DEFAULT 'OTHER'"
                )

    @staticmethod
    def _instrument_values(instruments: list[Instrument]) -> list[tuple]:
        return [
            (
                item.symbol,
                item.stock_code,
                item.name,
                item.exchange,
                item.market_segment,
                item.quote_type,
                item.currency,
                item.product_category,
                item.source,
            )
            for item in instruments
        ]

    @staticmethod
    def _upsert_instruments_on_connection(
        connection: sqlite3.Connection,
        instruments: list[Instrument],
    ) -> None:
        if not instruments:
            return
        connection.executemany(
            '''
            INSERT INTO instruments (
                symbol, stock_code, name, exchange, market_segment,
                quote_type, currency, product_category, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                stock_code = excluded.stock_code,
                name = excluded.name,
                exchange = excluded.exchange,
                market_segment = CASE
                    WHEN instruments.market_segment = 'EMERGING'
                    THEN instruments.market_segment
                    ELSE excluded.market_segment
                END,
                quote_type = excluded.quote_type,
                currency = excluded.currency,
                product_category = excluded.product_category,
                source = excluded.source,
                updated_at = CURRENT_TIMESTAMP
            ''',
            Database._instrument_values(instruments),
        )

    @staticmethod
    def _sync_names(connection: sqlite3.Connection) -> None:
        connection.execute(
            """UPDATE holdings
               SET stock_name = (
                   SELECT name FROM instruments
                   WHERE instruments.symbol = holdings.yahoo_symbol
               ), updated_at = CURRENT_TIMESTAMP
               WHERE EXISTS (
                   SELECT 1 FROM instruments
                   WHERE instruments.symbol = holdings.yahoo_symbol
               )"""
        )
        connection.execute(
            """UPDATE market_quotes
               SET name = (
                   SELECT name FROM instruments
                   WHERE instruments.symbol = market_quotes.symbol
               ), updated_at = CURRENT_TIMESTAMP
               WHERE EXISTS (
                   SELECT 1 FROM instruments
                   WHERE instruments.symbol = market_quotes.symbol
               )"""
        )
        connection.execute(
            """UPDATE corporate_actions
               SET stock_name = (
                   SELECT name FROM instruments
                   WHERE instruments.symbol = corporate_actions.symbol
               ), updated_at = CURRENT_TIMESTAMP
               WHERE EXISTS (
                   SELECT 1 FROM instruments
                   WHERE instruments.symbol = corporate_actions.symbol
               )"""
        )

    def upsert_instruments(self, instruments: list[Instrument]) -> None:
        if not instruments:
            return
        with self._connect() as connection:
            self._upsert_instruments_on_connection(connection, instruments)
            self._sync_names(connection)

    def replace_universe(
        self,
        instruments: list[Instrument],
        preserve_holding_instruments: bool = True,
    ) -> None:
        """
        清除舊商品清冊與行情後，寫入新的篩選結果。

        持股本身不刪除。若勾選保留持股商品，會保留那些商品的清冊資料，
        即使其類型不在本次勾選範圍內。
        """
        with self._connect() as connection:
            preserved: list[Instrument] = []
            if preserve_holding_instruments:
                rows = connection.execute(
                    '''SELECT i.symbol, i.stock_code, i.name, i.exchange,
                              i.market_segment, i.quote_type, i.currency,
                              i.product_category, i.source
                       FROM instruments AS i
                       INNER JOIN holdings AS h
                       ON h.yahoo_symbol = i.symbol'''
                ).fetchall()
                preserved = [Instrument(**dict(row)) for row in rows]

            connection.execute('DELETE FROM market_quotes')
            connection.execute('DELETE FROM instruments')

            merged = {item.symbol: item for item in preserved}
            merged.update({item.symbol: item for item in instruments})
            self._upsert_instruments_on_connection(
                connection,
                sorted(merged.values(), key=lambda item: item.symbol),
            )
            self._sync_names(connection)

    def list_instruments(self) -> list[Instrument]:
        with self._connect() as connection:
            rows = connection.execute(
                '''SELECT symbol, stock_code, name, exchange, market_segment,
                          quote_type, currency, product_category, source
                   FROM instruments ORDER BY symbol'''
            ).fetchall()
        return [Instrument(**dict(row)) for row in rows]

    def get_instrument(self, symbol: str) -> Instrument | None:
        with self._connect() as connection:
            row = connection.execute(
                '''SELECT symbol, stock_code, name, exchange, market_segment,
                          quote_type, currency, product_category, source
                   FROM instruments WHERE symbol = ?''',
                (symbol,),
            ).fetchone()
        return Instrument(**dict(row)) if row else None

    def find_instruments_by_code(self, stock_code: str) -> list[Instrument]:
        with self._connect() as connection:
            rows = connection.execute(
                '''SELECT symbol, stock_code, name, exchange, market_segment,
                          quote_type, currency, product_category, source
                   FROM instruments WHERE stock_code = ? ORDER BY symbol''',
                (stock_code,),
            ).fetchall()
        return [Instrument(**dict(row)) for row in rows]

    def upsert_holding(self, holding: Holding) -> None:
        with self._connect() as connection:
            connection.execute(
                '''INSERT INTO holdings (
                       stock_code, yahoo_symbol, stock_name,
                       market_segment, shares, total_cost
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(yahoo_symbol) DO UPDATE SET
                       stock_code = excluded.stock_code,
                       stock_name = excluded.stock_name,
                       market_segment = excluded.market_segment,
                       shares = excluded.shares,
                       total_cost = excluded.total_cost,
                       updated_at = CURRENT_TIMESTAMP''',
                (
                    holding.stock_code,
                    holding.yahoo_symbol,
                    holding.stock_name,
                    holding.market_segment,
                    holding.shares,
                    holding.total_cost,
                ),
            )

    def delete_holding(self, yahoo_symbol: str) -> None:
        with self._connect() as connection:
            connection.execute(
                'DELETE FROM holdings WHERE yahoo_symbol = ?',
                (yahoo_symbol,),
            )

    def list_holdings(self) -> list[Holding]:
        with self._connect() as connection:
            rows = connection.execute(
                '''SELECT id, stock_code, yahoo_symbol, stock_name,
                          market_segment, shares, total_cost
                   FROM holdings ORDER BY yahoo_symbol'''
            ).fetchall()
        return [Holding(**dict(row)) for row in rows]

    def upsert_quotes(self, quotes: list[MarketQuote]) -> None:
        if not quotes:
            return
        with self._connect() as connection:
            connection.executemany(
                '''INSERT INTO market_quotes (
                       symbol, stock_code, name, close, previous_close,
                       change_value, change_percent, volume, trade_date, currency
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(symbol) DO UPDATE SET
                       stock_code = excluded.stock_code,
                       name = excluded.name,
                       close = excluded.close,
                       previous_close = excluded.previous_close,
                       change_value = excluded.change_value,
                       change_percent = excluded.change_percent,
                       volume = excluded.volume,
                       trade_date = excluded.trade_date,
                       currency = excluded.currency,
                       updated_at = CURRENT_TIMESTAMP''',
                [
                    (
                        item.symbol,
                        item.stock_code,
                        item.name,
                        item.close,
                        item.previous_close,
                        item.change,
                        item.change_percent,
                        item.volume,
                        item.trade_date,
                        item.currency,
                    )
                    for item in quotes
                ],
            )

    def get_quote_map(self) -> dict[str, dict]:
        with self._connect() as connection:
            rows = connection.execute('SELECT * FROM market_quotes').fetchall()
        return {row['symbol']: dict(row) for row in rows}

    def list_quotes(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                'SELECT * FROM market_quotes ORDER BY symbol'
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_actions_for_symbol(
        self,
        symbol: str,
        actions: list[CorporateAction],
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM corporate_actions "
                "WHERE symbol = ? AND source = 'yfinance'",
                (symbol,),
            )
            connection.executemany(
                '''INSERT OR IGNORE INTO corporate_actions (
                       symbol, stock_code, stock_name, action_date,
                       action_type, value, source
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
                [
                    (
                        item.symbol,
                        item.stock_code,
                        item.stock_name,
                        item.action_date,
                        item.action_type,
                        item.value,
                        item.source,
                    )
                    for item in actions
                ],
            )

    def list_actions(
        self,
        action_type: str | None = None,
    ) -> list[CorporateAction]:
        sql = '''SELECT symbol, stock_code, stock_name, action_date,
                        action_type, value, source
                 FROM corporate_actions'''
        params: tuple = ()
        if action_type:
            sql += ' WHERE action_type = ?'
            params = (action_type,)
        sql += ' ORDER BY action_date DESC, symbol'
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        return [CorporateAction(**dict(row)) for row in rows]

    def add_sync_log(
        self,
        sync_type: str,
        status: str,
        message: str = '',
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                'INSERT INTO sync_log(sync_type, status, message) '
                'VALUES (?, ?, ?)',
                (sync_type, status, message),
            )

    def export_query_to_csv(self, sql: str, path: Path) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            cursor = connection.execute(sql)
            rows = cursor.fetchall()
            headers = [column[0] for column in cursor.description]
        with path.open('w', newline='', encoding='utf-8-sig') as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows([tuple(row) for row in rows])
        return len(rows)
