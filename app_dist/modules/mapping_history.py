"""
持久化字段映射历史记录
保存到 temp/mapping_history.json，按文件名+大小哈希索引。
用于下次上传同结构文件时自动预填映射。
"""

import json
import os
import hashlib
import time
from typing import Dict, List, Any, Optional

HISTORY_PATH = os.path.join('temp', 'mapping_history.json')


def _load_entries() -> List[Dict[str, Any]]:
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('entries', [])
    except (json.JSONDecodeError, IOError):
        return []


def _save_entries(entries: List[Dict[str, Any]]):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'entries': entries}, f,
                  ensure_ascii=False, indent=2)


def _compute_key(filename: str, file_size: int) -> str:
    raw = f"{filename}_{file_size}".encode()
    return hashlib.md5(raw).hexdigest()


def save_mapping(
    filename: str,
    file_size: int,
    field_mapping: Dict[str, str],
    balance_field_mapping: Optional[Dict[str, str]] = None,
    original_columns: Optional[List[str]] = None,
    balance_original_columns: Optional[List[str]] = None,
):
    """保存或更新一条映射历史记录"""
    key = _compute_key(filename, file_size)
    entries = _load_entries()
    now = time.strftime('%Y-%m-%dT%H:%M:%S')

    entry = {
        'key': key,
        'filename': filename,
        'file_size': file_size,
        'original_columns': original_columns or [],
        'field_mapping': field_mapping,
        'balance_original_columns': balance_original_columns or [],
        'balance_field_mapping': balance_field_mapping or {},
        'updated_at': now,
    }

    for i, e in enumerate(entries):
        if e.get('key') == key:
            entry['created_at'] = e.get('created_at', now)
            entries[i] = entry
            _save_entries(entries)
            return

    entry['created_at'] = now
    entries.append(entry)
    _save_entries(entries)


def find_match(filename: str, file_size: int,
               original_columns: List[str]) -> Optional[Dict[str, Any]]:
    """查找匹配的历史映射记录"""
    key = _compute_key(filename, file_size)
    entries = _load_entries()
    col_set = set(original_columns)

    for entry in entries:
        if entry.get('key') == key and set(entry.get('original_columns', [])) == col_set:
            return entry
    return None
