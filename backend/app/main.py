import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.services.scheduler import (
    create_scheduler,
    backfill_90_days,
    backfill_shareholding_all,
    refresh_stock_list,
)
from app.db.base import engine, Base


_FUBON_POOL = [
    ("1303","南亞"), ("1503","士電"), ("1513","中興電"), ("1514","亞力"), ("1519","華城"),
    ("1802","台玻"), ("1815","富喬"), ("2049","上銀"), ("2301","光寶科"), ("2308","台達電"),
    ("2312","金寶"), ("2313","華通"), ("2317","鴻海"), ("2324","仁寶"), ("2327","國巨"),
    ("2329","華泰"), ("2330","台積電"), ("2337","旺宏"), ("2342","茂矽"), ("2344","華邦電"),
    ("2349","錸德"), ("2355","敬鵬"), ("2356","英業達"), ("2376","技嘉"), ("2382","廣達"),
    ("2395","研華"), ("2408","南亞科"), ("2421","建準"), ("2449","京元電子"), ("2455","全新"),
    ("2467","志聖"), ("2481","強茂"), ("2484","希華"), ("2485","兆赫"), ("2492","華新科"),
    ("3017","奇鋐"), ("3026","禾伸堂"), ("3034","聯詠"), ("3037","欣興"), ("3042","晶技"),
    ("3062","建漢"), ("3081","聯亞"), ("3105","穩懋"), ("3163","波若威"), ("3189","景碩"),
    ("3211","順達"), ("3231","緯創"), ("3260","威剛"), ("3324","雙鴻"), ("3363","上詮"),
    ("3450","聯鈞"), ("3481","群創"), ("3532","台勝科"), ("3550","聯穎"), ("3653","健策"),
    ("3665","貿聯-KY"), ("3706","神達"), ("3711","日月光投控"), ("4576","大銀微系統"),
    ("4919","新唐"), ("4927","泰鼎-KY"), ("4938","和碩"), ("4939","亞電"), ("4967","十銓"),
    ("4979","華星光"), ("5289","宜鼎"), ("5340","建榮"), ("5388","中磊"), ("5475","德宏"),
    ("6147","頎邦"), ("6173","信昌電"), ("6217","中探針"), ("6223","旺矽"), ("6239","力成"),
    ("6257","矽格"), ("6274","台燿"), ("6282","康舒"), ("6285","啟碁"), ("6426","統新"),
    ("6442","光聖"), ("6451","訊芯-KY"), ("6456","GIS-KY"), ("6515","穎崴"), ("6669","緯穎"),
    ("6683","雍智科技"), ("6691","洋基工程"), ("6770","力積電"), ("6805","富世達"),
    ("8021","尖點"), ("8027","鈦昇"), ("8046","南電"), ("8210","勤誠"), ("8299","群聯"),
]


async def _apply_migrations():
    from sqlalchemy import text
    async with engine.begin() as conn:
        # score → score_b rename
        await conn.execute(text("""
            DO $$ BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'screening_result' AND column_name = 'score'
              ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'screening_result' AND column_name = 'score_b'
              ) THEN
                ALTER TABLE screening_result RENAME COLUMN score TO score_b;
              END IF;
            END $$;
        """))
        adds = [
            ("screening_result", "score_a",       "FLOAT DEFAULT 0"),
            ("screening_result", "score_b",       "FLOAT DEFAULT 0"),
            ("screening_result", "chip_ratio_20d","FLOAT DEFAULT 0"),
            ("screening_result", "holders_w2",    "FLOAT"),
            ("screening_result", "holders_w3",    "FLOAT"),
            ("screening_result", "ma5_days",      "INTEGER DEFAULT 0"),
            ("screening_result", "upper_slope",   "FLOAT DEFAULT 0"),
            ("screening_result", "ma20_slope",    "FLOAT DEFAULT 0"),
            ("screening_result", "close_position","FLOAT DEFAULT 0"),
            ("screening_result", "change_pct",    "FLOAT DEFAULT 0"),
            ("screening_result", "lending_5d_chg","FLOAT DEFAULT 0"),
            ("screening_result", "dip_bonus",     "FLOAT DEFAULT 0"),
            ("screening_result", "holders_bonus", "FLOAT DEFAULT 0"),
            ("shareholding",     "pct_400_lot",   "FLOAT"),
        ]
        for table, col, col_type in adds:
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {col_type}"
            ))
        # seed stock_pool from fubon watchlist if empty
        count = (await conn.execute(text("SELECT COUNT(*) FROM stock_pool"))).scalar()
        if count == 0:
            from datetime import datetime as _dt
            now = _dt.utcnow()
            for code, name in _FUBON_POOL:
                await conn.execute(text(
                    "INSERT INTO stock_pool (code, name, added_at) VALUES (:c, :n, :t)"
                    " ON CONFLICT (code) DO NOTHING"
                ), {"c": code, "n": name, "t": now})

        # seed us_watchlist with default symbols if empty
        us_count = (await conn.execute(text("SELECT COUNT(*) FROM us_watchlist"))).scalar()
        if us_count == 0:
            _US_DEFAULT = [
                ("TSM",  "台積電ADR"), ("NVDA", "輝達"), ("LITE", "Lumentum"),
                ("AAOI", "Applied Opt"), ("MRVL", "Marvell"), ("SPCX", "SpaceX"),
                ("MU",   "美光"), ("WDC",  "威騰"), ("TSLA", "特斯拉"),
                ("GOOGL","Alphabet"), ("MSFT", "微軟"), ("AMZN", "亞馬遜"),
                ("AAPL", "蘋果"),
            ]
            from datetime import datetime as _dt
            now = _dt.utcnow()
            for sym, name in _US_DEFAULT:
                await conn.execute(text(
                    "INSERT INTO us_watchlist (symbol, name, added_at) VALUES (:s, :n, :t)"
                    " ON CONFLICT (symbol) DO NOTHING"
                ), {"s": sym, "n": name, "t": now})


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _apply_migrations()
    SKIP_STARTUP_SYNC = os.getenv("SKIP_STARTUP_SYNC", "").lower() in ("1", "true")
    if not SKIP_STARTUP_SYNC:
        await refresh_stock_list()
        await backfill_90_days()
    asyncio.create_task(backfill_shareholding_all())
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="股票主力篩選", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:6174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
