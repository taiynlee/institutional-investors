# Taiwan Stock Screener (主力未跑籌碼篩選) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- X`) syntax for tracking.

**Goal:** 篩選台股電子類股中「創60日新高後拉回但主力未出場」的標的，以布林位階量化拉回程度，結合三大法人/融資/持股集中度判斷籌碼狀態，並以 React dashboard 呈現。

**Architecture:** FastAPI + PostgreSQL (Docker) 後端，每日 4 排程自動抓取 TWSE/FinMind 資料，21:00 後執行篩選並更新 dashboard；前端以 Vite + React + TypeScript 呈現深色主題看板，支援電子子族群標籤過濾。

**資料範圍限制（重要）：**
- **只處理台股上市（TWSE）和上櫃（TPEx）電子類股**，共約 1055 檔
- TWSE T86、TWT93U 等 API 回傳全市場資料，**必須在寫入 DB 前過濾**，只保留 `stock_list` 中存在的代號
- 非電子股、興櫃、創新板、ETF 等一律不寫入，不佔 DB 空間
- `institutional` 和 `margin_trading` 欄位 `foreign_net`/`trust_net` 單位為**張**（TWSE T86 原始股數 ÷ 1000）

**Tech Stack:** Python 3.12 / uv / FastAPI / SQLAlchemy async + asyncpg / Alembic / APScheduler / Scrapling / React 18 / TypeScript / Vite / Recharts / Docker Compose (PostgreSQL 16)

---

## 檔案結構總覽

```
stock-main-force/
├── docker-compose.yml
├── config/
│   └── sector_tags.yaml          # 電子子族群標籤設定
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── main.py               # FastAPI app + lifespan
│   │   ├── config.py             # Settings (pydantic-settings)
│   │   ├── db/
│   │   │   ├── base.py           # SQLAlchemy engine + session
│   │   │   └── models.py         # ORM 模型
│   │   ├── services/
│   │   │   ├── fetcher/
│   │   │   │   ├── twse.py       # TWSE 三大法人 + 日成交 + 融資
│   │   │   │   ├── finmind.py    # FinMind 持股集中度
│   │   │   │   └── market.py     # yfinance ^TWII
│   │   │   ├── screener.py       # BB 計算 + 篩選邏輯
│   │   │   └── scheduler.py      # APScheduler 4 jobs
│   │   └── api/
│   │       ├── deps.py           # DB session 依賴
│   │       └── routes.py         # REST endpoints
│   └── tests/
│       ├── conftest.py
│       ├── test_screener.py
│       └── test_fetcher.py
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx
        ├── types/index.ts
        ├── hooks/
        │   └── useScreener.ts
        ├── components/
        │   ├── StockCard.tsx
        │   ├── BBGauge.tsx
        │   ├── ChipBar.tsx
        │   └── TagFilter.tsx
        └── pages/
            └── Dashboard.tsx
```

---

## Task 1: Docker + PostgreSQL 基礎設施

**Files:**
- Create: `docker-compose.yml`
- Create: `config/sector_tags.yaml`

- ○ **Step 1: 寫 docker-compose.yml**

```yaml
services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: stock_force
      POSTGRES_USER: stock
      POSTGRES_PASSWORD: secret
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U stock -d stock_force"]
      interval: 5s
      timeout: 5s
      retries: 10

  backend:
    build: ./backend
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://stock:secret@db:5432/stock_force
      FINMIND_TOKEN: ""
    volumes:
      - ../config:/app/config:ro

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend

volumes:
  pgdata:
```

- ○ **Step 2: 寫 sector_tags.yaml**

```yaml
# 每檔股票可掛多個標籤
# 格式: "代號": [tag1, tag2, ...]
# 未列出的電子股視為 "other"

tags:
  "2330": [晶圓代工, AI]
  "2454": [IC設計, AI]
  "3034": [IC設計, AI]
  "6770": [ABF載板]
  "3037": [ABF載板]
  "8046": [ABF載板]
  "3008": [光學]
  "2382": [伺服器, AI]
  "3231": [伺服器]
  "6669": [散熱]
  "3591": [散熱]
  "8081": [散熱]
  "3105": [砷化鎵]
  "2455": [砷化鎵]
  "3443": [CPO, 光通訊]
  "4977": [光通訊]
  "6239": [光通訊, CPO]
  "3035": [PCB]
  "2374": [PCB]
  "8046": [PCB, ABF載板]

# 族群標籤清單（供前端 TagFilter 使用）
all_tags:
  - 晶圓代工
  - IC設計
  - AI
  - ABF載板
  - PCB
  - 散熱
  - 光通訊
  - CPO
  - 伺服器
  - 砷化鎵
  - 光學
  - other
```

- ○ **Step 3: 驗證 PostgreSQL 啟動**

```bash
cd ~/stock-main-force
docker compose up db -d
docker compose exec db psql -U stock -d stock_force -c "SELECT version();"
```
Expected: PostgreSQL 16.x 版本字串

- ○ **Step 4: Commit**

```bash
git add docker-compose.yml config/sector_tags.yaml
git commit -m "feat: add Docker Compose with PostgreSQL and sector_tags config"
```

---

## Task 2: Backend 專案初始化 + DB Models

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/config.py`
- Create: `backend/app/db/base.py`
- Create: `backend/app/db/models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`

- ○ **Step 1: 初始化 uv 專案**

```bash
cd ~/stock-main-force/backend
~/.local/bin/uv init --name stock-force-backend --python 3.12
~/.local/bin/uv add fastapi uvicorn[standard] sqlalchemy[asyncio] asyncpg \
    alembic pydantic-settings apscheduler scrapling yfinance pandas numpy \
    httpx pyyaml
~/.local/bin/uv add --dev pytest pytest-asyncio httpx
```

- ○ **Step 2: 寫 config.py**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://stock:secret@localhost:5432/stock_force"
    finmind_token: str = ""
    config_path: str = "/app/config"

    class Config:
        env_file = ".env"

settings = Settings()
```

