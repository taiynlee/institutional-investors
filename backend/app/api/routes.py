from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.db.base import engine
import asyncio
from app.db.models import (
    ScreeningResult, FetchLog, DailyPrice, MarginTrading, AIPick,
    StockList, Institutional, Shareholding, IcClassification,
    CompanyTag, MonthlyRevenue, QuarterlyEps, WatchlistA, StockPool, UsWatchlist,
    DaytradeCandidate, DaytradePreSessionLog, TradingSetting,
)
from app.services.screener import calc_bb_position

router = APIRouter()


async def _appearance_stats(codes: list[str], target_date: date, db: AsyncSession) -> dict[str, dict]:
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
        "chip_ratio_1d": r.chip_ratio_1d,
        "chip_ratio_6d": r.chip_ratio_6d,
        "chip_ratio_12d": r.chip_ratio_12d,
        "chip_ratio_20d": r.chip_ratio_20d,
        "margin_5d_chg": r.margin_5d_chg,
        "lending_5d_chg": r.lending_5d_chg,
        "score_a": r.score_a or 0,
        "score_b": r.score_b or 0,
        "dip_bonus": r.dip_bonus,
        "holders_bonus": r.holders_bonus,
        "holders_w2": r.holders_w2,
        "holders_w3": r.holders_w3,
        "ma5_days": r.ma5_days or 0,
        "upper_slope": r.upper_slope or 0,
        "ma20_slope": r.ma20_slope or 0,
        "close_position": r.close_position or 0,
        "change_pct": r.change_pct or 0,
        "appearances_5d": appearances_5d,
        "streak": streak,
    }


@router.get("/api/screener")
async def get_screener_results(
    db: AsyncSession = Depends(get_db),
    min_score: float = Query(60),
    calc_date: Optional[date] = Query(None),
):
    target_date = calc_date or date.today()
    q = (
        select(ScreeningResult)
        .where(and_(ScreeningResult.calc_date == target_date, ScreeningResult.passes == True))
        .order_by(ScreeningResult.score_b.desc())
    )
    results = (await db.execute(q)).scalars().all()

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
                select(ScreeningResult)
                .where(and_(ScreeningResult.calc_date == latest, ScreeningResult.passes == True))
                .order_by(ScreeningResult.score_b.desc())
            )).scalars().all()

    codes = [r.code for r in results]
    stats = await _appearance_stats(codes, target_date, db) if codes else {}
    return [_format_result(r, stats.get(r.code)) for r in results]


async def _ic_names_map(codes: list[str], db: AsyncSession) -> dict[str, list[str]]:
    if not codes:
        return {}
    rows = (await db.execute(
        select(CompanyTag.code, CompanyTag.tag)
        .where(CompanyTag.code.in_(codes))
    )).all()
    result: dict[str, list[str]] = {}
    for code, tag in rows:
        result.setdefault(code, []).append(tag)
    return result


@router.get("/api/score-a")
async def get_score_a(
    db: AsyncSession = Depends(get_db),
    calc_date: Optional[date] = Query(None),
):
    """策略A：BB突破品質評分 (100分)，score_a > 0"""
    target_date = calc_date or date.today()
    results = (await db.execute(
        select(ScreeningResult)
        .where(and_(
            ScreeningResult.calc_date == target_date,
            ScreeningResult.passes == True,
            ScreeningResult.tags.contains("A"),
            ScreeningResult.score_a > 0,
        ))
        .order_by(ScreeningResult.score_a.desc())
    )).scalars().all()

    if not results and calc_date is None:
        latest = (await db.execute(
            select(ScreeningResult.calc_date)
            .where(and_(
                ScreeningResult.passes == True,
                ScreeningResult.tags.contains("A"),
                ScreeningResult.score_a > 0,
            ))
            .order_by(ScreeningResult.calc_date.desc())
            .limit(1)
        )).scalar_one_or_none()
        if latest:
            target_date = latest
            results = (await db.execute(
                select(ScreeningResult)
                .where(and_(
                    ScreeningResult.calc_date == latest,
                    ScreeningResult.passes == True,
                    ScreeningResult.tags.contains("A"),
                    ScreeningResult.score_a > 0,
                ))
                .order_by(ScreeningResult.score_a.desc())
            )).scalars().all()

    codes = [r.code for r in results]
    stats = await _appearance_stats(codes, target_date, db) if codes else {}
    ic_map = await _ic_names_map(codes, db)
    out = []
    for r in results:
        d = _format_result(r, stats.get(r.code))
        d["ic_names"] = ic_map.get(r.code, [])
        out.append(d)
    return out


@router.get("/api/score-b")
async def get_score_b(
    db: AsyncSession = Depends(get_db),
    calc_date: Optional[date] = Query(None),
):
    """策略B：籌碼拉回評分，與主頁/score-a 一致：單一最新日期 + passes=True"""
    target_date = calc_date or date.today()
    results = (await db.execute(
        select(ScreeningResult)
        .where(and_(
            ScreeningResult.calc_date == target_date,
            ScreeningResult.passes == True,
            ScreeningResult.tags.contains("B"),
        ))
        .order_by(ScreeningResult.score_b.desc())
    )).scalars().all()

    if not results and calc_date is None:
        latest = (await db.execute(
            select(ScreeningResult.calc_date)
            .where(and_(ScreeningResult.passes == True, ScreeningResult.tags.contains("B")))
            .order_by(ScreeningResult.calc_date.desc())
            .limit(1)
        )).scalar_one_or_none()
        if latest:
            target_date = latest
            results = (await db.execute(
                select(ScreeningResult)
                .where(and_(
                    ScreeningResult.calc_date == latest,
                    ScreeningResult.passes == True,
                    ScreeningResult.tags.contains("B"),
                ))
                .order_by(ScreeningResult.score_b.desc())
            )).scalars().all()

    codes = [r.code for r in results]
    stats = await _appearance_stats(codes, target_date, db) if codes else {}

    vol_map: dict[str, int] = {}
    if codes:
        vol_rows = (await db.execute(
            select(DailyPrice.code, DailyPrice.volume)
            .where(and_(
                DailyPrice.code.in_(codes),
                DailyPrice.trade_date == target_date,
            ))
        )).all()
        vol_map = dict(vol_rows)

    out = []
    for r in results:
        d = _format_result(r, stats.get(r.code))
        d["volume"] = vol_map.get(r.code, 0)
        d["rs_vs_market"] = r.rs_vs_market or 0
        out.append(d)
    return out


@router.get("/api/score-c")
async def get_score_c(
    db: AsyncSession = Depends(get_db),
):
    """策略C：基本面加速篩選"""
    from app.services.screener_c import run_screener_c
    results = await run_screener_c()
    return results


@router.get("/api/result/dates")
async def get_result_dates(db: AsyncSession = Depends(get_db)):
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
    candidate_dates = (await db.execute(
        select(ScreeningResult.calc_date)
        .distinct()
        .where(ScreeningResult.calc_date < date.today())
        .order_by(ScreeningResult.calc_date.desc())
        .limit(20)
    )).scalars().all()

    latest_price_date = (await db.execute(
        select(DailyPrice.trade_date)
        .order_by(DailyPrice.trade_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    if not latest_price_date:
        return {"pred_date": None, "price_date": None, "rows": []}

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

    screened = (await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.calc_date == chosen)
        .order_by(ScreeningResult.score_b.desc())
    )).scalars().all()

    codes = [r.code for r in screened]
    if not codes:
        return {"pred_date": str(chosen), "price_date": None, "rows": []}

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

    next_prices = {r.code: r.close for r in (await db.execute(
        select(DailyPrice)
        .where(and_(DailyPrice.code.in_(codes), DailyPrice.trade_date == latest_price_date))
    )).scalars().all()}

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
            "score_b": s.score_b or 0,
            "score_a": s.score_a or 0,
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
    rows = (await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.code == code)
        .order_by(ScreeningResult.calc_date.desc())
        .limit(30)
    )).scalars().all()
    return [_format_result(r) for r in rows]


_JOB_SCHEDULE = {
    "job1": "18:00（週一～五）",
    "job2": "20:45（週一～五）",
    "job3": "18:30（週日）",
    "job4": "21:00（週一～五）",
    "job8": "21:05（週一～五）",
    "job5": "每月10-25日 12:00",
    "job6": "每季（3/1, 5/16, 8/15, 11/15）",
    "job7": "每半年（1/1, 7/1）",
}

_JOB_DISPLAY_NAME = {
    "job1": "法人＋股價",
    "job2": "融資借券",
    "job3": "大戶持股",
    "job4": "選股篩選",
    "job8": "當沖篩選",
    "job5": "月營收",
    "job6": "季報EPS",
    "job7": "產業鏈",
}


