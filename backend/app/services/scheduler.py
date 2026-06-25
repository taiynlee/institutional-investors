import asyncio
import logging
import numpy as np
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_, func
from app.db.base import AsyncSessionLocal
from app.db.models import (
    FetchLog, DailyPrice, Institutional, MarginTrading,
    Shareholding, ScreeningResult, StockList, AIPick, WatchlistA,
)
from app.services.fetcher.twse import fetch_institutional, fetch_daily_price, fetch_margin, fetch_tpex_margin
from app.services.fetcher.tdcc import fetch_shareholding_bulk
from app.services.fetcher.market import fetch_twii_bb_stats
from app.services.fetcher.stock_list import fetch_electronic_stocks
from app.services.screener import (
    check_entry_criteria, calc_vol_ratio, calc_chip_ratios,
    calc_score, calc_dip_buy_bonus, is_early_breakout, check_cond3_breakout,
    calc_score_a, calc_upper_slope, calc_ma20_slope,
    calc_close_position, _consecutive_days_above_ma5,
)

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


async def _ever_succeeded(job_name: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(FetchLog).where(
                FetchLog.job_name == job_name,
                FetchLog.status == "success",
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
    """18:00（週一～五）— 三大法人 + 日成交（只處理股票池）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.db.models import StockPool
    today = date.today()
    if today.weekday() in (5, 6):
        return
    if await _already_fetched("job1", today):
        return
    try:
        async with AsyncSessionLocal() as db:
            pool_codes = {r.code for r in (await db.execute(select(StockPool))).scalars().all()}

        target_codes = pool_codes
        pool_size = len(target_codes)
        inst_min = max(1, int(pool_size * 0.5))

        all_inst = await fetch_institutional(today)
        rows = [r for r in all_inst if r["code"] in target_codes]

        logger.info(f"job1 completeness: inst={len(rows)}/{pool_size} (min={inst_min})")
        if len(rows) < inst_min:
            await _log_fetch("job1", today, "failed", len(rows))
            logger.error(f"job1 incomplete: only {len(rows)}/{pool_size} pool stocks fetched")
            return

        price_rows = await fetch_daily_price(today, codes=target_codes)
        price_hit = len(price_rows)
        logger.info(f"job1 price completeness: {price_hit}/{pool_size}")
        if price_hit < inst_min:
            await _log_fetch("job1", today, "failed", price_hit)
            logger.error(f"job1 price incomplete: {price_hit}/{pool_size}")
            return

        async with AsyncSessionLocal() as db:
            if rows:
                stmt = pg_insert(Institutional).values(rows)
                await db.execute(stmt.on_conflict_do_nothing(index_elements=["code", "trade_date"]))
            if price_rows:
                stmt = pg_insert(DailyPrice).values(price_rows)
                await db.execute(stmt.on_conflict_do_update(
                    index_elements=["code", "trade_date"],
                    set_={"open": stmt.excluded.open, "high": stmt.excluded.high,
                          "low": stmt.excluded.low, "close": stmt.excluded.close,
                          "volume": stmt.excluded.volume},
                ))
            await db.commit()
        await _log_fetch("job1", today, "success", len(rows) + len(price_rows))
    except Exception as e:
        await _log_fetch("job1", today, "failed")
        logger.error(f"job1 failed: {e}")


async def job2_margin():
    """20:45（週一～五）— 融資融券餘額"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    today = date.today()
    if today.weekday() in (5, 6):
        return
    if await _already_fetched("job2", today):
        return
    try:
        async with AsyncSessionLocal() as db:
            from app.db.models import StockPool
            pool_codes = set(r[0] for r in (await db.execute(select(StockPool.code))).all())
            sl_codes = set(r[0] for r in (await db.execute(select(StockList.code))).all())
            stock_codes = pool_codes | sl_codes
        twse_rows = await fetch_margin(today)
        tpex_rows = await fetch_tpex_margin(today)
        margin_rows = [r for r in twse_rows + tpex_rows if r["code"] in stock_codes]
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
    """18:30（週六/週日）— TDCC 集保戶股權分散表（只處理股票池）"""
    today = date.today()
    if today.weekday() not in (5, 6):
        return
    if today.weekday() == 6:
        saturday = today - timedelta(days=1)
        if await _already_fetched("job3", saturday):
            return
    if await _already_fetched("job3", today):
        return
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from app.db.models import StockPool
        async with AsyncSessionLocal() as db:
            pool_codes = {r.code for r in (await db.execute(select(StockPool))).scalars().all()}
        target_codes = pool_codes
        pool_size = len(target_codes)
        sh_min = max(1, int(pool_size * 0.5))

        rows = await fetch_shareholding_bulk()
        rows = [r for r in rows if r["code"] in target_codes]

        logger.info(f"job3 completeness: {len(rows)}/{pool_size} pool stocks (min={sh_min})")
        if len(rows) < sh_min:
            await _log_fetch("job3", today, "failed", len(rows))
            logger.error(f"job3 incomplete: {len(rows)}/{pool_size}")
            return

        if rows:
            async with AsyncSessionLocal() as db:
                stmt = pg_insert(Shareholding).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code", "report_date"],
                    set_={
                        "holders_1000_lot": stmt.excluded.holders_1000_lot,
                        "pct_1000_lot":     stmt.excluded.pct_1000_lot,
                        "pct_400_lot":      stmt.excluded.pct_400_lot,
                    }
                )
                await db.execute(stmt)
                await db.commit()
        await _log_fetch("job3", today, "success", len(rows))
        logger.info(f"job3 shareholding: {len(rows)} rows inserted")
    except Exception as e:
        await _log_fetch("job3", today, "failed")
        logger.error(f"job3 failed: {e}")


async def job4_screener(force: bool = False, target_date: date | None = None):
    """21:00（週一～五）/ 22:30（週日）— 執行篩選，更新 screening_result
    target_date: 若指定，強制用該日資料補算（不受 weekday/already_fetched 限制）
    """
    today = date.today()
    if target_date is None:
        if not force and today.weekday() == 5:
            return
        async with AsyncSessionLocal() as db:
            inst_today = (await db.execute(
                select(Institutional.trade_date)
                .where(Institutional.trade_date <= today)
                .order_by(Institutional.trade_date.desc())
                .limit(1)
            )).scalar_one_or_none()
        if inst_today is None:
            logger.warning("job4 skipped: no institutional data in DB")
            return
        target_date = inst_today
        if not force and await _already_fetched("job4", target_date):
            return
    else:
        # 補算模式：用指定日期的最近法人資料
        async with AsyncSessionLocal() as db:
            inst_on_or_before = (await db.execute(
                select(Institutional.trade_date)
                .where(Institutional.trade_date <= target_date)
                .order_by(Institutional.trade_date.desc())
                .limit(1)
            )).scalar_one_or_none()
        if inst_on_or_before is None:
            logger.warning(f"job4 backfill {target_date}: no institutional data ≤ {target_date}")
            return
        target_date = inst_on_or_before
    try:
        market_bb_peak, market_bb_now = fetch_twii_bb_stats()
        market_bb_drop = max(0, market_bb_peak - market_bb_now)
        async with AsyncSessionLocal() as db:
            stocks = (await db.execute(select(StockList))).scalars().all()
        results = []
        for stock in stocks:
            opens, highs, lows, closes, volumes, price_dates = await _get_price_series(stock.code, price_date=target_date)
            if len(closes) < 65:
                continue
            entry = check_entry_criteria(opens, highs, lows, closes, volumes)
            if not entry["passes"]:
                continue
            chip = await _get_chip_summary(stock.code, target_date, stock.capital)
            holders_bonus = await _get_holders_bonus(stock.code)
            a_chip_ok = (
                (chip.get("chip_ratio_1d", 0) > 1.0 and chip.get("chip_ratio_12d", 0) > 0)
                or
                (chip.get("chip_ratio_1d", 0) > 0 and chip.get("chip_ratio_12d", 0) > 1.0)
            )
            b_chip_ok = (
                chip.get("chip_ratio_6d", 0) >= 1.0
                and chip.get("chip_ratio_12d", 0) >= 1.0
                and holders_bonus["w1"] >= -0.5
            )
            a_passes = entry["passes_A"] and a_chip_ok
            b_passes = entry["passes_B_price"] and b_chip_ok
            if not (a_passes or b_passes):
                continue
            if a_passes and b_passes:
                strategy_tag = "A+B"
            elif a_passes:
                strategy_tag = "A"
            else:
                strategy_tag = "B"
            tags = strategy_tag
            vol_ratio = calc_vol_ratio(volumes)
            inst_map = await _get_inst_map(stock.code, end_date=target_date)
            dip_bonus = calc_dip_buy_bonus(closes, price_dates, inst_map)
            chip["holders_1000_chg"] = holders_bonus["w1"]
            chip["holders_w1"] = holders_bonus["w1"]
            chip["holders_w2"] = holders_bonus["w2"]
            chip["holders_w3"] = holders_bonus["w3"]
            base_score = calc_score(entry, chip, market_bb_drop, vol_ratio)
            chip_fields = {k: chip[k] for k in (
                "foreign_6d_net", "trust_6d_net",
                "chip_ratio_1d", "chip_ratio_6d", "chip_ratio_12d", "chip_ratio_20d",
                "margin_5d_chg", "lending_5d_chg", "holders_1000_chg",
            ) if k in chip}
            _ma5d  = _consecutive_days_above_ma5(closes)
            _usl   = calc_upper_slope(closes)
            _m20sl = calc_ma20_slope(closes)
            _cpct  = calc_close_position(closes[-1], highs[-1], lows[-1])
            _chg_pct = (closes[-1] / closes[-2] - 1) * 100 if len(closes) >= 2 else 0.0
            _sh_chg = await _get_shareholder_change(stock.code) if a_passes else None
            _vol20_avg = float(np.mean(volumes[-21:-1])) if len(volumes) >= 21 else 0.0
            _vol_ratio_today = float(volumes[-1] / _vol20_avg) if _vol20_avg > 0 else 0.0
            _score_a = calc_score_a(
                bb_position=entry["bb_position"],
                close_position=_cpct,
                change_pct=_chg_pct,
                upper_slope=_usl,
                ma20_slope=_m20sl,
                chip1d=chip.get("chip_ratio_1d", 0),
                chip12d=chip.get("chip_ratio_12d", 0),
                shareholder_change=_sh_chg,
                vol_ratio=_vol_ratio_today,
            ) if a_passes else 0.0
            results.append(ScreeningResult(
                code=stock.code,
                name=stock.name,
                calc_date=target_date,
                tags=tags,
                bb_position=entry["bb_position"],
                bb_peak=entry["bb_peak"],
                peak_date=None,
                peak_days_ago=entry["peak_days_ago"],
                is_squeeze=entry["is_squeeze"],
                vol_ratio=_vol_ratio_today,
                score_b=base_score,
                dip_bonus=dip_bonus,
                holders_bonus=holders_bonus["w1"],
                holders_w2=holders_bonus["w2"],
                holders_w3=holders_bonus["w3"],
                passes=True,
                ma5_days=_ma5d,
                upper_slope=round(_usl, 3),
                ma20_slope=round(_m20sl, 3),
                close_position=round(_cpct, 1),
                change_pct=round(_chg_pct, 2),
                score_a=_score_a,
                **chip_fields,
            ))
        from sqlalchemy import delete
        async with AsyncSessionLocal() as db:
            await db.execute(delete(ScreeningResult).where(ScreeningResult.calc_date == target_date))
            for r in results:
                db.add(r)
            await db.commit()
        await _log_fetch("job4", target_date, "success", len(results))
        logger.info(f"Screener found {len(results)} stocks")
        if results:
            asyncio.create_task(_run_ai_pick(target_date, results))

        # 追蹤清單：加入符合條件股票
        selected_codes = {r.code for r in results}
        async with AsyncSessionLocal() as db:
            ever_selected = set(r[0] for r in (await db.execute(
                select(ScreeningResult.code).distinct()
                .where(
                    ScreeningResult.tags.contains("A"),
                    ScreeningResult.calc_date < target_date,
                )
            )).all())
            already_tracking = set(r[0] for r in (await db.execute(
                select(WatchlistA.code)
                .where(WatchlistA.status.in_(["tracking", "triggered", "entered"]))
            )).all())
        for stock in stocks:
            if stock.code in selected_codes:
                continue
            if stock.code not in ever_selected:
                continue
            if stock.code in already_tracking:
                continue
            opens, highs, lows, closes, volumes, _ = await _get_price_series(stock.code, price_date=target_date)
            if len(closes) < 65:
                continue
            entry = check_entry_criteria(opens, highs, lows, closes, volumes)
            if not entry["trend_ok"]:
                continue
            chip = await _get_chip_summary(stock.code, target_date, stock.capital)
            chip1d, chip12d = chip.get("chip_ratio_1d", 0), chip.get("chip_ratio_12d", 0)
            if not ((chip1d > 1.0 and chip12d > 0) or (chip1d > 0 and chip12d > 1.0)):
                continue
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            async with AsyncSessionLocal() as db:
                last_score = (await db.execute(
                    select(ScreeningResult.score_a)
                    .where(ScreeningResult.code == stock.code, ScreeningResult.tags.contains("A"))
                    .order_by(ScreeningResult.calc_date.desc())
                    .limit(1)
                )).scalar() or 0.0
                await db.execute(
                    pg_insert(WatchlistA).values(
                        code=stock.code, name=stock.name,
                        added_date=target_date,
                        added_close=closes[-1],
                        added_bb_position=entry["bb_position"],
                        added_score_a=last_score,
                        status="tracking",
                    ).on_conflict_do_nothing(index_elements=["code", "added_date"])
                )
                await db.commit()

        # 追蹤清單：超過10個交易日未觸發 → 自動刪除；否則檢查 BB ≤ 5
        async with AsyncSessionLocal() as db:
            tracking = (await db.execute(
                select(WatchlistA).where(WatchlistA.status == "tracking")
            )).scalars().all()
        for item in tracking:
            try:
                async with AsyncSessionLocal() as db:
                    trading_days = (await db.execute(
                        select(func.count()).where(
                            DailyPrice.code == item.code,
                            DailyPrice.trade_date > item.added_date,
                            DailyPrice.trade_date <= target_date,
                        )
                    )).scalar() or 0
                if trading_days >= 10:
                    async with AsyncSessionLocal() as db:
                        item_db = (await db.execute(
                            select(WatchlistA).where(WatchlistA.id == item.id)
                        )).scalar_one_or_none()
                        if item_db:
                            await db.delete(item_db)
                            await db.commit()
                    logger.info(f"WatchlistA auto-expired {item.code} after {trading_days} trading days")
                    continue
                opens, highs, lows, closes, volumes, _ = await _get_price_series(item.code, price_date=today)
                if not closes:
                    continue
                from app.services.screener import calc_bb_position
                bb_now = calc_bb_position(closes)
                if bb_now <= 5:
                    async with AsyncSessionLocal() as db:
                        item_db = (await db.execute(
                            select(WatchlistA).where(WatchlistA.id == item.id)
                        )).scalar_one()
                        item_db.status = "triggered"
                        item_db.triggered_date = target_date
                        item_db.triggered_close = closes[-1]
                        item_db.triggered_bb_position = round(bb_now, 2)
                        await db.commit()
            except Exception as e:
                logger.error(f"WatchlistA trigger check failed for {item.code}: {e}", exc_info=True)

        # 已進場股票：停損提醒
        async with AsyncSessionLocal() as db:
            entered = (await db.execute(
                select(WatchlistA).where(WatchlistA.status == "entered")
            )).scalars().all()
        for item in entered:
            try:
                if not item.triggered_close or item.triggered_close <= 0:
                    continue
                async with AsyncSessionLocal() as db:
                    price = (await db.execute(
                        select(DailyPrice.close)
                        .where(DailyPrice.code == item.code, DailyPrice.trade_date == target_date)
                    )).scalar_one_or_none()
                if price is None:
                    continue
                drop_pct = (price - item.triggered_close) / item.triggered_close * 100
                if drop_pct <= -7.0:
                    asyncio.create_task(_notify_stop_loss(
                        item.code, item.name, price, drop_pct,
                        item.triggered_close, item.triggered_date,
                    ))
            except Exception as e:
                logger.error(f"Stop-loss check failed for {item.code}: {e}", exc_info=True)

    except Exception as e:
        await _log_fetch("job4", target_date, "failed")
        logger.error(f"job4 failed: {e}")


def _fmt_lots(n: float) -> str:
    sign = "+" if n > 0 else ""
    if abs(n) >= 1000:
        return f"{sign}{n/1000:.0f}K張"
    return f"{sign}{n:.0f}張"


def _stock_analysis(r) -> str:
    lines = [f"【{r.code} {r.name}】"]
    tags = (r.tags or "").split()
    if "A" in tags or "A+B" in tags:
        lines.append("策略A：今天放量創近30日新高，法人當天同步買超≥1%股本。")
    if "B" in tags or "A+B" in tags:
        lines.append(f"策略B：50日內曾創高，今日BB={r.bb_position:.1f}（≤5），法人6日+12日均買超≥1%。")
    bb = r.bb_position or 0
    bb_desc = (
        "月線以下，已超賣" if bb <= 0 else
        "月線附近，充分回測" if bb <= 3 else
        "月線上方，策略B切入點" if bb <= 5 else
        "中段整理區" if bb <= 8 else
        "靠近上軌，偏強勢" if bb <= 10 else "突破上軌，極強勢"
    )
    lines.append(f"BB={bb:.1f}：{bb_desc}")
    foreign = r.foreign_6d_net or 0
    trust = r.trust_6d_net or 0
    chip6d = r.chip_ratio_6d or 0
    lines.append(
        f"chip6d={chip6d:.2f}%：（外資{_fmt_lots(foreign)} + 投信{_fmt_lots(trust)}）÷ 股本"
    )
    dip = r.dip_bonus or 0
    if dip > 0:
        lines.append(f"下跌日買超：最近{dip:.0f}次股價下跌日法人逆勢買超")
    holders = r.holders_bonus or 0
    if holders != 0:
        dir_str = f"增加{holders}%" if holders > 0 else f"減少{abs(holders)}%"
        lines.append(f"千張大戶：{'加碼' if holders > 0 else '減倉'}（{dir_str}）")
    return "\n".join(lines)


async def _run_ai_pick(calc_date: date, results: list) -> None:
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


async def _notify_watchlist_triggered(
    code: str, name: str, close: float, bb_now: float,
    added_date: date, added_close: float,
) -> None:
    import json, urllib.request
    from app.config import settings
    if not settings.line_channel_token or not settings.line_user_id:
        return

    async with AsyncSessionLocal() as db:
        a_dates = (await db.execute(
            select(ScreeningResult.calc_date)
            .where(ScreeningResult.code == code, ScreeningResult.tags.contains("A"),
                   ScreeningResult.calc_date < added_date)
            .order_by(ScreeningResult.calc_date.desc())
            .limit(20)
        )).scalars().all()
        screen_date = added_date
        if a_dates:
            screen_date = a_dates[0]
            for i in range(len(a_dates) - 1):
                if (a_dates[i] - a_dates[i + 1]).days > 7:
                    break
                screen_date = a_dates[i + 1]

        pre_dates = (await db.execute(
            select(Institutional.trade_date)
            .where(Institutional.code == code, Institutional.trade_date < screen_date)
            .order_by(Institutional.trade_date.desc())
            .limit(6)
        )).scalars().all()
        window_start = min(pre_dates) if pre_dates else screen_date

        inst_rows = (await db.execute(
            select(Institutional.trade_date, Institutional.three_major_net)
            .where(Institutional.code == code, Institutional.trade_date >= window_start)
            .order_by(Institutional.trade_date)
        )).all()

    post_cum = post_peak = win_cum = win_peak = 0
    for row_date, net in inst_rows:
        net = int(net or 0)
        win_cum += net
        if win_cum > win_peak:
            win_peak = win_cum
        if row_date >= added_date:
            post_cum += net
            if post_cum > post_peak:
                post_peak = post_cum

    post_selloff = max(0.0, (post_peak - post_cum) / post_peak * 100) if post_peak > 0 else None
    win_selloff  = max(0.0, (win_peak  - win_cum)  / win_peak  * 100) if win_peak  > 0 else None

    def _fmt(v: int) -> str:
        sign = '+' if v >= 0 else ''
        return f'{sign}{v:,} 張'

    def _pct(v) -> str:
        return f'{v:.1f}%' if v is not None else '—'

    chg_pct = (close - added_close) / added_close * 100 if added_close > 0 else 0
    triggered_date = date.today()

    msg = (
        f"📌 策略A到位\n"
        f"{code} {name}\n"
        f"{added_date.strftime('%m-%d')} 加入：{added_close}\n"
        f"{triggered_date.strftime('%m-%d')} 收盤：{close}（{chg_pct:+.1f}%）\n"
        f"拉回位階：{bb_now:.1f}\n"
        f"法人累積：{_fmt(post_cum)}\n"
        f"加入回吐率：{_pct(post_selloff)}\n"
        f"全窗回吐率：{_pct(win_selloff)}"
    )
    try:
        payload = json.dumps({
            "to": settings.line_user_id,
            "messages": [{"type": "text", "text": msg}],
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push",
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.line_channel_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.warning(f"WatchlistA LINE notify failed: {e}")


async def _notify_stop_loss(
    code: str, name: str, close: float, drop_pct: float,
    triggered_close: float, triggered_date,
) -> None:
    import json, urllib.request
    from app.config import settings
    if not settings.line_channel_token or not settings.line_user_id:
        return
    date_str = triggered_date.strftime("%m-%d") if triggered_date else "—"
    msg = (
        f"⚠️ 停損提醒\n"
        f"{code} {name}\n"
        f"{date_str} 進場基準：{triggered_close}\n"
        f"今日收盤：{close}（{drop_pct:+.1f}%）\n"
        f"已跌破 -7% 門檻，請考慮出場"
    )
    try:
        payload = json.dumps({
            "to": settings.line_user_id,
            "messages": [{"type": "text", "text": msg}],
        }, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            "https://api.line.me/v2/bot/message/push",
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.line_channel_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.warning(f"Stop-loss LINE notify failed: {e}")


async def _get_price_series(
    code: str,
    days: int = 200,
    price_date: date | None = None,
) -> tuple[list, list, list, list, list, list]:
    end_date = price_date if price_date is not None else date.today()
    cutoff = end_date - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DailyPrice)
            .where(and_(
                DailyPrice.code == code,
                DailyPrice.trade_date >= cutoff,
                DailyPrice.trade_date <= end_date,
            ))
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


async def _get_holders_bonus(code: str) -> dict:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Shareholding)
            .where(Shareholding.code == code)
            .order_by(Shareholding.report_date.desc())
            .limit(4)
        )).scalars().all()
    vals = [float(r.pct_1000_lot) for r in rows]
    def diff(i: int) -> float:
        return round(vals[0] - vals[i], 2) if len(vals) > i else 0.0
    return {"w1": diff(1), "w2": diff(2), "w3": diff(3)}


