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
from engine.data.session_state import SymbolSession
from engine.data.state_store import (
    init_tables as ss_init,
    cleanup_old_intraday,
    persist_daily_tracker,
    restore_daily_tracker,
    get_setting,
)
from engine.execution.broker import FubonBroker, tw_tick_size, round_down_tick, round_up_tick
from engine.execution.budget_manager import BudgetManager
from engine.execution.order_manager import OrderManager
from engine.risk.daily_tracker import DailyTracker
from engine.risk.manager import RiskManager
from engine.risk.position import Position
from engine.monitor.notifier import LineNotifier
from engine.strategy.futures_signal import FuturesSignal
from engine.strategy.signal_combiner import SignalCombiner

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
            "signal_log": [],      # 訊號 log (newest first, max 200)
        }
        # 共享物件（引擎執行時填入，停止後清空）
        self.om: Optional[OrderManager] = None
        self.dt: Optional[DailyTracker] = None
        self.paper = None  # 保留欄位相容性
        self.sessions: dict[str, SymbolSession] = {}
        self._lock = threading.Lock()
        self.session_date: Optional[str] = None  # 當前 session 的交易日期
        # SDK/account 供外部手動下單使用
        self.sdk = None
        self.account = None
        # 個股期貨 symbol map 和即時快取
        self.futures_sym_map: dict[str, str] = {}   # stock_id → futures symbol
        self.futures_signals: dict = {}              # stock_id → FuturesSignal
        # 觸價單 GUID 記錄，供外部（API）手動取消
        self.condition_ids: dict[str, dict] = {}     # symbol → {"sl": guid, "tp": guid}
        self.broker = None                           # FubonBroker 實例（引擎執行期間有效）

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
                "take_profit": pos.take_profit,
                "curr_price": self.sessions.get(sym, None) and self.sessions[sym].curr_price,
            }
            for sym, pos in self.om.positions.items()
        ]

    def get_pnl_summary(self) -> dict:
        if self.dt is None:
            return {"actual_pnl": 0.0, "actual_trades": 0, "paper_pnl": 0.0, "paper_trades": 0}
        unrealized = sum(
            (self.sessions[sym].curr_price - pos.entry_price) * pos.lots * 1000
            for sym, pos in self.om.positions.items() if sym in self.sessions
        ) if self.om else 0.0
        return {
            "actual_pnl": self.dt.total_pnl,
            "actual_trades": self.dt.trade_count,
            "actual_unrealized": round(unrealized),
            "daily_entries": self.dt.daily_entries,
            "max_daily": self._state.get("max_daily_positions", 5),
            "paper_pnl": 0.0,
            "paper_trades": 0,
            "paper_unrealized": 0,
        }

    def start(
        self,
        config_path: Optional[str] = None,
        ticks_db: Optional[str] = None,
        log_dir: Optional[str] = None,
        **_kwargs,  # 忽略廢棄參數
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
            self.sdk = None
            self.account = None
            self.condition_ids = {}
            self.broker = None
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

        # ── 設定載入（只讀富邦帳密，其餘參數全從 PG trading_settings 熱重載）─────
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        fubon_cfg = cfg.get("fubon", {})

        dry_run = True  # 永遠 dry_run（安全護欄）

        # 初始值 hardcoded；運行時由 ticks.db settings（同步自 PG）熱重載
        force_exit_str       = "13:20"
        dynamic_add_str      = "13:10"
        max_position_capital = 1_000_000
        max_daily_positions  = 5
        total_capital        = 10_000_000

        # ── 熱重載 helpers：每次被呼叫時從 ticks.db 讀取最新值 ─────────────────
        def _gs(key: str, default: str) -> str:
            return get_setting(ticks_db, key, default)

        def _max_position_capital() -> float:
            try: return max(0, float(_gs("max_position_capital", str(max_position_capital))))
            except Exception: return max_position_capital

        def _is_dry_run() -> bool:
            try: return str(_gs("dry_run", "true")).lower() in ("true", "1", "yes")
            except Exception: return True

        def _max_daily_positions() -> int:
            try: return max(1, int(_gs("max_daily_positions", str(max_daily_positions))))
            except Exception: return max_daily_positions

        def _force_exit_time() -> time:
            try:
                s = _gs("force_exit_time", force_exit_str)
                h, m = map(int, s.split(":"))
                return time(h, m)
            except Exception:
                h, m = map(int, force_exit_str.split(":"))
                return time(h, m)

        def _entry_cutoff() -> int:
            try:
                s = _gs("latest_dynamic_add_time", dynamic_add_str)
                h, m = map(int, s.split(":"))
                return h * 60 + m
            except Exception:
                h, m = map(int, dynamic_add_str.split(":"))
                return h * 60 + m

        def _tick_rise_threshold() -> int:
            try: return max(1, int(_gs("tick_rise_threshold", "4")))
            except Exception: return 4

        def _stop_loss_ticks() -> int:
            try: return max(1, int(_gs("stop_loss_ticks", "4")))
            except Exception: return 4

        def _take_profit_add_pct() -> float:
            try: return max(0.1, float(_gs("take_profit_add_pct", "4.0")))
            except Exception: return 4.0

        def _max_change_pct() -> float:
            try: return max(0.1, float(_gs("max_change_pct", "5.0")))
            except Exception: return 5.0

        def _entry_start_mins() -> int:
            try:
                s = _gs("entry_start_time", "09:15")
                h, m = map(int, s.split(":"))
                return h * 60 + m
            except Exception: return 9 * 60 + 15

        def _tick_window_seconds() -> int:
            try: return max(10, int(_gs("tick_window_seconds", "60")))
            except Exception: return 60

        def _vol_ratio_coefficient() -> float:
            try: return max(0.1, float(_gs("vol_ratio_coefficient", "1.3")))
            except Exception: return 1.3

        def _vol_ratio_min_pct() -> float:
            mins_after_open = max(0, _entry_start_mins() - 9 * 60)
            return round(mins_after_open * _vol_ratio_coefficient(), 1)

        def _amplitude_min_pct() -> float:
            try: return max(0.0, float(_gs("amplitude_min_pct", "3.0")))
            except Exception: return 3.0

        def _bid_1m_pct_threshold() -> float:
            try: return max(0.0, min(100.0, float(_gs("bid_1m_pct_threshold", "70.0"))))
            except Exception: return 70.0

        def _check_not_in_position() -> bool:
            return str(_gs("check_not_in_position", "True")).lower() in ("true", "1", "yes")

        def _check_futures_signal() -> bool:
            return str(_gs("check_futures_signal", "True")).lower() in ("true", "1", "yes")

        def _bid_pct_threshold() -> float:
            try: return max(0.0, float(_gs("bid_pct_threshold", "60.0")))
            except Exception: return 60.0

        with self._lock:
            self._state["dry_run"] = dry_run
            self._state["max_daily_positions"] = max_daily_positions

        logger.info("=== 引擎啟動 | dry_run=%s | %s ===", dry_run, today_str)
        log_event("engine_start", dry_run=dry_run, today=today_str)

        # 每日清空 quotes 累積表，確保外盤/內盤比例只統計今日成交
        try:
            with sqlite3.connect(ticks_db) as _tdb:
                _tdb.execute("DELETE FROM quotes")
            logger.info("quotes 表已清空（新交易日）")
        except Exception:
            pass

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

        # ── 標的清單（從 PG backend 取，fallback hardcoded） ────────────────
        symbols: list[str] = ["2330"]
        _avg_vol5: dict[str, float] = {}   # {symbol: 5日均量(張)}
        try:
            import httpx as _httpx
            _r = _httpx.get("http://localhost:8000/api/daytrade/list", timeout=8)
            if _r.status_code == 200:
                _data = _r.json()
                _codes = [s["stock_id"] for s in _data.get("stocks", []) if "stock_id" in s]
                if _codes:
                    symbols = _codes
                    _avg_vol5 = {
                        s["stock_id"]: float(s.get("avg_vol5") or 0)
                        for s in _data.get("stocks", [])
                        if "stock_id" in s
                    }
                    logger.info("從 PG daytrade_candidate 取得 %d 檔標的（%s）", len(symbols), _data.get("date", "?"))
        except Exception as e:
            logger.warning("daytrade_list 讀取失敗，使用 config: %s", e)

        # ── 盤前：過濾不可現股當沖的股票 ───────────────────────────────────
        _before = len(symbols)
        _restricted: set[str] = set()
        import urllib.request as _ureq

        # 1. 全額交割股（MI_MARGN 註記含 'O'）→ 不可當沖
        try:
            _req = _ureq.Request(
                "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN",
                headers={"User-Agent": "Mozilla/5.0", "accept": "application/json"},
            )
            with _ureq.urlopen(_req, timeout=10) as _resp:
                _margn = json.loads(_resp.read().decode("utf-8"))
            _full_cash = {row["股票代號"].strip() for row in _margn if "O" in row.get("註記", "")}
            _restricted |= _full_cash
            logger.info("全額交割股 %d 檔", len(_full_cash))
        except Exception as _e:
            logger.warning("全額交割清單取得失敗（略過）: %s", _e)

        # 2. 處置股票（TWT85U 分盤集合競價欄位含 '**'）→ 不可當沖
        try:
            _req2 = _ureq.Request(
                "https://www.twse.com.tw/exchangeReport/TWT85U?response=json",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.twse.com.tw/"},
            )
            with _ureq.urlopen(_req2, timeout=10) as _resp2:
                _twtdata = json.loads(_resp2.read().decode("utf-8"))
            _disposal = {
                row[0].strip()
                for row in _twtdata.get("data", [])
                if "**" in (row[2] if len(row) > 2 else "")
            }
            _restricted |= _disposal
            logger.info("處置股票（分盤）%d 檔: %s", len(_disposal), list(_disposal))
        except Exception as _e:
            logger.warning("處置股票清單取得失敗（略過）: %s", _e)

        if _restricted:
            _removed = [s for s in symbols if s in _restricted]
            symbols   = [s for s in symbols if s not in _restricted]
            if _removed:
                logger.info("排除不可當沖標的 %d 檔: %s", len(_removed), _removed)

        logger.info("當沖標的最終 %d 檔（原 %d 檔）", len(symbols), _before)

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
                circuit     TEXT NOT NULL DEFAULT 'normal',
                chg_day_pct REAL NOT NULL DEFAULT 0
            )""")
            try:
                _tdb.execute("ALTER TABLE index_ticks ADD COLUMN chg_day_pct REAL NOT NULL DEFAULT 0")
            except Exception:
                pass
            _tdb.execute("CREATE INDEX IF NOT EXISTS idx_idx_ts ON index_ticks(id)")
            _tdb.commit()

        ss_init(ticks_db)
        cleanup_old_intraday(ticks_db, keep_days=60)

        # ── 盤前資料：昨收 / 漲停 ──────────────────────────────────────────────
        sessions: dict[str, SymbolSession] = {}
        for sym in symbols:
            try:
                ticker = rc.intraday.ticker(symbol=sym)
                if isinstance(ticker, dict):
                    ref     = ticker.get("referencePrice", 0) or ticker.get("previousClose", 0)
                    limitup = ticker.get("limitUpPrice", ref * 1.1)
                else:
                    ref     = getattr(ticker, "referencePrice", 0) or getattr(ticker, "previousClose", 0)
                    limitup = getattr(ticker, "limitUpPrice", ref * 1.1)
            except Exception:
                ref, limitup = 100.0, 110.0
            logger.info("%s 昨收=%.0f 漲停=%.0f", sym, ref, limitup)
            sessions[sym] = SymbolSession(sym, float(ref), float(limitup))

        self.sessions = sessions

        # ── 個股期貨訊號 ──────────────────────────────────────────────────────
        futures_signals: dict[str, FuturesSignal] = {sym: FuturesSignal() for sym in symbols}

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
                if isinstance(_p, dict):
                    _underlying = str(_p.get("underlyingSymbol", "") or "")
                    _psym       = str(_p.get("symbol", "") or "")
                    _size       = int(_p.get("contractSize") or 0)
                else:
                    _underlying = str(getattr(_p, "underlyingSymbol", "") or "")
                    _psym       = str(getattr(_p, "symbol", "") or "")
                    _size       = int(getattr(_p, "contractSize", 0) or 0)
                if _underlying and _psym:
                    _bucket[_underlying].append((_size, _psym))
            logger.info("futopt products: %d 標的有個股期  map keys(前10)=%s",
                        len(_bucket), list(_bucket.keys())[:10])
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

        # 暴露給 API endpoint 使用
        self.futures_sym_map = futures_sym_map
        self.futures_signals = futures_signals

        # ── 交易模組 ─────────────────────────────────────────────────────────
        # broker 永遠 dry_run=True 作安全護欄，真實下單需明確修改此行並充分測試
        broker = FubonBroker(dry_run=True)
        broker.initialize(sdk, _account)
        self.broker = broker
        bm = BudgetManager(max_per_entry=_max_position_capital())
        dt = DailyTracker()
        om = OrderManager(broker)
        rm = RiskManager(om, force_exit_time=_force_exit_time())
        combiner = SignalCombiner(
            max_change_pct=_max_change_pct(),
        )
        notifier = LineNotifier(dry_run=False)

        self.om = om
        self.dt = dt
        self.sdk = sdk
        self.account = _account

        # 重啟恢復
        if is_market_hours():
            restore_daily_tracker(ticks_db, dt)

        # ── 大盤資料 ─────────────────────────────────────────────────────────
        condition_ids: dict[str, dict] = {}  # symbol → {"sl": guid, "tp": guid}
        self.condition_ids = condition_ids   # 暴露給 API 使用（同一物件引用）

        # TAIEX 昨收（用於計算日漲幅 gate）
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
            logger.warning("TAIEX 昨收取得失敗，大盤 gate 停用: %s", _e)

        _idx = {
            "prices": deque(),
            "curr": 0.0, "chg5": 0.0, "chg_day_pct": 0.0,
        }

        # ── tick 回呼 ─────────────────────────────────────────────────────────
        tick_count = [0]
        last_signal_eval: dict[str, datetime] = {}
        _entry_times: dict[str, datetime] = {}
        _cum_bid: dict[str, int] = {}     # 累積外盤成交量（成交價 >= 賣一，主動買方）
        _cum_ask: dict[str, int] = {}     # 累積內盤成交量（成交價 <= 買一，主動賣方）
        _cum_vol: dict[str, int] = {}     # 累積今日成交量（股，用於 vol_ratio 計算）
        _daily_high: dict[str, float] = {}  # 今日最高成交價
        _daily_low:  dict[str, float] = {}  # 今日最低成交價
        _log_cleared_date = [None]     # 追蹤清除日期

        def _append_log(entry: dict):
            """新增訊號 log，最新在最前；每個交易日 09:00 清除前一天資料。"""
            now_d = today_tw().isoformat()
            now_t = now_tw()
            if (now_d != _log_cleared_date[0]
                    and now_t.hour == 9 and now_t.minute <= 5):
                with self._lock:
                    self._state["signal_log"] = []
                _log_cleared_date[0] = now_d
            with self._lock:
                log: list = self._state["signal_log"]
                log.insert(0, entry)
                if len(log) > 200:
                    self._state["signal_log"] = log[:200]

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

            _cum_vol[symbol] = _cum_vol.get(symbol, 0) + size
            _daily_high[symbol] = max(_daily_high.get(symbol, price), price)
            _daily_low[symbol]  = min(_daily_low.get(symbol, price), price)
            sess.on_tick(price, size, ts_ns, tick_window_seconds=_tick_window_seconds())
            now = now_tw()

            pos_before = om.positions.get(symbol)
            exit_reason = rm.on_tick(symbol=symbol, price=price, now=now)
            if exit_reason and pos_before:
                pnl = (price - pos_before.entry_price) * pos_before.lots * 1000
                dt.record_trade(pnl=pnl, symbol=symbol, lots=pos_before.lots,
                                entry_price=pos_before.entry_price, exit_price=price)
                _entry_times.pop(symbol, None)
                # 取消未成交的停損/停利觸價單，並主動賣出（dry_run=True 時只 log）
                if symbol in condition_ids:
                    cids = condition_ids.pop(symbol)
                    if cids.get("sl"):
                        broker.cancel_conditional_order(cids["sl"])
                    if cids.get("tp"):
                        broker.cancel_conditional_order(cids["tp"])
                try:
                    broker.sell(symbol, pos_before.lots, price, reason=exit_reason)
                except Exception as _se:
                    logger.error("賣出下單失敗 %s: %s", symbol, _se)
                logger.info("🔴 出場 %s  原因=%s  損益=%+.0f", symbol, exit_reason, pnl)
                log_event("order_sell", symbol=symbol, reason=exit_reason,
                          entry_price=pos_before.entry_price, exit_price=price,
                          lots=pos_before.lots, pnl=pnl, cumulative_pnl=dt.total_pnl)
                _append_log({
                    "type": "sell",
                    "ts": now_tw().strftime("%H:%M:%S"),
                    "symbol": symbol,
                    "name": sname(symbol),
                    "lots": pos_before.lots,
                    "entry_price": pos_before.entry_price,
                    "exit_price": price,
                    "pnl": round(pnl),
                    "reason": exit_reason,
                })
                notifier.send(
                    f"🔴 出場 {symbol} {sname(symbol)}\n"
                    f"原因={exit_reason}  {pos_before.entry_price:.0f}→{price:.0f}\n"
                    f"損益={pnl:+,.0f}  {pos_before.lots}張",
                    msg_type="auto_exit",
                )

            last = last_signal_eval.get(symbol)
            if last is None or (now - last).total_seconds() >= 10:
                last_signal_eval[symbol] = now
                _evaluate_signal(symbol, sess, now.time())

        def on_quote(symbol: str, bids: list, asks: list):
            sess = sessions.get(symbol)
            if sess:
                sess.on_quote(bids, asks)
            # 計算買賣量（不應拋例外）
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
            # in-memory 更新必須先做，不受 SQLite 例外影響
            _cum_bid[symbol] = _cum_bid.get(symbol, 0) + bid_vol
            _cum_ask[symbol] = _cum_ask.get(symbol, 0) + ask_vol
            if sess:
                sess.on_bid_ask_tick(bid_vol, ask_vol, _tick_window_seconds())
            # SQLite 持久化（best-effort）
            try:
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
                logger.debug("on_quote SQLite 異常: %s", e)

        def on_index_tick(price: float, ts_ns: int):
            now = now_tw()
            _idx["curr"] = price
            _idx["prices"].append((now, price))
            cutoff = now - timedelta(minutes=5)
            while _idx["prices"] and _idx["prices"][0][0] < cutoff:
                _idx["prices"].popleft()

            if len(_idx["prices"]) >= 2:
                old_price = _idx["prices"][0][1]
                _idx["chg5"] = price - old_price
            else:
                _idx["chg5"] = 0.0

            # 日漲跌幅（進場 gate 用）
            if _idx_ref > 0:
                _idx["chg_day_pct"] = (price - _idx_ref) / _idx_ref * 100

            try:
                with sqlite3.connect(ticks_db) as _tdb:
                    _tdb.execute(
                        "INSERT INTO index_ticks(ts,price,change_5min,circuit,chg_day_pct) VALUES(?,?,?,?,?)",
                        (now.strftime("%Y-%m-%d %H:%M:%S"), price,
                         round(_idx["chg5"], 2), "normal",
                         round(_idx["chg_day_pct"], 4)),
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

        def _evaluate_signal(symbol: str, sess: SymbolSession, now_time: time):
            not_in_pos = symbol not in om.positions  # 同標的可重複進場（只要當下未持倉）
            trades_today = dt.daily_entries
            now = now_tw()

            # 熱重載可調參數
            combiner.max_change_pct = _max_change_pct()
            rm.force_exit_time = _force_exit_time()
            self._state["dry_run"] = _is_dry_run()  # 讓 WebSocket push 反映最新設定

            # 大盤日漲幅 gate：昨收取得失敗（_idx_ref=0）時放行
            market_chg = _idx.get("chg_day_pct", 0.0) if _idx_ref > 0 else 999.0

            _b = _cum_bid.get(symbol, 0)
            _a = _cum_ask.get(symbol, 0)
            _bp = _b / (_b + _a) * 100 if (_b + _a) > 0 else 50.0
            _avg5 = _avg_vol5.get(symbol, 0)
            _vr = (_cum_vol.get(symbol, 0) / 1000 / _avg5 * 100) if _avg5 > 0 else 100.0
            _ref_price = sess.reference_price
            _h = _daily_high.get(symbol, 0)
            _l = _daily_low.get(symbol, _h)
            _amp = (_h - _l) / _ref_price * 100 if _ref_price > 0 and _h > _l else 0.0
            _thr = _tick_rise_threshold()
            result = sess.evaluate(
                combiner=combiner,
                current_time=now_time,
                positions_count=trades_today,
                max_positions=_max_daily_positions(),
                not_in_position=not_in_pos,
                tick_rise_threshold=_thr,
                futures_signal=futures_signals.get(symbol),
                entry_cutoff_mins=_entry_cutoff(),
                entry_start_mins=_entry_start_mins(),
                bid_pct=_bp,
                bid_pct_threshold=_bid_pct_threshold(),
                check_not_in_position=_check_not_in_position(),
                check_futures_signal=_check_futures_signal(),
                vol_ratio=_vr,
                vol_ratio_min_pct=_vol_ratio_min_pct(),
                amplitude_pct=_amp,
                amplitude_min_pct=_amplitude_min_pct(),
                bid_1m_pct=sess.bid_pct_window,
                bid_1m_pct_threshold=_bid_1m_pct_threshold(),
            )
            # 只在 60s tick 條件達標時才記 log（避免噪音）
            if sess.tick_rise_60s >= _thr:
                _append_log({
                    "type": "eval",
                    "ts": now_tw().strftime("%H:%M:%S"),
                    "symbol": symbol,
                    "name": sname(symbol),
                    "passed": result.should_enter,
                    "reason": result.reason or "ok",
                    # 條件⑤ 動能
                    "tick_rise": round(sess.tick_rise_60s, 1),
                    "bid_1m_pct": round(sess.bid_pct_window, 1),   # 觀察窗口外盤%（條件⑤備用路徑）
                    # 條件⑦ 累積買盤
                    "bid_pct": round(_bp, 1),
                    # 條件⑧ 量比
                    "vol_ratio": round(_vr, 1),
                    "vol_ratio_thr": round(_vol_ratio_min_pct(), 1),  # 當下門檻（隨時間變動）
                    # 條件⑨ 振幅
                    "amplitude_pct": round(_amp, 2),
                    # 個股漲幅（條件④）
                    "change_pct": round(sess.change_pct, 2),
                })
            theory = sess.evaluate_theoretical(
                combiner=combiner,
                current_time=now_time,
                tick_rise_threshold=_tick_rise_threshold(),
                futures_signal=futures_signals.get(symbol),
                entry_cutoff_mins=_entry_cutoff(),
                entry_start_mins=_entry_start_mins(),
                check_futures_signal=_check_futures_signal(),
                bid_pct_threshold=_bid_pct_threshold(),
                vol_ratio=_vr,
                vol_ratio_min_pct=_vol_ratio_min_pct(),
                amplitude_pct=_amp,
                amplitude_min_pct=_amplitude_min_pct(),
                bid_1m_pct=sess.bid_pct_window,
                bid_1m_pct_threshold=_bid_1m_pct_threshold(),
            )

            logger.info(
                "EVAL %s  實際=%s(%s)  理論=%s(%s)  漲幅=%.2f%%  60s漲=%+.1ftick",
                symbol,
                "✓" if result.should_enter else "✗", result.reason or "ok",
                "✓" if theory.should_enter else "✗", theory.reason or "ok",
                sess.change_pct, sess.tick_rise_60s,
            )
            log_event("signal_eval",
                      symbol=symbol,
                      actual_enter=result.should_enter, actual_reason=result.reason,
                      theory_enter=theory.should_enter, theory_reason=theory.reason,
                      change_pct=round(sess.change_pct, 2),
                      tick_rise_60s=round(sess.tick_rise_60s, 1))

            if result.should_enter:
                _place_order(symbol, sess)

        def _place_order(symbol: str, sess: SymbolSession):
            broker.dry_run = _is_dry_run()  # 每次下單前同步最新 dry_run 設定
            price = sess.curr_price
            remaining = total_capital - sum(
                p.entry_price * p.lots * 1000 for p in om.positions.values()
            )
            bm.max_per_entry = _max_position_capital()
            lots = bm.calculate_lots(price=price, remaining_budget=remaining)
            if lots <= 0:
                logger.info("DRY RUN %s 計算張數=0，跳過", symbol)
                return

            # 停損：進場價向下 N 個 tick，向上捨入（確保觸價門檻不超過）
            sl_ticks = _stop_loss_ticks()
            ts = tw_tick_size(price)
            stop_loss = round_up_tick(price - sl_ticks * ts)

            # 停利：ref_price × (1 + (進場漲幅 + add_pct) / 100)，向下捨入 tick
            ref = sess.reference_price
            change_at_entry = (price - ref) / ref * 100 if ref > 0 else 0.0
            tp_raw = ref * (1 + (change_at_entry + _take_profit_add_pct()) / 100)
            take_profit = round_down_tick(tp_raw)

            pos = Position(
                symbol=symbol,
                entry_price=price,
                lots=lots,
                stop_loss=stop_loss,
                take_profit=take_profit,
            )
            om.positions[symbol] = pos
            _entry_times[symbol] = now_tw()
            dt.record_entry(symbol)

            # 實際買進（dry_run=True 時只 log，不送單）
            # order_type=Stock（現買），與觸價賣單一致
            try:
                broker.buy(symbol, lots, price)
            except Exception as _be:
                logger.error("買進下單失敗 %s: %s", symbol, _be)

            mode_tag = "DRY RUN" if broker.dry_run else "買進"
            logger.info(
                "🟢 %s %s  價=%.2f  張=%d  停損=%.2f  停利=%.2f",
                mode_tag, symbol, price, lots, stop_loss, take_profit,
            )
            log_event("order_buy", symbol=symbol, price=price, lots=lots,
                      stop_loss=stop_loss, take_profit=take_profit,
                      capital_used=price * lots * 1000)
            _append_log({
                "type": "buy",
                "ts": now_tw().strftime("%H:%M:%S"),
                "symbol": symbol,
                "name": sname(symbol),
                "lots": lots,
                "price": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "dry_run": broker.dry_run,
            })
            notifier.send(
                f"🟢 進場 {symbol} {sname(symbol)}\n"
                f"價={price:.0f}  張數={lots}\n"
                f"停損={stop_loss:.2f}  停利={take_profit:.2f}",
                msg_type="auto_entry",
            )

            # 掛觸價停損/停利賣單（dry_run 時只 log）
            trade_date_slash = today_str.replace("-", "/")  # Fubon SDK 需要 YYYY/MM/DD
            sl_guid = broker.place_conditional_stop(
                symbol=symbol, lots=lots, stop_price=stop_loss, trade_date=trade_date_slash
            )
            tp_guid = broker.place_conditional_take_profit(
                symbol=symbol, lots=lots, trigger_price=take_profit, trade_date=trade_date_slash
            )
            condition_ids[symbol] = {"sl": sl_guid, "tp": tp_guid}

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
        _force_exit_done: set[str] = set()
        _warned_1315 = False
        try:
            while not self._stop_event.is_set():
                time_module.sleep(1)
                now_loop = now_tw()
                curr_min = now_loop.minute
                if curr_min != last_persist_min:
                    last_persist_min = curr_min
                    persist_daily_tracker(ticks_db, dt, dry_run=dry_run)

                # ── 13:15 持倉預警（不依賴 tick，只送一次）────────────────────
                if not _warned_1315 and now_loop.time() >= time(13, 15) and om.positions:
                    _warned_1315 = True
                    pos_summary = "、".join(
                        f"{s}×{p.lots}張({p.entry_price:.0f}元)"
                        for s, p in list(om.positions.items())
                    )
                    notifier.send(
                        f"⚠️ 收盤前仍有持倉\n"
                        f"{pos_summary}\n"
                        f"距強制出場約 5 分鐘（{_force_exit_time().strftime('%H:%M')}）",
                        msg_type="warning",
                    )
                    logger.warning("13:15 持倉預警：%s", pos_summary)

                # ── 時間強制出場（主迴圈兜底，不依賴 WebSocket tick）───────────
                # 當跌停無成交或 WS 斷線導致 on_tick 不回調時確保必定出場
                if now_loop.time() >= _force_exit_time() and om.positions:
                    for sym in list(om.positions.keys()):
                        if sym in _force_exit_done:
                            continue
                        _force_exit_done.add(sym)
                        pos = om.positions.get(sym)
                        if pos is None:
                            continue  # 已由 tick 路徑出場，跳過

                        curr = (sessions[sym].curr_price
                                if sym in sessions and sessions[sym].curr_price
                                else pos.entry_price)
                        pnl_est = (curr - pos.entry_price) * pos.lots * 1000

                        logger.warning(
                            "⏰ 強制時間出場（主迴圈）%s %d張 @ %.2f，估損益=%+.0f",
                            sym, pos.lots, curr, pnl_est,
                        )

                        # 先取消未到期的觸價單
                        cids = condition_ids.pop(sym, {})
                        if cids.get("sl"):
                            broker.cancel_conditional_order(cids["sl"])
                        if cids.get("tp"):
                            broker.cancel_conditional_order(cids["tp"])

                        # ① 市價 IOC（快速成交優先）
                        try:
                            broker.sell(sym, pos.lots, 0.0, reason="force_exit_loop")
                        except Exception as _fe1:
                            logger.error("強制出場 IOC 失敗 %s: %s", sym, _fe1)

                        # ② 備援 ROD 限價賣（防跌停 IOC 無人承接；
                        #    若 IOC 已成交，券商會因無庫存拒絕此單）
                        try:
                            broker.limit_sell(sym, pos.lots, curr)
                        except Exception as _fe2:
                            logger.warning("強制出場備援 ROD 失敗 %s: %s", sym, _fe2)

                        # 從引擎記憶中移除持倉
                        om.positions.pop(sym, None)
                        _entry_times.pop(sym, None)
                        dt.record_trade(
                            pnl=pnl_est, symbol=sym, lots=pos.lots,
                            entry_price=pos.entry_price, exit_price=curr,
                        )
                        log_event("order_sell", symbol=sym, reason="force_exit_loop",
                                  entry_price=pos.entry_price, exit_price=curr,
                                  lots=pos.lots, pnl=pnl_est,
                                  cumulative_pnl=dt.total_pnl)
                        _append_log({
                            "type": "sell",
                            "ts": now_loop.strftime("%H:%M:%S"),
                            "symbol": sym,
                            "name": sname(sym),
                            "lots": pos.lots,
                            "entry_price": pos.entry_price,
                            "exit_price": curr,
                            "pnl": round(pnl_est),
                            "reason": "force_exit_loop",
                        })
                        notifier.send(
                            f"⏰ 強制出場（時間到）{sym} {sname(sym)}\n"
                            f"已同時送市價IOC + 限價ROD\n"
                            f"損益估計 {pnl_est:+,.0f}\n"
                            f"⚠️ 請至富邦確認是否成交",
                            msg_type="force_exit",
                        )
        finally:
            feed.disconnect()
            persist_daily_tracker(ticks_db, dt, dry_run=dry_run)
            logger.info("=== 引擎關閉 | 實際損益=%.0f | tick=%d筆 ===",
                        dt.total_pnl, tick_count[0])
            log_event("engine_stop", actual_pnl=dt.total_pnl, tick_count=tick_count[0])
            engine_logger.removeHandler(file_handler)


# 全域單例，由 main.py 初始化，app.py 引用
engine = TradingEngine()
