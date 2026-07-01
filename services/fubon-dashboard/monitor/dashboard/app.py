import asyncio
import json
import math
import os
import signal
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_TZ_TW = ZoneInfo("Asia/Taipei")


def _now_tw() -> datetime:
    return datetime.now(tz=_TZ_TW)

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class TradingParamsBody(BaseModel):
    # 倉位控制
    max_position_capital: int = 1000000
    max_daily_positions: int = 5
    dry_run: bool = True
    commission_discount: float = 0.28
    # 進場條件
    tick_rise_threshold: int = 4
    tick_window_seconds: int = 60
    max_change_pct: float = 5.0
    check_not_in_position: bool = True
    check_futures_signal: bool = True
    bid_pct_threshold: float = 60.0
    amplitude_min_pct: float = 3.0
    bid_1m_pct_threshold: float = 70.0
    vol_ratio_coefficient: float = 1.3
    # 停損停利
    stop_loss_ticks: int = 4
    take_profit_add_pct: float = 4.0
    # 交易時間
    entry_start_time: str = "09:15"
    latest_dynamic_add_time: str = "13:09"
    force_exit_time: str = "13:20"
    # 當沖篩選
    daytrade_price_min: float = 180.0
    daytrade_price_max: float = 990.0


def _today() -> str:
    return _now_tw().date().isoformat()


def _sanitize(obj):
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return str(obj)
    return obj


def _cleanup_ticks_db(db_path: str, keep_days: int = 30) -> dict:
    """刪除超過 keep_days 的 tick/trade/position 資料並 VACUUM。"""
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    stats: dict = {}
    try:
        with sqlite3.connect(db_path, check_same_thread=False) as c:
            for table, col in [
                ("ticks",             "ts"),
                ("index_ticks",       "ts"),
                ("intraday_trades",   "trade_date"),
                ("intraday_positions","trade_date"),
            ]:
                try:
                    cur = c.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
                    stats[table] = cur.rowcount
                except Exception:
                    stats[table] = -1
            c.execute("VACUUM")
        stats["cutoff"] = cutoff
        stats["ok"] = True
    except Exception as e:
        stats["ok"] = False
        stats["error"] = str(e)
    return stats


