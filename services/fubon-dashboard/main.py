import os
from data.storage.daily_store import DailyStore
from monitor.dashboard.app import create_app

_data_dir = os.environ.get("FUBON_DATA_DIR", "/fubon-data")
_ticks_db = os.path.join(_data_dir, "ticks.db")
_daily_db = os.path.join(_data_dir, "daily.db")

_store = DailyStore(_daily_db)
_store.init_db()

app = create_app(daily_store=_store, ticks_db=_ticks_db)
