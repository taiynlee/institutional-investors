from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.db.models import ScreeningResult, FetchLog, DailyPrice, MarginTrading, AIPick, StockList, Institutional, Shareholding
from app.services.screener import calc_bb_position

router = APIRouter()


async def _appearance_stats(codes: list[str], target_date: date, db: AsyncSession) -> dict[str, dict]:
    """近 5 個有篩選結果的交易日內，每檔的出現次數與連續天數。"""
    dates_rows = (await db.execute(
        select(ScreeningResult.calc_date)
        .distinct()
        .where(ScreeningResult.calc_date <= target_date)
        .order_by(ScreeningResult.calc_date.desc())
        .limit(5)
    )).all()
    last_5 = sorted([r[0] for r in dates_rows])

    if not last_5:
        return {c: {"appearances_5d": 1, "streak": 1} for c in codes}

    hist = (await db.execute(
        select(ScreeningResult.code, ScreeningResult.calc_date)
        .where(and_(
            ScreeningResult.code.in_(codes),
            ScreeningResult.calc_date.in_(last_5),
        ))
    )).all()
    appeared = {(r[0], r[1]) for r in hist}

    stats = {}
    for code in codes:
        count = sum(1 for d in last_5 if (code, d) in appeared)
        streak = 0
        for d in sorted(last_5, reverse=True):
            if (code, d) in appeared:
                streak += 1
            else:
                break
        stats[code] = {"appearances_5d": count, "streak": streak}
    return stats


@router.get("/api/screener")
async def get_screener_results(
    db: AsyncSession = Depends(get_db),
    min_score: float = Query(60),
    calc_date: Optional[date] = Query(None),
):
    target_date = calc_date or date.today()
    q = select(ScreeningResult).where(
        and_(ScreeningResult.calc_date == target_date, ScreeningResult.passes == True)
    ).order_by(ScreeningResult.score.desc())
    results = (await db.execute(q)).scalars().all()

    # 今天沒資料時 fallback 最近一筆
    if not results and calc_date is None:
        latest = (await db.execute(
            select(ScreeningResult.calc_date)
            .where(ScreeningResult.passes == True)
            .order_by(ScreeningResult.calc_date.desc())
            .limit(1)
        )).scalar_one_or_none()
        if latest:
            target_date = latest
            results = (await db.execute(
                select(ScreeningResult).where(
                    and_(ScreeningResult.calc_date == latest, ScreeningResult.passes == True)
                ).order_by(ScreeningResult.score.desc())
            )).scalars().all()

    codes = [r.code for r in results]
    stats = await _appearance_stats(codes, target_date, db) if codes else {}

    return [_format_result(r, stats.get(r.code)) for r in results]


@router.get("/api/result/dates")
async def get_result_dates(db: AsyncSession = Depends(get_db)):
    """回傳過去 10 個有篩選結果且之後有價格資料的交易日，供下拉選單使用。"""
    candidate_dates = (await db.execute(
        select(ScreeningResult.calc_date)
        .distinct()
        .where(ScreeningResult.calc_date < date.today())
        .order_by(ScreeningResult.calc_date.desc())
        .limit(20)
    )).scalars().all()

    valid = []
    for cd in candidate_dates:
        has_next = (await db.execute(
            select(DailyPrice.trade_date)
            .where(DailyPrice.trade_date > cd)
            .limit(1)
        )).scalar_one_or_none()
        if has_next:
            valid.append(str(cd))
        if len(valid) >= 10:
            break
    return valid