async def _get_inst_map(code: str, days: int = 60, end_date: date | None = None) -> dict:
    ed = end_date if end_date is not None else date.today()
    cutoff = ed - timedelta(days=days)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Institutional)
            .where(and_(
                Institutional.code == code,
                Institutional.trade_date >= cutoff,
                Institutional.trade_date <= ed,
            ))
            .order_by(Institutional.trade_date)
        )).scalars().all()
    return {r.trade_date: r.foreign_net + r.trust_net for r in rows}


async def _get_chip_summary(code: str, today: date, capital_lots: float) -> dict:
    cutoff_12d = today - timedelta(days=30)
    cutoff_5d = today - timedelta(days=8)
    async with AsyncSessionLocal() as db:
        inst = (await db.execute(
            select(Institutional)
            .where(and_(
                Institutional.code == code,
                Institutional.trade_date >= cutoff_12d,
                Institutional.trade_date <= today,
            ))
            .order_by(Institutional.trade_date)
        )).scalars().all()
        margin = (await db.execute(
            select(MarginTrading)
            .where(and_(
                MarginTrading.code == code,
                MarginTrading.trade_date >= cutoff_5d,
                MarginTrading.trade_date <= today,
            ))
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


async def _get_shareholder_change(code: str, max_weeks: int = 6) -> float | None:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Shareholding.report_date, Shareholding.pct_1000_lot)
            .where(Shareholding.code == code)
            .order_by(Shareholding.report_date.desc())
            .limit(max_weeks + 1)
        )).all()
    if len(rows) < 2:
        return None
    latest = rows[0].pct_1000_lot
    oldest = rows[min(len(rows) - 1, max_weeks)].pct_1000_lot
    return round(latest - oldest, 4)


