"""
DuckDB 版文件分析和预览模块
替代 DataProcessor 中基于 pandas 的 upload 分析阶段。

设计要点：
1. CSV 只读一次：加载到 DuckDB 临时表后，后续所有操作查临时表
2. GBK 编码处理：检测到 GBK 先流式转 UTF-8，再交给 DuckDB
3. 列统计在 Python 层计算：取前 N 行样本后在 Python 里算，避免每列一条 SQL
"""

import os
import uuid
import duckdb


_TYPE_MAP = {
    'INTEGER': 'number', 'BIGINT': 'number', 'SMALLINT': 'number',
    'TINYINT': 'number', 'HUGEINT': 'number', 'FLOAT': 'number',
    'DOUBLE': 'number', 'DECIMAL': 'number', 'NUMERIC': 'number',
    'REAL': 'number',
    'DATE': 'date', 'TIMESTAMP': 'date', 'TIMESTAMP_S': 'date',
    'TIMESTAMP_MS': 'date', 'TIMESTAMP_NS': 'date',
    'TIME': 'date', 'TIMESTAMPTZ': 'date',
    'TIMESTAMP WITH TIME ZONE': 'date',
    'VARCHAR': 'text', 'TEXT': 'text', 'BLOB': 'text',
    'STRING': 'text',
    'BOOLEAN': 'text',
}

_DATE_KEYWORDS = ['日期', 'date', 'time', '时间', '年', '月', '日',
                  'period', '会计期间', '记账日期', '交易日期']

# DuckDB read_csv_auto 支持的编码列表
_DUCKDB_SUPPORTED_ENCODINGS = {'utf-8', 'latin-1', 'utf-16'}


def _detect_encoding(filepath: str) -> str:
    """检测 CSV 编码。
    返回 DuckDB read_csv_auto 支持的编码名（utf-8 / latin-1 / utf-16）。
    GBK 文件返回 'gbk'，由外层做转换。
    """
    # 读 8KB 采样（比之前 1KB 更不易在 UTF-8 多字节字符边界处截断）
    try:
        with open(filepath, 'rb') as f:
            raw = f.read(8192)
    except Exception:
        return 'utf-8'

    # BOM 标记
    if raw.startswith(b'\xef\xbb\xbf'):
        return 'utf-8'
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        return 'utf-16'

    # UTF-8 严格解码。若失败，可能是采样边界恰好截断了一个多字节字符：
    # 从尾部逐步丢弃最多 3 字节（UTF-8 单字符最长 3 字节）再试，
    # 能解则说明文件本身是 UTF-8，只是采样被截断。
    def _is_utf8(b: bytes) -> bool:
        try:
            b.decode('utf-8')
            return True
        except UnicodeDecodeError:
            for drop in (1, 2, 3):
                if len(b) > drop:
                    try:
                        b[:-drop].decode('utf-8')
                        return True
                    except UnicodeDecodeError:
                        continue
            return False

    if _is_utf8(raw):
        return 'utf-8'

    # GBK 严格解码（同样处理采样截断，GBK 单字符最长 2 字节）
    def _is_gbk(b: bytes) -> bool:
        try:
            b.decode('gbk')
            return True
        except UnicodeDecodeError:
            for drop in (1, 2):
                if len(b) > drop:
                    try:
                        b[:-drop].decode('gbk')
                        return True
                    except UnicodeDecodeError:
                        continue
            return False

    if _is_gbk(raw):
        return 'gbk'

    # GB18030 是 GBK 的超集，兼容 GBK 无法解码的专有字符（如 €、部分生僻字）。
    # 放在 GBK 之后，不会影响纯 GBK 文件的判断；仅当 GBK 解码失败时才尝试。
    # GB18030 单字符最长 4 字节。
    def _is_gb18030(b: bytes) -> bool:
        try:
            b.decode('gb18030')
            return True
        except UnicodeDecodeError:
            for drop in (1, 2, 3, 4):
                if len(b) > drop:
                    try:
                        b[:-drop].decode('gb18030')
                        return True
                    except UnicodeDecodeError:
                        continue
            return False

    if _is_gb18030(raw):
        return 'gb18030'

    # latin-1 永远能解（单字节映射），作为最后兜底
    return 'latin-1'


