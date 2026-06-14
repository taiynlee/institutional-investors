import os
from data.storage.daily_store import DailyStore
from monitor.dashboard.app import create_app
from engine.trading_engine import engine
from engine.scheduler import DailyScheduler

_data_dir = os.environ.get("FUBON_DATA_DIR", "/fubon-data")
_ticks_db = os.path.join(_data_dir, "ticks.db")
_daily_db = os.path.join(_data_dir, "daily.db")

_store = DailyStore(_daily_db)
_store.init_db()

# 自動排程：每個交易日 08:55 啟動引擎，13:36 停止，次日重連
_scheduler = DailyScheduler(engine)
_scheduler.start()

app = create_app(daily_store=_store, ticks_db=_ticks_db, trading_engine=engine)
