from datetime import datetime, time
from typing import Optional
from engine.execution.order_manager import OrderManager


class RiskManager:
    def __init__(
        self,
        order_manager: OrderManager,
        force_exit_time: time = time(13, 20),
    ):
        self.om = order_manager
        self.force_exit_time = force_exit_time

    def on_tick(
        self,
        symbol: str,
        price: float,
        now: datetime,
        **_kwargs,
    ) -> Optional[str]:
        pos = self.om.positions.get(symbol)
        if pos is None:
            return None

        # 強制出場（最高優先）
        if now.time() >= self.force_exit_time:
            self.om.place_sell(symbol, reason="force_exit")
            return "force_exit"

        # 模擬觸價單（dry_run 時真實條件單不生效，改用 tick 檢查）
        reason = pos.check_price(price)
        if reason:
            self.om.place_sell(symbol, reason=reason)
            return reason

        return None
