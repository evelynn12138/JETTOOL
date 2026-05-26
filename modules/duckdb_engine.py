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
                   file_column_mapping: Optional[Dict[str, str]] = None,
                   header_row: Optional[int] = None,
                   constant_columns: Optional[Dict[str, str]] = None) -> int:
        """
        导入 CSV 文件到 DuckDB 表。

        Args:
            csv_path: CSV 文件路径
            table_name: 目标表名（如 'data' / 'balance_data'）
            rename_mapping: {源列名: 标准列名} 映射，用于字段重命名
            file_column_mapping: 如果 CSV 列名和映射键不匹配，
                                 提供 {标准字段名: 原始文件列名} 映射
            header_row: 表头行号（0-indexed），指定后使用 Pandas 读取以跳过非表头行
            constant_columns: 常量列 {列名: 值}，用于手动填写的字段（如公司名）

        Returns:
            导入的行数
        """
        csv_options = "header=true, all_varchar=true, quote='\"'"

        # 有常量列时，必须走 Pandas 路径
        needs_pandas = constant_columns is not None and len(constant_columns) > 0

        if needs_pandas or header_row is not None:
            # 使用 Pandas 读取以支持自定义表头行/常量列
            df = pd.read_csv(csv_path, header=header_row if header_row is not None else 0)
            print(f"[DUCKDB IMPORT_CSV] 自定义表头行 header_row={header_row}, {len(df)} 行, 列: {list(df.columns)}")
            if rename_mapping:
                df = df.rename(columns=rename_mapping)
            if constant_columns:
                for col_name, col_value in constant_columns.items():
                    if col_name not in df.columns:
                        df[col_name] = col_value
                        print(f"[DUCKDB IMPORT_CSV] 添加常量列 {col_name} = {col_value}")
            # 确保科目编号以文本形式存储，避免数字类型导致 ".0" 后缀
            if '科目编号' in df.columns:
                df['科目编号'] = df['科目编号'].apply(
                    lambda x: str(int(x)) if pd.notna(x) and isinstance(x, (int, float)) and x == int(x)
                              else str(x) if pd.notna(x)
                              else None
                )
            self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            self._conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM df')
            result = self._conn.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()
            return result[0]

        if file_column_mapping:
            select_parts = []
            for std_name, orig_name in file_column_mapping.items():
                select_parts.append(f'"{orig_name}" AS "{std_name}"')
            select_clause = ', '.join(select_parts)

            self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            self._conn.execute(f"""
                CREATE TABLE "{table_name}" AS
                SELECT {select_clause}
                FROM read_csv_auto('{csv_path}', {csv_options})
            """)
        elif rename_mapping:
            df = pd.read_csv(csv_path, nrows=1)
            csv_columns = list(df.columns)

            select_parts = []
            for csv_col in csv_columns:
                if csv_col in rename_mapping:
                    select_parts.append(f'"{csv_col}" AS "{rename_mapping[csv_col]}"')
                else:
                    select_parts.append(f'"{csv_col}"')
            select_clause = ', '.join(select_parts)

            mapped_cols = [c for c in csv_columns if c in rename_mapping]
            non_mapped = [c for c in csv_columns if c not in rename_mapping]
            print(f"[DUCKDB IMPORT_CSV] 已映射列: {len(mapped_cols)}, 未映射列(已保留): {len(non_mapped)}")

            self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            try:
                self._conn.execute(f"""
                    CREATE TABLE "{table_name}" AS
                    SELECT {select_clause}
                    FROM read_csv_auto('{csv_path}', {csv_options})
                """)
            except Exception as e:
                error_msg = str(e)
                import re
                line_match = re.search(r'Line:\s*(\d+)', error_msg)
                if line_match:
                    line_no = line_match.group(1)
                    orig_match = re.search(r'Original Line:\s*(.*?)(?:\n|$)', error_msg)
                    detail = f" (内容: {orig_match.group(1)[:100]})" if orig_match else ""
                    raise Exception(f"第 {line_no} 行数据存在问题：{error_msg[:200]}{detail}") from e
                raise
        else:
            self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            self._conn.execute(f"""
                CREATE TABLE "{table_name}" AS
                SELECT * FROM read_csv_auto('{csv_path}', {csv_options})
            """)

        result = self._conn.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()
        return result[0]

    def import_xlsx(self, xlsx_path: str, table_name: str,
                    rename_mapping: Optional[Dict[str, str]] = None,
                    sheet_name: Optional[str] = None,
                    header_row: Optional[int] = None,
                    constant_columns: Optional[Dict[str, str]] = None) -> int:
        """
        导入 XLSX 文件（通过 Pandas 桥接）

        Args:
            xlsx_path: Excel 文件路径
            table_name: 目标表名
            rename_mapping: {源列名: 标准列名}
            sheet_name: 要导入的 sheet 名称
            header_row: 表头行号（0-indexed）
            constant_columns: 常量列 {列名: 值}，用于手动填写的字段（如公司名）

        Returns:
            导入的行数
        """
        kwargs = {}
        if sheet_name:
            kwargs['sheet_name'] = sheet_name
        if header_row is not None:
            kwargs['header'] = header_row
        df = pd.read_excel(xlsx_path, **kwargs)

        # 添加常量列（如手动填写的公司名）
        if constant_columns:
            for col_name, col_value in constant_columns.items():
                if col_name not in df.columns:
                    df[col_name] = col_value
                    print(f"[DUCKDB IMPORT_XLSX] 添加常量列 {col_name} = {col_value}")
        print(f"[DUCKDB IMPORT_XLSX] 读取 Excel: {len(df)} 行, {len(df.columns)} 列, 列名: {list(df.columns)}")
        if rename_mapping:
            df_cols_before = list(df.columns)
            mapped = [c for c in df_cols_before if c in rename_mapping]
            not_mapped = [c for c in df_cols_before if c not in rename_mapping]
            df = df.rename(columns=rename_mapping)
            print(f"[DUCKDB IMPORT_XLSX] 已映射: {mapped}, 未映射(已保留): {not_mapped}")
            print(f"[DUCKDB IMPORT_XLSX] 重命名后列: {list(df.columns)}")

        # 确保科目编号以文本形式存储，避免数字类型导致 ".0" 后缀
        if '科目编号' in df.columns:
            df['科目编号'] = df['科目编号'].apply(
                lambda x: str(int(x)) if pd.notna(x) and isinstance(x, (int, float)) and x == int(x)
                          else str(x) if pd.notna(x)
                          else None
            )

        self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
        self._conn.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM df')
        result = self._conn.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()
        print(f"[DUCKDB IMPORT_XLSX] 表 {table_name} 创建完成, {result[0]} 行")
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
            error_msg = str(e)
            # 提取 DuckDB 错误中的列名和表名，用于前端友好展示
            error_detail = {}
            import re
            col_match = re.search(r'column\s+"?([^"\s]+)"?', error_msg, re.IGNORECASE)
            if col_match:
                error_detail['column'] = col_match.group(1)
            table_match = re.search(r'table\s+"?([^"\s]+)"?', error_msg, re.IGNORECASE)
            if table_match:
                error_detail['table'] = table_match.group(1)
            line_match = re.search(r'Line:\s*(\d+)', error_msg)
            if line_match:
                error_detail['line'] = line_match.group(1)
            return {
                'success': False,
                'error': error_msg,
                'error_detail': error_detail if error_detail else None
            }

    def execute_paginated(self, sql: str, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        """
        分页执行查询

        Returns 格式同 execute()，额外包含 total_rows, total_pages
        """
        count_sql = f"SELECT COUNT(*) FROM ({sql}) AS _sub"
        count_result = self._conn.execute(count_sql).fetchone()
        total_rows = count_result[0] if count_result else 0
        total_pages = max(1, math.ceil(total_rows / page_size))

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
        """检查表或视图是否存在（包括临时视图）"""
        # 检查普通表和持久化视图
        result = self._conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            f"WHERE table_name = '{table_name}'"
        ).fetchone()
        if result and result[0] > 0:
            return True
        # 检查临时视图（DESCRIBE 对表和临时视图都有效）
        try:
            self._conn.execute(f'DESCRIBE "{table_name}"').fetchall()
            return True
        except Exception:
            return False

    def drop_table(self, table_name: str):
        """删除表"""
        self._conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')

    def trim_text_columns(self, table_name: str):
        """去除表中所有 VARCHAR 列的前后空格。"""
        try:
            schema = self.get_schema(table_name)
            text_cols = [col['name'] for col in schema
                         if any(t in col['type'].upper() for t in ['VARCHAR', 'TEXT'])]
            if not text_cols:
                return
            set_parts = [f'"{c}" = TRIM("{c}")' for c in text_cols]
            self._conn.execute(f'UPDATE "{table_name}" SET {", ".join(set_parts)}')
            print(f"[DUCKDB] 已去除 {table_name} 的 {len(text_cols)} 个文本列空格")
        except Exception as e:
            print(f"[DUCKDB] 文本列去空格失败 ({table_name}): {e}")

    def cleanup(self):
        """关闭连接并删除数据库文件"""
        try:
            if self._conn:
                self._conn.close()
                self._conn = None
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                print(f"[DUCKDB] 已删除数据库文件: {self.db_path}")
                return True
        except Exception as e:
            print(f"[DUCKDB] 文件清理失败: {e}")
        return False

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
        if hasattr(val, 'isoformat'):
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
            tokens = [t for t in re.split(r'\s+', stmt) if t]
            if not tokens:
                continue
            first_word = tokens[0].upper()
            if first_word not in ('SELECT', 'WITH', 'EXPLAIN', 'DESCRIBE', 'SHOW'):
                return False
        return True