def create_app(
    positions: dict = None,
    daily_tracker=None,
    daily_store=None,
    max_position_capital: int = 1_000_000,
    max_daily_positions: int = 5,
    dry_run: bool = True,
    ticks_db: str = "/fubon-data/ticks.db",
    trading_engine=None,
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
    _engine = trading_engine
    _PARAM_KEYS = [
        "dry_run", "max_position_capital", "max_daily_positions", "commission_discount",
        "tick_rise_threshold", "tick_window_seconds", "max_change_pct",
        "check_not_in_position", "check_futures_signal", "bid_pct_threshold", "amplitude_min_pct",
        "bid_1m_pct_threshold", "vol_ratio_coefficient",
        "stop_loss_ticks", "take_profit_add_pct",
        "entry_start_time", "latest_dynamic_add_time", "force_exit_time",
        "daytrade_price_min", "daytrade_price_max",
    ]
    _trading_params: dict = {
        "dry_run": dry_run,
        "max_position_capital": max_position_capital,
        "max_daily_positions": max_daily_positions,
        "commission_discount": 0.28,
        "tick_rise_threshold": 4,
        "tick_window_seconds": 60,
        "max_change_pct": 5.0,
        "check_not_in_position": True,
        "check_futures_signal": True,
        "bid_pct_threshold": 60.0,
        "amplitude_min_pct": 3.0,
        "bid_1m_pct_threshold": 70.0,
        "vol_ratio_coefficient": 1.3,
        "stop_loss_ticks": 4,
        "take_profit_add_pct": 4.0,
        "entry_start_time": "09:15",
        "latest_dynamic_add_time": "13:09",
        "force_exit_time": "13:20",
        "daytrade_price_min": 180.0,
        "daytrade_price_max": 990.0,
    }

    def _cast_param(k: str, v: str):
        """字串 → 正確型別"""
        if k in ("dry_run", "check_not_in_position", "check_futures_signal"):
            return str(v).lower() in ("true", "1", "yes")
        if k in ("max_position_capital", "max_daily_positions",
                 "tick_rise_threshold", "tick_window_seconds", "stop_loss_ticks"):
            return int(v)
        if k in ("commission_discount", "take_profit_add_pct", "max_change_pct",
                 "daytrade_price_min", "daytrade_price_max",
                 "bid_pct_threshold", "amplitude_min_pct", "bid_1m_pct_threshold",
                 "vol_ratio_coefficient"):
            return float(v)
        return str(v)  # time strings

    def _sync_to_ticks_db(kv: dict):
        """把最新設定同步到 ticks.db，讓 engine _gs() 熱重載用"""
        try:
            with sqlite3.connect(_ticks_db, check_same_thread=False) as c:
                c.execute("""CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
                for k, v in kv.items():
                    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                              (k, str(v)))
        except Exception:
            pass

    def _load_trading_params_from_pg():
        """從 PG backend 載入設定；失敗時 retry 3次，最終 fallback SQLite"""
        import httpx as _httpx, time as _time
        for attempt in range(3):
            try:
                r = _httpx.get(f"{_BACKEND}/api/trading-settings", timeout=5)
                if r.status_code == 200:
                    for k, v in r.json().items():
                        if k in _PARAM_KEYS:
                            _trading_params[k] = _cast_param(k, v)
                    _sync_to_ticks_db({k: _trading_params[k] for k in _PARAM_KEYS})
                    return
            except Exception:
                pass
            if attempt < 2:
                _time.sleep(3)
        # fallback: SQLite
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                rows = c.execute(
                    f"SELECT key, value FROM settings WHERE key IN "
                    f"({','.join('?' * len(_PARAM_KEYS))})", _PARAM_KEYS
                ).fetchall()
            for k, v in rows:
                if k in _PARAM_KEYS:
                    _trading_params[k] = _cast_param(k, v)
        except Exception:
            pass

    _load_trading_params_from_pg()

    # ── WebSocket push ────────────────────────────────────────────────────────
    _ws_clients: set = set()

    async def _push_state():
        """每秒把引擎狀態推給所有已連線的 WebSocket 客戶端。"""
        while True:
            await asyncio.sleep(1)
            if not _ws_clients:
                continue
            try:
                _max_daily = _trading_params.get("max_daily_positions", 5)
                if _engine is not None:
                    state = _engine.get_state()
                    if state.get("status") == "running":
                        pnl = _engine.get_pnl_summary()
                        positions = _sanitize(_engine.get_positions())
                    else:
                        pnl = {"max_daily": _max_daily}
                        positions = []
                else:
                    state = {"status": "unavailable"}
                    pnl = {"max_daily": _max_daily}
                    positions = []
                msg = json.dumps(
                    {"type": "state", **state,
                     "dry_run": _trading_params.get("dry_run", True),
                     "tick_window_seconds": _trading_params.get("tick_window_seconds", 60),
                     "tick_rise_threshold": _trading_params.get("tick_rise_threshold", 4),
                     "bid_pct_threshold": _trading_params.get("bid_pct_threshold", 60.0),
                     "amplitude_min_pct": _trading_params.get("amplitude_min_pct", 3.0),
                     "bid_1m_pct_threshold": _trading_params.get("bid_1m_pct_threshold", 70.0),
                     "vol_ratio_coefficient": _trading_params.get("vol_ratio_coefficient", 1.3),
                     "entry_start_time": _trading_params.get("entry_start_time", "09:15"),
                     "pnl": pnl, "positions": positions},
                    ensure_ascii=False, default=str,
                )
                dead: set = set()
                for ws in list(_ws_clients):
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.add(ws)
                _ws_clients.difference_update(dead)
            except Exception:
                pass

    @app.websocket("/ws/stream")
    async def ws_stream(ws: WebSocket):
        await ws.accept()
        _ws_clients.add(ws)
        try:
            while True:
                try:
                    await asyncio.wait_for(ws.receive_text(), timeout=30)
                except asyncio.TimeoutError:
                    try:
                        await ws.send_text('{"ping":true}')
                    except Exception:
                        break
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            _ws_clients.discard(ws)

    async def _daily_cleanup_loop():
        """每天 20:00 台灣時間執行一次清理，保留最近 30 天資料。"""
        while True:
            now = _now_tw()
            next_run = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            await asyncio.sleep((next_run - _now_tw()).total_seconds())
            if Path(_ticks_db).exists():
                _cleanup_ticks_db(_ticks_db)

    @app.on_event("startup")
    async def _startup_tasks():
        asyncio.create_task(_daily_cleanup_loop())
        asyncio.create_task(_push_state())

    @app.post("/admin/cleanup-ticks")
    def manual_cleanup_ticks(keep_days: int = 30):
        """手動觸發 ticks.db 清理（預設保留30天）。"""
        if not Path(_ticks_db).exists():
            raise HTTPException(status_code=404, detail="ticks.db 不存在")
        return _cleanup_ticks_db(_ticks_db, keep_days)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # ── Positions ─────────────────────────────────────────────────────────────
    @app.get("/positions")
    def get_positions():
        if _engine is not None and _engine.om is not None:
            return _engine.get_positions()
        if _positions:
            return [
                {
                    "symbol": sym,
                    "lots": pos.lots,
                    "entry_price": pos.entry_price,
                    "stop_loss": pos.stop_loss,
                    "take_profit": getattr(pos, "take_profit", None),
                }
                for sym, pos in _positions.items()
            ]
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                c.row_factory = sqlite3.Row
                rows = c.execute(
                    "SELECT symbol, entry_price, lots, stop_loss, take_profit FROM intraday_positions "
                    "WHERE trade_date=? AND is_paper=0",
                    (_today(),),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── PnL / Status ──────────────────────────────────────────────────────────
    @app.get("/pnl")
    def get_pnl():
        if _engine is not None and _engine.dt is not None:
            return {"total_pnl": _engine.dt.total_pnl}
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
        if _engine is not None and _engine.dt is not None:
            return {"total_pnl": _engine.dt.total_pnl, "trade_count": _engine.dt.trade_count}
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

    # ── Delete trade ──────────────────────────────────────────────────────────
    @app.delete("/delete-trade")
    def delete_trade(trade_date: str, symbol: str):
        try:
            with sqlite3.connect(_ticks_db, check_same_thread=False) as c:
                c.execute(
                    "DELETE FROM intraday_trades WHERE trade_date=? AND symbol=? AND is_paper=0",
                    (trade_date, symbol),
                )
            return {"ok": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── Trade history (multi-day) ─────────────────────────────────────────────
    @app.get("/trade-history")
    def get_trade_history(limit: int = 500):
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                c.row_factory = sqlite3.Row
                rows = c.execute("""
                    SELECT
                        t.trade_date,
                        t.symbol,
                        '' AS name,
                        MAX(t.dry_run)       AS dry_run,
                        ROUND(SUM(t.pnl), 0) AS pnl,
                        COUNT(*)             AS trade_count,
                        SUM(t.lots)          AS total_lots,
                        ROUND(SUM(CASE WHEN COALESCE(t.entry_price,0)>0 THEN t.entry_price*t.lots ELSE 0 END)/NULLIF(SUM(CASE WHEN COALESCE(t.entry_price,0)>0 THEN t.lots ELSE 0 END),0), 1) AS avg_entry,
                        ROUND(SUM(CASE WHEN COALESCE(t.exit_price,0)>0  THEN t.exit_price *t.lots ELSE 0 END)/NULLIF(SUM(CASE WHEN COALESCE(t.exit_price,0)>0  THEN t.lots ELSE 0 END),0), 1) AS avg_exit,
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
                    WHERE t.is_paper = 0
                    GROUP BY t.trade_date, t.symbol
                    ORDER BY t.trade_date DESC, t.symbol
                    LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── Daytrade list — 全部改從 PG backend 讀取 ─────────────────────────────
    _BACKEND = "http://localhost:8000"

    @app.get("/daytrade-list")
    def get_daytrade_list(date_str: str = ""):
        import httpx as _httpx
        params = {"date_str": date_str} if date_str else {}
        try:
            r = _httpx.get(f"{_BACKEND}/api/daytrade/list", params=params, timeout=10)
            return r.json()
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.post("/daytrade-list/sync")
    def sync_daytrade_list(date_str: str = ""):
        """21:05 由 backend job8 觸發：
        pool live-filter ∪ 策略A ∪ 策略B ∪ watchlist-a(active) − 退場止損 → PG daytrade_candidate
        """
        from datetime import date as _date, timedelta
        import httpx as _httpx

        base = _date.fromisoformat(date_str) if date_str else _date.today()
        nxt = base + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        target_date = nxt.isoformat()

        price_min = _trading_params.get("daytrade_price_min", 200.0)
        price_max = _trading_params.get("daytrade_price_max", 990.0)
        selected: set[str] = set()
        # snapshot: {code: {ref_close, ref_close_date, avg_vol5_lot, chip_count, above_ma20}}
        snapshots: dict = {}

        # 1. Pool live-filter（above_ma20 + vol_ok + chip_count≥2）
        live_count = 0
        try:
            r = _httpx.get(f"{_BACKEND}/api/daytrade/list",
                           params={"live": "true", "source": "pool"}, timeout=30)
            if r.status_code == 200:
                stocks = r.json().get("stocks", [])
                live_count = len(stocks)
                for s in stocks:
                    c = s["stock_id"]
                    selected.add(c)
                    snapshots[c] = {
                        "ref_close": s.get("prev_close"),
                        "ref_close_date": s.get("prev_close_date"),
                        "avg_vol5_lot": s.get("avg_vol5"),
                        "chip_count": s.get("chip_count"),
                        "above_ma20": s.get("above_ma20"),
                    }
        except Exception:
            pass

        # 2. 策略A + 策略B
        score_count = 0
        try:
            for ep in (f"{_BACKEND}/api/score-a", f"{_BACKEND}/api/score-b"):
                r = _httpx.get(ep, timeout=10)
                if r.status_code == 200:
                    codes = [row["code"] for row in r.json() if "code" in row]
                    score_count += len(codes)
                    selected.update(codes)
        except Exception:
            pass

        # 2b. 策略C 滿分100分
        try:
            r = _httpx.get(f"{_BACKEND}/api/score-c", timeout=15)
            if r.status_code == 200:
                codes = [row["code"] for row in r.json() if row.get("score_c") == 100 and "code" in row]
                score_count += len(codes)
                selected.update(codes)
        except Exception:
            pass

        # 3. WatchlistA（tracking / triggered / entered）
        watch_count = 0
        try:
            r = _httpx.get(f"{_BACKEND}/api/watchlist-a", timeout=10)
            if r.status_code == 200:
                active = {"tracking", "triggered", "entered"}
                codes = [row["code"] for row in r.json() if row.get("status") in active]
                watch_count = len(codes)
                selected.update(codes)
        except Exception:
            pass

        # 4. 扣除退場止損名單
        exit_count = 0
        try:
            r = _httpx.get(f"{_BACKEND}/api/exit-alerts", timeout=10)
            if r.status_code == 200:
                exit_codes = {row["code"] for row in r.json()}
                exit_count = len(exit_codes & selected)
                selected -= exit_codes
                for c in exit_codes:
                    snapshots.pop(c, None)
        except Exception:
            pass

        # 5. 股價範圍過濾（批次取昨收，過濾 < price_min 或 > price_max）
        # 同時補全非 pool 股票的 ref_close snapshot
        price_excluded = 0
        if selected:
            try:
                r = _httpx.get(f"{_BACKEND}/api/stocks/latest-prices",
                               params={"codes": ",".join(selected)}, timeout=15)
                if r.status_code == 200:
                    prices = r.json()
                    # 補 ref_close 給 score-a/b / watchlist-a（pool 已有完整 snapshot）
                    for c, close in prices.items():
                        if c not in snapshots:
                            snapshots[c] = {"ref_close": close}
                        elif snapshots[c].get("ref_close") is None:
                            snapshots[c]["ref_close"] = close
                    before = len(selected)
                    selected = {
                        c for c in selected
                        if price_min <= prices.get(c, price_min) <= price_max
                    }
                    price_excluded = before - len(selected)
                    # 清除被排除的 snapshot
                    for c in list(snapshots):
                        if c not in selected:
                            del snapshots[c]
            except Exception:
                pass

        # 5b. 處置股票過濾（TWT85U 全部排除，避免分批競價量爆表且禁止當沖）
        disposal_excluded = 0
        try:
            import urllib.request as _ureq_d, json as _json_d
            _req_d = _ureq_d.Request(
                "https://www.twse.com.tw/exchangeReport/TWT85U?response=json",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.twse.com.tw/"},
            )
            with _ureq_d.urlopen(_req_d, timeout=10) as _resp_d:
                _twt_data = _json_d.loads(_resp_d.read().decode("utf-8"))
            _disposal_set = {row[0].strip() for row in _twt_data.get("data", []) if row and row[0].strip()}
            _before_d = len(selected)
            selected -= _disposal_set
            for _c in list(snapshots):
                if _c not in selected:
                    del snapshots[_c]
            disposal_excluded = _before_d - len(selected)
            if disposal_excluded > 0:
                import logging as _log_d
                _log_d.getLogger(__name__).info(
                    "sync_daytrade_list: 排除處置股 %d 檔", disposal_excluded
                )
        except Exception as _e_d:
            import logging as _log_d
            _log_d.getLogger(__name__).warning(
                "sync_daytrade_list: 處置股過濾失敗（略過）: %s", _e_d
            )

        # 寫入 PG（含快照）
        codes_list = list(selected)
        try:
            _httpx.post(f"{_BACKEND}/api/daytrade/sync",
                        json={"date": target_date, "codes": codes_list, "snapshots": snapshots},
                        timeout=10)
        except Exception:
            pass

        return {
            "ok": True, "date": target_date, "count": len(codes_list),
            "live_filter": live_count, "score_ab": score_count,
            "watchlist_a": watch_count, "excluded_exit": exit_count,
            "excluded_price": price_excluded, "excluded_disposal": disposal_excluded,
            "price_range": [price_min, price_max],
        }

    @app.post("/sync-pool")
    def sync_pool_from_pg():
        """確認 PG stock_pool 可存取（SQLite 已廢棄）"""
        import httpx as _httpx
        try:
            r = _httpx.get(f"{_BACKEND}/api/pool", timeout=10)
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"PG pool API 回傳 {r.status_code}")
            return {"ok": True, "synced": len(r.json())}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/daytrade-list/live")
    def get_daytrade_list_live():
        """PG-backed: 取最新 daytrade candidates，套用 above_ma20 & vol_ok & chip_count>=2"""
        import httpx as _httpx
        try:
            r = _httpx.get(f"{_BACKEND}/api/daytrade/list", params={"live": "true"}, timeout=10)
            data = r.json()
            stocks = data.get("stocks", [])
            return {"date": data.get("date"), "count": len(stocks), "stocks": stocks}
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))

    @app.get("/daytrade-list/dates")
    def get_daytrade_dates():
        import httpx as _httpx
        try:
            r = _httpx.get(f"{_BACKEND}/api/daytrade/dates", timeout=10)
            return r.json()
        except Exception:
            return []

    # ── Futures snapshot ─────────────────────────────────────────────────────
    @app.get("/futures-snapshot")
    def get_futures_snapshot(syms: str = ""):
        """個股期貨即時價格。優先從引擎 WebSocket 快取讀取，引擎未啟動時用 REST fallback。"""
        symbols = [s.strip() for s in syms.split(",") if s.strip()] if syms else []
        result: dict = {"ok": False, "ts": datetime.now().isoformat(), "data": {}, "error": None}

        # ── 優先：用引擎已建好的 futures_sym_map + futures_signals 快取 ──────────
        if _engine is not None and _engine.futures_sym_map:
            fsmap = _engine.futures_sym_map
            fsig  = _engine.futures_signals
            for sym in symbols:
                if sym not in fsmap:
                    continue
                sig = fsig.get(sym)
                if sig is None:
                    continue
                state = getattr(sig, "_state", None)
                if state is None:
                    continue
                price = getattr(state, "futures_price", None)
                chg_pct = getattr(state, "futures_change_pct", None)
                if price and price > 0:
                    result["data"][sym] = {
                        "price": float(price),
                        "change": 0.0,        # 暫無 change pts，用 chg_pct
                        "change_pct": round(float(chg_pct or 0), 2),
                        "futures_code": fsmap[sym],
                    }
            result["ok"] = True
            if result["data"] or not symbols:
                return result
            # map 有但 tick 尚未收到 → fallback 到 REST

        # ── Fallback：用 tickers API 建 {underlyingSymbol → 近月合約+price} ──────
        # products 回傳泛型代碼（FZF），ticker/quote 不支援；tickers 才有實際近月代碼。
        try:
            sdk = (_engine.sdk if _engine is not None else None)
            if sdk is None:
                result["error"] = "引擎未啟動，無法查期貨"
                return result
            rc_f = sdk.marketdata.rest_client.futopt

            # _futures_price_cache: {stock_id → {price, change_pct, futures_code}}
            # 掛在 _engine 上，30 秒 TTL 或缺 symbol 時觸發重建
            import time as _time
            _cache = getattr(_engine, "_futures_price_cache", {}) if _engine else {}
            _cache_ts = getattr(_engine, "_futures_cache_ts", 0.0) if _engine else 0.0
            _cache_stale = (_time.time() - _cache_ts) > 30
            need_rebuild = _cache_stale or (any(sym not in _cache for sym in symbols) if symbols else not _cache)

            if need_rebuild and _engine is not None:
                try:
                    from collections import defaultdict as _dd
                    import datetime as _dt

                    # Step1: products API → {productCode → [underlyingSymbol]}
                    _presp = rc_f.intraday.products(type="FUTURE")
                    _plist = (_presp if isinstance(_presp, list)
                              else _presp.get("data", []) if isinstance(_presp, dict) else [])
                    prod_to_und: dict = {}  # productCode → underlyingSymbol (stock_id)
                    und_to_prod: dict = {}  # underlyingSymbol → (productCode, contractSize, priority)
                    for _p in _plist:
                        _u = str(_p.get("underlyingSymbol", "") if isinstance(_p, dict)
                                 else getattr(_p, "underlyingSymbol", "") or "")
                        _s = str(_p.get("symbol", "") if isinstance(_p, dict)
                                 else getattr(_p, "symbol", "") or "")
                        _c = int((_p.get("contractSize") or 0) if isinstance(_p, dict)
                                 else (getattr(_p, "contractSize", 0) or 0))
                        if _u and _s:
                            # Prefer codes NOT ending with digit (e.g. FZF > FZ1, KDF > KD1)
                            # because digit-suffix codes are special near-month aliases,
                            # not the base product code used in actual contract symbols.
                            _not_digit = 1 if not _s[-1:].isdigit() else 0
                            _priority = (_not_digit, _c)  # prefer non-digit-suffix, then larger size
                            if _u not in und_to_prod or _priority > und_to_prod[_u][2]:
                                und_to_prod[_u] = (_s, _c, _priority)
                    # und_to_prod[stock_id] = (productCode, contractSize, priority)
                    prod_to_und = {v[0]: k for k, v in und_to_prod.items()}

                    # Step2: tickers API → all actual contracts with endDate + referencePrice
                    _tresp = rc_f.intraday.tickers(type="FUTURE")
                    _tlist = (_tresp if isinstance(_tresp, list)
                              else _tresp.get("data", []) if isinstance(_tresp, dict) else [])
                    today_str = _now_tw().date().isoformat()

                    # Group by product code prefix: FZFG6 → prefix FZF
                    # Find near-month (earliest endDate still >= today) for each prefix
                    prefix_contracts: dict = _dd(list)
                    for _t in _tlist:
                        _tsym = str(_t.get("symbol", "") if isinstance(_t, dict)
                                    else getattr(_t, "symbol", "") or "")
                        _end  = str(_t.get("endDate", "") if isinstance(_t, dict)
                                    else getattr(_t, "endDate", "") or "")
                        _ref  = (_t.get("referencePrice") if isinstance(_t, dict)
                                 else getattr(_t, "referencePrice", None))
                        if _tsym and _end:
                            # extract product code = all chars except last 2 (month+year)
                            _prefix = _tsym[:-2] if len(_tsym) > 2 else _tsym
                            prefix_contracts[_prefix].append((_end, _tsym, _ref))

                    # Build new cache
                    new_sym_map: dict = {}  # stock_id → actual_symbol
                    all_syms = list(_engine.futures_signals.keys()) if _engine.futures_signals else symbols
                    for _stk in all_syms:
                        if _stk not in und_to_prod:
                            continue
                        prod_code = und_to_prod[_stk][0]  # e.g., FZF
                        candidates = prefix_contracts.get(prod_code, [])
                        if not candidates:
                            continue
                        candidates.sort()
                        near = next(((e, s, r) for e, s, r in candidates if e >= today_str), None)
                        if near is None:
                            near = candidates[-1]
                        _end, _actual_sym, _ref = near
                        new_sym_map[_stk] = _actual_sym

                    if new_sym_map:
                        _engine.futures_sym_map = new_sym_map

                    # Get real-time price via quote API for each near-month symbol
                    new_cache: dict = {}
                    for _stk, _actual_sym in new_sym_map.items():
                        try:
                            _q = rc_f.intraday.quote(symbol=_actual_sym)
                            if _q is None:
                                continue
                            _lp = (_q.get("lastPrice") or _q.get("closePrice") or
                                   _q.get("previousClose")) if isinstance(_q, dict) \
                                  else (getattr(_q, "lastPrice", None) or getattr(_q, "previousClose", None))
                            _ref = (_q.get("previousClose") or _q.get("referencePrice")) if isinstance(_q, dict) \
                                   else (getattr(_q, "previousClose", None) or getattr(_q, "referencePrice", None))
                            _chg = (_q.get("change") or 0) if isinstance(_q, dict) \
                                   else (getattr(_q, "change", 0) or 0)
                            _chg_pct = (_q.get("changePercent") or 0) if isinstance(_q, dict) \
                                       else (getattr(_q, "changePercent", 0) or 0)
                            if _lp is not None and float(_lp) > 0:
                                new_cache[_stk] = {
                                    "price": float(_lp), "change": float(_chg),
                                    "change_pct": round(float(_chg_pct), 2),
                                    "futures_code": _actual_sym,
                                }
                        except Exception:
                            # fallback to referencePrice from tickers if quote fails
                            for _e2, _s2, _r2 in prefix_contracts.get(und_to_prod.get(_stk, ('',))[0], []):
                                if _s2 == _actual_sym and _r2 is not None and float(_r2) > 0:
                                    new_cache[_stk] = {
                                        "price": float(_r2), "change": 0.0,
                                        "change_pct": 0.0, "futures_code": _actual_sym,
                                    }
                                    break

                    if new_cache:
                        _engine._futures_price_cache = new_cache  # type: ignore
                        _engine._futures_cache_ts = _time.time()  # type: ignore
                        _cache = new_cache
                except Exception as _e:
                    result["error"] = f"tickers rebuild失敗: {_e}"

            for sym in symbols:
                entry = _cache.get(sym)
                if entry:
                    result["data"][sym] = entry
            result["ok"] = True
        except Exception as e:
            result["error"] = str(e)
        return result

    # ── Health check (19-item, port of premarket_check.py) ────────────────────
    @app.post("/health-check/run")
    def run_health_check(mode: str = "quick"):
        """18-item 系統健診。mode=quick 略過 SDK 呼叫；mode=full 執行所有項目。"""
        import datetime as dt
        ts = datetime.now().isoformat()
        items: list = []
        no_sdk = (mode != "full")

        def add(item_id, name, ok, warn=False, detail="", data_source="", logic=""):
            items.append({
                "item_id": item_id, "name": name, "ok": ok, "warn": warn,
                "detail": detail, "data_source": data_source, "logic": logic,
            })

        # 01: mode
        dry = _trading_params.get("dry_run", True)
        add(1, "模式標籤", True, detail="DRY RUN 模擬模式" if dry else "LIVE 實單模式",
            data_source="GET /trading-params", logic="dry_run field")

        # 02: PnL
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                row = c.execute(
                    "SELECT COALESCE(MAX(cumulative_pnl),0), COUNT(*) FROM intraday_trades "
                    "WHERE trade_date=? AND is_paper=0", (_today(),)
                ).fetchone()
                pnl, tc = (row[0], row[1]) if row else (0, 0)
            add(2, "損益金額", True, detail=f"今日累積 {pnl:+.0f} 元，{tc} 筆",
                data_source="ticks.db/intraday_trades", logic="MAX(cumulative_pnl)")
        except Exception as e:
            _no_tbl = "no such table" in str(e) or "unable to open database file" in str(e)
            if _no_tbl:
                add(2, "損益金額", True, warn=True, detail="引擎尚未啟動（盤前正常）",
                    data_source="ticks.db/intraday_trades")
            else:
                add(2, "損益金額", False, detail=f"讀取失敗: {e}", data_source="ticks.db/intraday_trades")

        # 03: positions
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                row = c.execute(
                    "SELECT COUNT(*) FROM intraday_positions WHERE trade_date=? AND is_paper=0",
                    (_today(),)
                ).fetchone()
                pc = row[0] if row else 0
            add(3, "持倉數", True, detail=f"{pc} 檔持倉", data_source="ticks.db/intraday_positions")
        except Exception as e:
            _no_tbl = "no such table" in str(e) or "unable to open database file" in str(e)
            if _no_tbl:
                add(3, "持倉數", True, warn=True, detail="引擎尚未啟動（盤前正常）",
                    data_source="ticks.db/intraday_positions")
            else:
                add(3, "持倉數", False, detail=f"讀取失敗: {e}", data_source="ticks.db/intraday_positions")

        # 04-05: index
        idx_price = idx_day_pct = None
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                row = c.execute(
                    "SELECT price, chg_day_pct FROM index_ticks ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    idx_price, idx_day_pct = row[0], row[1]
        except Exception:
            pass
        mkt = idx_price is not None and idx_price > 0
        add(4, "加權指數", True, warn=not mkt,
            detail=f"{idx_price:,.0f} 點" if mkt else "盤前/休市 - 無 tick 屬正常",
            data_source="ticks.db/index_ticks", logic="最新一筆 price")
        add(5, "指數日漲幅%", True, warn=not mkt,
            detail=f"{idx_day_pct:+.2f}%" if idx_day_pct is not None else "尚無資料",
            data_source="ticks.db/index_ticks", logic="chg_day_pct 欄位")

        # 07: engine direct status
        if _engine is not None:
            eng_st = _engine.get_state()
            eng_status_val = eng_st.get("status", "unknown")
            eng_running_now = eng_status_val == "running"
            eng_err = eng_st.get("error")
            add(7, "引擎直接狀態", eng_running_now or eng_status_val == "stopped",
                warn=eng_status_val in ("error", "unknown"),
                detail=f"status={eng_status_val}" + (f"  錯誤={eng_err}" if eng_err else ""),
                data_source="engine._state", logic="running=ok / stopped=ok / error=warn")
        else:
            add(7, "引擎直接狀態", False, warn=True,
                detail="trading_engine 未初始化", data_source="engine object")

        # 07b: DailyScheduler status
        # scheduler thread is a daemon started in main.py; we detect via engine session_date
        sched_detail = "排程中（08:30 自動啟動）"
        add("7b", "DailyScheduler", True,
            detail=sched_detail if _engine is None else
                   f"今日已跑={getattr(_engine, 'session_date', None) or '未啟動過'}",
            data_source="engine.session_date", logic="session_date 有值=曾啟動過")

        # 07c: 系統配置（DB trading-params）
        try:
            import urllib.request as _ur, json as _cj
            with _ur.urlopen("http://localhost:8090/trading-params", timeout=3) as _r:
                _tp = _cj.loads(_r.read())
            _cfg_db_ok = _tp.get("dry_run") is not None
            add("7c", "系統配置(DB)", _cfg_db_ok,
                warn=not _cfg_db_ok,
                detail=f"trading-params DB 讀取正常，dry_run={_tp.get('dry_run')}" if _cfg_db_ok else "dry_run 欄位缺失",
                data_source="GET /trading-params", logic="dry_run 欄位存在即 ok")
        except Exception as _e:
            add("7c", "系統配置(DB)", False, warn=True,
                detail=f"DB 配置讀取失敗: {_e}",
                data_source="GET /trading-params")

        # 07d: LINE 通知設定
        _line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        _line_target = os.environ.get("LINE_NOTIFY_TARGET", "")
        _line_ok = bool(_line_token) and bool(_line_target)
        add("7d", "LINE 通知設定", _line_ok,
            warn=not _line_ok,
            detail=("token ✓  target ✓" if _line_ok
                    else f"缺少 {'token' if not _line_token else 'target'}"),
            data_source="環境變數 LINE_CHANNEL_ACCESS_TOKEN / LINE_NOTIFY_TARGET",
            logic="兩個環境變數都有值才 ok")

        # 08: engine tick flow (actual data arriving from SDK)
        engine_ok = False
        engine_detail = "尚無 tick，引擎未啟動或休市"
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                row = c.execute("SELECT MAX(ts), COUNT(*) FROM ticks WHERE ts >= date('now','-1 day')").fetchone()
                if row and row[0]:
                    last_ts_str = row[0]
                    try:
                        last_dt = datetime.fromisoformat(last_ts_str)
                    except ValueError:
                        last_dt = datetime.strptime(last_ts_str, "%Y-%m-%d %H:%M:%S")
                    age_min = (datetime.now() - last_dt).total_seconds() / 60
                    cnt = row[1] or 0
                    if age_min < 15:
                        engine_ok = True
                        engine_detail = f"tick 持續流入（最後 {age_min:.0f} 分前，今日 {cnt:,} 筆）"
                    elif age_min < 60:
                        engine_detail = f"最後 tick {age_min:.0f} 分前（今日 {cnt:,} 筆）— 收盤後正常"
                    else:
                        engine_detail = f"最後 tick {age_min:.0f} 分前（今日 {cnt:,} 筆）— 引擎未連線"
        except Exception as e:
            if "no such table" in str(e) or "unable to open database file" in str(e):
                engine_detail = "引擎尚未啟動（盤前正常）"
            else:
                engine_detail = f"ticks.db 讀取失敗: {e}"
        add(8, "tick 資料流", engine_ok, warn=not engine_ok,
            detail=engine_detail, data_source="ticks.db/ticks",
            logic="最後 tick < 15分 → 資料流正常（盤中）")

        # 09-19: per-stock checks using first symbol from daytrade_list (PG-backed)
        sample_sym = None
        prev_close = None
        try:
            import httpx as _httpx
            _dt_r = _httpx.get(f"{_BACKEND}/api/daytrade/list", timeout=5)
            if _dt_r.status_code == 200:
                _dt_stocks = _dt_r.json().get("stocks", [])
                if _dt_stocks:
                    sample_sym = _dt_stocks[0].get("stock_id")
                    prev_close = _dt_stocks[0].get("prev_close")
        except Exception:
            pass

        if sample_sym:
            # 09: prev close
            pc_ok = prev_close is not None and prev_close > 0
            add(9, f"昨收 ({sample_sym})", pc_ok, warn=not pc_ok,
                detail=str(prev_close) if pc_ok else "無昨收資料",
                data_source="daily.db/daily_price", logic="最新一筆 close")

            # 10-13: from ticks.db
            latest_price = quote_ratio = None
            try:
                with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                     check_same_thread=False) as c:
                    row = c.execute(
                        "SELECT price FROM ticks WHERE id=(SELECT MAX(id) FROM ticks WHERE symbol=?)",
                        (sample_sym,)
                    ).fetchone()
                    if row:
                        latest_price = row[0]
                    row2 = c.execute(
                        "SELECT bid_vol, ask_vol FROM quotes WHERE symbol=?", (sample_sym,)
                    ).fetchone()
                    if row2 and row2[0] is not None and row2[1] is not None:
                        tot = (row2[0] or 0) + (row2[1] or 0)
                        quote_ratio = round(row2[0] / tot * 100) if tot else 50
            except Exception:
                pass

            tick_ok = latest_price is not None
            add(10, f"現價 ({sample_sym})", tick_ok, warn=not tick_ok,
                detail=str(latest_price) if tick_ok else "盤前/休市 - 無 tick",
                data_source="ticks.db/ticks", logic="MAX(id) 最新一筆")
            if tick_ok and prev_close:
                chg = round(float(latest_price) - float(prev_close), 2)
                chg_pct = round(chg / float(prev_close) * 100, 2)
                add(11, f"漲跌 ({sample_sym})", True, detail=f"{chg:+.2f}",
                    data_source="ticks - daily_price", logic="latest_price - prev_close")
                add(12, f"漲跌% ({sample_sym})", True, detail=f"{chg_pct:+.2f}%",
                    data_source="ticks - daily_price", logic="(price - prev_close) / prev_close")
            else:
                add(11, f"漲跌 ({sample_sym})", False, warn=True, detail="缺昨收或現價",
                    data_source="ticks - daily_price")
                add(12, f"漲跌% ({sample_sym})", False, warn=True, detail="缺昨收或現價",
                    data_source="ticks - daily_price")
            q_ok = quote_ratio is not None
            add(13, f"委買比 ({sample_sym})", q_ok, warn=not q_ok,
                detail=f"bid {quote_ratio}% / ask {100-quote_ratio}%" if q_ok else "尚無委託資料",
                data_source="ticks.db/quotes", logic="bid_vol / (bid_vol + ask_vol)")

            # 14-18: SDK required
            if no_sdk:
                for num, nm in [(14,"期貨價"),(15,"期現差")]:
                    add(num, f"{nm} ({sample_sym})", True, warn=True,
                        detail="快速健診略過 SDK 查詢", data_source="fubon_neo SDK (略過)",
                        logic="完整健診才執行")
                for num, nm in [(16,"Open"),(17,"High"),(18,"Low")]:
                    add(num, f"{nm} ({sample_sym})", True, warn=True,
                        detail="快速健診略過 SDK 查詢", data_source="fubon_neo SDK (略過)")
            else:
                fut_price = None
                try:
                    import yaml
                    config_path = os.environ.get("FUBON_CONFIG", "/home/tommy0322/fubon-config/config.yaml")
                    with open(config_path, encoding="utf-8") as f:
                        cfg_y = yaml.safe_load(f)
                    fc = cfg_y["fubon"]
                    from fubon_neo.sdk import FubonSDK, Mode
                    sdk = FubonSDK()
                    sdk_r = sdk.login(fc["id"], fc["password"], fc["cert_path"], fc["cert_password"])
                    if sdk_r.is_success:
                        sdk.init_realtime(Mode.Speed)
                        rc_f = sdk.marketdata.rest_client.futopt
                        rc_s = sdk.marketdata.rest_client.stock
                        mc = "FGHJKMNQUVXZ"
                        near = mc[dt.date.today().month-1] + str(dt.date.today().year)[-1]
                        try:
                            t = rc_f.intraday.ticker(symbol=f"{sample_sym}{near}")
                            if t is not None:
                                p = getattr(t, "lastPrice", None) or getattr(t, "close", None)
                                if isinstance(t, dict):
                                    p = t.get("lastPrice") or t.get("close")
                                if p:
                                    fut_price = float(p)
                        except Exception:
                            pass
                        add(14, f"期貨價 ({sample_sym})", fut_price is not None,
                            warn=fut_price is None,
                            detail=str(fut_price) if fut_price else "無個股期資料",
                            data_source=f"fubon_neo SDK rc_futopt.intraday.ticker({sample_sym}{near})")
                        if fut_price and tick_ok:
                            sp = round(fut_price - float(latest_price), 2)
                            add(15, f"期現差 ({sample_sym})", True, detail=f"{sp:+.2f}",
                                data_source="futures_price - latest_price")
                        else:
                            add(15, f"期現差 ({sample_sym})", False, warn=True,
                                detail="缺期貨或現價", data_source="futures_price - latest_price")
                        # OHLC
                        try:
                            candles = rc_s.intraday.candles(symbol=sample_sym)
                            data = candles if isinstance(candles, list) else \
                                   (candles.get("data", []) if isinstance(candles, dict) else [])
                            if data:
                                def _g(item, k):
                                    return item.get(k) if isinstance(item, dict) else getattr(item, k, None)
                                first = data[0]
                                o_val = _g(first, "open")
                                h_val = max((_g(c, "high") or 0) for c in data) or None
                                l_vals = [_g(c, "low") for c in data if _g(c, "low")]
                                l_val = min(l_vals) if l_vals else None
                                add(16, f"Open ({sample_sym})", o_val is not None,
                                    warn=o_val is None, detail=str(o_val) if o_val else "無資料",
                                    data_source="fubon_neo SDK rc_stock.intraday.candles")
                                add(17, f"High ({sample_sym})", h_val is not None,
                                    warn=h_val is None, detail=str(h_val) if h_val else "無資料",
                                    data_source="fubon_neo SDK")
                                add(18, f"Low ({sample_sym})", l_val is not None,
                                    warn=l_val is None, detail=str(l_val) if l_val else "無資料",
                                    data_source="fubon_neo SDK")
                            else:
                                for num, nm in [(16,"Open"),(17,"High"),(18,"Low")]:
                                    add(num, f"{nm} ({sample_sym})", False, warn=True,
                                        detail="candles 回傳空", data_source="fubon_neo SDK")
                        except Exception as ce:
                            for num, nm in [(16,"Open"),(17,"High"),(18,"Low")]:
                                add(num, f"{nm} ({sample_sym})", False, warn=True,
                                    detail=f"SDK error: {ce}", data_source="fubon_neo SDK")
                    else:
                        for num, nm in [(14,"期貨價"),(15,"期現差"),(16,"Open"),(17,"High"),(18,"Low")]:
                            add(num, f"{nm} ({sample_sym})", False, warn=True,
                                detail=f"SDK login失敗: {getattr(sdk_r,'message','')}", data_source="fubon_neo SDK")
                except ValueError as ve:
                    for num, nm in [(14,"期貨價"),(15,"期現差"),(16,"Open"),(17,"High"),(18,"Low")]:
                        add(num, f"{nm} ({sample_sym})", False, warn=True,
                            detail=f"SDK連線失敗（非交易日）: {ve}", data_source="fubon_neo SDK")
                except Exception as se:
                    for num, nm in [(14,"期貨價"),(15,"期現差"),(16,"Open"),(17,"High"),(18,"Low")]:
                        add(num, f"{nm} ({sample_sym})", False, warn=True,
                            detail=str(se), data_source="fubon_neo SDK")

            # 19: volume
            try:
                with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                     check_same_thread=False) as c:
                    row = c.execute(
                        "SELECT SUM(volume)/1000 FROM ticks WHERE symbol=? AND ts LIKE ?",
                        (sample_sym, f"{_today()}%")
                    ).fetchone()
                    vol = int(row[0]) if row and row[0] else 0
                add(19, f"成交量 ({sample_sym})", vol > 0, warn=vol == 0,
                    detail=f"{vol:,} 張" if vol > 0 else "盤前/休市 - 無成交",
                    data_source="ticks.db/ticks SUM(volume)/1000")
            except Exception as e:
                _no_tbl = "no such table" in str(e) or "unable to open database file" in str(e)
                if _no_tbl:
                    add(19, f"成交量 ({sample_sym})", True, warn=True,
                        detail="引擎尚未啟動（盤前正常）", data_source="ticks.db/ticks")
                else:
                    add(19, f"成交量 ({sample_sym})", False,
                        detail=f"讀取失敗: {e}", data_source="ticks.db/ticks")
        else:
            for num, nm in [(9,"昨收"),(10,"現價"),(11,"漲跌"),(12,"漲跌%"),(13,"委買比"),
                            (14,"期貨價"),(15,"期現差"),(16,"Open"),(17,"High"),(18,"Low"),(19,"成交量")]:
                add(num, nm, False, warn=True,
                    detail="today daytrade_list 無資料", data_source=f"{_BACKEND}/api/daytrade/list")

        hard_ok   = sum(1 for r in items if r["ok"] and not r["warn"])
        hard_fail = sum(1 for r in items if not r["ok"] and not r["warn"])
        soft_warn = sum(1 for r in items if r["warn"])
        out = {
            "ts": ts, "mode": mode, "no_sdk": no_sdk,
            "summary": {"total": len(items), "hard_ok": hard_ok, "hard_fail": hard_fail, "soft_warn": soft_warn},
            "results": items,
        }
        try:
            data_dir = os.environ.get("FUBON_DATA_DIR", "/fubon-data")
            Path(data_dir).mkdir(parents=True, exist_ok=True)
            (Path(data_dir) / "health_check.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2)
            )
        except Exception:
            pass
        return out

    @app.get("/health-check/results")
    def get_health_check_results():
        """上一次健診結果。"""
        try:
            hf = Path(os.environ.get("FUBON_DATA_DIR", "/fubon-data")) / "health_check.json"
            if not hf.exists():
                return {"ts": None, "results": [], "summary": {"total": 0}}
            return json.loads(hf.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── System status ──────────────────────────────────────────────────────────
    @app.get("/system-status")
    def get_system_status():
        result: dict = {}

        # PG 當沖 / pool stats
        result["daily_db_mb"] = 0  # SQLite 已廢棄
        try:
            import httpx as _httpx
            _pool_r = _httpx.get(f"{_BACKEND}/api/pool", timeout=5)
            if _pool_r.status_code == 200:
                result["watchlist_count"] = len(_pool_r.json())
            _dt_r = _httpx.get(f"{_BACKEND}/api/daytrade/list", timeout=5)
            if _dt_r.status_code == 200:
                _dt_resp = _dt_r.json()
                result["daytrade_latest_date"] = _dt_resp.get("date")
                result["daytrade_latest_count"] = _dt_resp.get("count", 0)
            _ps_r = _httpx.get(f"{_BACKEND}/api/pre-session/logs", params={"limit": 1}, timeout=5)
            if _ps_r.status_code == 200:
                _ps = _ps_r.json()
                if _ps:
                    result["last_presession_date"] = _ps[0].get("run_date")
                    result["last_presession_status"] = _ps[0].get("status")
                    result["last_presession_success"] = _ps[0].get("success_stocks")
                    result["last_presession_total"] = _ps[0].get("total_stocks")
        except Exception:
            pass

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
        import httpx as _httpx
        try:
            r = _httpx.get(f"{_BACKEND}/api/pre-session/logs", timeout=8)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        if _store is None:
            return []
        return _store.get_pre_session_logs(limit=10)

    @app.get("/pre-session/db-size")
    def get_db_size():
        return {"size_mb": 0}

    # ── Trading params ────────────────────────────────────────────────────────
    @app.get("/trading-params")
    def get_trading_params():
        return _trading_params.copy()

    @app.post("/trading-params")
    def update_trading_params(body: TradingParamsBody):
        import httpx as _httpx
        if body.max_position_capital <= 0:
            raise HTTPException(status_code=400, detail="max_position_capital must be > 0")
        if body.max_daily_positions <= 0:
            raise HTTPException(status_code=400, detail="max_daily_positions must be > 0")
        # 更新 in-memory dict
        _trading_params["dry_run"] = body.dry_run
        _trading_params["max_position_capital"] = body.max_position_capital
        _trading_params["max_daily_positions"] = body.max_daily_positions
        _trading_params["commission_discount"] = max(0.0, min(1.0, body.commission_discount))
        _trading_params["tick_rise_threshold"] = max(1, body.tick_rise_threshold)
        _trading_params["tick_window_seconds"] = max(10, body.tick_window_seconds)
        _trading_params["max_change_pct"] = max(0.1, body.max_change_pct)
        _trading_params["check_not_in_position"] = body.check_not_in_position
        _trading_params["check_futures_signal"] = body.check_futures_signal
        _trading_params["bid_pct_threshold"] = max(0.0, min(100.0, body.bid_pct_threshold))
        _trading_params["amplitude_min_pct"] = max(0.0, min(20.0, body.amplitude_min_pct))
        _trading_params["bid_1m_pct_threshold"] = max(0.0, min(100.0, body.bid_1m_pct_threshold))
        _trading_params["vol_ratio_coefficient"] = max(0.1, min(10.0, body.vol_ratio_coefficient))
        _trading_params["stop_loss_ticks"] = max(1, body.stop_loss_ticks)
        _trading_params["take_profit_add_pct"] = max(0.1, body.take_profit_add_pct)
        _trading_params["entry_start_time"] = body.entry_start_time
        _trading_params["latest_dynamic_add_time"] = body.latest_dynamic_add_time
        _trading_params["force_exit_time"] = body.force_exit_time
        _trading_params["daytrade_price_min"] = max(0.0, body.daytrade_price_min)
        _trading_params["daytrade_price_max"] = max(0.0, body.daytrade_price_max)
        # 持久化到 PG
        try:
            pg_body = {k: str(v) for k, v in _trading_params.items() if k in _PARAM_KEYS}
            _httpx.post(f"{_BACKEND}/api/trading-settings", json=pg_body, timeout=5)
        except Exception:
            pass
        # 同步到 ticks.db（engine _gs() 熱重載用）
        _sync_to_ticks_db({k: _trading_params[k] for k in _PARAM_KEYS})
        return {"ok": True, "note": "✓ 已儲存，即時生效", **_trading_params}

    # ── Debug: 模擬買賣（送真實 LINE 通知，不影響引擎狀態）──────────────────────
    _sim_positions: dict = {}  # symbol → {entry_price, lots, stop_loss}

    @app.post("/debug/simulate-buy")
    def simulate_buy(symbol: str = "2382", price: float = 0.0, lots: int = 1,
                     ref_price: float = 0.0, stop_loss_ticks: int = 4, take_profit_add_pct: float = 4.0):
        """模擬買入：建立暫存持倉，送 LINE 通知（dry_run=False 真實發送）。"""
        import urllib.request as _ur
        from engine.risk.position import Position
        from engine.execution.broker import tw_tick_size, round_up_tick, round_down_tick
        from engine.monitor.notifier import LineNotifier
        notifier = LineNotifier(dry_run=False)
        try:
            _pool = json.loads(_ur.urlopen("http://localhost:8000/api/pool", timeout=2).read())
            _sname = next((s.get("name","") for s in _pool if s.get("code")==symbol), "")
        except Exception:
            _sname = ""
        if price <= 0:
            price = 250.0
        if ref_price <= 0:
            ref_price = price
        ts = tw_tick_size(price)
        stop_loss = round_up_tick(price - stop_loss_ticks * ts)
        change_at_entry = (price - ref_price) / ref_price * 100 if ref_price > 0 else 0.0
        take_profit = round_down_tick(ref_price * (1 + (change_at_entry + take_profit_add_pct) / 100))
        pos = Position(symbol=symbol, entry_price=price, lots=lots,
                       stop_loss=stop_loss, take_profit=take_profit)
        _sim_positions[symbol] = {
            "entry_price": price, "lots": lots,
            "stop_loss": pos.stop_loss, "take_profit": pos.take_profit,
            "name": _sname,
        }
        msg = (
            f"🟢【模擬進場】{symbol} {_sname}\n"
            f"價={price:.1f}  張數={lots}\n"
            f"停損={pos.stop_loss:.2f}  停利={pos.take_profit:.2f}"
        )
        sent = notifier.send(msg, msg_type="debug")
        return {"ok": True, "sent": sent, "symbol": symbol, "entry_price": price,
                "lots": lots, "stop_loss": pos.stop_loss, "take_profit": pos.take_profit, "message": msg}

    @app.post("/debug/simulate-sell")
    def simulate_sell(symbol: str = "2382", price: float = 0.0, reason: str = "atr_stop"):
        """模擬賣出：結算暫存持倉損益，送 LINE 通知。"""
        from engine.monitor.notifier import LineNotifier
        notifier = LineNotifier(dry_run=False)
        pos = _sim_positions.pop(symbol, None)
        if pos is None:
            raise HTTPException(status_code=404, detail=f"無 {symbol} 模擬持倉，請先 simulate-buy")
        if price <= 0:
            price = pos["stop_loss"]
        pnl = (price - pos["entry_price"]) * pos["lots"] * 1000
        _sname = pos.get("name", "")
        msg = (
            f"🔴【模擬出場】{symbol} {_sname}\n"
            f"原因={reason}  {pos['entry_price']:.1f}→{price:.1f}\n"
            f"損益={pnl:+,.0f}  {pos['lots']}張\n"
            f"停損={pos['stop_loss']:.2f}  停利={pos.get('take_profit', 0):.2f}"
        )
        sent = notifier.send(msg, msg_type="debug")
        return {"ok": True, "sent": sent, "symbol": symbol, "exit_price": price,
                "pnl": pnl, "reason": reason, "message": msg}

    @app.get("/debug/simulate-positions")
    def get_sim_positions():
        return _sim_positions

    # ── Manual Trade（真實下單：獨立 broker dry_run=False）────────────────────
    _manual_positions: dict = {}  # symbol → position dict
    _oco_registered = [False]  # mutable flag for closure

    def _register_oco_callback(sdk):
        """SDK 就緒後呼叫一次，設 set_on_order_changed 實現軟 OCO。"""
        if _oco_registered[0]:
            return
        _oco_registered[0] = True

        def _on_order_changed(data):
            try:
                # 解析資料：支援 dict / object 兩種格式
                if isinstance(data, dict):
                    d = data
                elif hasattr(data, '__dict__'):
                    d = vars(data)
                else:
                    # 嘗試 getattr 取常見欄位
                    d = {f: getattr(data, f, None) for f in [
                        'id', 'guid', 'parent_guid', 'status', 'condition_filled_volume',
                        'order_no', 'buy_sell', 'symbol', 'action',
                    ]}
                __import__('logging').getLogger("manual_trade").debug("set_on_order_changed raw: %s", d)

                # 取 guid
                guid = (d.get('id') or d.get('guid') or d.get('parent_guid') or '')
                if not guid:
                    return
                guid = str(guid)

                # condition_filled_volume > 0 表示已觸發成交
                filled_vol = d.get('condition_filled_volume', 0) or 0
                status_str = str(d.get('status', '') or '')
                # QCT03=完全成交, QCT02=部分成交（推測），也接受 condition_filled_volume > 0
                triggered = (filled_vol > 0) or (status_str in ('QCT02', 'QCT03'))
                if not triggered:
                    return

                for sym, pos in list(_manual_positions.items()):
                    sg = str(pos.get('stop_guid') or '')
                    tg = str(pos.get('tp_guid') or '')
                    if guid == sg and tg:
                        # 停損已觸發 → 取消停利
                        try:
                            if _engine and _engine.sdk and _engine.account:
                                _engine.sdk.stock.cancel_condition_orders(_engine.account, tg)
                            pos['tp_guid'] = None
                            __import__('logging').getLogger("manual_trade").info("OCO: %s 停損觸發，自動取消停利 %s", sym, tg)
                        except Exception as ce:
                            __import__('logging').getLogger("manual_trade").warning("OCO 取消停利失敗: %s", ce)
                    elif guid == tg and sg:
                        # 停利已觸發 → 取消停損
                        try:
                            if _engine and _engine.sdk and _engine.account:
                                _engine.sdk.stock.cancel_condition_orders(_engine.account, sg)
                            pos['stop_guid'] = None
                            __import__('logging').getLogger("manual_trade").info("OCO: %s 停利觸發，自動取消停損 %s", sym, sg)
                        except Exception as ce:
                            __import__('logging').getLogger("manual_trade").warning("OCO 取消停損失敗: %s", ce)
            except Exception as e:
                __import__('logging').getLogger("manual_trade").debug("OCO callback error: %s", e)

        try:
            sdk.set_on_order_changed(_on_order_changed)
            __import__('logging').getLogger("manual_trade").info("OCO set_on_order_changed callback 已註冊")
        except Exception as e:
            __import__('logging').getLogger("manual_trade").warning("OCO callback 註冊失敗: %s", e)

    def _get_manual_broker():
        """建立真實下單 broker（需引擎已登入）"""
        from engine.execution.broker import FubonBroker
        if _engine is None or _engine.sdk is None or _engine.account is None:
            raise HTTPException(status_code=503, detail="引擎未啟動或 SDK 未連線，無法下單")
        _register_oco_callback(_engine.sdk)
        b = FubonBroker(dry_run=False)
        b.initialize(_engine.sdk, _engine.account)
        return b

    def _curr_price(symbol: str) -> float:
        """從引擎 sessions 取最新報價，無則回 0"""
        if _engine and symbol in _engine.sessions:
            return _engine.sessions[symbol].curr_price or 0.0
        return 0.0

    @app.get("/manual-trade/positions")
    def mt_positions():
        """手動交易目前持倉"""
        result = []
        for sym, pos in _manual_positions.items():
            curr = _curr_price(sym)
            unrealized = (curr - pos["entry_price"]) * pos["lots"] * 1000 if curr > 0 else None
            result.append({**pos, "curr_price": curr, "unrealized": unrealized})
        return result

    @app.get("/manual-trade/price/{symbol}")
    def mt_price(symbol: str):
        """取某股最新報價（需引擎在運行且有訂閱）"""
        p = _curr_price(symbol)
        return {"symbol": symbol, "price": p}

    @app.post("/manual-trade/buy")
    def mt_buy(
        symbol: str,
        lots: int = 1,
        price: float = 0.0,
        prev_close: float = 0.0,
        stop_loss_ticks: int = 4,
        take_profit_add_pct: float = 4.0,
        force_market: bool = False,
    ):
        """
        手動買進（真實下單）。
        price=0 → 用引擎最新 tick 報價。
        force_market=True → 市價 IOC 強制成交。
        """
        import datetime
        from engine.execution.broker import tw_tick_size, round_up_tick, round_down_tick

        if symbol in _manual_positions:
            raise HTTPException(status_code=400, detail=f"{symbol} 已有手動持倉，請先平倉")

        broker = _get_manual_broker()

        if price <= 0:
            price = _curr_price(symbol)
        if price <= 0:
            raise HTTPException(status_code=400, detail=f"無法取得 {symbol} 報價，請手動輸入買進價格")

        if prev_close <= 0:
            prev_close = price  # fallback: 以買進價當昨收

        # 計算停損、停利
        ts = tw_tick_size(price)
        stop_loss = round_up_tick(price - stop_loss_ticks * ts)
        entry_chg_pct = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0.0
        take_profit = round_down_tick(prev_close * (1 + (entry_chg_pct + take_profit_add_pct) / 100))

        trade_date = datetime.date.today().strftime("%Y/%m/%d")

        # 買進
        buy_mode = "stock"
        try:
            if force_market:
                from fubon_neo.sdk import Order
                from fubon_neo.constant import BSAction, MarketType, PriceType, TimeInForce, OrderType
                order = Order(
                    buy_sell=BSAction.Buy,
                    symbol=symbol,
                    quantity=lots * 1000,
                    market_type=MarketType.Common,
                    price_type=PriceType.Market,
                    time_in_force=TimeInForce.IOC,
                    order_type=OrderType.Stock,  # 現買
                )
                try:
                    broker._sdk.stock.place_order(broker._account, order)
                except Exception as _fe:
                    raise RuntimeError(f"下單失敗: {_fe}") from _fe
            else:
                buy_mode = broker.buy(symbol, lots, price)  # 預設 stock（現買）
        except RuntimeError as _e:
            raise HTTPException(status_code=400, detail=str(_e))

        # 掛停損觸價單
        stop_guid = broker.place_conditional_stop(symbol, lots, stop_loss, trade_date)
        # 掛停利觸價單
        tp_guid = broker.place_conditional_take_profit(symbol, lots, take_profit, trade_date)

        _manual_positions[symbol] = {
            "symbol": symbol,
            "entry_price": price,
            "lots": lots,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "stop_guid": stop_guid,
            "tp_guid": tp_guid,
            "prev_close": prev_close,
            "entry_time": datetime.datetime.now().strftime("%H:%M:%S"),
        }

        note = "（該股不支援當沖，改用普通單）" if "fallback" in (buy_mode or "") else ""

        return {
            "ok": True,
            "symbol": symbol,
            "entry_price": price,
            "lots": lots,
            "buy_mode": buy_mode,
            "note": note,
            "stop_loss": stop_loss,
            "stop_loss_desc": f"成交價 ≤ {stop_loss:.2f}（進場價 - {stop_loss_ticks} tick）→ 市價賣出",
            "take_profit": take_profit,
            "take_profit_desc": f"成交價 ≥ {take_profit:.2f}（昨收 {prev_close:.2f} × (1 + ({entry_chg_pct:.1f}% + {take_profit_add_pct}%)）→ 市價賣出",
            "stop_guid": stop_guid,
            "tp_guid": tp_guid,
        }

    @app.post("/manual-trade/sell/{symbol}")
    def mt_sell(symbol: str, price: float = 0.0):
        """手動市價賣出（真實），同時取消兩張觸價單。"""
        pos = _manual_positions.get(symbol)
        if pos is None:
            raise HTTPException(status_code=404, detail=f"無 {symbol} 手動持倉")

        broker = _get_manual_broker()

        # 取消觸價單
        if pos.get("stop_guid"):
            broker.cancel_conditional_order(pos["stop_guid"])
        if pos.get("tp_guid"):
            broker.cancel_conditional_order(pos["tp_guid"])

        # 市價賣出
        sell_price = price if price > 0 else (_curr_price(symbol) or pos["entry_price"])
        broker.sell(symbol, pos["lots"], sell_price, reason="manual_exit")

        pnl = (sell_price - pos["entry_price"]) * pos["lots"] * 1000
        del _manual_positions[symbol]

        return {"ok": True, "symbol": symbol, "exit_price": sell_price,
                "pnl": round(pnl, 0), "lots": pos["lots"]}

    @app.post("/manual-trade/limit-sell")
    def mt_limit_sell(symbol: str, lots: int = 1, price: float = 0.0):
        """手動限價賣出（真實），不需要有持倉記錄。"""
        broker = _get_manual_broker()

        if price <= 0:
            price = _curr_price(symbol)
        if price <= 0:
            raise HTTPException(status_code=400, detail=f"無法取得 {symbol} 報價，請手動輸入賣出價格")

        try:
            broker.limit_sell(symbol, lots, price)
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        return {"ok": True, "symbol": symbol, "price": price, "lots": lots}

    @app.post("/manual-trade/cancel-conditions/{symbol}")
    def mt_cancel_conditions(symbol: str):
        """只取消觸價單，持倉不動（手動管理）。"""
        pos = _manual_positions.get(symbol)
        if pos is None:
            raise HTTPException(status_code=404, detail=f"無 {symbol} 手動持倉")
        broker = _get_manual_broker()
        cancelled = []
        if pos.get("stop_guid"):
            broker.cancel_conditional_order(pos["stop_guid"])
            cancelled.append(f"停損 {pos['stop_guid']}")
            pos["stop_guid"] = None
        if pos.get("tp_guid"):
            broker.cancel_conditional_order(pos["tp_guid"])
            cancelled.append(f"停利 {pos['tp_guid']}")
            pos["tp_guid"] = None
        return {"ok": True, "cancelled": cancelled}

    @app.delete("/manual-trade/position/{symbol}")
    def mt_delete_position(symbol: str):
        """僅從記錄刪除（觸價單已自行觸發或已手動取消後用）。"""
        _manual_positions.pop(symbol, None)
        return {"ok": True}

    @app.post("/debug/simulate-full-day")
    def simulate_full_day(symbol: str = "2382", ref_price: float = 250.0):
        """完整交易日模擬（已停用：策略改為 60s tick 動量，請用 /debug/simulate-buy）。"""
        raise HTTPException(status_code=410, detail="simulate-full-day 已停用（舊 ORB 策略）。請改用 /debug/simulate-buy 測試新策略。")

    @app.get("/debug/futures-map")
    def debug_futures_map():
        if _engine is None:
            return {"error": "engine None"}
        return {
            "futures_sym_map": _engine.futures_sym_map,
            "futures_signals": {k: str(getattr(getattr(v, '_state', None), 'futures_price', '?'))
                                for k, v in _engine.futures_signals.items()},
            "status": _engine.status,
        }


    # ── Restart FastAPI ───────────────────────────────────────────────────────
    @app.post("/restart/fastapi")
    def restart_fastapi():
        """Kill this uvicorn process — Docker restart policy will bring it back."""
        def _kill():
            import time
            time.sleep(0.5)
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=_kill, daemon=True).start()
        return {"ok": True, "message": "FastAPI 重啟中，請稍候..."}

    # ── Config ────────────────────────────────────────────────────────────────
    @app.get("/config")
    def get_config():
        config_path = os.environ.get("FUBON_CONFIG", "/home/tommy0322/fubon-config/config.yaml")
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

    # ── Engine control ────────────────────────────────────────────────────────
    @app.get("/engine/status")
    def get_engine_status():
        if _engine is None:
            return {"status": "unavailable", "error": "trading_engine not initialized"}
        state = _engine.get_state()
        pnl = _engine.get_pnl_summary() if state["status"] == "running" else {}
        positions = _engine.get_positions() if state["status"] == "running" else []
        return {**state, "pnl": pnl, "positions": positions}

    @app.post("/engine/start")
    def start_engine():
        if _engine is None:
            raise HTTPException(status_code=503, detail="trading_engine not initialized")
        config_path = os.environ.get("FUBON_CONFIG", "/home/tommy0322/fubon-config/config.yaml")
        data_dir = os.environ.get("FUBON_DATA_DIR", "/fubon-data")
        log_dir = os.environ.get("FUBON_LOG_DIR", "/fubon-logs")
        ticks_db_path = os.path.join(data_dir, "ticks.db")
        ok = _engine.start(
            config_path=config_path,
            ticks_db=ticks_db_path,
            log_dir=log_dir,
        )
        if not ok:
            return {"ok": False, "message": f"引擎已在 {_engine.status} 狀態，無法重複啟動"}
        return {"ok": True, "message": "引擎啟動中..."}

    @app.post("/engine/stop")
    def stop_engine():
        if _engine is None:
            raise HTTPException(status_code=503, detail="trading_engine not initialized")
        ok = _engine.stop()
        if not ok:
            return {"ok": False, "message": f"引擎目前狀態={_engine.status}，無法停止"}
        return {"ok": True, "message": "引擎停止中..."}

    @app.post("/engine/cancel-conditions/{symbol}")
    def engine_cancel_conditions(symbol: str):
        """取消引擎為某個股掛的停損/停利觸價單（不賣股票）。
        用途：使用者想從手機 App 手動賣出前，先在這裡取消觸價單，避免觸價後無倉可賣。"""
        if _engine is None or _engine.status != "running":
            raise HTTPException(status_code=503, detail="引擎未執行")
        cids = _engine.condition_ids.pop(symbol, None)
        if cids is None:
            raise HTTPException(status_code=404, detail=f"{symbol} 無觸價單記錄（可能已觸發或未進場）")
        broker = _engine.broker
        if broker is None:
            raise HTTPException(status_code=503, detail="broker 未初始化")
        cancelled = []
        errors = []
        if cids.get("sl"):
            try:
                broker.cancel_conditional_order(cids["sl"])
                cancelled.append(f"停損 {cids['sl']}")
            except Exception as e:
                errors.append(f"停損取消失敗: {e}")
        if cids.get("tp"):
            try:
                broker.cancel_conditional_order(cids["tp"])
                cancelled.append(f"停利 {cids['tp']}")
            except Exception as e:
                errors.append(f"停利取消失敗: {e}")
        return {"ok": True, "symbol": symbol, "cancelled": cancelled, "errors": errors}

    # ── LINE 通知紀錄 ──────────────────────────────────────────────────────────
    @app.get("/line-notifications")
    def get_line_notifications(days: int = 5, limit: int = 200):
        """查詢 LINE 通知記錄，預設近 5 天。"""
        import datetime as _dt
        ym = _dt.datetime.now().strftime("%Y-%m")
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT monthly_seq, msg_type, content, sent_at, success"
                    " FROM line_notifications"
                    " WHERE sent_at >= datetime('now',?,'localtime')"
                    " ORDER BY id DESC LIMIT ?",
                    (f"-{days} days", limit),
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) FROM line_notifications WHERE year_month=?",
                    (ym,),
                ).fetchone()[0]
            return {
                "year_month": ym,
                "total_sent": total,
                "free_remaining": max(0, 200 - total),
                "rows": [dict(r) for r in rows],
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ── SSE: live tick stream ─────────────────────────────────────────────────
    _live_conn: list = [None]  # mutable cell for closure

    def _get_live_conn():
        if _live_conn[0] is None and Path(_ticks_db).exists():
            try:
                _live_conn[0] = sqlite3.connect(
                    f"file:{_ticks_db}?mode=ro", uri=True, check_same_thread=False
                )
            except Exception:
                pass
        return _live_conn[0]

    def _query_live(symbols: list[str]) -> dict:
        if not symbols or not Path(_ticks_db).exists():
            return {}
        out: dict = {}
        today = _today()
        today_pct = f"{today}%"
        now = _now_tw()
        this_min = now.replace(second=0, microsecond=0, tzinfo=None)
        this_min_str  = this_min.strftime("%Y-%m-%d %H:%M:%S")
        prev_min_str  = (this_min - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        prev2_min_str = (this_min - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")

        c = _get_live_conn()
        if c is None:
            return {}
        try:
            ph = ','.join('?' * len(symbols))
            # Latest price
            for sym, p in c.execute(
                f"SELECT symbol, price FROM ticks WHERE id IN ("
                f"SELECT MAX(id) FROM ticks WHERE symbol IN ({ph}) GROUP BY symbol)",
                symbols,
            ).fetchall():
                out.setdefault(sym, {})["price"] = p

            # Today OHLV (date-filtered)
            # volume 欄位儲存 SDK trades.volume（今日累積張數，與 TWSE v 欄位一致），MAX 取最新值
            # H/L/Open 只取 09:00+ 真實成交（濾除試撮和停牌期間模擬價）
            open_ts = f"{today} 09:00:00"
            for sym, op, hi, lo, vol in c.execute(
                f"""SELECT t.symbol,
                    (SELECT price FROM ticks t2
                     WHERE t2.symbol=t.symbol AND t2.ts >= ? AND t2.ts LIKE ?
                     ORDER BY t2.id ASC LIMIT 1) AS open,
                    MAX(CASE WHEN t.ts >= ? THEN t.price END),
                    MIN(CASE WHEN t.ts >= ? THEN t.price END),
                    MAX(t.volume)
                    FROM ticks t WHERE t.symbol IN ({ph}) AND t.ts LIKE ?
                    GROUP BY t.symbol""",
                [open_ts, today_pct, open_ts, open_ts] + symbols + [today_pct],
            ).fetchall():
                out.setdefault(sym, {}).update(
                    open=op, high=hi, low=lo,
                    vol_lots=int(vol or 0),
                )

            # Level 2 quotes
            for sym, bv, av in c.execute(
                f"SELECT symbol, bid_vol, ask_vol FROM quotes WHERE symbol IN ({ph})",
                symbols,
            ).fetchall():
                total = (bv or 0) + (av or 0)
                out.setdefault(sym, {}).update(
                    bid_vol=bv or 0, ask_vol=av or 0,
                    bid_pct=round(bv / total * 100) if total else 50,
                )

            # 1-minute volume comparison
            for sym, cv, pv in c.execute(
                f"""SELECT symbol,
                    SUM(CASE WHEN ts >= ? THEN volume ELSE 0 END),
                    SUM(CASE WHEN ts >= ? AND ts < ? THEN volume ELSE 0 END)
                    FROM ticks
                    WHERE ts >= ? AND ts LIKE ? AND symbol IN ({ph})
                    GROUP BY symbol""",
                [this_min_str, prev_min_str, this_min_str,
                 prev2_min_str, today_pct] + symbols,
            ).fetchall():
                out.setdefault(sym, {}).update(
                    vol_1m=int(cv or 0), vol_prev_1m=int(pv or 0)
                )

            # Active position data (stop_loss, ATR)
            for sym, sl, atr, ep, lots in c.execute(
                f"""SELECT symbol, stop_loss, atr, entry_price, lots
                    FROM intraday_positions
                    WHERE trade_date=? AND is_paper=0 AND symbol IN ({ph})""",
                [today] + symbols,
            ).fetchall():
                out.setdefault(sym, {}).update(
                    pos_stop_loss=sl, pos_atr=round(atr, 3) if atr else None,
                    pos_entry=ep, pos_lots=lots,
                )

            # Index
            idx_row = c.execute(
                "SELECT price, change_5min, circuit, chg_day_pct FROM index_ticks ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if idx_row:
                out["__index__"] = {
                    "price": idx_row[0],
                    "chg5": idx_row[1],
                    "circuit": idx_row[2],
                    "chg_day_pct": idx_row[3] if len(idx_row) > 3 else 0.0,
                }
        except Exception:
            _live_conn[0] = None  # reset so next call reconnects
        return out

    @app.get("/stream")
    async def sse_stream(syms: str = ""):
        symbols = [s.strip() for s in syms.split(",") if s.strip()]

        async def event_gen():
            while True:
                data = _query_live(symbols)
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.2)

        return StreamingResponse(
            event_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app
