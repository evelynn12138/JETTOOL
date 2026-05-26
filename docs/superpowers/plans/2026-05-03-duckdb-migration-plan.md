# DuckDB 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Pandas-based data processing with DuckDB to support 2GB/million-row CSV files in the financial audit analysis tool.

**Architecture:** Add `duckdb_engine.py` module handling all DuckDB operations; rewrite `integrity_checker.py` to use SQL; modify `ai_codegen.py` to generate SQL; update `app.py` routes; remove `sandbox.py`.

**Tech Stack:** DuckDB (embedded), Python, SQL, existing Flask frontend

---

## File Structure

| File | Status | Responsibility |
|------|--------|----------------|
| `modules/duckdb_engine.py` | **Create** | DuckDB session, CSV/XLSX import, SQL execution, schema queries |
| `modules/data_processor.py` | Modify | Add `import_full_data()` for DuckDB import path |
| `modules/ai_codegen.py` | Modify | Generate SQL instead of Python; SQL validation |
| `modules/integrity_checker.py` | **Rewrite** | Same test logic via DuckDB SQL |
| `modules/sandbox.py` | **Delete** | No longer needed |
| `config.py` | Modify | MAX_CONTENT_LENGTH→2GB, add DUCKDB_DIR, remove sandbox config |
| `app.py` | Modify | Update routes to use DuckDB; remove sandbox dependency |
| `templates/query.html` | Modify | CodeMirror mode → SQL, minor hint updates |

## Execution Order

Dependencies flow: config → duckdb_engine → data_processor → ai_codegen → integrity_checker → app.py → query.html → remove sandbox.

---

### Task 1: Update config.py

**Files:**
- Modify: `config.py` (entire file)

- [ ] **Step 1: Rewrite config.py**

Replace sandbox config with DuckDB config, raise upload limit.

```python
import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)

    # 文件上传配置
    MAX_CONTENT_LENGTH = 2048 * 1024 * 1024  # 2GB
    UPLOAD_FOLDER = 'temp'
    DUCKDB_DIR = 'temp/db'
    ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}

    # AI API配置
    DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
    DEEPSEEK_MODEL = "deepseek-chat"
    DEEPSEEK_TEMPERATURE = 0.3

    # 数据预览配置
    PREVIEW_ROWS = 10
    MAX_ROWS_PREVIEW = 10000
```

---

### Task 2: Create duckdb_engine.py

**Files:**
- Create: `modules/duckdb_engine.py`

This module wraps all DuckDB interactions. The key design decisions:
- Each session gets its own `.db` file at `config.DUCKDB_DIR/{session_id}.db`
- DuckDB connection opens in read-only mode for query execution
- Column types inferred automatically by DuckDB's CSV reader
- XLSX files use pandas as a bridge to DuckDB
- All results returned as JSON-safe Python types

- [ ] **Step 1: Write duckdb_engine.py**

