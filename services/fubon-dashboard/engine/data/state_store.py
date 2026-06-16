import logging
import sqlite3
from datetime import datetime

from engine.utils.tz import TZ_TW, today_tw

logger = logging.getLogger(__name__)

_SETTINGS_DDL = """CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)"""


def get_setting(db: str, key: str, default=None):
    try:
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        if row:
            return row[0]
    except Exception:
        pass
    return default


def set_setting(db: str, key: str, value) -> None:
    try:
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                (key, str(value)),
            )
            conn.commit()
    except Exception as e:
        logger.warning("settings 寫入失敗: %s", e)


_DDL = [
    """CREATE TABLE IF NOT EXISTS intraday_trades (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date     TEXT    NOT NULL,
        trade_time     TEXT    NOT NULL,
        symbol         TEXT    NOT NULL,
        lots           INTEGER NOT NULL DEFAULT 0,
        pnl            REAL    NOT NULL,
        cumulative_pnl REAL    NOT NULL,
        is_paper       INTEGER NOT NULL DEFAULT 0,
        dry_run        INTEGER NOT NULL DEFAULT 1
    )""",
    """CREATE TABLE IF NOT EXISTS intraday_positions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date  TEXT    NOT NULL,
        symbol      TEXT    NOT NULL,
        entry_price REAL    NOT NULL,
        lots        INTEGER NOT NULL,
        entry_time  TEXT    NOT NULL,
        stop_loss   REAL    NOT NULL,
        take_profit REAL    NOT NULL DEFAULT 0,
        is_paper    INTEGER NOT NULL DEFAULT 0
    )""",
]