@router.get("/api/status")
async def get_data_status(db: AsyncSession = Depends(get_db)):
    logs = (await db.execute(
        select(FetchLog)
        .order_by(FetchLog.fetch_date.desc(), FetchLog.job_name)
    )).scalars().all()

    # job5/job6 use dynamic keys (e.g. job5_202605, job6_q2_2026); match by prefix
    def _best_log(prefix: str) -> FetchLog | None:
        today_str = str(date.today())
        candidates = [l for l in logs if l.job_name.startswith(prefix)]
        if not candidates:
            return None
        # prefer today's entry; fallback to most recent
        today_hits = [l for l in candidates if str(l.fetch_date) == today_str]
        return today_hits[0] if today_hits else candidates[0]

    log_map: dict[str, FetchLog | None] = {
        "job1": next((l for l in logs if l.job_name == "job1" and str(l.fetch_date) == str(date.today())), None),
        "job2": next((l for l in logs if l.job_name == "job2" and str(l.fetch_date) == str(date.today())), None),
        "job3": next((l for l in logs if l.job_name == "job3"), None),
        "job4": next((l for l in logs if l.job_name == "job4" and str(l.fetch_date) == str(date.today())), None),
        "job8": next((l for l in logs if l.job_name == "job8" and str(l.fetch_date) == str(date.today())), None),
        "job5": _best_log("job5_"),
        "job6": _best_log("job6_"),
        "job7": _best_log("job7_"),
    }

    def _fmt_job(job_name: str) -> dict:
        l = log_map.get(job_name)
        updated_at = None
        if l and l.created_at:
            taipei_dt = l.created_at + timedelta(hours=8)
            updated_at = taipei_dt.strftime("%m/%d %H:%M")
        return {
            "name": _JOB_DISPLAY_NAME.get(job_name, job_name),
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
        "jobs": [_fmt_job(j) for j in ("job1", "job2", "job3", "job4", "job8", "job5", "job6", "job7")],
        "is_reliable": log_map.get("job4") is not None and log_map["job4"].status == "success",
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
            "monthly_revenue": {"label": "月營收", "source": "MOPS", "via": "job5 每月10-25日"},
            "quarterly_eps": {"label": "季報EPS", "source": "FinMind", "via": "job6 每季"},
        },
    }


@router.get("/api/sector-flow")
async def get_sector_flow(
    db: AsyncSession = Depends(get_db),
    days: int = Query(5, ge=1, le=30),
):
    """各類股法人買賣超統計"""
    cutoff = date.today() - timedelta(days=days * 2)
    inst_dates = (await db.execute(
        select(Institutional.trade_date).distinct()
        .where(Institutional.trade_date >= cutoff)
        .order_by(Institutional.trade_date.desc())
        .limit(days)
    )).scalars().all()

    if not inst_dates:
        return []

    stocks = {r.code: r for r in (await db.execute(select(StockList))).scalars().all()}
    inst_rows = (await db.execute(
        select(Institutional)
        .where(and_(
            Institutional.code.in_(list(stocks.keys())),
            Institutional.trade_date.in_(inst_dates),
        ))
    )).scalars().all()

    sector_agg: dict = defaultdict(lambda: {"net": 0.0, "count": 0})
    for row in inst_rows:
        stock = stocks.get(row.code)
        if not stock:
            continue
        sector = stock.sector or "其他"
        net = (row.foreign_net or 0) + (row.trust_net or 0)
        sector_agg[sector]["net"] += net
        sector_agg[sector]["count"] += 1

    result = [
        {"sector": sector, "net": round(v["net"]), "stock_count": v["count"]}
        for sector, v in sector_agg.items()
    ]
    result.sort(key=lambda x: x["net"], reverse=True)
    return result


@router.get("/api/sector-stocks/{sector}")
async def get_sector_stocks(
    sector: str,
    db: AsyncSession = Depends(get_db),
    days: int = Query(5, ge=1, le=20),
):
    """某類股下各股法人淨額排行"""
    stocks = {r.code: r for r in (await db.execute(
        select(StockList).where(StockList.sector == sector)
    )).scalars().all()}
    if not stocks:
        return []

    cutoff = date.today() - timedelta(days=days * 2)
    inst_dates = (await db.execute(
        select(Institutional.trade_date).distinct()
        .where(Institutional.trade_date >= cutoff)
        .order_by(Institutional.trade_date.desc())
        .limit(days)
    )).scalars().all()

    inst_rows = (await db.execute(
        select(Institutional)
        .where(and_(
            Institutional.code.in_(list(stocks.keys())),
            Institutional.trade_date.in_(inst_dates),
        ))
    )).scalars().all()

    agg: dict = defaultdict(float)
    for row in inst_rows:
        agg[row.code] += (row.foreign_net or 0) + (row.trust_net or 0)

    result = [
        {"code": code, "name": stocks[code].name, "net": round(net)}
        for code, net in agg.items()
    ]
    result.sort(key=lambda x: x["net"], reverse=True)
    return result


_market_overview_cache: list[dict] = []


@router.get("/api/market-overview")
async def get_market_overview():
    """大盤行情：fast_info（即時）優先，fallback history"""
    import asyncio, math
    from concurrent.futures import ThreadPoolExecutor
    global _market_overview_cache
    try:
        import yfinance as yf
    except ImportError:
        return _market_overview_cache or []

    symbols = {
        "^TWII":  "台灣加權",
        "^SOX":   "費半",
        "^IXIC":  "Nasdaq",
        "^N225":  "日經225",
        "^KS11":  "韓國綜合",
    }

    def fetch_index(sym: str, name: str):
        try:
            from datetime import date as _date
            ticker = yf.Ticker(sym)

            # 取 history — 最近確認收盤價
            hist = ticker.history(period="10d", auto_adjust=True).dropna(subset=["Close"])
            if len(hist) < 1:
                return None
            hist_last = float(hist["Close"].iloc[-1])

            # 嘗試 fast_info 現價
            fi_price = None
            try:
                fi_price = float(ticker.fast_info.last_price)
                if math.isnan(fi_price):
                    fi_price = None
            except Exception:
                pass

            # 若 fast_info 與 history[-1] 差異 > 0.01%，代表有新一日資料
            if (fi_price is not None and hist_last != 0
                    and abs(fi_price - hist_last) / hist_last > 0.0001):
                last = fi_price
                prev = hist_last
                date_str = _date.today().strftime("%m/%d")
            else:
                # 同一日或 fast_info 無效 → 純 history
                if len(hist) < 2:
                    return None
                last = hist_last
                prev = float(hist["Close"].iloc[-2])
                try:
                    date_str = hist.index[-1].strftime("%m/%d")
                except Exception:
                    date_str = str(hist.index[-1])[:10][5:].replace("-", "/")

            if math.isnan(last) or math.isnan(prev) or prev == 0:
                return None
            chg_pts = last - prev
            chg_pct = chg_pts / prev * 100
            return {
                "symbol": sym,
                "name": name,
                "close": round(last, 2),
                "chg_pts": round(chg_pts, 2),
                "chg_pct": round(chg_pct, 2),
                "date": date_str,
            }
        except Exception:
            return None

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=5) as ex:
        tasks = [loop.run_in_executor(ex, fetch_index, sym, name) for sym, name in symbols.items()]
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=45.0)
        except asyncio.TimeoutError:
            results = []

    fresh = [r for r in results if r is not None]
    if fresh:
        order = list(symbols.keys())
        fresh.sort(key=lambda r: order.index(r["symbol"]) if r["symbol"] in order else 99)
        _market_overview_cache = fresh
        return fresh

    return _market_overview_cache or []


@router.get("/api/trading-settings")
async def get_trading_settings(db: AsyncSession = Depends(get_db)):
    """回傳所有交易引擎設定（key-value dict）"""
    rows = (await db.execute(select(TradingSetting))).scalars().all()
    return {r.key: r.value for r in rows}


