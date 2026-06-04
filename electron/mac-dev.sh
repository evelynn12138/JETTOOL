#!/bin/bash
# macOS 开发模式启动脚本
# 绕过 Electron，直接启动 Flask 并在浏览器中打开
# 适用于 macOS 开发调试

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=========================================="
echo "  DA数据清洗业务AI应用 - 开发模式"
echo "=========================================="
echo ""

# 检查 Python 3
PYTHON=""
for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    PYTHON="$cmd"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "❌ 未找到 Python 3，请安装 Python 3.9+"
  exit 1
fi

echo "🔍 使用 Python: $($PYTHON --version)"

# 检查依赖
if [ ! -d "$PROJECT_DIR/venv" ]; then
  echo "📦 创建虚拟环境..."
  $PYTHON -m venv "$PROJECT_DIR/venv"
  source "$PROJECT_DIR/venv/bin/activate"
  pip install -r "$PROJECT_DIR/requirements.txt"
else
  source "$PROJECT_DIR/venv/bin/activate"
fi

echo "🚀 启动 Flask 后端..."
echo "   访问地址: http://127.0.0.1:5003"
echo ""

cd "$PROJECT_DIR"
$PYTHON app.py &

FLASK_PID=$!
echo "   Flask PID: $FLASK_PID"

# 等待 Flask 启动
echo "   等待服务就绪..."
for i in $(seq 1 30); do
  if curl -s http://127.0.0.1:5003/ >/dev/null 2>&1; then
    echo "   ✅ 服务就绪！"
    break
  fi
  sleep 1
done

# 在浏览器中打开
echo "🌐 在浏览器中打开..."
open http://127.0.0.1:5003

echo ""
echo "按 Ctrl+C 停止服务"

# 等待 Flask 进程
trap "kill $FLASK_PID 2>/dev/null; exit" INT TERM
wait $FLASK_PID
