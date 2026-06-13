"""
Strategy C: 基本面加速
入選條件（硬篩）:
  1. 最新月營收 YoY >= 10%
  2. 月營收 YoY 連 2 個月加速（YoY% 數字本身在拉高）
  3. 近 2 季 EPS > 0

評分（100分）:
  月營收 YoY 幅度   25分
  月營收 YoY 連加速 15分
  月營收 MoM        15分（2月或3月固定5分）
  EPS QoQ 近2季     30分（各15分）
  EPS TTM YoY       15分
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date


@dataclass
class FinSnapshot:
    code: str
    rev_latest: float = 0.0
    rev_prev: float = 0.0
    rev_yoy_latest: float = 0.0
    rev_yoy_prev: float = 0.0
    rev_yoy_prev2: float = 0.0
    rev_month: int = 0
    eps: list[float] = field(default_factory=list)
    rev_q: list[float] = field(default_factory=list)


def _score_yoy(yoy: float) -> int:
    if yoy > 50: return 25
    if yoy > 30: return 20
    if yoy > 20: return 15
    if yoy > 10: return 8
    return 0


def _score_accel(yoy_latest: float, yoy_prev: float, yoy_prev2: float) -> int:
    m3 = yoy_latest > yoy_prev > yoy_prev2
    m2 = yoy_latest > yoy_prev
    if m3: return 15
    if m2: return 9
    return 4


def _score_mom(mom: float, month: int) -> int:
    if month in (2, 3):
        return 5
    if mom > 10: return 15
    if mom > 5:  return 10
    if mom > 0:  return 5
    return 0


def _score_eps_qoq(eps_new: float, eps_old: float) -> int:
    if eps_old == 0:
        return 6 if eps_new > 0 else 0
    pct = (eps_new - eps_old) / abs(eps_old) * 100
    if pct > 20: return 15
    if pct > 10: return 12
    if pct > 5:  return 9
    if pct > 0:  return 6
    return 0


def _score_ttm_yoy(eps: list[float]) -> int:
    if len(eps) < 8:
        return 0
    ttm = sum(eps[:4])
    prior = sum(eps[4:8])
    if prior == 0:
        return 5 if ttm > 0 else 0
    yoy = (ttm - prior) / abs(prior) * 100
    if yoy > 30: return 15
    if yoy > 20: return 12
    if yoy > 10: return 9
    if yoy > 0:  return 5
    return 0


def calc_score_c(snap: FinSnapshot) -> int:
    score = 0
    score += _score_yoy(snap.rev_yoy_latest)
    score += _score_accel(snap.rev_yoy_latest, snap.rev_yoy_prev, snap.rev_yoy_prev2)
    mom = (snap.rev_latest - snap.rev_prev) / snap.rev_prev * 100 if snap.rev_prev > 0 else 0.0
    score += _score_mom(mom, snap.rev_month)
    if len(snap.eps) >= 2:
        score += _score_eps_qoq(snap.eps[0], snap.eps[1])
    if len(snap.eps) >= 3:
        score += _score_eps_qoq(snap.eps[1], snap.eps[2])
    score += _score_ttm_yoy(snap.eps)
    return score


def passes_c(snap: FinSnapshot) -> bool:
    if snap.rev_yoy_latest < 10.0:
        return False
    if not (snap.rev_yoy_latest > snap.rev_yoy_prev):
        return False
    if len(snap.eps) < 2:
        return False
    if snap.eps[0] <= 0 or snap.eps[1] <= 0:
        return False
    return True


async def build_fin_snapshot(code: str, ref_year: int, ref_month: int) -> FinSnapshot | None:
    from sqlalchemy import select
    from app.db.base import AsyncSessionLocal
    from app.db.models import MonthlyRevenue, QuarterlyEps

    snap = FinSnapshot(code=code)

    async with AsyncSessionLocal() as db:
        rev_rows = (await db.execute(
            select(MonthlyRevenue)
            .where(MonthlyRevenue.code == code)
            .order_by(MonthlyRevenue.year.desc(), MonthlyRevenue.month.desc())
            .limit(15)
        )).scalars().all()

        eps_rows = (await db.execute(
            select(QuarterlyEps)
            .where(QuarterlyEps.code == code)
            .order_by(QuarterlyEps.year.desc(), QuarterlyEps.quarter.desc())
            .limit(8)
        )).scalars().all()

    if not rev_rows:
        return None

    rev_map: dict[tuple[int, int], float] = {
        (r.year, r.month): r.revenue for r in rev_rows
    }

    def _yoy(year: int, month: int) -> float:
        cur = rev_map.get((year, month), 0)
        prior = rev_map.get((year - 1, month), 0)
        if prior <= 0 or cur <= 0:
            return 0.0
        return (cur - prior) / prior * 100

    def _prev_month(year: int, month: int) -> tuple[int, int]:
        if month == 1:
            return year - 1, 12
        return year, month - 1

    latest = rev_rows[0]
    snap.rev_latest = latest.revenue
    snap.rev_month = latest.month

    prev_y, prev_m = _prev_month(latest.year, latest.month)
    prev2_y, prev2_m = _prev_month(prev_y, prev_m)

    snap.rev_prev = rev_map.get((prev_y, prev_m), 0)
    snap.rev_yoy_latest = _yoy(latest.year, latest.month)
    snap.rev_yoy_prev   = _yoy(prev_y, prev_m)
    snap.rev_yoy_prev2  = _yoy(prev2_y, prev2_m)

    snap.eps   = [float(r.eps) for r in eps_rows]
    snap.rev_q = [float(r.revenue) for r in eps_rows]

    return snap


async def run_screener_c() -> list[dict]:
    from sqlalchemy import select
    from app.db.base import AsyncSessionLocal
    from app.db.models import StockPool, MonthlyRevenue
    from datetime import date

    today = date.today()

    async with AsyncSessionLocal() as db:
        latest_rev = (await db.execute(
            select(MonthlyRevenue.year, MonthlyRevenue.month)
            .order_by(MonthlyRevenue.year.desc(), MonthlyRevenue.month.desc())
            .limit(1)
        )).first()
        if not latest_rev:
            return []
        ref_year, ref_month = latest_rev.year, latest_rev.month

        pool_stocks = {r.code: r for r in (await db.execute(select(StockPool))).scalars().all()}

        codes_with_rev = set(r[0] for r in (await db.execute(
            select(MonthlyRevenue.code).distinct()
            .where(MonthlyRevenue.year == ref_year, MonthlyRevenue.month == ref_month)
        )).all())

    pool_codes_with_rev = codes_with_rev & set(pool_stocks.keys())

    results = []
    for code in pool_codes_with_rev:
        snap = await build_fin_snapshot(code, ref_year, ref_month)
        if snap is None:
            continue
        if not passes_c(snap):
            continue
        score = calc_score_c(snap)
        stock = pool_stocks.get(code)
        mom = (snap.rev_latest - snap.rev_prev) / snap.rev_prev * 100 if snap.rev_prev > 0 else 0.0
        results.append({
            "calc_date": today.isoformat(),
            "code": code,
            "name": stock.name if stock else code,
            "score_c": score,
            "rev_yoy": round(snap.rev_yoy_latest, 1),
            "rev_mom": round(mom, 1),
            "rev_month": ref_month,
            "rev_year": ref_year,
            "eps_q1": snap.eps[0] if len(snap.eps) > 0 else None,
            "eps_q2": snap.eps[1] if len(snap.eps) > 1 else None,
            "eps_q3": snap.eps[2] if len(snap.eps) > 2 else None,
            "eps_q4": snap.eps[3] if len(snap.eps) > 3 else None,
        })

    results.sort(key=lambda x: x["score_c"], reverse=True)
    return results