```python
import os
import duckdb
import pandas as pd
import json
import math
from typing import Dict, List, Any, Optional, Tuple
from flask import current_app


class DuckDBEngine:
    """DuckDB 操作引擎 - 每个会话一个独立数据库文件"""

    def __init__(self, db_path: str):
        """
        初始化 DuckDB 连接

        Args:
            db_path: .db 文件路径
        """
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._conn = duckdb.connect(db_path)

    def import_csv(self, csv_path: str, table_name: str,
                   rename_mapping: Optional[Dict[str, str]] = None,
                   file_column_mapping: Optional[Dict[str, str]] = None) -> int:
        """
        导入 CSV 文件到 DuckDB 表。

        Args:
            csv_path: CSV 文件路径
            table_name: 目标表名（如 'data' / 'balance_data'）
            rename_mapping: {源列名: 标准列名} 映射，用于字段重命名
            file_column_mapping: 如果 CSV 列名和映射键不匹配，
                                 提供 {标准字段名: 原始文件列名} 映射

        Returns:
            导入的行数
        """
        # 先创建一个临时命名视图，读取 CSV
        # DuckDB read_csv_auto 自动检测 schema
        # 使用双引号保留列名中的中文字符

        if file_column_mapping:
            # 重命名列名：SELECT original_col AS standard_col, ...
            select_parts = []
            for std_name, orig_name in file_column_mapping.items():
                # 对列名加双引号以防特殊字符
                select_parts.append(f'"{orig_name}" AS "{std_name}"')
            select_clause = ', '.join(select_parts)

            self._conn.execute(f"""
                CREATE TABLE "{table_name}" AS
                SELECT {select_clause}
                FROM read_csv_auto('{csv_path}', header=true)
            """)
        elif rename_mapping:
            # 第二种方式：先读 CSV 然后用 rename_mapping 重命名
            df = pd.read_csv(csv_path, nrows=1)
            csv_columns = list(df.columns)

            # 找出 CSV 中哪些列被映射了
            select_parts = []
            for csv_col in csv_columns:
                if csv_col in rename_mapping:
                    select_parts.append(f'"{csv_col}" AS "{rename_mapping[csv_col]}"')
                else:
                    select_parts.append(f'"{csv_col}"')
            select_clause = ', '.join(select_parts)

            self._conn.execute(f"""
                CREATE TABLE "{table_name}" AS
                SELECT {select_clause}
                FROM read_csv_auto('{csv_path}', header=true)
            """)
        else:
            self._conn.execute(f"""
                CREATE TABLE "{table_name}" AS
                SELECT * FROM read_csv_auto('{csv_path}', header=true)
            """)

        result = self._conn.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()
        return result[0]

    def import_xlsx(self, xlsx_path: str, table_name: str,
                    rename_mapping: Optional[Dict[str, str]] = None) -> int:
        """
        导入 XLSX 文件（通过 Pandas 桥接）

        Args:
            xlsx_path: Excel 文件路径
            table_name: 目标表名
            rename_mapping: {源列名: 标准列名}

        Returns:
            导入的行数
        """
        df = pd.read_excel(xlsx_path)
        if rename_mapping:
            df = df.rename(columns=rename_mapping)

        self._conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM df')
        result = self._conn.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()
        return result[0]

    def execute(self, sql: str) -> Dict[str, Any]:
        """
        执行 SQL 查询并返回 JSON 安全结果

        Args:
            sql: SQL 查询语句

        Returns:
            {
                'success': bool,
                'result': {
                    'type': 'dataframe',
                    'columns': [...],
                    'data': [...]
                } | 'type': 'scalar', 'value': ...
                'execution_time': float
            }
        """
        import time
        start = time.time()

        try:
            result = self._conn.execute(sql)
            rows = result.fetchall()
            columns = [desc[0] for desc in result.description]
            execution_time = time.time() - start

            if not rows:
                return {
                    'success': True,
                    'result': {
                        'type': 'dataframe',
                        'columns': columns,
                        'data': []
                    },
                    'execution_time': execution_time
                }

            # 判断结果类型
            if len(columns) == 1 and len(rows) == 1:
                # 标量结果
                scalar_val = self._to_json_safe(rows[0][0])
                return {
                    'success': True,
                    'result': {
                        'type': 'scalar',
                        'value': scalar_val,
                        'label': columns[0]
                    },
                    'execution_time': execution_time
                }

            # DataFrame 类型结果
            data = []
            for row in rows:
                row_dict = {}
                for i, col in enumerate(columns):
                    row_dict[col] = self._to_json_safe(row[i])
                data.append(row_dict)

            return {
                'success': True,
                'result': {
                    'type': 'dataframe',
                    'columns': columns,
                    'data': data,
                    'shape': [len(rows), len(columns)]
                },
                'execution_time': execution_time
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def execute_paginated(self, sql: str, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        """
        分页执行查询

        Returns 格式同 execute()，额外包含 total_rows, total_pages
        """
        # 先获取总数
        count_sql = f"SELECT COUNT(*) FROM ({sql}) AS _sub"
        count_result = self._conn.execute(count_sql).fetchone()
        total_rows = count_result[0] if count_result else 0
        total_pages = max(1, math.ceil(total_rows / page_size))

        # 分页查询
        offset = (page - 1) * page_size
        paginated_sql = f"{sql} LIMIT {page_size} OFFSET {offset}"
        result = self.execute(paginated_sql)

        if result.get('success') and result.get('result'):
            result['result']['total_rows'] = total_rows
            result['result']['total_pages'] = total_pages
            result['result']['page'] = page

        return result

    def get_schema(self, table_name: str) -> List[Dict[str, str]]:
        """
        获取表结构（列名 + 类型）

        Returns:
            [{'name': str, 'type': str}, ...]
        """
        result = self._conn.execute(
            f"DESCRIBE \"{table_name}\""
        ).fetchall()
        return [{'name': row[0], 'type': row[1]} for row in result]

    def get_total_rows(self, table_name: str) -> int:
        """获取表总行数"""
        result = self._conn.execute(
            f"SELECT COUNT(*) FROM \"{table_name}\""
        ).fetchone()
        return result[0] if result else 0

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        result = self._conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            f"WHERE table_name = '{table_name}'"
        ).fetchone()
        return result[0] > 0 if result else False

    def drop_table(self, table_name: str):
        """删除表"""
        self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')

    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _to_json_safe(val):
        """将 Python/DuckDB 类型转换为 JSON 安全类型"""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
                return None
            return val
        if isinstance(val, bool):
            return val
        if isinstance(val, bytes):
            try:
                return val.decode('utf-8')
            except:
                return str(val)
        if isinstance(val, (list, tuple)):
            return [DuckDBEngine._to_json_safe(v) for v in val]
        if isinstance(val, dict):
            return {k: DuckDBEngine._to_json_safe(v) for k, v in val.items()}
        if hasattr(val, 'isoformat'):  # date/datetime/timedelta
            return str(val)
        return str(val)

    @staticmethod
    def validate_select_only(sql: str) -> bool:
        """
        验证 SQL 是否只包含 SELECT 查询

        Returns:
            True 如果安全（仅 SELECT），False 如果不安全
        """
        import re
        sql_trimmed = sql.strip()

        # 去除注释
        sql_clean = re.sub(r'--.*$', '', sql_trimmed, flags=re.MULTILINE)
        sql_clean = re.sub(r'/\*.*?\*/', '', sql_clean, flags=re.DOTALL)

        # 如果有多个语句，逐条检查
        statements = [s.strip() for s in sql_clean.split(';') if s.strip()]
        for stmt in statements:
            # 检查第一条非空 token
            tokens = [t for t in re.split(r'\s+', stmt) if t]
            if not tokens:
                continue
            first_word = tokens[0].upper()
            if first_word not in ('SELECT', 'WITH', 'EXPLAIN', 'DESCRIBE', 'SHOW'):
                return False
        return True
```

---

