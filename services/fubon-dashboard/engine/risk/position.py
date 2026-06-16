from dataclasses import dataclass
from typing import Optional


@dataclass
class Position:
    symbol: str
    entry_price: float
    lots: int
    stop_loss: float    # entry_price - stop_loss_ticks * tick_size
    take_profit: float  # ref_price * (1 + (change_pct_at_entry + add_pct) / 100)

    def check_price(self, price: float) -> Optional[str]:
        if price <= self.stop_loss:
            return "tick_stop"
        if price >= self.take_profit:
            return "take_profit"
        return None
