from engine.utils.tz import now_tw


class DailyTracker:
    def __init__(self):
        self.total_pnl: float = 0.0
        self.trades: list[dict] = []
        self.entered_symbols: set[str] = set()  # 今日已進場的標的（無論是否已出場）

    def record_entry(self, symbol: str):
        """記錄進場（買入）—— 一天最多交易 N 檔的計數依據"""
        self.entered_symbols.add(symbol)

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

    @property
    def daily_entries(self) -> int:
        """今日已進場檔數（含出場後的計數不歸零）"""
        return len(self.entered_symbols)
