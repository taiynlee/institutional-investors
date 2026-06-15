"""
台股當沖自動交易引擎。
以背景執行緒運行，由 FastAPI 的 /engine/* 端點控制。
"""
import json
import logging
import os
import sqlite3
import threading
import time as time_module
import yaml
from collections import deque
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

from engine.utils.tz import TZ_TW, now_tw, today_tw, from_ts_ns
from engine.utils.market import is_market_hours, is_pre_session_time
from engine.data.fetcher.fubon_feed import FubonFeed
from engine.data.paper_tracker import PaperTracker
from engine.data.session_state import SymbolSession
from engine.data.state_store import (
    init_tables as ss_init,
    cleanup_old_intraday,
    persist_daily_tracker, persist_paper_tracker,
    restore_daily_tracker, restore_paper_tracker,
    get_setting,
)
from engine.execution.broker import FubonBroker
from engine.execution.budget_manager import BudgetManager
from engine.execution.order_manager import OrderManager
from engine.risk.daily_tracker import DailyTracker
from engine.risk.manager import RiskManager
from engine.risk.position import Position
from engine.monitor.notifier import LineNotifier
from engine.strategy.futures_signal import FuturesSignal
from engine.strategy.signal_combiner import SignalCombiner
from engine.strategy.volume_price import VolumePriceStrategy
from engine.strategy.technical import TechnicalStrategy

logger = logging.getLogger(__name__)


