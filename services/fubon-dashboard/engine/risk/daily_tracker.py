from engine.utils.tz import now_tw


class DailyTracker:
    def __init__(self):
        self.total_pnl: float = 0.0
        self.trades: list[dict] = []

    def record_trade(self, pnl: float, symbol: str = "", lots: int = 0,
                     entry_price: float = 0.0, exit_price: float = 0.0):
        self.total_pnl += pnl
        self.trades.append({
            "time": now_tw().strftime("%H:%M:%S"),
            "symbol": symbol,
            "lots": lots,
            "pnl": pnl,
            "cumulative_pnl": self.total_pnl,
            "entry_price": entry_price,
            "exit_price": exit_price,
        })

    @property
    def trade_count(self) -> int:
        return len(self.trades)
