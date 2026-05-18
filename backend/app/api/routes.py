import json
from datetime import date
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
    tags: Optional[str] = Query(None),
    min_score: float = Query(0),
    calc_date: Optional[date] = Query(None),
):
    target_date = calc_date or date.today()
    q = select(ScreeningResult).where(
        and_(ScreeningResult.calc_date == target_date, ScreeningResult.passes == True)
    ).order_by(ScreeningResult.score.desc())
    results = (await db.execute(q)).scalars().all()
    if tags:
        tag_list = [t.strip() for t in tags.split(",")]
        results = [
            r for r in results
            if any(t in json.loads(r.tags or "[]") for t in tag_list)
        ]
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


@router.get("/api/status")
async def get_data_status(db: AsyncSession = Depends(get_db)):
    logs = (await db.execute(
        select(FetchLog).where(FetchLog.fetch_date == date.today())
        .order_by(FetchLog.job_name)
    )).scalars().all()
    return {
        "date": str(date.today()),
        "jobs": [{"name": l.job_name, "status": l.status, "rows": l.rows_fetched} for l in logs],
        "is_reliable": any(l.job_name == "job4" and l.status == "success" for l in logs),
    }


@router.get("/api/tags")
async def get_all_tags():
    import yaml
    from pathlib import Path
    from app.config import settings
    cfg = yaml.safe_load(open(Path(settings.config_path) / "sector_tags.yaml"))
    return {"tags": cfg.get("all_tags", [])}


def _format_result(r: ScreeningResult) -> dict:
    return {
        "code": r.code,
        "name": r.name,
        "calc_date": str(r.calc_date),
        "tags": json.loads(r.tags or "[]"),
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
