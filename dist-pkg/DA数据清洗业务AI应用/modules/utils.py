import os
import json
import hashlib
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Union
import pandas as pd
import numpy as np

class FileUtils:
    """文件工具类"""

    @staticmethod
    def get_file_hash(filepath: str) -> str:
        """
        计算文件哈希值

        Args:
            filepath: 文件路径

        Returns:
            文件哈希值
        """
        hash_md5 = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    @staticmethod
    def safe_delete(filepath: str) -> bool:
        """
        安全删除文件

        Args:
            filepath: 文件路径

        Returns:
            是否成功删除
        """
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
                return True
            return False
        except:
            return False

    @staticmethod
    def create_temp_dir() -> str:
        """
        创建临时目录

        Returns:
            临时目录路径
        """
        temp_dir = tempfile.mkdtemp(prefix='finance_query_')
        return temp_dir

    @staticmethod
    def cleanup_temp_dir(dirpath: str) -> bool:
        """
        清理临时目录

        Args:
            dirpath: 目录路径

        Returns:
            是否成功清理
        """
        try:
            if os.path.exists(dirpath):
                shutil.rmtree(dirpath)
                return True
            return False
        except:
            return False

    @staticmethod
    def get_file_info(filepath: str) -> Dict[str, Any]:
        """
        获取文件信息

        Args:
            filepath: 文件路径

        Returns:
            文件信息字典
        """
        try:
            stat = os.stat(filepath)
            return {
                'filename': os.path.basename(filepath),
                'size': stat.st_size,
                'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'extension': os.path.splitext(filepath)[1].lower(),
                'path': filepath
            }
        except Exception as e:
            return {
                'filename': os.path.basename(filepath),
                'error': str(e)
            }

