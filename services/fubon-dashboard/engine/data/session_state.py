from collections import deque
from datetime import timedelta
from typing import Optional

from engine.utils.tz import now_tw
from engine.strategy.bar_builder import Bar, BarBuilder
from engine.strategy.signal_combiner import SignalCombiner, SignalResult
from engine.execution.broker import tw_tick_size


class SymbolSession:
    def __init__(
        self,
        symbol: str,
        reference_price: float,
        limitup_price: float,
        atr: float = 0.0,  # 保留相容性，不再使用
    ):
        self.symbol = symbol
        self.reference_price = reference_price
        self.limitup_price = limitup_price

        self.bar_builder = BarBuilder()
        self.bar_builder.on_1min_close = self._on_1min_close

        self.prev_1min_volume: int = 0
        self.prev_1min_close: float = reference_price
        self.curr_price: float = reference_price

        # 60秒滾動價格歷史（用於 tick_rise_60s 計算）
        self._price_history: deque = deque()  # (datetime, price)
        # 60秒滾動買賣盤成交量歷史（用於 bid_pct_window 計算）
        self._quote_history: deque = deque()  # (datetime, bid_vol, ask_vol)
        # _vol_history 已移除：vol_1m_lots 改用 _quote_history 的外盤量（bid_vol）

    def on_tick(self, price: float, size: int, ts_ns: int, tick_window_seconds: int = 60):
        self.curr_price = price
        dt = now_tw()
        self.bar_builder.on_tick({"price": price, "volume": size, "time": dt})
        cutoff = dt - timedelta(seconds=tick_window_seconds)
        # 更新滾動價格歷史
        self._price_history.append((dt, price))
        while self._price_history and self._price_history[0][0] < cutoff:
            self._price_history.popleft()

    def on_quote(self, bids: list, asks: list):
        pass  # quote data no longer used

    def on_bid_ask_tick(self, bid_vol: int, ask_vol: int, window_seconds: int = 60):
        """記錄本 tick 的買賣量到滾動窗口，用於計算觀察期間買盤佔比。"""
        dt = now_tw()
        self._quote_history.append((dt, bid_vol, ask_vol))
        cutoff = dt - timedelta(seconds=window_seconds)
        while self._quote_history and self._quote_history[0][0] < cutoff:
            self._quote_history.popleft()

    def _on_1min_close(self, bar: Bar):
        self.prev_1min_volume = bar.volume
        self.prev_1min_close = bar.close

    @property
    def change_pct(self) -> float:
        if self.reference_price <= 0:
            return 0.0
        return (self.curr_price - self.reference_price) / self.reference_price * 100

    @property
    def bid_pct_window(self) -> float:
        """觀察窗口內買盤佔總成交量的比例（%）。"""
        total_bid = sum(b for _, b, _ in self._quote_history)
        total_ask = sum(a for _, _, a in self._quote_history)
        total = total_bid + total_ask
        return total_bid / total * 100 if total > 0 else 50.0

    @property
    def vol_1m_lots(self) -> float:
        """過去 60 秒內外盤成交量（張）。bid_vol 單位：股，÷1000=張。"""
        return sum(b for _, b, _ in self._quote_history) / 1000

    @property
    def tick_rise_60s(self) -> float:
        """60秒內上漲了幾個 tick。負值表示下跌。"""
        if len(self._price_history) < 2:
            return 0.0
        oldest_price = self._price_history[0][1]
        ts = tw_tick_size(oldest_price)
        if ts == 0:
            return 0.0
        return (self.curr_price - oldest_price) / ts

    def evaluate(
        self,
        combiner: SignalCombiner,
        current_time,
        positions_count: int,
        max_positions: int,
        not_in_position: bool,
        tick_rise_threshold: int,
        futures_signal=None,
        entry_cutoff_mins: int = 13 * 60 + 10,
        entry_start_mins: int = 9 * 60 + 15,
        check_not_in_position: bool = True,
        check_futures_signal: bool = True,
        vol_ratio: float = 100.0,
        vol_ratio_min_pct: float = 0.0,
        amplitude_pct: float = 0.0,
        amplitude_min_pct: float = 3.0,
        bid_1m_pct: float = 50.0,
        bid_1m_pct_threshold: float = 70.0,
        avg_vol5_lot: float = 0.0,
        vol_1m_coef: float = 1.0,
    ) -> SignalResult:
        current_mins = current_time.hour * 60 + current_time.minute
        time_ok = current_mins >= entry_start_mins and current_mins < entry_cutoff_mins
        return combiner.evaluate(
            symbol=self.symbol,
            time_ok=time_ok,
            not_in_position=not_in_position,
            positions_count=positions_count,
            max_positions=max_positions,
            change_pct=self.change_pct,
            tick_rise=self.tick_rise_60s,
            tick_rise_threshold=tick_rise_threshold,
            futures_signal=futures_signal,
            check_not_in_position=check_not_in_position,
            check_futures_signal=check_futures_signal,
            vol_ratio=vol_ratio,
            vol_ratio_min_pct=vol_ratio_min_pct,
            amplitude_pct=amplitude_pct,
            amplitude_min_pct=amplitude_min_pct,
            bid_1m_pct=bid_1m_pct,
            bid_1m_pct_threshold=bid_1m_pct_threshold,
            vol_1m_lots=self.vol_1m_lots,
            avg_vol5_lot=avg_vol5_lot,
            vol_1m_coef=vol_1m_coef,
        )

    def evaluate_theoretical(
        self,
        combiner: SignalCombiner,
        current_time,
        tick_rise_threshold: int,
        futures_signal=None,
        entry_cutoff_mins: int = 13 * 60 + 10,
        entry_start_mins: int = 9 * 60 + 15,
        check_futures_signal: bool = True,
        vol_ratio: float = 100.0,
        vol_ratio_min_pct: float = 0.0,
        amplitude_pct: float = 0.0,
        amplitude_min_pct: float = 3.0,
        bid_1m_pct: float = 50.0,
        bid_1m_pct_threshold: float = 70.0,
        avg_vol5_lot: float = 0.0,
        vol_1m_coef: float = 1.0,
    ) -> SignalResult:
        current_mins = current_time.hour * 60 + current_time.minute
        time_ok = current_mins >= entry_start_mins and current_mins < entry_cutoff_mins
        return combiner.evaluate(
            symbol=self.symbol,
            time_ok=time_ok,
            not_in_position=True,
            positions_count=0,
            max_positions=999,
            change_pct=self.change_pct,
            tick_rise=self.tick_rise_60s,
            tick_rise_threshold=tick_rise_threshold,
            futures_signal=futures_signal,
            check_not_in_position=False,
            check_futures_signal=check_futures_signal,
            vol_ratio=vol_ratio,
            vol_ratio_min_pct=vol_ratio_min_pct,
            amplitude_pct=amplitude_pct,
            amplitude_min_pct=amplitude_min_pct,
            bid_1m_pct=bid_1m_pct,
            bid_1m_pct_threshold=bid_1m_pct_threshold,
            vol_1m_lots=self.vol_1m_lots,
            avg_vol5_lot=avg_vol5_lot,
            vol_1m_coef=vol_1m_coef,
        )
