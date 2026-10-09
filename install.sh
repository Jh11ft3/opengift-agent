#!/bin/sh
# ============================================================
# OpenGift 一键下载脚本
# 用法：curl -fsSL https://你的域名/install.sh -o install.sh && sh install.sh
# 也可：sh install.sh https://你的真实域名
# 只做一件事：把 opengift.py 下载到当前目录（不需要任何第三方环境）
# ============================================================
set -e

BASE="${1:-https://你的域名}"

echo "== 正在从 $BASE 下载 OpenGift =="
curl -fsSL "$BASE/opengift.py" -o opengift.py
echo "== 下载完成：opengift.py（$(wc -l < opengift.py | tr -d ' ') 行）=="
echo
echo "接下来两步："
echo "  1) python3 opengift.py --config   # 选择服务商、粘贴 API Key、选模型（默认硅基流动 Qwen/Qwen3-8B）"
echo "  2) python3 opengift.py            # 开始聊天"
