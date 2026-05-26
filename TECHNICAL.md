# DA数据清洗业务AI应用 技术文档

## 一、项目概述

DA数据清洗业务AI应用是一个基于 Flask 的本地财务数据查询分析工具，通过自然语言驱动 AI 生成 Pandas 代码，在安全沙箱中执行查询。支持序时账（Journal）和科目余额表（Balance Sheet）双表导入、字段映射、完整性测试和智能查询。

**技术栈：**
- 后端：Flask 3.0 + Flask-Session（服务端文件存储）
- 数据处理：Pandas 2.1 + NumPy 1.26
- AI 接口：DeepSeek API（deepseek-chat 模型）
- 代码执行：自定义 AST 安全沙箱（SafeSandbox）
- Excel 读写：openpyxl 3.1
- 前端：原生 HTML/CSS/JS（无前端框架），CodeMirror 代码编辑器

---

## 二、目录结构

```
DA数据清洗业务AI应用/
├── app.py                          # Flask 主应用（路由 + 会话管理 + 业务编排）
├── config.py                       # 全局配置（Secret Key、上传限制、超时等）
├── requirements.txt                # Python 依赖
├── start.sh                        # 快速启动脚本
├── sample.xlsx                     # 示例数据文件
│
├── modules/                        # 核心业务模块
│   ├── __init__.py
│   ├── data_processor.py           # DataProcessor - 文件加载/分析/字段映射
│   ├── ai_codegen.py               # AICodeGenerator - 调用 DeepSeek 生成代码
│   ├── sandbox.py                  # SafeSandbox - AST 安全沙箱执行环境
│   ├── integrity_checker.py        # IntegrityChecker - 三项固化完整性测试
│   └── utils.py                    # 工具类（文件/数据/会话/导出）
│
├── templates/                      # Jinja2 页面模板（5 步流程）
│   ├── index.html                  # 首页
│   ├── upload.html                 # 步骤1：文件上传
│   ├── field-mapper.html           # 步骤2：字段映射（序时账 + 科目余额表）
│   ├── api-config.html             # 步骤3：DeepSeek API Key 配置
│   ├── integrity-test.html         # 步骤4：完整性测试（可选）
│   └── query.html                  # 步骤5：自然语言查询分析
│
├── static/                         # 静态资源
│   ├── css/style.css
│   └── js/app.js
│
├── temp/                           # 上传文件存储目录（自动创建）
├── flask_session/                  # Flask-Session 文件存储目录（自动创建）
│
└── TECHNICAL.md                    # 本文件
```

---

## 三、5 步工作流

```
[上传文件] → [字段映射] → [API 配置] → [完整性测试(可选)] → [查询分析]
  步骤1          步骤2           步骤3             步骤4               步骤5
```

### 第 1 步：上传文件
- 支持格式：`.xlsx`、`.xls`、`.csv`
- 最大文件 50MB
- 上传序时账：`POST /api/upload` → 存储在 `session['data_info']`
- 上传科目余额表（可选）：`POST /api/upload-balance` → 存储在 `session['balance_data_info']`
- 关键操作：`DataProcessor.process()` 加载文件前 100 行进行分析，识别字段类型（text/number/date），生成预览数据

### 第 2 步：字段映射
- 前端将文件原始字段映射到标准字段（11 个序时账字段 + 9 个科目余额表字段）
- 映射格式：`{标准字段名: 源字段名}`
- 提交：`POST /api/configure-fields`
- 后端保存映射到 session，并计算 `mapped_fields` 和 `mapped_preview`（用于后续 AI 提示词）
- 同时支持序时账和科目余额表的映射

### 第 3 步：API 配置
- 输入 DeepSeek API Key
- `POST /api/configure-api` → 仅存于会话，不持久化

### 第 4 步：完整性测试（可选）
- `POST /api/integrity-test/run` → 运行三项固化测试
- 结果可导出为 Excel：`POST /api/integrity-test/export`

### 第 5 步：查询分析
- 用户输入自然语言 → `POST /api/generate-code` → DeepSeek 生成 Pandas 代码
- `POST /api/execute` → SafeSandbox 执行（含自动重试机制）
- `POST /api/export` → 导出结果（CSV/Excel）

---

## 四、核心模块详解

### 4.1 DataProcessor（`modules/data_processor.py`）

```python
class DataProcessor:
    def __init__(self, filepath: str)
    def load_data(self, nrows: Optional[int] = None) -> pd.DataFrame
    def get_total_rows(self) -> int
    def analyze_columns(self) -> List[Dict]
    def get_preview_data(self, rows: int = 5) -> List[Dict]
    def process(self) -> Dict
    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame
    def _apply_field_mapping_to_fields(self, fields_info, field_mapping)
    def _apply_field_mapping_to_preview(self, preview_data, field_mapping)
```

- `load_data()`：加载 Excel 或 CSV（自动尝试 utf-8-sig → utf-8 → gbk 等编码）
- `analyze_columns()`：检测每列类型（text/number/date），基于样本和关键词匹配
- `clean_data()`：关键的数据清洗方法，将 bool 列转为字符串（须在 `is_numeric_dtype()` 检查之前），数值 NaN 填充 0，对象列填充空字符串
- `process()`：综合分析入口，返回包含 `fields`、`preview`、`row_count` 等信息的字典

