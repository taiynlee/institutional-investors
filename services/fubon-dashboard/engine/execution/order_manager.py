from typing import Optional
from engine.execution.broker import FubonBroker
from engine.risk.position import Position


class OrderManager:
    def __init__(self, broker: FubonBroker, atr_multiplier: float = 1.8):
        self.broker = broker
        self.atr_multiplier = atr_multiplier
        self._locks: set[str] = set()
        self.positions: dict[str, Position] = {}

    def is_locked(self, symbol: str) -> bool:
        return symbol in self._locks

    def place_buy(
        self,
        symbol: str,
        lots: int,
        price: float,
        stop_loss: float,
        take_profit: float,
        atr: float = 2.0,
    ) -> bool:
        if symbol in self._locks:
            return False
        self._locks.add(symbol)
        self.broker.buy(symbol=symbol, lots=lots, price=price)
        return True

    def on_fill(
        self,
        symbol: str,
        filled_lots: int,
        fill_price: float,
        atr: float = 2.0,
        orb_low: Optional[float] = None,
    ):
        self._locks.discard(symbol)
        self.positions[symbol] = Position(
            symbol=symbol,
            entry_price=fill_price,
            lots=filled_lots,
            atr=atr,
            atr_multiplier=self.atr_multiplier,
            orb_low=orb_low,
        )

    def place_sell(self, symbol: str, reason: str = "") -> bool:
        pos = self.positions.get(symbol)
        if pos is None:
            return False
        self.broker.sell(symbol=symbol, lots=pos.lots, price=0.0, reason=reason)
        del self.positions[symbol]
        return True