class DataUtils:
    """数据工具类"""

    @staticmethod
    def detect_encoding(filepath: str) -> str:
        """
        检测文件编码

        Args:
            filepath: 文件路径

        Returns:
            检测到的编码
        """
        encodings = ['utf-8', 'gbk', 'gb2312', 'latin1', 'cp1252']

        for encoding in encodings:
            try:
                with open(filepath, 'r', encoding=encoding) as f:
                    f.read(1024)
                return encoding
            except UnicodeDecodeError:
                continue

        return 'utf-8'  # 默认编码

    @staticmethod
    def convert_to_dataframe(data: Any) -> pd.DataFrame:
        """
        将各种数据类型转换为DataFrame

        Args:
            data: 输入数据

        Returns:
            DataFrame
        """
        if isinstance(data, pd.DataFrame):
            return data.copy()
        elif isinstance(data, dict):
            # 单个字典
            if all(isinstance(v, (list, tuple, pd.Series)) for v in data.values()):
                return pd.DataFrame(data)
            else:
                return pd.DataFrame([data])
        elif isinstance(data, list):
            if len(data) == 0:
                return pd.DataFrame()
            elif all(isinstance(item, dict) for item in data):
                return pd.DataFrame(data)
            else:
                return pd.DataFrame({'value': data})
        elif isinstance(data, pd.Series):
            return pd.DataFrame(data)
        else:
            try:
                return pd.DataFrame(data)
            except:
                return pd.DataFrame({'value': [data]})

    @staticmethod
    def dataframe_to_dict(df: pd.DataFrame, max_rows: int = 1000) -> Dict[str, Any]:
        """
        将DataFrame转换为字典

        Args:
            df: DataFrame
            max_rows: 最大行数限制

        Returns:
            字典格式的数据
        """
        if len(df) > max_rows:
            df = df.head(max_rows)

        return {
            'columns': list(df.columns),
            'data': df.to_dict('records'),
            'shape': df.shape,
            'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()}
        }

    @staticmethod
    def calculate_statistics(df: pd.DataFrame) -> Dict[str, Any]:
        """
        计算数据统计信息

        Args:
            df: DataFrame

        Returns:
            统计信息字典
        """
        stats = {
            'row_count': int(len(df)),
            'column_count': int(len(df.columns)),
            'missing_values': {},
            'numeric_stats': {},
            'date_stats': {},
            'text_stats': {}
        }

        # 缺失值统计
        for col in df.columns:
            missing_count = int(df[col].isnull().sum())
            if missing_count > 0:
                stats['missing_values'][col] = missing_count

        # 数值列统计
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            col_stats = df[col].describe().to_dict()
            # 转换为Python原生类型
            stats['numeric_stats'][col] = {
                'count': int(col_stats.get('count', 0)),
                'mean': float(col_stats.get('mean', 0)),
                'std': float(col_stats.get('std', 0)),
                'min': float(col_stats.get('min', 0)),
                '25%': float(col_stats.get('25%', 0)),
                '50%': float(col_stats.get('50%', 0)),
                '75%': float(col_stats.get('75%', 0)),
                'max': float(col_stats.get('max', 0)),
                'sum': float(df[col].sum())
            }

        # 日期列统计
        date_cols = []
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                date_cols.append(col)

        for col in date_cols:
            stats['date_stats'][col] = {
                'min': df[col].min().isoformat() if not pd.isna(df[col].min()) else None,
                'max': df[col].max().isoformat() if not pd.isna(df[col].max()) else None,
                'range_days': (df[col].max() - df[col].min()).days if len(df[col].dropna()) > 0 else 0
            }

        # 文本列统计
        text_cols = df.select_dtypes(include=['object']).columns
        for col in text_cols:
            unique_count = int(df[col].nunique())
            stats['text_stats'][col] = {
                'unique_count': unique_count,
                'most_common': df[col].value_counts().head(5).to_dict()
            }

        return stats

    @staticmethod
    def clean_financial_data(df: pd.DataFrame) -> pd.DataFrame:
        """
        清理财务数据

        Args:
            df: 原始DataFrame

        Returns:
            清理后的DataFrame
        """
        cleaned_df = df.copy()

        # 清理列名
        cleaned_df.columns = cleaned_df.columns.str.strip()
        cleaned_df.columns = cleaned_df.columns.str.replace(r'[^\w\s]', '', regex=True)

        # 清理日期列
        date_keywords = ['日期', 'date', '时间', '记账日期', '交易日期']
        for col in cleaned_df.columns:
            col_lower = col.lower()
            if any(keyword in col_lower for keyword in date_keywords):
                try:
                    cleaned_df[col] = pd.to_datetime(cleaned_df[col], errors='coerce')
                except:
                    pass

        # 清理金额列
        amount_keywords = ['金额', 'amount', '借方', 'debit', '贷方', 'credit', 'money', '价格']
        for col in cleaned_df.columns:
            col_lower = col.lower()
            if any(keyword in col_lower for keyword in amount_keywords):
                if cleaned_df[col].dtype == 'object':
                    # 去除货币符号和千分位分隔符
                    cleaned_df[col] = cleaned_df[col].astype(str).str.replace(r'[^\d.-]', '', regex=True)
                cleaned_df[col] = pd.to_numeric(cleaned_df[col], errors='coerce')
                cleaned_df[col] = cleaned_df[col].fillna(0)

        # 清理文本列
        text_keywords = ['摘要', '科目', '凭证号', '部门', '人员', '说明', '备注']
        for col in cleaned_df.columns:
            col_lower = col.lower()
            if any(keyword in col_lower for keyword in text_keywords):
                cleaned_df[col] = cleaned_df[col].astype(str).str.strip()
                cleaned_df[col] = cleaned_df[col].replace({'nan': '', 'None': '', 'NaN': ''})

        # 删除全空列
        cleaned_df = cleaned_df.dropna(axis=1, how='all')

        # 删除全空行
        cleaned_df = cleaned_df.dropna(axis=0, how='all')

        return cleaned_df

