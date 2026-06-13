"""
月營收下載：使用 TWSE / TPEx Open API（JSON），一次取全市場資料。

TWSE: https://openapi.twse.com.tw/v1/opendata/t187ap05_L
TPEx: https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O

資料年月格式：民國年月，例如 "11504" = 民國115年04月 = 2026/04
營收單位：千元
"""

import httpx
import logging
from datetime import date

logger = logging.getLogger(__name__)

_TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
_TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"


def _parse_roc_ym(ym: str) -> tuple[int, int] | None:
    ym = ym.strip()
    if len(ym) != 5:
        return None
    try:
        roc_year = int(ym[:3])
        month = int(ym[3:])
        return roc_year + 1911, month
    except ValueError:
        return None


def _parse_revenue(s: str) -> float:
    try:
        v = float(s.replace(",", "").strip())
        return v if v > 0 else 0.0
    except (ValueError, AttributeError):
        return 0.0


def _parse_rows(data: list[dict]) -> list[dict]:
    rows = []
    for item in data:
        code = item.get("公司代號", "").strip()
        if not code.isdigit() or not (4 <= len(code) <= 6):
            continue
        ym = item.get("資料年月", "")
        parsed = _parse_roc_ym(ym)
        if not parsed:
            continue
        year, month = parsed
        revenue = _parse_revenue(item.get("營業收入-當月營收", "0"))
        if revenue <= 0:
            continue
        rows.append({"code": code, "year": year, "month": month, "revenue": revenue})
    return rows


async def fetch_monthly_revenue() -> tuple[list[dict], list[dict]]:
    async with httpx.AsyncClient(timeout=30) as client:
        twse_resp = await client.get(_TWSE_URL)
        twse_resp.raise_for_status()
        tpex_resp = await client.get(_TPEX_URL)
        tpex_resp.raise_for_status()

    twse_rows = _parse_rows(twse_resp.json())
    tpex_rows = _parse_rows(tpex_resp.json())
    return twse_rows, tpex_rows


def latest_available_month(ref: date | None = None) -> tuple[int, int]:
    d = ref or date.today()
    if d.day >= 10:
        m = d.month - 1 if d.month > 1 else 12
        y = d.year if d.month > 1 else d.year - 1
        return y, m
    if d.month > 2:
        return d.year, d.month - 2
    if d.month == 2:
        return d.year - 1, 12
    return d.year - 1, 11
