"""
审计轨迹模块 - 记录用户查询和 SQL 执行历史
JSONL 格式追加写入 temp/audit_trail.jsonl
"""

import json
import os
import time
from typing import Optional

AUDIT_FILE = os.path.join('temp', 'audit_trail.jsonl')


def _append(entry: dict):
    os.makedirs(os.path.dirname(AUDIT_FILE), exist_ok=True)
    try:
        with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except IOError as e:
        print(f"[AUDIT_TRAIL] 写入失败: {e}")


def log_generate(session_id: str, user_query: str, generated_sql: str,
                 success: bool, error: Optional[str] = None):
    """记录 /api/generate-code 调用"""
    _append({
        'event': 'generate_code',
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'session_id': session_id,
        'user_query': user_query,
        'generated_sql': generated_sql,
        'success': success,
        'error': error,
    })


def log_execute(session_id: str, sql: str, success: bool,
                row_count: Optional[int] = None,
                execution_time: Optional[float] = None,
                error: Optional[str] = None):
    """记录 /api/execute 调用"""
    _append({
        'event': 'execute_sql',
        'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'session_id': session_id,
        'sql': sql,
        'success': success,
        'row_count': row_count,
        'execution_time': execution_time,
        'error': error,
    })