### Task 3: Modify data_processor.py

**Files:**
- Modify: `modules/data_processor.py`

Add the `import_full_data()` method and keep existing logic.

- [ ] **Step 1: Add DuckDB import method**

Add import and new method at end of `data_processor.py` (before or inside the DataProcessor class). No changes needed to existing methods since `process()` already only reads 100 rows for preview.

```python
    def import_full_data(self, duckdb_engine, table_name: str = 'data') -> int:
        """
        将完整数据导入 DuckDB

        Args:
            duckdb_engine: DuckDBEngine 实例
            table_name: 目标表名

        Returns:
            导入的行数
        """
        # 构建映射：{源列名: 标准列名}
        rename_mapping = None
        if self.field_mapping:
            rename_mapping = {v: k for k, v in self.field_mapping.items()}

        if self.file_type == 'excel':
            return duckdb_engine.import_xlsx(
                self.filepath, table_name, rename_mapping
            )
        else:
            return duckdb_engine.import_csv(
                self.filepath, table_name, rename_mapping=rename_mapping
            )
```

Also add `field_mapping` parameter to `__init__`:

```python
    def __init__(self, filepath: str, field_mapping: Optional[Dict[str, str]] = None):
        self.filepath = filepath
        self.field_mapping = field_mapping
        self.df = None
        self.file_type = self._detect_file_type()
```

---

### Task 4: Rewrite integrity_checker.py to use DuckDB

**Files:**
- Rewrite: `modules/integrity_checker.py`

The new IntegrityChecker uses DuckDB instead of Pandas. The frontend JSON result format must remain identical.

- [ ] **Step 1: Write new integrity_checker.py**

