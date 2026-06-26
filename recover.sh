#!/usr/bin/env bash
# 一鍵復元腳本 — 電腦重啟或意外斷電後執行此腳本恢復全部服務
# 用法：bash recover.sh
set -e

PROJ_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="/home/tommy0322/fubon-logs"
LOGFILE="$LOG_DIR/recover_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$LOG_DIR"
exec > >(tee "$LOGFILE") 2>&1

echo "=== 一鍵復元 $(date) ==="

# ── 0. 確保 systemd linger 開啟（user service 才能在無登入時自動啟動）─────────
if loginctl show-user "$(whoami)" 2>/dev/null | grep -q "Linger=no"; then
    echo ">>> [0] 啟用 systemd linger..."
    sudo loginctl enable-linger "$(whoami)"
    echo "    linger 已啟用"
fi

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

# ── 2. fubon-dashboard via systemd user service ─────────────────────────────
echo ">>> [2/3] 啟動 fubon-dashboard（systemd user service）..."
if curl -sf http://localhost:8090/health > /dev/null 2>&1; then
    echo "    fubon-dashboard 已在運行（port 8090），跳過啟動"
else
    # 若 service 曾達到 StartLimitBurst 上限，先 reset 再啟動
    systemctl --user reset-failed fubon-dashboard.service 2>/dev/null || true
    systemctl --user restart fubon-dashboard.service 2>/dev/null || \
        systemctl --user start fubon-dashboard.service
    echo ">>> [3/3] 等待 fubon-dashboard 就緒..."
    for i in $(seq 1 20); do
        if curl -sf http://localhost:8090/health > /dev/null 2>&1; then
            echo "    fubon-dashboard 啟動成功（${i}s）"
            break
        fi
        sleep 1
    done
    if ! curl -sf http://localhost:8090/health > /dev/null 2>&1; then
        echo "    ⚠ fubon-dashboard 尚未就緒，查看："
        echo "      journalctl --user -u fubon-dashboard -n 50"
        echo "      systemctl --user status fubon-dashboard"
    fi
fi

echo ""
echo "=== 復元完成 $(date) ==="
echo "    前端 Dashboard : http://localhost:6174"
echo "    當沖 API       : http://localhost:8090"
echo "    Log 檔案       : $LOGFILE"
