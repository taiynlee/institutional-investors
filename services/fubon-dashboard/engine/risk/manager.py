from datetime import datetime, time
from typing import Optional
from engine.execution.order_manager import OrderManager


class RiskManager:
    def __init__(
        self,
        order_manager: OrderManager,
        take_profit_pct: float = 5.0,
        time_stop_hour: float = 11,
        force_exit_time: time = time(13, 20),
        vwap_exit: bool = True,
        vwap_exit_volume_ratio: float = 0.7,
    ):
        self.om = order_manager
        self.take_profit_pct = take_profit_pct
        self.time_stop_hour = time_stop_hour
        self.force_exit_time = force_exit_time
        self.vwap_exit = vwap_exit
        self.vwap_exit_volume_ratio = vwap_exit_volume_ratio

    def on_tick(
        self,
        symbol: str,
        price: float,
        vwap: float,
        now: datetime,
        futures_signal=None,
        current_volume: int = 0,
        avg_volume: float = 0.0,
    ) -> Optional[str]:
        pos = self.om.positions.get(symbol)
        if pos is None:
            return None

        current_time = now.time()

        if current_time >= self.force_exit_time:
            self.om.place_sell(symbol, reason="force_exit")
            return "force_exit"

        if futures_signal is not None:
            exit_now, reason = futures_signal.should_exit()
            if exit_now:
                self.om.place_sell(symbol, reason=reason)
                return reason

        exit_reason = pos.update_price(price)
        if exit_reason:
            self.om.place_sell(symbol, reason=exit_reason)
            return exit_reason

        futures_rocket = futures_signal is not None and futures_signal.wait_for_limit_up()
        if not futures_rocket:
            if price >= pos.entry_price * (1 + self.take_profit_pct / 100):
                self.om.place_sell(symbol, reason="take_profit")
                return "take_profit"

        _tsh = int(self.time_stop_hour)
        _tsm = round((self.time_stop_hour - _tsh) * 60)
        if current_time >= time(_tsh, _tsm) and price < pos.entry_price:
            self.om.place_sell(symbol, reason="time_stop")
            return "time_stop"

        if self.vwap_exit and price < vwap:
            volume_ok = (
                avg_volume <= 0
                or current_volume >= avg_volume * self.vwap_exit_volume_ratio
            )
            if volume_ok:
                self.om.place_sell(symbol, reason="vwap_exit")
                return "vwap_exit"

        return None
