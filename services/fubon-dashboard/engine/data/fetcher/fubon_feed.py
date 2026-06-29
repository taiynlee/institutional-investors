import json
import logging
import time
import threading
import urllib.request
from typing import Callable, Optional

from fubon_neo.sdk import FubonSDK, Mode

logger = logging.getLogger(__name__)

_TWSE_INDEX_URL = (
    "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
    "?ex_ch=tse_t00.tw&json=1&delay=0"
)


def _fetch_taiex_price() -> Optional[float]:
    try:
        req = urllib.request.Request(
            _TWSE_INDEX_URL,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://mis.twse.com.tw/"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        items = data.get("msgArray", [])
        if items:
            price_str = items[0].get("z", "") or items[0].get("a", "")
            if price_str and price_str != "-":
                return float(price_str)
    except Exception as e:
        logger.debug("TWSE index fetch error: %s", e)
    return None


class FubonFeed:
    def __init__(
        self,
        sdk: FubonSDK,
        symbols: list[str],
        on_tick: Optional[Callable] = None,
        on_quote: Optional[Callable] = None,
        subscribe_quote: bool = True,
        futures_sym_map: Optional[dict[str, str]] = None,
        on_futures_tick: Optional[Callable] = None,
        index_symbol: str = "Y9999",
        on_index_tick: Optional[Callable] = None,
        relogin_fn: Optional[Callable[[], "FubonSDK"]] = None,
    ):
        self._sdk = sdk
        self._symbols = symbols
        self._on_tick = on_tick
        self._on_quote = on_quote
        self._subscribe_quote = subscribe_quote
        self._futures_sym_map = futures_sym_map or {}
        self._on_futures_tick = on_futures_tick
        self._index_symbol = index_symbol
        self._on_index_tick = on_index_tick
        self._relogin_fn = relogin_fn
        self._fsym_to_stock: dict[str, str] = {v: k for k, v in self._futures_sym_map.items()}

        self._last_price: dict[str, float] = {}
        self._ws = None
        self._ws_futopt = None
        self._connected = threading.Event()
        self._futopt_connected = threading.Event()
        self._stop_event = threading.Event()
        self._reconnect_count = 0
        self._reconnect_lock = threading.Lock()
        self._reconnecting = False

    def connect(self):
        self._sdk.init_realtime(Mode.Speed)
        self._ws = self._sdk.marketdata.websocket_client._client.stock

        self._ws.on("connect",    self._on_connect)
        self._ws.on("message",    self._on_message)
        self._ws.on("error",      self._on_error)
        self._ws.on("disconnect", self._on_disconnect)

        self._ws.connect()
        if not self._connected.wait(timeout=10):
            raise RuntimeError("股票 WebSocket 連線逾時")

        if self._on_index_tick and self._index_symbol:
            t = threading.Thread(target=self._index_poll_loop, daemon=True, name="index-poll")
            t.start()
            logger.info("大盤指數輪詢執行緒已啟動 (10s 間隔)")

        if self._futures_sym_map:
            self._ws_futopt = self._sdk.marketdata.websocket_client._client.futopt
            self._ws_futopt.on("connect",    self._on_futopt_connect)
            self._ws_futopt.on("message",    self._on_futopt_message)
            self._ws_futopt.on("error",      lambda e: logger.error("期貨 WS 錯誤: %s", e))
            self._ws_futopt.on("disconnect", lambda *a: logger.warning("期貨 WS 斷線"))
            self._ws_futopt.connect()
            if not self._futopt_connected.wait(timeout=10):
                logger.warning("個股期貨 WebSocket 連線逾時，期貨訊號將無資料")

    def disconnect(self):
        self._stop_event.set()
        if self._ws:
            self._ws.disconnect()
        if self._ws_futopt:
            self._ws_futopt.disconnect()

    def _index_poll_loop(self):
        while not self._stop_event.is_set():
            try:
                price = _fetch_taiex_price()
                if price is not None:
                    self._on_index_tick(price, int(time.time() * 1_000_000_000))
            except Exception as e:
                logger.debug("index poll error: %s", e)
            self._stop_event.wait(timeout=10)

    def _on_connect(self):
        logger.info("股票 WebSocket 已連線，訂閱 %d 檔", len(self._symbols))
        for sym in self._symbols:
            self._ws.subscribe({"channel": "trades", "symbol": sym})
            if self._subscribe_quote:
                self._ws.subscribe({"channel": "quote", "symbol": sym})
        if self._on_index_tick and self._index_symbol:
            self._ws.subscribe({"channel": "trades", "symbol": self._index_symbol})
        self._connected.set()

    def _on_message(self, raw):
        try:
            self._on_message_inner(raw)
        except Exception as e:
            logger.debug("WS message parse skip: %s", e)

    def _on_message_inner(self, raw):
        try:
            msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except Exception:
            return
        if isinstance(msg, list):
            for item in msg:
                if isinstance(item, dict):
                    self._on_message(item)
            return
        event = msg.get("event", "")
        data = msg.get("data", {})
        channel = msg.get("channel", "")
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    ch = channel or item.get("channel", "")
                    sym = item.get("symbol", "") or msg.get("symbol", "")
                    if event == "data":
                        if ch == "trades":
                            self._handle_trade(sym, item)
                        elif ch == "quote":
                            self._handle_quote(sym, item)
            return
        channel = channel or data.get("channel", "")
        symbol = data.get("symbol", "") or msg.get("symbol", "")
        if event == "data":
            if channel == "trades":
                self._handle_trade(symbol, data)
            elif channel == "quote":
                self._handle_quote(symbol, data)
        elif event in ("authenticated", "subscribed"):
            logger.debug("股票 WS %s: %s", event, data)
        elif event == "error":
            logger.error("股票 WS error: %s", data)

    def _handle_trade(self, symbol: str, data: dict):
        price = data.get("price")
        ts    = data.get("time", 0)
        if symbol == self._index_symbol:
            if price is None:
                price = (data.get("closePrice") or data.get("close") or
                         data.get("lastPrice") or data.get("tradePrice"))
            if self._on_index_tick and price is not None:
                self._on_index_tick(float(price), ts)
            return

        size = data.get("size")
        if self._on_quote is not None and price is not None:
            bid = data.get("bid")
            ask = data.get("ask")
            _sz = int(size or 0)
            if _sz > 0:
                fp = float(price)
                if bid is not None and ask is not None:
                    fb, fa = float(bid), float(ask)
                    if fp >= fa:
                        bids_q = [[fb, _sz]]; asks_q = []
                    elif fp <= fb:
                        bids_q = []; asks_q = [[fa, _sz]]
                    else:
                        half = max(_sz // 2, 1)
                        bids_q = [[fb, half]]; asks_q = [[fa, _sz - half]]
                else:
                    prev = self._last_price.get(symbol)
                    if prev is None or fp > prev:
                        bids_q = [[fp, _sz]]; asks_q = []
                    elif fp < prev:
                        bids_q = []; asks_q = [[fp, _sz]]
                    else:
                        half = max(_sz // 2, 1)
                        bids_q = [[fp, half]]; asks_q = [[fp, _sz - half]]
                self._on_quote(symbol, bids_q, asks_q)
                self._last_price[symbol] = fp

        if self._on_tick is None:
            return
        if price is not None and size is not None:
            self._on_tick(symbol, float(price), int(size), ts)

    def _handle_quote(self, symbol: str, data: dict):
        if symbol == self._index_symbol and self._on_index_tick:
            price = (data.get("closePrice") or data.get("close") or
                     data.get("lastPrice") or data.get("tradePrice") or
                     data.get("price"))
            if price is not None:
                self._on_index_tick(float(price), data.get("time", 0))
            return
        # quote channel 是委買委賣掛單（未成交），不計入外盤/內盤統計

    def _on_error(self, err):
        err_str = str(err)
        if "'list' object has no attribute 'get'" in err_str:
            logger.debug("股票 WS SDK list-parse error: %s", err_str)
            return
        logger.error("股票 WebSocket 錯誤: %s", err)

    def _on_disconnect(self, code=None, reason=None):
        logger.warning("股票 WebSocket 斷線 code=%s reason=%s", code, reason)
        self._connected.clear()
        if self._stop_event.is_set():
            return
        with self._reconnect_lock:
            if self._reconnecting:
                return
            self._reconnecting = True
            delay = min(2 ** self._reconnect_count * 2, 60)
            self._reconnect_count += 1
        logger.info("%.0f 秒後自動重連 (第 %d 次)...", delay, self._reconnect_count)
        threading.Timer(delay, self._reconnect_stock).start()

    def _reconnect_stock(self):
        if self._stop_event.is_set():
            with self._reconnect_lock:
                self._reconnecting = False
            return
        try:
            logger.info("股票 WebSocket 重連中...")
            try:
                self._sdk.init_realtime(Mode.Speed)
            except Exception as ie:
                if "Login Error" in str(ie) and self._relogin_fn:
                    logger.warning("SDK session 過期，重新登入...")
                    self._sdk = self._relogin_fn()
                else:
                    raise
            self._ws = self._sdk.marketdata.websocket_client._client.stock
            self._ws.on("connect",    self._on_connect)
            self._ws.on("message",    self._on_message)
            self._ws.on("error",      self._on_error)
            self._ws.on("disconnect", self._on_disconnect)
            self._ws.connect()
            if self._connected.wait(timeout=15):
                logger.info("股票 WebSocket 重連成功")
                self._reconnect_count = 0
                with self._reconnect_lock:
                    self._reconnecting = False
            else:
                logger.error("重連逾時，再次排程")
                with self._reconnect_lock:
                    self._reconnecting = False
                self._on_disconnect()
        except Exception as e:
            logger.error("重連失敗: %s", e)
            with self._reconnect_lock:
                self._reconnecting = False
            if not self._stop_event.is_set():
                threading.Timer(30, self._reconnect_stock).start()

    def _on_futopt_connect(self):
        logger.info("期貨 WebSocket 已連線，訂閱 %d 檔", len(self._futures_sym_map))
        for fsym in self._futures_sym_map.values():
            self._ws_futopt.subscribe({"channel": "trades", "symbol": fsym})
        self._futopt_connected.set()

    def _on_futopt_message(self, raw):
        try:
            msg = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except Exception:
            return
        if isinstance(msg, list):
            for item in msg:
                if isinstance(item, dict):
                    self._on_futopt_message(item)
            return
        event   = msg.get("event", "")
        data    = msg.get("data", {})
        # channel can be at top-level OR inside data, depending on SDK version
        channel = msg.get("channel", "") or (data.get("channel", "") if isinstance(data, dict) else "")
        if event == "data" and channel == "trades":
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    fsym  = item.get("symbol", "")
                    price = item.get("price")
                    ts    = item.get("time", 0)
                    sid   = self._fsym_to_stock.get(fsym)
                    if sid and price is not None and self._on_futures_tick:
                        self._on_futures_tick(sid, float(price), ts)
            else:
                fsym     = data.get("symbol", "")
                price    = data.get("price")
                ts       = data.get("time", 0)
                stock_id = self._fsym_to_stock.get(fsym)
                if stock_id and price is not None and self._on_futures_tick:
                    self._on_futures_tick(stock_id, float(price), ts)
                elif price is not None:
                    logger.debug("期貨 tick fsym=%s 未在 map 中 (map=%s)", fsym, list(self._fsym_to_stock.keys())[:5])
        elif event in ("authenticated", "subscribed"):
            logger.debug("期貨 WS %s: %s", event, data)
        elif event == "error":
            logger.error("期貨 WS error: %s", data)
