from datetime import datetime


class ORBStrategy:
    """09:00–09:15 記錄 ORB 高低點，之後偵測突破訊號。"""

    def __init__(self, window_minutes: int = 15):
        self.window_minutes = window_minutes
        self.orb_high: float | None = None
        self.orb_low: float | None = None
        self.is_locked: bool = False
        self._start_time: datetime | None = None

    def on_bar(self, high: float, low: float, time: datetime):
        if self._start_time is None:
            self._start_time = time

        elapsed = (time - self._start_time).seconds // 60
        if self.is_locked:
            return

        if elapsed < self.window_minutes:
            self.orb_high = max(self.orb_high or high, high)
            self.orb_low = min(self.orb_low or low, low)
        else:
            self.is_locked = True

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
