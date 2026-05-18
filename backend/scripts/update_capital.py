"""
用 yfinance fast_info.shares 更新 StockList.capital（張）
TWSE: .TW  /  TPEx: .TWO
"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://stock:secret@localhost:5432/stock_force")
os.environ.setdefault("CONFIG_PATH", "/home/tommy0322/institutional-investors/config")

import yfinance as yf
from sqlalchemy import select, update
from app.db.base import AsyncSessionLocal
from app.db.models import StockList

_SUFFIX = {"TWSE": ".TW", "TPEx": ".TWO"}


async def main():
    async with AsyncSessionLocal() as db:
        stocks = (await db.execute(select(StockList))).scalars().all()

    print(f"共 {len(stocks)} 支股票，開始抓股本...")
    updated = 0
    failed = 0
    for i, s in enumerate(stocks):
        ticker = s.code + _SUFFIX.get(s.market, ".TW")
        try:
            info = yf.Ticker(ticker).fast_info
            shares = getattr(info, "shares", None)
            if shares and shares > 0:
                capital_lots = float(shares) / 1000.0
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(StockList)
                        .where(StockList.code == s.code)
                        .values(capital=capital_lots)
                    )
                    await db.commit()
                updated += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{len(stocks)}] updated={updated} failed={failed}", flush=True)

    print(f"\n完成：更新 {updated} 支，失敗/無資料 {failed} 支")


if __name__ == "__main__":
    asyncio.run(main())