@router.get("/api/result")
async def get_result_comparison(
    db: AsyncSession = Depends(get_db),
    pred_date: Optional[date] = Query(None),
):
    """篩選結果 vs 最後一個有資料交易日收盤比較。"""
    # 取得所有可用日期
    candidate_dates = (await db.execute(
        select(ScreeningResult.calc_date)
        .distinct()
        .where(ScreeningResult.calc_date < date.today())
        .order_by(ScreeningResult.calc_date.desc())
        .limit(20)
    )).scalars().all()

    # 找最後一個有價格資料的日期（基準收盤日）
    latest_price_date = (await db.execute(
        select(DailyPrice.trade_date)
        .order_by(DailyPrice.trade_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not latest_price_date:
        return {"pred_date": None, "price_date": None, "rows": []}

    # 選定 pred_date：若未指定則用最近一個有資料的日期
    if pred_date:
        chosen = pred_date if pred_date in candidate_dates else None
    else:
        chosen = None
        for cd in candidate_dates:
            if cd < latest_price_date:
                chosen = cd
                break

    if not chosen:
        return {"pred_date": None, "price_date": None, "rows": []}

    # 取得那天的篩選結果
    screened = (await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.calc_date == chosen)
        .order_by(ScreeningResult.score.desc())
    )).scalars().all()

    codes = [r.code for r in screened]
    if not codes:
        return {"pred_date": str(chosen), "price_date": None, "rows": []}

    # 篩選日收盤：找最近一個 ≤ chosen 的交易日（避免篩選日是假日無價格資料）
    prev_price_date = (await db.execute(
        select(func.max(DailyPrice.trade_date))
        .where(and_(DailyPrice.code.in_(codes), DailyPrice.trade_date <= chosen))
    )).scalar_one_or_none()

    if not prev_price_date:
        return {"pred_date": str(chosen), "price_date": None, "rows": []}

    prev_prices = {r.code: r.close for r in (await db.execute(
        select(DailyPrice)
        .where(and_(DailyPrice.code.in_(codes), DailyPrice.trade_date == prev_price_date))
    )).scalars().all()}

    # 最後一個有資料交易日收盤
    next_prices = {r.code: r.close for r in (await db.execute(
        select(DailyPrice)
        .where(and_(DailyPrice.code.in_(codes), DailyPrice.trade_date == latest_price_date))
    )).scalars().all()}

    # AI 精選
    ai_pick_row = (await db.execute(
        select(AIPick).where(AIPick.calc_date == chosen)
    )).scalar_one_or_none()
    ai_pick_code = ai_pick_row.code if ai_pick_row else None

    stats = await _appearance_stats(codes, chosen, db)

    rows = []
    for i, s in enumerate(screened):
        prev = prev_prices.get(s.code)
        nxt = next_prices.get(s.code)
        if prev is None or nxt is None:
            continue
        chg = (nxt - prev) / prev * 100
        st = stats.get(s.code, {})
        rows.append({
            "code": s.code,
            "name": s.name,
            "tags": s.tags or "",
            "score": s.score,
            "dip_bonus": s.dip_bonus or 0,
            "holders_bonus": s.holders_bonus or 0,
            "streak": st.get("streak", 1),
            "bb_position": s.bb_position or 0,
            "chip_ratio_6d": s.chip_ratio_6d or 0,
            "prev_close": prev,
            "close": nxt,
            "chg_pct": round(chg, 2),
            "is_top_score": i == 0,
            "is_ai_pick": s.code == ai_pick_code,
        })

    rows.sort(key=lambda x: x["chg_pct"], reverse=True)
    return {"pred_date": str(chosen), "price_date": str(latest_price_date), "rows": rows}


@router.get("/api/price/{code}")
async def get_price_history(code: str, db: AsyncSession = Depends(get_db)):
    cutoff = date.today() - timedelta(days=65)
    rows = (await db.execute(
        select(DailyPrice)
        .where(and_(DailyPrice.code == code, DailyPrice.trade_date >= cutoff))
        .order_by(DailyPrice.trade_date)
    )).scalars().all()
    return [{"date": str(r.trade_date), "close": r.close} for r in rows]


@router.get("/api/screener/{code}")
async def get_stock_detail(code: str, db: AsyncSession = Depends(get_db)):
    q = select(ScreeningResult).where(
        ScreeningResult.code == code
    ).order_by(ScreeningResult.calc_date.desc()).limit(30)
    rows = (await db.execute(q)).scalars().all()
    return [_format_result(r) for r in rows]


_JOB_SCHEDULE = {
    "job1": "18:00",
    "job2": "20:45",
    "job3": "18:30 (週日)",
    "job4": "21:00",
}


@router.get("/api/status")
async def get_data_status(db: AsyncSession = Depends(get_db)):
    logs = (await db.execute(
        select(FetchLog).where(FetchLog.fetch_date == date.today())
        .order_by(FetchLog.job_name)
    )).scalars().all()
    log_map = {l.job_name: l for l in logs}

    def _fmt_job(job_name: str) -> dict:
        l = log_map.get(job_name)
        updated_at = None
        if l and l.created_at:
            taipei_dt = l.created_at + timedelta(hours=8)
            updated_at = taipei_dt.strftime("%m/%d %H:%M")
        return {
            "name": job_name,
            "schedule": _JOB_SCHEDULE.get(job_name, ""),
            "status": l.status if l else "pending",
            "rows": l.rows_fetched if l else 0,
            "updated_at": updated_at,
        }

    margin_latest = (await db.execute(
        select(MarginTrading.trade_date).order_by(MarginTrading.trade_date.desc()).limit(1)
    )).scalar_one_or_none()

    return {
        "date": str(date.today()),
        "jobs": [_fmt_job(j) for j in ("job1", "job2", "job3", "job4")],
        "is_reliable": any(l.job_name == "job4" and l.status == "success" for l in logs),
        "data_sources": {
            "institutional": {"label": "法人買賣超", "source": "TWSE T86", "via": "job1 18:00"},
            "price": {"label": "日收盤價", "source": "TWSE MI_INDEX", "via": "job1 18:00"},
            "margin": {
                "label": "融資+借券",
                "source": "TWSE TWT93U",
                "via": "job2 20:45",
                "latest_date": str(margin_latest) if margin_latest else None,
            },
            "shareholding": {"label": "持股集中度", "source": "TDCC 集保", "via": "job3 週日 18:30"},
        },
    }


def _format_result(r: ScreeningResult, stats: dict | None = None) -> dict:
    appearances_5d = stats["appearances_5d"] if stats else 1
    streak = stats["streak"] if stats else 1
    return {
        "code": r.code,
        "name": r.name,
        "calc_date": str(r.calc_date),
        "tags": r.tags.split() if r.tags else [],
        "bb_position": r.bb_position,
        "bb_peak": r.bb_peak,
        "peak_days_ago": r.peak_days_ago or 0,
        "is_squeeze": r.is_squeeze,
        "vol_ratio": r.vol_ratio,
        "foreign_6d_net": r.foreign_6d_net,
        "trust_6d_net": r.trust_6d_net,
        "chip_ratio_6d": r.chip_ratio_6d,
        "chip_ratio_12d": r.chip_ratio_12d,
        "margin_5d_chg": r.margin_5d_chg,
        "lending_5d_chg": r.lending_5d_chg,
        "score": r.score,
        "dip_bonus": r.dip_bonus,
        "holders_bonus": r.holders_bonus,
        "appearances_5d": appearances_5d,
        "streak": streak,
    }


@router.get("/api/exit-alerts")
async def get_exit_alerts(db: AsyncSession = Depends(get_db)):
    """過去 10 交易日篩出的股票，檢查技術/動能/籌碼退場條件。"""
    cutoff = date.today() - timedelta(days=20)

    # 最近 10 個有篩選結果的交易日
    recent_dates = (await db.execute(
        select(ScreeningResult.calc_date)
        .distinct()
        .where(and_(ScreeningResult.calc_date >= cutoff, ScreeningResult.passes == True))
        .order_by(ScreeningResult.calc_date.desc())
        .limit(10)
    )).scalars().all()

    if not recent_dates:
        return []

    # 最新一次篩選結果的股票代號（不顯示在退場欄）
    latest_screener_date = recent_dates[0]
    current_screener_codes = set((await db.execute(
        select(ScreeningResult.code)
        .where(and_(
            ScreeningResult.calc_date == latest_screener_date,
            ScreeningResult.passes == True,
        ))
    )).scalars().all())

    all_results = (await db.execute(
        select(ScreeningResult)
        .where(and_(
            ScreeningResult.calc_date.in_(recent_dates),
            ScreeningResult.passes == True,
        ))
        .order_by(ScreeningResult.code, ScreeningResult.calc_date.desc())
    )).scalars().all()

    # 每檔：取最新一筆（最新 bb_position）+ 歷史最高 bb_peak
    # 排除目前仍在篩選結果中的股票（避免推薦 vs 退場矛盾）
    stock_latest: dict = {}
    stock_peak_bb: dict = {}
    for r in all_results:
        if r.code in current_screener_codes:
            continue
        if r.code not in stock_latest:
            stock_latest[r.code] = r
        peak = max(r.bb_peak or 0, r.bb_position or 0)
        stock_peak_bb[r.code] = max(stock_peak_bb.get(r.code, 0), peak)

    codes = list(stock_latest.keys())
    if not codes:
        return []

    # 股本
    capitals = {r.code: r.capital for r in (await db.execute(
        select(StockList).where(StockList.code.in_(codes))
    )).scalars().all()}

    # 近 3 個有資料的交易日法人資料
    inst_dates = (await db.execute(
        select(Institutional.trade_date)
        .distinct()
        .where(Institutional.trade_date >= date.today() - timedelta(days=10))
        .order_by(Institutional.trade_date.desc())
        .limit(3)
    )).scalars().all()

    chip_3d: dict = {}
    if inst_dates:
        inst_rows = (await db.execute(
            select(Institutional)
            .where(and_(
                Institutional.code.in_(codes),
                Institutional.trade_date.in_(inst_dates),
            ))
        )).scalars().all()
        for row in inst_rows:
            net = (row.foreign_net or 0) + (row.trust_net or 0)
            chip_3d[row.code] = chip_3d.get(row.code, 0) + net

    # 為每檔從 DailyPrice 抓 65 天重算 BB
    cutoff_bb = date.today() - timedelta(days=100)
    price_rows = (await db.execute(
        select(DailyPrice)
        .where(and_(
            DailyPrice.code.in_(codes),
            DailyPrice.trade_date >= cutoff_bb,
        ))
        .order_by(DailyPrice.code, DailyPrice.trade_date)
    )).scalars().all()

    closes_by_code: dict = {}
    for row in price_rows:
        closes_by_code.setdefault(row.code, []).append(row.close)

    alerts = []
    for code, latest in stock_latest.items():
        closes = closes_by_code.get(code, [])
        bb = calc_bb_position(closes) if len(closes) >= 20 else (latest.bb_position or 0)
        peak_bb = stock_peak_bb.get(code, 0)
        capital = capitals.get(code) or 1
        chip_sum = chip_3d.get(code, 0)
        chip_pct = chip_sum / capital * 100

        triggered = []
        if bb < 0:
            triggered.append({"type": "tech", "label": "跌破月線", "bb": round(bb, 1)})
        if chip_pct <= -0.5:
            triggered.append({"type": "chip", "label": "籌碼出場", "chip_pct": round(chip_pct, 2)})

        if triggered:
            alerts.append({
                "code": code,
                "name": latest.name,
                "bb": round(bb, 1),
                "peak_bb": round(peak_bb, 1),
                "chip_3d_pct": round(chip_pct, 2),
                "triggered": triggered,
            })

    return alerts


@router.get("/api/holders")
async def get_holders(
    db: AsyncSession = Depends(get_db),
):
    """千張大戶占比排行，含週增減。"""
    latest_date = (await db.execute(
        select(func.max(Shareholding.report_date))
    )).scalar_one_or_none()

    if not latest_date:
        return []

    prev_date = (await db.execute(
        select(func.max(Shareholding.report_date)).where(Shareholding.report_date < latest_date)
    )).scalar_one_or_none()

    latest_rows = {r.code: r for r in (await db.execute(
        select(Shareholding).where(Shareholding.report_date == latest_date)
    )).scalars().all()}

    prev_rows = {}
    if prev_date:
        prev_rows = {r.code: r for r in (await db.execute(
            select(Shareholding).where(Shareholding.report_date == prev_date)
        )).scalars().all()}

    stocks = {r.code: r for r in (await db.execute(
        select(StockList).where(StockList.code.in_(list(latest_rows.keys())))
    )).scalars().all()}

    result = []
    for code, sh in latest_rows.items():
        sl = stocks.get(code)
        prev = prev_rows.get(code)
        result.append({
            "code": code,
            "name": sl.name if sl else code,
            "sector": sl.sector if sl else "",
            "report_date": str(sh.report_date),
            "holders": sh.holders_1000_lot,
            "pct": sh.pct_1000_lot,
            "prev_holders": prev.holders_1000_lot if prev else None,
            "prev_pct": prev.pct_1000_lot if prev else None,
            "holders_chg": (sh.holders_1000_lot - prev.holders_1000_lot) if prev else None,
            "pct_chg": round(sh.pct_1000_lot - prev.pct_1000_lot, 2) if prev else None,
        })

    result.sort(key=lambda x: x["pct_chg"] if x["pct_chg"] is not None else -999, reverse=True)
    return result


@router.get("/api/ai-pick")
async def get_ai_pick(db: AsyncSession = Depends(get_db)):
    """回傳最近一筆 AI 精選結果，只回傳與最新篩選同日的結果。"""
    latest_screen_date = (await db.execute(
        select(ScreeningResult.calc_date)
        .where(ScreeningResult.passes == True)
        .order_by(ScreeningResult.calc_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not latest_screen_date:
        return {"calc_date": None, "code": None, "name": None, "reason": None}

    row = (await db.execute(
        select(AIPick).where(AIPick.calc_date == latest_screen_date)
    )).scalar_one_or_none()
    if not row:
        return {"calc_date": None, "code": None, "name": None, "reason": None}
    return {
        "calc_date": str(row.calc_date),
        "code": row.code,
        "name": row.name,
        "reason": row.reason,
    }
