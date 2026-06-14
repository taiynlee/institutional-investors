from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ_TW = ZoneInfo("Asia/Taipei")


def now_tw() -> datetime:
    return datetime.now(tz=TZ_TW)


def today_tw() -> date:
    return now_tw().date()


def from_ts_ns(ts_ns: int) -> datetime:
    return datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=TZ_TW)
