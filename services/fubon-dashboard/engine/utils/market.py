from datetime import time as _t
from engine.utils.tz import now_tw

MARKET_OPEN       = _t(9, 0)
MARKET_CLOSE      = _t(13, 30)
PRE_SESSION_START = _t(8, 30)   # 提前 30 分鐘登入，確保 09:00 前 WebSocket 已就緒
SESSION_END       = _t(13, 36)  # 收盤後 6 分鐘確保強制平倉完成


def is_weekday() -> bool:
    return now_tw().weekday() < 5  # Mon=0 … Fri=4


def is_market_hours() -> bool:
    return MARKET_OPEN <= now_tw().time() < MARKET_CLOSE


def is_pre_session_time() -> bool:
    t = now_tw().time()
    return PRE_SESSION_START <= t < MARKET_OPEN


def is_session_active() -> bool:
    """8:30–13:36 平日 → 應維持連線（08:30 提前登入確保 09:00 前就緒）"""
    if not is_weekday():
        return False
    t = now_tw().time()
    return PRE_SESSION_START <= t < SESSION_END


def seconds_to_open() -> float:
    now = now_tw()
    open_dt = now.replace(hour=9, minute=0, second=0, microsecond=0)
    return (open_dt - now).total_seconds()