async def job5_monthly_revenue(force: bool = False):
    """每月10~25日每天 12:00 — 從 TWSE/TPEx 下載上月月營收"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.fetcher.mops import fetch_monthly_revenue, latest_available_month
    from app.db.models import MonthlyRevenue

    today = date.today()
    if not force and (today.day < 10 or today.day > 25):
        return
    if not force and today.weekday() in (5, 6):
        return

    MIN_ROWS_TWSE = 900
    MIN_ROWS_TPEX = 700
    MAX_RETRIES = 3

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            twse_rows, tpex_rows = await fetch_monthly_revenue()
            if len(twse_rows) < MIN_ROWS_TWSE:
                raise ValueError(f"TWSE rows too few: {len(twse_rows)} < {MIN_ROWS_TWSE}")
            if len(tpex_rows) < MIN_ROWS_TPEX:
                raise ValueError(f"TPEx rows too few: {len(tpex_rows)} < {MIN_ROWS_TPEX}")

            all_rows = twse_rows + tpex_rows
            data_year = twse_rows[0]["year"]
            data_month = twse_rows[0]["month"]
            job_key = f"job5_{data_year}{data_month:02d}"

            if await _ever_succeeded(job_key):
                logger.info(f"job5 already succeeded for {data_year}-{data_month:02d}, skipping")
                return

            async with AsyncSessionLocal() as db:
                stmt = pg_insert(MonthlyRevenue).values(all_rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code", "year", "month"],
                    set_={"revenue": stmt.excluded.revenue, "updated_at": stmt.excluded.updated_at},
                )
                await db.execute(stmt)
                await db.commit()
            await _log_fetch(job_key, today, "success", len(all_rows))
            logger.info(f"job5 monthly revenue {data_year}-{data_month:02d}: total={len(all_rows)}")
            return
        except Exception as e:
            logger.warning(f"job5 attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(60)

    year, month = latest_available_month()
    await _log_fetch(f"job5_{year}{month:02d}", today, "failed")
    logger.error(f"job5 failed after {MAX_RETRIES} attempts")


async def backfill_revenue_history(start_date: str = "2023-01-01"):
    """一次性 — 從 FinMind 補抓池子股票的歷史月營收（用於 YoY 計算）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.fetcher.finmind import fetch_monthly_revenue_history
    from app.db.models import MonthlyRevenue, StockPool

    async with AsyncSessionLocal() as db:
        codes = [r[0] for r in (await db.execute(select(StockPool.code))).all()]

    logger.info(f"backfill_revenue: {len(codes)} pool stocks from {start_date}")
    success_count = 0
    failed: list[str] = []

    for code in codes:
        try:
            rows = await fetch_monthly_revenue_history(code, start_date)
            if rows:
                async with AsyncSessionLocal() as db:
                    stmt = pg_insert(MonthlyRevenue).values(rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code", "year", "month"],
                        set_={"revenue": stmt.excluded.revenue},
                    )
                    await db.execute(stmt)
                    await db.commit()
                success_count += 1
            else:
                failed.append(code)
        except Exception as e:
            logger.warning(f"backfill_revenue failed {code}: {e}")
            failed.append(code)
        await asyncio.sleep(0.5)

    logger.info(f"backfill_revenue done: {success_count}/{len(codes)}, failed={failed}")


