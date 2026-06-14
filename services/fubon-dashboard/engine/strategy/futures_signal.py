from dataclasses import dataclass
from collections import deque
from typing import Optional


@dataclass
class FuturesSnapshot:
    futures_price: float
    spot_price: float
    futures_change_pct: float

    @property
    def spread_pct(self) -> float:
        if self.spot_price <= 0:
            return 0.0
        return (self.futures_price - self.spot_price) / self.spot_price * 100


class FuturesSignal:
    """
    個股期貨訊號：進場過濾、倉位調整、觸發出場。
    無期貨資料時（update 未被呼叫）→ 所有過濾器跳過，允許正常交易。
    """

    def __init__(
        self,
        no_buy_spread_pct: float = 0.3,
        reduce_spread_pct: float = 0.8,
        sell_spread_pct: float = 1.5,
        fast_reversal_pct: float = 0.5,
        rocket_threshold_pct: float = 9.5,
        crash_threshold_pct: float = 9.5,
        history_len: int = 3,
    ):
        self._no_buy = no_buy_spread_pct
        self._reduce = reduce_spread_pct
        self._sell = sell_spread_pct
        self._fast_reversal = fast_reversal_pct
        self._rocket = rocket_threshold_pct
        self._crash = crash_threshold_pct
        self._history: deque[float] = deque(maxlen=history_len)
        self._state: Optional[FuturesSnapshot] = None

    def update(self, futures_price: float, spot_price: float, futures_change_pct: float) -> None:
        if self._state is not None:
            self._history.append(self._state.spread_pct)
        self._state = FuturesSnapshot(futures_price, spot_price, futures_change_pct)

    def can_buy(self) -> tuple[bool, str]:
        if self._state is None:
            return True, "no_futures_data"
        fchg = self._state.futures_change_pct
        spread = self._state.spread_pct
        if fchg >= self._rocket:
            return False, f"futures_near_limit_up_{fchg:.1f}pct"
        if spread <= -self._no_buy:
            return False, f"backwardation_{spread:.2f}pct"
        return True, "ok"

    def position_size_ratio(self) -> float:
        if self._state is None:
            return 1.0
        if self._state.spread_pct <= -self._reduce:
            return 0.5
        return 1.0

    def should_exit(self) -> tuple[bool, str]:
        if self._state is None:
            return False, ""
        fchg = self._state.futures_change_pct
        spread = self._state.spread_pct
        if fchg <= -self._crash:
            return True, f"futures_crash_{fchg:.1f}pct"
        if spread <= -self._sell:
            return True, f"backwardation_exit_{spread:.2f}pct"
        if self._history:
            delta = spread - self._history[0]
            if delta <= -self._fast_reversal:
                return True, f"spread_fast_deterioration_{delta:.2f}pct"
        return False, ""

    def wait_for_limit_up(self) -> bool:
        if self._state is None:
            return False
        return self._state.futures_change_pct >= self._rocket

    def is_bullish_confirmation(self) -> bool:
        if self._state is None:
            return False
        return (
            self._state.spread_pct > 0.5
            and self._state.futures_change_pct > 3.0
        )
