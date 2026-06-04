"""
预设筛选规则模块
从 temp/preset_rules.json 加载规则，支持规则包（pack）体系：
- 内置规则包（is_builtin=true）：通用、行业特征、EY GAM 等
- 自定义规则（custom_rules）：用户自行创建

API 返回 packs + custom_rules 结构，前端按包分组展示。
"""

import json
import os
import time
import uuid
from typing import Dict, List, Any, Optional

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_FILE = os.path.join(_APP_ROOT, 'temp', 'preset_rules.json')


def _load_data() -> dict:
    if not os.path.exists(RULES_FILE):
        return {'version': 2, 'packs': [], 'custom_rules': []}
    try:
        with open(RULES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {'version': 2, 'packs': [], 'custom_rules': []}


def _save_data(data: dict):
    os.makedirs(os.path.dirname(RULES_FILE), exist_ok=True)
    with open(RULES_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_packs() -> List[Dict[str, Any]]:
    """返回所有规则包（每个包内含 rules 列表）"""
    data = _load_data()
    return data.get('packs', [])


def get_custom_rules() -> List[Dict[str, Any]]:
    """返回自定义规则列表"""
    data = _load_data()
    return data.get('custom_rules', [])


def get_rules() -> List[Dict[str, Any]]:
    """扁平返回所有可用的规则（内置包规则 + 自定义规则）"""
    data = _load_data()
    rules = []
    for pack in data.get('packs', []):
        for rule in pack.get('rules', []):
            rule['_pack_id'] = pack['id']
            rule['_pack_name'] = pack['name']
            rule['_source'] = pack.get('source', '')
            rules.append(rule)
    rules.extend(data.get('custom_rules', []))
    return rules


def get_rule_by_id(rule_id: str) -> Optional[Dict[str, Any]]:
    for rule in get_rules():
        if rule.get('id') == rule_id:
            return rule
    return None


def get_pack_by_id(pack_id: str) -> Optional[Dict[str, Any]]:
    for pack in get_packs():
        if pack.get('id') == pack_id:
            return pack
    return None


def apply_rule(rule_id: str, param_values: Dict[str, str]) -> Optional[str]:
    """
    用传入参数填充 SQL 模板，返回生成的 SQL
    param_values: {param_name: value}
    """
    rule = get_rule_by_id(rule_id)
    if not rule:
        return None

    template = rule.get('sql_template', '')
    sql = template
    for param_name, value in param_values.items():
        sql = sql.replace('{' + param_name + '}', str(value))

    if '{' in sql and '}' in sql:
        return None

    return sql


def save_rule(rule_data: dict) -> dict:
    """
    保存自定义规则到 custom_rules 数组。
    如果 rule_data 有 id 且已存在则更新，否则新建。
    """
    data = _load_data()
    custom_rules = data.get('custom_rules', [])

    rule_id = rule_data.get('id', '').strip()
    if rule_id:
        for i, r in enumerate(custom_rules):
            if r.get('id') == rule_id:
                rule_data['is_custom'] = True
                rule_data['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                custom_rules[i] = {**r, **rule_data}
                data['custom_rules'] = custom_rules
                _save_data(data)
                return custom_rules[i]

    new_rule = {
        'id': rule_id or f'custom_{uuid.uuid4().hex[:8]}',
        'name': rule_data.get('name', '未命名规则'),
        'description': rule_data.get('description', ''),
        'category': rule_data.get('category', '自定义'),
        'sql_template': rule_data.get('sql_template', ''),
        'params': rule_data.get('params', []),
        'is_custom': True,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'updated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    custom_rules.append(new_rule)
    data['custom_rules'] = custom_rules
    _save_data(data)
    return new_rule


def delete_rule(rule_id: str) -> bool:
    """删除自定义规则"""
    data = _load_data()
    custom_rules = data.get('custom_rules', [])
    before = len(custom_rules)
    custom_rules = [r for r in custom_rules if r.get('id') != rule_id]
    if len(custom_rules) < before:
        data['custom_rules'] = custom_rules
        _save_data(data)
        return True
    return False
