import requests
from datetime import date

BASE_TWSE = "https://www.twse.com.tw/rwd/zh"

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _get(url: str) -> dict:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return {}


async def fetch_institutional(trade_date: date) -> list[dict]:
    """TWSE 三大法人 T86（全市場上市）"""
    date_str = trade_date.strftime("%Y%m%d")
    url = f"{BASE_TWSE}/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
    data = _get(url)
    if data.get("stat") != "OK":
        return []
    rows = []
    for r in data.get("data", []):
        try:
            rows.append({
                "code": r[0].strip(),
                "trade_date": trade_date,
                "foreign_net": _parse_num(r[4]),
                "trust_net": _parse_num(r[7]),
                "dealer_net": _parse_num(r[10]),
                "three_major_net": _parse_num(r[11]),
            })
        except (IndexError, ValueError):
            continue
    return rows


async def fetch_daily_price(trade_date: date, codes: set[str] | None = None) -> list[dict]:
    """TWSE 個股日成交 MI_INDEX（全市場，可傳 codes 過濾只存目標股）"""
    date_str = trade_date.strftime("%Y%m%d")
    url = f"{BASE_TWSE}/afterTrading/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    data = _get(url)
    rows = []
    for table in data.get("tables", []):
        fields = table.get("fields", [])
        if not any("證券代號" in str(f) for f in fields):
            continue
        for r in table.get("data", []):
            if len(r) < 9:
                continue
            code = r[0].strip()
            if codes and code not in codes:
                continue
            try:
                rows.append({
                    "code": code,
                    "trade_date": trade_date,
                    "volume": int(r[2].replace(",", "").replace("--", "0") or "0"),
                    "open": _parse_num(r[5]),
                    "high": _parse_num(r[6]),
                    "low": _parse_num(r[7]),
                    "close": _parse_num(r[8]),
                })
            except (ValueError, IndexError):
                continue
    return rows


async def fetch_margin(trade_date: date) -> list[dict]:
    """TWSE 融資融券 TWT93U"""
    date_str = trade_date.strftime("%Y%m%d")
    url = f"{BASE_TWSE}/marginTrading/TWT93U?response=json&date={date_str}&selectType=ALL"
    data = _get(url)
    if data.get("stat") != "OK":
        return []
    rows = []
    for r in data.get("data", []):
        try:
            rows.append({
                "code": r[0].strip(),
                "trade_date": trade_date,
                "margin_balance": _parse_int(r[6]),
                "margin_change": _parse_int(r[7]),
                "short_balance": _parse_int(r[12]),
                "short_change": _parse_int(r[13]),
            })
        except (IndexError, ValueError):
            continue
    return rows


def _parse_num(s: str) -> float:
    return float(s.replace(",", "").replace("+", "").strip() or "0")


def _parse_int(s: str) -> int:
    return int(s.replace(",", "").replace("+", "").strip() or "0")
