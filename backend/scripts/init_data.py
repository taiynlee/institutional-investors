"""
快速初始化資料腳本（本地開發用）
- 股票清單：從 FinMind 取得，capital 設 0（跳過逐檔查詢，速度快）
- 90日回填：TWSE 三大法人 + 日成交 + 融資
- 跑一次篩選
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://stock:secret@localhost:5432/stock_force")
os.environ.setdefault("CONFIG_PATH", "/home/tommy0322/institutional-investors/config")

from datetime import date, timedelta
from sqlalchemy import select
from app.db.base import AsyncSessionLocal, engine, Base
from app.db.models import StockList, DailyPrice, Institutional, MarginTrading, ScreeningResult
from app.services.fetcher.stock_list import fetch_electronic_stocks
from app.services.fetcher.twse import fetch_institutional, fetch_margin
from app.services.fetcher.price import fetch_prices_yf
from app.services.fetcher.market import fetch_twii_bb_stats
from app.services.screener import check_entry_criteria, calc_vol_ratio, calc_chip_ratios, calc_score


async def step1_stock_list():
    print("Step 1: 取得電子股清單 (capital=0)...")
    rows = await fetch_electronic_stocks()
    if not rows:
        print("  ✗ 無資料，FinMind API 可能有問題")
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from datetime import datetime
    async with AsyncSessionLocal() as db:
        count = 0
        for r in rows:
            existing = (await db.execute(
                select(StockList).where(StockList.code == r["code"])
            )).scalar_one_or_none()
            if not existing:
                db.add(StockList(**r, capital=0.0))
                count += 1
        await db.commit()
    print(f"  ✓ 新增 {count} 檔，共 {len(rows)} 檔電子股")


async def step2_backfill(days: int = 95, skip_prices: bool = False):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # --- 2a: 價量 via yfinance (bulk) ---
    if skip_prices:
        print("Step 2a: 跳過（價量已有資料）")
    else:
        print(f"Step 2a: 回填近 {days} 日價量 (yfinance)...")
        async with AsyncSessionLocal() as db:
            stocks = [(r[0], r[1]) for r in (await db.execute(select(StockList.code, StockList.market))).all()]
        print(f"  取得 {len(stocks)} 支股票，開始批次下載...")
        price_rows = await fetch_prices_yf(stocks, days=days)
        CHUNK = 1000
        written = 0
        for start_idx in range(0, len(price_rows), CHUNK):
            chunk = price_rows[start_idx : start_idx + CHUNK]
            async with AsyncSessionLocal() as db:
                stmt = pg_insert(DailyPrice).values(chunk)
                stmt = stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"])
                await db.execute(stmt)
                await db.commit()
            written += len(chunk)
        print(f"  ✓ 共寫入 {written} 筆價量資料")

    # --- 2b: 法人 via TWSE T86 (逐日) ---
    print(f"Step 2b: 回填近 {days} 日法人 (TWSE T86)...")
    today = date.today()
    # 只保留 stock_list 中的上市上櫃電子股代號
    async with AsyncSessionLocal() as db:
        stock_codes = set(r[0] for r in (await db.execute(select(StockList.code))).all())
    fetched = 0
    for i in range(days, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            rows_i = [r for r in await fetch_institutional(d) if r["code"] in stock_codes]
            margin_rows = [r for r in await fetch_margin(d) if r["code"] in stock_codes]
            if not rows_i and not margin_rows:
                continue
            async with AsyncSessionLocal() as db:
                if rows_i:
                    stmt = pg_insert(Institutional).values(rows_i)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"])
                    await db.execute(stmt)
                if margin_rows:
                    stmt = pg_insert(MarginTrading).values(margin_rows)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"])
                    await db.execute(stmt)
                await db.commit()
            fetched += 1
            print(f"  {d}: 法人{len(rows_i)} 融資{len(margin_rows)}", flush=True)
        except Exception as e:
            print(f"  {d}: 失敗 {type(e).__name__}: {str(e)[:80]}")
        await asyncio.sleep(0.5)
    print(f"  ✓ 共回填 {fetched} 個交易日法人資料")


async def step3_screener():
    print("Step 3: 執行篩選...")
    market_bb_peak, market_bb_now = fetch_twii_bb_stats()
    market_bb_drop = max(0, market_bb_peak - market_bb_now)
    print(f"  大盤 BB 降幅: {market_bb_drop:.2f}")

    async with AsyncSessionLocal() as db:
        stocks = (await db.execute(select(StockList))).scalars().all()

    today = date.today()
    results = []
    cutoff = today - timedelta(days=120)

    from sqlalchemy import and_

    for stock in stocks:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(DailyPrice)
                .where(and_(DailyPrice.code == stock.code, DailyPrice.trade_date >= cutoff))
                .order_by(DailyPrice.trade_date)
            )).scalars().all()
        if len(rows) < 52:
            continue

        opens = [r.open for r in rows]
        highs = [r.high for r in rows]
        lows = [r.low for r in rows]
        closes = [r.close for r in rows]
        volumes = [r.volume for r in rows]

        entry = check_entry_criteria(opens, highs, lows, closes, volumes)
        if not entry["passes"]:
            continue

        vol_ratio = calc_vol_ratio(volumes)

        # 法人籌碼
        inst_cutoff = today - timedelta(days=20)
        async with AsyncSessionLocal() as db:
            inst_rows = (await db.execute(
                select(Institutional)
                .where(and_(Institutional.code == stock.code, Institutional.trade_date >= inst_cutoff))
                .order_by(Institutional.trade_date)
            )).scalars().all()
            margin_rows = (await db.execute(
                select(MarginTrading)
                .where(and_(MarginTrading.code == stock.code, MarginTrading.trade_date >= inst_cutoff))
                .order_by(MarginTrading.trade_date)
            )).scalars().all()

        chip = calc_chip_ratios(inst_rows, stock.capital)

        # 融資5日變化
        if len(margin_rows) >= 5:
            mb_now = margin_rows[-1].margin_balance
            mb_5d = margin_rows[-5].margin_balance
            chip["margin_5d_chg"] = float((mb_now - mb_5d) / mb_5d) if mb_5d > 0 else 0.0
        else:
            chip["margin_5d_chg"] = 0.0
        chip["holders_1000_chg"] = 0

        # 法人硬門檻：6日或12日買超/股本 >= 1%
        if stock.capital > 0:
            if chip["chip_ratio_6d"] < 1.0 and chip["chip_ratio_12d"] < 1.0:
                continue

        score = calc_score(entry, chip, market_bb_drop)

        results.append(ScreeningResult(
            code=stock.code,
            name=stock.name,
            calc_date=today,
            tags=stock.tags,
            bb_position=entry["bb_position"],
            bb_peak=entry["bb_peak"],
            peak_date=None,
            is_squeeze=entry["is_squeeze"],
            vol_ratio=vol_ratio,
            score=score,
            passes=True,
            **chip,
        ))
        print(f"  ✓ {stock.code} {stock.name} BB={entry['bb_position']} score={score}")

    from sqlalchemy import delete as sa_delete
    async with AsyncSessionLocal() as db:
        await db.execute(sa_delete(ScreeningResult).where(ScreeningResult.calc_date == today))
        for r in results:
            db.add(r)
        await db.commit()
    print(f"  ✓ 篩出 {len(results)} 檔，已寫入 DB")


async def main():
    import sys
    args = sys.argv[1:]
    skip_step1 = "--skip-step1" in args
    skip_prices = "--skip-prices" in args

    if not skip_step1:
        await step1_stock_list()
    else:
        print("Step 1: 跳過（stock_list 已有資料）")
    await step2_backfill(90, skip_prices=skip_prices)
    await step3_screener()
    print("\n完成！開啟 http://localhost:5173 查看儀表板")


if __name__ == "__main__":
    asyncio.run(main())
