from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.db.models import ScreeningResult, FetchLog, DailyPrice, MarginTrading

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


@router.get("/api/result")
async def get_result_comparison(db: AsyncSession = Depends(get_db)):
    """最近一次篩選結果 vs 次交易日收盤價比較。"""
    # 最近一次篩選日（排除今天，確保已有次日價格）
    pred_date_row = (await db.execute(
        select(ScreeningResult.calc_date)
        .distinct()
        .where(ScreeningResult.calc_date < date.today())
        .order_by(ScreeningResult.calc_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not pred_date_row:
        return {"pred_date": None, "price_date": None, "rows": []}

    pred_date = pred_date_row

    # 取得那天的篩選結果
    screened = (await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.calc_date == pred_date)
        .order_by(ScreeningResult.score.desc())
    )).scalars().all()

    codes = [r.code for r in screened]
    if not codes:
        return {"pred_date": str(pred_date), "price_date": None, "rows": []}

    # 篩選日收盤（昨收）
    prev_prices = {r.code: r.close for r in (await db.execute(
        select(DailyPrice)
        .where(and_(DailyPrice.code.in_(codes), DailyPrice.trade_date == pred_date))
    )).scalars().all()}

    # 次交易日收盤（今收）— 找篩選日之後最近一天有資料的日期
    next_price_row = (await db.execute(
        select(DailyPrice.trade_date)
        .where(and_(DailyPrice.code.in_(codes), DailyPrice.trade_date > pred_date))
        .order_by(DailyPrice.trade_date)
        .limit(1)
    )).scalar_one_or_none()

    if not next_price_row:
        return {"pred_date": str(pred_date), "price_date": None, "rows": []}

    price_date = next_price_row
    next_prices = {r.code: r.close for r in (await db.execute(
        select(DailyPrice)
        .where(and_(DailyPrice.code.in_(codes), DailyPrice.trade_date == price_date))
    )).scalars().all()}

    stats = await _appearance_stats(codes, pred_date, db)

    rows = []
    for s in screened:
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
        })

    rows.sort(key=lambda x: x["chg_pct"], reverse=True)
    return {"pred_date": str(pred_date), "price_date": str(price_date), "rows": rows}


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
    "job1": "16:05",
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
            "institutional": {"label": "法人買賣超", "source": "TWSE T86", "via": "job1 16:05"},
            "price": {"label": "日收盤價", "source": "TWSE MI_INDEX", "via": "job1 16:05"},
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
