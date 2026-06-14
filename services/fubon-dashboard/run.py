#!/usr/bin/env python3
"""
台股當沖一鍵啟動。
用法：cd services/fubon-dashboard && python run.py
"""
import os
import sys

# ── 環境預設值 ────────────────────────────────────────────────────────────────
os.environ.setdefault("FUBON_DATA_DIR", "/home/tommy0322/fubon-data")
os.environ.setdefault("FUBON_LOG_DIR",  "/home/tommy0322/fubon-logs")
os.environ.setdefault("FUBON_CONFIG",   "/home/tommy0322/fubon-config/config.yaml")

# ── 載入 .env（LINE token 等）────────────────────────────────────────────────
_env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

import uvicorn
uvicorn.run("main:app", host="0.0.0.0", port=8090, log_level="info")