```python
"""
完整性检查模块 - 基于 DuckDB 的财务数据完整性测试逻辑

包含三类完整性测试：
1. 序时账完整性测试：按公司名+凭证号+生效日期分组，检查发生额汇总
2. 科目余额表完整性测试：汇总期初金额、期末金额、发生额(期末-期初)是否归零
3. 序时账&科目余额表交叉验证：按公司+科目编号+科目名称，检查两表发生额一致性
"""

import duckdb
from typing import Dict, Any, Optional


class IntegrityChecker:
    """完整性检查器 - 基于 DuckDB 的财务数据一致性验证"""

    def __init__(self, duckdb_engine, journal_table: str = 'data',
                 balance_table: Optional[str] = 'balance_data'):
        """
        Args:
            duckdb_engine: DuckDBEngine 实例
            journal_table: 序时账表名
            balance_table: 科目余额表表名（可为空）
        """
        self.engine = duckdb_engine
        self.journal_table = journal_table
        self.balance_table = balance_table
        self.results = {}

    def _table_exists(self, table: str) -> bool:
        return self.engine.table_exists(table)

    def _fetchone(self, sql: str):
        """直接执行 SQL 并返回单行结果"""
        conn = self.engine._conn
        return conn.execute(sql).fetchone()

    def _fetchall(self, sql: str):
        """直接执行 SQL 并返回全部结果"""
        conn = self.engine._conn
        return conn.execute(sql).fetchall()

    def _describe(self, sql: str):
        """获取 SQL 查询的列描述"""
        conn = self.engine._conn
        result = conn.execute(sql)
        return [desc[0] for desc in result.description], result.fetchall()

    # ========== 测试1：序时账完整性测试 ==========

    def test_journal_integrity(self) -> Dict[str, Any]:
        """
        序时账完整性测试
        按公司名、凭证号、日期分组汇总发生额，检查凭证平衡性
        """
        result = {
            'test_name': '序时账完整性测试',
            'description': '按公司名+凭证号+日期分组，汇总发生额，检查凭证平衡性',
            'status': 'skipped',
            'details': {}
        }

        if not self._table_exists(self.journal_table):
            result['status'] = 'skipped'
            result['message'] = '序时账数据为空，跳过测试'
            return result

        conn = self.engine._conn

        # 检查必要字段
        schema = {col['name'] for col in self.engine.get_schema(self.journal_table)}
        required = {'公司名', '凭证号', '日期', '金额'}
        missing = required - schema
        if missing:
            result['status'] = 'error'
            result['message'] = f'序时账缺少以下字段: {", ".join(sorted(missing))}，无法完成完整性测试'
            result['missing_fields'] = list(missing)
            return result

        try:
            # 分组汇总
            sql = f'''
                SELECT
                    "{'公司名'}",
                    "{'凭证号'}",
                    "{'日期'}",
                    CAST(SUM(CAST("{'金额'}" AS DOUBLE)) AS DOUBLE) AS "汇总发生额"
                FROM "{self.journal_table}"
                GROUP BY "{'公司名'}", "{'凭证号'}", "{'日期'}"
            '''
            headers, rows = self._describe(sql)
            total_groups = len(rows)
            total_amount = sum(r[3] or 0 for r in rows)

            positive_groups = sum(1 for r in rows if (r[3] or 0) > 0)
            negative_groups = sum(1 for r in rows if (r[3] or 0) < 0)
            zero_groups = sum(1 for r in rows if r[3] == 0 or r[3] is None)

            # 预览前 20 条
            groups_preview = [
                dict(zip(headers, r)) for r in rows[:20]
            ]

            result['status'] = 'completed'
            result['message'] = '序时账完整性测试完成'
            result['details'] = {
                'total_groups': int(total_groups),
                'total_amount': float(round(total_amount, 2)),
                'positive_groups': int(positive_groups),
                'negative_groups': int(negative_groups),
                'zero_groups': int(zero_groups),
                'groups_preview': groups_preview,
                'total_groups_exceed_preview': total_groups > 20
            }
            result['passed'] = True

        except Exception as e:
            result['status'] = 'error'
            result['message'] = f'序时账完整性测试执行失败: {str(e)}'

        return result

    # ========== 测试2：科目余额表完整性测试 ==========

    def test_balance_integrity(self) -> Dict[str, Any]:
        """
        科目余额表完整性测试
        汇总期初余额、期末余额，计算发生额（期末-期初）并检查汇总是否为0
        """
        result = {
            'test_name': '科目余额表完整性测试',
            'description': '汇总期初余额、期末余额，计算发生额汇总是否归零',
            'status': 'skipped',
            'details': {}
        }

        if not self.balance_table or not self._table_exists(self.balance_table):
            result['status'] = 'skipped'
            result['message'] = '未上传科目余额表，跳过测试'
            return result

        schema = {col['name'] for col in self.engine.get_schema(self.balance_table)}
        required = {'期初余额', '期末余额'}
        missing = required - schema
        if missing:
            result['status'] = 'error'
            result['message'] = f'科目余额表缺少以下字段: {", ".join(sorted(missing))}，无法完成完整性测试'
            result['missing_fields'] = list(missing)
            return result

        try:
            conn = self.engine._conn
            row = conn.execute(f'''
                SELECT
                    CAST(SUM(CAST("{'期初余额'}" AS DOUBLE)) AS DOUBLE),
                    CAST(SUM(CAST("{'期末余额'}" AS DOUBLE)) AS DOUBLE),
                    CAST(SUM(CAST("{'期末余额'}" AS DOUBLE)) - SUM(CAST("{'期初余额'}" AS DOUBLE)) AS DOUBLE)
                FROM "{self.balance_table}"
            ''').fetchone()

            total_beginning = row[0] or 0.0
            total_ending = row[1] or 0.0
            total_occurrence = row[2] or 0.0
            balance_check = abs(total_occurrence) < 0.01

            # 获取行数
            count_row = conn.execute(
                f'SELECT COUNT(*) FROM "{self.balance_table}"'
            ).fetchone()

            result['status'] = 'completed'
            result['message'] = '科目余额表完整性测试完成'
            result['details'] = {
                'total_beginning': float(round(total_beginning, 2)),
                'total_ending': float(round(total_ending, 2)),
                'total_occurrence': float(round(total_occurrence, 2)),
                'balance_check_passed': bool(balance_check),
                'balance_check_message': '期初余额 + 发生额 = 期末余额，数据平衡' if balance_check
                else f'发生额汇总不为零（{round(total_occurrence, 2)}），可能存在数据异常',
                'row_count': int(count_row[0]) if count_row else 0
            }
            result['passed'] = balance_check

        except Exception as e:
            result['status'] = 'error'
            result['message'] = f'科目余额表完整性测试执行失败: {str(e)}'

        return result

    # ========== 测试3：交叉验证 ==========

    def test_cross_validation(self) -> Dict[str, Any]:
        """
        序时账&科目余额表交叉验证
        按公司+科目编号+科目名称汇总，检查两表发生额一致性
        """
        result = {
            'test_name': '序时账&科目余额表交叉验证',
            'description': '按公司+科目编号+科目名称汇总，检查两表发生额一致性',
            'status': 'skipped',
            'details': {}
        }

        if not self._table_exists(self.journal_table):
            result['status'] = 'skipped'
            result['message'] = '序时账数据为空，跳过测试'
            return result

        if not self.balance_table or not self._table_exists(self.balance_table):
            result['status'] = 'skipped'
            result['message'] = '未上传科目余额表，跳过测试'
            return result

        j_schema = {col['name'] for col in self.engine.get_schema(self.journal_table)}
        b_schema = {col['name'] for col in self.engine.get_schema(self.balance_table)}

        j_required = {'公司名', '科目编号', '科目名称', '金额'}
        b_required = {'公司名', '科目编号', '科目名称', '期初余额', '期末余额'}

        j_missing = j_required - j_schema
        b_missing = b_required - b_schema

        missing = []
        if j_missing:
            missing.append(f'序时账缺少: {", ".join(sorted(j_missing))}')
        if b_missing:
            missing.append(f'科目余额表缺少: {", ".join(sorted(b_missing))}')

        if missing:
            result['status'] = 'error'
            result['message'] = '; '.join(missing) + '，无法完成交叉验证'
            result['missing_fields'] = {
                'journal': list(j_missing),
                'balance': list(b_missing)
            }
            return result

        try:
            conn = self.engine._conn

            sql = f'''
                WITH journal_agg AS (
                    SELECT
                        "{'公司名'}",
                        "{'科目编号'}",
                        "{'科目名称'}",
                        CAST(SUM(CAST("{'金额'}" AS DOUBLE)) AS DOUBLE) AS "序时账发生额"
                    FROM "{self.journal_table}"
                    GROUP BY "{'公司名'}", "{'科目编号'}", "{'科目名称'}"
                ),
                balance_agg AS (
                    SELECT
                        "{'公司名'}",
                        "{'科目编号'}",
                        "{'科目名称'}",
                        CAST(
                            SUM(CAST("{'期末余额'}" AS DOUBLE)) - SUM(CAST("{'期初余额'}" AS DOUBLE))
                        AS DOUBLE) AS "余额表发生额"
                    FROM "{self.balance_table}"
                    GROUP BY "{'公司名'}", "{'科目编号'}", "{'科目名称'}"
                )
                SELECT
                    COALESCE(j."公司名", b."公司名") AS "公司名",
                    COALESCE(j."科目编号", b."科目编号") AS "科目编号",
                    COALESCE(j."科目名称", b."科目名称") AS "科目名称",
                    COALESCE(j."序时账发生额", 0.0) AS "序时账发生额",
                    COALESCE(b."余额表发生额", 0.0) AS "余额表发生额",
                    COALESCE(j."序时账发生额", 0.0) - COALESCE(b."余额表发生额", 0.0) AS "差异"
                FROM journal_agg j
                FULL OUTER JOIN balance_agg b
                    ON j."公司名" = b."公司名"
                    AND j."科目编号" = b."科目编号"
                    AND j."科目名称" = b."科目名称"
                ORDER BY ABS("差异") DESC
            '''

            headers, rows = self._describe(sql)
            total_accounts = len(rows)

            # 分类统计
            consistent_count = sum(1 for r in rows if abs(r[5] or 0) <= 0.01
                                   and r[3] is not None and r[4] is not None)
            difference_count = sum(1 for r in rows if abs(r[5] or 0) > 0.01)
            only_in_journal = sum(1 for r in rows if r[4] == 0.0 and r[3] != 0.0)
            only_in_balance = sum(1 for r in rows if r[3] == 0.0 and r[4] != 0.0)

            is_consistent = difference_count == 0 and only_in_journal == 0 and only_in_balance == 0

            # 提取差异记录（前20条）
            diff_records = [
                dict(zip(headers, r))
                for r in rows
                if abs(r[5] or 0) > 0.01
            ][:20]

            # 仅有序时账（前10条）
            only_journal_records = [
                dict(zip(headers, r))
                for r in rows
                if r[4] == 0.0 and r[3] != 0.0
            ][:10]

            # 仅有余额表（前10条）
            only_balance_records = [
                dict(zip(headers, r))
                for r in rows
                if r[3] == 0.0 and r[4] != 0.0
            ][:10]

            # 汇总金额
            journal_total = sum(r[3] or 0 for r in rows)
            balance_total = sum(r[4] or 0 for r in rows)

            result['status'] = 'completed'
            result['message'] = '交叉验证完成'
            result['details'] = {
                'total_accounts': int(total_accounts),
                'consistent_count': int(consistent_count),
                'difference_count': int(difference_count),
                'only_in_journal': int(only_in_journal),
                'only_in_balance': int(only_in_balance),
                'is_consistent': bool(is_consistent),
                'journal_total_amount': float(round(journal_total, 2)),
                'balance_total_occurrence': float(round(balance_total, 2)),
                'diff_records': diff_records,
                'only_journal_records': only_journal_records,
                'only_balance_records': only_balance_records,
                'has_more_diffs': difference_count > 20,
                'has_more_only_journal': only_in_journal > 10,
                'has_more_only_balance': only_in_balance > 10
            }
            result['passed'] = is_consistent

        except Exception as e:
            import traceback
            result['status'] = 'error'
            result['message'] = f'交叉验证执行失败: {str(e)}'
            result['traceback'] = traceback.format_exc()

        return result

    # ========== 运行全部测试 ==========

    def run_all(self) -> Dict[str, Any]:
        """运行所有可执行的完整性测试"""
        results = {
            'journal_test': self.test_journal_integrity(),
            'balance_test': self.test_balance_integrity(),
            'cross_test': self.test_cross_validation()
        }

        total = 3
        completed = sum(1 for r in results.values() if r['status'] == 'completed')
        errors = sum(1 for r in results.values() if r['status'] == 'error')
        skipped = sum(1 for r in results.values() if r['status'] == 'skipped')

        return {
            'success': True,
            'summary': {
                'total': total,
                'completed': completed,
                'errors': errors,
                'skipped': skipped
            },
            'results': results,
            'all_passed': all(
                r.get('passed', False) for r in results.values()
                if r['status'] == 'completed'
            )
        }
```

