#!/bin/bash
# DA数据清洗业务AI应用 - 打包分发脚本
# 运行方式: bash distribute.sh
# 输出: dist/DA数据清洗业务AI应用/ (可ZIP分发)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$SCRIPT_DIR/dist-pkg/DA数据清洗业务AI应用"

echo "=========================================="
echo "  打包 DA数据清洗业务AI应用"
echo "=========================================="

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"
mkdir -p "$DIST_DIR/temp/db"
mkdir -p "$DIST_DIR/temp/uploads"

# 复制核心代码
echo "📦 复制核心代码..."
cp "$SCRIPT_DIR/app.py" "$DIST_DIR/"
cp "$SCRIPT_DIR/config.py" "$DIST_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$DIST_DIR/"
cp "$SCRIPT_DIR/start.command" "$DIST_DIR/"
chmod +x "$DIST_DIR/start.command"

# 复制模块
echo "📦 复制模块..."
mkdir -p "$DIST_DIR/modules"
for f in "$SCRIPT_DIR/modules/"*.py; do
    [ -f "$f" ] && cp "$f" "$DIST_DIR/modules/"
done

# 复制模板
echo "📦 复制模板..."
mkdir -p "$DIST_DIR/templates"
cp "$SCRIPT_DIR/templates/"*.html "$DIST_DIR/templates/"

# 复制静态资源
echo "📦 复制静态资源..."
cp -r "$SCRIPT_DIR/static" "$DIST_DIR/static/"

# 复制预设规则
echo "📦 复制预设规则..."
cp "$SCRIPT_DIR/temp/preset_rules.json" "$DIST_DIR/temp/"

# 复制示例数据
echo "📦 复制示例数据..."
for f in "$SCRIPT_DIR/"*.csv "$SCRIPT_DIR/"*.xlsx; do
    [ -f "$f" ] && cp "$f" "$DIST_DIR/"
done 2>/dev/null || true

# 创建 README
cat > "$DIST_DIR/使用说明.txt" << 'EOF'
DA数据清洗业务AI应用 - 使用说明
========================================

📋 系统要求
  - macOS 或 Windows / Linux
  - Python 3.9 或更高版本
    (从 https://www.python.org/downloads/ 下载)

🚀 启动方法 (macOS)
  1. 双击 start.command
  2. 首次启动会自动安装依赖（需要联网）
  3. 浏览器自动打开 http://127.0.0.1:5003

🚀 启动方法 (Windows)
  1. 打开终端 (cmd)，进入此文件夹
  2. 运行: pip install -r requirements.txt
  3. 运行: python app.py
  4. 浏览器访问 http://127.0.0.1:5003

🛑 停止服务
  - 关闭终端窗口，或按 Ctrl+C

📝 使用流程
  1. 上传财务数据文件 (.csv, .xlsx)
  2. 配置字段映射
  3. 输入 DeepSeek API Key
  4. 使用自然语言查询数据

❓ 常见问题
  - 端口被占用: 修改 config.py 中的端口号
  - Python 未安装: 按上面链接下载安装
  - 依赖安装失败: 确保网络连接正常
EOF

echo ""
echo "=========================================="
echo "  ✅ 打包完成!"
echo ""
echo "  分发文件夹: $DIST_DIR"
echo "  大小: $(du -sh "$DIST_DIR" | cut -f1)"
echo ""
echo "  可以直接 ZIP 此文件夹发给别人使用"
echo "=========================================="
