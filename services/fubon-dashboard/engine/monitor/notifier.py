import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineNotifier:
    """LINE 通知：優先用環境變數直打 Messaging API；無 token 則 fallback subprocess。"""

    def __init__(self, bot_dir: str = "/home/tommy0322/claude-line-bot", dry_run: bool = False):
        self.bot_dir = Path(bot_dir)
        self.dry_run = dry_run
        self._token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
        self._target = os.environ.get("LINE_NOTIFY_TARGET", "")

    def send(self, message: str) -> bool:
        if self.dry_run:
            logger.info("[LINE DRY RUN] %s", message)
            return True

        if self._token and self._target:
            return self._send_api(message)
        return self._send_subprocess(message)

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