- ○ **Step 3: 寫 db/base.py**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
```

- ○ **Step 4: 寫 db/models.py**

```python
from datetime import date, datetime
from sqlalchemy import String, Integer, Float, Boolean, Date, DateTime, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class StockList(Base):
    __tablename__ = "stock_list"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(50))
    market: Mapped[str] = mapped_column(String(10))  # TWSE / TPEx
    sector: Mapped[str] = mapped_column(String(50))   # 電子工業 etc.
    tags: Mapped[str] = mapped_column(Text, default="")  # JSON list as text
    capital: Mapped[float] = mapped_column(Float, default=0)  # 股本（千股），用於法人買超比率正規化
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class DailyPrice(Base):
    __tablename__ = "daily_price"
    __table_args__ = (UniqueConstraint("code", "trade_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[int] = mapped_column(Integer)

class Institutional(Base):
    __tablename__ = "institutional"
    __table_args__ = (UniqueConstraint("code", "trade_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    foreign_net: Mapped[float] = mapped_column(Float, default=0)  # 外資淨買超 (股)
    trust_net: Mapped[float] = mapped_column(Float, default=0)    # 投信淨買超
    dealer_net: Mapped[float] = mapped_column(Float, default=0)   # 自營商淨買超
    three_major_net: Mapped[float] = mapped_column(Float, default=0)  # 三大法人合計

class MarginTrading(Base):
    __tablename__ = "margin_trading"
    __table_args__ = (UniqueConstraint("code", "trade_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    margin_balance: Mapped[int] = mapped_column(Integer, default=0)   # 融資餘額 (張)
    margin_change: Mapped[int] = mapped_column(Integer, default=0)    # 融資增減
    short_balance: Mapped[int] = mapped_column(Integer, default=0)    # 融券餘額
    short_change: Mapped[int] = mapped_column(Integer, default=0)     # 融券增減

class Shareholding(Base):
    __tablename__ = "shareholding"
    __table_args__ = (UniqueConstraint("code", "report_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)  # 週報日期
    holders_1000_lot: Mapped[int] = mapped_column(Integer, default=0)  # >1000張持有人數
    pct_1000_lot: Mapped[float] = mapped_column(Float, default=0)      # 佔比%

class ScreeningResult(Base):
    __tablename__ = "screening_result"
    __table_args__ = (UniqueConstraint("code", "calc_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(10), index=True)
    name: Mapped[str] = mapped_column(String(50))
    calc_date: Mapped[date] = mapped_column(Date, index=True)
    tags: Mapped[str] = mapped_column(Text, default="")
    # BB 指標
    bb_position: Mapped[float] = mapped_column(Float)      # 當前布林位階
    bb_peak: Mapped[float] = mapped_column(Float)          # 創高當日位階
    peak_date: Mapped[date] = mapped_column(Date, nullable=True)
    is_squeeze: Mapped[bool] = mapped_column(Boolean, default=False)
    # 成交量
    vol_ratio: Mapped[float] = mapped_column(Float)        # 近5日/前5日均量
    # 籌碼
    foreign_6d_net: Mapped[float] = mapped_column(Float, default=0)    # 外資6日淨買超（張）
    trust_6d_net: Mapped[float] = mapped_column(Float, default=0)     # 投信6日淨買超（張）
    chip_ratio_6d: Mapped[float] = mapped_column(Float, default=0)    # (外資+投信)6日買超/股本 %
    chip_ratio_12d: Mapped[float] = mapped_column(Float, default=0)   # (外資+投信)12日買超/股本 %
    margin_5d_chg: Mapped[float] = mapped_column(Float, default=0)    # 融資5日增減%
    holders_1000_chg: Mapped[float] = mapped_column(Float, default=0) # 大戶增減人數
    # RS
    rs_vs_market: Mapped[float] = mapped_column(Float, default=0)     # vs 大盤 BB 降幅
    # 綜合評分
    score: Mapped[float] = mapped_column(Float, default=0)
    passes: Mapped[bool] = mapped_column(Boolean, default=True)

class FetchLog(Base):
    __tablename__ = "fetch_log"
    __table_args__ = (UniqueConstraint("job_name", "fetch_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(50))
    fetch_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))  # success / failed / skipped
    rows_fetched: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- ○ **Step 5: 設定 Alembic**

```bash
cd ~/stock-main-force/backend
~/.local/bin/uv run alembic init alembic
```

編輯 `alembic/env.py`，在 `target_metadata` 前加入：
```python
from app.db.base import Base
from app.db import models  # noqa: F401  確保模型被載入
target_metadata = Base.metadata
```

在 `alembic.ini` 中設定：
```ini
sqlalchemy.url = postgresql+asyncpg://stock:secret@localhost:5432/stock_force
```

- ○ **Step 6: 產生並套用 migration**

```bash
cd ~/stock-main-force/backend
~/.local/bin/uv run alembic revision --autogenerate -m "initial schema"
~/.local/bin/uv run alembic upgrade head
```

Expected: 6 個 table 建立完成，`alembic_version` table 存在

- ○ **Step 7: Commit**

```bash
git add backend/
git commit -m "feat: backend project init with SQLAlchemy models and Alembic"
```

---

## Task 3: TWSE 資料抓取 (三大法人 + 日成交 + 融資)

**Files:**
- Create: `backend/app/services/fetcher/twse.py`
- Create: `backend/tests/test_fetcher.py` (TWSE 部分)

- ○ **Step 1: 寫失敗測試**

```python
# backend/tests/test_fetcher.py
import pytest
from datetime import date
from app.services.fetcher.twse import fetch_institutional, fetch_daily_price, fetch_margin

@pytest.mark.asyncio
async def test_fetch_institutional_returns_list():
    rows = await fetch_institutional(date(2025, 5, 16))
    assert isinstance(rows, list)
    assert len(rows) > 0
    first = rows[0]
    assert "code" in first
    assert "foreign_net" in first

@pytest.mark.asyncio
async def test_fetch_margin_returns_list():
    rows = await fetch_margin(date(2025, 5, 16))
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert "margin_balance" in rows[0]
```

- ○ **Step 2: 執行確認失敗**

```bash
cd ~/stock-main-force/backend
~/.local/bin/uv run pytest tests/test_fetcher.py -v
```

Expected: `ImportError` 或 `ModuleNotFoundError`

- ○ **Step 3: 實作 twse.py**

```python
import json
from datetime import date
from scrapling.fetchers import Fetcher

BASE_TWSE = "https://www.twse.com.tw/rwd/zh"

async def fetch_institutional(trade_date: date) -> list[dict]:
    """TWSE 三大法人 T86（全市場）"""
    date_str = trade_date.strftime("%Y%m%d")
    url = f"{BASE_TWSE}/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
    page = Fetcher.get(url, stealthy_headers=True)
    if page.status != 200:
        return []
    data = json.loads(page.text)
    if data.get("stat") != "OK":
        return []
    rows = []
    for r in data.get("data", []):
        # r: [代號, 名稱, 外資買, 外資賣, 外資淨, 投信買, 投信賣, 投信淨, 自營買, 自營賣, 自營淨, 三大合計]
        try:
            rows.append({
                "code": r[0].strip(),
                "trade_date": trade_date,
                "foreign_net": _parse_num(r[4]),
                "trust_net": _parse_num(r[7]),
                "dealer_net": _parse_num(r[10]),
                "three_major_net": _parse_num(r[11]),
            })
        except (IndexError, ValueError):
            continue
    return rows

async def fetch_daily_price(trade_date: date) -> list[dict]:
    """TWSE 個股日成交（MI_INDEX 全市場）"""
    date_str = trade_date.strftime("%Y%m%d")
    url = f"{BASE_TWSE}/afterTrading/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    page = Fetcher.get(url, stealthy_headers=True)
    if page.status != 200:
        return []
    data = json.loads(page.text)
    rows = []
    for table in data.get("tables", []):
        if "證券代號" not in str(table.get("fields", [])):
            continue
        fields = table.get("fields", [])
        for r in table.get("data", []):
            if len(r) < 9:
                continue
            try:
                rows.append({
                    "code": r[0].strip(),
                    "trade_date": trade_date,
                    "volume": int(r[2].replace(",", "")),
                    "open": float(r[5].replace(",", "")),
                    "high": float(r[6].replace(",", "")),
                    "low": float(r[7].replace(",", "")),
                    "close": float(r[8].replace(",", "")),
                })
            except (ValueError, IndexError):
                continue
    return rows

async def fetch_margin(trade_date: date) -> list[dict]:
    """TWSE 融資融券 TWT93U"""
    date_str = trade_date.strftime("%Y%m%d")
    url = f"{BASE_TWSE}/marginTrading/TWT93U?response=json&date={date_str}&selectType=ALL"
    page = Fetcher.get(url, stealthy_headers=True)
    if page.status != 200:
        return []
    data = json.loads(page.text)
    rows = []
    for r in data.get("data", []):
        try:
            rows.append({
                "code": r[0].strip(),
                "trade_date": trade_date,
                "margin_balance": _parse_int(r[6]),
                "margin_change": _parse_int(r[7]),
                "short_balance": _parse_int(r[12]),
                "short_change": _parse_int(r[13]),
            })
        except (IndexError, ValueError):
            continue
    return rows

def _parse_num(s: str) -> float:
    return float(s.replace(",", "").replace("+", ""))

def _parse_int(s: str) -> int:
    return int(s.replace(",", "").replace("+", ""))
```

- ○ **Step 4: 執行測試確認通過**

```bash
cd ~/stock-main-force/backend
~/.local/bin/uv run pytest tests/test_fetcher.py::test_fetch_institutional_returns_list -v
~/.local/bin/uv run pytest tests/test_fetcher.py::test_fetch_margin_returns_list -v
```

Expected: PASS，rows > 100

- ○ **Step 5: Commit**

```bash
git add backend/app/services/fetcher/twse.py backend/tests/test_fetcher.py
git commit -m "feat: TWSE institutional, daily price, margin fetchers"
```

---

## Task 4: FinMind 持股集中度 + 股本抓取

**Files:**
- Modify: `backend/app/services/fetcher/finmind.py`

- ○ **Step 1: 寫失敗測試（加到 test_fetcher.py）**

```python
@pytest.mark.asyncio
async def test_fetch_shareholding_returns_data():
    rows = await fetch_shareholding("2330", weeks=4)
    assert isinstance(rows, list)
    assert len(rows) > 0
    assert "holders_1000_lot" in rows[0]

@pytest.mark.asyncio
async def test_fetch_stock_capital_returns_float():
    capital = await fetch_stock_capital("2330")
    assert isinstance(capital, float)
    assert capital > 0  # 台積電股本 > 0
```

- ○ **Step 2: 執行確認失敗**

```bash
~/.local/bin/uv run pytest tests/test_fetcher.py::test_fetch_shareholding_returns_data -v
~/.local/bin/uv run pytest tests/test_fetcher.py::test_fetch_stock_capital_returns_float -v
```

- ○ **Step 3: 實作 finmind.py**

```python
import httpx
from datetime import date, timedelta
from app.config import settings

FINMIND_BASE = "https://api.finmindtrade.com/api/v4/data"

def _finmind_params(dataset: str, data_id: str, start_date: str) -> dict:
    params = {"dataset": dataset, "data_id": data_id, "start_date": start_date}
    if settings.finmind_token:
        params["token"] = settings.finmind_token
    return params

async def fetch_shareholding(code: str, weeks: int = 12) -> list[dict]:
    """FinMind TaiwanStockShareholding — 千張以上大戶持股"""
    start = (date.today() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(FINMIND_BASE, params=_finmind_params(
            "TaiwanStockShareholding", code, start
        ))
    if resp.status_code != 200:
        return []
    rows = []
    for r in resp.json().get("data", []):
        if r.get("HoldingSharesLevel") == "1,000張以上":
            rows.append({
                "code": code,
                "report_date": date.fromisoformat(r["date"]),
                "holders_1000_lot": int(r.get("people", 0)),
                "pct_1000_lot": float(r.get("holdingSharesPercent", 0)),
            })
    return rows

async def fetch_stock_capital(code: str) -> float:
    """
    FinMind TaiwanStockInfo — 取得股本（千股）
    capital 欄位單位為「千元」，需除以票面價（通常10元）得到股數千股
    實務上直接用 capital / 10 / 1000 = 張數（千張）
    回傳單位：張（方便與三大法人買賣超張數計算比率）
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={"dataset": "TaiwanStockInfo", "data_id": code,
                    **({"token": settings.finmind_token} if settings.finmind_token else {})}
        )
    if resp.status_code != 200:
        return 0.0
    data = resp.json().get("data", [])
    if not data:
        return 0.0
    # capital 欄位：股本（千元），÷10（票面）÷1000 = 千張
    capital_k_ntd = float(data[0].get("capital", 0))
    return capital_k_ntd / 10 / 1000  # 回傳：張數（千張 scale）
```

- ○ **Step 4: 執行測試確認通過**

```bash
~/.local/bin/uv run pytest tests/test_fetcher.py::test_fetch_shareholding_returns_data -v
~/.local/bin/uv run pytest tests/test_fetcher.py::test_fetch_stock_capital_returns_float -v
```

- ○ **Step 5: Commit**

```bash
git add backend/app/services/fetcher/finmind.py
git commit -m "feat: FinMind shareholding + stock capital fetcher"
```

---

## Task 5: 電子股清單 + sector_tags 載入

**Files:**
- Create: `backend/app/services/fetcher/stock_list.py`

- ○ **Step 1: 實作 stock_list.py**

```python
import json
import yaml
from pathlib import Path
from scrapling.fetchers import Fetcher
from app.config import settings

def load_sector_tags() -> dict[str, list[str]]:
    path = Path(settings.config_path) / "sector_tags.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("tags", {})

async def fetch_electronic_stocks() -> list[dict]:
    """從 TWSE BWIBBU_d 取得電子類股清單"""
    url = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json&selectType=EW"
    page = Fetcher.get(url, stealthy_headers=True)
    if page.status != 200:
        return []
    data = json.loads(page.text)
    tags_map = load_sector_tags()
    rows = []
    for r in data.get("data", []):
        code = r[0].strip()
        rows.append({
            "code": code,
            "name": r[1].strip(),
            "market": "TWSE",
            "sector": "電子工業",
            "tags": json.dumps(tags_map.get(code, []), ensure_ascii=False),
        })
    return rows
```

- ○ **Step 2: 測試清單抓取**

```bash
cd ~/stock-main-force/backend
~/.local/bin/uv run python -c "
import asyncio
from app.services.fetcher.stock_list import fetch_electronic_stocks
rows = asyncio.run(fetch_electronic_stocks())
print(f'電子股數量: {len(rows)}')
print(rows[:2])
"
```

Expected: 電子股數量 > 200

- ○ **Step 3: Commit**

```bash
git add backend/app/services/fetcher/stock_list.py
git commit -m "feat: electronic stock list fetcher with sector tags"
```

---

## Task 6: 市場指數 RS 基準

**Files:**
- Create: `backend/app/services/fetcher/market.py`

- X **Step 1: 實作 market.py**

```python
import numpy as np
import yfinance as yf

def fetch_twii_bb_stats() -> tuple[float, float]:
    """
    計算大盤 ^TWII 的 BB 位階資訊。
    回傳 (peak_bb_30d, current_bb)：
      peak_bb_30d — 近30日內 BB 位階最高值（用於計算大盤下滑幅度）
      current_bb  — 當前 BB 位階
    用於 RS 計算：market_bb_drop = peak_bb_30d - current_bb
    """
    df = yf.Ticker("^TWII").history(period="6mo", interval="1d")
    if df.empty or len(df) < 20:
        return 0.0, 0.0
    close = df["Close"].values
    ma20 = np.array([close[max(0,i-19):i+1].mean() for i in range(len(close))])
    std20 = np.array([close[max(0,i-19):i+1].std(ddof=0) + 1e-8 for i in range(len(close))])
    bb_pos = (close - ma20) / (2 * std20) * 10

    current_bb = float(bb_pos[-1])
    peak_bb_30d = float(bb_pos[-30:].max()) if len(bb_pos) >= 30 else float(bb_pos.max())
    return peak_bb_30d, current_bb
```

- X **Step 2: 快速驗證**

```bash
~/.local/bin/uv run python -c "
from app.services.fetcher.market import fetch_twii_bb_stats
peak, current = fetch_twii_bb_stats()
print(f'大盤 BB 位階: 近30日高點={peak:.2f}, 當前={current:.2f}, 降幅={peak-current:.2f}')
"
```

Expected: peak >= current，降幅 >= 0

- X **Step 3: Commit**

```bash
git add backend/app/services/fetcher/market.py
git commit -m "feat: market index BB position via yfinance"
```

---

## Task 7: 篩選引擎 (Screener)

**Files:**
- Create: `backend/app/services/screener.py`
- Create: `backend/tests/test_screener.py`

- X **Step 1: 寫失敗測試**

```python
# backend/tests/test_screener.py
import pytest
import numpy as np
from app.services.screener import (
    calc_bb_position, is_squeeze, check_entry_criteria,
    find_50d_high_event, check_breakout_candle
)

def make_ohlcv(n=80, trend="up_then_down"):
    """產生測試用 OHLCV 序列"""
    if trend == "up_then_down":
        closes = list(np.concatenate([np.linspace(100, 130, 50), np.linspace(130, 110, 30)]))
    else:
        closes = [100.0 + i * 0.1 for i in range(n)]
    opens  = [c * 0.995 for c in closes]   # 全紅K（收>開）
    highs  = [c * 1.005 for c in closes]
    lows   = [c * 0.990 for c in closes]
    vols   = [1000] * n
    # 突破日（第50天）出量
    vols[49] = 3000
    return opens, highs, lows, closes, vols

def test_calc_bb_position_at_ma20():
    closes = [100.0] * 60
    assert abs(calc_bb_position(closes)) < 0.5

def test_calc_bb_position_beyond_upper():
    # 位階可超過 10
    closes = [100.0] * 59 + [115.0]  # 遠超上軌
    pos = calc_bb_position(closes)
    assert pos > 10.0  # 不截斷

def test_is_squeeze_detects_contraction():
    closes = [100.0 + 0.01 * i for i in range(60)]
    assert is_squeeze(closes) is True

def test_find_50d_high_event_detects_breakout():
    opens, highs, lows, closes, vols = make_ohlcv()
    # 第50天是突破日（今日>=50日高，昨日<50日高）
    event = find_50d_high_event(closes, vols, lookback_event=25)
    assert event is not None
    bb_peak, days_ago = event
    assert bb_peak > 8
    assert days_ago <= 25

def test_find_50d_high_event_no_breakout():
    # 平穩下跌，無突破
    closes = list(np.linspace(130, 100, 80))
    vols = [1000] * 80
    assert find_50d_high_event(closes, vols) is None

def test_check_breakout_candle_pass():
    # 紅K + 出量 + 無長上影
    assert check_breakout_candle(
        open_=100, high=105, low=99, close=104,
        volume=3000, ma20_vol=1000
    ) is True

def test_check_breakout_candle_fail_long_shadow():
    # 長上影 (high-close)/(high-low) > 0.2
    assert check_breakout_candle(
        open_=100, high=110, low=99, close=101,
        volume=3000, ma20_vol=1000
    ) is False

def test_check_entry_criteria_pass():
    opens, highs, lows, closes, vols = make_ohlcv()
    result = check_entry_criteria(opens, highs, lows, closes, vols)
    assert result["passes"] is True
    assert -3 <= result["bb_position"] <= 5
    assert result["bb_peak"] > 8

def test_check_entry_criteria_fail_too_low():
    opens = [100.0] * 80
    closes = list(np.concatenate([np.linspace(100, 130, 50), np.linspace(130, 70, 30)]))
    highs = [c * 1.005 for c in closes]
    lows = [c * 0.99 for c in closes]
    vols = [1000] * 80
    vols[49] = 3000
    result = check_entry_criteria(opens, highs, lows, closes, vols)
    assert result["passes"] is False  # 跌破 -3
```

- X **Step 2: 執行確認失敗**

```bash
~/.local/bin/uv run pytest tests/test_screener.py -v
```

Expected: `ImportError` 或函式不存在

- X **Step 3: 實作 screener.py**

```python
import numpy as np
from datetime import date

def calc_bb_position(closes: list[float]) -> float:
    """
    布林位階 = (Close - MA20) / (2 × STD20) × 10
    可超出 ±10（超出布林帶時延伸計算，不截斷）
    """
    arr = np.array(closes, dtype=float)
    if len(arr) < 20:
        return 0.0
    ma20 = arr[-20:].mean()
    std20 = arr[-20:].std(ddof=0)  # 總體標準差（與布林帶標準定義一致）
    if std20 < 1e-8:
        return 0.0
    return float((arr[-1] - ma20) / (2 * std20) * 10)

def calc_bb_bandwidth(closes: list[float]) -> float:
    """帶寬率 = (上軌 - 下軌) / MA20"""
    arr = np.array(closes[-20:], dtype=float)
    if len(arr) < 20:
        return 0.0
    ma20 = arr.mean()
    std20 = arr.std(ddof=0)
    return float(4 * std20 / ma20) if ma20 > 0 else 0.0

def is_squeeze(closes: list[float]) -> bool:
    """盤整確認: 最近5日中 ≥3日帶寬 < 帶寬_MA20 × 0.85"""
    if len(closes) < 40:
        return False
    bws = []
    for i in range(len(closes) - 25, len(closes)):
        bws.append(calc_bb_bandwidth(closes[:i+1]))
    if len(bws) < 25:
        return False
    bw_ma20 = np.mean(bws[:20])
    recent_5 = bws[-5:]
    return sum(1 for bw in recent_5 if bw < bw_ma20 * 0.85) >= 3

def check_breakout_candle(
    open_: float, high: float, low: float, close: float,
    volume: int, ma20_vol: float
) -> bool:
    """
    驗證創高當日 K 棒形態：
    1. 紅K（收 > 開）
    2. 出量（成交量 > 20日均量 × 2，漲停除外）
    3. 上影線 < (高 - 低) × 0.2
    """
    if close <= open_:  # 非紅K
        return False
    is_limit_up = (high == close)  # 漲停鎖住，量不足也通過
    if not is_limit_up and volume < ma20_vol * 2:
        return False
    candle_range = high - low
    upper_shadow = high - close
    if candle_range > 0 and upper_shadow / candle_range > 0.2:
        return False
    return True

def find_50d_high_event(
    closes: list[float],
    volumes: list[int],
    opens: list[float] = None,
    highs: list[float] = None,
    lows: list[float] = None,
    lookback_event: int = 20,
) -> tuple[float, int] | None:
    """
    在最近 lookback_event 日內找符合條件的50日新高突破事件。
    條件：
      - 今日收盤 > 50日最高收盤 且 昨日收盤 < 50日最高收盤（突破當天）
      - 創高當日 check_breakout_candle 通過
      - 創高當日 BB 位階 > 8
    回傳 (bb_peak, days_ago) 或 None
    """
    n = len(closes)
    if n < 52:  # 至少需要 50日高 + 1日前 + 1日當天
        return None

    for days_ago in range(lookback_event):
        idx = n - 1 - days_ago
        if idx < 51:
            break

        today_close = closes[idx]
        yesterday_close = closes[idx - 1]
        # 50日最高收盤（不含當天）
        high_50d = max(closes[idx - 50: idx])

        if today_close < high_50d or yesterday_close >= high_50d:
            continue  # 不是突破當天

        # K 棒形態驗證
        if opens and highs and lows:
            ma20_vol = float(np.mean(volumes[max(0, idx-20): idx])) if idx >= 20 else 0
            if not check_breakout_candle(
                opens[idx], highs[idx], lows[idx], closes[idx],
                volumes[idx], ma20_vol
            ):
                continue

        # BB 位階驗證
        bb_peak = calc_bb_position(closes[:idx + 1])
        if bb_peak <= 8:
            continue

        return bb_peak, days_ago

    return None

def check_entry_criteria(
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[int],
) -> dict:
    """
    篩選條件:
    1. 近20日內有50日新高突破事件（出量+紅K+無長上影+BB位階>8）
    2. 當前 BB 位階 -3 ~ 5（拉回到月線附近）
    3. 趨勢保護：MA20 > MA60, MA60 斜率>0, 收盤>MA60
    """
    bb_now = calc_bb_position(closes)
    event = find_50d_high_event(closes, volumes, opens, highs, lows, lookback_event=20)
    squeeze = is_squeeze(closes)

    # 趨勢保護
    arr = np.array(closes, dtype=float)
    trend_ok = False
    if len(arr) >= 60:
        ma20 = arr[-20:].mean()
        ma60 = arr[-60:].mean()
        ma60_prev = arr[-61:-1].mean() if len(arr) >= 61 else ma60
        trend_ok = bool(ma20 > ma60 and ma60 > ma60_prev and arr[-1] > ma60)

    passes = (
        event is not None
        and -3 <= bb_now <= 5
        and trend_ok
    )

    bb_peak, peak_days_ago = event if event else (0.0, 0)
    return {
        "bb_position": round(bb_now, 2),
        "bb_peak": round(bb_peak, 2),
        "peak_days_ago": peak_days_ago,
        "is_squeeze": squeeze,
        "trend_ok": trend_ok,
        "passes": passes,
    }

def calc_vol_ratio(volumes: list[int]) -> float:
    """近5日均量 / 前5日均量"""
    if len(volumes) < 10:
        return 1.0
    recent = np.mean(volumes[-5:])
    prev = np.mean(volumes[-10:-5])
    return float(recent / prev) if prev > 0 else 1.0

def calc_chip_ratios(inst_rows: list, capital_lots: float) -> dict:
    """
    計算法人買超/股本比率（6日 + 12日）
    inst_rows: 從 DB 取出的 Institutional 記錄（按日期升序）
    capital_lots: 股本（張），來自 StockList.capital
    """
    if not inst_rows or capital_lots <= 0:
        return {"chip_ratio_6d": 0.0, "chip_ratio_12d": 0.0,
                "foreign_6d_net": 0.0, "trust_6d_net": 0.0}

    rows_6 = inst_rows[-6:]
    rows_12 = inst_rows[-12:]
    f6 = sum(r.foreign_net for r in rows_6)
    t6 = sum(r.trust_net for r in rows_6)
    f12 = sum(r.foreign_net for r in rows_12)
    t12 = sum(r.trust_net for r in rows_12)

    return {
        "foreign_6d_net": f6,
        "trust_6d_net": t6,
        "chip_ratio_6d": round((f6 + t6) / capital_lots * 100, 3),
        "chip_ratio_12d": round((f12 + t12) / capital_lots * 100, 3),
    }

def calc_score(result: dict, chip: dict, market_bb_drop: float) -> float:
    """
    綜合評分 (0~100)
    - BB 位階越靠近 0~2 分越高（25%）
    - 法人買超/股本（6日+12日各滿1%加分）（25%）
    - 量縮（拉回量比 < 0.5）（20%）
    - RS 優於大盤（15%）
    - 盤整突破加分（15%）
    """
    score = 50.0
    bb = result["bb_position"]

    # BB 位階（25%，最高 25 分）
    score += max(0, (5 - abs(bb - 1.5)) / 5 * 25)

    # 法人籌碼（25%）
    if chip.get("chip_ratio_6d", 0) >= 1.0:
        score += 12.5
    if chip.get("chip_ratio_12d", 0) >= 1.0:
        score += 12.5

    # 融資扣分（散戶追高）
    if chip.get("margin_5d_chg", 0) > 0.05:
        score -= 10

    # 大戶人數增加加分
    if chip.get("holders_1000_chg", 0) > 0:
        score += 5

    # 盤整加分（15%）
    if result.get("is_squeeze"):
        score += 15

    # RS（15%）：個股 BB 降幅 < 大盤降幅 × 1.2
    stock_bb_drop = result["bb_peak"] - result["bb_position"]
    if market_bb_drop > 0 and stock_bb_drop < market_bb_drop * 1.2:
        score += 15

    return round(min(100, max(0, score)), 1)
```

- X **Step 4: 執行測試確認通過**

```bash
~/.local/bin/uv run pytest tests/test_screener.py -v
```

Expected: 全部 5 個測試 PASS

- X **Step 5: Commit**

```bash
git add backend/app/services/screener.py backend/tests/test_screener.py
git commit -m "feat: BB position screener engine with entry criteria and scoring"
```

---

## Task 8: Scheduler (4 排程 + 90 日回填)

**Files:**
- Create: `backend/app/services/scheduler.py`

- X **Step 1: 實作 scheduler.py**

```python
import asyncio
import logging
from datetime import date, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, and_
from app.db.base import AsyncSessionLocal
from app.db.models import FetchLog, DailyPrice, Institutional, MarginTrading, Shareholding, ScreeningResult, StockList
from app.services.fetcher.twse import fetch_institutional, fetch_daily_price, fetch_margin
from app.services.fetcher.finmind import fetch_shareholding
from app.services.fetcher.market import fetch_twii_bb_position
from app.services.fetcher.stock_list import fetch_electronic_stocks
from app.services.screener import check_entry_criteria, calc_vol_ratio, calc_score
import json

logger = logging.getLogger(__name__)

async def _already_fetched(job_name: str, fetch_date: date) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(FetchLog).where(
                and_(FetchLog.job_name == job_name, FetchLog.fetch_date == fetch_date)
            )
        )
        return result.scalar_one_or_none() is not None

async def _log_fetch(job_name: str, fetch_date: date, status: str, rows: int = 0):
    async with AsyncSessionLocal() as db:
        db.add(FetchLog(job_name=job_name, fetch_date=fetch_date, status=status, rows_fetched=rows))
        await db.commit()

async def job1_institutional_price():
    """16:00 — 三大法人 + 日成交"""
    today = date.today()
    if await _already_fetched("job1", today):
        return
    try:
        rows = await fetch_institutional(today)
        price_rows = await fetch_daily_price(today)
        async with AsyncSessionLocal() as db:
            for r in rows:
                db.add(Institutional(**r))
            for r in price_rows:
                db.add(DailyPrice(**r))
            await db.commit()
        await _log_fetch("job1", today, "success", len(rows) + len(price_rows))
    except Exception as e:
        await _log_fetch("job1", today, "failed")
        logger.error(f"job1 failed: {e}")

async def job2_margin():
    """18:30 — 融資融券"""
    today = date.today()
    if await _already_fetched("job2", today):
        return
    try:
        rows = await fetch_margin(today)
        async with AsyncSessionLocal() as db:
            for r in rows:
                db.add(MarginTrading(**r))
            await db.commit()
        await _log_fetch("job2", today, "success", len(rows))
    except Exception as e:
        await _log_fetch("job2", today, "failed")
        logger.error(f"job2 failed: {e}")

async def job3_shareholding():
    """20:30 — FinMind 持股集中度（只在週五執行）"""
    today = date.today()
    if today.weekday() != 4:  # 0=Monday, 4=Friday
        return
    if await _already_fetched("job3", today):
        return
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(StockList.code))
            codes = [r[0] for r in result.fetchall()]
        total = 0
        for code in codes:
            rows = await fetch_shareholding(code, weeks=1)
            async with AsyncSessionLocal() as db:
                for r in rows:
                    db.add(Shareholding(**r))
                await db.commit()
            total += len(rows)
            await asyncio.sleep(0.5)
        await _log_fetch("job3", today, "success", total)
    except Exception as e:
        await _log_fetch("job3", today, "failed")
        logger.error(f"job3 failed: {e}")

async def job4_screener():
    """21:00 — 執行篩選，更新 screening_result"""
    today = date.today()
    if await _already_fetched("job4", today):
        return
    try:
        market_bb_peak, market_bb_now = fetch_twii_bb_stats()
        market_bb_drop = max(0, market_bb_peak - market_bb_now)
        async with AsyncSessionLocal() as db:
            stocks = (await db.execute(select(StockList))).scalars().all()
        results = []
        for stock in stocks:
            closes, volumes, opens, highs, lows = await _get_price_series(stock.code, days=90)
            if len(closes) < 55:  # 需要足夠歷史計算50日高+MA60
                continue
            entry = check_entry_criteria(opens, highs, lows, closes, volumes)
            if not entry["passes"]:
                continue
            chip = await _get_chip_summary(stock.code, today, stock.capital)
            vol_ratio = calc_vol_ratio(volumes)
            score = calc_score(entry, chip, market_bb_drop)
            results.append(ScreeningResult(
                code=stock.code,
                name=stock.name,
                calc_date=today,
                tags=stock.tags,
                bb_position=entry["bb_position"],
                bb_peak=entry["bb_peak"],
                is_squeeze=entry["is_squeeze"],
                vol_ratio=vol_ratio,
                score=score,
                passes=True,
                **chip,
            ))
        async with AsyncSessionLocal() as db:
            for r in results:
                db.add(r)
            await db.commit()
        await _log_fetch("job4", today, "success", len(results))
        logger.info(f"Screener found {len(results)} stocks")
    except Exception as e:
        await _log_fetch("job4", today, "failed")
        logger.error(f"job4 failed: {e}")

async def _get_price_series(code: str, days: int = 120) -> tuple[list, list, list, list, list]:
    """回傳 (opens, highs, lows, closes, volumes)，取更多天確保 MA60 + 50日高有效"""
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
    )

async def _get_chip_summary(code: str, today: date, capital_lots: float) -> dict:
    cutoff_12d = today - timedelta(days=17)  # 多抓幾天保證有12個交易日
    cutoff_5d = today - timedelta(days=7)
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
    from app.services.screener import calc_chip_ratios
    chip = calc_chip_ratios(list(inst), capital_lots)
    margin_chg = 0.0
    if len(margin) >= 2:
        old_bal = margin[0].margin_balance
        new_bal = margin[-1].margin_balance
        margin_chg = (new_bal - old_bal) / old_bal if old_bal > 0 else 0.0
    return {
        **chip,
        "margin_5d_chg": margin_chg,
        "holders_1000_chg": 0,  # 從 shareholding 補充
    }

async def backfill_90_days():
    """首次啟動時，補抓 90 日歷史"""
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(DailyPrice))).first()
    if count is not None:
        return  # 已有資料，不需回填
    logger.info("Starting 90-day backfill...")
    today = date.today()
    for i in range(90, -1, -1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:  # 跳過週末
            continue
        await job1_institutional_price.__wrapped__(d) if hasattr(job1_institutional_price, '__wrapped__') else None
        # 直接呼叫抓取函式
        rows_i = await fetch_institutional(d)
        price_rows = await fetch_daily_price(d)
        margin_rows = await fetch_margin(d)
        async with AsyncSessionLocal() as db:
            for r in rows_i:
                db.add(Institutional(**r))
            for r in price_rows:
                db.add(DailyPrice(**r))
            for r in margin_rows:
                db.add(MarginTrading(**r))
            await db.commit()
        await asyncio.sleep(1)
    logger.info("Backfill complete.")

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Taipei")
    scheduler.add_job(job1_institutional_price, "cron", hour=16, minute=5)
    scheduler.add_job(job2_margin, "cron", hour=18, minute=30)
    scheduler.add_job(job3_shareholding, "cron", hour=20, minute=30)
    scheduler.add_job(job4_screener, "cron", hour=21, minute=0)
    return scheduler
```

- X **Step 2: Commit**

```bash
git add backend/app/services/scheduler.py
git commit -m "feat: APScheduler with 4 daily jobs and 90-day backfill"
```

---

## Task 9: FastAPI Main App + API Routes

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/api/routes.py`
- Create: `backend/app/api/deps.py`

- X **Step 1: 實作 deps.py**

```python
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.base import AsyncSessionLocal

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

- X **Step 2: 實作 routes.py**

```python
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_db
from app.db.models import ScreeningResult, StockList, FetchLog
import json

router = APIRouter()

@router.get("/api/screener")
async def get_screener_results(
    db: AsyncSession = Depends(get_db),
    tags: Optional[str] = Query(None),  # 逗號分隔標籤
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
    from app.services.fetcher.stock_list import load_sector_tags
    from app.config import settings
    import yaml
    from pathlib import Path
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
        "foreign_5d_net": r.foreign_5d_net,
        "trust_5d_net": r.trust_5d_net,
        "margin_5d_chg": r.margin_5d_chg,
        "score": r.score,
    }
```

- X **Step 3: 實作 main.py**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.services.scheduler import create_scheduler, backfill_90_days
from app.db.base import engine, Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await backfill_90_days()
    scheduler = create_scheduler()
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="股票主力篩選", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

- X **Step 4: 測試 API 啟動**

```bash
cd ~/stock-main-force/backend
~/.local/bin/uv run uvicorn app.main:app --reload --port 8000
# 另一個 terminal:
curl http://localhost:8000/health
curl http://localhost:8000/api/status
```

Expected: `{"status": "ok"}` 和 jobs 列表

- X **Step 5: Commit**

```bash
git add backend/app/
git commit -m "feat: FastAPI app with screener routes and scheduler lifespan"
```

---

## Task 10: React Frontend — 初始化 + 型別

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`
- Create: `frontend/src/types/index.ts`

- X **Step 1: 初始化 Vite + React**

```bash
cd ~/stock-main-force
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install recharts axios
npm install -D tailwindcss @tailwindcss/vite
```

- X **Step 2: 設定 Tailwind (vite.config.ts)**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

- X **Step 3: 定義型別 (src/types/index.ts)**

```typescript
export interface ScreenerResult {
  code: string;
  name: string;
  calc_date: string;
  tags: string[];
  bb_position: number;
  bb_peak: number;
  is_squeeze: boolean;
  vol_ratio: number;
  foreign_5d_net: number;
  trust_5d_net: number;
  margin_5d_chg: number;
  score: number;
}

export interface DataStatus {
  date: string;
  jobs: { name: string; status: string; rows: number }[];
  is_reliable: boolean;
}
```

- X **Step 4: Commit**

```bash
git add frontend/
git commit -m "feat: React frontend init with Vite, Tailwind, types"
```

---

## Task 11: Frontend 元件

**Files:**
- Create: `frontend/src/hooks/useScreener.ts`
- Create: `frontend/src/components/BBGauge.tsx`
- Create: `frontend/src/components/StockCard.tsx`
- Create: `frontend/src/components/TagFilter.tsx`
- Create: `frontend/src/components/ChipBar.tsx`

- X **Step 1: 實作 useScreener hook**

```typescript
// frontend/src/hooks/useScreener.ts
import { useState, useEffect } from 'react';
import axios from 'axios';
import type { ScreenerResult, DataStatus } from '../types';

export function useScreener(tags: string[]) {
  const [results, setResults] = useState<ScreenerResult[]>([]);
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const tagParam = tags.length > 0 ? `?tags=${tags.join(',')}` : '';
    Promise.all([
      axios.get<ScreenerResult[]>(`/api/screener${tagParam}`),
      axios.get<DataStatus>('/api/status'),
    ]).then(([res, statusRes]) => {
      setResults(res.data);
      setStatus(statusRes.data);
    }).finally(() => setLoading(false));
  }, [tags.join(',')]);

  return { results, status, loading };
}
```

- X **Step 2: 實作 BBGauge.tsx**

```typescript
// frontend/src/components/BBGauge.tsx
interface BBGaugeProps {
  position: number;  // -10 到 +10
}

export function BBGauge({ position }: BBGaugeProps) {
  const pct = ((position + 10) / 20) * 100;
  const color = position > 5 ? '#22c55e' : position > 0 ? '#eab308' : position > -3 ? '#f97316' : '#ef4444';
  return (
    <div className="w-full">
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>-10</span><span>0</span><span>+10</span>
      </div>
      <div className="relative h-3 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
        <div className="absolute inset-y-0 left-1/2 w-px bg-gray-400" />
      </div>
      <div className="text-center text-sm font-bold mt-1" style={{ color }}>
        {position.toFixed(1)}
      </div>
    </div>
  );
}
```

- X **Step 3: 實作 ChipBar.tsx**

```typescript
// frontend/src/components/ChipBar.tsx
import type { ScreenerResult } from '../types';

interface ChipBarProps { stock: ScreenerResult; }

function ChipItem({ label, value, positive }: { label: string; value: string; positive: boolean }) {
  return (
    <div className="text-center">
      <div className={`text-xs font-medium ${positive ? 'text-green-400' : 'text-red-400'}`}>{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  );
}

export function ChipBar({ stock }: ChipBarProps) {
  const fmt = (n: number) => n > 0 ? `+${(n/1000).toFixed(0)}K` : `${(n/1000).toFixed(0)}K`;
  return (
    <div className="grid grid-cols-3 gap-2 mt-2 p-2 bg-gray-800 rounded">
      <ChipItem label="外資5日" value={fmt(stock.foreign_5d_net)} positive={stock.foreign_5d_net > 0} />
      <ChipItem label="投信5日" value={fmt(stock.trust_5d_net)} positive={stock.trust_5d_net > 0} />
      <ChipItem label="融資增減" value={`${(stock.margin_5d_chg * 100).toFixed(1)}%`} positive={stock.margin_5d_chg < 0} />
    </div>
  );
}
```

- X **Step 4: 實作 StockCard.tsx**

```typescript
// frontend/src/components/StockCard.tsx
import type { ScreenerResult } from '../types';
import { BBGauge } from './BBGauge';
import { ChipBar } from './ChipBar';

interface StockCardProps { stock: ScreenerResult; }

export function StockCard({ stock }: StockCardProps) {
  const scoreColor = stock.score >= 70 ? 'text-green-400' : stock.score >= 50 ? 'text-yellow-400' : 'text-gray-400';
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 hover:border-blue-500 transition-colors">
      <div className="flex justify-between items-start mb-3">
        <div>
          <span className="text-white font-bold text-lg">{stock.code}</span>
          <span className="text-gray-400 text-sm ml-2">{stock.name}</span>
        </div>
        <div className={`text-2xl font-black ${scoreColor}`}>{stock.score}</div>
      </div>
      <div className="flex flex-wrap gap-1 mb-3">
        {stock.tags.map(tag => (
          <span key={tag} className="px-2 py-0.5 bg-blue-900 text-blue-300 text-xs rounded-full">{tag}</span>
        ))}
        {stock.is_squeeze && (
          <span className="px-2 py-0.5 bg-purple-900 text-purple-300 text-xs rounded-full">盤整</span>
        )}
      </div>
      <BBGauge position={stock.bb_position} />
      <div className="text-xs text-gray-500 text-center mt-1">
        創高位階 {stock.bb_peak.toFixed(1)} | 量比 {stock.vol_ratio.toFixed(2)}
      </div>
      <ChipBar stock={stock} />
    </div>
  );
}
```

- X **Step 5: 實作 TagFilter.tsx**

```typescript
// frontend/src/components/TagFilter.tsx
interface TagFilterProps {
  allTags: string[];
  selected: string[];
  onChange: (tags: string[]) => void;
}

export function TagFilter({ allTags, selected, onChange }: TagFilterProps) {
  const toggle = (tag: string) => {
    onChange(selected.includes(tag) ? selected.filter(t => t !== tag) : [...selected, tag]);
  };
  return (
    <div className="flex flex-wrap gap-2 mb-6">
      <button
        onClick={() => onChange([])}
        className={`px-3 py-1 rounded-full text-sm ${selected.length === 0 ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400'}`}
      >全部</button>
      {allTags.map(tag => (
        <button
          key={tag}
          onClick={() => toggle(tag)}
          className={`px-3 py-1 rounded-full text-sm transition-colors ${
            selected.includes(tag) ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
          }`}
        >{tag}</button>
      ))}
    </div>
  );
}
```

- X **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: frontend components (BBGauge, StockCard, ChipBar, TagFilter)"
```

---

## Task 12: Dashboard 頁面 + App 整合

**Files:**
- Create: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/App.tsx`

- X **Step 1: 實作 Dashboard.tsx**

```typescript
// frontend/src/pages/Dashboard.tsx
import { useState, useEffect } from 'react';
import axios from 'axios';
import { useScreener } from '../hooks/useScreener';
import { StockCard } from '../components/StockCard';
import { TagFilter } from '../components/TagFilter';

export function Dashboard() {
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [allTags, setAllTags] = useState<string[]>([]);
  const { results, status, loading } = useScreener(selectedTags);

  useEffect(() => {
    axios.get<{ tags: string[] }>('/api/tags').then(r => setAllTags(r.data.tags));
  }, []);

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-black text-white">台股電子股主力篩選</h1>
            <p className="text-gray-400 text-sm">創高後拉回、主力未出場</p>
          </div>
          <div className="text-right">
            <div className={`text-sm font-medium ${status?.is_reliable ? 'text-green-400' : 'text-yellow-400'}`}>
              {status?.is_reliable ? '資料完整' : '資料更新中'}
            </div>
            <div className="text-xs text-gray-500">{status?.date} 21:00 後可信</div>
          </div>
        </div>

        {/* Status Bar */}
        {status && (
          <div className="flex gap-4 mb-6 p-3 bg-gray-900 rounded-lg">
            {status.jobs.map(job => (
              <div key={job.name} className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-full ${job.status === 'success' ? 'bg-green-400' : 'bg-gray-600'}`} />
                <span className="text-xs text-gray-400">{job.name}</span>
              </div>
            ))}
            <span className="text-xs text-gray-500 ml-auto">篩出 {results.length} 檔</span>
          </div>
        )}

        {/* Tag Filter */}
        <TagFilter allTags={allTags} selected={selectedTags} onChange={setSelectedTags} />

        {/* Results Grid */}
        {loading ? (
          <div className="text-center text-gray-500 py-20">載入中...</div>
        ) : results.length === 0 ? (
          <div className="text-center text-gray-500 py-20">目前無符合條件的股票</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {results.map(stock => <StockCard key={stock.code} stock={stock} />)}
          </div>
        )}
      </div>
    </div>
  );
}
```

- X **Step 2: 修改 App.tsx**

```typescript
import { Dashboard } from './pages/Dashboard';
import './index.css';

export default function App() {
  return <Dashboard />;
}
```

- X **Step 3: 在 index.css 確認 Tailwind**

```css
@import "tailwindcss";
```

- X **Step 4: 啟動並驗證**

```bash
# Terminal 1: 後端
cd ~/stock-main-force/backend && ~/.local/bin/uv run uvicorn app.main:app --reload

# Terminal 2: 前端
cd ~/stock-main-force/frontend && npm run dev
```

開啟 `http://localhost:5173` 確認：
- 深色主題 dashboard 顯示
- 族群標籤 filter 可點選
- API status bar 顯示各 job 狀態

- X **Step 5: Commit**

```bash
git add frontend/src/
git commit -m "feat: complete dashboard with tag filter and stock cards"
```

---

## Task 13: Docker Build + 整合測試

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`

- X **Step 1: 寫 backend/Dockerfile**

```dockerfile
FROM python:3.12-slim
RUN pip install uv
WORKDIR /app
COPY pyproject.toml .
RUN uv sync --no-dev
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- X **Step 2: 寫 frontend/Dockerfile**

```dockerfile
FROM node:20-alpine as builder
WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

- X **Step 3: 寫 frontend/nginx.conf**

```nginx
server {
  listen 80;
  root /usr/share/nginx/html;
  index index.html;
  location /api/ {
    proxy_pass http://backend:8000/api/;
  }
  location / {
    try_files $uri $uri/ /index.html;
  }
}
```

- X **Step 4: Docker Compose 全套啟動**

```bash
cd ~/stock-main-force
docker compose up --build -d
docker compose logs -f backend
```

Expected: backend 起動，DB migration 完成，backfill 開始

- X **Step 5: 端對端驗證**

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/status
curl http://localhost:3000  # 前端 dashboard
```

- X **Step 6: 最終 Commit**

```bash
git add backend/Dockerfile frontend/Dockerfile frontend/nginx.conf
git commit -m "feat: Docker multi-stage builds for backend and frontend"
git tag v0.1.0
```

---

## 自我審查 (Self-Review)

### Spec Coverage

| 需求 | 對應 Task |
|------|----------|
| 布林位階篩選 | Task 7 (screener.py) |
| 創60日新高 | Task 7 (find_peak_bb) |
| 盤整偵測 | Task 7 (is_squeeze) |
| 三大法人 | Task 3 (twse.py) |
| 融資融券 | Task 3 (fetch_margin) |
| 持股集中度 | Task 4 (finmind.py) |
| 4 排程 | Task 8 (scheduler.py) |
| 90日回填 | Task 8 (backfill_90_days) |
| fetch_log 防重複 | Task 8 (_already_fetched) |
| 族群標籤 YAML | Task 1 (sector_tags.yaml) |
| RS vs 大盤 | Task 6 + Task 7 (calc_score) |
| 21:00 後才可信 | Task 9 (is_reliable) |
| React 深色 dashboard | Task 10-12 |
| Docker PostgreSQL | Task 1 + 13 |

### 型別一致性確認

- `ScreeningResult` model 欄位 = `_format_result()` 輸出 = `ScreenerResult` TypeScript 型別 ✓
- `calc_score` 參數 `chip: dict` keys = `_get_chip_summary()` 輸出 keys ✓
- `check_entry_criteria` 回傳 `passes`, `bb_position`, `bb_peak`, `is_squeeze` = `ScreeningResult` 欄位 ✓
