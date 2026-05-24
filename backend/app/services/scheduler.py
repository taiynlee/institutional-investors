import asyncio
import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_
from app.db.base import AsyncSessionLocal
from app.db.models import (
    FetchLog, DailyPrice, Institutional, MarginTrading,
    Shareholding, ScreeningResult, StockList, AIPick,
)
from app.services.fetcher.twse import fetch_institutional, fetch_daily_price, fetch_margin
from app.services.fetcher.tdcc import fetch_shareholding_bulk
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
    """20:45 — 融資 + 借券賣出餘額（TWT93U，TWSE 約 20:30 更新，含融資欄位2-7與借券欄位8-12）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    today = date.today()
    if await _already_fetched("job2", today):
        return
    try:
        async with AsyncSessionLocal() as db:
            stock_codes = set(r[0] for r in (await db.execute(select(StockList.code))).all())
        all_margin = await fetch_margin(today)
        margin_rows = [r for r in all_margin if r["code"] in stock_codes]
        async with AsyncSessionLocal() as db:
            if margin_rows:
                stmt = pg_insert(MarginTrading).values(margin_rows)
                await db.execute(stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"]))
            await db.commit()
        await _log_fetch("job2", today, "success", len(margin_rows))
    except Exception as e:
        await _log_fetch("job2", today, "failed")
        logger.error(f"job2 failed: {e}")


async def job3_shareholding():
    """18:30（週日）— TDCC 集保戶股權分散表，一次下載全市場 level 15（千張以上）"""
    today = date.today()
    if today.weekday() != 6:
        return
    if await _already_fetched("job3", today):
        return
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        async with AsyncSessionLocal() as db:
            stock_codes = {r[0] for r in (await db.execute(select(StockList.code))).all()}
        rows = await fetch_shareholding_bulk()
        rows = [r for r in rows if r["code"] in stock_codes]
        if rows:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    pg_insert(Shareholding).values(rows).on_conflict_do_nothing(
                        index_elements=["code", "report_date"]
                    )
                )
                await db.commit()
        await _log_fetch("job3", today, "success", len(rows))
        logger.info(f"job3 shareholding: {len(rows)} rows inserted")
    except Exception as e:
        await _log_fetch("job3", today, "failed")
        logger.error(f"job3 failed: {e}")


async def job4_screener():
    """21:00 — 執行篩選，更新 screening_result"""
    today = date.today()
    if await _already_fetched("job4", today):
        return
    async with AsyncSessionLocal() as db:
        inst_today = (await db.execute(
            select(Institutional.trade_date).where(Institutional.trade_date == today).limit(1)
        )).scalar_one_or_none()
    if inst_today is None:
        logger.warning("job4 skipped: no institutional data for today in DB (job1 may have run before T86 published)")
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
            # 資加、戶加需在 calc_score 前算，holders_1000_chg 要進 chip dict
            inst_map = await _get_inst_map(stock.code)
            dip_bonus = calc_dip_buy_bonus(closes, price_dates, inst_map)
            holders_bonus = await _get_holders_bonus(stock.code)
            chip["holders_1000_chg"] = holders_bonus
            base_score = calc_score(entry, chip, market_bb_drop, vol_ratio)
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
        if results:
            asyncio.create_task(_run_ai_pick(today, results))
    except Exception as e:
        await _log_fetch("job4", today, "failed")
        logger.error(f"job4 failed: {e}")


def _fmt_lots(n: float) -> str:
    sign = "+" if n > 0 else ""
    if abs(n) >= 1000:
        return f"{sign}{n/1000:.0f}K張"
    return f"{sign}{n:.0f}張"


def _stock_analysis(r) -> str:
    """產生與前端 tooltip 一致的完整解讀文字，供 AI 精選使用。"""
    lines = [f"【{r.code} {r.name}】"]

    tags = (r.tags or "").split()
    if "A" in tags or "A+B" in tags:
        lines.append("策略A：今天放量創近30日新高，法人當天同步買超≥1%股本。主力帶動突破，非散戶追漲。")
    if "B" in tags or "A+B" in tags:
        lines.append(f"策略B：50日內曾創高，今日BB={r.bb_position:.1f}（≤5），法人6日+12日均買超≥1%。主力推過、拉回月線附近未出場。")

    bb = r.bb_position or 0
    bb_desc = (
        "月線以下，已超賣" if bb <= 0 else
        "月線附近，充分回測" if bb <= 3 else
        "月線上方一點點，策略B切入點" if bb <= 5 else
        "中段整理區" if bb <= 8 else
        "靠近上軌，偏強勢" if bb <= 10 else "突破上軌，極強勢"
    )
    lines.append(f"BB={bb:.1f}：{bb_desc}")

    foreign = r.foreign_6d_net or 0
    trust = r.trust_6d_net or 0
    chip6d = r.chip_ratio_6d or 0
    chip_ok = chip6d >= 1
    lines.append(
        f"chip6d={chip6d:.2f}%：（外資{_fmt_lots(foreign)} + 投信{_fmt_lots(trust)}）÷ 股本 × 100% = {chip6d:.2f}%，"
        + ("超過入場門檻（≥1%），主力持續在場" if chip_ok else "未達入場門檻（≥1%），籌碼集中度不足")
    )

    conds = []
    if not r.is_squeeze:
        conds.append("BB尚未壓縮（型態未蓄積）")
    vol = r.vol_ratio or 0
    if vol > 0.5:
        conds.append(f"量縮不足（vol_ratio={vol:.2f}，拉回量仍偏大）")
    margin_chg = r.margin_5d_chg or 0
    if margin_chg > 0:
        conds.append(f"融資5日增加（+{margin_chg*100:.1f}%，散戶追進）")
    lending_chg = r.lending_5d_chg or 0
    if lending_chg > 0:
        conds.append(f"借券5日增加（+{lending_chg*100:.1f}%，空方增加）")
    if conds:
        lines.append("技術條件不足：" + "；".join(conds))
    else:
        lines.append("技術條件：BB壓縮、量縮、融資借券均健康")

    dip = r.dip_bonus or 0
    if dip > 0:
        full = dip >= 5
        lines.append(
            f"下跌日買超：最近{dip:.0f}次股價下跌日法人逆勢買超{'，一次不漏（滿分）' if full else ''}，主力洗盤跡象{'強烈' if full else '明顯'}。"
        )
    else:
        lines.append("下跌日買超：無特別洗盤訊號")

    holders = r.holders_bonus or 0
    if holders != 0:
        dir_str = f"增加{holders}%" if holders > 0 else f"減少{abs(holders)}%"
        lines.append(
            f"千張大戶：本週{'加碼，籌碼向上集中，偏多' if holders > 0 else '減倉，籌碼分散，偏空'}（{dir_str}）"
        )

    if dip >= 4 and not conds:
        lines.append("綜合：籌碼沉澱訊號強、技術條件健康，值得重點關注。")
    elif dip >= 4:
        lines.append("綜合：籌碼沉澱訊號強，但技術條件尚不完整，需等待型態確認。")
    elif not conds:
        lines.append("綜合：技術條件到位，籌碼訊號待觀察。")
    else:
        lines.append("綜合：技術與籌碼條件均待改善，持續觀察。")

    return "\n".join(lines)


async def _run_ai_pick(calc_date: date, results: list) -> None:
    """job4 完成後，呼叫 LINE bot claude 精選一檔，存入 ai_pick。"""
    import json, urllib.request
    from app.config import settings
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    header = [
        "你是台股選股助手。以下是今日通過量化篩選的電子股，每檔附完整指標解讀。",
        "請綜合所有資訊，精選「最值得關注的一檔」。",
        "只回傳以下格式，不要其他文字：代號|股名|理由（30字以內）",
        "",
        "---",
    ]
    stock_blocks = [_stock_analysis(r) for r in results]
    lines = header + stock_blocks + ["---"]
    prompt = "\n".join(lines)

    try:
        payload = json.dumps({"prompt": prompt}).encode("utf-8")
        req = urllib.request.Request(
            f"{settings.line_bot_url}/internal/ask",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        reply = data.get("reply", "").strip()
        parts = reply.split("|")
        if len(parts) < 3:
            logger.warning(f"AI pick parse fail: {reply!r}")
            return
        code, name, reason = parts[0].strip(), parts[1].strip(), "|".join(parts[2:]).strip()
        async with AsyncSessionLocal() as db:
            stmt = pg_insert(AIPick).values(
                calc_date=calc_date, code=code, name=name, reason=reason,
                created_at=date.today(),
            ).on_conflict_do_update(
                index_elements=["calc_date"],
                set_={"code": code, "name": name, "reason": reason},
            )
            await db.execute(stmt)
            await db.commit()
        logger.info(f"AI pick {calc_date}: {code} {name} — {reason}")
    except Exception as e:
        logger.error(f"AI pick failed: {e}")


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
    """千張大戶本週 vs 上週人數增減（人頭數差值，可負）"""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Shareholding)
            .where(Shareholding.code == code)
            .order_by(Shareholding.report_date.desc())
            .limit(2)
        )).scalars().all()
    if len(rows) < 2:
        return 0.0
    return float(rows[0].holders_1000_lot - rows[1].holders_1000_lot)


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
    chip = calc_chip_ratios(list(inst), capital_lots)

    margin_chg = 0.0
    lending_chg = 0.0
    if len(margin) >= 2:
        old_m = margin[0].margin_balance
        new_m = margin[-1].margin_balance
        margin_chg = (new_m - old_m) / old_m if old_m > 0 else 0.0
        old_l = margin[0].short_balance
        new_l = margin[-1].short_balance
        lending_chg = (new_l - old_l) / old_l if old_l > 0 else 0.0

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
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            async with AsyncSessionLocal() as db:
                if rows_i:
                    await db.execute(pg_insert(Institutional).values(rows_i).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                if price_rows:
                    await db.execute(pg_insert(DailyPrice).values(price_rows).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                if margin_rows:
                    await db.execute(pg_insert(MarginTrading).values(margin_rows).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                await db.commit()
        except Exception as e:
            logger.warning(f"Backfill {d} failed: {e}")
        await asyncio.sleep(1)
    logger.info("Backfill complete.")




async def backfill_shareholding_all():
    """啟動時補填大戶持股（表為空時）— 從 TDCC 下載當週全市場資料"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(Shareholding))).first()
    if count is not None:
        logger.info("Shareholding data exists, skipping backfill.")
        return
    async with AsyncSessionLocal() as db:
        stock_codes = {r[0] for r in (await db.execute(select(StockList.code))).all()}
    logger.info(f"Starting shareholding backfill from TDCC (bulk download)...")
    try:
        rows = await fetch_shareholding_bulk()
        rows = [r for r in rows if r["code"] in stock_codes]
        if rows:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    pg_insert(Shareholding).values(rows).on_conflict_do_nothing(
                        index_elements=["code", "report_date"]
                    )
                )
                await db.commit()
        logger.info(f"Shareholding backfill complete: {len(rows)} rows inserted.")
    except Exception as e:
        logger.error(f"Shareholding backfill failed: {e}")


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
    scheduler.add_job(job1_institutional_price, "cron", hour=18, minute=0)
    scheduler.add_job(job2_margin, "cron", hour=20, minute=45)
    scheduler.add_job(job3_shareholding, "cron", hour=18, minute=30)
    scheduler.add_job(job4_screener, "cron", hour=21, minute=0)
    return scheduler
