import asyncio
import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_
from app.db.base import AsyncSessionLocal
from app.db.models import (
    FetchLog, DailyPrice, Institutional, MarginTrading, SecuritiesLending,
    Shareholding, ScreeningResult, StockList,
)
from app.services.fetcher.twse import fetch_institutional, fetch_daily_price, fetch_margin, fetch_lending
from app.services.fetcher.finmind import fetch_shareholding
from app.services.fetcher.market import fetch_twii_bb_stats
from app.services.fetcher.stock_list import fetch_electronic_stocks
from app.services.screener import check_entry_criteria, calc_vol_ratio, calc_chip_ratios, calc_score, calc_dip_buy_bonus

logger = logging.getLogger(__name__)


async def _already_fetched(job_name: str, fetch_date: date) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(FetchLog).where(
                and_(
                    FetchLog.job_name == job_name,
                    FetchLog.fetch_date == fetch_date,
                    FetchLog.status == "success",
                )
            )
        )
        return result.scalar_one_or_none() is not None


async def _log_fetch(job_name: str, fetch_date: date, status: str, rows: int = 0):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    async with AsyncSessionLocal() as db:
        stmt = pg_insert(FetchLog).values(
            job_name=job_name, fetch_date=fetch_date, status=status, rows_fetched=rows
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["job_name", "fetch_date"],
            set_={"status": status, "rows_fetched": rows},
        )
        await db.execute(stmt)
        await db.commit()


async def job1_institutional_price():
    """16:05 — 三大法人 + 日成交（只存 stock_list 內的上市上櫃電子股）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    today = date.today()
    if await _already_fetched("job1", today):
        return
    try:
        async with AsyncSessionLocal() as db:
            stock_codes = set(r[0] for r in (await db.execute(select(StockList.code))).all())
        all_inst = await fetch_institutional(today)
        rows = [r for r in all_inst if r["code"] in stock_codes]
        price_rows = await fetch_daily_price(today, codes=stock_codes)
        async with AsyncSessionLocal() as db:
            if rows:
                stmt = pg_insert(Institutional).values(rows)
                await db.execute(stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"]))
            if price_rows:
                stmt = pg_insert(DailyPrice).values(price_rows)
                await db.execute(stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"]))
            await db.commit()
        await _log_fetch("job1", today, "success", len(rows) + len(price_rows))
    except Exception as e:
        await _log_fetch("job1", today, "failed")
        logger.error(f"job1 failed: {e}")


async def job2_margin():
    """18:30 — 融資融券 + 借券賣出（只存 stock_list 內的上市上櫃電子股）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    today = date.today()
    if await _already_fetched("job2", today):
        return
    try:
        async with AsyncSessionLocal() as db:
            stock_codes = set(r[0] for r in (await db.execute(select(StockList.code))).all())
        all_margin = await fetch_margin(today)
        margin_rows = [r for r in all_margin if r["code"] in stock_codes]
        all_lending = await fetch_lending(today)
        lending_rows = [r for r in all_lending if r["code"] in stock_codes]
        async with AsyncSessionLocal() as db:
            if margin_rows:
                stmt = pg_insert(MarginTrading).values(margin_rows)
                await db.execute(stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"]))
            if lending_rows:
                stmt = pg_insert(SecuritiesLending).values(lending_rows)
                await db.execute(stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"]))
            await db.commit()
        await _log_fetch("job2", today, "success", len(margin_rows) + len(lending_rows))
    except Exception as e:
        await _log_fetch("job2", today, "failed")
        logger.error(f"job2 failed: {e}")


async def job3_shareholding():
    """20:30 — FinMind 持股集中度（只在週五執行）"""
    today = date.today()
    if today.weekday() != 4:
        return
    if await _already_fetched("job3", today):
        return
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(StockList.code))
            codes = [r[0] for r in result.fetchall()]
        total = 0
        for code in codes:
            rows = await fetch_shareholding(code, weeks=1)
            async with AsyncSessionLocal() as db:
                for r in rows:
                    db.add(Shareholding(**r))
                await db.commit()
            total += len(rows)
            await asyncio.sleep(0.5)
        await _log_fetch("job3", today, "success", total)
    except Exception as e:
        await _log_fetch("job3", today, "failed")
        logger.error(f"job3 failed: {e}")


async def job4_screener():
    """21:00 — 執行篩選，更新 screening_result"""
    today = date.today()
    if await _already_fetched("job4", today):
        return
    try:
        market_bb_peak, market_bb_now = fetch_twii_bb_stats()
        market_bb_drop = max(0, market_bb_peak - market_bb_now)
        async with AsyncSessionLocal() as db:
            stocks = (await db.execute(select(StockList))).scalars().all()
        results = []
        for stock in stocks:
            opens, highs, lows, closes, volumes, price_dates = await _get_price_series(stock.code)
            if len(closes) < 65:
                continue
            entry = check_entry_criteria(opens, highs, lows, closes, volumes)
            if not entry["passes"]:
                continue
            chip = await _get_chip_summary(stock.code, today, stock.capital)
            # A 策略：chip_1d ≥ 1%（今日主力剛發動）AND chip_12d > 0
            a_chip_ok = (
                chip.get("chip_ratio_1d", 0) >= 1.0
                and chip.get("chip_ratio_12d", 0) > 0
            )
            # B 策略：chip_6d ≥ 1% AND chip_12d ≥ 1%
            b_chip_ok = (
                chip.get("chip_ratio_6d", 0) >= 1.0
                and chip.get("chip_ratio_12d", 0) >= 1.0
            )
            a_passes = entry["passes_A"] and a_chip_ok
            b_passes = entry["passes_B_price"] and b_chip_ok
            if not (a_passes or b_passes):
                continue
            # 標記入場策略
            if a_passes and b_passes:
                strategy_tag = "A+B"
            elif a_passes:
                strategy_tag = "A"
            else:
                strategy_tag = "B"
            tags = strategy_tag
            vol_ratio = calc_vol_ratio(volumes)
            base_score = calc_score(entry, chip, market_bb_drop, vol_ratio)
            # 特別加分：資加（下跌日法人買超各+1，上限+5）+ 戶加（千張大戶週增減%）
            inst_map = await _get_inst_map(stock.code)
            dip_bonus = calc_dip_buy_bonus(closes, price_dates, inst_map)
            holders_bonus = await _get_holders_bonus(stock.code)
            chip_fields = {k: chip[k] for k in (
                "foreign_6d_net", "trust_6d_net",
                "chip_ratio_1d", "chip_ratio_6d", "chip_ratio_12d",
                "margin_5d_chg", "lending_5d_chg", "holders_1000_chg",
            ) if k in chip}
            results.append(ScreeningResult(
                code=stock.code,
                name=stock.name,
                calc_date=today,
                tags=tags,
                bb_position=entry["bb_position"],
                bb_peak=entry["bb_peak"],
                peak_date=None,
                peak_days_ago=entry["peak_days_ago"],
                is_squeeze=entry["is_squeeze"],
                vol_ratio=vol_ratio,
                score=base_score,
                dip_bonus=dip_bonus,
                holders_bonus=holders_bonus,
                passes=True,
                **chip_fields,
            ))
        from sqlalchemy import delete
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ScreeningResult).where(ScreeningResult.calc_date == today))
            for r in results:
                db.add(r)
            await db.commit()
        await _log_fetch("job4", today, "success", len(results))
        logger.info(f"Screener found {len(results)} stocks")
    except Exception as e:
        await _log_fetch("job4", today, "failed")
        logger.error(f"job4 failed: {e}")