@router.post("/api/trading-settings")
async def update_trading_settings(body: dict, db: AsyncSession = Depends(get_db)):
    """Upsert 交易引擎設定。body = {key: value, ...}（value 皆為字串）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from datetime import datetime as _dt
    now_ts = _dt.utcnow()
    for k, v in body.items():
        await db.execute(
            pg_insert(TradingSetting)
            .values(key=k, value=str(v), updated_at=now_ts)
            .on_conflict_do_update(index_elements=["key"], set_={"value": str(v), "updated_at": now_ts})
        )
    await db.commit()
    rows = (await db.execute(select(TradingSetting))).scalars().all()
    return {r.key: r.value for r in rows}


@router.get("/api/server-time")
async def server_time():
    """回傳台北當前時間（毫秒 timestamp + ISO string），供前端時鐘同步"""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone(timedelta(hours=8)))
    return {"timestamp_ms": int(now.timestamp() * 1000), "taipei": now.isoformat()}


@router.get("/api/taifex-futures")
async def taifex_futures():
    """台指期最新報價（TAIFEX 公開 API）
    MarketType=1 → 夜盤（-M suffix）；MarketType=0 → 日盤（-F suffix）
    優先夜盤，無資料 fallback 日盤。
    """
    import httpx, re
    url = "https://mis.taifex.com.tw/futures/api/getQuoteList"
    headers = {"Referer": "https://mis.taifex.com.tw/"}

    def _extract(items: list, suffix: str) -> dict | None:
        pattern = re.compile(rf"^TXF[A-L]\d+-{suffix}$")
        for item in items:
            if not pattern.match(item.get("SymbolID", "")):
                continue
            vol = item.get("CTotalVolume", "")
            last_str = item.get("CLastPrice", "")
            diff_str = item.get("CDiff", "")
            if not vol or not last_str or not diff_str:
                continue
            rate_str = item.get("CDiffRate", "")
            return {
                "symbol": item["SymbolID"],
                "session": "night" if suffix == "M" else "day",
                "last": float(last_str),
                "diff": float(diff_str),
                "diff_pct": float(rate_str) if rate_str else None,
                "volume": int(vol),
                "date": item.get("CDate", ""),
                "time": item.get("CTime", ""),
            }
        return None

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Try night session first (MarketType=1, SymbolID suffix -M)
            r1 = await client.post(url, json={
                "SymbolType": "F", "MarketType": "1", "SymbolCode": "TX",
                "ContractYear": "", "ContractMonth": "", "SettlementMonth": "0",
                "Settlement": "", "Status": "0",
            }, headers=headers)
            night_items = (r1.json().get("RtData") or {}).get("QuoteList") or []
            result = _extract(night_items, "M")
            if result:
                return result

            # Fallback: day session (MarketType=0, SymbolID suffix -F)
            r0 = await client.post(url, json={
                "SymbolType": "F", "MarketType": "0", "SymbolCode": "TX",
                "ContractYear": "", "ContractMonth": "", "SettlementMonth": "0",
                "Settlement": "", "Status": "0",
            }, headers=headers)
            day_items = (r0.json().get("RtData") or {}).get("QuoteList") or []
            return _extract(day_items, "F")
    except Exception:
        pass
    return None


@router.get("/api/is-trading-day")
async def is_trading_day():
    """檢查今天台股是否開盤（非週末 + 非國定假日）"""
    import httpx
    today = date.today()
    if today.weekday() >= 5:
        return {"trading": False, "reason": "weekend"}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule",
                params={"response": "json", "queryYear": str(today.year)},
            )
            rows = r.json().get("data", [])
            holidays = {row[0] for row in rows}
            today_str = today.strftime("%Y/%m/%d")
            if today_str in holidays:
                return {"trading": False, "reason": "holiday"}
    except Exception:
        pass
    return {"trading": True}


@router.get("/api/us-watchlist")
async def get_us_watchlist(db: AsyncSession = Depends(get_db)):
    """美股追蹤清單"""
    rows = (await db.execute(
        select(UsWatchlist).order_by(UsWatchlist.added_at)
    )).scalars().all()
    return [{"id": r.id, "symbol": r.symbol, "name": r.name, "added_at": r.added_at.isoformat()} for r in rows]


class UsWatchlistAdd(BaseModel):
    symbol: str
    name: str = ""


@router.post("/api/us-watchlist")
async def add_us_watchlist(body: UsWatchlistAdd, db: AsyncSession = Depends(get_db)):
    sym = body.symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol 不可為空")
    existing = (await db.execute(
        select(UsWatchlist).where(UsWatchlist.symbol == sym)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"{sym} 已在清單中")
    item = UsWatchlist(symbol=sym, name=body.name.strip())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"ok": True, "id": item.id, "symbol": item.symbol, "name": item.name}


@router.delete("/api/us-watchlist/{symbol}")
async def delete_us_watchlist(symbol: str, db: AsyncSession = Depends(get_db)):
    sym = symbol.strip().upper()
    item = (await db.execute(
        select(UsWatchlist).where(UsWatchlist.symbol == sym)
    )).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=f"{sym} 不在清單中")
    await db.delete(item)
    await db.commit()
    return {"ok": True, "symbol": sym}


@router.get("/api/us-stock-lookup")
async def us_stock_lookup(symbol: str):
    """查詢美股代號的英文名稱（yfinance shortName），供前端新增時自動帶入"""
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor
    import asyncio
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol 不可為空")
    def _fetch():
        try:
            info = yf.Ticker(sym).info
            return info.get("shortName") or info.get("longName") or ""
        except Exception:
            return ""
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=1) as ex:
        eng_name = await loop.run_in_executor(ex, _fetch)
    return {"symbol": sym, "eng_name": eng_name}


_us_stocks_cache: list[dict] = []


@router.get("/api/us-stocks")
async def get_us_stocks(db: AsyncSession = Depends(get_db)):
    """美股追蹤清單（收盤價＋盤後價）"""
    import yfinance as yf
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    global _us_stocks_cache

    rows = (await db.execute(
        select(UsWatchlist).order_by(UsWatchlist.added_at)
    )).scalars().all()
    watchlist = [(r.symbol, r.name) for r in rows]
    if not watchlist:
        _us_stocks_cache = []
        return []

    def fetch_one(sym: str, name: str):
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")  # 5d 確保週末也有資料
            if len(hist) < 1:
                return None
            close = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
            chg_pct = (close - prev) / prev * 100 if prev else 0

            # 盤後價：先試 fast_info（盤後時段有值），再 fallback 到 .info
            post_price = None
            try:
                fi = t.fast_info
                pp = getattr(fi, "post_market_price", None)
                if pp and float(pp) != close:
                    post_price = float(pp)
            except Exception:
                pass
            if post_price is None:
                try:
                    info = t.info
                    pp = info.get("postMarketPrice")
                    if pp and float(pp) != close:
                        post_price = float(pp)
                except Exception:
                    pass

            post_chg_pct = None
            if post_price and close:
                post_chg_pct = (post_price - close) / close * 100

            return {
                "symbol": sym,
                "name": name,
                "close": round(close, 2),
                "chg_pct": round(chg_pct, 2),
                "post_price": round(post_price, 2) if post_price else None,
                "post_chg_pct": round(post_chg_pct, 2) if post_chg_pct is not None else None,
            }
        except Exception:
            return None

    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=8) as ex:
        tasks = [loop.run_in_executor(ex, fetch_one, sym, name) for sym, name in watchlist]
        try:
            results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=45.0)
        except asyncio.TimeoutError:
            results = []

    fresh = [r for r in results if r is not None]
    if fresh:
        sym_order = {sym: i for i, (sym, _) in enumerate(watchlist)}
        fresh.sort(key=lambda r: sym_order.get(r["symbol"], 999))
        # 保留快取的盤後價（非盤後時段 fetch 會是 None，延用上次盤後資料）
        cache_map = {item["symbol"]: item for item in _us_stocks_cache}
        for item in fresh:
            if item["post_price"] is None and item["symbol"] in cache_map:
                prev_cached = cache_map[item["symbol"]]
                if prev_cached.get("post_price"):
                    item["post_price"] = prev_cached["post_price"]
                    item["post_chg_pct"] = prev_cached.get("post_chg_pct")
        _us_stocks_cache = fresh
        return fresh

    # fetch 全失敗 → 回傳上次快取
    if _us_stocks_cache:
        return _us_stocks_cache
    return []


@router.get("/api/stock-snapshot/{code}")
async def get_stock_snapshot(code: str, db: AsyncSession = Depends(get_db)):
    """單股完整快照"""
    stock = (await db.execute(
        select(StockList).where(StockList.code == code)
    )).scalar_one_or_none()
    if not stock:
        raise HTTPException(status_code=404, detail="Stock not found")

    latest_screen = (await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.code == code)
        .order_by(ScreeningResult.calc_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    latest_price = (await db.execute(
        select(DailyPrice)
        .where(DailyPrice.code == code)
        .order_by(DailyPrice.trade_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    latest_inst = (await db.execute(
        select(Institutional)
        .where(Institutional.code == code)
        .order_by(Institutional.trade_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    latest_sh = (await db.execute(
        select(Shareholding)
        .where(Shareholding.code == code)
        .order_by(Shareholding.report_date.desc())
        .limit(1)
    )).scalar_one_or_none()

    tags = [r.tag for r in (await db.execute(
        select(CompanyTag).where(CompanyTag.code == code)
    )).scalars().all()]

    return {
        "code": code,
        "name": stock.name,
        "sector": stock.sector,
        "market": stock.market,
        "capital": stock.capital,
        "tags": tags,
        "price": {
            "close": latest_price.close if latest_price else None,
            "high": latest_price.high if latest_price else None,
            "low": latest_price.low if latest_price else None,
            "volume": latest_price.volume if latest_price else None,
            "date": str(latest_price.trade_date) if latest_price else None,
        },
        "inst": {
            "foreign_net": latest_inst.foreign_net if latest_inst else None,
            "trust_net": latest_inst.trust_net if latest_inst else None,
            "three_major_net": latest_inst.three_major_net if latest_inst else None,
            "date": str(latest_inst.trade_date) if latest_inst else None,
        },
        "shareholding": {
            "pct_1000_lot": latest_sh.pct_1000_lot if latest_sh else None,
            "pct_400_lot": latest_sh.pct_400_lot if latest_sh else None,
            "date": str(latest_sh.report_date) if latest_sh else None,
        },
        "screen": _format_result(latest_screen) if latest_screen else None,
    }


@router.get("/api/stock-levels/{code}")
async def get_stock_levels(code: str, db: AsyncSession = Depends(get_db)):
    """支撐壓力位階計算"""
    import pandas as pd
    from app.services.stock_levels import calc_levels

    cutoff = date.today() - timedelta(days=380)
    price_rows = (await db.execute(
        select(DailyPrice)
        .where(and_(DailyPrice.code == code, DailyPrice.trade_date >= cutoff))
        .order_by(DailyPrice.trade_date)
    )).scalars().all()

    if not price_rows:
        return {"current_price": 0, "supports": [], "resistances": []}

    inst_rows = (await db.execute(
        select(Institutional)
        .where(and_(Institutional.code == code, Institutional.trade_date >= cutoff))
        .order_by(Institutional.trade_date)
    )).scalars().all()

    price_df = pd.DataFrame([
        {
            "trade_date": r.trade_date,
            "open": r.open, "high": r.high, "low": r.low,
            "close": r.close, "volume": r.volume,
        }
        for r in price_rows
    ])
    inst_df = pd.DataFrame([
        {"trade_date": r.trade_date, "three_major_net": r.three_major_net}
        for r in inst_rows
    ])

    return calc_levels(price_df, inst_df)


@router.get("/api/stock-peers/{code}")
async def get_stock_peers(code: str, db: AsyncSession = Depends(get_db)):
    """同類股同業列表"""
    stock = (await db.execute(
        select(StockList).where(StockList.code == code)
    )).scalar_one_or_none()
    if not stock or not stock.sector:
        return []

    peers = (await db.execute(
        select(StockList)
        .where(and_(StockList.sector == stock.sector, StockList.code != code))
        .limit(30)
    )).scalars().all()

    result = []
    for p in peers:
        latest_price = (await db.execute(
            select(DailyPrice)
            .where(DailyPrice.code == p.code)
            .order_by(DailyPrice.trade_date.desc())
            .limit(1)
        )).scalar_one_or_none()
        result.append({
            "code": p.code,
            "name": p.name,
            "close": latest_price.close if latest_price else None,
        })
    return result


@router.get("/api/company-tags")
async def get_all_company_tags(db: AsyncSession = Depends(get_db)):
    """所有股票標籤（依代碼分組）"""
    rows = (await db.execute(
        select(CompanyTag).order_by(CompanyTag.code, CompanyTag.tag)
    )).scalars().all()
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r.code, []).append(r.tag)
    return result


@router.get("/api/company-tags/{code}")
async def get_company_tags(code: str, db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(CompanyTag).where(CompanyTag.code == code)
    )).scalars().all()
    return [r.tag for r in rows]


@router.get("/api/fins/{code}")
async def get_fins(code: str, db: AsyncSession = Depends(get_db)):
    """財務資料：月營收 + 季報EPS"""
    rev_rows = (await db.execute(
        select(MonthlyRevenue)
        .where(MonthlyRevenue.code == code)
        .order_by(MonthlyRevenue.year.desc(), MonthlyRevenue.month.desc())
        .limit(24)
    )).scalars().all()

    eps_rows = (await db.execute(
        select(QuarterlyEps)
        .where(QuarterlyEps.code == code)
        .order_by(QuarterlyEps.year.desc(), QuarterlyEps.quarter.desc())
        .limit(8)
    )).scalars().all()

    rev_list = [
        {"year": r.year, "month": r.month, "revenue": r.revenue}
        for r in rev_rows
    ]
    eps_list = [
        {
            "year": r.year, "quarter": r.quarter,
            "eps": r.eps, "revenue": r.revenue,
            "op_income": r.op_income, "net_income": r.net_income,
        }
        for r in eps_rows
    ]
    return {"revenue": rev_list, "eps": eps_list}


@router.get("/api/ic-chains")
async def get_ic_chains_new(db: AsyncSession = Depends(get_db)):
    """產業鏈分類 (新路徑)"""
    from collections import OrderedDict
    rows = (await db.execute(
        select(IcClassification, StockList.name.label("sl_name"))
        .outerjoin(StockList, IcClassification.code == StockList.code)
        .order_by(IcClassification.ic_code, IcClassification.code)
    )).all()

    groups: dict = OrderedDict()
    for ic, sl_name in rows:
        if ic.ic_code not in groups:
            groups[ic.ic_code] = {
                "ic_code": ic.ic_code,
                "ic_name": ic.ic_name,
                "ic_parent": ic.ic_parent,
                "companies": [],
            }
        groups[ic.ic_code]["companies"].append({
            "code": ic.code,
            "name": sl_name or ic.name or ic.code,
            "ic_node": ic.ic_node,
        })
    return list(groups.values())


@router.get("/api/ic_chain")
async def get_ic_chains(db: AsyncSession = Depends(get_db)):
    """產業鏈分類（舊路徑，保持相容）"""
    return await get_ic_chains_new(db)


@router.get("/api/watchlist-a")
async def get_watchlist_a(
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None),
):
    """策略A追蹤清單"""
    q = select(WatchlistA)
    if status:
        q = q.where(WatchlistA.status == status)
    q = q.order_by(WatchlistA.added_date.desc())
    rows = (await db.execute(q)).scalars().all()

    codes = [r.code for r in rows]
    latest_prices: dict[str, float] = {}
    if codes:
        price_subq = (
            select(DailyPrice.code, DailyPrice.close, DailyPrice.trade_date)
            .where(DailyPrice.code.in_(codes))
            .distinct(DailyPrice.code)
            .order_by(DailyPrice.code, DailyPrice.trade_date.desc())
        ).subquery()
        price_rows = (await db.execute(select(price_subq))).all()
        for r in price_rows:
            latest_prices[r.code] = r.close

    result = []
    for r in rows:
        close = latest_prices.get(r.code)
        chg_pct = None
        if close and r.added_close and r.added_close > 0:
            chg_pct = round((close - r.added_close) / r.added_close * 100, 2)
        result.append({
            "id": r.id,
            "code": r.code,
            "name": r.name,
            "added_date": str(r.added_date),
            "added_close": r.added_close,
            "added_bb_position": r.added_bb_position,
            "added_score_a": r.added_score_a,
            "status": r.status,
            "triggered_date": str(r.triggered_date) if r.triggered_date else None,
            "triggered_close": r.triggered_close,
            "triggered_bb_position": r.triggered_bb_position,
            "current_close": close,
            "chg_pct": chg_pct,
        })
    return result


class WatchlistStatusUpdate(BaseModel):
    status: str


@router.patch("/api/watchlist-a/{item_id}/status")
async def update_watchlist_status(
    item_id: int,
    body: WatchlistStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新追蹤清單狀態 (entered / exited / dismissed)"""
    valid = {"tracking", "triggered", "entered", "exited", "dismissed"}
    if body.status not in valid:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid}")
    item = (await db.execute(
        select(WatchlistA).where(WatchlistA.id == item_id)
    )).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.status = body.status
    await db.commit()
    return {"id": item_id, "status": body.status}


