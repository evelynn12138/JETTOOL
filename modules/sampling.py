"""
审计取样模块 - 定义取样方法数据结构和 SQL 生成
Mock 实现：实际对 DuckDB 执行随机查询获取样本
"""

from typing import Dict, List, Any, Optional


def get_methods() -> List[Dict[str, Any]]:
    return [
        {
            "id": "monetary_unit_sampling",
            "name": "货币单位抽样 (MUS)",
            "description": "按金额大小进行概率抽样，金额越大的交易被抽中的概率越高",
            "params": [
                {"name": "sample_size", "label": "样本量", "type": "number", "default": 50},
                {"name": "amount_field", "label": "金额字段", "type": "field_selector", "default": "金额"},
            ],
        },
        {
            "id": "random_sampling",
            "name": "随机抽样",
            "description": "从全量数据中随机抽取指定数量的样本",
            "params": [
                {"name": "sample_size", "label": "样本量", "type": "number", "default": 100},
            ],
        },
        {
            "id": "stratified_sampling",
            "name": "分层抽样",
            "description": "按指定分层字段将数据分组，从每组中等比例随机抽取样本",
            "params": [
                {"name": "sample_size", "label": "样本量", "type": "number", "default": 100},
                {"name": "stratum_field", "label": "分层字段", "type": "field_selector", "default": "科目名称"},
            ],
        },
        {
            "id": "directed_selection",
            "name": "定向选取",
            "description": "根据指定条件定向选取特定交易记录（如金额大于某个阈值）",
            "params": [
                {"name": "amount_field", "label": "金额字段", "type": "field_selector", "default": "金额"},
                {"name": "min_amount", "label": "最小金额", "type": "number", "default": 100000},
                {"name": "max_count", "label": "最大条数", "type": "number", "default": 50},
            ],
        },
    ]


def generate_sql(method_id: str, params: Dict[str, str],
                 table_name: str = 'data') -> Optional[str]:
    if method_id == 'monetary_unit_sampling':
        amount_field = params.get('amount_field', '金额')
        sample_size = int(params.get('sample_size', 50))
        return f'''
        SELECT * FROM (
            SELECT *, ABS(CAST("{amount_field}" AS DOUBLE)) AS "_mus_weight_"
            FROM "{table_name}"
        ) sub
        ORDER BY "_mus_weight_" DESC
        LIMIT {sample_size}
        '''

    elif method_id == 'random_sampling':
        sample_size = int(params.get('sample_size', 100))
        return f'''
        SELECT * FROM "{table_name}"
        ORDER BY random()
        LIMIT {sample_size}
        '''

    elif method_id == 'stratified_sampling':
        sample_size = int(params.get('sample_size', 100))
        stratum_field = params.get('stratum_field', '科目名称')
        return f'''
        SELECT * FROM (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY "{stratum_field}" ORDER BY random()) AS _rn,
                COUNT(*) OVER (PARTITION BY "{stratum_field}") AS _grp_cnt
            FROM "{table_name}"
        ) sub
        WHERE _rn <= GREATEST(1, CAST({sample_size} * _grp_cnt * 1.0 / (SELECT COUNT(*) FROM "{table_name}") AS INTEGER))
        '''

    elif method_id == 'directed_selection':
        amount_field = params.get('amount_field', '金额')
        min_amount = float(params.get('min_amount', 100000))
        max_count = int(params.get('max_count', 50))
        return f'''
        SELECT * FROM "{table_name}"
        WHERE ABS(CAST("{amount_field}" AS DOUBLE)) >= {min_amount}
        ORDER BY ABS(CAST("{amount_field}" AS DOUBLE)) DESC
        LIMIT {max_count}
        '''

    return None
