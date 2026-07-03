#!/usr/bin/env bash
set -euo pipefail

# TikTok → 微信动图收割机 — 一键部署脚本
# 用法: bash deploy.sh [端口号]
# 默认端口 8501

PORT="${1:-8501}"
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 安装/更新依赖 ==="
pip install -r "$APP_DIR/requirements.txt" --quiet

echo "=== 启动 Streamlit (端口 $PORT) ==="
streamlit run "$APP_DIR/app.py" \
    --server.port "$PORT" \
    --server.headless true \
    --theme.base light \
    --logger.level error
