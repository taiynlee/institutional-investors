"""
每日資料儲存層 — SQLite daily.db 已廢棄，所有資料移至 PostgreSQL。
此檔案保留相容介面（DailyStore），但所有操作改呼叫後端 API。
"""
from __future__ import annotations


_BACKEND = "http://localhost:8000"


class DailyStore:
    def __init__(self, db_path: str = "data/daily.db"):
        self.db_path = db_path  # 保留欄位相容，但不使用

    def init_db(self):
        pass

    def get_db_size_mb(self) -> float:
        return 0.0

    # ── 舊介面 stub（防止 import 錯誤）──────────────────────────────────────

    def get_watchlist_ids(self) -> list[str]:
        try:
            import httpx as _httpx
            r = _httpx.get(f"{_BACKEND}/api/pool", timeout=5)
            if r.status_code == 200:
                return [s["code"] for s in r.json()]
        except Exception:
            pass
        return []