class TradingEngine:
    """
    交易引擎包裝類別，由 FastAPI 控制啟停。
    所有狀態透過 self._state dict 共享給 API 端點。
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state: dict = {
            "status": "stopped",   # stopped | starting | running | stopping | error
            "error": None,
            "started_at": None,
            "dry_run": True,
            "symbols": [],
            "tick_count": 0,
        }
        # 共享物件（引擎執行時填入，停止後清空）
        self.om: Optional[OrderManager] = None
        self.dt: Optional[DailyTracker] = None
        self.paper: Optional[PaperTracker] = None
        self.sessions: dict[str, SymbolSession] = {}
        self._lock = threading.Lock()
        self.session_date: Optional[str] = None  # 當前 session 的交易日期

        # 預設路徑從 env var 讀取（run.py 已 set，scheduler 直接呼 start() 時使用）
        _data = os.environ.get("FUBON_DATA_DIR", "/home/tommy0322/fubon-data")
        self._default_config = os.environ.get("FUBON_CONFIG", "/home/tommy0322/fubon-config/config.yaml")
        self._default_ticks_db = os.path.join(_data, "ticks.db")
        self._default_log_dir = os.environ.get("FUBON_LOG_DIR", "/home/tommy0322/fubon-logs")

    @property
    def status(self) -> str:
        return self._state["status"]

    def get_state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def get_positions(self) -> list:
        if self.om is None:
            return []
        return [
            {
                "symbol": sym,
                "lots": pos.lots,
                "entry_price": pos.entry_price,
                "stop_loss": pos.stop_loss,
                "atr": pos.atr,
                "curr_price": self.sessions.get(sym, None) and self.sessions[sym].curr_price,
            }
            for sym, pos in self.om.positions.items()
        ]

    def get_pnl_summary(self) -> dict:
        if self.dt is None:
            return {"actual_pnl": 0.0, "actual_trades": 0, "paper_pnl": 0.0, "paper_trades": 0}
        curr_prices = {s: sess.curr_price for s, sess in self.sessions.items()}
        unrealized = sum(
            (self.sessions[sym].curr_price - pos.entry_price) * pos.lots * 1000
            for sym, pos in self.om.positions.items() if sym in self.sessions
        ) if self.om else 0.0
        paper_unrealized = self.paper.unrealized_pnl(curr_prices) if self.paper else 0.0
        return {
            "actual_pnl": self.dt.total_pnl,
            "actual_trades": self.dt.trade_count,
            "actual_unrealized": round(unrealized),
            "daily_entries": self.dt.daily_entries,
            "max_daily": self._state.get("max_daily_positions", 3),
            "paper_pnl": self.paper.total_pnl if self.paper else 0.0,
            "paper_trades": self.paper.trade_count if self.paper else 0,
            "paper_unrealized": round(paper_unrealized),
        }

    def start(
        self,
        config_path: Optional[str] = None,
        ticks_db: Optional[str] = None,
        log_dir: Optional[str] = None,
        **_kwargs,  # 忽略廢棄的 daily_db 參數
    ) -> bool:
        config_path = config_path or self._default_config
        ticks_db    = ticks_db    or self._default_ticks_db
        log_dir     = log_dir     or self._default_log_dir
        with self._lock:
            if self._state["status"] in ("running", "starting"):
                return False
            self._stop_event.clear()
            self._state["status"] = "starting"
            self._state["error"] = None

        self._thread = threading.Thread(
            target=self._run,
            args=(config_path, ticks_db, log_dir),
            daemon=True,
            name="trading-engine",
        )
        self._thread.start()
        return True

    def stop(self) -> bool:
        with self._lock:
            if self._state["status"] not in ("running", "starting"):
                return False
            self._state["status"] = "stopping"
        self._stop_event.set()
        return True

    # ── 主執行迴圈 ────────────────────────────────────────────────────────────

    def _run(self, config_path: str, ticks_db: str, log_dir: str):
        today_str = today_tw().isoformat()
        self.session_date = today_str
        try:
            self._run_inner(config_path, ticks_db, log_dir, today_str)
        except Exception as e:
            logger.error("交易引擎異常終止: %s", e, exc_info=True)
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = str(e)
        finally:
            self.om = None
            self.paper = None
            self.sessions = {}
            if self._state["status"] not in ("error",):
                with self._lock:
                    self._state["status"] = "stopped"

    def _run_inner(self, config_path: str, ticks_db: str, log_dir: str, today_str: str):
        # ── 日誌 ─────────────────────────────────────────────────────────────
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_file = Path(log_dir) / f"dry_run_{today_str}.log"
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        engine_logger = logging.getLogger("engine")
        engine_logger.addHandler(file_handler)

        event_log_path = Path(log_dir) / f"dry_run_{today_str}.jsonl"

        def log_event(event_type: str, **kwargs):
            record = {"ts": now_tw().isoformat(), "type": event_type, **kwargs}
            try:
                with open(str(event_log_path), "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception:
                pass

        # ── 設定載入 ─────────────────────────────────────────────────────────
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        trading = cfg.get("trading", {})
        fubon_cfg = cfg.get("fubon", {})
        risk_cfg = cfg.get("risk", {})
        signal_cfg = cfg.get("signal", {})

        dry_run = True  # 永遠 dry_run（安全護欄）
        force_exit_str = trading.get("force_exit_time", "13:20")
        force_exit_h, force_exit_m = map(int, force_exit_str.split(":"))
        dynamic_add_str = trading.get("latest_dynamic_add_time", "13:10")
        _da_h, _da_m = map(int, dynamic_add_str.split(":"))
        entry_cutoff_mins = _da_h * 60 + _da_m
        max_position_capital = trading.get("max_position_capital", 0)
        max_daily_positions = trading.get("max_daily_positions", 3)
        total_capital = trading.get("max_daily_buy_amount", 10_000_000)

        # 從 config 讀取可設定參數
        atr_multiplier_cfg    = float(risk_cfg.get("atr_multiplier", 1.8))
        risk_per_trade_pct    = risk_cfg.get("risk_per_trade_pct", 1.0)
        trailing_trigger_pct  = risk_cfg.get("trailing_trigger_pct", 2.0)
        trailing_pullback_pct = float(risk_cfg.get("trailing_pullback_pct", 1.5))
        take_profit_pct       = risk_cfg.get("take_profit_pct", 5.0)
        time_stop_hour        = float(trading.get("time_stop_hour", 11))
        cb_pause_min_cfg      = int(trading.get("cb_pause_minutes", 30))
        max_entry_gain_pct    = float(signal_cfg.get("max_entry_gain_pct", 4.0))
        limit_up_buffer_pct   = float(signal_cfg.get("limit_up_buffer", 4.0))
        MKT_DAY_GATE_PCT      = float(signal_cfg.get("market_drop_threshold", -1.5))

        with self._lock:
            self._state["dry_run"] = dry_run
            self._state["max_daily_positions"] = max_daily_positions

        logger.info("=== 引擎啟動 | dry_run=%s | %s ===", dry_run, today_str)
        log_event("engine_start", dry_run=dry_run, today=today_str)

        # ── SDK 登入（帶 timeout 避免非交易時間 hang 住 FastAPI）────────────────
        from fubon_neo.sdk import FubonSDK, Mode
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        LOGIN_TIMEOUT = 30  # 秒

        def _do_login(s: FubonSDK):
            return s.login(
                fubon_cfg["id"], fubon_cfg["password"],
                fubon_cfg["cert_path"], fubon_cfg["cert_password"],
            )

        def _relogin() -> FubonSDK:
            new_sdk = FubonSDK()
            with ThreadPoolExecutor(max_workers=1) as ex:
                try:
                    res = ex.submit(_do_login, new_sdk).result(timeout=LOGIN_TIMEOUT)
                except FuturesTimeout:
                    raise RuntimeError("Fubon 重新登入逾時（富邦伺服器無回應）")
            if not res.is_success:
                raise RuntimeError(f"Fubon 重新登入失敗: {res.message}")
            new_sdk.init_realtime(Mode.Speed)
            return new_sdk

        sdk = FubonSDK()
        with ThreadPoolExecutor(max_workers=1) as _ex:
            try:
                login_result = _ex.submit(_do_login, sdk).result(timeout=LOGIN_TIMEOUT)
            except FuturesTimeout:
                raise RuntimeError("Fubon 登入逾時（富邦伺服器無回應，請確認是否為交易日）")
        if not login_result.is_success:
            raise RuntimeError(f"Fubon 登入失敗: {login_result.message}")

        # 取第一個股票帳號（供觸價單使用）
        _accounts = getattr(login_result, "data", []) or []
        _account = next(
            (a for a in _accounts if getattr(a, "account_type", "") == "stock"),
            _accounts[0] if _accounts else None,
        )
        logger.info("SDK 登入成功: %s  account=%s", fubon_cfg["id"],
                    getattr(_account, "account", "N/A"))
        sdk.init_realtime(Mode.Speed)
        rc        = sdk.marketdata.rest_client.stock
        rc_futopt = sdk.marketdata.rest_client.futopt

        # ── 標的清單（優先從 PG backend 取，fallback config） ────────────────
        symbols: list[str] = trading.get("dry_run_watchlist", ["2330"])
        try:
            import httpx as _httpx
            _r = _httpx.get("http://localhost:8000/api/daytrade/list", timeout=8)
            if _r.status_code == 200:
                _codes = [row["code"] for row in _r.json() if "code" in row]
                if _codes:
                    symbols = _codes
                    logger.info("從 PG daytrade_candidate 取得 %d 檔標的", len(symbols))
        except Exception as e:
            logger.warning("daytrade_list 讀取失敗，使用 config: %s", e)

        with self._lock:
            self._state["symbols"] = symbols

        # 股票名稱（從 PG pool 取）
        stock_names: dict[str, str] = {}
        try:
            import httpx as _httpx
            _r = _httpx.get("http://localhost:8000/api/pool", timeout=8)
            if _r.status_code == 200:
                stock_names = {s["code"]: s.get("name", "") for s in _r.json()}
        except Exception:
            pass

        def sname(sym: str) -> str:
            return stock_names.get(sym, sym)

        # ── ticks.db 初始化 ──────────────────────────────────────────────────
        with sqlite3.connect(ticks_db) as _tdb:
            _tdb.execute("PRAGMA journal_mode=WAL")
            _tdb.execute("""CREATE TABLE IF NOT EXISTS ticks (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                ts     TEXT NOT NULL,
                price  REAL NOT NULL,
                volume INTEGER NOT NULL
            )""")
            _tdb.execute("CREATE INDEX IF NOT EXISTS idx_ticks_sym ON ticks(symbol, id)")
            _tdb.execute("""CREATE TABLE IF NOT EXISTS quotes (
                symbol     TEXT PRIMARY KEY,
                bid_vol    INTEGER NOT NULL DEFAULT 0,
                ask_vol    INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )""")
            _tdb.execute("DELETE FROM quotes")
            _tdb.execute("""CREATE TABLE IF NOT EXISTS index_ticks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT NOT NULL,
                price       REAL NOT NULL,
                change_5min REAL NOT NULL DEFAULT 0,
                circuit     TEXT NOT NULL DEFAULT 'normal'
            )""")
            _tdb.execute("CREATE INDEX IF NOT EXISTS idx_idx_ts ON index_ticks(id)")
            _tdb.commit()

        ss_init(ticks_db)
        cleanup_old_intraday(ticks_db, keep_days=60)

        # ── 盤前資料：昨收 / 漲停 / ATR ──────────────────────────────────────
        sessions: dict[str, SymbolSession] = {}
        for sym in symbols:
            try:
                ticker = rc.intraday.ticker(symbol=sym)
                if isinstance(ticker, dict):
                    ref = ticker.get("referencePrice", 0) or ticker.get("previousClose", 0)
                    limitup = ticker.get("limitUpPrice", ref * 1.1)
                else:
                    ref = getattr(ticker, "referencePrice", 0) or getattr(ticker, "previousClose", 0)
                    limitup = getattr(ticker, "limitUpPrice", ref * 1.1)
            except Exception:
                ref, limitup = 100.0, 110.0

            atr = self._fetch_atr(rc, sym, today_str)
            if atr is None:
                atr = round(float(ref) * 0.015, 2)
                logger.warning("%s ATR 使用估算值 %.2f", sym, atr)
            else:
                logger.info("%s 昨收=%.0f 漲停=%.0f ATR=%.2f", sym, ref, limitup, atr)

            sessions[sym] = SymbolSession(sym, float(ref), float(limitup), float(atr))

        self.sessions = sessions


        # ── 個股期貨訊號 ──────────────────────────────────────────────────────
        futures_signals: dict[str, FuturesSignal] = {
            sym: FuturesSignal(
                no_buy_spread_pct    = signal_cfg.get("futures_spread_no_buy_pct", 0.3),
                reduce_spread_pct    = signal_cfg.get("futures_spread_reduce_pct", 0.8),
                sell_spread_pct      = signal_cfg.get("futures_spread_sell_pct", 1.5),
                fast_reversal_pct    = signal_cfg.get("futures_spread_fast_reversal_pct", 0.5),
                rocket_threshold_pct = signal_cfg.get("futures_rocket_threshold", 9.5),
                crash_threshold_pct  = signal_cfg.get("futures_crash_threshold", 9.5),
            )
            for sym in symbols
        }

        # 期貨 symbol 對照
        import datetime as _dt
        futures_sym_map: dict[str, str] = {}
        futures_ref: dict[str, float] = {}

        _products_map: dict[str, str] = {}
        try:
            from collections import defaultdict as _dd
            _products_resp = rc_futopt.intraday.products(type="FUTURE")
            _products_list = (
                _products_resp if isinstance(_products_resp, list)
                else _products_resp.get("data", []) if isinstance(_products_resp, dict)
                else []
            )
            _bucket = _dd(list)
            for _p in _products_list:
                if not isinstance(_p, dict):
                    continue
                _underlying = str(_p.get("underlyingSymbol", ""))
                _psym = str(_p.get("symbol", ""))
                _size = int(_p.get("contractSize") or 0)
                if _underlying and _underlying.isdigit() and _psym:
                    _bucket[_underlying].append((_size, _psym))
            for _sym in symbols:
                if _sym in _bucket:
                    _entries = sorted(_bucket[_sym], key=lambda x: -x[0])
                    _products_map[_sym] = _entries[0][1]
        except Exception as _pe:
            logger.warning("futopt products 查詢失敗: %s", _pe)

        for sym in symbols:
            candidates = [_products_map[sym]] if sym in _products_map else []
            for fsym in candidates:
                try:
                    t = rc_futopt.intraday.ticker(symbol=fsym)
                    ref_f = float(
                        (t.get("referencePrice") or t.get("previousClose") or
                         t.get("lastPrice") or t.get("close") or 0)
                        if isinstance(t, dict) else
                        (getattr(t, "referencePrice", 0) or getattr(t, "previousClose", 0) or 0)
                    ) if t else 0
                    if ref_f > 0:
                        futures_sym_map[sym] = fsym
                        futures_ref[sym] = ref_f
                        logger.info("期貨 symbol：%s → %s  昨結=%.2f", sym, fsym, ref_f)
                        break
                except Exception as e:
                    logger.debug("期貨 symbol %s 失敗: %s", fsym, e)

        # ── 交易模組 ─────────────────────────────────────────────────────────
        # broker 永遠 dry_run=True 作安全護欄，真實下單需明確修改此行並充分測試
        broker = FubonBroker(dry_run=True)
        broker.initialize(sdk, _account)
        bm = BudgetManager(total_capital, risk_per_trade_pct, max_position_capital)
        dt = DailyTracker()
        om = OrderManager(broker, atr_multiplier=atr_multiplier_cfg)
        rm = RiskManager(
            om,
            take_profit_pct=take_profit_pct,
            time_stop_hour=time_stop_hour,
            force_exit_time=time(force_exit_h, force_exit_m),
        )
        combiner = SignalCombiner(
            max_entry_gain_pct=max_entry_gain_pct,
            limit_up_buffer_pct=limit_up_buffer_pct,
        )
        vp = VolumePriceStrategy()
        tech = TechnicalStrategy()
        # dry_run 模式仍發 LINE 通知（讓使用者監控訊號是否正確觸發）
        notifier = LineNotifier(dry_run=False)
        paper = PaperTracker(
            take_profit_pct=take_profit_pct,
            time_stop_hour=time_stop_hour,
            force_exit_time=time(force_exit_h, force_exit_m),
            atr_multiplier=atr_multiplier_cfg,
        )

        self.om = om
        self.dt = dt
        self.paper = paper

        # 重啟恢復
        if is_market_hours():
            restore_daily_tracker(ticks_db, dt)
            # 從已出場紀錄重建 entered_symbols（避免重啟後計數歸零）
            dt.entered_symbols = {t["symbol"] for t in dt.trades}
            restore_paper_tracker(ticks_db, paper)

        # ── 大盤熔斷狀態 ──────────────────────────────────────────────────────
        # MKT_DAY_GATE_PCT 從 config 讀取（已在上方設定）
        condition_ids: dict[str, str] = {}  # symbol → 觸價單 guid

        def _cb_crash_pct() -> float:
            try:
                return max(0.1, float(get_setting(ticks_db, "cb_crash_pct", "1.5")))
            except Exception:
                return 1.5

        def _cb_pause_min() -> int:
            try:
                return max(5, int(get_setting(ticks_db, "cb_pause_minutes", str(cb_pause_min_cfg))))
            except Exception:
                return cb_pause_min_cfg

        # TAIEX 昨收（用於計算日跌幅 gate）
        _idx_ref: float = 0.0
        try:
            import urllib.request as _ur, json as _js
            _req = _ur.Request(
                "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/"},
            )
            with _ur.urlopen(_req, timeout=5) as _r:
                _d = _js.loads(_r.read())
            _y = (_d.get("msgArray") or [{}])[0].get("y", "")
            if _y and _y != "-":
                _idx_ref = float(_y)
                logger.info("TAIEX 昨收 = %.2f", _idx_ref)
        except Exception as _e:
            logger.warning("TAIEX 昨收取得失敗，日跌幅 gate 停用: %s", _e)

        _idx = {
            "prices": deque(),
            "curr": 0.0, "chg5": 0.0, "chg_day_pct": 0.0,
            "circuit": "normal", "resume": None,
        }

        def _cb_window() -> int:
            try:
                return max(1, int(get_setting(ticks_db, "cb_window_min", "5")))
            except Exception:
                return 5

        # ── tick 回呼 ─────────────────────────────────────────────────────────
        tick_count = [0]
        last_signal_eval: dict[str, datetime] = {}
        _entry_times: dict[str, datetime] = {}

        def on_tick(symbol: str, price: float, size: int, ts_ns: int):
            tick_count[0] += 1
            with self._lock:
                self._state["tick_count"] = tick_count[0]
            sess = sessions.get(symbol)
            if sess is None:
                return

            # ts 格式：完整 datetime（讓 app.py LIKE "date%" 查詢可用）
            ts_str = now_tw().strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
            try:
                with sqlite3.connect(ticks_db) as _tdb:
                    _tdb.execute(
                        "INSERT INTO ticks(symbol,ts,price,volume) VALUES(?,?,?,?)",
                        (symbol, ts_str, price, size),
                    )
            except Exception:
                pass

            sess.on_tick(price, size, ts_ns)
            now = now_tw()

            pos_before = om.positions.get(symbol)
            exit_reason = rm.on_tick(
                symbol=symbol, price=price, now=now,
                futures_signal=futures_signals.get(symbol),
                current_volume=sess.bar_builder.current_1min.volume if sess.bar_builder.current_1min else 0,
                avg_volume=float(sess.prev_1min_volume or 1),
            )
            if exit_reason and pos_before:
                pnl = (price - pos_before.entry_price) * pos_before.lots * 1000
                dt.record_trade(pnl=pnl, symbol=symbol, lots=pos_before.lots,
                                entry_price=pos_before.entry_price, exit_price=price)
                _entry_times.pop(symbol, None)
                # 取消未成交的觸價賣單
                if symbol in condition_ids:
                    broker.cancel_conditional_stop(condition_ids.pop(symbol))
                logger.info("🔴 出場 %s  原因=%s  損益=%+.0f", symbol, exit_reason, pnl)
                log_event("order_sell", symbol=symbol, reason=exit_reason,
                          entry_price=pos_before.entry_price, exit_price=price,
                          lots=pos_before.lots, pnl=pnl, cumulative_pnl=dt.total_pnl)
                notifier.send(
                    f"🔴 出場 {symbol} {sname(symbol)}\n"
                    f"原因={exit_reason}  {pos_before.entry_price:.0f}→{price:.0f}\n"
                    f"損益={pnl:+,.0f}  {pos_before.lots}張"
                )

            paper_exit = paper.on_tick(
                symbol=symbol, price=price, now=now,
                current_volume=sess.bar_builder.current_1min.volume if sess.bar_builder.current_1min else 0,
                avg_volume=float(sess.prev_1min_volume or 1),
            )
            if paper_exit:
                logger.debug("📄 [理論] 出場 %s 原因=%s", symbol, paper_exit)

            last = last_signal_eval.get(symbol)
            if last is None or (now - last).total_seconds() >= 10:
                last_signal_eval[symbol] = now
                _evaluate_signal(symbol, sess, now.time())

        def on_quote(symbol: str, bids: list, asks: list):
            sess = sessions.get(symbol)
            if sess:
                sess.on_quote(bids, asks)
            try:
                bid_vol = 0
                ask_vol = 0
                if bids:
                    if isinstance(bids[0], (list, tuple)):
                        bid_vol = sum(int(b[1] if len(b) > 1 else 1) for b in bids)
                    else:
                        bid_vol = sum(int(b.get("size", 1) if isinstance(b, dict) else 1) for b in bids)
                if asks:
                    if isinstance(asks[0], (list, tuple)):
                        ask_vol = sum(int(a[1] if len(a) > 1 else 1) for a in asks)
                    else:
                        ask_vol = sum(int(a.get("size", 1) if isinstance(a, dict) else 1) for a in asks)
                with sqlite3.connect(ticks_db) as _tdb:
                    _tdb.execute(
                        "INSERT INTO quotes(symbol,bid_vol,ask_vol,updated_at) VALUES(?,?,?,?)"
                        " ON CONFLICT(symbol) DO UPDATE SET"
                        "  bid_vol=bid_vol+excluded.bid_vol,"
                        "  ask_vol=ask_vol+excluded.ask_vol,"
                        "  updated_at=excluded.updated_at",
                        (symbol, bid_vol, ask_vol, now_tw().strftime("%H:%M:%S")),
                    )
            except Exception as e:
                logger.debug("on_quote 異常: %s", e)

        def on_index_tick(price: float, ts_ns: int):
            now = now_tw()
            _idx["curr"] = price
            _idx["prices"].append((now, price))
            cutoff = now - timedelta(minutes=_cb_window())
            while _idx["prices"] and _idx["prices"][0][0] < cutoff:
                _idx["prices"].popleft()

            # N分鐘絕對變動（顯示用）及%變動（熔斷判斷）
            if len(_idx["prices"]) >= 2:
                old_price = _idx["prices"][0][1]
                _idx["chg5"] = price - old_price
                chg5_pct = (price - old_price) / old_price * 100 if old_price > 0 else 0.0
            else:
                chg5_pct = 0.0

            # 當日漲跌幅（進場 gate 用）
            if _idx_ref > 0:
                _idx["chg_day_pct"] = (price - _idx_ref) / _idx_ref * 100

            if _idx["circuit"] == "crash" and _idx["resume"] and now >= _idx["resume"]:
                _idx["circuit"] = "normal"
                _idx["resume"] = None
                logger.info("大盤熔斷解除")

            # 熔斷判斷：N分鐘跌幅 >= cb_crash_pct（可由 UI 調整）
            _threshold_pct = _cb_crash_pct()
            if chg5_pct <= -_threshold_pct and _idx["circuit"] != "crash":
                _idx["circuit"] = "crash"
                _idx["resume"] = now + timedelta(minutes=_cb_pause_min())
                logger.warning("⚡ 大盤急跌熔斷！%d分跌 %.2f%%，暫停 %d 分鐘",
                               _cb_window(), abs(chg5_pct), _cb_pause_min())
                _emergency_liquidate_all("circuit_crash")
            elif chg5_pct >= _threshold_pct:
                if _idx["circuit"] != "surge":
                    _idx["circuit"] = "surge"
            else:
                if _idx["circuit"] == "surge":
                    _idx["circuit"] = "normal"

            try:
                with sqlite3.connect(ticks_db) as _tdb:
                    _tdb.execute(
                        "INSERT INTO index_ticks(ts,price,change_5min,circuit) VALUES(?,?,?,?)",
                        (now.strftime("%Y-%m-%d %H:%M:%S"), price,
                         round(_idx["chg5"], 2), _idx["circuit"]),
                    )
            except Exception:
                pass

        def on_futures_tick(stock_id: str, futures_price: float, ts_ns: int):
            fs = futures_signals.get(stock_id)
            if fs is None:
                return
            ref_f = futures_ref.get(stock_id, 0)
            change_pct = (futures_price - ref_f) / ref_f * 100 if ref_f else 0.0
            spot = sessions[stock_id].curr_price
            fs.update(futures_price=futures_price, spot_price=spot, futures_change_pct=change_pct)

        def _emergency_liquidate_all(reason: str):
            now = now_tw()
            for sym in list(om.positions.keys()):
                pos = om.positions.pop(sym)
                price = sessions[sym].curr_price if sym in sessions else pos.entry_price
                pnl = (price - pos.entry_price) * pos.lots * 1000
                dt.record_trade(pnl=pnl, symbol=sym, lots=pos.lots,
                                entry_price=pos.entry_price, exit_price=price)
                _entry_times.pop(sym, None)
                # 取消未成交的觸價賣單
                if sym in condition_ids:
                    broker.cancel_conditional_stop(condition_ids.pop(sym))
            for sym in list(paper.positions.keys()):
                price = sessions[sym].curr_price if sym in sessions else 0.0
                paper.close(sym, price, now, reason=reason)

        def _evaluate_signal(symbol: str, sess: SymbolSession, now_time: time):
            # 今日已進場過（含已出場）→ 不再重入，避免出場後立即重買同一支
            not_in_pos = symbol not in om.positions and symbol not in dt.entered_symbols
            # 今日已進場檔數（進場後即使出場也不歸還額度）
            trades_today = dt.daily_entries
            now = now_tw()

            # 大盤日跌幅 gate：昨收取得失敗（_idx_ref=0）時放行
            market_ok = (_idx_ref <= 0 or _idx.get("chg_day_pct", 0.0) > MKT_DAY_GATE_PCT)

            result = sess.evaluate(
                combiner=combiner, vp=vp, tech=tech,
                current_time=now_time,
                positions_count=trades_today,
                max_positions=max_daily_positions,
                not_in_position=not_in_pos,
                futures_signal=futures_signals.get(symbol),
                entry_cutoff_mins=entry_cutoff_mins,
                market_ok=market_ok,
            )
            theory = sess.evaluate_theoretical(
                combiner=combiner, vp=vp, tech=tech,
                current_time=now_time,
                futures_signal=futures_signals.get(symbol),
                entry_cutoff_mins=entry_cutoff_mins,
                market_ok=market_ok,
            )

            logger.info(
                "EVAL %s  實際=%s(%s)  理論=%s(%s)  漲幅=%.2f%%",
                symbol,
                "✓" if result.should_enter else "✗", result.reason or "ok",
                "✓" if theory.should_enter else "✗", theory.reason or "ok",
                sess.change_pct,
            )
            log_event("signal_eval",
                      symbol=symbol,
                      actual_enter=result.should_enter, actual_reason=result.reason,
                      theory_enter=theory.should_enter, theory_reason=theory.reason,
                      change_pct=round(sess.change_pct, 2))

            if result.should_enter:
                if _idx["circuit"] == "crash":
                    logger.info("大盤熔斷中，暫停進場 %s", symbol)
                else:
                    _place_order(symbol, sess, result.position_size_ratio)

            if theory.should_enter and symbol not in paper.positions:
                price = sess.curr_price
                lots = bm.calculate_lots(atr=sess.atr, atr_multiplier=atr_multiplier_cfg,
                                         price=price, remaining_budget=total_capital)
                lots = max(1, int(lots * theory.position_size_ratio))
                if paper.enter(symbol=symbol, price=price, lots=lots,
                               atr=sess.atr, now=now, orb_low=None):
                    logger.info("📄 [理論] 買進 %s  價=%.2f  張=%d", symbol, price, lots)
                    log_event("paper_buy", symbol=symbol, price=price, lots=lots)

        def _place_order(symbol: str, sess: SymbolSession, size_ratio: float):
            price = sess.curr_price
            remaining = total_capital - sum(
                p.entry_price * p.lots * 1000 for p in om.positions.values()
            )
            lots = bm.calculate_lots(atr=sess.atr, atr_multiplier=atr_multiplier_cfg,
                                     price=price, remaining_budget=remaining)
            lots = max(0, int(lots * size_ratio))
            if lots <= 0:
                logger.info("DRY RUN %s 計算張數=0，跳過", symbol)
                return

            pos = Position(
                symbol=symbol, entry_price=price, lots=lots,
                atr=sess.atr, atr_multiplier=atr_multiplier_cfg, orb_low=None,
                trailing_trigger_pct=trailing_trigger_pct,
                trailing_pullback_pct=trailing_pullback_pct,
            )
            om.positions[symbol] = pos
            _entry_times[symbol] = now_tw()
            dt.record_entry(symbol)  # 計入今日已交易檔數（出場後不歸還額度）

            logger.info("🟢 DRY RUN 買進 %s  價=%.2f  張=%d  停損=%.2f", symbol, price, lots, pos.stop_loss)
            log_event("order_buy", symbol=symbol, price=price, lots=lots,
                      stop_loss=pos.stop_loss,
                      capital_used=price * lots * 1000, atr=sess.atr)
            notifier.send(
                f"🟢 進場 {symbol} {sname(symbol)}\n"
                f"價={price:.0f}  張數={lots}  停損={pos.stop_loss:.2f}"
            )
            # 掛觸價停損賣單（dry_run 時只 log）
            cid = broker.place_conditional_stop(
                symbol=symbol, lots=lots, stop_price=pos.stop_loss, trade_date=today_str
            )
            if cid:
                condition_ids[symbol] = cid

        # ── WebSocket 啟動 ─────────────────────────────────────────────────────
        feed = FubonFeed(
            sdk=sdk,
            symbols=symbols,
            on_tick=on_tick,
            on_quote=on_quote,
            subscribe_quote=True,
            futures_sym_map=futures_sym_map,
            on_futures_tick=on_futures_tick,
            on_index_tick=on_index_tick,
            relogin_fn=_relogin,
        )

        feed.connect()
        logger.info("WebSocket 已連線，等待 tick...")

        with self._lock:
            self._state["status"] = "running"
            self._state["started_at"] = now_tw().isoformat()

        last_persist_min = -1
        try:
            while not self._stop_event.is_set():
                time_module.sleep(1)
                curr_min = now_tw().minute
                if curr_min != last_persist_min:
                    last_persist_min = curr_min
                    persist_daily_tracker(ticks_db, dt, dry_run=dry_run)
                    persist_paper_tracker(ticks_db, paper, dry_run=dry_run)
        finally:
            feed.disconnect()
            persist_daily_tracker(ticks_db, dt, dry_run=dry_run)
            persist_paper_tracker(ticks_db, paper, dry_run=dry_run)
            logger.info("=== 引擎關閉 | 實際損益=%.0f | 理論損益=%.0f | tick=%d筆 ===",
                        dt.total_pnl, paper.total_pnl, tick_count[0])
            log_event("engine_stop", actual_pnl=dt.total_pnl, paper_pnl=paper.total_pnl,
                      tick_count=tick_count[0])
            engine_logger.removeHandler(file_handler)

    @staticmethod
    def _fetch_atr(rc, symbol: str, today_str: str, period: int = 14) -> Optional[float]:
        try:
            r = rc.historical.candles(symbol=symbol, from_="2026-05-01", to=today_str, timeframe="D")
            candles = r.get("data", []) if isinstance(r, dict) else r
            if not candles or len(candles) < period + 1:
                return None
            trs = []
            for i in range(1, len(candles)):
                c = candles[i]
                if isinstance(c, dict):
                    h, l, pc = c["high"], c["low"], candles[i - 1]["close"]
                else:
                    h, l, pc = c.high, c.low, candles[i - 1].close
                tr = max(h - l, abs(h - pc), abs(l - pc))
                trs.append(tr)
            if len(trs) < period:
                return None
            atr = sum(trs[:period]) / period
            for tr in trs[period:]:
                atr = (atr * (period - 1) + tr) / period
            return round(atr, 2)
        except Exception as e:
            logger.warning("ATR fetch 失敗 %s: %s", symbol, e)
            return None


# 全域單例，由 main.py 初始化，app.py 引用
engine = TradingEngine()