### 4.2 AICodeGenerator（`modules/ai_codegen.py`）

```python
class AICodeGenerator:
    def generate(self, query: str, fields_info: List[Dict], data_preview: Optional[List[Dict]]) -> str
```

- 构建提示词时，将 `fields_info` 中的所有字段名、类型、示例值传入 AI
- 提示词中强调："数据字段信息中提供的字段名是经过映射后的标准字段名，请直接使用这些字段名"
- 严格要求 AI 只使用 pandas 和 numpy，禁止文件/网络/系统操作
- 代码提取支持多种 markdown 代码块格式
- 验证层（`_validate_code_safety()`）还检查正则表达式合法性、`str.extract()` 必须有捕获组

### 4.3 SafeSandbox（`modules/sandbox.py`）

```python
class SafeSandbox:
    def __init__(self, timeout: int = 30, memory_limit: int = 100*1024*1024)
    def execute(self, code: str, data: Union[pd.DataFrame, List, Dict]) -> Dict
```

安全策略：
1. **AST 静态检查**：解析代码 AST，检查 import 是否在允许列表中，禁止 `eval`/`exec`/`open`/`os`/`sys` 等
2. **受限执行环境**：`__builtins__` 替换为安全子集（只有 `int`/`str`/`round`/`len`/`print` 等），`__import__` 重定向到只允许 pandas/numpy/math/datetime/time
3. **bool 列处理**：执行前注入代码将所有 bool 列转为字符串
4. **超时保护**：在独立线程中执行，超时自动终止
5. **结果处理**：递归将 numpy/pandas 类型（`np.bool_`、`np.integer`、`pd.Timestamp`、`NaT` 等）转为 JSON 安全的 Python 原生类型
6. **错误增强**：捕获常见错误（NaN 布索索引、日期格式不匹配、缺少捕获组等），提供中文解决建议

### 4.4 IntegrityChecker（`modules/integrity_checker.py`）

三项固化测试：

**测试一：序时账完整性**
- 按公司名+凭证号+日期分组，汇总金额
- 统计正/负/零值分组数
- 预期：正常情况各凭证组发生额应为 0（借贷平衡），或有正负分布

**测试二：科目余额表完整性**
- 汇总期初余额、期末余额
- 计算发生额 = 期末 - 期初
- 检查发生额汇总是否归零
- 预期：所有科目的发生额合计应为 0（借贷平衡）

**测试三：交叉验证**
- 序时账按公司+科目编号+科目名称汇总金额
- 余额表按同样维度汇总发生额（期末-期初）
- 两表全外连接，比较差异
- 统计差异记录、仅有序时账的记录、仅有余额表的记录

---

## 五、数据流详解

### 字段映射全链路

这是项目中最重要的数据流，涉及 4 个环节：

```
用户选择映射         前端收集           后端处理              查询执行
┌─────────┐    ┌──────────────┐    ┌────────────┐    ┌──────────────┐
│  "科目"  │ →  │ field_mapping│ →  │ data_info  │ →  │ df.rename()  │
│  →       │    │ = {          │    │ .mapped_   │    │ 重命名为     │
│ "科目名" │    │   "科目":    │    │ fields     │    │ 标准字段名    │
│          │    │   "科目名"   │    │ 传参给AI   │    │               │
│ 字段映射UI│    │ }           │    │            │    │ AI代码匹配    │
└─────────┘    └──────────────┘    └────────────┘    └──────────────┘
```

- `field_mapping` 格式：`{标准字段名: 源字段名}`（前端定义）
- 反向映射用于 DataFrame 重命名：`{源字段名: 标准字段名}`
- AI 提示词中展示的是标准字段名（如"科目"）
- 执行时 DataFrame 列名也是标准字段名，确保 AI 生成的代码能正确执行

### Session 数据模型

每个用户会话包含以下键：

| Session Key | 类型 | 说明 |
|-------------|------|------|
| `filepath` | str | 序时账文件路径 |
| `data_info` | dict | 序时账分析结果（fields, preview, mapped_fields, mapped_preview） |
| `field_mapping` | dict | 序时账字段映射 `{标准名: 源字段名}` |
| `balance_filepath` | str | 科目余额表文件路径 |
| `balance_data_info` | dict | 科目余额表分析结果 |
| `balance_field_mapping` | dict | 科目余额表字段映射 |
| `api_key` | str | DeepSeek API Key（仅会话生命周期） |
| `integrity_results` | dict | 完整性测试结果 |
| `last_execution_result` | dict | 上次代码执行结果（完整数据存于 temp/result_*.json） |

### `_json_safe()` 函数

```python
def _json_safe(obj):
```
全局 JSON 安全转换器，递归处理：
- `np.integer` → `int`
- `np.floating` → `float`
- `np.bool_` → `bool`
- `np.ndarray` → list → 递归

