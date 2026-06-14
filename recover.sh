#!/usr/bin/env bash
# 一鍵復元腳本 — 電腦重啟或意外斷電後執行此腳本恢復全部服務
# 用法：bash recover.sh
set -e

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
FUBON_DIR="$PROJ_DIR/services/fubon-dashboard"
LOG_DIR="/home/tommy0322/fubon-logs"
LOGFILE="$LOG_DIR/recover_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"
exec > >(tee "$LOGFILE") 2>&1

echo "=== 一鍵復元 $(date) ==="

# ── 1. Docker Compose ───────────────────────────────────────────────────────
echo ">>> [1/3] 啟動 Docker Compose（DB + 後端 + 前端）..."
cd "$PROJ_DIR"
docker compose up -d
echo "    Docker Compose 啟動完成"

# 等 backend 健康
echo "    等待 backend 就緒（最多 30s）..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "    backend OK (${i}s)"
        break
    fi
    sleep 1
done

# ── 2. 檢查 fubon-dashboard 是否已在跑 ──────────────────────────────────────
echo ">>> [2/3] 檢查當沖引擎..."
if curl -sf http://localhost:8090/health > /dev/null 2>&1; then
    echo "    fubon-dashboard 已在運行（port 8090），跳過啟動"
else
    echo ">>> [3/3] 啟動 fubon-dashboard（背景執行）..."
    cd "$FUBON_DIR"
    nohup python run.py >> "$LOG_DIR/fubon_stdout.log" 2>&1 &
    FPID=$!
    echo "    fubon-dashboard PID=$FPID，等待 5s..."
    sleep 5
    if curl -sf http://localhost:8090/health > /dev/null 2>&1; then
        echo "    fubon-dashboard 啟動成功"
    else
        echo "    ⚠ fubon-dashboard 尚未就緒，請查看 $LOG_DIR/fubon_stdout.log"
    fi
fi

echo ""
echo "=== 復元完成 $(date) ==="
echo "    前端 Dashboard : http://localhost:6174"
echo "    當沖 API       : http://localhost:8090"
echo "    Log 檔案       : $LOGFILE"
