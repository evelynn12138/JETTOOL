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
- 最大文件大小：50MB
- 推荐包含字段：日期、摘要、科目、借方、贷方、金额

### 第二步：字段映射
- 系统自动识别字段并推荐映射
- 手动调整映射关系（如果需要）
- 确保核心字段正确映射

### 第三步：配置API Key
- 输入您的DeepSeek API Key
- API Key仅存储在本次会话中
- 可随时重新配置

### 第四步：自然语言查询
- 用中文描述您的分析需求
- 示例：
  - "统计每个科目的总金额"
  - "找出2024年第一季度的管理费用"
  - "按部门汇总差旅费报销"

### 第五步：执行与导出
- AI自动生成安全Pandas代码
- 在安全沙箱中执行
- 导出结果为Excel或CSV

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