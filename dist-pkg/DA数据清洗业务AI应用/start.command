#!/bin/bash
# DA数据清洗业务AI应用 - macOS双击启动脚本
# 将此文件拖到终端，或直接在Finder中双击运行

cd "$(dirname "$0")"

echo "=========================================="
echo "  DA数据清洗业务AI应用"
echo "=========================================="

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 Python3"
    echo ""
    echo "请从 https://www.python.org/downloads/ 下载安装"
    echo "安装后重新双击此文件"
    echo ""
    read -p "按回车键退出..."
    exit 1
fi

echo "✅ Python $(python3 --version | cut -d' ' -f2)"

# 检查并安装依赖
if [ ! -f "requirements.txt" ]; then
    echo "❌ 缺少 requirements.txt"
    read -p "按回车键退出..."
    exit 1
fi

echo "🔧 检查依赖..."
pip3 install -q -r requirements.txt 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ 依赖就绪"
else
    echo "⚠️ 依赖安装有问题，尝试继续..."
fi

# 确保 temp 目录存在
mkdir -p temp/db temp/uploads temp/flask_session

# 停止旧的进程
pkill -f "python app.py" 2>/dev/null

# 启动 Flask 应用
echo "▶️  启动服务..."
python3 app.py &
APP_PID=$!
sleep 3

# 检查是否启动成功
if curl -s http://127.0.0.1:5003/ > /dev/null 2>&1; then
    echo "✅ 服务启动成功！"
    echo ""
    echo "🌐 正在打开浏览器..."
    open http://127.0.0.1:5003
    echo ""
    echo "⚠️  使用完毕后请关闭此窗口"
    echo "   或者在终端按下 Ctrl+C 停止服务"
    echo ""
    # 保持窗口打开
    wait $APP_PID
else
    echo "❌ 启动失败，请检查控制台输出"
    read -p "按回车键退出..."
fi