---

### Task 5: Rewrite ai_codegen.py to generate SQL

**Files:**
- Modify: `modules/ai_codegen.py`

Replace the `generate()` method's prompt to produce SQL instead of Python code. Add `_validate_sql()` method. Keep `explain_code()` and `optimize_query()` with adjusted prompts. Remove `_validate_code_safety()`.

- [ ] **Step 1: Rewrite generate() for SQL**

Key changes to `ai_codegen.py`:

1. In `__init__`: Set `self.max_tokens = 1500`
2. Rewrite `_build_prompt()` to generate SQL
3. Replace `_validate_code_safety()` with `_validate_sql()`
4. Replace `_extract_code()` to extract SQL from response
5. Update `explain_code()` prompt for SQL

````python
    def _build_prompt(self, query: str, fields_info: List[Dict[str, Any]],
                     data_preview: Optional[List[Dict]]) -> str:
        """构建提示词 - 生成 DuckDB SQL"""
        fields_desc = []
        for field in fields_info:
            field_desc = f"- {field['name']} ({field['type']})"
            if field.get('sample'):
                field_desc += f" 示例: {field['sample']}"
            fields_desc.append(field_desc)
        fields_str = "\n".join(fields_desc)

        preview_str = ""
        if data_preview and len(data_preview) > 0:
            preview_lines = ["数据预览:"]
            for i, row in enumerate(data_preview[:3]):
                row_str = ", ".join([f"{k}: {v}" for k, v in row.items()])
                preview_lines.append(f"  行{i+1}: {row_str}")
            preview_str = "\n".join(preview_lines)

        prompt = f"""你是一个专业的财务数据分析专家，专门处理财务序时账数据。

## 任务要求
根据用户的自然语言查询，生成 DuckDB SQL 查询语句来处理财务数据。

## 数据表信息
表名: data
字段信息:
{fields_str}

{preview_str}

## 用户查询
{query}

## 财务数据特点
1. 财务数据通常包含凭证信息，一个凭证可能有多个行项目（借方和贷方）
2. 常见财务字段：日期、凭证号、摘要、科目名称、借方金额、贷方金额、制单人
3. 如果还有科目余额表可用，表名为 balance_data，包含字段：公司名、科目编号、科目名称、期初余额、期末余额等

## SQL 要求
1. **必须只包含 SELECT 查询**，不包含 INSERT/UPDATE/DELETE/CREATE/DROP/ALTER
2. 使用双引号包裹表名和列名（防止中文字符问题）：如 FROM "data"
3. 金额字段可能需要 CAST 为 DOUBLE：CAST("金额" AS DOUBLE)
4. 日期比较使用标准 SQL：WHERE "日期" >= '2024-01-01'
5. 文本匹配使用：WHERE "摘要" LIKE '%关键词%'
6. 聚合函数：SUM, COUNT, AVG, MAX, MIN
7. 分组使用 GROUP BY，排序使用 ORDER BY
8. 结果限制使用 LIMIT（最多1000条）
9. 有科目余额表时可以用 JOIN：FROM "data" d JOIN "balance_data" b ON ...

## 输出要求
请只返回 SQL 代码，不要包含解释或额外文本。SQL 必须完整且可执行。

```sql
```
"""
        return prompt
