from dataclasses import dataclass


@dataclass
class SignalResult:
    symbol: str
    should_enter: bool
    reason: str = ""


class SignalCombiner:
    """
    進場條件：
    1. 時間窗口（entry_start_mins ~ entry_cutoff）
    2. 大盤日漲幅 > market_rise_min（預設 1%）
    3. 同標的當下未持倉（可關閉）
    4. 今日進場未達上限
    5. 個股漲跌幅在 ±max_change_pct 內（預設 5%）
    6. tick_window_seconds 秒內上漲 >= tick_rise_threshold 個 tick（必要條件）
    7. 有個股期貨資料時：期貨價 > 現價（正價差，可關閉）
    8. 已成交買盤 >= bid_pct_threshold（預設 60%，可調）
    9. 今日累積量/5日均量 >= 開盤後觀察分鐘數 × 1.3%
    """

    def __init__(
        self,
        max_change_pct: float = 5.0,
        market_rise_min: float = 1.0,
    ):
        self.max_change_pct = max_change_pct
        self.market_rise_min = market_rise_min

    def evaluate(
        self,
        symbol: str,
        time_ok: bool,
        market_chg_pct: float,
        not_in_position: bool,
        positions_count: int,
        max_positions: int,
        change_pct: float,
        tick_rise: float,
        tick_rise_threshold: int,
        futures_signal=None,
        bid_pct: float = 50.0,
        bid_pct_threshold: float = 60.0,
        check_not_in_position: bool = True,
        check_futures_signal: bool = True,
        vol_ratio: float = 100.0,
        vol_ratio_min_pct: float = 0.0,
    ) -> SignalResult:
        def no(r):
            return SignalResult(symbol=symbol, should_enter=False, reason=r)

        if not time_ok:
            return no("time_not_ok")
        if market_chg_pct <= self.market_rise_min:
            return no(f"market_rise_low_{market_chg_pct:.2f}pct")
        if check_not_in_position and not not_in_position:
            return no("already_in_position")
        if positions_count >= max_positions:
            return no("max_daily_trades_reached")
        if abs(change_pct) > self.max_change_pct:
            return no(f"change_pct_exceeded_{change_pct:.2f}pct")
        if tick_rise < tick_rise_threshold:
            return no(f"tick_rise_low_{tick_rise:.1f}")
        if check_futures_signal and futures_signal is not None and not futures_signal.is_leading():
            return no("futures_not_leading")
        if bid_pct < bid_pct_threshold:
            return no(f"bid_pct_low_{bid_pct:.0f}")
        if vol_ratio_min_pct > 0 and vol_ratio < vol_ratio_min_pct:
            return no(f"vol_ratio_low_{vol_ratio:.1f}pct_need_{vol_ratio_min_pct:.1f}pct")

        return SignalResult(symbol=symbol, should_enter=True, reason="ok")
