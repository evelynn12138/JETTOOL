"""
同义词词典模块 - 财务关键词的同义词扩展

用于查询优化时自动补充财务术语的同义词、英文缩写、常见变体，
帮助 AI 生成更全面的 SQL 查询条件。
"""

# 核心同义词映射
SYNONYM_MAP = {
    # === 调整/冲销类 ===
    "调整": ["调", "adj", "adjustment"],
    "冲销": ["冲", "冲销", "reverse", "reversal", "storno"],
    "红冲": ["红冲", "冲红", "负数冲销"],
    # === 结转类 ===
    "结转": ["结转", "转结", "carry forward", "carryforward"],
    "损益": ["损益", "profit and loss", "pl", "p&l"],
    # === 常用会计科目 ===
    "管理费用": ["管理费", "管理经费"],
    "销售费用": ["销售费", "营业费用"],
    "财务费用": ["财务费"],
    "主营业务收入": ["主营收入", "销售收入"],
    "主营业务成本": ["主营成本", "销售成本"],
    "应收账款": ["应收"],
    "应付账款": ["应付"],
    "固定资产": ["固资"],
    "累计折旧": ["折旧"],
    # === 金额/数量 ===
    "大于": [">", "超过", "以上"],
    "小于": ["<", "不足", "以下", "不超过"],
    "等于": ["=", "等于"],
    "合计": ["汇总", "总金额", "总和", "总额"],
    # === 时间 ===
    "年初": ["年初", "期初", "年初余额"],
    "年末": ["年末", "期末", "年末余额"],
    "本期": ["本期", "当月", "当月度"],
    "累计": ["累计", "本年累计"],
    # === 凭证 ===
    "凭证": ["凭证", "记账凭证", "voucher"],
    "制单": ["制单", "制单人", "记账人"],
    "审核": ["审核", "复核", "审阅"],
}


def find_keywords(text: str) -> list:
    """
    从文本中找出所有命中同义词词典的片段。

    Returns:
        [{'standard': str, 'variants': [str], 'start': int, 'end': int}, ...]
    """
    text_lower = text.lower()
    results = []

    # 按长度降序排列标准词（优先匹配长词，避免短词覆盖）
    sorted_terms = sorted(SYNONYM_MAP.keys(), key=len, reverse=True)
    occupied = set()  # 已占用的字符位置（防止重叠匹配）

    for std in sorted_terms:
        if occupied:
            # 跳过已完全覆盖的位置区间（性能优化）
            pass
        # 查找标准词在文本中的所有出现位置
        pattern = std.lower()
        start = 0
        while True:
            idx = text_lower.find(pattern, start)
            if idx < 0:
                break
            # 检查是否被已有匹配覆盖
            if not any(i in occupied for i in range(idx, idx + len(std))):
                for i in range(idx, idx + len(std)):
                    occupied.add(i)
                results.append({
                    'standard': std,
                    'variants': [v for v in SYNONYM_MAP.get(std, []) if v != std],
                    'start': idx,
                    'end': idx + len(std),
                })
                break  # 每个标准词只在文本中扩展一次
            start = idx + 1

    results.sort(key=lambda x: x['start'])
    return results


def expand_keywords(text: str) -> str:
    """
    将文本中的财务关键词扩展为含同义词的自然语句。
    匹配到的关键词后面追加等和相关关键词，不产生会导致 SQL 混淆的括号标注。

    Example:
        "筛选包含调整和冲销的凭证"
        → "筛选包含调整、冲销、reverse、adj、adjustment、reversal等相关关键词的凭证"
    """
    matches = find_keywords(text)
    if not matches:
        return text

    # 收集所有命中的标准词和其同义词
    seen_terms = set()
    all_terms = []
    for m in matches:
        std = m['standard']
        if std in seen_terms:
            continue
        seen_terms.add(std)
        all_terms.append(std)
        for v in m['variants']:
            if v not in seen_terms:
                seen_terms.add(v)
                all_terms.append(v)

    # 在文本末尾追加"等相关关键词"
    suffix = '、' + '、'.join(all_terms) + '等相关关键词'
    return text + suffix


if __name__ == '__main__':
    tests = [
        "筛选出摘要中包含调整和冲销的凭证",
        "计算管理费用本年累计金额",
        "查找管理费用累计折旧大于10000的记录",
        "查找结转损益凭证",
    ]
    for t in tests:
        print(f"原始: {t}")
        print(f"扩展: {expand_keywords(t)}")
        print()