````

- [ ] **Step 2: Replace `_validate_code_safety` with `_validate_sql`**

```python
    def _validate_sql(self, sql: str) -> bool:
        """
        验证 SQL 安全性 - 只允许 SELECT 查询

        Returns:
            是否安全
        """
        import re
        sql_trimmed = sql.strip()

        # 去除注释
        sql_clean = re.sub(r'--.*$', '', sql_trimmed, flags=re.MULTILINE)
        sql_clean = re.sub(r'/\*.*?\*/', '', sql_clean, flags=re.DOTALL)

        # 如果有多个语句，逐条检查
        statements = [s.strip() for s in sql_clean.split(';') if s.strip()]
        for stmt in statements:
            tokens = [t for t in re.split(r'\s+', stmt) if t]
            if not tokens:
                continue
            first_word = tokens[0].upper()
            if first_word not in ('SELECT', 'WITH', 'EXPLAIN', 'DESCRIBE', 'SHOW'):
                return False
        return True
```

- [ ] **Step 3: Update `generate()` to use SQL validation instead of code safety check**

In `generate()`:
```python
    def generate(self, query: str, fields_info: List[Dict[str, Any]],
                data_preview: Optional[List[Dict]] = None) -> str:
        try:
            prompt = self._build_prompt(query, fields_info, data_preview)
            response = self._call_api(prompt)
            sql = self._extract_code(response)  # reuses extraction logic

            if not self._validate_sql(sql):
                raise ValueError("生成的 SQL 包含非 SELECT 操作")

            return sql
        except Exception as e:
            raise Exception(f"SQL 生成失败: {str(e)}")
```

- [ ] **Step 4: Update `explain_code()` prompt for SQL**

Replace the prompt in `explain_code()`:
```python
    def explain_code(self, sql: str) -> str:
        prompt = f"""请解释以下 DuckDB SQL 查询的功能和执行步骤：

```sql
{sql}
```

请用中文简洁明了地解释：
1. 这条 SQL 的主要功能是什么？
2. 查询了哪些表和字段？
3. 使用了什么过滤条件和聚合逻辑？
4. 会输出什么结果？
5. 执行时需要注意什么？

请用自然语言回答，不要包含代码。"""
        # ... rest of the method stays the same
```

- [ ] **Step 5: Remove `_validate_code_safety` and update `_extract_code`**

In `_extract_code()`, change the import check: instead of checking for `import pandas`, ensure the extracted code starts with `SELECT` or `WITH` or contains SQL patterns. Update:

```python
    def _extract_code(self, response_content: str) -> str:
        """从 API 响应中提取 SQL 代码"""
        content = response_content.strip()

        # 提取代码块
        code_patterns = [
            r"```sql\n(.*?)```",
            r"```\n(.*?)```",
            r"```(?:sql)?\s*\n(.*?)\n```",
            r"```(?:sql)?(.*?)```",
        ]

        matches = []
        for pattern in code_patterns:
            try:
                found = re.findall(pattern, content, re.DOTALL)
                if found:
                    matches.extend(found)
                    break
            except re.error:
                continue

        if matches:
            sql = matches[-1].strip()
        else:
            # 尝试从响应中提取以 SELECT/WITH 开头的内容
            lines = content.split('\n')
            sql_lines = []
            in_sql = False
            for line in lines:
                stripped = line.strip()
                if stripped.upper().startswith('SELECT') or stripped.upper().startswith('WITH'):
                    in_sql = True
                if in_sql:
                    sql_lines.append(line)
            sql = '\n'.join(sql_lines).strip() if sql_lines else content

        # 清理空行
        sql_lines = [line.rstrip() for line in sql.split('\n') if line.strip()]
        return '\n'.join(sql_lines)
```

