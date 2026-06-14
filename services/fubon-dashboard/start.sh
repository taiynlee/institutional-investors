#!/usr/bin/env bash
# fubon-dashboard UI server — 直接在 WSL 執行
# 用法：bash start.sh
set -e
cd "$(dirname "$0")"

export FUBON_DATA_DIR="/home/tommy0322/fubon-data"
export FUBON_LOG_DIR="/home/tommy0322/fubon-logs"
export FUBON_CONFIG="/home/tommy0322/fubon-config/config.yaml"

# 讀取 .env（LINE token 等）
set -a
[ -f .env ] && source .env
set +a

mkdir -p "$FUBON_DATA_DIR" "$FUBON_LOG_DIR"

if [ ! -f .deps_installed ]; then
    echo "安裝依賴套件（第一次）..."
    pip install -q -r requirements.txt
    pip install -q ./vendor/fubon_neo-2.2.8-cp37-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
    touch .deps_installed
fi

echo "啟動 UI server on :8090 ..."
exec uvicorn main:app --host 0.0.0.0 --port 8090 --log-level warning