@router.get("/api/watchlist-a/{code}/inst-flow")
async def get_watchlist_inst_flow(
    code: str,
    db: AsyncSession = Depends(get_db),
    pre_days: int = Query(6, ge=1, le=30),
):
    """追蹤清單個股法人流向（預設6日）"""
    cutoff = date.today() - timedelta(days=pre_days * 2 + 5)
    inst_dates = (await db.execute(
        select(Institutional.trade_date).distinct()
        .where(Institutional.trade_date >= cutoff)
        .order_by(Institutional.trade_date.desc())
        .limit(pre_days)
    )).scalars().all()

    if not inst_dates:
        return []

    rows = (await db.execute(
        select(Institutional)
        .where(and_(
            Institutional.code == code,
            Institutional.trade_date.in_(inst_dates),
        ))
        .order_by(Institutional.trade_date.desc())
    )).scalars().all()

    return [
        {
            "date": str(r.trade_date),
            "foreign_net": round(r.foreign_net or 0),
            "trust_net": round(r.trust_net or 0),
            "dealer_net": round(r.dealer_net or 0),
            "net": round((r.foreign_net or 0) + (r.trust_net or 0)),
        }
        for r in rows
    ]


@router.get("/api/inst-flow/{code}")
async def get_inst_flow_stock(
    code: str,
    db: AsyncSession = Depends(get_db),
    days: int = Query(20, ge=1, le=60),
):
    """個股法人買賣超歷史"""
    cutoff = date.today() - timedelta(days=days * 2 + 5)
    inst_dates = (await db.execute(
        select(Institutional.trade_date).distinct()
        .where(Institutional.trade_date >= cutoff)
        .order_by(Institutional.trade_date.desc())
        .limit(days)
    )).scalars().all()

    if not inst_dates:
        return []

    rows = (await db.execute(
        select(Institutional)
        .where(and_(
            Institutional.code == code,
            Institutional.trade_date.in_(inst_dates),
        ))
        .order_by(Institutional.trade_date)
    )).scalars().all()

    return [
        {
            "date": str(r.trade_date),
            "foreign_net": round(r.foreign_net or 0),
            "trust_net": round(r.trust_net or 0),
            "dealer_net": round(r.dealer_net or 0),
            "net": round((r.foreign_net or 0) + (r.trust_net or 0)),
        }
        for r in rows
    ]


