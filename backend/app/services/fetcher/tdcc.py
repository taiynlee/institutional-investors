import csv
import io
from datetime import date
import httpx

TDCC_BULK_URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"


async def fetch_shareholding_bulk() -> list[dict]:
    """
    TDCC 集保戶股權分散表 — level 14（400~999 張）+ level 15（1000 張以上）
    回傳格式: [{"code", "report_date", "holders_1000_lot", "pct_1000_lot", "pct_400_lot"}, ...]
    pct_400_lot = level14_pct + level15_pct（四百張以上大戶合計持股比例）
    """
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(TDCC_BULK_URL)
    if resp.status_code != 200:
        return []

    from collections import defaultdict
    data: dict[tuple, dict] = defaultdict(lambda: {
        "holders_1000_lot": 0, "pct_1000_lot": 0.0, "pct_400_lot": 0.0
    })

    content = resp.content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(content))
    next(reader, None)  # skip header
    for r in reader:
        if len(r) < 6:
            continue
        level = r[2].strip()
        if level not in ("14", "15"):
            continue
        try:
            report_date = date(int(r[0][:4]), int(r[0][4:6]), int(r[0][6:8]))
            code = r[1].strip()
            key = (code, report_date)
            pct = float(r[5]) if r[5].strip() else 0.0
            if level == "15":
                data[key]["holders_1000_lot"] = int(r[3]) if r[3].strip() else 0
                data[key]["pct_1000_lot"] = pct
                data[key]["pct_400_lot"] += pct
            elif level == "14":
                data[key]["pct_400_lot"] += pct
        except (ValueError, IndexError):
            continue

    return [
        {
            "code": code,
            "report_date": report_date,
            "holders_1000_lot": v["holders_1000_lot"],
            "pct_1000_lot":     round(v["pct_1000_lot"], 4),
            "pct_400_lot":      round(v["pct_400_lot"], 4),
        }
        for (code, report_date), v in data.items()
    ]
