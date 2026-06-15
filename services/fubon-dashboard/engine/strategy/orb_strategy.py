from datetime import datetime, time as dtime
from engine.utils.tz import now_tw


class ORBStrategy:
    """09:00–09:xx 記錄 ORB 高低點，之後偵測突破訊號。結束時間由 window_minutes 決定。"""

    _ORB_START = dtime(9, 0)

    def __init__(self, window_minutes: int = 15):
        self.window_minutes = window_minutes
        # ORB 結束時間由 window_minutes 動態計算（預設 09:15）
        self._ORB_END = dtime(9 + window_minutes // 60, window_minutes % 60)
        self.orb_high: float | None = None
        self.orb_low: float | None = None
        self.is_locked: bool = False
        self._start_time: datetime | None = None

    def on_bar(self, high: float, low: float, time: datetime):
        if self.is_locked:
            return

        # 以牆上時鐘判斷 ORB 窗口，避免引擎重啟後錯判 elapsed
        now = now_tw().time().replace(second=0, microsecond=0)

        if now >= self._ORB_END:
            # 已過 09:15 → 直接 lock（用目前累積的高低，若無則用當前 bar）
            if self.orb_high is None:
                self.orb_high = high
            if self.orb_low is None:
                self.orb_low = low
            self.is_locked = True
            return

        if now < self._ORB_START:
            return  # 開盤前不計入

        # 09:00–09:14：累積 ORB 高低
        if self._start_time is None:
            self._start_time = time
        self.orb_high = max(self.orb_high or high, high)
        self.orb_low = min(self.orb_low or low, low)

    def check_breakout(
        self,
        price: float,
        volume: int,
        avg_open_volume: float,
        volume_multiplier: float,
        ma5_5min: float,
        ma20_5min: float,
    ) -> bool:
        if not self.is_locked or self.orb_high is None:
            return False
        above_orb = price > self.orb_high
        vol_ok = volume >= avg_open_volume * volume_multiplier
        trend_ok = ma5_5min > ma20_5min
        return above_orb and vol_ok and trend_ok