async def job6_quarterly_eps(force: bool = False):
    """每季一次 — 從 FinMind 批次下載所有股票季報 EPS"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.fetcher.finmind import fetch_quarterly_eps
    from app.db.models import QuarterlyEps

    today = date.today()
    job_key = f"job6_q{(today.month-1)//3+1}_{today.year}"
    if not force and await _already_fetched(job_key, today):
        return

    async with AsyncSessionLocal() as db:
        from app.db.models import StockPool
        codes = [r[0] for r in (await db.execute(select(StockPool.code))).all()]

    logger.info(f"job6 starting quarterly EPS fetch for {len(codes)} stocks")
    RATE_LIMIT = 550
    SLEEP_SEC  = 3600 / RATE_LIMIT

    failed: list[str] = []
    success_count = 0

    async def _upsert(rows: list[dict]):
        if not rows:
            return
        async with AsyncSessionLocal() as db:
            stmt = pg_insert(QuarterlyEps).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code", "year", "quarter"],
                set_={
                    "eps": stmt.excluded.eps,
                    "revenue": stmt.excluded.revenue,
                    "op_income": stmt.excluded.op_income,
                    "net_income": stmt.excluded.net_income,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await db.execute(stmt)
            await db.commit()

    for code in codes:
        try:
            rows = await fetch_quarterly_eps(code)
            if not rows:
                failed.append(code)
            else:
                await _upsert(rows)
                success_count += 1
        except Exception as e:
            logger.warning(f"job6 fetch failed {code}: {e}")
            failed.append(code)
        await asyncio.sleep(SLEEP_SEC)

    if failed:
        retry_failed = []
        for code in failed:
            try:
                rows = await fetch_quarterly_eps(code)
                if not rows:
                    retry_failed.append(code)
                else:
                    await _upsert(rows)
                    success_count += 1
            except Exception as e:
                retry_failed.append(code)
            await asyncio.sleep(SLEEP_SEC)
        if retry_failed:
            logger.error(f"job6 still failed after retry: {retry_failed}")

    status = "success" if not failed else "failed"
    await _log_fetch(job_key, today, status, success_count)
    logger.info(f"job6 done: {success_count}/{len(codes)} success")


async def job7_ic_chain():
    """每半年（1/1、7/1）02:00 — 從 ic.tpex.org.tw 抓取電子科技產業鏈公司分類"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.fetcher.ic_chain import fetch_all_ic_chains
    from app.db.models import IcClassification

    today = date.today()
    half = 1 if today.month <= 6 else 2
    job_key = f"job7_{today.year}H{half}"
    if await _ever_succeeded(job_key):
        logger.info(f"job7 already succeeded for {job_key}, skipping")
        return

    try:
        rows = await fetch_all_ic_chains()
        if not rows:
            await _log_fetch(job_key, today, "failed")
            return

        async with AsyncSessionLocal() as db:
            stmt = pg_insert(IcClassification).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code", "ic_code"],
                set_={
                    "name":        stmt.excluded.name,
                    "ic_node":     stmt.excluded.ic_node,
                    "ic_position": stmt.excluded.ic_position,
                    "updated_at":  stmt.excluded.updated_at,
                },
            )
            await db.execute(stmt)
            await db.commit()

        await _log_fetch(job_key, today, "success", len(rows))
        logger.info(f"job7 ic_chain: {len(rows)} rows upserted")
    except Exception as e:
        await _log_fetch(job_key, today, "failed")
        logger.error(f"job7 ic_chain failed: {e}")


