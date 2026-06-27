import json
import logging
import os
import sqlite3
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
_TZ = ZoneInfo("Asia/Taipei")

_NOTIF_DDL = """CREATE TABLE IF NOT EXISTS line_notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month  TEXT    NOT NULL,
    monthly_seq INTEGER NOT NULL,
    msg_type    TEXT    NOT NULL DEFAULT 'general',
    content     TEXT    NOT NULL,
    sent_at     TEXT    NOT NULL,
    success     INTEGER NOT NULL DEFAULT 1
)"""


class LineNotifier:
    """LINE 通知：優先用環境變數直打 Messaging API；無 token 則 fallback subprocess。
    每則訊息自動加上月序號 #YYYY-MM-NNN 並寫入 ticks.db/line_notifications。
    LINE free plan: 200 push messages/month。
    """

    def __init__(self, bot_dir: str = "/home/tommy0322/claude-line-bot", dry_run: bool = False):
        self.bot_dir = Path(bot_dir)
        self.dry_run = dry_run
        self._token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self._target = os.environ.get("LINE_NOTIFY_TARGET", "")
        data_dir = os.environ.get("FUBON_DATA_DIR", "/fubon-data")
        self._db = os.path.join(data_dir, "ticks.db")
        self._init_db()

    def _init_db(self) -> None:
        try:
            with sqlite3.connect(self._db) as conn:
                conn.execute(_NOTIF_DDL)
                conn.commit()
        except Exception as e:
            logger.warning("line_notifications 初始化失敗: %s", e)

    def _get_next_seq(self, ym: str) -> int:
        try:
            with sqlite3.connect(self._db) as conn:
                row = conn.execute(
                    "SELECT COALESCE(MAX(monthly_seq), 0) FROM line_notifications WHERE year_month=?",
                    (ym,),
                ).fetchone()
                return (row[0] if row else 0) + 1
        except Exception as e:
            logger.warning("取得月序號失敗: %s", e)
            return 0

    def _insert_log(self, ym: str, seq: int, msg_type: str,
                    content: str, sent_at: datetime, success: bool) -> None:
        try:
            with sqlite3.connect(self._db) as conn:
                conn.execute(
                    "INSERT INTO line_notifications"
                    "(year_month, monthly_seq, msg_type, content, sent_at, success)"
                    " VALUES(?,?,?,?,?,?)",
                    (ym, seq, msg_type, content, sent_at.isoformat(), int(success)),
                )
                conn.commit()
        except Exception as e:
            logger.warning("line_notifications 寫入失敗: %s", e)

    def send(self, message: str, msg_type: str = "general") -> bool:
        now = datetime.now(_TZ)
        ym = now.strftime("%Y-%m")
        seq = self._get_next_seq(ym)
        label = f"本月第{seq}次通知" if seq > 0 else ""
        full_msg = f"{label}\n{message}" if label else message

        if self.dry_run:
            logger.info("[LINE DRY RUN] %s", full_msg)
            if seq > 0:
                self._insert_log(ym, seq, msg_type, full_msg, now, True)
            return True

        bot_url = os.environ.get("LINE_BOT_URL", "")
        if bot_url:
            ok = self._send_bot_notify(bot_url, full_msg)
        elif self._token and self._target:
            ok = self._send_api(full_msg)
        else:
            ok = self._send_subprocess(full_msg)

        if seq > 0:
            self._insert_log(ym, seq, msg_type, full_msg, now, ok)
        return ok

    def _send_bot_notify(self, bot_url: str, message: str) -> bool:
        payload = json.dumps({"message": message}).encode("utf-8")
        req = urllib.request.Request(
            f"{bot_url.rstrip('/')}/notify",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("LINE 通知已送出 (bot /notify)")
                    return True
                logger.error("LINE bot /notify 回傳 %d", resp.status)
                return False
        except Exception as e:
            logger.error("LINE bot /notify 例外: %s", e)
            return False

    def _send_api(self, message: str) -> bool:
        payload = json.dumps({
            "to": self._target,
            "messages": [{"type": "text", "text": message}],
        }).encode("utf-8")
        req = urllib.request.Request(
            _LINE_PUSH_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logger.info("LINE 通知已送出 (API)")
                    return True
                logger.error("LINE API 回傳 %d", resp.status)
                return False
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            logger.error("LINE API HTTPError %d: %s", e.code, body)
            return False
        except Exception as e:
            logger.error("LINE API 例外: %s", e)
            return False

    def _send_subprocess(self, message: str) -> bool:
        uv = self._find_uv()
        try:
            result = subprocess.run(
                [uv, "run", "python", "send.py", message],
                cwd=str(self.bot_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                logger.info("LINE 通知已送出 (subprocess)")
                return True
            logger.error("LINE subprocess 失敗: %s", result.stderr.strip())
            return False
        except Exception as e:
            logger.error("LINE subprocess 例外: %s", e)
            return False

    @staticmethod
    def _find_uv() -> str:
        for p in ("/home/tommy0322/.local/bin/uv", "/usr/local/bin/uv", "uv"):
            if Path(p).exists():
                return p
        return "uv"
