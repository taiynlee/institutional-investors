import asyncio
import json
import math
import os
import sqlite3
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class TradingParamsBody(BaseModel):
    max_position_capital: int
    max_daily_positions: int
    dry_run: bool


def _today() -> str:
    return date.today().isoformat()


def _sanitize(obj):
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return str(obj)
    return obj


def create_app(
    positions: dict = None,
    daily_tracker=None,
    daily_store=None,
    max_position_capital: int = 1_000_000,
    max_daily_positions: int = 3,
    dry_run: bool = True,
    ticks_db: str = "/fubon-data/ticks.db",
) -> FastAPI:
    app = FastAPI(title="Fubon DayTrade Dashboard")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _positions = positions or {}
    _tracker = daily_tracker
    _store = daily_store
    _ticks_db = ticks_db
    _trading_params = {
        "max_position_capital": max_position_capital,
        "max_daily_positions": max_daily_positions,
        "dry_run": dry_run,
    }

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ── Positions ─────────────────────────────────────────────────────────────
    @app.get("/positions")
    def get_positions():
        if _positions:
            return [
                {
                    "symbol": sym,
                    "lots": pos.lots,
                    "entry_price": pos.entry_price,
                    "stop_loss": pos.stop_loss,
                }
                for sym, pos in _positions.items()
            ]
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                c.row_factory = sqlite3.Row
                rows = c.execute(
                    "SELECT symbol, entry_price, lots, stop_loss FROM intraday_positions "
                    "WHERE trade_date=? AND is_paper=0",
                    (_today(),),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── PnL / Status ──────────────────────────────────────────────────────────
    @app.get("/pnl")
    def get_pnl():
        if _tracker:
            return {"total_pnl": _tracker.total_pnl}
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                row = c.execute(
                    "SELECT cumulative_pnl FROM intraday_trades "
                    "WHERE trade_date=? AND is_paper=0 ORDER BY id DESC LIMIT 1",
                    (_today(),),
                ).fetchone()
            return {"total_pnl": row[0] if row else 0.0}
        except Exception:
            return {"total_pnl": 0.0}

    @app.get("/status")
    def get_status():
        if _tracker:
            return {"total_pnl": _tracker.total_pnl, "trade_count": _tracker.trade_count}
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                row = c.execute(
                    "SELECT COUNT(*), COALESCE(MAX(cumulative_pnl), 0) FROM intraday_trades "
                    "WHERE trade_date=? AND is_paper=0",
                    (_today(),),
                ).fetchone()
            return {"total_pnl": row[1] if row else 0.0, "trade_count": row[0] if row else 0}
        except Exception:
            return {"total_pnl": 0.0, "trade_count": 0}

    # ── Trades ────────────────────────────────────────────────────────────────
    @app.get("/trades")
    def get_trades():
        if _tracker:
            return _tracker.trades
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                c.row_factory = sqlite3.Row
                rows = c.execute(
                    "SELECT trade_time as time, symbol, lots, pnl, cumulative_pnl "
                    "FROM intraday_trades WHERE trade_date=? AND is_paper=0 ORDER BY id",
                    (_today(),),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Trade history (multi-day) ─────────────────────────────────────────────
    @app.get("/trade-history")
    def get_trade_history(limit: int = 500):
        if _store is None:
            daily_db_path = None
        else:
            daily_db_path = getattr(_store, "db_path", None)

        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                c.row_factory = sqlite3.Row
                if daily_db_path and Path(daily_db_path).exists():
                    try:
                        c.execute(f"ATTACH DATABASE 'file:{daily_db_path}?mode=ro' AS wldb")
                        name_join = "LEFT JOIN wldb.watchlist w ON w.stock_id = t.symbol"
                    except Exception:
                        name_join = ""
                else:
                    name_join = ""

                rows = c.execute(f"""
                    SELECT
                        t.trade_date,
                        t.symbol,
                        COALESCE(w.name, '') AS name,
                        MAX(t.dry_run)       AS dry_run,
                        ROUND(SUM(t.pnl), 0) AS pnl,
                        COUNT(*)             AS trade_count,
                        ROUND(AVG(NULLIF(COALESCE(t.entry_price,0),0)), 2) AS avg_entry,
                        ROUND(AVG(NULLIF(COALESCE(t.exit_price,0), 0)), 2) AS avg_exit,
                        SUM(
                            CAST(COALESCE(t.entry_price,0)*t.lots*1000*0.001425 AS INTEGER) +
                            CAST(COALESCE(t.exit_price,0) *t.lots*1000*0.001425 AS INTEGER) +
                            CAST(COALESCE(t.exit_price,0) *t.lots*1000*0.0015   AS INTEGER)
                        ) AS commission,
                        SUM(
                            CAST(COALESCE(t.entry_price,0)*t.lots*1000*0.001425 AS INTEGER) +
                            CAST(COALESCE(t.exit_price,0) *t.lots*1000*0.001425 AS INTEGER)
                        ) AS brokerage_only
                    FROM intraday_trades t
                    {name_join}
                    WHERE t.is_paper = 0
                    GROUP BY t.trade_date, t.symbol
                    ORDER BY t.trade_date DESC, t.symbol
                    LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Daytrade list (pre-session screened stocks) ───────────────────────────
    @app.get("/daytrade-list")
    def get_daytrade_list(date_str: str = ""):
        if _store is None:
            raise HTTPException(status_code=503, detail="daily_store 未初始化")
        daily_db_path = getattr(_store, "db_path", None)
        if not daily_db_path or not Path(daily_db_path).exists():
            raise HTTPException(status_code=503, detail="daily.db 未就緒")
        try:
            with sqlite3.connect(f"file:{daily_db_path}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                c.row_factory = sqlite3.Row
                if date_str:
                    target_date = date_str
                else:
                    row = c.execute("SELECT MAX(date) FROM daytrade_list").fetchone()
                    target_date = row[0] if row and row[0] else _today()

                rows = c.execute("""
                    SELECT
                        d.stock_id,
                        COALESCE(w.name, '') AS name,
                        dp.close             AS prev_close,
                        dp.volume            AS volume,
                        (SELECT close FROM daily_price dp_p
                         WHERE dp_p.stock_id = d.stock_id AND dp_p.date < dp.date
                         ORDER BY dp_p.date DESC LIMIT 1) AS prev_prev_close,
                        (SELECT AVG(volume) FROM (
                            SELECT volume FROM daily_price dp3
                            WHERE dp3.stock_id = d.stock_id
                            ORDER BY dp3.date DESC LIMIT 5
                        )) AS avg_vol5,
                        (SELECT AVG(close) FROM (
                            SELECT close FROM daily_price dp2
                            WHERE dp2.stock_id = d.stock_id
                            ORDER BY dp2.date DESC LIMIT 20
                        )) AS ma20,
                        COALESCE(inst.foreign_net, 0)   AS foreign_net,
                        COALESCE(inst.trust_net, 0)     AS trust_net,
                        COALESCE(inst.dealer_net, 0)    AS dealer_net,
                        COALESCE(mgn.margin_balance, 0) AS margin_balance,
                        COALESCE(mgn.margin_change, 0)  AS margin_change,
                        COALESCE(mgn.short_balance, 0)  AS short_balance
                    FROM daytrade_list d
                    LEFT JOIN watchlist w ON w.stock_id = d.stock_id
                    LEFT JOIN daily_price dp ON dp.stock_id = d.stock_id
                        AND dp.date = (
                            SELECT MAX(date) FROM daily_price m WHERE m.stock_id = d.stock_id
                        )
                    LEFT JOIN institutional inst ON inst.stock_id = d.stock_id
                        AND inst.date = (
                            SELECT MAX(date) FROM institutional i WHERE i.stock_id = d.stock_id
                        )
                    LEFT JOIN margin mgn ON mgn.stock_id = d.stock_id
                        AND mgn.date = (
                            SELECT MAX(date) FROM margin m WHERE m.stock_id = d.stock_id
                        )
                    WHERE d.date = ?
                    ORDER BY d.stock_id
                """, (target_date,)).fetchall()

                result = []
                for r in rows:
                    row_d = dict(r)
                    prev = row_d.get("prev_prev_close") or row_d.get("prev_close") or 0
                    cur  = row_d.get("prev_close") or 0
                    change = round(cur - prev, 2) if prev else 0
                    change_pct = round(change / prev * 100, 2) if prev else 0
                    avg5 = row_d.get("avg_vol5") or 0
                    row_d["change"] = change
                    row_d["change_pct"] = change_pct
                    row_d["avg_vol5"] = round(avg5)
                    row_d["above_ma20"] = cur > (row_d.get("ma20") or 0)
                    row_d["vol_ok"] = avg5 >= 2000
                    # chip_count: 外資買 + 投信買 + 融資減
                    row_d["chip_count"] = (
                        (1 if row_d["foreign_net"] > 0 else 0) +
                        (1 if row_d["trust_net"] > 0 else 0) +
                        (1 if row_d["margin_change"] < 0 else 0)
                    )
                    result.append(row_d)
                return {"date": target_date, "count": len(result), "stocks": result}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/daytrade-list/dates")
    def get_daytrade_dates():
        if _store is None:
            return []
        daily_db_path = getattr(_store, "db_path", None)
        if not daily_db_path or not Path(daily_db_path).exists():
            return []
        try:
            with sqlite3.connect(f"file:{daily_db_path}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                rows = c.execute(
                    "SELECT date, COUNT(*) as cnt FROM daytrade_list GROUP BY date ORDER BY date DESC LIMIT 30"
                ).fetchall()
            return [{"date": r[0], "count": r[1]} for r in rows]
        except Exception:
            return []

    # ── System status ──────────────────────────────────────────────────────────
    @app.get("/system-status")
    def get_system_status():
        result: dict = {}

        # daily.db stats
        if _store is not None:
            daily_db_path = getattr(_store, "db_path", None)
            if daily_db_path and Path(daily_db_path).exists():
                p = Path(daily_db_path)
                result["daily_db_mb"] = round(p.stat().st_size / 1024 / 1024, 2)
                try:
                    with sqlite3.connect(f"file:{daily_db_path}?mode=ro", uri=True,
                                         check_same_thread=False) as c:
                        row = c.execute(
                            "SELECT date, COUNT(*) FROM daytrade_list GROUP BY date ORDER BY date DESC LIMIT 1"
                        ).fetchone()
                        if row:
                            result["daytrade_latest_date"] = row[0]
                            result["daytrade_latest_count"] = row[1]
                        else:
                            result["daytrade_latest_date"] = None
                            result["daytrade_latest_count"] = 0

                        row2 = c.execute(
                            "SELECT COUNT(*) FROM watchlist"
                        ).fetchone()
                        result["watchlist_count"] = row2[0] if row2 else 0

                        row3 = c.execute(
                            "SELECT run_date, status, success_stocks, total_stocks FROM pre_session_log "
                            "ORDER BY run_date DESC LIMIT 1"
                        ).fetchone()
                        if row3:
                            result["last_presession_date"] = row3[0]
                            result["last_presession_status"] = row3[1]
                            result["last_presession_success"] = row3[2]
                            result["last_presession_total"] = row3[3]
                except Exception:
                    pass
            else:
                result["daily_db_mb"] = 0

        # ticks.db stats
        if Path(_ticks_db).exists():
            p2 = Path(_ticks_db)
            result["ticks_db_mb"] = round(p2.stat().st_size / 1024 / 1024, 2)
            try:
                with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                     check_same_thread=False) as c:
                    row = c.execute("SELECT COUNT(*), MAX(ts) FROM ticks").fetchone()
                    result["ticks_count"] = row[0] if row else 0
                    result["last_tick_ts"] = row[1] if row else None

                    row2 = c.execute("SELECT COUNT(*), MAX(ts) FROM index_ticks").fetchone()
                    result["index_ticks_count"] = row2[0] if row2 else 0
                    result["last_index_tick_ts"] = row2[1] if row2 else None

                    row3 = c.execute(
                        "SELECT COUNT(*) FROM intraday_trades WHERE trade_date=?", (_today(),)
                    ).fetchone()
                    result["today_trades"] = row3[0] if row3 else 0
            except Exception:
                pass
        else:
            result["ticks_db_mb"] = 0

        # log file status
        log_dir = os.environ.get("FUBON_LOG_DIR", "/fubon-logs")
        log_path = Path(log_dir)
        result["log_dir"] = log_dir
        if log_path.exists():
            log_files = sorted(log_path.glob("dry_run_*.log"), reverse=True)
            if log_files:
                latest = log_files[0]
                result["latest_log_file"] = latest.name
                result["latest_log_date"] = latest.stem.replace("dry_run_", "")
                result["latest_log_lines"] = len(
                    latest.read_text(encoding="utf-8", errors="replace").splitlines()
                )
            else:
                result["latest_log_file"] = None
        else:
            result["latest_log_file"] = None

        return result

    # ── Pre-session log ───────────────────────────────────────────────────────
    @app.get("/pre-session/logs")
    def get_pre_session_logs():
        if _store is None:
            return []
        return _store.get_pre_session_logs(limit=10)

    @app.get("/pre-session/db-size")
    def get_db_size():
        if _store is None:
            return {"size_mb": 0}
        return {"size_mb": round(_store.get_db_size_mb(), 2)}

    # ── Trading params ────────────────────────────────────────────────────────
    @app.get("/trading-params")
    def get_trading_params():
        return _trading_params.copy()

    @app.post("/trading-params")
    def update_trading_params(body: TradingParamsBody):
        if body.max_position_capital <= 0:
            raise HTTPException(status_code=400, detail="max_position_capital must be > 0")
        if body.max_daily_positions <= 0:
            raise HTTPException(status_code=400, detail="max_daily_positions must be > 0")
        _trading_params["max_position_capital"] = body.max_position_capital
        _trading_params["max_daily_positions"] = body.max_daily_positions
        _trading_params["dry_run"] = body.dry_run
        return {"ok": True, "note": "僅更新 dashboard 顯示，不影響運行中的交易引擎", **_trading_params}

    # ── Config ────────────────────────────────────────────────────────────────
    @app.get("/config")
    def get_config():
        config_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
        try:
            import yaml
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            if "fubon" in cfg:
                fubon = dict(cfg["fubon"])
                fubon["password"] = "***"
                fubon["cert_password"] = "***"
                cfg["fubon"] = fubon
            return _sanitize(cfg)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"config 讀取失敗: {e}")

    # ── Logs ──────────────────────────────────────────────────────────────────
    @app.get("/logs/today")
    def get_today_log(lines: int = 200):
        log_dir = os.environ.get("FUBON_LOG_DIR", "/fubon-logs")
        log_file = Path(log_dir) / f"dry_run_{_today()}.log"
        if not log_file.exists():
            return {"lines": [], "file": str(log_file), "exists": False}
        try:
            all_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            return {"lines": all_lines[-lines:], "file": log_file.name, "exists": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/logs/latest")
    def get_latest_log(lines: int = 200):
        log_dir = os.environ.get("FUBON_LOG_DIR", "/fubon-logs")
        log_path = Path(log_dir)
        if not log_path.exists():
            return {"lines": [], "file": None, "exists": False, "date": None}
        log_files = sorted(log_path.glob("dry_run_*.log"), reverse=True)
        if not log_files:
            return {"lines": [], "file": None, "exists": False, "date": None}
        latest = log_files[0]
        log_date = latest.stem.replace("dry_run_", "")
        try:
            all_lines = latest.read_text(encoding="utf-8", errors="replace").splitlines()
            return {
                "lines": all_lines[-lines:],
                "file": latest.name,
                "exists": True,
                "date": log_date,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── SSE: live tick stream ─────────────────────────────────────────────────
    def _query_live(symbols: list[str]) -> dict:
        if not symbols or not Path(_ticks_db).exists():
            return {}
        out = {}
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                rows = c.execute(
                    f"SELECT symbol, price FROM ticks WHERE id IN ("
                    f"SELECT MAX(id) FROM ticks WHERE symbol IN "
                    f"({','.join('?'*len(symbols))}) GROUP BY symbol)",
                    symbols,
                ).fetchall()
                for sym, p in rows:
                    out.setdefault(sym, {})["price"] = p

                rows2 = c.execute(
                    f"""SELECT t.symbol,
                        (SELECT price FROM ticks t2 WHERE t2.symbol=t.symbol ORDER BY id ASC LIMIT 1),
                        MAX(t.price), MIN(t.price), SUM(t.volume)
                        FROM ticks t WHERE t.symbol IN ({','.join('?'*len(symbols))})
                        GROUP BY t.symbol""",
                    symbols,
                ).fetchall()
                for sym, op, hi, lo, vol in rows2:
                    out.setdefault(sym, {}).update(
                        open=op, high=hi, low=lo,
                        vol_lots=int((vol or 0) // 1000),
                    )

                rows3 = c.execute(
                    f"SELECT symbol, bid_vol, ask_vol FROM quotes "
                    f"WHERE symbol IN ({','.join('?'*len(symbols))})",
                    symbols,
                ).fetchall()
                for sym, bv, av in rows3:
                    total = (bv or 0) + (av or 0)
                    out.setdefault(sym, {}).update(
                        bid_vol=bv or 0, ask_vol=av or 0,
                        bid_pct=round(bv / total * 100) if total else 50,
                    )

                idx_row = c.execute(
                    "SELECT price, change_5min, circuit FROM index_ticks "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if idx_row:
                    out["__index__"] = {
                        "price": idx_row[0],
                        "chg5": idx_row[1],
                        "circuit": idx_row[2],
                    }
        except Exception:
            pass
        return out

    @app.get("/stream")
    async def sse_stream(syms: str = ""):
        symbols = [s.strip() for s in syms.split(",") if s.strip()]

        async def event_gen():
            while True:
                data = _query_live(symbols)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.8)

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app
