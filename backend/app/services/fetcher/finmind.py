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


async def fetch_monthly_revenue_history(code: str, start_date: str = "2023-01-01") -> list[dict]:
    """FinMind TaiwanStockMonthRevenue — 歷史月營收

    FinMind date = 公告月（announcement month），非營收月。
    e.g. date "2026-06-10" = May revenue → store month=5.
    FinMind revenue 單位 = NTD (元)，需 ÷1000 轉換為千元與 MOPS 一致。
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(FINMIND_BASE, params=_params(
            "TaiwanStockMonthRevenue", code, start_date
        ))
    if resp.status_code != 200:
        return []
    rows = []
    for r in resp.json().get("data", []):
        try:
            dt = r.get("date", "")[:7]
            year, month = int(dt[:4]), int(dt[5:7])
            # 公告月 → 營收月（減 1）
            if month == 1:
                year -= 1
                month = 12
            else:
                month -= 1
            revenue = float(r.get("revenue", 0) or 0) / 1000  # NTD → 千元
            if revenue <= 0:
                continue
            rows.append({"code": code, "year": year, "month": month, "revenue": revenue})
        except (ValueError, TypeError):
            continue
    return rows


async def fetch_quarterly_eps(code: str, start_date: str = "2020-01-01") -> list[dict]:
    """FinMind TaiwanStockFinancialStatements — 季報損益"""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(FINMIND_BASE, params=_params(
            "TaiwanStockFinancialStatements", code, start_date
        ))
    if resp.status_code != 200:
        return []
    raw = resp.json().get("data", [])
    if not raw:
        return []

    from collections import defaultdict
    by_period: dict[str, dict] = defaultdict(dict)
    for r in raw:
        key = r.get("date", "")[:10]
        t = r.get("type", "")
        v = r.get("value", 0)
        by_period[key][t] = v

    rows = []
    for dt_str, fields in by_period.items():
        try:
            yr = int(dt_str[:4])
            mo = int(dt_str[5:7])
        except (ValueError, IndexError):
            continue
        quarter = (mo - 1) // 3 + 1
        eps = float(fields.get("EPS", 0) or 0)
        rows.append({
            "code": code,
            "year": yr,
            "quarter": quarter,
            "eps": eps,
            "revenue":   float(fields.get("Revenue", 0) or 0),
            "op_income": float(fields.get("OperatingIncome", 0) or 0),
            "net_income": float(fields.get("NetIncome", 0) or 0),
        })
    return rows


async def fetch_stock_capital(code: str) -> float:
    """FinMind TaiwanStockBalanceSheet — 取得股本（張）
    OrdinaryShare 欄位單位：NTD 元，面額 10 元/股 → 張 = OrdinaryShare / 10 / 1000
    """
    import datetime as _dt
    start = (_dt.date.today() - _dt.timedelta(days=365)).isoformat()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            FINMIND_BASE,
            params={
                "dataset": "TaiwanStockBalanceSheet",
                "data_id": code,
                "start_date": start,
                **({"token": settings.finmind_token} if settings.finmind_token else {}),
            }
        )
    if resp.status_code != 200:
        return 0.0
    rows = resp.json().get("data", [])
    # 取最新一筆 OrdinaryShare 或 CapitalStock
    capital_ntd = 0.0
    for row in reversed(rows):
        if row.get("type") in ("OrdinaryShare", "CapitalStock"):
            v = float(row.get("value", 0) or 0)
            if v > 0:
                capital_ntd = v
                break
    if capital_ntd <= 0:
        return 0.0
    return capital_ntd / 10 / 1000