用于确保所有经过 `jsonify()` 返回的数据不含 numpy 类型（否则 500 错误）。

---

## 六、关键 API 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 首页 |
| GET | `/upload` | 上传页面 |
| GET | `/field-mapper` | 字段映射页面（加载 session 中的数据） |
| GET | `/api-config` | API 配置页面 |
| GET | `/integrity-test` | 完整性测试页面 |
| GET | `/query` | 查询页面（传递 `data_info` 到模板） |
| POST | `/api/upload` | 上传序时账文件，调用 `DataProcessor.process()` |
| POST | `/api/upload-balance` | 上传科目余额表文件 |
| POST | `/api/configure-fields` | 保存字段映射，计算 `mapped_fields`/`mapped_preview` |
| POST | `/api/configure-api` | 保存 API Key |
| POST | `/api/generate-code` | AI 生成 Pandas 代码 |
| POST | `/api/execute` | 执行代码（含三级重试） |
| POST | `/api/export` | 导出执行结果（CSV/Excel） |
| POST | `/api/integrity-test/run` | 运行完整性测试 |
| GET | `/api/integrity-test/results` | 获取上次测试结果 |
| POST | `/api/integrity-test/export` | 导出测试结果为 Excel（3 sheet） |

---

## 七、代码执行重试机制

`/api/execute` 实现了三级重试，应对不同数据质量问题：

```
第1次执行 → 失败？ → 检查错误类型
   ↓ 是
第2次执行（增强清洗：object→str，bool→str，numeric→fillna(0)） → 失败？
   ↓ 是
第3次执行（极端清洗：所有列→str.strip()）
```

触发重试的错误关键词：
- `Cannot mask with non-boolean array containing NA`
- `not supported between instances`
- `Can only use .str accessor with string values`
- `doesn't match format`
- `requires string as left operand`

---

## 八、潜在坑点与注意事项

### 1. bool 列处理顺序
`pd.api.types.is_numeric_dtype()` 在部分 Pandas 版本中对 bool 列返回 `True`（因 numpy bool 继承自 int）。**必须在 `is_numeric_dtype` 之前检查 `is_bool_dtype`**，否则 bool 列会被当作数值列处理，留下 bool 类型数据导致后续 `str.contains()` / `'in <string>'` 操作失败。
相关修改点：
- `data_processor.py:clean_data()`
- `sandbox.py:_prepare_data()`
- `app.py` 执行重试逻辑

### 2. session 修改后必须重新赋值
Flask-Session 文件存储基于 pickle。修改 session 中嵌套字典后，必须重新赋值才会持久化：
```python
data_info = session.get('data_info', {})
data_info['mapped_fields'] = mapped_fields
session['data_info'] = data_info  # 必须重新赋值
```

### 3. 完整性测试导出重新加载数据
导出逻辑不依赖 session 中的缓存结果（仅 20 条预览），而是重新加载文件数据并计算全量明细。

### 4. 前端 Flex 布局溢出
查询结果表字段过多时，页面会被撑变形。解决方案：
- `.query-main` 设置 `min-width: 0` 允许 flex 子项收缩
- `.result-preview-card` 设置 `overflow: hidden`
- 表格使用 `overflow: auto` + `max-height: 500px` 实现双轴滚动

### 5. 字段映射格式
- 前端收集：`mapping[stdField.name] = selectedField` → `{标准字段名: 源字段名}`
- 后端存储：直接保存 `field_mapping`
- DataFrame 重命名：反转映射 `{v: k}` → `{源字段名: 标准字段名}` → `df.rename(columns=reverse)`

### 6. CSV 编码
加载 CSV 时尝试 `utf-8-sig` → `utf-8` → `gbk` → `gb2312` → `latin1` → `cp1252`。

---

## 九、开发与调试

### 启动
```bash
cd DA数据清洗业务AI应用
pip install -r requirements.txt
python app.py
# 访问 http://localhost:5003
```

### 端口占用
```bash
lsof -ti:5003 | xargs kill -9
```

### 调试日志
在 `app.py` 的 `configure_fields()` 和 `generate_code()` 中已内置 `app.logger.info()` 日志，打印：
- 接收到的 `field_mapping`
- `data_info.keys()`（确认 mapped_fields 存在）
- 传递给 AI 的字段名列表

### 新增模块
在 `modules/` 下新建文件，`app.py` 顶部 import 即可。

### 新增路由
参考现有路由模式：页面路由返回 `render_template()`，API 路由返回 `jsonify()`。

---

## 十、依赖清单

| 包名 | 版本 | 用途 |
|------|------|------|
| Flask | 3.0.0 | Web 框架 |
| Flask-Session | 0.8.0 | 服务端会话存储（filesystem） |
| pandas | 2.1.4 | 数据处理 |
| numpy | 1.26.0 | 数值计算 |
| requests | 2.31.0 | 调用 DeepSeek API |
| openpyxl | 3.1.2 | Excel 读写 |
| Werkzeug | 3.0.1 | Flask 依赖 |
| python-dotenv | 1.0.0 | 环境变量加载 |
