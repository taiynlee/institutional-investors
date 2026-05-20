from datetime import date, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.db.models import ScreeningResult, FetchLog

router = APIRouter()


@router.get("/api/screener")
async def get_screener_results(
    db: AsyncSession = Depends(get_db),
    min_score: float = Query(0),
    calc_date: Optional[date] = Query(None),
):
    target_date = calc_date or date.today()
    q = select(ScreeningResult).where(
        and_(ScreeningResult.calc_date == target_date, ScreeningResult.passes == True)
    ).order_by(ScreeningResult.score.desc())
    results = (await db.execute(q)).scalars().all()
    if min_score > 0:
        results = [r for r in results if r.score >= min_score]
    return [_format_result(r) for r in results]


@router.get("/api/screener/{code}")
async def get_stock_detail(code: str, db: AsyncSession = Depends(get_db)):
    q = select(ScreeningResult).where(
        ScreeningResult.code == code
    ).order_by(ScreeningResult.calc_date.desc()).limit(30)
    rows = (await db.execute(q)).scalars().all()
    return [_format_result(r) for r in rows]


_JOB_SCHEDULE = {
    "job1": "16:05",
    "job2": "18:30",
    "job3": "20:30 (週五)",
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
            updated_at = taipei_dt.strftime("%H:%M")
        return {
            "name": job_name,
            "schedule": _JOB_SCHEDULE.get(job_name, ""),
            "status": l.status if l else "pending",
            "rows": l.rows_fetched if l else 0,
            "updated_at": updated_at,
        }

    return {
        "date": str(date.today()),
        "jobs": [_fmt_job(j) for j in ("job1", "job2", "job3", "job4")],
        "is_reliable": any(l.job_name == "job4" and l.status == "success" for l in logs),
    }


def _format_result(r: ScreeningResult) -> dict:
    return {
        "code": r.code,
        "name": r.name,
        "calc_date": str(r.calc_date),
        "tags": r.tags.split() if r.tags else [],
        "bb_position": r.bb_position,
        "bb_peak": r.bb_peak,
        "peak_days_ago": 0,
        "is_squeeze": r.is_squeeze,
        "vol_ratio": r.vol_ratio,
        "foreign_6d_net": r.foreign_6d_net,
        "trust_6d_net": r.trust_6d_net,
        "chip_ratio_6d": r.chip_ratio_6d,
        "chip_ratio_12d": r.chip_ratio_12d,
        "margin_5d_chg": r.margin_5d_chg,
        "score": r.score,
    }
