# DuckDB 迁移设计：支持 2GB/百万行级财务数据分析

## 1. 动机

当前工具使用 Pandas 处理财务数据，受限于内存，在 100 万行以上或超过 100MB 的数据集上性能急剧下降。实际审计工作中常遇到数百万行的 CSV 文件（50MB-2GB），需要一种能处理更大数据量的方案，同时保持自然语言查询和完整性测试等核心功能。

## 2. 方案选择

DuckDB 嵌入式列式数据库，理由：
- 嵌入式，零运维，适合本地工具
- 列式存储 + 向量化执行引擎，对聚合型查询极快
- 可直接查询 CSV 或导入后查询
- AI 生成 SQL 的可靠性高，且 SQL 天然安全（无需沙箱）

## 3. 数据导入策略

| 文件类型 | 大小 | 处理方式 |
|---------|------|---------|
| CSV | 任意 | 导入 DuckDB 持久化表 |
| XLSX | <100MB | 用 Pandas 读取后注册为 DuckDB 表 |
| XLSX | ≥100MB | 理论上不存在（Excel 行数上限 104 万行） |

导入过程：
1. 用户上传文件 → 检测格式和大小
2. 创建会话级 `.db` 文件（每个会话独立）
3. 序时账 → 表名 `data`，科目余额表 → 表名 `balance_data`
4. 应用字段映射（重名列名）→ `CREATE TABLE data AS SELECT ...`
5. 执行 AI 生成的 SQL 直接查询该表

## 4. 模块变更

### 4.1 新增模块 `modules/duckdb_engine.py`

DuckDB 操作封装：
- `init_session(db_path)` — 创建/打开会话级 DuckDB 数据库
- `import_csv(filepath, table_name, mapping)` — CSV 导入并应用映射
- `import_xlsx(filepath, table_name, mapping)` — XLSX 通过 pandas 桥接导入
- `execute(sql)` — 执行 SQL 返回 JSON 安全结果
- `execute_paginated(sql, page, page_size)` — 分页查询
- `get_schema(table_name)` — 获取表结构（用于 AI 提示词）
- `get_total_rows(table_name)` — 获取总行数
- `close()` — 关闭连接

### 4.2 修改 `modules/data_processor.py`

保持字段预览、列分析等逻辑，但 `process()` 方法不再全量加载数据：
- 仍读取前 100 行用于字段检测和预览
- 新增 `import_full_data()` 方法调用 DuckDB 引擎完成导入
- `clean_data()` 保留用于数据清洗（导入前对数据进行预处理）

### 4.3 修改 `modules/ai_codegen.py`

- `generate(query, schema_info, preview)` → 生成 SQL 而非 Python 代码
- 添加 SQL 安全验证（仅允许 SELECT 查询）
- 修改提示词模板：字段信息 + 表名 → DuckDB SQL
- `explain_code(sql)` → 解释 SQL 查询
- `optimize_query(query)` → 保持原来逻辑
- **去掉** `_validate_code_safety()`（不再需要，SQL 更安全）

### 4.4 重写 `modules/integrity_checker.py`

三条测试全部改为 DuckDB SQL：

1. **序时账完整性**（借贷平衡）：
   ```sql
   SELECT 公司名, 凭证号, 日期, SUM(金额) as 汇总发生额
   FROM data GROUP BY 公司名, 凭证号, 日期
   ```

2. **科目余额表完整性**（发生额归零）：
   ```sql
   SELECT SUM(期末余额) - SUM(期初余额) as 发生额
   FROM balance_data
   ```

3. **交叉验证**：
   ```sql
   SELECT coalesce(j.公司名, b.公司名) as 公司名, ...
   FROM data j FULL JOIN balance_data b ...
   ```

### 4.5 移除 `modules/sandbox.py`

不再需要 Python 沙箱。所有代码执行由 DuckDB SQL 替代。

### 4.6 修改 `config.py`