@router.get("/api/inst-flow")
async def get_inst_flow(
    db: AsyncSession = Depends(get_db),
    days: int = Query(5, ge=1, le=30),
    top: int = Query(30, ge=5, le=100),
):
    """法人買超 / 賣超排行"""
    cutoff = date.today() - timedelta(days=days * 2)
    inst_dates = (await db.execute(
        select(Institutional.trade_date).distinct()
        .where(Institutional.trade_date >= cutoff)
        .order_by(Institutional.trade_date.desc())
        .limit(days)
    )).scalars().all()

    if not inst_dates:
        return {"buy": [], "sell": []}

    stocks = {r.code: r for r in (await db.execute(select(StockList))).scalars().all()}
    inst_rows = (await db.execute(
        select(Institutional)
        .where(and_(
            Institutional.code.in_(list(stocks.keys())),
            Institutional.trade_date.in_(inst_dates),
        ))
    )).scalars().all()

    agg: dict = defaultdict(float)
    for row in inst_rows:
        agg[row.code] += (row.foreign_net or 0) + (row.trust_net or 0)

    sorted_agg = sorted(agg.items(), key=lambda x: x[1], reverse=True)
    buy_list = [
        {"code": c, "name": stocks[c].name if c in stocks else c, "net": round(n)}
        for c, n in sorted_agg[:top] if n > 0
    ]
    sell_list = [
        {"code": c, "name": stocks[c].name if c in stocks else c, "net": round(n)}
        for c, n in sorted_agg[-top:] if n < 0
    ]
    sell_list.reverse()
    return {"buy": buy_list, "sell": sell_list}


@router.get("/api/exit-alerts")
async def get_exit_alerts(db: AsyncSession = Depends(get_db)):
    cutoff = date.today() - timedelta(days=20)

    recent_dates = (await db.execute(
        select(ScreeningResult.calc_date)
        .distinct()
        .where(and_(ScreeningResult.calc_date >= cutoff, ScreeningResult.passes == True))
        .order_by(ScreeningResult.calc_date.desc())
        .limit(10)
    )).scalars().all()

    if not recent_dates:
        return []

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

    capitals = {r.code: r.capital for r in (await db.execute(
        select(StockList).where(StockList.code.in_(codes))
    )).scalars().all()}

    all_inst_dates = (await db.execute(
        select(Institutional.trade_date)
        .distinct()
        .where(Institutional.trade_date >= date.today() - timedelta(days=25))
        .order_by(Institutional.trade_date.desc())
        .limit(12)
    )).scalars().all()

    inst_dates_3d = set(all_inst_dates[:3])
    chip_3d: dict = {}
    chip_12d: dict = {}
    if all_inst_dates:
        inst_rows = (await db.execute(
            select(Institutional)
            .where(and_(
                Institutional.code.in_(codes),
                Institutional.trade_date.in_(all_inst_dates),
            ))
        )).scalars().all()
        for row in inst_rows:
            net = (row.foreign_net or 0) + (row.trust_net or 0)
            chip_12d[row.code] = chip_12d.get(row.code, 0) + net
            if row.trade_date in inst_dates_3d:
                chip_3d[row.code] = chip_3d.get(row.code, 0) + net

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

    # 計算每個落榜股「已消失幾個篩選日」（recent_dates 已依日期降序）
    recent_dates_sorted_asc = list(reversed(recent_dates))  # 升序
    alerts = []
    for code, latest in stock_latest.items():
        closes = closes_by_code.get(code, [])
        bb = calc_bb_position(closes) if len(closes) >= 20 else (latest.bb_position or 0)
        capital = capitals.get(code) or 0
        chip_sum = chip_3d.get(code, 0)
        last_seen = latest.calc_date

        # 消失幾個篩選日（recent_dates 裡在 last_seen 之後的個數）
        days_off = sum(1 for d in recent_dates if d > last_seen)

        badges = []
        chip_pct = None
        if capital and capital > 0:
            chip_pct = chip_sum / capital * 100
            chip_12d_pct = chip_12d.get(code, 0) / capital * 100
            if chip_pct <= -1.5 and chip_12d_pct <= 0:
                badges.append({"type": "chip", "label": "籌碼出場"})

        alerts.append({
            "code": code,
            "name": latest.name,
            "bb": round(bb, 1),
            "chip_3d_pct": round(chip_pct, 2) if chip_pct is not None else None,
            "last_seen_date": str(last_seen),
            "days_off": days_off,
            "badges": badges,
        })

    # 5個篩選日後自動移除；最近才落榜的排前面
    alerts = [a for a in alerts if a["days_off"] < 5]
    alerts.sort(key=lambda x: x["days_off"])
    return alerts


@router.get("/api/holders")
async def get_holders(db: AsyncSession = Depends(get_db)):
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
            "pct_400_lot": sh.pct_400_lot,
            "prev_holders": prev.holders_1000_lot if prev else None,
            "prev_pct": prev.pct_1000_lot if prev else None,
            "holders_chg": (sh.holders_1000_lot - prev.holders_1000_lot) if prev else None,
            "pct_chg": round(sh.pct_1000_lot - prev.pct_1000_lot, 2) if prev else None,
        })

    result.sort(key=lambda x: x["pct_chg"] if x["pct_chg"] is not None else -999, reverse=True)
    return result


@router.get("/api/ai-pick")
async def get_ai_pick(db: AsyncSession = Depends(get_db)):
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
        # fallback: 最新的 ai_pick 不論日期
        row = (await db.execute(
            select(AIPick).order_by(AIPick.calc_date.desc()).limit(1)
        )).scalar_one_or_none()
    if not row:
        return {"calc_date": None, "code": None, "name": None, "reason": None}
    return {
        "calc_date": str(row.calc_date),
        "code": row.code,
        "name": row.name,
        "reason": row.reason,
    }


class PoolAddBody(BaseModel):
    code: str
    name: str = ""


@router.get("/api/pool")
async def get_pool(db: AsyncSession = Depends(get_db)):
    """目前股票池清單"""
    rows = (await db.execute(
        select(StockPool).order_by(StockPool.code)
    )).scalars().all()
    return [
        {"code": r.code, "name": r.name, "added_at": str(r.added_at)[:10]}
        for r in rows
    ]


async def _trigger_fubon_pool_sync():
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            await client.post("http://host.docker.internal:8090/sync-pool", timeout=10)
    except Exception:
        pass


@router.post("/api/pool")
async def add_to_pool(body: PoolAddBody, db: AsyncSession = Depends(get_db)):
    """加入股票到池"""
    import asyncio, re
    code = body.code.strip()
    # 拒絕代碼含中文或代碼==名稱（防止髒資料）
    if re.search(r'[一-鿿]', code):
        raise HTTPException(status_code=400, detail=f"代碼不可含中文：{code}，請用正確股票代碼")
    if code == body.name.strip() and body.name.strip():
        raise HTTPException(status_code=400, detail=f"代碼與名稱相同（{code}），請先查詢取得正確名稱")
    exists = (await db.execute(
        select(StockPool).where(StockPool.code == code)
    )).scalar_one_or_none()
    if exists:
        return {"ok": True, "already": True}
    name = body.name.strip()
    if not name or name == code:
        sl = (await db.execute(
            select(StockList).where(StockList.code == code)
        )).scalar_one_or_none()
        name = sl.name if sl else ""
    if not name:
        raise HTTPException(status_code=400, detail=f"找不到代碼 {code} 的名稱，請先透過搜尋確認")
    db.add(StockPool(code=code, name=name))
    await db.commit()
    from app.services.scheduler import backfill_financials_for_codes
    asyncio.create_task(backfill_financials_for_codes([code]))
    asyncio.create_task(_trigger_fubon_pool_sync())
    return {"ok": True, "code": code, "name": name}


