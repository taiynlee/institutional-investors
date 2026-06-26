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

    def on_tick(self, price: float, size: int, ts_ns: int, tick_window_seconds: int = 60):
        self.curr_price = price
        dt = now_tw()
        self.bar_builder.on_tick({"price": price, "volume": size, "time": dt})
        # 更新滾動價格歷史
        self._price_history.append((dt, price))
        cutoff = dt - timedelta(seconds=tick_window_seconds)
        while self._price_history and self._price_history[0][0] < cutoff:
            self._price_history.popleft()

    def on_quote(self, bids: list, asks: list):
        pass  # quote data no longer used

    def _on_1min_close(self, bar: Bar):
        self.prev_1min_volume = bar.volume
        self.prev_1min_close = bar.close

    @property
    def change_pct(self) -> float:
        if self.reference_price <= 0:
            return 0.0
        return (self.curr_price - self.reference_price) / self.reference_price * 100

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
        market_chg_pct: float,
        tick_rise_threshold: int,
        futures_signal=None,
        entry_cutoff_mins: int = 13 * 60 + 10,
        entry_start_mins: int = 9 * 60 + 15,
        bid_pct: float = 50.0,
        check_not_in_position: bool = True,
        check_futures_signal: bool = True,
        check_bid_pct: bool = True,
    ) -> SignalResult:
        current_mins = current_time.hour * 60 + current_time.minute
        time_ok = current_mins >= entry_start_mins and current_mins < entry_cutoff_mins
        return combiner.evaluate(
            symbol=self.symbol,
            time_ok=time_ok,
            market_chg_pct=market_chg_pct,
            not_in_position=not_in_position,
            positions_count=positions_count,
            max_positions=max_positions,
            change_pct=self.change_pct,
            tick_rise=self.tick_rise_60s,
            tick_rise_threshold=tick_rise_threshold,
            futures_signal=futures_signal,
            bid_pct=bid_pct,
            check_not_in_position=check_not_in_position,
            check_futures_signal=check_futures_signal,
            check_bid_pct=check_bid_pct,
        )

    def evaluate_theoretical(
        self,
        combiner: SignalCombiner,
        current_time,
        market_chg_pct: float,
        tick_rise_threshold: int,
        futures_signal=None,
        entry_cutoff_mins: int = 13 * 60 + 10,
        entry_start_mins: int = 9 * 60 + 15,
        check_futures_signal: bool = True,
        check_bid_pct: bool = True,
    ) -> SignalResult:
        current_mins = current_time.hour * 60 + current_time.minute
        time_ok = current_mins >= entry_start_mins and current_mins < entry_cutoff_mins
        return combiner.evaluate(
            symbol=self.symbol,
            time_ok=time_ok,
            market_chg_pct=market_chg_pct,
            not_in_position=True,
            positions_count=0,
            max_positions=999,
            change_pct=self.change_pct,
            tick_rise=self.tick_rise_60s,
            tick_rise_threshold=tick_rise_threshold,
            futures_signal=futures_signal,
            check_not_in_position=False,
            check_futures_signal=check_futures_signal,
            check_bid_pct=check_bid_pct,
        )
