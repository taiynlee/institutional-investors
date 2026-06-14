from dataclasses import dataclass, field
from typing import Optional

from engine.execution.broker import tw_tick_size as tick_size  # 統一來源


@dataclass
class Position:
    symbol: str
    entry_price: float
    lots: int
    atr: float
    atr_multiplier: float = 1.8
    trailing_trigger_pct: float = 2.0
    trailing_pullback_pct: float = 1.5
    orb_low: Optional[float] = None

    peak_price: float = field(init=False)
    stop_loss: float = field(init=False)
    trailing_active: bool = field(default=False, init=False)

    def __post_init__(self):
        self.peak_price = self.entry_price
        atr_stop = self.entry_price - self.atr_multiplier * self.atr

        if self.orb_low is not None:
            structural_stop = self.orb_low - tick_size(self.orb_low)
            self.stop_loss = max(atr_stop, structural_stop)
        else:
            self.stop_loss = atr_stop

    def update_price(self, price: float) -> Optional[str]:
        if price <= self.stop_loss:
            return "atr_stop"

        if price > self.peak_price:
            self.peak_price = price

        gain_pct = (self.peak_price - self.entry_price) / self.entry_price * 100
        if gain_pct >= self.trailing_trigger_pct:
            self.trailing_active = True

        if self.trailing_active:
            pullback = (self.peak_price - price) / self.peak_price * 100
            if pullback >= self.trailing_pullback_pct:
                return "trailing_stop"

        return None
