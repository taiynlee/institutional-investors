import requests
from datetime import date

BASE_TWSE = "https://www.twse.com.tw/rwd/zh"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    "Referer": "https://www.twse.com.tw/",
}


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
                "foreign_net": _parse_num(r[4]) / 1000,       # 外陸資買賣超(不含外資自營商)
                "trust_net": _parse_num(r[10]) / 1000,       # 投信買賣超
                "dealer_net": _parse_num(r[11]) / 1000,      # 自營商買賣超(合計)
                "three_major_net": _parse_num(r[18]) / 1000, # 三大法人買賣超
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
    # TWT93U fields: [代號, 名稱, 融資前日餘額, 賣出, 買進, 現券, 融資今日餘額, 次日限額,
    #                  借券前日餘額, 借券當日賣出, 借券還券, 借券調整, 借券今日餘額, 次日可限額, 備註]
    for r in data.get("data", []):
        try:
            mb = _parse_int(r[6])
            mb_prev = _parse_int(r[2])
            sb = _parse_int(r[12])
            sb_prev = _parse_int(r[8])
            rows.append({
                "code": r[0].strip(),
                "trade_date": trade_date,
                "margin_balance": mb,
                "margin_change": mb - mb_prev,
                "short_balance": sb,
                "short_change": sb - sb_prev,
            })
        except (IndexError, ValueError, AttributeError):
            continue
    return rows


async def fetch_lending(trade_date: date) -> list[dict]:
    """TWSE 借券賣出餘額 TWT38U（已廢棄，資料已合併至 TWT93U，保留函式避免 import 錯誤）"""
    return []
    data = _get(url)
    if data.get("stat") != "OK":
        return []
    rows = []
    # TWT38U fields: [代號, 名稱, 前日餘額, 當日賣出, 當日還券, 當日調整, 今日餘額, 次日限額]
    for r in data.get("data", []):
        try:
            prev_bal = _parse_int(r[2])
            today_bal = _parse_int(r[6])
            rows.append({
                "code": r[0].strip(),
                "trade_date": trade_date,
                "lending_balance": today_bal,
                "lending_change": today_bal - prev_bal,
            })
        except (IndexError, ValueError, AttributeError):
            continue
    return rows


def _parse_num(s) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    return float(str(s).replace(",", "").replace("+", "").strip() or "0")


def _parse_int(s) -> int:
    if isinstance(s, int):
        return s
    return int(str(s).replace(",", "").replace("+", "").strip() or "0")
