"""
每個交易日自動：
  08:30 → 啟動引擎（登入 Fubon SDK，訂閱 WebSocket，確保 09:00 前就緒）
  13:36 → 停止引擎（斷線，清理 session）
  隔日  → 偵測日期變更，舊 session 強制停止，再等 08:30 重啟

不需要手動按「啟動引擎」。
"""
import logging
import threading
from engine.utils.market import is_session_active, is_weekday
from engine.utils.tz import now_tw, today_tw

logger = logging.getLogger(__name__)

_CHECK_INTERVAL = 30  # 秒，輪詢間隔


class DailyScheduler:
    def __init__(self, engine):
        self._engine = engine
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="daily-scheduler"
        )
        self._thread.start()
        logger.info("DailyScheduler 啟動（每 %ds 檢查一次市場時間）", _CHECK_INTERVAL)

    def stop(self):
        self._stop.set()

    # ── 主迴圈 ────────────────────────────────────────────────────────────────

    def _loop(self):
        last_checked_date: str | None = None

        while not self._stop.is_set():
            now = now_tw()
            today = today_tw().isoformat()
            eng = self._engine
            status = eng.status

            # ── 新的一天：強制停止前日 session ──────────────────────────────
            if last_checked_date and last_checked_date != today:
                if status in ("running", "starting", "error"):
                    logger.info("日期變更 %s → %s，停止前日 session", last_checked_date, today)
                    eng.stop()
            last_checked_date = today

            # ── 是否應該連線 ─────────────────────────────────────────────────
            should_run = is_session_active()

            if should_run and status in ("stopped", "error"):
                # session_date 跟今天相同代表今天已經跑過並結束了（收盤停止）
                # 等到 session_date 不是今天或是 None 才允許重啟
                already_ran_today = (eng.session_date == today and status == "stopped")
                if not already_ran_today:
                    logger.info("開盤時間 %s，自動啟動引擎", now.strftime("%H:%M"))
                    eng.start()

            elif not should_run and status == "running":
                logger.info("收盤時間 %s，自動停止引擎", now.strftime("%H:%M"))
                eng.stop()

            self._stop.wait(timeout=_CHECK_INTERVAL)

        logger.info("DailyScheduler 已停止")
