import requests
from app.config import settings

ELECTRONIC_INDUSTRIES = {
    "電子工業", "電子零組件業", "其他電子業", "其他電子類",
    "光電業", "電腦及週邊設備業", "電子通路業", "半導體業",
    "通信網路業",
}


async def fetch_electronic_stocks() -> list[dict]:
    """
    FinMind TaiwanStockInfo — 電子類股清單（上市+上櫃）
    過濾 ELECTRONIC_INDUSTRIES，無子族群標籤。
    """
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockInfo"},
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        data = r.json().get("data", [])
    except Exception:
        return []

    seen = set()
    rows = []
    for item in data:
        if item.get("industry_category", "") not in ELECTRONIC_INDUSTRIES:
            continue
        code = item.get("stock_id", "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append({
            "code": code,
            "name": item.get("stock_name", "").strip(),
            "market": "TWSE" if item.get("type") == "twse" else "TPEx",
            "sector": item.get("industry_category", ""),
            "tags": "",
        })
    return rows
