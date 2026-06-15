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

    # ── Pre-session log（透過 PG backend API）────────────────────────────────

    def log_start(self, run_date: str, started_at: str, total_stocks: int) -> int:
        try:
            import httpx as _httpx
            r = _httpx.post(f"{_BACKEND}/api/pre-session/log/start",
                            json={"run_date": run_date, "total_stocks": total_stocks}, timeout=5)
            if r.status_code == 200:
                return r.json().get("id", 0)
        except Exception:
            pass
        return 0

    def log_finish(self, log_id: int, finished_at: str, success_stocks: int,
                   status: str = "ok", error_msg: str = None):
        try:
            import httpx as _httpx
            _httpx.patch(f"{_BACKEND}/api/pre-session/log/{log_id}",
                         json={"finished_at": finished_at, "status": status,
                               "success_stocks": success_stocks, "error_msg": error_msg},
                         timeout=5)
        except Exception:
            pass

    def get_pre_session_logs(self, limit: int = 10) -> list[dict]:
        try:
            import httpx as _httpx
            r = _httpx.get(f"{_BACKEND}/api/pre-session/logs", timeout=8)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

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
