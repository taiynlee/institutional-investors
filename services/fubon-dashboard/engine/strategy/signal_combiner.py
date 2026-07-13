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
    4. 個股漲跌幅絕對值 ≤ max_change_pct（預設 5.0%，避免追高或追跌）
    5. ⭐ 必要條件（三者同時成立）：
       (a) 觀察窗口內上漲 >= tick_rise_threshold 個 tick（預設 4，設 0 關閉）
       (b) 觀察窗口內外盤佔比 >= bid_1m_pct_threshold（預設 85%），且
       (c) 過去 60 秒外盤量(張) >= 近5分鐘平均每分鐘總成交量(張) × vol_1m_coef
           （0=關閉；資料不足2分鐘自動跳過；預設 0.8）
    6. 今日累積量/5日均量 >= 開盤後觀察分鐘數 × vol_ratio_coefficient%
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
        check_not_in_position: bool = True,
        vol_ratio: float = 100.0,
        vol_ratio_min_pct: float = 0.0,
        tick_rise: float = 0.0,
        tick_rise_threshold: int = 4,
        bid_1m_pct: float = 50.0,
        bid_1m_pct_threshold: float = 85.0,
        vol_1m_lots: float = 0.0,
        past_5min_avg_vol: float = 0.0,
        vol_1m_coef: float = 0.8,
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
        if tick_rise_threshold > 0 and tick_rise < tick_rise_threshold:
            return no(f"tick_rise_low_{tick_rise:.1f}_need_{tick_rise_threshold}")
        if bid_1m_pct < bid_1m_pct_threshold:
            return no(f"bid1m_low_{bid_1m_pct:.0f}pct_need_{bid_1m_pct_threshold:.0f}pct")
        if vol_1m_coef > 0 and past_5min_avg_vol > 0:
            min_vol = past_5min_avg_vol * vol_1m_coef
            if vol_1m_lots < min_vol:
                return no(f"vol_1m_low_{vol_1m_lots:.1f}lots_need_{min_vol:.1f}lots")
        if vol_ratio_min_pct > 0 and vol_ratio < vol_ratio_min_pct:
            return no(f"vol_ratio_low_{vol_ratio:.1f}pct_need_{vol_ratio_min_pct:.1f}pct")

        return SignalResult(symbol=symbol, should_enter=True, reason="ok")
