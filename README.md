# DA数据清洗业务AI应用 - 本地智能财务凭证查询与分析工具

一个运行在浏览器内的、无需后端服务的、通过大模型驱动的单机数据查询客户端。让非技术用户通过自然语言在本地安全环境中对财务序时账进行查询分析。

## 🚀 快速开始

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 启动应用
```bash
python app.py
```

### 3. 访问应用
打开浏览器访问：http://localhost:5003

## 📋 使用流程

### 第一步：上传财务数据文件
- 支持格式：`.csv`, `.xlsx`, `.xls`
- 支持序时账和科目余额表双表导入
- 自动检测编码、字段类型，支持选择 Sheet 和自定义表头行

### 第二步：配置 API Key
- 输入你的 AI API Key（支持 DeepSeek / 百炼 / Kimi 等）
- API Key 仅存储在本次会话中，用完即清
- 可选配置第二 AI 模型用于 SQL 复核

### 第三步：字段映射
- 系统自动推荐映射（基于关键词匹配 + AI 智能映射）
- 手动调整映射关系
- 科目余额表支持借贷方计算模式

### 第四步：完整性测试（可选）
- 一键运行三项固化测试：凭证平衡、科目归零、两表交叉验证
- AI 引导式对话，根据企业实际情况定制测试参数
- 测试报告可导出 Excel

### 第五步：智能查询
- 用中文描述你的分析需求
- **优化表达**：点击"优化表达"让 AI 帮你把模糊的查询变具体
  - 语义优化：月底→最后五天，最近→近30天
  - 关键词扩展：调整→adj/adjustment
  - 人名识别：周健→zhoujian、zj
- AI 自动生成 DuckDB SQL 并在本地引擎中执行
- 支持 SQL 代码复核、手动编辑、结果导出
- 示例：
  - "统计每个科目的总金额"
  - "筛选出月底做账的凭证"
  - "筛选出摘要中包含调整的凭证"

## 🔧 故障排除

### 文件上传失败
```bash
# 运行诊断工具
python diagnose_upload.py 您的文件.csv

# 常见问题：
# 1. 文件编码问题 → 另存为UTF-8编码CSV
# 2. 日期格式问题 → 确保日期列为标准格式
# 3. 文件过大 → 拆分文件或减少数据量
```

### 应用启动问题
```bash
# 检查端口占用
lsof -i :5003

# 重启应用
pkill -f "python app.py"
python app.py
```

### 查看日志
```bash
# Flask应用日志
cat flask_debug.log
```

## 🛡️ 安全特性

- **数据本地化**：所有数据在本地处理，不上传服务器
- **安全沙箱**：用户代码在隔离环境中执行
- **API Key安全**：API Key仅存储在会话中，会话结束自动清除
- **代码验证**：AI生成的代码经过安全检查

## 📁 文件说明

```
finance-query-agent/
├── app.py                    # Flask主应用
├── requirements.txt          # Python依赖
├── config.py                # 配置文件
├── modules/                 # 核心模块
│   ├── data_processor.py   # 数据处理
│   ├── ai_codegen.py       # AI代码生成
│   └── sandbox.py          # 安全沙箱
├── templates/              # HTML模板
├── static/                 # 静态资源
├── sample_finance_data.csv # 示例数据
├── diagnose_upload.py      # 文件诊断工具
└── final_test.py          # 功能测试脚本
```

## 🧪 测试与验证

```bash
# 运行完整功能测试
python final_test.py

# 测试文件上传
python test_upload_error.py

# 测试字段映射
python test_field_mapping.py
```

## 💡 使用技巧

1. **数据准备**
   - 确保日期列为标准日期格式
   - 金额列应为数值类型
   - 清理列名中的特殊字符

2. **查询优化**
   - 具体描述需求（时间范围、科目、部门等）
   - 使用标准财务术语
   - 复杂需求可分步查询

3. **性能建议**
   - 大型文件（100万+行）建议先抽样测试
   - 复杂查询可分步执行
   - 定期清理浏览器缓存

## 📞 技术支持

遇到问题请提供：
1. 错误信息截图
2. 诊断工具输出：`python diagnose_upload.py 您的文件`
3. Flask日志内容：`cat flask_debug.log`

---

**注意**：本工具为本地部署，AI功能需要DeepSeek API Key，请确保遵守API使用条款。