async def _get_price_series(code: str, days: int = 200) -> tuple[list, list, list, list, list, list]:
    """回傳 (opens, highs, lows, closes, volumes, dates)"""
    cutoff = date.today() - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DailyPrice)
            .where(and_(DailyPrice.code == code, DailyPrice.trade_date >= cutoff))
            .order_by(DailyPrice.trade_date)
        )
        rows = result.scalars().all()
    return (
        [r.open for r in rows],
        [r.high for r in rows],
        [r.low for r in rows],
        [r.close for r in rows],
        [r.volume for r in rows],
        [r.trade_date for r in rows],
    )


async def _get_holders_bonus(code: str) -> float:
    """千張大戶本週 vs 上週增減%，1% = 1分（可負）"""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Shareholding)
            .where(Shareholding.code == code)
            .order_by(Shareholding.report_date.desc())
            .limit(2)
        )).scalars().all()
    if len(rows) < 2:
        return 0.0
    this_week = rows[0].holders_1000_lot
    last_week = rows[1].holders_1000_lot
    if last_week <= 0:
        return 0.0
    pct_change = (this_week - last_week) / last_week * 100
    return round(pct_change, 1)


async def _get_inst_map(code: str, days: int = 60) -> dict:
    """回傳 {trade_date: foreign_net + trust_net}，用於特別加分計算"""
    cutoff = date.today() - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Institutional)
            .where(and_(Institutional.code == code, Institutional.trade_date >= cutoff))
            .order_by(Institutional.trade_date)
        )).scalars().all()
    return {r.trade_date: r.foreign_net + r.trust_net for r in rows}


async def _get_chip_summary(code: str, today: date, capital_lots: float) -> dict:
    cutoff_12d = today - timedelta(days=18)
    cutoff_5d = today - timedelta(days=8)
    async with AsyncSessionLocal() as db:
        inst = (await db.execute(
            select(Institutional)
            .where(and_(Institutional.code == code, Institutional.trade_date >= cutoff_12d))
            .order_by(Institutional.trade_date)
        )).scalars().all()
        margin = (await db.execute(
            select(MarginTrading)
            .where(and_(MarginTrading.code == code, MarginTrading.trade_date >= cutoff_5d))
            .order_by(MarginTrading.trade_date)
        )).scalars().all()
        lending = (await db.execute(
            select(SecuritiesLending)
            .where(and_(SecuritiesLending.code == code, SecuritiesLending.trade_date >= cutoff_5d))
            .order_by(SecuritiesLending.trade_date)
        )).scalars().all()

    chip = calc_chip_ratios(list(inst), capital_lots)

    margin_chg = 0.0
    if len(margin) >= 2:
        old_bal = margin[0].margin_balance
        new_bal = margin[-1].margin_balance
        margin_chg = (new_bal - old_bal) / old_bal if old_bal > 0 else 0.0

    lending_chg = 0.0
    if len(lending) >= 2:
        old_bal = lending[0].lending_balance
        new_bal = lending[-1].lending_balance
        lending_chg = (new_bal - old_bal) / old_bal if old_bal > 0 else 0.0

    return {
        **chip,
        "margin_5d_chg": margin_chg,
        "lending_5d_chg": lending_chg,
        "holders_1000_chg": 0,
    }


