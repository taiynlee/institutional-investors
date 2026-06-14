from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional
import math


@dataclass
class Bar:
    minute: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class BarBuilder:
    """聚合 tick → 1min & 5min K 棒，維護 VWAP SD 通道。"""

    def __init__(self):
        self.current_1min: Optional[Bar] = None
        self._5min_bars: list[Bar] = []
        self.current_5min: Optional[Bar] = None

        self._cum_pv: float = 0.0
        self._cum_vol: float = 0.0
        self._sq_dev_sum: float = 0.0
        self.vwap: float = 0.0
        self.vwap_sigma: float = 0.0
        self.vwap_upper: float = 0.0
        self.vwap_lower: float = 0.0

        self.on_1min_close: Callable[[Bar], None] = lambda b: None
        self.on_5min_close: Callable[[Bar], None] = lambda b: None

    def on_tick(self, tick: dict):
        price: float = tick["price"]
        volume: int = tick["volume"]
        dt: datetime = tick["time"]
        minute = dt.replace(second=0, microsecond=0)

        self._cum_pv += price * volume
        self._cum_vol += volume
        if self._cum_vol > 0:
            prev_vwap = self.vwap
            self.vwap = self._cum_pv / self._cum_vol
            self._sq_dev_sum += volume * (price - prev_vwap) ** 2
            variance = self._sq_dev_sum / self._cum_vol
            self.vwap_sigma = math.sqrt(variance)
            self.vwap_upper = self.vwap + self.vwap_sigma
            self.vwap_lower = self.vwap - self.vwap_sigma

        if self.current_1min is None:
            self.current_1min = Bar(minute, price, price, price, price, volume)
        elif minute != self.current_1min.minute:
            self.on_1min_close(self.current_1min)
            self._update_5min(self.current_1min)
            self.current_1min = Bar(minute, price, price, price, price, volume)
        else:
            b = self.current_1min
            b.high = max(b.high, price)
            b.low = min(b.low, price)
            b.close = price
            b.volume += volume

    def _update_5min(self, bar: Bar):
        if self.current_5min is None:
            self.current_5min = Bar(bar.minute, bar.open, bar.high, bar.low, bar.close, bar.volume)
        else:
            self.current_5min.high = max(self.current_5min.high, bar.high)
            self.current_5min.low = min(self.current_5min.low, bar.low)
            self.current_5min.close = bar.close
            self.current_5min.volume += bar.volume

        self._5min_bars.append(bar)
        if len(self._5min_bars) == 5:
            self.on_5min_close(self.current_5min)
            self.current_5min = None
            self._5min_bars.clear()