def init_tables(db: str) -> None:
    with sqlite3.connect(db) as conn:
        conn.execute(_SETTINGS_DDL)
        for ddl in _DDL:
            conn.execute(ddl)
        for _col, _def in [
            ("dry_run",     "INTEGER NOT NULL DEFAULT 1"),
            ("entry_price", "REAL    NOT NULL DEFAULT 0"),
            ("exit_price",  "REAL    NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE intraday_trades ADD COLUMN {_col} {_def}")
            except sqlite3.OperationalError:
                pass
        for _col, _def in [
            ("take_profit", "REAL NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE intraday_positions ADD COLUMN {_col} {_def}")
            except sqlite3.OperationalError:
                pass
        conn.commit()


def cleanup_old_intraday(db: str, keep_days: int = 60) -> None:
    from datetime import timedelta
    cutoff = (today_tw() - timedelta(days=keep_days)).isoformat()
    try:
        with sqlite3.connect(db) as conn:
            conn.execute("DELETE FROM intraday_trades WHERE trade_date < ?", (cutoff,))
            conn.execute("DELETE FROM intraday_positions WHERE trade_date < ?", (cutoff,))
            conn.commit()
    except Exception as e:
        logger.warning("清理舊盤中紀錄失敗: %s", e)


def _today() -> str:
    return today_tw().isoformat()


def persist_daily_tracker(db: str, dt, dry_run: bool = True) -> None:
    today = _today()
    dr = int(dry_run)
    try:
        with sqlite3.connect(db) as conn:
            conn.execute(
                "DELETE FROM intraday_trades WHERE trade_date=? AND is_paper=0", (today,))
            for t in dt.trades:
                conn.execute(
                    "INSERT INTO intraday_trades"
                    "(trade_date,trade_time,symbol,lots,pnl,cumulative_pnl,"
                    "is_paper,dry_run,entry_price,exit_price)"
                    " VALUES(?,?,?,?,?,?,0,?,?,?)",
                    (today, t["time"], t["symbol"],
                     t.get("lots", 0), t["pnl"], t["cumulative_pnl"], dr,
                     t.get("entry_price", 0), t.get("exit_price", 0)),
                )
            conn.commit()
    except Exception as e:
        logger.warning("DailyTracker 持久化失敗: %s", e)


def persist_paper_tracker(db: str, paper, dry_run: bool = True) -> None:
    today = _today()
    dr = int(dry_run)
    try:
        with sqlite3.connect(db) as conn:
            conn.execute(
                "DELETE FROM intraday_trades WHERE trade_date=? AND is_paper=1", (today,))
            conn.execute(
                "DELETE FROM intraday_positions WHERE trade_date=? AND is_paper=1", (today,))

            cumulative = 0.0
            for t in paper.closed_trades:
                cumulative += t.pnl
                conn.execute(
                    "INSERT INTO intraday_trades"
                    "(trade_date,trade_time,symbol,lots,pnl,cumulative_pnl,is_paper,dry_run)"
                    " VALUES(?,?,?,?,?,?,1,?)",
                    (today,
                     t.exit_time.strftime("%H:%M:%S") if t.exit_time else "",
                     t.symbol, t.lots, t.pnl, cumulative, dr),
                )

            for sym, pt in paper.positions.items():
                conn.execute(
                    "INSERT INTO intraday_positions"
                    "(trade_date,symbol,entry_price,lots,entry_time,stop_loss,atr,orb_low,is_paper)"
                    " VALUES(?,?,?,?,?,?,?,?,1)",
                    (today, sym, pt.entry_price, pt.lots,
                     pt.entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                     pt.stop_loss, pt.atr, pt.orb_low),
                )
            conn.commit()
    except Exception as e:
        logger.warning("PaperTracker 持久化失敗: %s", e)


def restore_daily_tracker(db: str, dt) -> bool:
    today = _today()
    try:
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                "SELECT trade_time,symbol,lots,pnl,cumulative_pnl"
                " FROM intraday_trades WHERE trade_date=? AND is_paper=0 ORDER BY id",
                (today,),
            ).fetchall()
        if not rows:
            return False
        dt.trades = [
            {"time": r[0], "symbol": r[1], "lots": r[2],
             "pnl": r[3], "cumulative_pnl": r[4]}
            for r in rows
        ]
        dt.total_pnl = rows[-1][4]
        logger.info("恢復 DailyTracker: %d 筆成交，累計損益=%.0f", len(rows), dt.total_pnl)
        return True
    except Exception as e:
        logger.warning("DailyTracker 恢復失敗: %s", e)
        return False


def restore_paper_tracker(db: str, paper) -> bool:
    from engine.data.paper_tracker import PaperTrade
    today = _today()
    try:
        with sqlite3.connect(db) as conn:
            closed_rows = conn.execute(
                "SELECT trade_time,symbol,lots,pnl"
                " FROM intraday_trades WHERE trade_date=? AND is_paper=1 ORDER BY id",
                (today,),
            ).fetchall()
            pos_rows = conn.execute(
                "SELECT symbol,entry_price,lots,entry_time,stop_loss,atr,orb_low"
                " FROM intraday_positions WHERE trade_date=? AND is_paper=1",
                (today,),
            ).fetchall()

        for r in closed_rows:
            pt = PaperTrade(
                symbol=r[1], entry_price=0.0, lots=r[2],
                entry_time=datetime.now(tz=TZ_TW), atr=0.0, stop_loss=0.0,
            )
            pt.exit_price = 0.0
            pt.pnl = r[3]
            paper.closed_trades.append(pt)

        for r in pos_rows:
            try:
                et = datetime.strptime(r[3], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ_TW)
            except Exception:
                et = datetime.now(tz=TZ_TW)
            paper.positions[r[0]] = PaperTrade(
                symbol=r[0], entry_price=r[1], lots=r[2],
                entry_time=et, atr=r[5], stop_loss=r[4], orb_low=r[6],
            )

        total = len(paper.closed_trades) + len(paper.positions)
        if total:
            logger.info("恢復 PaperTracker: %d 已平倉, %d 開倉",
                        len(paper.closed_trades), len(paper.positions))
            return True
        return False
    except Exception as e:
        logger.warning("PaperTracker 恢復失敗: %s", e)
        return False