async def job8_daytrade_screener():
    """21:05（週一～五）— 觸發富邦當沖篩選，更新隔日 daytrade_list"""
    import httpx
    today = date.today()
    if today.weekday() in (5, 6):
        return
    if await _already_fetched("job8", today):
        return
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "http://host.docker.internal:8090/daytrade-list/sync",
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        await _log_fetch("job8", today, "success", data.get("count", 0))
        logger.info("job8 daytrade screener: %d stocks → %s", data.get("count", 0), data.get("date"))
    except Exception as e:
        await _log_fetch("job8", today, "failed")
        logger.error("job8 failed: %s", e)


async def startup_backfill():
    """啟動時：先補歷史缺口（最近 14 曆日），再補今天應跑未成功的 jobs。"""
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt

    # 先補歷史缺漏（非今天）
    await startup_gap_backfill(lookback_days=14)

    now = _dt.now(tz=ZoneInfo("Asia/Taipei"))
    today = now.date()
    wd = today.weekday()  # 0=Mon 6=Sun
    h, m = now.hour, now.minute

    def due(sched_h, sched_m):
        return h > sched_h or (h == sched_h and m >= sched_m)

    tasks = []
    if wd < 5 and due(18, 0) and not await _already_fetched("job1", today):
        tasks.append(("job1", job1_institutional_price()))
    if wd < 5 and due(20, 45) and not await _already_fetched("job2", today):
        tasks.append(("job2", job2_margin()))
    job4_due = (wd < 5 and due(21, 0)) or (wd == 6 and due(22, 30))
    if job4_due and not await _already_fetched("job4", today):
        tasks.append(("job4", job4_screener()))
    if wd < 5 and due(21, 5) and not await _already_fetched("job8", today):
        tasks.append(("job8", job8_daytrade_screener()))

    if tasks:
        names = [t[0] for t in tasks]
        logger.info("startup_backfill: 補跑 %s", names)
        await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
    else:
        logger.info("startup_backfill: 今天無需補跑")