def _ensure_utf8_csv(path: str) -> str:
    """如果文件不是 DuckDB 直接支持的编码，转换为 UTF-8 临时文件。"""
    enc = _detect_encoding(path)
    if enc in _DUCKDB_SUPPORTED_ENCODINGS:
        return path  # DuckDB 可以直接读
    if enc in ('gbk', 'gb18030'):
        tmp_path = path + '.utf8'
        with open(path, 'r', encoding=enc) as fin, \
             open(tmp_path, 'w', encoding='utf-8', newline='') as fout:
            import shutil
            shutil.copyfileobj(fin, fout)
        return tmp_path
    # 兜底：DuckDB 用 latin-1 编码尝试读
    return path


def _map_duckdb_type(duckdb_type: str) -> str:
    """将 DuckDB 类型映射为 text/number/date。"""
    t = duckdb_type.upper().strip()
    for key, mapped in _TYPE_MAP.items():
        if key in t:
            return mapped
    return 'text'


def _xlsx_to_temp_csv(filepath: str, csv_dir: str,
                      sheet_name=None, header_row=None) -> str:
    """用 openpyxl 流式读取 XLSX 并写入临时 CSV，返回 CSV 路径。"""
    import openpyxl
    import csv as csv_module

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active

    header_row_idx = header_row if header_row is not None else 0
    headers = []
    valid_col_indices = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i < header_row_idx:
            continue
        if i == header_row_idx:
            for ci, c in enumerate(row):
                h = str(c).strip() if c else ''
                if h and not h.startswith('Unnamed'):
                    headers.append(h)
                    valid_col_indices.append(ci)
            break
    if not headers:
        wb.close()
        raise Exception("无法读取 Excel 表头行")

    os.makedirs(csv_dir, exist_ok=True)
    tmp_csv = os.path.join(csv_dir, f'_analysis_{uuid.uuid4().hex[:12]}.csv')
    with open(tmp_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv_module.writer(f)
        writer.writerow(headers)
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i <= header_row_idx:
                continue
            vals = [str(c).strip() if c is not None else '' for c in row]
            filtered = [vals[ci] if ci < len(vals) else '' for ci in valid_col_indices]
            writer.writerow(filtered)
    wb.close()
    return tmp_csv


class AnalysisEngine:
    """DuckDB 版文件分析和预览工具

    用法：
        engine = get_duckdb_engine()
        conn = engine.get_connection()
        analyzer = AnalysisEngine(filepath, conn)
        info = analyzer.analyze_all()  # 一次性返回 total_rows + fields + preview
        # 或用独立方法：
        preview = analyzer.get_preview_data(n=5)
        fields = analyzer.analyze_columns()
        total = analyzer.get_total_rows()
        analyzer.cleanup()
    """

    def __init__(self, filepath: str, conn: duckdb.DuckDBPyConnection,
                 csv_dir: str = 'temp'):
        self.filepath = filepath
        self.conn = conn
        self.csv_dir = csv_dir
        self.ext = os.path.splitext(filepath)[1].lower()
        self.cached_csv_path = None   # XLSX→CSV 缓存路径
        self._tmp_table = None         # DuckDB 临时表名
        self._tmp_utf8_path = None     # GBK→UTF-8 转换路径

    def _resolve_readable(self, sheet_name=None, header_row=None):
        """返回可被 DuckDB read_csv_auto 读取的 CSV 路径及已知编码。

        返回 (csv_path, known_encoding)：
        - XLSX 转出的临时 CSV 是程序用 UTF-8 写入的，known_encoding='utf-8'，
          不需要再走检测，避免采样截断误判。
        - CSV 文件需检测；GBK 文件先转 UTF-8，转后 known_encoding='utf-8'。
        - 其余情况 known_encoding=None，由调用方自行检测。
        """
        if self.ext == '.csv':
            path = self.filepath
            # GBK / GB18030 编码转换（GB18030 是 GBK 超集，含专有字符时检测返回 gb18030）
            if _detect_encoding(path) in ('gbk', 'gb18030'):
                self._tmp_utf8_path = _ensure_utf8_csv(path)
                return self._tmp_utf8_path, 'utf-8'
            return path, None
        elif self.ext == '.xlsx':
            if not self.cached_csv_path or not os.path.exists(self.cached_csv_path):
                self.cached_csv_path = _xlsx_to_temp_csv(
                    self.filepath, self.csv_dir,
                    sheet_name=sheet_name, header_row=header_row,
                )
            return self.cached_csv_path, 'utf-8'
        else:
            raise ValueError(f"不支持的文件类型: {self.ext}")

    def _load_table(self, sheet_name=None, header_row=None):
        """将数据加载到 DuckDB 临时表（CSV 只读一次）。
        始终用 all_varchar=true 避免 DuckDB 类型推断报错。
        后续的 get_total_rows / analyze_columns / get_preview_data 都查此表。
        """
        if self._tmp_table:
            return self._tmp_table

        csv_path, known_enc = self._resolve_readable(sheet_name=sheet_name,
                                                     header_row=header_row)
        tbl = f"_analysis_{uuid.uuid4().hex[:8]}"
        enc = known_enc or _detect_encoding(csv_path)
        enc_clause = f"encoding='{enc}'" if enc in _DUCKDB_SUPPORTED_ENCODINGS else ""

        self.conn.execute(f"""
            CREATE OR REPLACE TEMP TABLE "{tbl}" AS
            SELECT * FROM read_csv_auto('{csv_path}',
                header=true, {enc_clause}, all_varchar=true)
        """)
        self._tmp_table = tbl
        return tbl

    # ── 公共方法 ──

    def get_total_rows(self, sheet_name=None, header_row=None) -> int:
        """获取数据总行数（查临时表或直接 COUNT CSV）。"""
        if self._tmp_table:
            result = self.conn.execute(
                f'SELECT COUNT(*) FROM "{self._tmp_table}"'
            ).fetchone()
            return result[0] if result else 0

        csv_path, known_enc = self._resolve_readable(sheet_name=sheet_name,
                                                     header_row=header_row)
        enc = known_enc or _detect_encoding(csv_path)
        enc_clause = f"encoding='{enc}'" if enc in _DUCKDB_SUPPORTED_ENCODINGS else ""
        result = self.conn.execute(
            f"SELECT COUNT(*) FROM read_csv_auto('{csv_path}', "
            f"header=true, {enc_clause}, all_varchar=true)"
        ).fetchone()
        return result[0] if result else 0

    def get_preview_data(self, n: int = 5,
                         sheet_name=None, header_row=None):
        """获取前 n 行预览数据，返回 [{col: val}, ...]。"""
        if self._tmp_table:
            result = self.conn.execute(
                f'SELECT * FROM "{self._tmp_table}" LIMIT {n}'
            )
        else:
            csv_path, known_enc = self._resolve_readable(sheet_name=sheet_name,
                                                         header_row=header_row)
            enc = known_enc or _detect_encoding(csv_path)
            enc_clause = f"encoding='{enc}'" if enc in _DUCKDB_SUPPORTED_ENCODINGS else ""
            result = self.conn.execute(
                f"SELECT * FROM read_csv_auto('{csv_path}', "
                f"header=true, {enc_clause}, all_varchar=true) LIMIT {n}"
            )

        columns = [desc[0] for desc in result.description]
        rows = result.fetchall()
        preview = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                val = row[i]
                if val is None:
                    row_dict[col] = None
                elif isinstance(val, (int, float)):
                    row_dict[col] = val
                else:
                    s = str(val)
                    if len(s) > 100:
                        s = s[:100] + '...'
                    row_dict[col] = s
            preview.append(row_dict)
        return preview

    def analyze_columns(self, n_sample: int = 100,
                        sheet_name=None, header_row=None):
        """分析列信息，返回 list[dict]。

        CSV 在此方法中被加载到临时表一次（all_varchar=true），
        类型推断在 Python 层处理，避免 DuckDB 类型转换报错。
        """
        # 1) 加载数据到临时表（CSV 只读一次）
        tbl = self._load_table()

        # 2) 取前 n_sample 行到 Python 做分析
        sample = self.conn.execute(
            f'SELECT * FROM "{tbl}" LIMIT {n_sample}'
        )
        sample_columns = [desc[0] for desc in sample.description]
        sample_rows = sample.fetchall()

        if not sample_rows:
            return [
                {'name': col, 'type': 'text',
                 'non_null_count': 0, 'null_count': 0,
                 'unique_count': 0, 'sample': None}
                for col in sample_columns
            ]

        # 3) 逐列推断类型（Python 层，不用 DuckDB 的 DESCRIBE 类型）
        import re as _re
        from datetime import datetime as _dt

        fields = []
        for ci, col in enumerate(sample_columns):
            raw_vals = []
            for r in sample_rows:
                v = r[ci]
                if v is not None:
                    s = str(v).strip()
                    if s:
                        raw_vals.append(s)

            non_null = len(raw_vals)
            nulls = n_sample - non_null
            uniques = len(set(raw_vals))
            sample_val = raw_vals[0] if raw_vals else None
            if isinstance(sample_val, str) and len(sample_val) > 100:
                sample_val = sample_val[:100] + '...'

            # ---- Python 层类型推断 ----
            field_type = 'text'

            # ① 日期关键词 + 实际值检测
            if any(kw in col.lower() for kw in _DATE_KEYWORDS):
                date_count = 0
                for v in raw_vals[:20]:
                    try:
                        _dt.strptime(v[:10], '%Y-%m-%d')
                        date_count += 1
                    except (ValueError, IndexError):
                        try:
                            _dt.strptime(v[:10], '%Y/%m/%d')
                            date_count += 1
                        except (ValueError, IndexError):
                            pass
                if date_count > len(raw_vals[:20]) * 0.5:
                    field_type = 'date'

            # ② 数值检测
            if field_type == 'text':
                num_count = 0
                for v in raw_vals[:50]:
                    try:
                        float(v.replace(',', '').replace(' ', ''))
                        num_count += 1
                    except (ValueError, TypeError):
                        pass
                if num_count > len(raw_vals[:50]) * 0.5:
                    field_type = 'number'

            fields.append({
                'name': col,
                'type': field_type,
                'non_null_count': non_null,
                'null_count': nulls,
                'unique_count': uniques,
                'sample': sample_val,
            })

        return fields

    def analyze_all(self, n_sample: int = 100,
                    sheet_name=None, header_row=None):
        """一键分析：total_rows + analyze_columns + get_preview_data。
        数据只读一次。
        """
        # 加载数据（CSV 只读一次，sheet_name/header_row 必须传，否则多 sheet XLSX 会读错）
        self._load_table(sheet_name=sheet_name, header_row=header_row)

        # 总行数
        total = self.conn.execute(
            f'SELECT COUNT(*) FROM "{self._tmp_table}"'
        ).fetchone()
        total_rows = total[0] if total else 0

        # 列分析（查临时表，不复读 CSV）
        fields = self.analyze_columns(n_sample=n_sample,
                                      sheet_name=sheet_name,
                                      header_row=header_row)

        # 预览（查临时表）
        preview = self.get_preview_data(n=5)

        return {
            'total_rows': total_rows,
            'fields': fields,
            'preview': preview,
        }

    def cleanup(self):
        """清理所有临时资源：临时表 + 缓存 CSV + UTF-8 转换临时文件。"""
        # 删除 DuckDB 临时表
        if self._tmp_table:
            try:
                self.conn.execute(f'DROP TABLE IF EXISTS "{self._tmp_table}"')
            except Exception:
                pass
            self._tmp_table = None

        # 删除 XLSX 缓存 CSV
        if self.cached_csv_path and os.path.exists(self.cached_csv_path):
            try:
                os.remove(self.cached_csv_path)
            except Exception:
                pass
            self.cached_csv_path = None

        # 删除 GBK→UTF-8 转换临时文件
        if self._tmp_utf8_path and os.path.exists(self._tmp_utf8_path):
            try:
                os.remove(self._tmp_utf8_path)
            except Exception:
                pass
            self._tmp_utf8_path = None