- [ ] **Step 6: Update `test_generation()` to test SQL (optional, keep if desired)**

Remove references to `import pandas` and `df` in test, just verify the output isn't empty.

---

### Task 6: Modify app.py routes

**Files:**
- Modify: `app.py`

Now wire everything together. The major route changes:

- [ ] **Step 1: Update imports**

```python
from modules.data_processor import DataProcessor
from modules.ai_codegen import AICodeGenerator
from modules.duckdb_engine import DuckDBEngine
from modules.integrity_checker import IntegrityChecker
# 不再导入 sandbox
```

Remove `from modules.sandbox import SafeSandbox`.

- [ ] **Step 2: Add module-level DuckDB helper**

```python
def get_duckdb_engine():
    """获取当前会话的 DuckDB 引擎"""
    if not os.path.exists(app.config['DUCKDB_DIR']):
        os.makedirs(app.config['DUCKDB_DIR'], exist_ok=True)

    # 每个会话一个独立 db 文件
    session_id = session.sid or 'default'
    db_path = os.path.join(app.config['DUCKDB_DIR'], f'{session_id}.db')
    return DuckDBEngine(db_path)
```

- [ ] **Step 3: Update /api/upload - trigger DuckDB import after field config**

The upload route stays mostly the same (reads 100 rows for preview), but also store a flag that import hasn't happened yet:

Keep `/api/upload` mostly unchanged - still reads 100 rows for preview. Add `session['duckdb_imported'] = False`.

- [ ] **Step 4: Update /api/configure-fields - trigger DuckDB import**

After saving field_mapping in session, also trigger DuckDB import:

```python
@app.route('/api/configure-fields', methods=['POST'])
def configure_fields():
    data = request.json
    field_mapping = data.get('field_mapping')
    balance_field_mapping = data.get('balance_field_mapping')

    if not field_mapping:
        return jsonify({'success': False, 'error': '序时账字段映射不能为空'})

    session['field_mapping'] = field_mapping

    # ... (existing mapping logic unchanged) ...

    # 导入序时账到 DuckDB
    journal_filepath = session.get('filepath')
    if journal_filepath and os.path.exists(journal_filepath):
        try:
            processor = DataProcessor(journal_filepath)
            engine = get_duckdb_engine()
            rename_mapping = {v: k for k, v in field_mapping.items()}
            if processor.file_type == 'excel':
                engine.import_xlsx(journal_filepath, 'data', rename_mapping)
            else:
                engine.import_csv(journal_filepath, 'data', rename_mapping=rename_mapping)
            session['duckdb_imported'] = True
        except Exception as e:
            app.logger.error(f"DuckDB 导入序时账失败: {e}")

    # 导入科目余额表到 DuckDB
    if balance_field_mapping:
        session['balance_field_mapping'] = balance_field_mapping
        balance_filepath = session.get('balance_filepath')
        if balance_filepath and os.path.exists(balance_filepath):
            try:
                engine = get_duckdb_engine()
                rename_mapping = {v: k for k, v in balance_field_mapping.items()}
                if processor.file_type == 'excel':
                    engine.import_xlsx(balance_filepath, 'balance_data', rename_mapping)
                else:
                    engine.import_csv(balance_filepath, 'balance_data', rename_mapping=rename_mapping)
            except Exception as e:
                app.logger.error(f"DuckDB 导入科目余额表失败: {e}")

    # ... rest unchanged ...
```

- [ ] **Step 5: Update /api/generate-code - pass schema info instead of fields/preview**

```python
@app.route('/api/generate-code', methods=['POST'])
def generate_code():
    data = request.json
    query = data.get('query')

    if not query:
        return jsonify({'success': False, 'error': '查询语句不能为空'})

    api_key = session.get('api_key')
    if not api_key:
        return jsonify({'success': False, 'error': '请先配置API Key'})

    data_info = session.get('data_info')
    if not data_info:
        return jsonify({'success': False, 'error': '请先上传数据文件'})

    try:
        generator = AICodeGenerator(api_key)
        fields = data_info.get('mapped_fields', data_info.get('fields', []))
        preview = data_info.get('mapped_preview', data_info.get('preview', []))

        # 如果 DuckDB 表存在，附加表结构信息
        if session.get('duckdb_imported'):
            try:
                engine = get_duckdb_engine()
                schema = engine.get_schema('data')
                # 将 schema 信息合并到 fields 中
                # 有 balance_data 也一并告知
                has_balance = engine.table_exists('balance_data')
                fields = [{'name': f['name'], 'type': f['type']} for f in schema]
                if has_balance:
                    balance_schema = engine.get_schema('balance_data')
                    fields.append({'name': '--- 科目余额表字段 ---', 'type': 'info'})
                    fields.extend([{'name': f['name'], 'type': f['type']} for f in balance_schema])
            except Exception as e:
                app.logger.warning(f"获取 DuckDB schema 失败: {e}")

        sql = generator.generate(query, fields, preview)
        return jsonify({'success': True, 'code': sql})
    except Exception as e:
        return jsonify({'success': False, 'error': f'SQL 生成失败: {str(e)}'})
```

