import csv
import io
from datetime import date
import httpx

TDCC_BULK_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"


async def fetch_shareholding_bulk() -> list[dict]:
    """
    TDCC 集保戶股權分散表 — 一次取得全市場所有股票當週 level 15（千張以上）持股資料。
    回傳格式: [{"code", "report_date", "holders_1000_lot", "pct_1000_lot"}, ...]
    Level 15 = 持股超過 1,000,000 股 = 超過 1000 張
    """
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(TDCC_BULK_URL)
    if resp.status_code != 200:
        return []

    rows = []
    content = resp.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))
    next(reader, None)  # skip header
    for r in reader:
        if len(r) < 6:
            continue
        if r[2].strip() != "15":
            continue
        try:
            report_date = date(int(r[0][:4]), int(r[0][4:6]), int(r[0][6:8]))
            rows.append({
                "code": r[1].strip(),
                "report_date": report_date,
                "holders_1000_lot": int(r[3]) if r[3].strip() else 0,
                "pct_1000_lot": float(r[5]) if r[5].strip() else 0.0,
            })
        except (ValueError, IndexError):
            continue
    return rows