async def backfill_90_days():
    """首次啟動時，補抓 90 日歷史（僅在 daily_price 為空時執行）"""
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(DailyPrice))).first()
    if count is not None:
        logger.info("Data exists, skipping backfill.")
        return

    logger.info("Starting 90-day backfill...")
    today = date.today()
    for i in range(90, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            rows_i = await fetch_institutional(d)
            price_rows = await fetch_daily_price(d)
            margin_rows = await fetch_margin(d)
            lending_rows = await fetch_lending(d)
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            async with AsyncSessionLocal() as db:
                if rows_i:
                    await db.execute(pg_insert(Institutional).values(rows_i).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                if price_rows:
                    await db.execute(pg_insert(DailyPrice).values(price_rows).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                if margin_rows:
                    await db.execute(pg_insert(MarginTrading).values(margin_rows).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                if lending_rows:
                    await db.execute(pg_insert(SecuritiesLending).values(lending_rows).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                await db.commit()
        except Exception as e:
            logger.warning(f"Backfill {d} failed: {e}")
        await asyncio.sleep(1)
    logger.info("Backfill complete.")


async def backfill_lending_90_days():
    """補抓 90 日借券賣出歷史（securities_lending 表為空時執行）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(SecuritiesLending))).first()
    if count is not None:
        logger.info("Lending data exists, skipping backfill.")
        return
    logger.info("Starting 90-day lending backfill...")
    async with AsyncSessionLocal() as db:
        stock_codes = set(r[0] for r in (await db.execute(select(StockList.code))).all())
    today = date.today()
    for i in range(90, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            all_rows = await fetch_lending(d)
            rows = [r for r in all_rows if r["code"] in stock_codes]
            if rows:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        pg_insert(SecuritiesLending).values(rows).on_conflict_do_nothing(
                            index_elements=["code", "trade_date"]
                        )
                    )
                    await db.commit()
            logger.info(f"Lending backfill {d}: {len(rows)} rows")
        except Exception as e:
            logger.warning(f"Lending backfill {d} failed: {e}")
        await asyncio.sleep(0.3)
    logger.info("Lending backfill complete.")


async def backfill_shareholding_all():
    """背景慢速補抓所有電子股大戶持股（Shareholding 表為空時執行，1.5s/檔避免封鎖）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.fetcher.finmind import fetch_shareholding
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(Shareholding))).first()
    if count is not None:
        logger.info("Shareholding data exists, skipping backfill.")
        return
    async with AsyncSessionLocal() as db:
        codes = [r[0] for r in (await db.execute(select(StockList.code))).all()]
    logger.info(f"Starting shareholding backfill for {len(codes)} stocks...")
    total = 0
    for i, code in enumerate(codes):
        try:
            rows = await fetch_shareholding(code, weeks=8)
            if rows:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        pg_insert(Shareholding).values(rows).on_conflict_do_nothing(
                            index_elements=["code", "report_date"]
                        )
                    )
                    await db.commit()
                total += len(rows)
        except Exception as e:
            logger.warning(f"Shareholding backfill {code} failed: {e}")
        if (i + 1) % 50 == 0:
            logger.info(f"Shareholding backfill progress: {i+1}/{len(codes)}, stored {total} rows")
        await asyncio.sleep(1.5)
    logger.info(f"Shareholding backfill complete: {total} rows for {len(codes)} stocks.")


async def refresh_stock_list():
    """更新電子股清單（含股本）"""
    rows = await fetch_electronic_stocks()
    if not rows:
        return
    from app.services.fetcher.finmind import fetch_stock_capital
    from app.db.models import StockList
    from datetime import datetime
    async with AsyncSessionLocal() as db:
        for r in rows:
            capital = await fetch_stock_capital(r["code"])
            existing = (await db.execute(
                select(StockList).where(StockList.code == r["code"])
            )).scalar_one_or_none()
            if existing:
                existing.name = r["name"]
                existing.tags = r["tags"]
                existing.capital = capital
                existing.updated_at = datetime.utcnow()
            else:
                db.add(StockList(**r, capital=capital))
        await db.commit()
    logger.info(f"Stock list updated: {len(rows)} stocks")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    scheduler.add_job(job1_institutional_price, "cron", hour=16, minute=5)
    scheduler.add_job(job2_margin, "cron", hour=18, minute=30)
    scheduler.add_job(job3_shareholding, "cron", hour=20, minute=30)
    scheduler.add_job(job4_screener, "cron", hour=21, minute=0)
    return scheduler
