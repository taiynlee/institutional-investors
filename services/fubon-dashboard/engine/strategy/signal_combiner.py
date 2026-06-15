from dataclasses import dataclass
from typing import Optional


@dataclass
class SignalResult:
    symbol: str
    should_enter: bool
    change_pct: float
    reason: str = ""
    position_size_ratio: float = 1.0


class SignalCombiner:
    def __init__(
        self,
        min_volume_price_score: int = 2,
        min_technical_score: int = 2,
        max_entry_gain_pct: float = 4.0,
        limit_up_buffer_pct: float = 4.0,
    ):
        self.min_volume_price_score = min_volume_price_score
        self.min_technical_score = min_technical_score
        self.max_entry_gain_pct = max_entry_gain_pct
        self.limit_up_buffer_pct = limit_up_buffer_pct

    def evaluate(
        self,
        symbol: str,
        current_price: float,
        time_ok: bool,
        market_ok: bool,
        not_in_position: bool,
        no_order_lock: bool,
        positions_count: int,
        max_positions: int,
        limit_up_pct_away: float,
        volume_price_score: int,
        technical_score: int,
        chips_score: int,
        change_pct: float,
        futures_signal=None,
    ) -> SignalResult:
        def no(reason):
            return SignalResult(symbol=symbol, should_enter=False, change_pct=change_pct, reason=reason)

        if not time_ok:
            return no("time_not_ok")
        if not market_ok:
            return no("market_blocked")
        if not not_in_position:
            return no("already_in_position")
        if not no_order_lock:
            return no("order_locked")
        if positions_count >= max_positions:
            return no("max_daily_trades_reached")
        if limit_up_pct_away < self.limit_up_buffer_pct:
            return no("too_close_to_limit_up")
        if change_pct > self.max_entry_gain_pct:
            return no("entry_gain_too_high")

        if futures_signal is not None:
            ok, reason = futures_signal.can_buy()
            if not ok:
                return no(f"futures_{reason}")

        bullish_boost = futures_signal is not None and futures_signal.is_bullish_confirmation()
        min_vp = max(1, self.min_volume_price_score - (1 if bullish_boost else 0))
        min_tc = max(1, self.min_technical_score - (1 if bullish_boost else 0))

        if volume_price_score < min_vp:
            return no("volume_price_score_low")
        if technical_score < min_tc:
            return no("technical_score_low")

        size_ratio = futures_signal.position_size_ratio() if futures_signal is not None else 1.0
        return SignalResult(
            symbol=symbol,
            should_enter=True,
            change_pct=change_pct,
            position_size_ratio=size_ratio,
        )
