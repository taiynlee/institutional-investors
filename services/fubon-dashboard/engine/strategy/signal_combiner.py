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
    2. 同標的當下未持倉（可關閉）
    3. 今日進場未達上限
    4. 個股漲跌幅在 ±max_change_pct 內（預設 5%）
    5. ⭐ 必要條件（三者同時成立）：
       (a) tick_window_seconds 秒內上漲 >= tick_rise_threshold 個 tick，且
       (b) 觀察窗口內買盤佔比 >= bid_1m_pct_threshold（預設 70%），且
       (c) 過去 60 秒外盤量(張) >= avg_vol5_lot ÷ 270 × vol_1m_coef（0=關閉，預設 1.0）
    6. 有個股期貨資料時：期貨價 > 現價（正價差，可關閉）
    7. 今日累積量/5日均量 >= 開盤後觀察分鐘數 × vol_ratio_coefficient%
    8. 當日振幅（(High-Low)/昨收×100）>= amplitude_min_pct（預設 3%，可調）
    """

    def __init__(
        self,
        max_change_pct: float = 5.0,
    ):
        self.max_change_pct = max_change_pct

    def evaluate(
        self,
        symbol: str,
        time_ok: bool,
        not_in_position: bool,
        positions_count: int,
        max_positions: int,
        change_pct: float,
        tick_rise: float,
        tick_rise_threshold: int,
        futures_signal=None,
        check_not_in_position: bool = True,
        check_futures_signal: bool = True,
        vol_ratio: float = 100.0,
        vol_ratio_min_pct: float = 0.0,
        amplitude_pct: float = 0.0,
        amplitude_min_pct: float = 3.0,
        bid_1m_pct: float = 50.0,
        bid_1m_pct_threshold: float = 70.0,
        vol_1m_lots: float = 0.0,
        avg_vol5_lot: float = 0.0,
        vol_1m_coef: float = 1.0,
    ) -> SignalResult:
        def no(r):
            return SignalResult(symbol=symbol, should_enter=False, reason=r)

        if not time_ok:
            return no("time_not_ok")
        if check_not_in_position and not not_in_position:
            return no("already_in_position")
        if positions_count >= max_positions:
            return no("max_daily_trades_reached")
        if abs(change_pct) > self.max_change_pct:
            return no(f"change_pct_exceeded_{change_pct:.2f}pct")
        # ⑤ 三者同時成立 (a)(b)(c)
        if tick_rise < tick_rise_threshold or bid_1m_pct < bid_1m_pct_threshold:
            return no(f"tick_rise_low_{tick_rise:.1f}_bid1m_{bid_1m_pct:.0f}pct")
        if vol_1m_coef > 0 and avg_vol5_lot > 0:
            min_vol = avg_vol5_lot / 270 * vol_1m_coef
            if vol_1m_lots < min_vol:
                return no(f"vol_1m_low_{vol_1m_lots:.1f}lots_need_{min_vol:.1f}lots")
        if check_futures_signal and futures_signal is not None and not futures_signal.is_leading():
            return no("futures_not_leading")
        if vol_ratio_min_pct > 0 and vol_ratio < vol_ratio_min_pct:
            return no(f"vol_ratio_low_{vol_ratio:.1f}pct_need_{vol_ratio_min_pct:.1f}pct")
        if amplitude_min_pct > 0 and amplitude_pct < amplitude_min_pct:
            return no(f"amplitude_low_{amplitude_pct:.1f}pct_need_{amplitude_min_pct:.1f}pct")

        return SignalResult(symbol=symbol, should_enter=True, reason="ok")
