from dataclasses import dataclass
from typing import Optional


@dataclass
class FuturesSnapshot:
    futures_price: float
    spot_price: float
    futures_change_pct: float


class FuturesSignal:
    """
    個股期貨訊號。無資料時（update 未被呼叫）→ 跳過所有過濾，允許正常交易。
    進場條件：期貨價 > 現價（正價差，期貨領先現貨）。
    """

    def __init__(self):
        self._state: Optional[FuturesSnapshot] = None

    def update(self, futures_price: float, spot_price: float, futures_change_pct: float) -> None:
        self._state = FuturesSnapshot(futures_price, spot_price, futures_change_pct)

    def is_leading(self) -> bool:
        """期貨價 > 現價 = 期貨領先，允許進場。無資料時回傳 True（跳過過濾）。"""
        if self._state is None:
            return True
        return self._state.futures_price > self._state.spot_price
