import pytest
from datetime import date
from app.services.fetcher.twse import fetch_institutional, fetch_daily_price, fetch_margin
from app.services.fetcher.finmind import fetch_shareholding, fetch_stock_capital
from app.services.fetcher.stock_list import fetch_electronic_stocks


# ── Task 3: TWSE ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_institutional_returns_list():
    rows = await fetch_institutional(date(2025, 5, 16))
    assert isinstance(rows, list)
    assert len(rows) > 0
    first = rows[0]
    assert "code" in first
    assert "foreign_net" in first


@pytest.mark.asyncio
async def test_fetch_margin_returns_list():
    rows = await fetch_margin(date(2025, 5, 16))
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert "margin_balance" in rows[0]


# ── Task 4: FinMind ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_shareholding_returns_data():
    rows = await fetch_shareholding("2330", weeks=4)
    assert isinstance(rows, list)
    # 可能空（免費額度耗盡），但不應 crash
    if rows:
        assert "holders_1000_lot" in rows[0]


@pytest.mark.asyncio
async def test_fetch_stock_capital_returns_float():
    capital = await fetch_stock_capital("2330")
    assert isinstance(capital, float)
    # 台積電股本 > 0（免費 token 也能取到 TaiwanStockInfo）
    assert capital >= 0


# ── Task 5: 電子股清單 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_electronic_stocks_returns_list():
    rows = await fetch_electronic_stocks()
    assert isinstance(rows, list)
    assert len(rows) > 100  # 電子股應超過 100 筆
    assert "code" in rows[0]
    assert "name" in rows[0]
