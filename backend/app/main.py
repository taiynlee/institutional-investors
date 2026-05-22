from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.services.scheduler import create_scheduler, backfill_90_days, backfill_shareholding_all, refresh_stock_list
from app.db.base import engine, Base


async def _apply_migrations():
    """手動補欄位（無 alembic 版本管理時用）"""
    from sqlalchemy import text
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE screening_result ADD COLUMN IF NOT EXISTS lending_5d_chg FLOAT DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE screening_result ADD COLUMN IF NOT EXISTS dip_bonus FLOAT DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE screening_result ADD COLUMN IF NOT EXISTS holders_bonus FLOAT DEFAULT 0"
        ))


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    import asyncio as _asyncio
    await _apply_migrations()
    if os.getenv("SKIP_STARTUP_SYNC", "").lower() not in ("1", "true"):
        await refresh_stock_list()
        await backfill_90_days()
    _asyncio.create_task(backfill_shareholding_all())
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
