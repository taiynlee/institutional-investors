import asyncio
import json
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
        # fallback: read from intraday_positions in ticks.db
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
            # mask credentials
            if "fubon" in cfg:
                fubon = dict(cfg["fubon"])
                fubon["password"] = "***"
                fubon["cert_password"] = "***"
                cfg["fubon"] = fubon
            return cfg
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