async def job_watchdog():
    """每 30 分鐘檢查應跑但未成功的 jobs，自動補跑。"""
    from zoneinfo import ZoneInfo
    from datetime import datetime as _dt
    now = _dt.now(tz=ZoneInfo("Asia/Taipei"))
    today = now.date()
    wd = today.weekday()
    h, m = now.hour, now.minute

    def due(sched_h, sched_m):
        return h > sched_h or (h == sched_h and m >= sched_m)

    if wd < 5 and due(18, 0) and h < 21:
        if not await _already_fetched("job1", today):
            logger.info("watchdog: 補跑 job1")
            await job1_institutional_price()

    if wd < 5 and due(20, 45) and h < 23:
        if not await _already_fetched("job2", today):
            logger.info("watchdog: 補跑 job2")
            await job2_margin()

    job4_due = (wd < 5 and due(21, 0)) or (wd == 6 and due(22, 30))
    if job4_due and h < 23:
        if not await _already_fetched("job4", today):
            logger.info("watchdog: 補跑 job4")
            await job4_screener()

    if wd < 5 and due(21, 5) and h < 23:
        if not await _already_fetched("job8", today):
            logger.info("watchdog: 補跑 job8")
            await job8_daytrade_screener()


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei", misfire_grace_time=300)
    scheduler.add_job(job1_institutional_price, "cron", hour=18, minute=0)
    scheduler.add_job(job2_margin, "cron", hour=20, minute=45)
    scheduler.add_job(job3_shareholding, "cron", day_of_week="sat", hour=11, minute=30)
    scheduler.add_job(job3_shareholding, "cron", day_of_week="sun", hour=18, minute=30)
    scheduler.add_job(job4_screener, "cron", hour=21, minute=0)
    scheduler.add_job(job4_screener, "cron", day_of_week="sun", hour=22, minute=30)
    scheduler.add_job(job8_daytrade_screener, "cron", hour=21, minute=5)
    scheduler.add_job(job5_monthly_revenue, "cron", day="10-25", hour=12, minute=0)
    scheduler.add_job(job6_quarterly_eps, "cron", month="5", day=16, hour=9, minute=0)
    scheduler.add_job(job6_quarterly_eps, "cron", month="8", day=15, hour=9, minute=0)
    scheduler.add_job(job6_quarterly_eps, "cron", month="11", day=15, hour=9, minute=0)
    scheduler.add_job(job6_quarterly_eps, "cron", month="3", day=1, hour=9, minute=0)
    scheduler.add_job(job7_ic_chain, "cron", month="1,7", day=1, hour=2, minute=0)
    scheduler.add_job(job_watchdog, "interval", minutes=30)
    return scheduler


