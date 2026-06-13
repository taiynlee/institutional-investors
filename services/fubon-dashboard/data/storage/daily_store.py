"""
每日盤前資料的 SQLite 儲存（法人、融資券、股價、當沖名單、股票池、盤前執行紀錄）。
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path


class DailyStore:
    def __init__(self, db_path: str = "data/daily.db"):
        self.db_path = db_path

    def init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS institutional (
                    date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    foreign_net INTEGER DEFAULT 0,
                    trust_net INTEGER DEFAULT 0,
                    dealer_net INTEGER DEFAULT 0,
                    PRIMARY KEY (date, stock_id)
                );

                CREATE TABLE IF NOT EXISTS margin (
                    date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    margin_balance INTEGER DEFAULT 0,
                    margin_change INTEGER DEFAULT 0,
                    short_balance INTEGER DEFAULT 0,
                    short_change INTEGER DEFAULT 0,
                    PRIMARY KEY (date, stock_id)
                );

                CREATE TABLE IF NOT EXISTS daily_price (
                    date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER DEFAULT 0,
                    PRIMARY KEY (date, stock_id)
                );

                CREATE TABLE IF NOT EXISTS daytrade_list (
                    date TEXT NOT NULL,
                    stock_id TEXT NOT NULL,
                    PRIMARY KEY (date, stock_id)
                );

                CREATE TABLE IF NOT EXISTS watchlist (
                    stock_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    added_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS pre_session_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_date TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    total_stocks INTEGER DEFAULT 0,
                    success_stocks INTEGER DEFAULT 0,
                    error_msg TEXT
                );
            """)
            conn.commit()

    # ── Institutional ─────────────────────────────────────────────────────────
    def upsert_institutional(self, date: str, stock_id: str,
                             foreign_net: int, trust_net: int, dealer_net: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO institutional
                    (date, stock_id, foreign_net, trust_net, dealer_net)
                VALUES (?, ?, ?, ?, ?)
            """, (date, stock_id, foreign_net, trust_net, dealer_net))

    def upsert_margin(self, date: str, stock_id: str,
                      margin_balance: int, margin_change: int,
                      short_balance: int, short_change: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO margin
                    (date, stock_id, margin_balance, margin_change, short_balance, short_change)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (date, stock_id, margin_balance, margin_change, short_balance, short_change))

    def upsert_price(self, date: str, stock_id: str,
                     open_: float, high: float, low: float, close: float, volume: int):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO daily_price
                    (date, stock_id, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (date, stock_id, open_, high, low, close, volume))

    def upsert_daytrade_list(self, date: str, stock_ids: list[str]):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM daytrade_list WHERE date=?", (date,))
            conn.executemany(
                "INSERT OR IGNORE INTO daytrade_list (date, stock_id) VALUES (?, ?)",
                [(date, sid) for sid in stock_ids],
            )

    # ── Watchlist ─────────────────────────────────────────────────────────────
    def get_watchlist(self) -> list[dict]:
        """回傳 [{"stock_id": "2330", "name": "台積電", "added_at": "..."}, ...]"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT stock_id, name, added_at FROM watchlist ORDER BY stock_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_watchlist_ids(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT stock_id FROM watchlist ORDER BY stock_id"
            ).fetchall()
        return [r[0] for r in rows]

    def add_to_watchlist(self, stock_id: str, name: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO watchlist (stock_id, name, added_at) VALUES (?, ?, date('now'))",
                (stock_id, name),
            )

    def update_watchlist_name(self, stock_id: str, name: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE watchlist SET name=? WHERE stock_id=?",
                (name, stock_id),
            )

    def remove_from_watchlist(self, stock_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM watchlist WHERE stock_id=?", (stock_id,))

    def seed_watchlist(self, stock_ids: list[str], names: dict[str, str] = None):
        """初次從 config.yaml 載入名單（已存在的不覆蓋）。names={stock_id: name}"""
        names = names or {}
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO watchlist (stock_id, name, added_at) VALUES (?, ?, date('now'))",
                [(sid, names.get(sid, "")) for sid in stock_ids],
            )
            # 補填已存在但 name 為空的
            for sid, name in names.items():
                if name:
                    conn.execute(
                        "UPDATE watchlist SET name=? WHERE stock_id=? AND name=''",
                        (name, sid),
                    )

    # ── Pre-session log ───────────────────────────────────────────────────────
    def log_start(self, run_date: str, started_at: str, total_stocks: int) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("""
                INSERT INTO pre_session_log (run_date, started_at, status, total_stocks)
                VALUES (?, ?, 'running', ?)
            """, (run_date, started_at, total_stocks))
            return cur.lastrowid

    def log_finish(self, log_id: int, finished_at: str, success_stocks: int,
                   status: str = "ok", error_msg: str = None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE pre_session_log
                SET finished_at=?, status=?, success_stocks=?, error_msg=?
                WHERE id=?
            """, (finished_at, status, success_stocks, error_msg, log_id))

    def get_pre_session_logs(self, limit: int = 10) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM pre_session_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Read helpers ──────────────────────────────────────────────────────────
    def get_prices(self, stock_id: str, days: int = 25) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM daily_price WHERE stock_id=? ORDER BY date DESC LIMIT ?",
                (stock_id, days),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_institutional(self, stock_id: str, days: int = 5) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM institutional WHERE stock_id=? ORDER BY date DESC LIMIT ?",
                (stock_id, days),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_margin(self, stock_id: str, date: str) -> dict | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM margin WHERE stock_id=? AND date=?",
                (stock_id, date),
            ).fetchone()
        return dict(row) if row else None

    def get_last_daytrade_list(self, exclude_date: str = None) -> tuple:
        """回傳最近一次非空的 daytrade_list (date, [stock_ids])，用於大跌日備援。"""
        with sqlite3.connect(self.db_path) as conn:
            dates = [r[0] for r in conn.execute(
                "SELECT DISTINCT date FROM daytrade_list ORDER BY date DESC LIMIT 30"
            ).fetchall()]
        for d in dates:
            if exclude_date and d == exclude_date:
                continue
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT stock_id FROM daytrade_list WHERE date=?", (d,)
                ).fetchall()
            if rows:
                return d, [r[0] for r in rows]
        return None, []

    def is_daytrade(self, stock_id: str, date: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT 1 FROM daytrade_list WHERE stock_id=? AND date=?",
                (stock_id, date),
            ).fetchone()
        return row is not None

    def get_db_size_mb(self) -> float:
        return Path(self.db_path).stat().st_size / 1024 / 1024

    # ── Cleanup ───────────────────────────────────────────────────────────────
    def cleanup_old_data(self, keep_days: int = 60):
        """刪除超過 keep_days 天的歷史資料，防止資料庫無限增長。"""
        cutoff = (date.today() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            for tbl in ("institutional", "margin", "daily_price"):
                conn.execute(f"DELETE FROM {tbl} WHERE date < ?", (cutoff,))
            cutoff30 = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
            conn.execute("DELETE FROM daytrade_list WHERE date < ?", (cutoff30,))
            cutoff90 = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d")
            conn.execute("DELETE FROM pre_session_log WHERE run_date < ?", (cutoff90,))
        # VACUUM 不能在 transaction 內執行，需單獨連線
        with sqlite3.connect(self.db_path) as conn:
            conn.isolation_level = None
            conn.execute("VACUUM")
