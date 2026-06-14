import asyncio
import json
import math
import os
import signal
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


class TradingParamsBody(BaseModel):
    max_position_capital: int
    max_daily_positions: int
    dry_run: bool
    commission_discount: float = 0.28
    cb_crash_pct: float = 1.5   # N分鐘跌幅觸發熔斷（%）
    cb_window_min: int = 5
    cb_pause_minutes: int = 30  # 熔斷後暫停進場分鐘數


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
    max_daily_positions: int = 3,
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
    _trading_params = {
        "max_position_capital": max_position_capital,
        "max_daily_positions": max_daily_positions,
        "dry_run": dry_run,
        "commission_discount": 0.28,
        "cb_crash_pct": 1.5,
        "cb_window_min": 5,
        "cb_pause_minutes": 30,
    }

    def _load_trading_params_from_db():
        """從 SQLite settings 表還原所有交易參數（重啟後不遺失）"""
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                rows = c.execute(
                    "SELECT key, value FROM settings WHERE key IN "
                    "('cb_crash_pct','cb_window_min','cb_pause_minutes',"
                    "'max_position_capital','max_daily_positions','dry_run','commission_discount')"
                ).fetchall()
            for k, v in rows:
                if k == 'cb_crash_pct':
                    _trading_params['cb_crash_pct'] = float(v)
                elif k == 'cb_window_min':
                    _trading_params['cb_window_min'] = int(v)
                elif k == 'cb_pause_minutes':
                    _trading_params['cb_pause_minutes'] = int(v)
                elif k == 'max_position_capital':
                    _trading_params['max_position_capital'] = int(v)
                elif k == 'max_daily_positions':
                    _trading_params['max_daily_positions'] = int(v)
                elif k == 'dry_run':
                    _trading_params['dry_run'] = v.lower() in ('true', '1', 'yes')
                elif k == 'commission_discount':
                    _trading_params['commission_discount'] = float(v)
        except Exception:
            pass

    _load_trading_params_from_db()

    # ── WebSocket push ────────────────────────────────────────────────────────
    _ws_clients: set = set()

    async def _push_state():
        """每秒把引擎狀態推給所有已連線的 WebSocket 客戶端。"""
        while True:
            await asyncio.sleep(1)
            if not _ws_clients:
                continue
            try:
                if _engine is not None:
                    state = _engine.get_state()
                    if state.get("status") == "running":
                        pnl = _engine.get_pnl_summary()
                        positions = _sanitize(_engine.get_positions())
                    else:
                        pnl = {}
                        positions = []
                else:
                    state = {"status": "unavailable"}
                    pnl = {}
                    positions = []
                msg = json.dumps(
                    {"type": "state", **state, "pnl": pnl, "positions": positions},
                    ensure_ascii=False, default=str,
                )
                dead: set = set()
                for ws in list(_ws_clients):
                    try:
                        await ws.send_text(msg)
                    except Exception:
                        dead.add(ws)
                _ws_clients -= dead
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
        """每天 20:00 執行一次清理，保留最近 30 天資料。"""
        while True:
            now = datetime.now()
            next_run = now.replace(hour=20, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            await asyncio.sleep((next_run - datetime.now()).total_seconds())
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
                    "atr": getattr(pos, "atr", None),
                    "orb_low": getattr(pos, "orb_low", None),
                }
                for sym, pos in _positions.items()
            ]
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                c.row_factory = sqlite3.Row
                rows = c.execute(
                    "SELECT symbol, entry_price, lots, stop_loss, atr, orb_low FROM intraday_positions "
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

    @app.get("/daytrade-list/live")
    def get_daytrade_list_live():
        """Fubon-style: INNER JOIN watchlist + criteria (above_ma20 & vol_ok & chip_count>=2) + dry_run_watchlist."""
        if _store is None:
            raise HTTPException(status_code=503, detail="daily_store 未初始化")
        daily_db_path = getattr(_store, "db_path", None)
        if not daily_db_path or not Path(daily_db_path).exists():
            raise HTTPException(status_code=503, detail="daily.db 未就緒")

        config_watchlist: list = []
        try:
            import yaml
            config_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            config_watchlist = [
                str(s) for s in (cfg.get("trading", {}).get("dry_run_watchlist") or [])
                if s is not None
            ]
        except Exception:
            pass

        try:
            with sqlite3.connect(f"file:{daily_db_path}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                c.row_factory = sqlite3.Row
                date_row = c.execute("SELECT MAX(date) FROM daytrade_list").fetchone()
                target_date = date_row[0] if date_row and date_row[0] else _today()

                rows = c.execute("""
                    SELECT
                        d.stock_id,
                        COALESCE(w.name, '') AS name,
                        dp.close             AS prev_close,
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
                        COALESCE(inst.foreign_net, 0)  AS foreign_net,
                        COALESCE(inst.trust_net, 0)    AS trust_net,
                        COALESCE(mgn.margin_change, 0) AS margin_change
                    FROM daytrade_list d
                    JOIN watchlist w ON w.stock_id = d.stock_id
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
                avg5 = row_d.get("avg_vol5") or 0
                ma20 = row_d.get("ma20") or 0

                above_ma20 = cur > ma20
                vol_ok     = avg5 >= 2000
                chip_count = (
                    (1 if row_d["foreign_net"] > 0 else 0) +
                    (1 if row_d["trust_net"] > 0 else 0) +
                    (1 if row_d["margin_change"] < 0 else 0)
                )

                if not (above_ma20 and vol_ok and chip_count >= 2):
                    continue
                if config_watchlist and row_d["stock_id"] not in config_watchlist:
                    continue

                change = round(cur - prev, 2) if prev else 0
                change_pct = round(change / prev * 100, 2) if prev else 0
                row_d["change"] = change
                row_d["change_pct"] = change_pct
                row_d["avg_vol5"] = round(avg5)
                row_d["above_ma20"] = above_ma20
                row_d["vol_ok"] = vol_ok
                row_d["chip_count"] = chip_count
                result.append(row_d)

            if config_watchlist:
                order_map = {sym: i for i, sym in enumerate(config_watchlist)}
                result.sort(key=lambda x: order_map.get(x["stock_id"], len(config_watchlist)))

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

    # ── Futures snapshot ─────────────────────────────────────────────────────
    @app.get("/futures-snapshot")
    def get_futures_snapshot(syms: str = ""):
        """近月個股期貨價格 via SDK。非交易日 SDK 無法連線時 gracefully 回傳 error。"""
        symbols = [s.strip() for s in syms.split(",") if s.strip()] if syms else []
        result: dict = {"ok": False, "ts": datetime.now().isoformat(), "data": {}, "error": None}
        try:
            import yaml
            config_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            fc = cfg["fubon"]
        except Exception as e:
            result["error"] = f"config 讀取失敗: {e}"
            return result
        try:
            import datetime as dt
            from fubon_neo.sdk import FubonSDK, Mode
            sdk = FubonSDK()
            r = sdk.login(fc["id"], fc["password"], fc["cert_path"], fc["cert_password"])
            if not r.is_success:
                result["error"] = f"SDK login 失敗: {getattr(r, 'message', '')}"
                return result
            sdk.init_realtime(Mode.Speed)
            rc_f = sdk.marketdata.rest_client.futopt
            today = dt.date.today()
            mc = "FGHJKMNQUVXZ"
            near = mc[today.month - 1] + str(today.year)[-1]
            next_m = today.month % 12 + 1
            next_y = str(today.year + (1 if today.month == 12 else 0))[-1]
            next_code = mc[next_m - 1] + next_y
            for sym in (symbols or ["TX"]):
                for code in [f"{sym}{near}", f"{sym}{next_code}", f"{sym}F1", f"{sym}F"]:
                    try:
                        t = rc_f.intraday.ticker(symbol=code)
                        if t is None:
                            continue
                        price = getattr(t, "lastPrice", None) or getattr(t, "close", None)
                        if isinstance(t, dict):
                            price = t.get("lastPrice") or t.get("close")
                        if price is None:
                            continue
                        prev = getattr(t, "referencePrice", None) or getattr(t, "previousClose", None)
                        if isinstance(t, dict):
                            prev = t.get("referencePrice") or t.get("previousClose")
                        chg = round(float(price) - float(prev), 2) if prev else 0
                        chg_pct = round(chg / float(prev) * 100, 2) if prev else 0
                        result["data"][sym] = {
                            "price": float(price), "change": chg,
                            "change_pct": chg_pct, "futures_code": code,
                        }
                        break
                    except Exception:
                        continue
            result["ok"] = True
        except ValueError as e:
            result["error"] = f"SDK 連線失敗（非交易日）: {e}"
        except ImportError:
            result["error"] = "fubon_neo 未安裝"
        except Exception as e:
            result["error"] = str(e)
        return result

    # ── Health check (19-item, port of premarket_check.py) ────────────────────
    @app.post("/health-check/run")
    def run_health_check(mode: str = "quick"):
        """19-item 系統健診。mode=quick 略過 SDK 呼叫；mode=full 執行所有項目。"""
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
            add(3, "持倉數", False, detail=f"讀取失敗: {e}", data_source="ticks.db/intraday_positions")

        # 04-06: index
        idx_price = idx_chg5 = None
        idx_circuit = "normal"
        try:
            with sqlite3.connect(f"file:{_ticks_db}?mode=ro", uri=True,
                                 check_same_thread=False) as c:
                row = c.execute(
                    "SELECT price, change_5min, circuit FROM index_ticks ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    idx_price, idx_chg5, idx_circuit = row[0], row[1], row[2] or "normal"
        except Exception:
            pass
        mkt = idx_price is not None and idx_price > 0
        add(4, "加權指數", True, warn=not mkt,
            detail=f"{idx_price:,.0f} 點" if mkt else "盤前/休市 - 無 tick 屬正常",
            data_source="ticks.db/index_ticks", logic="最新一筆 price")
        add(5, "指數5min變化", True, warn=not mkt,
            detail=f"{idx_chg5:+.0f} 點" if idx_chg5 is not None else "尚無資料",
            data_source="ticks.db/index_ticks", logic="change_5min 欄位")
        cok = idx_circuit == "normal"
        add(6, "熔斷狀態", cok, warn=not cok and mkt,
            detail=f"circuit={idx_circuit}", data_source="ticks.db/index_ticks")

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

        # 07c: config.yaml readable
        _cfg_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
        try:
            import yaml as _yaml
            with open(_cfg_path, encoding="utf-8") as _cf:
                _cfg_data = _yaml.safe_load(_cf)
            _fubon_ok = bool(_cfg_data.get("fubon", {}).get("id"))
            add("7c", "config.yaml", _fubon_ok,
                warn=not _fubon_ok,
                detail=f"{_cfg_path}  fubon.id={'有' if _fubon_ok else '未設定'}",
                data_source=_cfg_path, logic="fubon.id 存在即 ok")
        except FileNotFoundError:
            add("7c", "config.yaml", False, detail=f"找不到 {_cfg_path}", data_source=_cfg_path)
        except Exception as _e:
            add("7c", "config.yaml", False, detail=f"讀取失敗: {_e}", data_source=_cfg_path)

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
            engine_detail = f"ticks.db 讀取失敗: {e}"
        add(8, "tick 資料流", engine_ok, warn=not engine_ok,
            detail=engine_detail, data_source="ticks.db/ticks",
            logic="最後 tick < 15分 → 資料流正常（盤中）")

        # 09-19: per-stock checks using first symbol from daytrade_list
        sample_sym = None
        prev_close = None
        if _store is not None:
            daily_db_path = getattr(_store, "db_path", None)
            if daily_db_path and Path(daily_db_path).exists():
                try:
                    with sqlite3.connect(f"file:{daily_db_path}?mode=ro", uri=True,
                                         check_same_thread=False) as c:
                        row = c.execute(
                            "SELECT d.stock_id, dp.close FROM daytrade_list d "
                            "LEFT JOIN daily_price dp ON dp.stock_id=d.stock_id "
                            "AND dp.date=(SELECT MAX(date) FROM daily_price m WHERE m.stock_id=d.stock_id) "
                            "WHERE d.date=(SELECT MAX(date) FROM daytrade_list) LIMIT 1"
                        ).fetchone()
                        if row:
                            sample_sym, prev_close = row[0], row[1]
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
                    config_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
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
                add(19, f"成交量 ({sample_sym})", False,
                    detail=f"讀取失敗: {e}", data_source="ticks.db/ticks")
        else:
            for num, nm in [(9,"昨收"),(10,"現價"),(11,"漲跌"),(12,"漲跌%"),(13,"委買比"),
                            (14,"期貨價"),(15,"期現差"),(16,"Open"),(17,"High"),(18,"Low"),(19,"成交量")]:
                add(num, nm, False, warn=True,
                    detail="today daytrade_list 無資料", data_source="daily.db/daytrade_list")

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

    # ── Config update (preserve comments via regex) ───────────────────────────
    _CONFIG_ALLOWED = {
        # 交易時間
        'trading.force_exit_time', 'trading.latest_dynamic_add_time',
        'trading.time_stop_hour',
        # 進場信號
        'signal.orb_window_minutes', 'signal.orb_volume_multiplier',
        'signal.market_drop_threshold', 'signal.limit_up_buffer',
        'signal.max_entry_gain_pct',
        'signal.futures_rocket_threshold', 'signal.futures_crash_threshold',
        'signal.futures_spread_no_buy_pct', 'signal.futures_spread_reduce_pct',
        'signal.futures_spread_sell_pct', 'signal.futures_spread_fast_reversal_pct',
        # 風控
        'risk.atr_multiplier', 'risk.risk_per_trade_pct',
        'risk.take_profit_pct', 'risk.vwap_exit_volume_ratio',
        'risk.trailing_trigger_pct', 'risk.trailing_pullback_pct',
        # 委託（dry run 時無效，未來用）
        'order.buy_order_timeout_secs', 'order.buy_retry_ticks',
        'order.futures_poll_interval_secs',
    }

    @app.post("/config/update")
    def update_config_yaml(updates: dict):
        import re as _re
        config_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
        try:
            with open(config_path, encoding="utf-8") as f:
                content = f.read()
            updated: list = []
            for dotted, value in updates.items():
                if dotted not in _CONFIG_ALLOWED:
                    continue
                leaf = dotted.split('.')[-1]
                if isinstance(value, str):
                    yaml_val = f'"{value}"'
                elif isinstance(value, bool):
                    yaml_val = 'true' if value else 'false'
                elif isinstance(value, (int, float)):
                    yaml_val = str(value)
                else:
                    continue
                pattern = rf'^(\s*{_re.escape(leaf)}:\s*)\S+?((?:\s+#.*)?)$'
                content, n = _re.subn(pattern, rf'\g<1>{yaml_val}\g<2>', content, flags=_re.MULTILINE)
                if n:
                    updated.append(dotted)
            with open(config_path, 'w', encoding="utf-8") as f:
                f.write(content)
            return {"ok": True, "updated": updated}
        except PermissionError:
            raise HTTPException(status_code=403, detail="config.yaml 唯讀，無法寫入")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

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
        _trading_params["commission_discount"] = max(0.0, min(1.0, body.commission_discount))
        _trading_params["cb_crash_pct"] = max(0.1, body.cb_crash_pct)
        _trading_params["cb_window_min"] = max(1, body.cb_window_min)
        _trading_params["cb_pause_minutes"] = max(5, body.cb_pause_minutes)
        try:
            with sqlite3.connect(_ticks_db, check_same_thread=False) as c:
                for k, v in [
                    ('max_position_capital', str(body.max_position_capital)),
                    ('max_daily_positions', str(body.max_daily_positions)),
                    ('dry_run', str(body.dry_run)),
                    ('commission_discount', str(body.commission_discount)),
                    ('cb_crash_pct', str(body.cb_crash_pct)),
                    ('cb_window_min', str(body.cb_window_min)),
                    ('cb_pause_minutes', str(body.cb_pause_minutes)),
                ]:
                    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, v))
        except Exception:
            pass
        return {"ok": True, "note": "已更新並持久化，重啟後生效", **_trading_params}

    # ── Debug: 模擬買賣（送真實 LINE 通知，不影響引擎狀態）──────────────────────
    _sim_positions: dict = {}  # symbol → {entry_price, lots, stop_loss}

    @app.post("/debug/simulate-buy")
    def simulate_buy(symbol: str = "2382", price: float = 0.0, lots: int = 1, atr: float = 0.0):
        """模擬買入：建立暫存持倉，送 LINE 通知（dry_run=False 真實發送）。"""
        from engine.risk.position import Position
        from engine.monitor.notifier import LineNotifier
        notifier = LineNotifier(dry_run=False)
        if price <= 0:
            price = 250.0
        if atr <= 0:
            atr = round(price * 0.015, 1)
        import yaml as _yaml
        _cfg_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
        try:
            with open(_cfg_path, encoding="utf-8") as _f:
                _cfg = _yaml.safe_load(_f)
            _atr_mult = float(_cfg.get("risk", {}).get("atr_multiplier", 1.8))
        except Exception:
            _atr_mult = 1.8
        pos = Position(symbol=symbol, entry_price=price, lots=lots, atr=atr, atr_multiplier=_atr_mult)
        _sim_positions[symbol] = {
            "entry_price": price, "lots": lots,
            "stop_loss": pos.stop_loss, "atr": atr,
        }
        msg = (
            f"🟢【模擬進場】{symbol}\n"
            f"價={price:.1f}  張數={lots}  ATR={atr:.2f}\n"
            f"停損={pos.stop_loss:.2f}  (ATR×{_atr_mult})"
        )
        sent = notifier.send(msg)
        return {"ok": True, "sent": sent, "symbol": symbol, "entry_price": price,
                "lots": lots, "stop_loss": pos.stop_loss, "message": msg}

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
        msg = (
            f"🔴【模擬出場】{symbol}\n"
            f"原因={reason}  {pos['entry_price']:.1f}→{price:.1f}\n"
            f"損益={pnl:+,.0f}  {pos['lots']}張\n"
            f"停損設定={pos['stop_loss']:.2f}"
        )
        sent = notifier.send(msg)
        return {"ok": True, "sent": sent, "symbol": symbol, "exit_price": price,
                "pnl": pnl, "reason": reason, "message": msg}

    @app.get("/debug/simulate-positions")
    def get_sim_positions():
        return _sim_positions

    @app.post("/debug/simulate-full-day")
    def simulate_full_day(symbol: str = "2382", ref_price: float = 250.0):
        """完整交易日模擬：選股→ORB觀察→進場→移動停利→出場，送真實 LINE 通知。"""
        import yaml
        from datetime import datetime
        from engine.data.session_state import SymbolSession
        from engine.strategy.signal_combiner import SignalCombiner
        from engine.strategy.volume_price import VolumePriceStrategy
        from engine.strategy.technical import TechnicalStrategy
        from engine.execution.budget_manager import BudgetManager
        from engine.execution.broker import round_up_tick
        from engine.risk.position import Position
        from engine.monitor.notifier import LineNotifier

        log: list[dict] = []

        def step(phase: str, msg: str, **kv):
            entry = {"phase": phase, "msg": msg, **kv}
            log.append(entry)
            return entry

        # ── 讀取 config ──────────────────────────────────────────────
        cfg_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        risk_cfg   = cfg.get("risk", {})
        signal_cfg = cfg.get("signal", {})
        trading_cfg = cfg.get("trading", {})

        atr_multiplier       = float(risk_cfg.get("atr_multiplier", 1.8))
        risk_per_trade_pct   = float(risk_cfg.get("risk_per_trade_pct", 1.0))
        trailing_trigger_pct = float(risk_cfg.get("trailing_trigger_pct", 2.0))
        trailing_pullback_pct = float(risk_cfg.get("trailing_pullback_pct", 1.5))
        take_profit_pct      = float(risk_cfg.get("take_profit_pct", 5.0))
        orb_volume_mult      = float(signal_cfg.get("orb_volume_multiplier", 1.5))
        orb_window           = int(signal_cfg.get("orb_window_minutes", 15))
        max_entry_gain_pct   = float(signal_cfg.get("max_entry_gain_pct", 4.0))
        limit_up_buffer_pct  = float(signal_cfg.get("limit_up_buffer", 4.0))
        max_pos_capital      = float(trading_cfg.get("max_position_capital", 1_000_000))

        step("設定讀取", "config.yaml 讀取完成",
             atr_multiplier=atr_multiplier, trailing_trigger_pct=trailing_trigger_pct,
             trailing_pullback_pct=trailing_pullback_pct, orb_window=orb_window,
             orb_volume_mult=orb_volume_mult)

        # ── Phase 1: 選股 ────────────────────────────────────────────
        atr = round(ref_price * 0.015, 1)          # 估算 ATR ≈ 1.5% of price
        limitup_price = round(ref_price * 1.10, 1) # 漲停 ≈ +10%
        step("選股", f"{symbol}  ref={ref_price}  ATR≈{atr}  漲停={limitup_price}  "
                     f"策略={orb_window}分ORB",
             symbol=symbol, ref_price=ref_price, atr=atr, limitup_price=limitup_price)

        # ── Phase 2: ORB 觀察期 9:00–9:14 ───────────────────────────
        sess = SymbolSession(symbol, ref_price, limitup_price, atr,
                             orb_window_minutes=orb_window)

        # 注入 15 根 1min bar（前10根盤整、後5根微升 → MA5 > MA20）
        bar_closes = [ref_price] * 10 + [
            ref_price + 0.5, ref_price + 1.0,
            ref_price + 1.0, ref_price + 1.5,
            ref_price + 2.0,
        ]
        bar_vols = [800] * 10 + [900, 950, 900, 920, 1000]

        for i, (close, vol) in enumerate(zip(bar_closes, bar_vols)):
            minute = datetime(2026, 6, 16, 9, i)
            high = round(close + 0.5, 1)
            low  = round(close - 0.5, 1)
            sess._df_1min.append({
                "open": round(close - 0.2, 1), "high": high,
                "low": low, "close": close, "volume": vol,
            })
            sess.orb.on_bar(high, low, minute)
            sess.prev_1min_volume = vol
            sess.prev_1min_close  = close

        orb_high = sess.orb.orb_high
        orb_low  = sess.orb.orb_low
        sess.orb.is_locked = True  # 模擬 9:15 鎖定
        avg_orb_vol = sum(bar_vols) / len(bar_vols)

        step("ORB鎖定", f"ORB high={orb_high}  low={orb_low}  均量={avg_orb_vol:.0f}",
             orb_high=orb_high, orb_low=orb_low, avg_orb_vol=avg_orb_vol)

        # ── Phase 3: 突破進場 9:16 ───────────────────────────────────
        breakout_price = round(orb_high + 0.5, 1)  # 比 ORB high 高一個 tick
        breakout_vol   = int(avg_orb_vol * orb_volume_mult * 1.2)  # 確保超過 1.5× 均量

        sess.curr_price = breakout_price

        # 讓 bar_builder.current_1min.volume = breakout_vol（ORB 信號需要）
        class _FakeBar:
            volume = breakout_vol
        sess.bar_builder.current_1min = _FakeBar()

        combiner = SignalCombiner(
            max_entry_gain_pct=max_entry_gain_pct,
            limit_up_buffer_pct=limit_up_buffer_pct,
        )
        vp   = VolumePriceStrategy()
        tech = TechnicalStrategy()

        entry_time = datetime(2026, 6, 16, 9, 16)
        sig = sess.evaluate(
            combiner=combiner, vp=vp, tech=tech,
            current_time=entry_time,
            positions_count=0, max_positions=3,
            not_in_position=True,
            entry_cutoff_mins=13 * 60 + 10,
            market_ok=True,
            orb_volume_multiplier=orb_volume_mult,
        )

        orb_fired = sess.orb_signal(orb_volume_mult)
        step("信號評估", f"should_enter={sig.should_enter}  orb_signal={orb_fired}  "
                         f"reason={sig.reason or '—'}  breakout_vol={breakout_vol}(需>{avg_orb_vol*orb_volume_mult:.0f})",
             should_enter=sig.should_enter, orb_signal=orb_fired,
             breakout_price=breakout_price)

        # ── 計算張數 ─────────────────────────────────────────────────
        bm   = BudgetManager(total_capital=max_pos_capital * 3,
                             risk_per_trade_pct=risk_per_trade_pct,
                             max_position_capital=max_pos_capital)
        lots = bm.calculate_lots(atr=atr, atr_multiplier=atr_multiplier,
                                 price=breakout_price, remaining_budget=max_pos_capital)
        lots = max(lots, 1)

        # ── 建立持倉 ─────────────────────────────────────────────────
        pos = Position(
            symbol=symbol,
            entry_price=breakout_price,
            lots=lots,
            atr=atr,
            atr_multiplier=atr_multiplier,
            trailing_trigger_pct=trailing_trigger_pct,
            trailing_pullback_pct=trailing_pullback_pct,
            orb_low=orb_low,
        )
        cond_stop = round_up_tick(pos.stop_loss)

        step("進場", f"價={breakout_price}  張={lots}  "
                     f"停損={pos.stop_loss:.2f}→tick捨入={cond_stop}  "
                     f"資金={breakout_price*lots*1000:,.0f}",
             entry_price=breakout_price, lots=lots,
             stop_loss=pos.stop_loss, cond_stop=cond_stop,
             capital_used=breakout_price*lots*1000)

        notifier = LineNotifier(dry_run=False)
        buy_msg = (
            f"🟢【完整模擬進場】{symbol}\n"
            f"時間=09:16  價={breakout_price}  張={lots}\n"
            f"ATR={atr}(×{atr_multiplier})  停損={pos.stop_loss:.2f}\n"
            f"觸價單={cond_stop}  ORB突破({orb_high}→{breakout_price})"
        )
        sent_buy = notifier.send(buy_msg)
        step("LINE進場通知", f"sent={sent_buy}")

        # ── Phase 4: 持倉追蹤（模擬漲到 +3%）───────────────────────
        step("持倉追蹤", f"模擬價格從 {breakout_price} 上漲到 +3%")
        sim_prices = [
            round(breakout_price * (1 + i * 0.005), 1)
            for i in range(7)  # +0%, +0.5%, +1%, +1.5%, +2%, +2.5%, +3%
        ]

        trail_step = None
        exit_reason = None
        for p in sim_prices:
            before_trail = pos.trailing_active
            r = pos.update_price(p)
            if pos.trailing_active and not before_trail:
                trail_step = step("移動停利啟動",
                                  f"價={p}  peak={pos.peak_price}  "
                                  f"漲幅={((p-breakout_price)/breakout_price*100):.1f}%",
                                  trigger_price=p, peak=pos.peak_price)
            if r:
                exit_reason = r
                step("提前出場", f"price={p}  reason={r}", price=p)
                break

        # ── Phase 5: 高點拉回 → 移動停利出場 ────────────────────────
        if exit_reason is None:
            peak = pos.peak_price
            pullback_price = round(peak * (1 - trailing_pullback_pct / 100 - 0.001), 1)
            exit_reason = pos.update_price(pullback_price)
            step("回落觸發",
                 f"peak={peak}  exit_price={pullback_price}  "
                 f"回落={(peak-pullback_price)/peak*100:.2f}%  reason={exit_reason}",
                 peak=peak, exit_price=pullback_price, reason=exit_reason)
        else:
            pullback_price = pos.peak_price  # 已提前出場

        pnl = (pullback_price - breakout_price) * lots * 1000

        sell_msg = (
            f"🔴【完整模擬出場】{symbol}\n"
            f"原因={exit_reason}  {breakout_price}→{pullback_price}  {lots}張\n"
            f"損益={pnl:+,.0f}  peak={pos.peak_price}"
        )
        sent_sell = notifier.send(sell_msg)
        step("LINE出場通知", f"sent={sent_sell}")

        step("結算",
             f"損益={pnl:+,.0f}  {'獲利' if pnl > 0 else '虧損'}  "
             f"進={breakout_price}→出={pullback_price}  {lots}張",
             pnl=pnl, win=pnl > 0, entry=breakout_price, exit=pullback_price, lots=lots)

        return {"ok": True, "pnl": pnl, "win": pnl > 0, "log": log}

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
        config_path = os.environ.get("FUBON_CONFIG", "/fubon-config/config.yaml")
        data_dir = os.environ.get("FUBON_DATA_DIR", "/fubon-data")
        log_dir = os.environ.get("FUBON_LOG_DIR", "/fubon-logs")
        ticks_db_path = os.path.join(data_dir, "ticks.db")
        daily_db_path = os.path.join(data_dir, "daily.db")
        ok = _engine.start(
            config_path=config_path,
            ticks_db=ticks_db_path,
            daily_db=daily_db_path,
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
        now = datetime.now()
        this_min = now.replace(second=0, microsecond=0)
        this_min_str  = this_min.strftime("%Y-%m-%d %H:%M:%S")
        prev_min_str  = (this_min - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        prev2_min_str = (this_min - timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S")
        orb_end = f"{today} 09:15:00"

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
            for sym, op, hi, lo, vol in c.execute(
                f"""SELECT t.symbol,
                    (SELECT price FROM ticks t2
                     WHERE t2.symbol=t.symbol AND t2.ts LIKE ?
                     ORDER BY t2.id ASC LIMIT 1) AS open,
                    MAX(t.price), MIN(t.price), SUM(t.volume)
                    FROM ticks t WHERE t.symbol IN ({ph}) AND t.ts LIKE ?
                    GROUP BY t.symbol""",
                [today_pct] + symbols + [today_pct],
            ).fetchall():
                out.setdefault(sym, {}).update(
                    open=op, high=hi, low=lo,
                    vol_lots=int((vol or 0) // 1000),
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

            # VWAP (today, volume-weighted)
            for sym, vwap in c.execute(
                f"""SELECT symbol,
                    CASE WHEN SUM(volume) > 0
                         THEN ROUND(SUM(CAST(price AS REAL) * volume) / SUM(volume), 2)
                         ELSE NULL END
                    FROM ticks WHERE ts LIKE ? AND symbol IN ({ph})
                    GROUP BY symbol""",
                [today_pct] + symbols,
            ).fetchall():
                if vwap is not None:
                    out.setdefault(sym, {})["vwap"] = vwap

            # ORB (09:00–09:15 today)
            for sym, orb_h, orb_l in c.execute(
                f"""SELECT symbol, MAX(price), MIN(price)
                    FROM ticks WHERE ts >= ? AND ts <= ? AND symbol IN ({ph})
                    GROUP BY symbol""",
                [f"{today} 09:00:00", orb_end] + symbols,
            ).fetchall():
                if orb_h is not None:
                    out.setdefault(sym, {}).update(orb_high=orb_h, orb_low=orb_l)

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
                "SELECT price, change_5min, circuit FROM index_ticks ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if idx_row:
                out["__index__"] = {
                    "price": idx_row[0],
                    "chg5": idx_row[1],
                    "circuit": idx_row[2],
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