async def backfill_financials_for_codes(codes: list[str], start_date: str = "2023-01-01"):
    """補抓指定股票的月營收和季報EPS（FinMind）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.fetcher.finmind import fetch_monthly_revenue_history, fetch_quarterly_eps
    from app.db.models import MonthlyRevenue, QuarterlyEps

    SLEEP_SEC = 3600 / 550  # FinMind rate limit ≈ 6.5s

    logger.info(f"backfill_financials: starting for {len(codes)} stocks")

    for code in codes:
        try:
            rev_rows = await fetch_monthly_revenue_history(code, start_date)
            if rev_rows:
                async with AsyncSessionLocal() as db:
                    stmt = pg_insert(MonthlyRevenue).values(rev_rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code", "year", "month"],
                        set_={"revenue": stmt.excluded.revenue},
                    )
                    await db.execute(stmt)
                    await db.commit()
                logger.info(f"backfill_financials revenue {code}: {len(rev_rows)} rows")
        except Exception as e:
            logger.warning(f"backfill_financials revenue failed {code}: {e}")
        await asyncio.sleep(SLEEP_SEC)

        try:
            eps_rows = await fetch_quarterly_eps(code)
            if eps_rows:
                async with AsyncSessionLocal() as db:
                    stmt = pg_insert(QuarterlyEps).values(eps_rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code", "year", "quarter"],
                        set_={
                            "eps": stmt.excluded.eps,
                            "revenue": stmt.excluded.revenue,
                            "op_income": stmt.excluded.op_income,
                            "net_income": stmt.excluded.net_income,
                            "updated_at": stmt.excluded.updated_at,
                        },
                    )
                    await db.execute(stmt)
                    await db.commit()
                logger.info(f"backfill_financials eps {code}: {len(eps_rows)} rows")
        except Exception as e:
            logger.warning(f"backfill_financials eps failed {code}: {e}")
        await asyncio.sleep(SLEEP_SEC)

    logger.info(f"backfill_financials done for {len(codes)} stocks")


async def backfill_90_days():
    """首次啟動時，補抓 90 日歷史（只補股票池內的股票）"""
    from app.db.models import StockPool
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(DailyPrice).limit(1))).first()
    if count is not None:
        logger.info("Data exists, skipping backfill.")
        return

    async with AsyncSessionLocal() as db:
        pool_codes = {r.code for r in (await db.execute(select(StockPool))).scalars().all()}
    if not pool_codes:
        logger.warning("stock_pool is empty, skipping backfill_90_days")
        return

    logger.info(f"Starting 90-day backfill for {len(pool_codes)} pool stocks...")
    today = date.today()
    for i in range(90, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            rows_i = await fetch_institutional(d)
            price_rows = await fetch_daily_price(d)
            margin_rows = await fetch_margin(d)
            rows_i = [r for r in rows_i if r["code"] in pool_codes]
            price_rows = [r for r in price_rows if r["code"] in pool_codes]
            margin_rows = [r for r in margin_rows if r["code"] in pool_codes]
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


async def backfill_single_day(target_date: date):
    """補抓指定交易日的法人+股價+融資（不跳過已有資料）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.db.models import StockPool
    if target_date.weekday() >= 5:
        logger.warning(f"backfill_single_day: {target_date} is weekend, skip")
        return {"skipped": True, "reason": "weekend"}
    async with AsyncSessionLocal() as db:
        pool_codes = {r.code for r in (await db.execute(select(StockPool))).scalars().all()}
    logger.info(f"backfill_single_day {target_date}: pool={len(pool_codes)}")
    try:
        rows_i = await fetch_institutional(target_date)
        price_rows = await fetch_daily_price(target_date)
        margin_rows = await fetch_margin(target_date)
        rows_i = [r for r in rows_i if r["code"] in pool_codes]
        price_rows = [r for r in price_rows if r["code"] in pool_codes]
        margin_rows = [r for r in margin_rows if r["code"] in pool_codes]
        async with AsyncSessionLocal() as db:
            if rows_i:
                await db.execute(pg_insert(Institutional).values(rows_i).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
            if price_rows:
                price_stmt = pg_insert(DailyPrice).values(price_rows)
                await db.execute(price_stmt.on_conflict_do_update(
                    index_elements=["code", "trade_date"],
                    set_={"open": price_stmt.excluded.open,
                          "high": price_stmt.excluded.high,
                          "low": price_stmt.excluded.low,
                          "close": price_stmt.excluded.close,
                          "volume": price_stmt.excluded.volume},
                ))
            if margin_rows:
                await db.execute(pg_insert(MarginTrading).values(margin_rows).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
            await db.commit()
        total = len(rows_i) + len(price_rows) + len(margin_rows)
        await _log_fetch("job1", target_date, "success", len(rows_i) + len(price_rows))
        await _log_fetch("job2", target_date, "success", len(margin_rows))
        logger.info(f"backfill_single_day {target_date}: inst={len(rows_i)} price={len(price_rows)} margin={len(margin_rows)}")
        return {"ok": True, "inst": len(rows_i), "price": len(price_rows), "margin": len(margin_rows)}
    except Exception as e:
        logger.error(f"backfill_single_day {target_date} failed: {e}")
        return {"ok": False, "error": str(e)}


async def startup_gap_backfill(lookback_days: int = 14):
    """啟動時往回查缺漏的交易日（最多 lookback_days 個曆日），自動補抓 job1/job2/job4。
    只補 job1 缺失的日期；job4 每補一天就跑一次。
    """
    today = date.today()
    # 收集最近 lookback_days 曆日內所有工作日（不含今天，今天由 startup_backfill 處理）
    candidates: list[date] = []
    for i in range(1, lookback_days + 1):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            candidates.append(d)

    missing: list[date] = []
    for d in candidates:
        if not await _already_fetched("job1", d):
            missing.append(d)

    if not missing:
        logger.info("startup_gap_backfill: 無歷史缺口")
        return

    logger.info(f"startup_gap_backfill: 發現 {len(missing)} 天缺口 → {[str(d) for d in missing]}")
    for d in sorted(missing):
        logger.info(f"startup_gap_backfill: 補抓 {d}")
        result = await backfill_single_day(d)
        # 有實際資料才跑 job4；0 rows = 假日，跳過（避免 job4 撈前日資料覆蓋已有結果）
        if result.get("ok") and result.get("inst", 0) > 0:
            await job4_screener(target_date=d)
        await asyncio.sleep(2)
    logger.info("startup_gap_backfill: 補抓完成")


async def backfill_shareholding_all():
    """啟動時補填大戶持股（表為空時）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(Shareholding))).first()
    if count is not None:
        logger.info("Shareholding data exists, skipping backfill.")
        return
    async with AsyncSessionLocal() as db:
        from app.db.models import StockPool
        stock_codes = {r[0] for r in (await db.execute(select(StockPool.code))).all()}
    logger.info("Starting shareholding backfill from TDCC...")
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
        logger.info(f"Shareholding backfill complete: {len(rows)} rows.")
    except Exception as e:
        logger.error(f"Shareholding backfill failed: {e}")


async def refresh_stock_list():
    """更新股票清單（只更新股票池內的股票）"""
    from app.services.fetcher.finmind import fetch_stock_capital
    from app.db.models import StockList, StockPool
    from datetime import datetime

    async with AsyncSessionLocal() as db:
        pool_rows = (await db.execute(select(StockPool))).scalars().all()
    if not pool_rows:
        logger.warning("stock_pool is empty, skipping refresh_stock_list")
        return

    all_rows = await fetch_electronic_stocks()
    stock_map = {r["code"]: r for r in all_rows}
    pool_codes = {r.code for r in pool_rows}
    pool_name_map = {r.code: r.name for r in pool_rows}

    async with AsyncSessionLocal() as db:
        for code in pool_codes:
            r = stock_map.get(code, {
                "code": code,
                "name": pool_name_map.get(code, code),
                "market": "TWSE",
                "sector": "",
                "tags": "",
            })
            capital = await fetch_stock_capital(code)
            existing = (await db.execute(
                select(StockList).where(StockList.code == code)
            )).scalar_one_or_none()
            if existing:
                existing.name = r.get("name", existing.name)
                existing.tags = r.get("tags", existing.tags)
                if capital > 0:
                    existing.capital = capital
                existing.updated_at = datetime.utcnow()
            else:
                db.add(StockList(
                    code=code,
                    name=r.get("name", pool_name_map.get(code, code)),
                    market=r.get("market", "TWSE"),
                    sector=r.get("sector", ""),
                    tags=r.get("tags", ""),
                    capital=capital,
                ))
        await db.commit()
    logger.info(f"Stock list refreshed for {len(pool_codes)} pool stocks")