@router.delete("/api/pool/{code}")
async def remove_from_pool(code: str, db: AsyncSession = Depends(get_db)):
    """從池移除股票"""
    row = (await db.execute(
        select(StockPool).where(StockPool.code == code)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not in pool")
    await db.delete(row)
    await db.commit()
    asyncio.create_task(_trigger_fubon_pool_sync())
    return {"ok": True}


@router.post("/api/admin/sync-fubon-pool")
async def sync_fubon_pool():
    """手動觸發 PG pool → SQLite watchlist 同步"""
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post("http://host.docker.internal:8090/sync-pool", timeout=15)
            return r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/api/stocks/latest-prices")
async def get_latest_prices(codes: str = Query(...), db: AsyncSession = Depends(get_db)):
    """批次取最新收盤價，codes=2330,2317,..."""
    from sqlalchemy import text as _text
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        return {}
    rows = (await db.execute(_text("""
        SELECT DISTINCT ON (code) code, close
        FROM daily_price
        WHERE code = ANY(:codes)
        ORDER BY code, trade_date DESC
    """), {"codes": code_list})).mappings().all()
    return {r["code"]: float(r["close"]) for r in rows}


# 全台股清單快取（FinMind TaiwanStockInfo，每 12 小時重刷）
_tw_stock_cache: list[dict] = []
_tw_stock_cache_ts: float = 0.0


async def _get_tw_stock_cache() -> list[dict]:
    import time, httpx
    from app.config import settings
    global _tw_stock_cache, _tw_stock_cache_ts
    if _tw_stock_cache and (time.time() - _tw_stock_cache_ts) < 43200:
        return _tw_stock_cache
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://api.finmindtrade.com/api/v4/data",
                params={
                    "dataset": "TaiwanStockInfo",
                    **({"token": settings.finmind_token} if settings.finmind_token else {}),
                }
            )
        data = resp.json().get("data", [])
        _tw_stock_cache = [
            {
                "code": d.get("stock_id", ""),
                "name": d.get("stock_name", ""),
                "sector": d.get("industry_category", ""),
            }
            for d in data if d.get("stock_id", "").strip()
        ]
        _tw_stock_cache_ts = time.time()
    except Exception:
        pass
    return _tw_stock_cache


@router.get("/api/stocks/search")
async def search_stocks(q: str = Query(""), db: AsyncSession = Depends(get_db)):
    """搜尋股票（代碼或名稱），回傳 in_pool 旗標"""
    import re
    q = q.strip()
    if not q:
        return []
    pool_codes = {r[0] for r in (await db.execute(select(StockPool.code))).all()}
    rows = (await db.execute(
        select(StockList).where(
            StockList.code.ilike(f"%{q}%") | StockList.name.ilike(f"%{q}%")
        ).limit(20)
    )).scalars().all()
    results = [{"code": r.code, "name": r.name, "sector": r.sector, "in_pool": r.code in pool_codes} for r in rows]

    if not results:
        # 從全台股快取搜尋（代碼精確 or 名稱模糊）
        all_stocks = await _get_tw_stock_cache()
        q_lower = q.lower()
        matched = [
            s for s in all_stocks
            if q_lower in s["code"].lower() or q_lower in s["name"]
        ][:20]
        results = [
            {**s, "in_pool": s["code"] in pool_codes}
            for s in matched
        ]
    return results


@router.post("/api/admin/trim_to_pool")
async def trim_to_pool(db: AsyncSession = Depends(get_db)):
    """刪除非股票池的所有歷史資料（不可逆）"""
    from sqlalchemy import text
    pool_codes = [r.code for r in (await db.execute(select(StockPool.code))).all()]
    if not pool_codes:
        return {"error": "pool is empty"}
    placeholders = ",".join(f"'{c}'" for c in pool_codes)
    tables = [
        "daily_price", "institutional", "margin_trading", "shareholding",
        "securities_lending", "screening_result", "company_tags",
        "monthly_revenue", "quarterly_eps", "ic_classification",
    ]
    deleted = {}
    async with engine.begin() as conn:
        for tbl in tables:
            result = await conn.execute(text(
                f"DELETE FROM {tbl} WHERE code NOT IN ({placeholders})"
            ))
            deleted[tbl] = result.rowcount
        result = await conn.execute(text(
            f"DELETE FROM stock_list WHERE code NOT IN ({placeholders})"
        ))
        deleted["stock_list"] = result.rowcount
    return {"deleted": deleted}


@router.post("/api/admin/refresh_stock_list")
async def trigger_refresh_stock_list():
    from app.services.scheduler import refresh_stock_list
    asyncio.create_task(refresh_stock_list())
    return {"status": "triggered"}


@router.post("/api/admin/refresh_ic_chain")
async def trigger_ic_chain_refresh():
    import asyncio
    from app.services.scheduler import job7_ic_chain
    asyncio.create_task(job7_ic_chain())
    return {"status": "triggered"}


@router.get("/api/admin/screener_debug")
async def screener_debug(target_date: str | None = None, db: AsyncSession = Depends(get_db)):
    """逐關卡統計篩選結果，診斷哪個條件砍最多股票"""
    from app.services.scheduler import _get_price_series, _get_chip_summary
    from app.services.screener import check_entry_criteria, is_early_breakout
    from app.db.models import StockList
    from datetime import date as _date
    import numpy as np

    td = _date.fromisoformat(target_date) if target_date else _date.today()
    stocks = (await db.execute(select(StockList))).scalars().all()

    total = len(stocks)
    no_data = 0
    fail_trend = 0
    fail_A_breakout = 0
    fail_A_chip = 0
    fail_B_bb = 0
    fail_B_breakout = 0
    fail_B_chip = 0
    pass_A = 0
    pass_B = 0

    for stock in stocks:
        opens, highs, lows, closes, volumes, _ = await _get_price_series(stock.code, price_date=td)
        if len(closes) < 65:
            no_data += 1
            continue
        entry = check_entry_criteria(opens, highs, lows, closes, volumes)
        if not entry["trend_ok"]:
            fail_trend += 1
            continue
        if entry["passes_A"]:
            chip = await _get_chip_summary(stock.code, td, stock.capital or 1)
            a_chip_ok = (
                (chip.get("chip_ratio_1d", 0) > 1.0 and chip.get("chip_ratio_12d", 0) > 0)
                or (chip.get("chip_ratio_1d", 0) > 0 and chip.get("chip_ratio_12d", 0) > 1.0)
            )
            if a_chip_ok:
                pass_A += 1
            else:
                fail_A_chip += 1
        else:
            fail_A_breakout += 1

        if entry["passes_B_price"]:
            chip = await _get_chip_summary(stock.code, td, stock.capital or 1)
            b_chip_ok = (
                chip.get("chip_ratio_6d", 0) >= 1.0
                and chip.get("chip_ratio_12d", 0) >= 1.0
            )
            if b_chip_ok:
                pass_B += 1
            else:
                fail_B_chip += 1
        else:
            fail_B_bb += 1

    return {
        "date": str(td),
        "total_stocks": total,
        "no_data_lt65": no_data,
        "fail_trend_ok": fail_trend,
        "trend_ok_stocks": total - no_data - fail_trend,
        "fail_A_no_breakout": fail_A_breakout,
        "fail_A_chip": fail_A_chip,
        "pass_A": pass_A,
        "fail_B_bb_too_high": fail_B_bb,
        "fail_B_chip": fail_B_chip,
        "pass_B": pass_B,
    }


@router.post("/api/admin/run_institutional")
async def trigger_institutional():
    import asyncio
    from app.services.scheduler import job1_institutional_price
    asyncio.create_task(job1_institutional_price())
    return {"status": "triggered"}


@router.post("/api/admin/backfill_price_range")
async def trigger_backfill_price_range(start_date: str, end_date: str):
    """補抓指定日期區間的法人+股價+融資（pool 所有股票）"""
    import asyncio, logging
    from datetime import date as _date, timedelta
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.fetcher.twse import fetch_daily_price, fetch_institutional, fetch_margin
    from app.db.models import DailyPrice, Institutional, MarginTrading, StockPool
    _logger = logging.getLogger(__name__)

    async def _run():
        from app.db.base import AsyncSessionLocal as _ASL
        async with _ASL() as db:
            pool_codes = {r.code for r in (await db.execute(select(StockPool))).scalars().all()}

        d = _date.fromisoformat(start_date)
        end = _date.fromisoformat(end_date)
        ok_count = 0
        while d <= end:
            if d.weekday() < 5:
                try:
                    price_rows = await fetch_daily_price(d)
                    inst_rows  = await fetch_institutional(d)
                    margin_rows = await fetch_margin(d)
                    price_rows  = [r for r in price_rows  if r["code"] in pool_codes]
                    inst_rows   = [r for r in inst_rows   if r["code"] in pool_codes]
                    margin_rows = [r for r in margin_rows if r["code"] in pool_codes]
                    async with _ASL() as db:
                        if price_rows:
                            stmt = pg_insert(DailyPrice).values(price_rows)
                            await db.execute(stmt.on_conflict_do_update(
                                index_elements=["code", "trade_date"],
                                set_={"open": stmt.excluded.open, "high": stmt.excluded.high,
                                      "low": stmt.excluded.low, "close": stmt.excluded.close,
                                      "volume": stmt.excluded.volume},
                            ))
                        if inst_rows:
                            await db.execute(pg_insert(Institutional).values(inst_rows).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                        if margin_rows:
                            await db.execute(pg_insert(MarginTrading).values(margin_rows).on_conflict_do_nothing(index_elements=["code", "trade_date"]))
                        await db.commit()
                    _logger.info(f"backfill {d}: price={len(price_rows)} inst={len(inst_rows)} margin={len(margin_rows)}")
                    ok_count += 1
                except Exception as e:
                    _logger.warning(f"backfill {d} failed: {e}")
            d += timedelta(days=1)
        _logger.info(f"backfill_price_range done: {ok_count} days")

    asyncio.create_task(_run())
    return {"status": "triggered", "start": start_date, "end": end_date}


@router.post("/api/admin/run_screener")
async def trigger_screener(force: bool = False, target_date: str | None = None):
    from app.services.scheduler import job4_screener
    from datetime import date as _date
    td = _date.fromisoformat(target_date) if target_date else None
    asyncio.create_task(job4_screener(force=force, target_date=td))
    return {"status": "triggered", "target_date": target_date or "auto"}


@router.post("/api/admin/run_daytrade_screener")
async def trigger_daytrade_screener():
    import asyncio
    from app.services.scheduler import job8_daytrade_screener
    asyncio.create_task(job8_daytrade_screener())
    return {"status": "triggered"}


@router.post("/api/admin/run_revenue")
async def trigger_revenue(force: bool = True):
    import asyncio
    from app.services.scheduler import job5_monthly_revenue
    asyncio.create_task(job5_monthly_revenue(force=force))
    return {"status": "triggered"}


@router.post("/api/admin/run_ai_pick")
async def trigger_ai_pick(db: AsyncSession = Depends(get_db)):
    import asyncio
    from app.services.scheduler import _run_ai_pick
    from app.db.models import ScreeningResult
    latest_date = (await db.execute(
        select(ScreeningResult.calc_date).order_by(ScreeningResult.calc_date.desc()).limit(1)
    )).scalar_one_or_none()
    if not latest_date:
        raise HTTPException(status_code=404, detail="no screening results in DB")
    results = (await db.execute(
        select(ScreeningResult)
        .where(ScreeningResult.calc_date == latest_date)
        .order_by(ScreeningResult.score_b.desc())
    )).scalars().all()
    asyncio.create_task(_run_ai_pick(latest_date, results))
    return {"status": "triggered", "date": str(latest_date), "stocks": len(results)}


@router.post("/api/admin/run_monthly_revenue")
async def trigger_monthly_revenue():
    import asyncio
    from app.services.scheduler import job5_monthly_revenue
    asyncio.create_task(job5_monthly_revenue())
    return {"status": "triggered"}


@router.post("/api/admin/backfill_revenue")
async def trigger_backfill_revenue(start_date: str = "2023-01-01"):
    import asyncio
    from app.services.scheduler import backfill_revenue_history
    asyncio.create_task(backfill_revenue_history(start_date))
    return {"status": "triggered", "start_date": start_date}


@router.post("/api/admin/run_quarterly_eps")
async def trigger_quarterly_eps(force: bool = True):
    """Job6 — FinMind TaiwanStockFinancialStatements 季報EPS"""
    import asyncio
    from app.services.scheduler import job6_quarterly_eps
    asyncio.create_task(job6_quarterly_eps(force=force))
    return {"status": "triggered"}


@router.post("/api/admin/run_eps")
async def trigger_eps(force: bool = True):
    import asyncio
    from app.services.scheduler import job6_quarterly_eps
    asyncio.create_task(job6_quarterly_eps(force=force))
    return {"status": "triggered"}


@router.get("/api/pool/financials-status")
async def get_pool_financials_status(db: AsyncSession = Depends(get_db)):
    """回傳每個 pool 股票是否有月營收 / 季報EPS 資料，及最新更新時間"""
    from sqlalchemy import func as sqlfunc
    pool_rows = (await db.execute(select(StockPool).order_by(StockPool.code))).scalars().all()
    codes = [r.code for r in pool_rows]
    if not codes:
        return []

    rev_q = await db.execute(
        select(MonthlyRevenue.code, sqlfunc.max(MonthlyRevenue.updated_at).label("updated_at"))
        .where(MonthlyRevenue.code.in_(codes))
        .group_by(MonthlyRevenue.code)
    )
    rev_map = {r[0]: r[1] for r in rev_q.all()}

    eps_q = await db.execute(
        select(QuarterlyEps.code, sqlfunc.max(QuarterlyEps.updated_at).label("updated_at"))
        .where(QuarterlyEps.code.in_(codes))
        .group_by(QuarterlyEps.code)
    )
    eps_map = {r[0]: r[1] for r in eps_q.all()}

    def _fmt(dt):
        if dt is None:
            return None
        from zoneinfo import ZoneInfo
        taipei = dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Taipei"))
        return taipei.strftime("%m/%d %H:%M")

    name_map = {r.code: r.name for r in pool_rows}
    return [
        {
            "code": c,
            "name": name_map.get(c, ""),
            "has_revenue": c in rev_map,
            "has_eps": c in eps_map,
            "revenue_updated_at": _fmt(rev_map.get(c)),
            "eps_updated_at": _fmt(eps_map.get(c)),
        }
        for c in codes
    ]


@router.post("/api/pool/backfill-missing")
async def backfill_missing_financials(db: AsyncSession = Depends(get_db)):
    """只補抓月營收或季EPS缺失的 pool 股票"""
    import asyncio
    from app.services.scheduler import backfill_financials_for_codes

    pool_rows = (await db.execute(select(StockPool).order_by(StockPool.code))).scalars().all()
    codes = [r.code for r in pool_rows]
    if not codes:
        return {"status": "skipped", "reason": "pool is empty"}

    rev_q = await db.execute(
        select(MonthlyRevenue.code).where(MonthlyRevenue.code.in_(codes)).distinct()
    )
    has_rev = {r[0] for r in rev_q.all()}

    eps_q = await db.execute(
        select(QuarterlyEps.code).where(QuarterlyEps.code.in_(codes)).distinct()
    )
    has_eps = {r[0] for r in eps_q.all()}

    missing = [c for c in codes if c not in has_rev or c not in has_eps]
    if not missing:
        return {"status": "ok", "missing": 0}

    asyncio.create_task(backfill_financials_for_codes(missing))
    return {"status": "triggered", "missing": len(missing), "codes": missing}


@router.post("/api/admin/backfill_pool_financials")
async def trigger_backfill_pool_financials(
    start_date: str = "2023-01-01",
    db: AsyncSession = Depends(get_db),
):
    """補抓所有 pool 股票的月營收 + 季報EPS（FinMind，背景執行）"""
    import asyncio
    from app.services.scheduler import backfill_financials_for_codes
    codes = [r.code for r in (await db.execute(select(StockPool))).scalars().all()]
    if not codes:
        return {"status": "skipped", "reason": "pool is empty"}
    asyncio.create_task(backfill_financials_for_codes(codes, start_date))
    return {"status": "triggered", "codes": len(codes), "start_date": start_date}


@router.post("/api/admin/backfill_screener_range")
async def backfill_screener_range(start: str, end: str | None = None, db: AsyncSession = Depends(get_db)):
    """逐日補算篩選結果，從 start 到 end（預設今天），各天用各天的資料"""
    from app.services.scheduler import job4_screener
    from datetime import date as _date
    start_d = _date.fromisoformat(start)
    end_d = _date.fromisoformat(end) if end else _date.today()

    results = []
    d = start_d
    while d <= end_d:
        if d.weekday() < 5:
            await job4_screener(force=True, target_date=d)
            results.append(str(d))
        d += timedelta(days=1)
    return {"backfilled_dates": results}


@router.post("/api/admin/backfill_shareholding")
async def backfill_shareholding(weeks: int = 4, db: AsyncSession = Depends(get_db)):
    """用 FinMind TaiwanStockShareholding 補抓歷史千張大戶資料（每支股票一次 API call）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from app.services.fetcher.finmind import fetch_shareholding
    from app.db.models import StockPool, Shareholding
    import asyncio

    codes = [r[0] for r in (await db.execute(select(StockPool.code))).all()]
    success, failed, inserted = 0, [], 0
    for code in codes:
        try:
            rows = await fetch_shareholding(code, weeks=weeks)
            if rows:
                async with AsyncSessionLocal() as s:
                    stmt = pg_insert(Shareholding).values(rows)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code", "report_date"],
                        set_={
                            "holders_1000_lot": stmt.excluded.holders_1000_lot,
                            "pct_1000_lot": stmt.excluded.pct_1000_lot,
                        },
                    )
                    await s.execute(stmt)
                    await s.commit()
                inserted += len(rows)
                success += 1
            await asyncio.sleep(0.3)
        except Exception as e:
            failed.append(f"{code}:{e}")
    return {"ok": True, "stocks": len(codes), "success": success, "inserted": inserted, "failed": failed}


@router.post("/api/admin/backfill_day")
async def backfill_day(d: str):
    """補抓指定日期的法人+股價+融資（格式 YYYY-MM-DD）"""
    from app.services.scheduler import backfill_single_day
    from datetime import date as _date
    try:
        target = _date.fromisoformat(d)
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式錯誤，請用 YYYY-MM-DD")
    result = await backfill_single_day(target)
    return result


@router.post("/api/admin/backfill_missing_days")
async def backfill_missing_days(days: int = 14, db: AsyncSession = Depends(get_db)):
    """補抓最近 N 個交易日中 job1 缺失或失敗的資料"""
    from app.services.scheduler import backfill_single_day
    from datetime import date as _date
    today = _date.today()
    success_dates = set((await db.execute(
        select(FetchLog.fetch_date)
        .where(FetchLog.job_name == "job1", FetchLog.status == "success",
               FetchLog.fetch_date >= today - timedelta(days=days))
    )).scalars().all())

    missing = []
    for i in range(1, days + 1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        if d not in success_dates:
            missing.append(d)

    results = []
    for d in sorted(missing):
        r = await backfill_single_day(d)
        results.append({"date": str(d), **r})
    return {"missing_days": len(missing), "results": results}


# ── Daytrade (PG-backed, replaces SQLite daytrade_list) ─────────────────────

class DaytradeSyncBody(BaseModel):
    date: str
    codes: list[str]
    # {code: {ref_close, ref_close_date, avg_vol5_lot, chip_count, above_ma20}}
    snapshots: dict[str, dict] = {}


@router.get("/api/daytrade/dates")
async def get_daytrade_dates(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(DaytradeCandidate.trade_date, func.count(DaytradeCandidate.code).label("cnt"))
        .group_by(DaytradeCandidate.trade_date)
        .order_by(DaytradeCandidate.trade_date.desc())
        .limit(30)
    )).all()
    return [{"date": r[0].isoformat(), "count": r[1]} for r in rows]


@router.get("/api/daytrade/list")
async def get_daytrade_list(
    db: AsyncSession = Depends(get_db),
    date_str: Optional[str] = Query(None),
    live: bool = Query(False),
    source: str = Query("candidates"),
):
    from sqlalchemy import text as _text
    if source == "pool":
        pool_rows = (await db.execute(select(StockPool.code, StockPool.name))).all()
        codes = [r.code for r in pool_rows]
        target_date = date.today()
        if not codes:
            return {"date": target_date.isoformat(), "count": 0, "stocks": []}
    else:
        if date_str:
            target_date = date.fromisoformat(date_str)
        else:
            target_date = (await db.execute(
                select(func.max(DaytradeCandidate.trade_date))
            )).scalar_one_or_none()
            if not target_date:
                return {"date": None, "count": 0, "stocks": []}

        snap_rows = (await db.execute(
            select(
                DaytradeCandidate.code,
                DaytradeCandidate.ref_close,
                DaytradeCandidate.ref_close_date,
                DaytradeCandidate.avg_vol5_lot,
                DaytradeCandidate.chip_count,
                DaytradeCandidate.above_ma20,
            ).where(DaytradeCandidate.trade_date == target_date)
        )).mappings().all()
        codes = [r["code"] for r in snap_rows]
        snap_map = {r["code"]: dict(r) for r in snap_rows}
        if not codes:
            return {"date": target_date.isoformat(), "count": 0, "stocks": []}

    if source == "pool":
        snap_map = {}
        pool_map = {r.code: r.name for r in pool_rows}
    else:
        pool_map = {r.code: r.name for r in (await db.execute(
            select(StockPool.code, StockPool.name).where(StockPool.code.in_(codes))
        )).all()}

    # Batch fetch latest prices (last 100 calendar days = 65+ trading days, for MA60)
    prices_raw = (await db.execute(_text("""
        SELECT code, trade_date, open, high, low, close, volume
        FROM daily_price
        WHERE code = ANY(:codes)
          AND trade_date >= (
            SELECT MAX(trade_date) - INTERVAL '100 days'
            FROM daily_price WHERE code = daily_price.code
          )
        ORDER BY code, trade_date DESC
    """), {"codes": list(codes)})).mappings().all()

    from collections import defaultdict
    price_by_code: dict[str, list] = defaultdict(list)
    for r in prices_raw:
        price_by_code[r["code"]].append(r)

    inst_raw = (await db.execute(_text("""
        SELECT DISTINCT ON (code) code, foreign_net, trust_net, dealer_net
        FROM institutional WHERE code = ANY(:codes)
        ORDER BY code, trade_date DESC
    """), {"codes": list(codes)})).mappings().all()
    inst_map = {r["code"]: r for r in inst_raw}

    margin_raw = (await db.execute(_text("""
        SELECT DISTINCT ON (code) code, margin_balance, margin_change, short_balance
        FROM margin_trading WHERE code = ANY(:codes)
        ORDER BY code, trade_date DESC
    """), {"codes": list(codes)})).mappings().all()
    margin_map = {r["code"]: r for r in margin_raw}

    result = []
    for code in codes:
        prices = price_by_code.get(code, [])
        inst = inst_map.get(code)
        margin = margin_map.get(code)
        snap = snap_map.get(code, {}) if snap_map else {}

        # daily_price.volume 單位為股(shares)，除以 1000 換算成張
        volume_shares = prices[0]["volume"] if prices else None
        volume = round(volume_shares / 1000) if volume_shares else None
        avg_vol5_shares = round(sum(p["volume"] for p in prices[:5]) / min(5, len(prices))) if prices else 0
        ma20 = sum(p["close"] for p in prices[:20]) / min(20, len(prices)) if prices else 0
        ma60 = sum(p["close"] for p in prices[:60]) / min(60, len(prices)) if prices else 0

        foreign_net = float(inst["foreign_net"]) if inst else 0
        trust_net = float(inst["trust_net"]) if inst else 0
        dealer_net = float(inst["dealer_net"]) if inst else 0
        margin_balance = int(margin["margin_balance"]) if margin else 0      # 單位：張(千股)
        margin_change = int(margin["margin_change"]) if margin else 0        # 單位：張(千股)
        # short_balance 來自 TWT93U 欄位，實際儲存為股；除以 1000 換算成張
        short_balance = round(int(margin["short_balance"]) / 1000) if margin else 0

        live_chip_count = (
            (1 if foreign_net > 0 else 0) +
            (1 if trust_net > 0 else 0) +
            (1 if margin_change < 0 else 0)
        )

        # Use stored screening snapshot if available; prevents display drift when daily_price updated after sync
        has_snap = snap.get("ref_close") is not None
        if has_snap:
            prev_close = float(snap["ref_close"])
            avg_vol5 = snap["avg_vol5_lot"] if snap.get("avg_vol5_lot") is not None else round(avg_vol5_shares / 1000)
            chip_count = snap["chip_count"] if snap.get("chip_count") is not None else live_chip_count
            above_ma20 = snap["above_ma20"] if snap.get("above_ma20") is not None else ((prev_close or 0) > ma60)
        else:
            prev_close = prices[0]["close"] if prices else None
            avg_vol5 = round(avg_vol5_shares / 1000)
            chip_count = live_chip_count
            above_ma20 = (prev_close or 0) > ma60

        vol_ok = avg_vol5 >= 2000  # 僅供前端顯示參考，不再作為 live filter 條件（引擎量比即時把關）
        prev_prev_close = prices[1]["close"] if len(prices) > 1 else prev_close
        change = round((prev_close or 0) - (prev_prev_close or prev_close or 0), 2)
        change_pct = round(change / prev_prev_close * 100, 2) if prev_prev_close else 0

        if live and not (above_ma20 and chip_count >= 2 and (foreign_net + trust_net) >= 0):
            continue

        result.append({
            "stock_id": code,
            "name": pool_map.get(code, code),
            "prev_close": prev_close,
            "prev_close_date": snap.get("ref_close_date").isoformat() if snap.get("ref_close_date") else (str(prices[0]["trade_date"]) if prices else None),
            "volume": volume,            # 張
            "prev_prev_close": prev_prev_close,
            "avg_vol5": avg_vol5,        # 張
            "ma20": round(ma20, 4),
            "ma60": round(ma60, 4),
            "foreign_net": foreign_net,
            "trust_net": trust_net,
            "dealer_net": dealer_net,
            "margin_balance": margin_balance,
            "margin_change": margin_change,
            "short_balance": short_balance,
            "change": change,
            "change_pct": change_pct,
            "above_ma20": above_ma20,  # 實際為 above_ma60（欄位名沿用相容性）
            "vol_ok": vol_ok,
            "chip_count": chip_count,
        })

    return {"date": target_date.isoformat(), "count": len(result), "stocks": result}


@router.post("/api/daytrade/sync")
async def sync_daytrade_candidates(body: DaytradeSyncBody, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import delete as _delete
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    trade_date = date.fromisoformat(body.date)
    await db.execute(_delete(DaytradeCandidate).where(DaytradeCandidate.trade_date == trade_date))
    if body.codes:
        rows = []
        for c in body.codes:
            snap = body.snapshots.get(c, {})
            row: dict = {"trade_date": trade_date, "code": c}
            if snap.get("ref_close") is not None:
                row["ref_close"] = snap["ref_close"]
                ref_d = snap.get("ref_close_date")
                row["ref_close_date"] = date.fromisoformat(ref_d) if ref_d else None
                row["avg_vol5_lot"] = snap.get("avg_vol5_lot")
                row["chip_count"] = snap.get("chip_count")
                row["above_ma20"] = snap.get("above_ma20")
            rows.append(row)
        await db.execute(
            pg_insert(DaytradeCandidate).values(rows).on_conflict_do_nothing()
        )
    await db.commit()
    return {"ok": True, "date": body.date, "count": len(body.codes)}


# ── Pre-session log (PG-backed) ──────────────────────────────────────────────

class PreSessionLogStartBody(BaseModel):
    run_date: str
    total_stocks: int = 0


class PreSessionLogFinishBody(BaseModel):
    finished_at: Optional[str] = None
    status: str = "ok"
    success_stocks: int = 0
    error_msg: Optional[str] = None


@router.post("/api/pre-session/log/start")
async def start_pre_session_log(body: PreSessionLogStartBody, db: AsyncSession = Depends(get_db)):
    log = DaytradePreSessionLog(
        run_date=date.fromisoformat(body.run_date),
        total_stocks=body.total_stocks,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return {"id": log.id}


@router.patch("/api/pre-session/log/{log_id}")
async def finish_pre_session_log(
    log_id: int,
    body: PreSessionLogFinishBody,
    db: AsyncSession = Depends(get_db),
):
    log = (await db.execute(
        select(DaytradePreSessionLog).where(DaytradePreSessionLog.id == log_id)
    )).scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="log not found")
    log.status = body.status
    log.success_stocks = body.success_stocks
    log.error_msg = body.error_msg
    log.finished_at = (
        datetime.fromisoformat(body.finished_at) if body.finished_at else datetime.utcnow()
    )
    await db.commit()
    return {"ok": True}


@router.get("/api/pre-session/logs")
async def get_pre_session_logs(db: AsyncSession = Depends(get_db)):
    from zoneinfo import ZoneInfo
    rows = (await db.execute(
        select(DaytradePreSessionLog)
        .order_by(DaytradePreSessionLog.id.desc())
        .limit(20)
    )).scalars().all()

    def _fmt_dt(dt):
        if dt is None:
            return None
        return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")

    return [
        {
            "id": r.id,
            "run_date": r.run_date.isoformat() if r.run_date else None,
            "started_at": _fmt_dt(r.started_at),
            "finished_at": _fmt_dt(r.finished_at),
            "status": r.status,
            "total_stocks": r.total_stocks,
            "success_stocks": r.success_stocks,
            "error_msg": r.error_msg,
        }
        for r in rows
    ]