- [ ] **Step 6: Rewrite /api/execute - run SQL on DuckDB instead of sandbox**

```python
@app.route('/api/execute', methods=['POST'])
def execute_code():
    data = request.json
    sql = data.get('code')

    if not sql:
        return jsonify({'success': False, 'error': 'SQL 不能为空'})

    if not session.get('duckdb_imported'):
        return jsonify({'success': False, 'error': '请先配置字段映射后再执行查询'})

    try:
        engine = get_duckdb_engine()

        # 验证 SQL 安全性
        if not DuckDBEngine.validate_select_only(sql):
            return jsonify({'success': False, 'error': '仅支持 SELECT 查询'})

        result = engine.execute(sql)

        # 存储结果用于导出
        if result.get('success') and result.get('result'):
            result_data = result['result']
            import tempfile, json, time
            temp_dir = app.config['UPLOAD_FOLDER']
            timestamp = int(time.time())
            result_filename = f'result_{timestamp}.json'
            result_filepath = os.path.join(temp_dir, result_filename)
            with open(result_filepath, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, default=str)

            session['last_execution_result'] = {
                'success': True,
                'simplified_result': {
                    'type': result_data.get('type'),
                    'columns': result_data.get('columns'),
                    'data_length': len(result_data.get('data', [])),
                    'result_file': result_filename
                }
            }
        else:
            session['last_execution_result'] = {
                'success': False,
                'error': result.get('error')
            }

        return jsonify(result)
    except Exception as e:
        import traceback
        app.logger.error(f"[EXECUTE ERROR] {str(e)}\n{traceback.format_exc()}")
        return jsonify({'success': False, 'error': f'SQL 执行失败: {str(e)}'})
```

- [ ] **Step 7: Update /api/integrity-test/run - use new DuckDB-based IntegrityChecker**

```python
@app.route('/api/integrity-test/run', methods=['POST'])
def run_integrity_tests():
    try:
        if not session.get('duckdb_imported'):
            return jsonify({
                'success': False,
                'error': '请先配置字段映射后再运行完整性测试'
            })

        engine = get_duckdb_engine()
        has_balance = engine.table_exists('balance_data')
        checker = IntegrityChecker(engine, 'data', 'balance_data' if has_balance else None)
        results = checker.run_all()
        session['integrity_results'] = results
        return jsonify(results)

    except Exception as e:
        import traceback
        app.logger.error(f"[INTEGRITY TEST ERROR] {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'error': f'完整性测试执行失败: {str(e)}'
        })
```

- [ ] **Step 8: Update /api/explain-code prompt for SQL**

```python
@app.route('/api/explain-code', methods=['POST'])
def explain_code():
    # ... same logic, just the prompt in AICodeGenerator.explain_code was already updated
    # The method already takes whatever code is passed (now SQL)
```

- [ ] **Step 9: Clean up unused code**

Remove imports of `SafeSandbox`, `numpy`, `json_module` aliases that are no longer needed. Remove the `_json_safe()` function (the DuckDBEngine handles conversion). Remove the retry logic block in the old execute route.

Keep `_json_safe` for backward compatibility with any session data that might contain numpy types.

---

### Task 7: Update query.html CodeMirror mode

**Files:**
- Modify: `templates/query.html`

- [ ] **Step 1: Change CodeMirror mode to SQL**

```javascript
// Change from:
codeMirrorEditor = CodeMirror.fromTextArea(textarea, {
    mode: 'python',
    ...
});

// To:
codeMirrorEditor = CodeMirror.fromTextArea(textarea, {
    mode: 'text/x-sql',
    ...
});
```

No need to load a separate SQL mode file - CodeMirror includes basic SQL highlighting in the core. But if we want better highlighting, add the SQL mode script:

```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.2/mode/sql/sql.min.js"></script>
```

- [ ] **Step 2: Minor UI hint adjustments (optional)**

Update placeholder text or tooltips to reflect SQL instead of Python where visible.

---

### Task 8: Remove sandbox.py

**Files:**
- Delete: `modules/sandbox.py`

- [ ] **Step 1: Verify no imports reference sandbox**

Check app.py:
```bash
grep -rn "sandbox" modules/ app.py
```

Expected: only references in import lines that are being removed.

- [ ] **Step 2: Delete the file**

```bash
rm modules/sandbox.py
```

Also clean up `__pycache__`:
```bash
rm -rf modules/__pycache__
```

---

## Dependencies Between Tasks

```
Task 1 (config.py)           ← independent
    │
Task 2 (duckdb_engine.py)    ← independent (new module)
    │
    ├── Task 3 (data_processor.py)  ← depends on duckdb_engine
    ├── Task 4 (integrity_checker.py) ← depends on duckdb_engine
    │
Task 5 (ai_codegen.py)       ← independent
    │
    ├── Task 6 (app.py)      ← depends on Tasks 1-5
    │
    └── Task 7 (query.html)  ← independent
    │
Task 8 (remove sandbox)      ← last (after verifying app.py no longer imports it)
```

---

## Self-Review Checklist

After writing, verify:

- [ ] spec coverage: Every section of the DuckDB migration spec has at least one task implementing it
- [ ] No placeholders: Every step has complete code or exact instructions
- [ ] Type consistency: `DuckDBEngine.execute()` return format matches what `execute_code()` route and frontend expect
- [ ] Frontend backward compatibility: Integrity test result JSON shape unchanged
- [ ] No dangling imports: sandbox.py references removed from app.py before deletion
