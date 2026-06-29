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
        """
        純偵測器：只判斷是否應出場，返回原因。
        實際下單由 trading_engine 執行（含追價/成交確認邏輯）。
        時間強制出場由主迴圈負責，此處不處理。
        """
        pos = self.om.positions.get(symbol)
        if pos is None:
            return None

        # 停損/停利 tick 觸發（dry_run 時真實條件單不生效，由 tick 檢查代替）
        return pos.check_price(price)
