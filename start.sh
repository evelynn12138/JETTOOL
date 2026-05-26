#!/bin/bash
# DA数据清洗业务AI应用 - 快速启动脚本

echo "DA数据清洗业务AI应用 - 快速启动"
echo "========================================"

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到Python3，请先安装Python3"
    exit 1
fi

echo "✅ Python版本: $(python3 --version)"

# 检查依赖
echo "🔧 检查Python依赖..."
if [ ! -f "requirements.txt" ]; then
    echo "❌ 缺少requirements.txt文件"
    exit 1
fi

# 安装依赖（如果尚未安装）
echo "📦 正在检查/安装依赖..."
pip3 install -r requirements.txt > /dev/null 2>&1

if [ $? -eq 0 ]; then
    echo "✅ 依赖检查完成"
else
    echo "⚠️  依赖安装可能有问题，尝试继续启动..."
fi

# 停止可能正在运行的进程
echo "🛑 停止现有进程..."
pkill -f "python app.py" 2>/dev/null

# 启动Flask应用
echo "▶️  启动Flask应用..."
nohup python3 app.py > flask.log 2>&1 &

# 等待应用启动
echo "⏳ 等待应用启动..."
sleep 5

# 检查应用状态
echo "🔍 检查应用状态..."
if curl -s http://localhost:5003/ > /dev/null 2>&1; then
    echo "✅ 应用启动成功!"
    echo ""
    echo "🌐 请在浏览器中访问: http://localhost:5003"
    echo ""
    echo "📋 使用步骤:"
    echo "  1. 上传财务数据文件 (.csv, .xlsx)"
    echo "  2. 配置字段映射"
    echo "  3. 输入DeepSeek API Key"
    echo "  4. 使用自然语言查询数据"
    echo ""
    echo "📊 测试文件:"
    echo "  - sample_finance_data.csv (示例数据)"
    echo "  - test_gl_data.csv (GLA JE格式)"
    echo ""
    echo "🔧 故障排除:"
    echo "  - 查看日志: tail -f flask.log"
    echo "  - 诊断文件: python3 diagnose_upload.py 您的文件.csv"
    echo "  - 完整测试: python3 final_test.py"
else
    echo "❌ 应用启动失败，请查看日志: cat flask.log"
    exit 1
fi

echo ""
echo "🛑 要停止应用，请运行: pkill -f 'python app.py'"