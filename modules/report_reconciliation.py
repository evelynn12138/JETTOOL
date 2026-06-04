"""
科目余额表 ↔ 报表期末余额核对

双阶段设计:
  阶段1 — 映射: 规则引擎给科目余额表每行打上"报表科目名称"标签
  阶段2 — 核对: 按报表科目汇总 → 逐项比对 → 输出差异

前端交互:
  左侧: 科目余额表（科目编号|科目名称|期末余额|可编辑的报表科目名称）
  右侧: 核对结果（报表科目|报表期末|余额表汇总|差异）
  用户可自行修改左侧"报表科目名称"，点击"刷新核对"重新计算
"""

import re
import json as json_module
import copy
from typing import Optional, List
from difflib import SequenceMatcher


class ReconciliationEngine:
    """科目余额表 ↔ 报表核对引擎"""

    # ── 科目编号前缀 → 报表项目映射 ──
    ACCOUNT_CODE_RULES = {
        "1001": "货币资金", "1002": "货币资金", "1012": "货币资金",
        "1015": "货币资金", "1021": "货币资金",
        "1101": "交易性金融资产",
        "1121": "应收票据", "1122": "应收账款", "1231": "应收账款",
        "1123": "预付款项",
        "1131": "应收股利", "1132": "应收利息","1201": "其他流动资产",
        "1221": "其他应收款",
        "1401": "存货", "1402": "存货", "1403": "存货",
        "1404": "存货", "1405": "存货", "1406": "存货",
        "1407": "存货", "1408": "存货", "1411": "存货",
        "1412": "存货", "1461": "存货", "1471": "存货",
        "1501": "持有至到期投资", "1503": "可供出售金融资产",
        "1511": "长期股权投资", "1512": "长期股权投资",
        "1521": "投资性房地产",
        "1601": "固定资产", "1602": "固定资产", "1603": "固定资产",
        "1604": "在建工程", "1605": "工程物资", "1606": "固定资产清理",
        "1701": "无形资产", "1702": "累计摊销", "1703": "无形资产减值准备",
        "1801": "长期待摊费用", "1811": "递延所得税资产",
        "1901": "其他非流动资产",
        "2001": "短期借款", "2101": "交易性金融负债",
        "2201": "应付票据", "2202": "应付账款", "2203": "预收款项",
        "2211": "应付职工薪酬", "2221": "应交税费",
        "2231": "应付利息", "2232": "应付股利", "2241": "其他应付款",
        "2401": "长期借款", "2501": "应付债券",
        "2701": "长期应付款", "2702": "专项应付款",
        "2901": "递延所得税负债", "2911": "预计负债",
        "4001": "实收资本（或股本）", "4002": "资本公积",
        "4101": "盈余公积", "4103": "未分配利润", "4104": "未分配利润",
        "5001": "存货", "5101": "存货", "5201": "存货",
        # === 利润表科目（6xxx 损益类） ===
        "6001": "营业收入",
        "6002": "营业外收入",
        "6003": "营业收入",
        "6011": "营业收入",
        "6041": "营业收入",
        "6051": "营业收入",
        "6101": "公允价值变动收益",
        "6111": "投资收益",
        "6301": "营业外收入",
        "6401": "营业成本",
        "6402": "营业外支出",
        "6403": "税金及附加",
        "6601": "销售费用",
        "6602": "管理费用",
        "6603": "财务费用",
        "6604": "管理费用",
        "6611": "研发费用",
        "6621": "资产减值损失",
        "6701": "信用减值损失",
        "6711": "营业外支出",
        "6801": "所得税费用",
        "6901": "以前年度损益调整",
    }

    # ── 科目名称关键词 → 报表项目映射 ──
    ACCOUNT_NAME_RULES = [
        (["现金", "银行存款", "货币资金", "其他货币资金"], "货币资金"),
        (["应收票据"], "应收票据"),
        (["应收账款", "应收帐款", "坏账准备"], "应收账款"),
        (["预付"], "预付款项"),
        (["材料", "采购", "原材料", "商品", "库存商品", "发出商品",
          "在产品", "产成品", "自制半成品", "周转材料", "包装物",
          "存货", "跌价准备", "生产成本", "制造费用"], "存货"),
        (["固定资产", "累计折旧", "减值准备", "工程"], "固定资产"),
        (["在建工程"], "在建工程"),
        (["无形资产", "累计摊销"], "无形资产"),
        (["其他应收"], "其他应收款"),
        (["应付票据"], "应付票据"),
        (["应付账款", "应付帐款"], "应付账款"),
        (["预收"], "预收款项"),
        (["其他应付"], "其他应付款"),
        (["职工薪酬", "应付工资", "应付薪酬", "工资"], "应付职工薪酬"),
        (["应交", "税费", "税金"], "应交税费"),
        (["短期借款"], "短期借款"),
        (["长期借款"], "长期借款"),
        (["实收资本", "股本"], "实收资本（或股本）"),
        (["资本公积"], "资本公积"),
        (["盈余公积"], "盈余公积"),
        (["未分配利润", "本年利润", "利润分配"], "未分配利润"),
        (["长期待摊"], "长期待摊费用"),
        (["长期应付"], "长期应付款"),
        (["预计负债"], "预计负债"),
        (["递延所得税资产"], "递延所得税资产"),
        (["递延所得税负债"], "递延所得税负债"),
        (["应付债券"], "应付债券"),
        # === 利润表关键词 ===
        (["主营业务收入", "营业收入", "其他业务收入", "利息收入",
          "手续费收入", "保费收入", "汇兑收益"], "营业收入"),
        (["营业外收入"], "营业外收入"),
        (["主营业务成本", "营业成本", "其他业务成本", "利息支出",
          "手续费支出", "赔付支出"], "营业成本"),
        (["营业外支出"], "营业外支出"),
        (["税金及附加"], "税金及附加"),
        (["销售费用", "营业费用", "销售服务费"], "销售费用"),
        (["管理费用", "办公费", "差旅费", "业务招待费", "会议费",
          "中介费", "咨询费"], "管理费用"),
        (["财务费用", "利息支出", "利息费用", "汇兑损益",
          "银行手续费"], "财务费用"),
        (["研发费用", "研发支出", "开发支出", "研究费用"], "研发费用"),
        (["投资收益"], "投资收益"),
        (["公允价值变动"], "公允价值变动收益"),
        (["信用减值", "坏账准备", "坏帐准备"], "信用减值损失"),
        (["资产减值"], "资产减值损失"),
        (["营业外收入", "政府补助", "补贴收入"], "营业外收入"),
        (["营业外支出", "罚款", "捐赠支出"], "营业外支出"),
        (["所得税费用", "所得税"], "所得税费用"),
        (["以前年度损益调整"], "以前年度损益调整"),
        (["资产处置"], "资产处置收益"),
    ]

    def __init__(self, db_cursor=None, balance_fields: list = None,
                 balance_table: str = 'balance_data'):
        """
        balance_table: DuckDB 中科目余额表的表名
           - 'balance_data': 原始导入
           - 'balance_leaf': 完整性测试处理后的末级科目版
        """
        self._cursor = db_cursor
        self._balance_table = balance_table
        self._balance_fields = balance_fields or []
        self._code_field = None
        self._name_field = None
        self._amount_field = None
        self._company_field = None
        self._resolve_fields()
        self._report_rows_cache = []
        self._balance_rows_cache = []

    def _resolve_fields(self):
        """解析字段名"""
        self._code_field = self._find_field(["account_code", "科目编号", "科目代码"])
        self._name_field = self._find_field(["account_name", "科目名称", "科目"])
        self._amount_field = self._find_field(["ending", "期末余额", "期末借方"])
        self._company_field = self._find_field(["company", "公司名", "公司名称", "公司"])

    # ══════════════════════════════════════════════════════════
    #  阶段1: 获取映射数据（供前端可编辑界面使用）
    # ══════════════════════════════════════════════════════════

    def get_balance_mappings(self, report_data: dict,
                             dify_client=None) -> dict:
        """
        返回科目余额表每行 + 规则初始映射 + 报表项目列表
        company 字段用于前端筛选
        """
        if not report_data or not report_data.get("data"):
            return {"success": False, "error": "报表数据为空"}

        report_rows = report_data["data"]
        self._report_rows_cache = report_rows
        balance_rows = self._fetch_balance_rows()
        if not balance_rows:
            return {"success": False, "error": "科目余额表无数据，请先导入"}

        if not self._name_field or not self._amount_field:
            return {"success": False, "error": "科目余额表缺少科目名称或期末余额字段"}

        # 提取报表项目名称列表
        report_items = self._extract_report_items(report_rows)

        # 逐行映射
        rows_with_mapping = []
        unmatched = []
        seen_companies = set()

        for row in balance_rows:
            company = str(row.get(self._company_field, "")).strip() if self._company_field else ""
            code = str(row.get(self._code_field, "")).strip() if self._code_field else ""
            name = str(row.get(self._name_field, "")).strip()
            amount = self._parse_amount(row.get(self._amount_field))
            if not name:
                continue

            if company:
                seen_companies.add(company)

            # 规则映射
            candidate = self._map_one(code, name)
            # 将规则映射的标准名模糊匹配到报表实际名称
            report_item = self._match_to_actual(candidate, report_items)

            mapped_row = {
                "account_code": code or "",
                "account_name": name or "",
                "ending_balance": amount,
                "report_item": report_item or "",
                "company": company or "",
            }
            rows_with_mapping.append(mapped_row)

            if not report_item:
                unmatched.append(mapped_row)

        # AI 兜底（只补未匹配的，附带附近已匹配的映射模式供参考）
        if unmatched and dify_client:
            ai_result = self._ai_fallback(unmatched, report_items, dify_client,
                                          all_rows=rows_with_mapping)
            for code_key, report_item in ai_result.items():
                for rw in rows_with_mapping:
                    if rw["account_code"] == code_key:
                        rw["report_item"] = report_item
                        break

        # 按科目编号降序排列
        rows_with_mapping.sort(key=lambda r: r["account_code"])

        return {
            "success": True,
            "balance_rows": rows_with_mapping,
            "report_items": report_items,
            "companies": sorted(seen_companies),
            "_fields": {
                "code_field": self._code_field,
                "name_field": self._name_field,
                "amount_field": self._amount_field,
                "company_field": self._company_field,
            },
        }

    # ══════════════════════════════════════════════════════════
    #  阶段2: 接收用户自定义映射 → 重新核对
    # ══════════════════════════════════════════════════════════

    def reconcile_with_mappings(self, mappings: list,
                                report_data: dict = None) -> dict:
        """
        根据用户修改后的映射重新计算核对结果

        mappings: [{account_code, account_name, ending_balance, report_item}, ...]
        report_data: 如果未传则用缓存
        """
        report_rows = report_data["data"] if report_data else self._report_rows_cache
        if not report_rows:
            return {"success": False, "error": "报表数据为空"}

        # 按 report_item 分组汇总科目余额
        grouped = {}  # {report_item: {accounts: [...], total: 0}}
        unmatched = []
        for m in mappings:
            item = m.get("report_item", "").strip()
            amount = self._parse_amount(m.get("ending_balance", 0))
            if not item:
                unmatched.append(m)
                continue
            if item not in grouped:
                grouped[item] = {"accounts": [], "total": 0}
            grouped[item]["accounts"].append({
                "code": m.get("account_code", ""),
                "name": m.get("account_name", ""),
                "amount": amount,
            })
            grouped[item]["total"] += amount

        # 逐项比对
        comparison = []
        for item_name, group in grouped.items():
            report_amount = 0
            for rrow in report_rows:
                rname = rrow["项目名称"] if "项目名称" in rrow else (list(rrow.values())[0] if rrow else "")
                if rname == item_name:
                    report_amount = self._parse_report_amount(rrow)
                    break
            total = round(group["total"], 2)
            diff = round(abs(total) - abs(report_amount), 2)
            comparison.append({
                "report_item": item_name,
                "report_amount": report_amount,
                "balance_amount": total,
                "diff": diff,
                "matched_accounts": group["accounts"][:30],
                "match_type": "mapped",
            })

        # 未匹配科目
        if unmatched:
            total_unmatched = sum(self._parse_amount(u.get("ending_balance", 0)) for u in unmatched)
            comparison.append({
                "report_item": "(未匹配科目)",
                "report_amount": 0,
                "balance_amount": round(total_unmatched, 2),
                "diff": round(abs(total_unmatched), 2),
                "matched_accounts": [{"code": u["account_code"], "name": u["account_name"],
                                      "amount": self._parse_amount(u.get("ending_balance", 0))}
                                     for u in unmatched],
                "match_type": "unmatched",
            })

        # 反向：报表有但余额表没映射到的
        mapped_names = {c["report_item"] for c in comparison if c["report_item"] != "(未匹配科目)"}
        for rrow in report_rows:
            rname = rrow["项目名称"] if "项目名称" in rrow else (list(rrow.values())[0] if rrow else "")
            if rname and rname not in mapped_names:
                rval = self._parse_report_amount(rrow)
                comparison.append({
                    "report_item": rname,
                    "report_amount": rval,
                    "balance_amount": 0,
                    "diff": round(-abs(rval), 2),
                    "matched_accounts": [],
                    "match_type": "report_only",
                })
                mapped_names.add(rname)

        comparison.sort(key=lambda x: abs(x["diff"]), reverse=True)
        stats = self._calc_stats(comparison)

        # 将映射数据格式化为 balance_data（供导出等下游使用）
        balance_data = []
        for m in mappings:
            balance_data.append({
                "account_code": m.get("account_code", ""),
                "account_name": m.get("account_name", ""),
                "ending_balance": self._parse_amount(m.get("ending_balance", 0)),
                "report_item": m.get("report_item", "").strip() or "",
            })

        return {
            "success": True,
            "comparison": comparison,
            "stats": stats,
            "balance_data": balance_data,
        }

    # ══════════════════════════════════════════════════════════
    #  优化引擎（贪心爬山 + 局部交换）
    # ══════════════════════════════════════════════════════════

    def optimize_mappings(self, mappings: list,
                          report_data: dict = None) -> dict:
        """
        基于第一版核对结果，用贪心爬山算法优化科目→报表项目映射。
        目标：最小化总绝对差异 Σ |余额表汇总金额 - 报表金额|

        算法流程:
          1. 预计算每个科目的候选报表项目列表
          2. 计算当前总绝对差异
          3. 对每个科目尝试每个候选 → 选择使总差异减少最多的单次移动
          4. 检测跨项目的交换对（两个科目互换报表项目能否共同减差异）
          5. 重复 3~4 直到连续 N 轮无改善

        Args:
            mappings: [{account_code, account_name, ending_balance, report_item}, ...]
            report_data: 报表数据（含 data 列表）

        Returns:
            {
                success: bool,
                optimized_mappings: [...],  # 优化后的映射
                comparison: [...],          # 优化后的核对结果
                stats: {...},              # 优化后的统计
                changes: [{account_code, account_name, from, to, reason}],  # 变更记录
                metrics: {initial_diff, final_diff, improvement_pct, iterations},
            }
        """
        report_rows = report_data.get("data", []) if report_data else self._report_rows_cache
        if not report_rows:
            return {"success": False, "error": "报表数据为空"}

        report_items = self._extract_report_items(report_rows)

        # ── 1. 深层复制 mappings，优化过程不影响原始数据 ──
        optimized = copy.deepcopy(mappings)

        # ── 2. 预计算每个科目的候选列表 ──
        # key = account_code|account_name, value = [report_item, ...]
        candidates_map = {}
        for m in optimized:
            code = str(m.get("account_code", ""))
            name = str(m.get("account_name", ""))
            key = f"{code}|{name}"
            # 当前映射
            current = m.get("report_item", "").strip()
            # 生成候选（含分数）
            scored = self._generate_candidates(code, name, report_items, top_n=15)
            cands = [item for item, _ in scored]
            # 确保当前映射在最前面（如果不在候选里）
            if current and current not in cands:
                cands.insert(0, current)
            elif current and cands and cands[0] != current:
                # 把当前映射提到最前面（优先级最高）
                cands = [current] + [c for c in cands if c != current]
            candidates_map[key] = cands

        # ── 3. 工具函数: 计算分组汇总和总绝对差异 ──
        def _calc_grouped(mappings_list):
            """返回 grouped_map {item: total} 和各项的 report_amount"""
            grouped = {}
            for m in mappings_list:
                item = m.get("report_item", "").strip()
                amt = self._parse_amount(m.get("ending_balance", 0))
                if not item:
                    # 未映射的科目单独统计
                    item = "__unmatched__"
                if item not in grouped:
                    grouped[item] = 0
                grouped[item] += amt

            # 找报表金额
            report_amounts = {}
            for rrow in report_rows:
                rname = rrow.get("项目名称", list(rrow.values())[0] if rrow else "")
                if rname:
                    report_amounts[rname] = self._parse_report_amount(rrow)

            return grouped, report_amounts

        def _total_diff(grouped, report_amounts):
            diff = 0.0
            # 各项目的差异
            for item, total in grouped.items():
                if item == "__unmatched__":
                    diff += abs(total)
                    continue
                target = report_amounts.get(item, 0)
                diff += abs(abs(total) - abs(target))
            # 报表有但余额表无映射的项目
            mapped_items = {k for k in grouped if k != "__unmatched__"}
            for ri, amt in report_amounts.items():
                if ri not in mapped_items and amt:
                    diff += abs(amt)
            return round(diff, 2)

        # ── 4. 计算初始总差异 ──
        init_grouped, init_ra = _calc_grouped(optimized)
        initial_diff = _total_diff(init_grouped, init_ra)
        best_diff = initial_diff

        # ── 4a. 找出已匹配一致的项目，锁定其下的科目（优化不动） ──
        locked_indices = set()
        for item, total in init_grouped.items():
            if item == "__unmatched__":
                continue
            target = init_ra.get(item, 0)
            if abs(abs(total) - abs(target)) <= 0.01:
                # 这个项目余额表汇总 ≈ 报表金额，锁定其所有科目
                for idx, m in enumerate(optimized):
                    if m.get("report_item", "").strip() == item:
                        locked_indices.add(idx)

        change_log = []

        # ── 5. 主循环：贪心爬山 + 局部交换 ──
        for iteration in range(15):  # 最多 15 轮
            improved = False

            # ── 5a. 单科目移动 ──
            best_move = None  # (idx, target_item, new_diff)
            for idx, m in enumerate(optimized):
                # ⛔ 已匹配一致的科目不动
                if idx in locked_indices:
                    continue

                code = str(m.get("account_code", ""))
                name = str(m.get("account_name", ""))
                key = f"{code}|{name}"
                cands = candidates_map.get(key, [])
                old_item = m.get("report_item", "").strip()

                # 跳过没有候选的科目
                if not cands or (len(cands) == 1 and cands[0] == old_item):
                    continue

                for cand in cands:
                    if cand == old_item:
                        continue
                    # 尝试移动
                    m["report_item"] = cand
                    g, ra = _calc_grouped(optimized)
                    new_diff = _total_diff(g, ra)
                    # 还原
                    m["report_item"] = old_item

                    if new_diff < best_diff - 0.005:  # 5分钱以上的改善
                        best_diff = new_diff
                        best_move = (idx, cand, old_item, new_diff, "单科目移动")

            if best_move:
                idx, cand, old_item, new_diff, reason = best_move
                optimized[idx]["report_item"] = cand
                change_log.append({
                    "account_code": optimized[idx].get("account_code", ""),
                    "account_name": optimized[idx].get("account_name", ""),
                    "from": old_item,
                    "to": cand,
                    "reason": reason,
                    "diff_before": round(best_diff_before := (initial_diff if iteration == 0 else best_diff_prev), 2),
                    "diff_after": round(best_diff, 2),
                })
                best_diff_prev = best_diff
                improved = True
                continue  # 重新计算，然后进入下一轮

            # ── 5b. 跨项目交换检测（处理贪心无法解决的"交换"场景） ──
            # 先找出当前分组情况
            g, ra = _calc_grouped(optimized)
            diff_items = []
            for item, total in g.items():
                if item == "__unmatched__":
                    continue
                target = ra.get(item, 0)
                d = abs(total) - abs(target)
                if abs(d) > 0.01:
                    diff_items.append((item, d))

            # 尝试交换一对科目（来自不同项目、差异方向相反）
            if len(diff_items) >= 2:
                # 把科目按所属项目分组
                accounts_by_item = {}
                for m in optimized:
                    item = m.get("report_item", "").strip()
                    if item:
                        key = f"{item}"
                        if key not in accounts_by_item:
                            accounts_by_item[key] = []
                        accounts_by_item[key].append(m)

                best_swap = None
                # 只尝试差异方向相反的项目对
                for i in range(len(diff_items)):
                    for j in range(i + 1, len(diff_items)):
                        item_a, diff_a = diff_items[i]
                        item_b, diff_b = diff_items[j]
                        # 差异方向相反才可能通过交换改善
                        if (diff_a > 0 and diff_b < 0) or (diff_a < 0 and diff_b > 0):
                            accts_a = accounts_by_item.get(item_a, [])
                            accts_b = accounts_by_item.get(item_b, [])
                            # 尝试每对科目交换
                            for ma in accts_a:
                                for mb in accts_b:
                                    old_a = ma.get("report_item", "")
                                    old_b = mb.get("report_item", "")
                                    if old_a == old_b:
                                        continue
                                    # 交换
                                    ma["report_item"] = item_b
                                    mb["report_item"] = item_a
                                    g2, ra2 = _calc_grouped(optimized)
                                    swap_diff = _total_diff(g2, ra2)
                                    # 还原
                                    ma["report_item"] = old_a
                                    mb["report_item"] = old_b

                                    if swap_diff < best_diff - 0.01:
                                        best_diff = swap_diff
                                        best_swap = (ma, mb, old_a, old_b, item_a, item_b, swap_diff, "科目交换")

                if best_swap:
                    ma, mb, old_a, old_b, item_a, item_b, new_diff, reason = best_swap
                    ma["report_item"] = item_b
                    mb["report_item"] = item_a
                    # 记录两次变更
                    change_log.append({
                        "account_code": ma.get("account_code", ""),
                        "account_name": ma.get("account_name", ""),
                        "from": old_a,
                        "to": item_b,
                        "reason": f"与{mb.get('account_code','')}交换",
                        "diff_before": round(best_diff_prev if iteration > 0 else initial_diff, 2),
                        "diff_after": round(best_diff, 2),
                    })
                    change_log.append({
                        "account_code": mb.get("account_code", ""),
                        "account_name": mb.get("account_name", ""),
                        "from": old_b,
                        "to": item_a,
                        "reason": f"与{ma.get('account_code','')}交换",
                        "diff_before": round(best_diff_prev if iteration > 0 else initial_diff, 2),
                        "diff_after": round(best_diff, 2),
                    })
                    best_diff_prev = best_diff
                    improved = True

            if not improved:
                break  # 没有改善，退出循环

        # ── 6. 生成优化后的核对结果 ──
        reconciled = self.reconcile_with_mappings(optimized, report_data)
        comparison = reconciled.get("comparison", [])
        stats = reconciled.get("stats", {})

        final_diff = best_diff
        improvement = initial_diff - final_diff
        improvement_pct = round(improvement / initial_diff * 100, 1) if initial_diff > 0 else 0

        return {
            "success": True,
            "optimized_mappings": optimized,
            "comparison": comparison,
            "stats": stats,
            "changes": change_log,
            "metrics": {
                "initial_diff": initial_diff,
                "final_diff": final_diff,
                "improvement": round(improvement, 2),
                "improvement_pct": improvement_pct,
                "iterations": len(change_log) if change_log else 0,
            },
        }

    # ══════════════════════════════════════════════════════════
    #  映射引擎
    # ══════════════════════════════════════════════════════════

    def _generate_candidates(self, code: str, name: str,
                             report_items: list, top_n: int = 15) -> list:
        """
        为一个科目生成多个候选报表项目名称（返回实际报表中的名称）。
        取消当前 _map_one 的短路逻辑，收集所有可能的匹配结果。

        Args:
            code: 科目编号
            name: 科目名称
            report_items: 报表项目名称列表（实际值）
            top_n: 最多返回 N 个候选

        Returns:
            [(report_item, score), ...] 按匹配度降序排列
        """
        candidates = []  # list of (item, score)
        seen = set()
        has_code_match = False  # 标记是否有科目编号前缀匹配

        def _add(item, score):
            if item and item not in seen:
                candidates.append((item, score))
                seen.add(item)

        # ── 1. 科目编号前缀匹配（收集所有匹配，不只是最长前缀） ──
        if code:
            clean_code = re.sub(r'[－\-—\s.]', '', code)
            prefixes = sorted(self.ACCOUNT_CODE_RULES.keys(), key=len, reverse=True)
            for prefix in prefixes:
                if clean_code.startswith(prefix):
                    standard = self.ACCOUNT_CODE_RULES[prefix]
                    actual = self._match_to_actual(standard, report_items)
                    # 最长前缀给最高分，短前缀递减
                    prefix_len_score = len(prefix) / 4.0
                    _add(actual, 100 + prefix_len_score)
                    has_code_match = True

        # ── 2. 科目名称关键词匹配（收集所有匹配的关键词组） ──
        name_lower = name.lower()
        for keywords, standard_item in self.ACCOUNT_NAME_RULES:
            if any(kw in name or kw in name_lower for kw in keywords):
                actual = self._match_to_actual(standard_item, report_items)
                # 分数按匹配关键词数量/深度
                match_count = sum(1 for kw in keywords if kw in name or kw in name_lower)
                _add(actual, 80 + match_count * 5)

        # ── 3. 模糊匹配：科目名称 vs 报表项目名称 ──
        if name:
            # 如果科目编号已有预设规则匹配，模糊匹配门槛提高（防止窜到完全不相关的项目）
            fuzzy_threshold = 0.60 if has_code_match else 0.45
            norm_name = self._normalize_name(name)
            for ri in report_items:
                norm_ri = self._normalize_name(ri)
                ratio = SequenceMatcher(None, norm_name, norm_ri).ratio()
                # 加权：科目名含在报表名中加分
                if norm_name in norm_ri:
                    ratio += 0.15
                # 报表名含在科目名中加分（部分匹配）
                if norm_ri in norm_name and len(norm_ri) > 2:
                    ratio += 0.10
                if ratio >= fuzzy_threshold:
                    _add(ri, 50 + ratio * 30)

        # ── 4. 按分数降序排序 ──
        candidates.sort(key=lambda x: -x[1])

        # ── 5. 确保当前映射也在候选里（用空字符串占位，由调用方填充） ──
        # 如果候选太少，补充一些未覆盖的报表项目（靠后的匹配）
        if len(candidates) < top_n:
            for ri in report_items:
                if ri not in seen:
                    candidates.append((ri, 0))
                    seen.add(ri)
                    if len(candidates) >= top_n * 2:
                        break

        return candidates[:top_n]

    def _map_one(self, code: str, name: str) -> Optional[str]:
        """规则映射一个科目到报表项目"""
        if code:
            clean_code = re.sub(r'[－\-—\s.]', '', code)
            prefixes = sorted(self.ACCOUNT_CODE_RULES.keys(), key=len, reverse=True)
            for prefix in prefixes:
                if clean_code.startswith(prefix):
                    return self.ACCOUNT_CODE_RULES[prefix]

        name_lower = name.lower()
        for keywords, item in self.ACCOUNT_NAME_RULES:
            if any(kw in name or kw in name_lower for kw in keywords):
                return item

        return None

    def _fuzzy_match_item(self, name: str, report_items: list) -> Optional[str]:
        """模糊匹配科目名到相似报表项目"""
        best_ratio = 0
        best_item = None
        for item in report_items:
            ratio = SequenceMatcher(None, name, item).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_item = item
        return best_item if best_ratio >= 0.5 else None

    def _extract_report_items(self, report_rows: list) -> list:
        """提取报表项目名称列表"""
        items = []
        for r in report_rows:
            name = r["项目名称"] if "项目名称" in r else (list(r.values())[0] if r else "")
            if name:
                items.append(name)
        return items

    def _match_to_actual(self, standard_name: str,
                         report_items: list) -> Optional[str]:
        """
        将规则映射出的标准报表名，匹配到实际报表中的准确名称。

        比如规则说"应收账款"，实际报表叫"应收帐款"→ 返回"应收帐款"
            规则说"营业收入"，实际报表叫"一、营业收入"→ 返回"一、营业收入"
            规则说"预收款项"，实际报表叫"预收账款"→ 返回"预收账款"
        """
        if not standard_name or not report_items:
            return standard_name

        norm_standard = self._normalize_name(standard_name)

        # 先试精确匹配（标准化后）
        for actual in report_items:
            if self._normalize_name(actual) == norm_standard:
                return actual

        # 再试模糊匹配（相似度 >= 0.6）
        best_ratio = 0
        best_item = None
        for actual in report_items:
            norm_actual = self._normalize_name(actual)
            ratio = SequenceMatcher(None, norm_standard, norm_actual).ratio()
            # 加权：标准名如果包含在实际名中（含前缀），加分
            if norm_standard in norm_actual:
                ratio += 0.15
            if ratio > best_ratio:
                best_ratio = ratio
                best_item = actual

        if best_ratio >= 0.55 and best_item:
            return best_item

        # 没匹配上就返回原始标准名
        return standard_name

    def _normalize_name(self, name: str) -> str:
        """标准化报表项目名，去除编号前缀、统一异体字、去空格"""
        s = name.strip()
        # 去除中文编号前缀："一、营业收入" → "营业收入"
        # "（一）营业收入" → "营业收入"  "1、营业收入" → "营业收入"
        s = re.sub(r'^[（(]?[一二三四五六七八九十百千\d]+[）).、、\s]*', '', s)
        # 统一异体字
        s = s.replace('帐', '账')
        s = s.replace('余款', '余额')
        s = s.replace('（', '(').replace('）', ')')
        # 去空格
        s = s.replace(' ', '').replace('　', '')
        return s

    # ══════════════════════════════════════════════════════════
    #  AI 兜底
    # ══════════════════════════════════════════════════════════

    def _ai_fallback(self, unmatched: list, report_items: list,
                     dify_client, all_rows: list = None) -> dict:
        """
        通过 Dify 代理 AI 补全：返回 {account_code: report_item}

        相比之前改进：
        - 附带上下几个科目编号范围内已匹配科目的映射模式，帮助 AI 推断
        - 结合科目名称判断
        """
        # ── 构建已匹配科目的上下文（按编号排序取附近匹配） ──
        context_lines = []
        if all_rows:
            # 按科目编号排序
            sorted_rows = sorted(
                [r for r in all_rows if r.get("account_code")],
                key=lambda r: r["account_code"]
            )
            # 对每个未匹配科目，找上下 3 个已匹配的科目供 AI 参考
            for u in unmatched:
                ucode = u.get("account_code", "") or ""
                if not ucode:
                    continue
                neighbors = []
                ucode_clean = re.sub(r'[－\-—\s.]', '', ucode)
                # 找同一编号前缀范围的已匹配科目
                prefix_len = min(4, len(ucode_clean))
                u_prefix = ucode_clean[:prefix_len] if ucode_clean else ""
                for r in sorted_rows:
                    rcode = r.get("account_code", "")
                    ritem = r.get("report_item", "").strip()
                    if not rcode or not ritem:
                        continue
                    rcode_clean = re.sub(r'[－\-—\s.]', '', rcode)
                    # 前缀相同或在附近
                    if (u_prefix and rcode_clean.startswith(u_prefix)) or abs(len(rcode_clean) - len(ucode_clean)) <= 2:
                        neighbors.append(f"    {rcode} {r.get('account_name','')} → {ritem}")
                if neighbors:
                    context_lines.append(f"  {ucode} {u.get('account_name','')}（附近已匹配参考:）")
                    context_lines.extend(neighbors[:5])

        acct_lines = "\n".join(
            f"  - 科目编号: {u['account_code'] or '(无)'}, 科目名称: {u['account_name']}"
            for u in unmatched[:50]
        )
        item_lines = "\n".join(f"  - {n}" for n in report_items)

        context_section = ""
        if context_lines:
            context_section = f"\n## 附近已匹配科目（供参考映射模式）\n{chr(10).join(context_lines)}\n"

        prompt = f"""你是一个会计科目映射专家。请将以下未匹配的科目映射到最合适的报表项目。

## 报表项目列表
{item_lines}

## 待匹配科目
{acct_lines}
{context_section}
## 映射规则
1. **优先参考「附近已匹配科目」的映射模式**：如果同编号前缀的科目都映射到了同一个报表项目，那当前科目也应该相同
2. **其次根据科目名称判断**：科目名称中的关键词通常指向对应的报表项目
3. **金额大小辅助判断**：大额科目通常对应主要报表项目

返回 JSON 数组: [{{"code": "科目编号", "report_item": "报表项目名称"}}]
如果无法匹配任何项目，report_item 设为空字符串。
只返回 JSON 数组，不要其他内容。
"""
        try:
            content = dify_client.chat(
                "你是一个会计科目映射专家，返回严格 JSON 格式。",
                prompt,
                timeout=30,
            )
            parsed = self._parse_json(content)
            if not isinstance(parsed, list):
                return {}

            result = {}
            for item in parsed:
                code = item.get("code", "")
                ri = item.get("report_item", "").strip()
                if code and ri:
                    result[code] = ri
            return result
        except Exception:
            return {}

    def _parse_json(self, text: str) -> Optional[list]:
        text = text.strip()
        try:
            return json_module.loads(text)
        except json_module.JSONDecodeError:
            pass
        m = re.search(r'\[[^\[\]]*\]', text, re.DOTALL)
        if m:
            try:
                return json_module.loads(m.group(0))
            except json_module.JSONDecodeError:
                pass
        return None

    # ══════════════════════════════════════════════════════════
    #  金额处理
    # ══════════════════════════════════════════════════════════

    def _parse_report_amount(self, row: dict) -> float:
        for key in ["期末余额", "年初余额", "本月金额", "本年累计金额", "上年同期累计数"]:
            val = row.get(key, "")
            if val != "" and val is not None:
                return self._parse_amount(val)
        vals = list(row.values())
        if len(vals) >= 2:
            return self._parse_amount(vals[1])
        return 0

    def _parse_amount(self, val) -> float:
        if val is None or val == "":
            return 0
        if isinstance(val, (int, float)):
            return float(val)
        try:
            cleaned = str(val).replace(",", "").replace("，", "").replace(" ", "")
            return float(cleaned) if cleaned else 0
        except (ValueError, TypeError):
            return 0

    def _calc_stats(self, comparison: list) -> dict:
        total_items = len(comparison)
        matched = sum(1 for c in comparison if c["match_type"] == "mapped" and abs(c["diff"]) <= 0.01)
        difference = sum(1 for c in comparison if c["match_type"] == "mapped" and abs(c["diff"]) > 0.01)
        return {
            "total_items": total_items,
            "matched": matched,
            "difference": difference,
            "report_only": sum(1 for c in comparison if c["match_type"] == "report_only"),
            "unmatched": sum(1 for c in comparison if c["match_type"] == "unmatched"),
            "match_rate": round(matched / total_items * 100, 1) if total_items else 0,
        }

    # ══════════════════════════════════════════════════════════
    #  数据获取
    # ══════════════════════════════════════════════════════════

    def _fetch_balance_rows(self) -> list:
        if not self._cursor:
            return []
        try:
            rows = self._cursor.execute(f'SELECT * FROM "{self._balance_table}"').fetchall()
            cols = [d[0] for d in self._cursor.description]
            self._balance_rows_cache = [dict(zip(cols, r)) for r in rows]
            return self._balance_rows_cache
        except Exception:
            return []

    def _find_field(self, candidates: list) -> Optional[str]:
        """
        在字段定义中找标准字段对应的实际列名。
        优先级: DuckDB 实际列名 > session 字段定义。
        避免 session 记录的字段名（如 "期末借方"）在快照表实际列名（如 "期末余额"）中不存在。
        """
        # 先查 DuckDB 实际列名（更可靠，因为快照表的列名可能与原始不同）
        if self._cursor:
            try:
                cols = [d[0] for d in self._cursor.description]
                for c in candidates:
                    key = c.replace("account_", "")
                    for col in cols:
                        if key in col.replace("account_", ""):
                            return col
            except Exception:
                pass
        # 再 fallback 到 session 字段定义
        for f in self._balance_fields:
            fname = f.get("name", "") if isinstance(f, dict) else str(f)
            if fname in candidates:
                return fname
        return None