- `MAX_CONTENT_LENGTH` — 提升至 2GB（2048 * 1024 * 1024）
- 新增 `DUCKDB_DIR = 'temp/db'` — DuckDB 文件存放目录
- 移除沙箱相关配置 `EXECUTION_TIMEOUT`、`MEMORY_LIMIT`
- 保留或调整 `UPLOAD_FOLDER`

### 4.7 修改 `app.py` 路由

| 路由 | 变更 |
|------|------|
| `/api/upload` | 检测文件后立即触发 DuckDB 导入 |
| `/api/generate-code` | 改为生成 SQL |
| `/api/execute` | 改为在 DuckDB 上执行 SQL |
| `/api/integrity-test/run` | 改为调用 DuckDB 版 IntegrityChecker |
| `/api/explain-code` | 解释 SQL（微调提示词） |
| 移除 `/api/upload-balance` | 合并到统一上传流程 |

### 4.8 修改 `templates/query.html`

- 代码编辑器模式从 Python → SQL（CodeMirror mode）
- SQL 自然仍然是文本，无需编辑器本身大改
- 但 UI 提示词改为 SQL 相关提示

## 5. 数据流

### 上传 → 查询流程

```
用户上传 CSV
  → app.py: upload_file()
    → DataProcessor.process() 读取前100行 → 字段预览/分析
    → session 存文件路径
  → 用户配置字段映射
  → app.py: configure_fields()
    → duckdb_engine.import_csv(filepath, 'data', field_mapping)
  → 跳转到查询页

用户输入"按科目汇总金额"
  → AICodeGenerator.generate(query, schema, preview)
    → 调用 DeepSeek API → 返回 SQL
  → DuckDB 执行 SQL
  → 返回 JSON 结果给前端渲染
```

### 完整性测试流程

```
用户点击"运行完整性测试"
  → IntegrityChecker.run_all()
    → test_journal_integrity() → DuckDB SQL
    → test_balance_integrity() → DuckDB SQL
    → test_cross_validation() → DuckDB SQL
  → 返回 JSON 结果
```

## 6. 字段映射处理

现有字段映射逻辑保持不变，只是在导入数据到 DuckDB 时应用重命名：

```python
# configure_fields 接收映射后
mapping = {"科目名称": "GL Account Name", "日期": "Effective Date", ...}
# 导入时：DuckDB 建表时列名直接使用标准名
duckdb_engine.import_csv(filepath, 'data', mapping)
# AI 生成 SQL 时：表结构已使用标准名
schema = duckdb_engine.get_schema('data')
# → 返回 [('日期', 'VARCHAR'), ('科目名称', 'VARCHAR'), ('金额', 'DOUBLE'), ...]
```

## 7. SQL 安全性

- AI 生成的 SQL 必须只包含 `SELECT` 查询
- 额外验证：禁止 `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`CREATE`
- 对多语句查询，逐条验证
- DuckDB 连接以只读模式打开（`READ_ONLY=True`）

## 8. 前后端适配

### 前端（最小改动）

- 代码编辑器保持显示生成的代码，但内容变为 SQL
- 示例按钮的 prompt 文本可以保持自然语言
- 结果渲染完全不变（仍是 JSON → 表格）

### 结果导出（不变）

`/api/export` 路由的逻辑无需改变，因为 DuckDB 执行结果仍返回 JSON 格式。

## 9. 尚未解决的问题（后续迭代）

- 多文件同时加载（当前一次只能处理一个序时账 + 一个余额表）
- 增量导入/替换（重新导入时覆盖或追加）
- DuckDB 文件垃圾回收（上传失败时清理）
- 内存监控（导入前检查磁盘空间）

## 10. 删除的内容

- `modules/sandbox.py` — 整个模块，含 SafeSandbox 类及其 test_sandbox 方法
- `config.py` 中的 `EXECUTION_TIMEOUT`、`MEMORY_LIMIT` 配置项
