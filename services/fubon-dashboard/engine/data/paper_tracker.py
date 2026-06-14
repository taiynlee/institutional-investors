from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional

from engine.risk.position import Position, tick_size


@dataclass
class PaperTrade:
    symbol: str
    entry_price: float
    lots: int
    entry_time: datetime
    atr: float
    stop_loss: float
    orb_low: Optional[float] = None
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    pnl: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.exit_price is None


class PaperTracker:
    def __init__(
        self,
        take_profit_pct: float = 5.0,
        time_stop_hour: float = 11,
        force_exit_time: time = time(13, 23),
        vwap_exit: bool = True,
        vwap_exit_volume_ratio: float = 0.7,
        atr_multiplier: float = 1.8,
    ):
        self.take_profit_pct = take_profit_pct
        self.time_stop_hour = time_stop_hour
        self.force_exit_time = force_exit_time
        self.vwap_exit = vwap_exit
        self.vwap_exit_volume_ratio = vwap_exit_volume_ratio
        self.atr_multiplier = atr_multiplier

        self.positions: dict[str, PaperTrade] = {}
        self.closed_trades: list[PaperTrade] = []

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.closed_trades)

    @property
    def trade_count(self) -> int:
        return len(self.closed_trades)

    @property
    def win_rate(self) -> float:
        if not self.closed_trades:
            return 0.0
        wins = sum(1 for t in self.closed_trades if t.pnl > 0)
        return wins / len(self.closed_trades)

    def unrealized_pnl(self, current_prices: dict[str, float]) -> float:
        total = 0.0
        for sym, trade in self.positions.items():
            price = current_prices.get(sym, trade.entry_price)
            total += (price - trade.entry_price) * trade.lots * 1000
        return total

    def enter(
        self,
        symbol: str,
        price: float,
        lots: int,
        atr: float,
        now: datetime,
        orb_low: Optional[float] = None,
    ) -> bool:
        if symbol in self.positions:
            return False

        if orb_low is not None:
            structural_stop = orb_low - tick_size(orb_low)
            atr_stop = price - self.atr_multiplier * atr
            stop = max(atr_stop, structural_stop)
        else:
            stop = price - self.atr_multiplier * atr

        self.positions[symbol] = PaperTrade(
            symbol=symbol,
            entry_price=price,
            lots=lots,
            entry_time=now,
            atr=atr,
            stop_loss=stop,
            orb_low=orb_low,
        )
        return True

    def close(self, symbol: str, price: float, now: datetime, reason: str = "") -> Optional[str]:
        trade = self.positions.get(symbol)
        if trade is None:
            return None
        return self._close(trade, price, now, reason)

    def on_tick(
        self,
        symbol: str,
        price: float,
        now: datetime,
        vwap: float,
        current_volume: int = 0,
        avg_volume: float = 0.0,
    ) -> Optional[str]:
        trade = self.positions.get(symbol)
        if trade is None:
            return None

        curr_time = now.time()

        if curr_time >= self.force_exit_time:
            return self._close(trade, price, now, "force_exit")

        if price <= trade.stop_loss:
            return self._close(trade, price, now, "stop_loss")

        if price >= trade.entry_price * (1 + self.take_profit_pct / 100):
            return self._close(trade, price, now, "take_profit")

        _tsh = int(self.time_stop_hour)
        _tsm = round((self.time_stop_hour - _tsh) * 60)
        if curr_time >= time(_tsh, _tsm) and price < trade.entry_price:
            return self._close(trade, price, now, "time_stop")

        if self.vwap_exit and price < vwap:
            vol_ok = (
                avg_volume <= 0
                or current_volume >= avg_volume * self.vwap_exit_volume_ratio
            )
            if vol_ok:
                return self._close(trade, price, now, "vwap_exit")

        return None

    def _close(self, trade: PaperTrade, price: float, now: datetime, reason: str) -> str:
        trade.exit_price = price
        trade.exit_time = now
        trade.exit_reason = reason
        trade.pnl = (price - trade.entry_price) * trade.lots * 1000
        del self.positions[trade.symbol]
        self.closed_trades.append(trade)
        return reason

    def daily_summary(self, current_prices: dict[str, float]) -> dict:
        unrealized = self.unrealized_pnl(current_prices)
        return {
            "trade_count": self.trade_count,
            "total_pnl": self.total_pnl,
            "unrealized_pnl": unrealized,
            "combined_pnl": self.total_pnl + unrealized,
            "win_rate": round(self.win_rate * 100, 1),
            "trades": [
                {
                    "symbol": t.symbol,
                    "entry": t.entry_price,
                    "exit": t.exit_price,
                    "lots": t.lots,
                    "pnl": t.pnl,
                    "reason": t.exit_reason,
                }
                for t in self.closed_trades
            ],
        }