class SessionUtils:
    """会话工具类"""

    @staticmethod
    def create_session_id() -> str:
        """
        创建会话ID

        Returns:
            会话ID
        """
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        random_str = hashlib.md5(str(os.urandom(16)).encode()).hexdigest()[:8]
        return f"session_{timestamp}_{random_str}"

    @staticmethod
    def get_session_info(session_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        获取会话信息

        Args:
            session_data: 会话数据

        Returns:
            会话信息
        """
        info = {
            'session_id': session_data.get('session_id', 'unknown'),
            'created_at': session_data.get('created_at', datetime.now().isoformat()),
            'data_file': session_data.get('data_file', None),
            'field_mapping': session_data.get('field_mapping', {}),
            'api_key_configured': bool(session_data.get('api_key', False)),
            'query_count': len(session_data.get('query_history', []))
        }

        # 计算会话年龄
        if 'created_at' in session_data:
            created_at = datetime.fromisoformat(session_data['created_at'])
            age = datetime.now() - created_at
            info['age_hours'] = age.total_seconds() / 3600
            info['age_minutes'] = age.total_seconds() / 60

        return info

    @staticmethod
    def cleanup_old_sessions(sessions_dir: str, max_age_hours: int = 24) -> List[str]:
        """
        清理旧会话

        Args:
            sessions_dir: 会话目录
            max_age_hours: 最大保留时间（小时）

        Returns:
            已清理的会话列表
        """
        cleaned_sessions = []

        if not os.path.exists(sessions_dir):
            return cleaned_sessions

        for filename in os.listdir(sessions_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(sessions_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        session_data = json.load(f)

                    created_at = datetime.fromisoformat(session_data.get('created_at', '2000-01-01'))
                    age = datetime.now() - created_at

                    if age.total_seconds() > max_age_hours * 3600:
                        # 删除会话文件
                        os.remove(filepath)
                        cleaned_sessions.append(filename)
                except:
                    # 如果无法读取，也删除
                    try:
                        os.remove(filepath)
                        cleaned_sessions.append(filename)
                    except:
                        pass

        return cleaned_sessions

class ExportUtils:
    """导出工具类"""

    @staticmethod
    def export_to_excel(data: Any, filepath: str) -> str:
        """
        导出数据到Excel

        Args:
            data: 数据（DataFrame、字典列表等）
            filepath: 导出文件路径

        Returns:
            导出文件路径
        """
        df = DataUtils.convert_to_dataframe(data)

        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='数据', index=False)

            # 添加统计信息
            stats_df = pd.DataFrame([DataUtils.calculate_statistics(df)])
            stats_df.to_excel(writer, sheet_name='统计信息', index=False)

        return filepath

    @staticmethod
    def export_to_csv(data: Any, filepath: str) -> str:
        """
        导出数据到CSV

        Args:
            data: 数据
            filepath: 导出文件路径

        Returns:
            导出文件路径
        """
        df = DataUtils.convert_to_dataframe(data)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        return filepath

    @staticmethod
    def create_export_package(data: Any, output_dir: str,
                             include_stats: bool = True) -> str:
        """
        创建导出包（包含数据和统计信息）

        Args:
            data: 数据
            output_dir: 输出目录
            include_stats: 是否包含统计信息

        Returns:
            压缩包路径
        """
        import zipfile

        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix='export_')

        try:
            # 导出数据
            data_file = os.path.join(temp_dir, 'data.xlsx')
            ExportUtils.export_to_excel(data, data_file)

            # 导出统计信息（如果需要）
            if include_stats:
                df = DataUtils.convert_to_dataframe(data)
                stats = DataUtils.calculate_statistics(df)

                stats_file = os.path.join(temp_dir, 'statistics.json')
                with open(stats_file, 'w', encoding='utf-8') as f:
                    json.dump(stats, f, ensure_ascii=False, indent=2)

            # 创建README
            readme_file = os.path.join(temp_dir, 'README.txt')
            with open(readme_file, 'w', encoding='utf-8') as f:
                f.write("DA数据清洗业务AI应用数据导出包\n")
                f.write("=" * 40 + "\n")
                f.write(f"导出时间: {datetime.now().isoformat()}\n")
                f.write(f"数据记录数: {len(df)}\n")
                f.write(f"数据字段数: {len(df.columns)}\n")
                f.write("\n文件说明:\n")
                f.write("- data.xlsx: 主数据文件\n")
                if include_stats:
                    f.write("- statistics.json: 统计信息文件\n")
                f.write("\n注意事项:\n")
                f.write("1. 此文件由DA数据清洗业务AI应用系统生成\n")
                f.write("2. 数据已进行基本清洗处理\n")
                f.write("3. 建议使用Excel或文本编辑器打开\n")

            # 创建压缩包
            zip_path = os.path.join(output_dir, f"finance_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, temp_dir)
                        zipf.write(file_path, arcname)

            return zip_path

        finally:
            # 清理临时目录
            shutil.rmtree(temp_dir, ignore_errors=True)