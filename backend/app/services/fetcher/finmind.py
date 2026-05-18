import httpx
from datetime import date, timedelta
from app.config import settings

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"


def _params(dataset: str, data_id: str, start_date: str) -> dict:
    params = {"dataset": dataset, "data_id": data_id, "start_date": start_date}
    if settings.finmind_token:
        params["token"] = settings.finmind_token
    return params


async def fetch_shareholding(code: str, weeks: int = 12) -> list[dict]:
    """FinMind TaiwanStockShareholding — 千張以上大戶持股"""
    start = (date.today() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(FINMIND_BASE, params=_params(
            "TaiwanStockShareholding", code, start
        ))
    if resp.status_code != 200:
        return []
    rows = []
    for r in resp.json().get("data", []):
        if r.get("HoldingSharesLevel") == "1,000張以上":
            rows.append({
                "code": code,
                "report_date": date.fromisoformat(r["date"]),
                "holders_1000_lot": int(r.get("people", 0)),
                "pct_1000_lot": float(r.get("holdingSharesPercent", 0)),
            })
    return rows


async def fetch_stock_capital(code: str) -> float:
    """
    FinMind TaiwanStockInfo — 取得股本（張）
    capital 欄位：股本千元，÷10（票面）÷1000 = 張數
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            FINMIND_BASE,
            params={
                "dataset": "TaiwanStockInfo",
                "data_id": code,
                **({"token": settings.finmind_token} if settings.finmind_token else {}),
            }
        )
    if resp.status_code != 200:
        return 0.0
    data = resp.json().get("data", [])
    if not data:
        return 0.0
    capital_k_ntd = float(data[0].get("capital", 0))
    return capital_k_ntd / 10 / 1000  # 回傳：張
