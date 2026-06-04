"""
完整性检查模块 - 基于 DuckDB 的财务数据完整性测试逻辑

包含三类完整性测试：
1. 序时账完整性测试：按公司名+凭证号+生效日期分组，检查发生额汇总
2. 科目余额表完整性测试：汇总期初金额、期末金额、发生额(期末-期初)是否归零
3. 序时账&科目余额表交叉验证：按公司+科目编号+科目名称，检查两表发生额一致性

支持反结转模式（金蝶/用友）：自动识别并剔除结转损益凭证，调整科目余额表后再验证。
"""

import duckdb
import pandas as pd
from typing import Dict, Any, Optional


# ====== 反结转相关 SQL 常量 ======

SQL_CF_VOUCHERS = """
    CREATE TEMP VIEW cf_vouchers AS
    SELECT DISTINCT "公司名", "日期", "凭证号"
    FROM "{journal_table}"
    WHERE CAST("科目编号" AS VARCHAR) = '4103'
       OR ("摘要" LIKE '%结转%' AND "摘要" LIKE '%损益%')
"""

SQL_CF_AMOUNTS = """
    CREATE TEMP VIEW cf_amounts AS
    SELECT
        d."公司名",
        CAST(d."科目编号" AS VARCHAR) AS "科目编号",
        d."科目名称",
        SUM(CAST(d."金额" AS DOUBLE)) AS "结转损益金额"
    FROM "{journal_table}" d
    JOIN cf_vouchers v
        ON  d."公司名" = v."公司名"
        AND d."日期"   = v."日期"
        AND d."凭证号" = v."凭证号"
    GROUP BY d."公司名", d."科目编号", d."科目名称"
"""

SQL_JOURNAL_FILTERED = """
    CREATE TEMP VIEW journal_filtered AS
    SELECT d.*
    FROM "{journal_table}" d
    LEFT JOIN cf_vouchers v
        ON  d."公司名" = v."公司名"
        AND d."日期"   = v."日期"
        AND d."凭证号" = v."凭证号"
    WHERE v."公司名" IS NULL
"""

SQL_BALANCE_ADJUSTED = """
    CREATE TEMP VIEW balance_adjusted AS
    SELECT
        b."公司名",
        CAST(b."科目编号" AS VARCHAR) AS "科目编号",
        b."科目名称",
        SUM(CAST(b."期初余额" AS DOUBLE)) AS "期初余额",
        SUM(CAST(b."期末余额" AS DOUBLE)) - COALESCE(SUM(cf."结转损益金额"), 0) AS "期末余额",
        (SUM(CAST(b."期末余额" AS DOUBLE)) - COALESCE(SUM(cf."结转损益金额"), 0))
            - SUM(CAST(b."期初余额" AS DOUBLE)) AS "发生额",
        SUM(CAST(b."期末余额" AS DOUBLE)) AS "原始期末余额",
        COALESCE(SUM(cf."结转损益金额"), 0) AS "结转损益金额"
    FROM "{balance_table}" b
    LEFT JOIN cf_amounts cf
        ON  CAST(b."公司名" AS VARCHAR)   = CAST(cf."公司名" AS VARCHAR)
        AND CAST(b."科目编号" AS VARCHAR) = CAST(cf."科目编号" AS VARCHAR)
    GROUP BY b."公司名", b."科目编号", b."科目名称"
"""

# ====== 导出用 SQL 常量 ======

SQL_EXPORT_JOURNAL = """
    SELECT
        "公司名",
        "凭证号",
        "日期",
        CAST(SUM(CAST("金额" AS DOUBLE)) AS DOUBLE) AS "汇总发生额"
    FROM "{table}"
    WHERE "凭证号" IS NOT NULL
      AND CAST("凭证号" AS VARCHAR) != ''
    GROUP BY "公司名", "凭证号", "日期"
    ORDER BY "公司名", "日期", "凭证号"
"""

SQL_EXPORT_BALANCE = """
    SELECT
        "公司名",
        CAST("科目编号" AS VARCHAR) AS "科目编号",
        "科目名称",
        CAST(SUM(CAST("期初余额" AS DOUBLE)) AS DOUBLE) AS "期初余额",
        CAST(SUM(CAST("期末余额" AS DOUBLE)) AS DOUBLE) AS "期末余额",
        CAST(
            SUM(CAST("期末余额" AS DOUBLE)) - SUM(CAST("期初余额" AS DOUBLE))
        AS DOUBLE) AS "发生额"
    FROM "{table}"
    GROUP BY "公司名", "科目编号", "科目名称"
    ORDER BY "公司名", CAST("科目编号" AS VARCHAR)
"""

SQL_CROSS_JOIN_AMOUNT = """
    SUM(CAST("{col}" AS DOUBLE))
"""

SQL_EXPORT_CROSS = """
    WITH journal_agg AS (
        SELECT
            "公司名",
            CAST("科目编号" AS VARCHAR) AS "科目编号",
            "科目名称",
            CAST(SUM(CAST("金额" AS DOUBLE)) AS DOUBLE) AS "序时账发生额"
        FROM "{journal_table}"
        WHERE "凭证号" IS NOT NULL
          AND CAST("凭证号" AS VARCHAR) != ''
        GROUP BY "公司名", "科目编号", "科目名称"
    ),
    balance_agg AS (
        SELECT
            "公司名",
            CAST("科目编号" AS VARCHAR) AS "科目编号",
            "科目名称",
            CAST(SUM(CAST("期末余额" AS DOUBLE)) - SUM(CAST("期初余额" AS DOUBLE)) AS DOUBLE) AS "科目余额表发生额",
            CAST(SUM(CAST("期末余额" AS DOUBLE)) AS DOUBLE) AS "科目余额表期末",
            CAST(SUM(CAST("期初余额" AS DOUBLE)) AS DOUBLE) AS "科目余额表期初"
        FROM "{balance_table}"
        GROUP BY "公司名", "科目编号", "科目名称"
    )
    SELECT
        COALESCE(CAST(j."公司名" AS VARCHAR), CAST(b."公司名" AS VARCHAR)) AS "公司名",
        COALESCE(CAST(j."科目编号" AS VARCHAR), CAST(b."科目编号" AS VARCHAR)) AS "科目编号",
        COALESCE(CAST(j."科目名称" AS VARCHAR), CAST(b."科目名称" AS VARCHAR)) AS "科目名称",
        COALESCE(CAST(b."科目余额表期初" AS DOUBLE), 0.0) AS "科目余额表期初",
        COALESCE(CAST(b."科目余额表期末" AS DOUBLE), 0.0) AS "科目余额表期末",
        COALESCE(CAST(b."科目余额表发生额" AS DOUBLE), 0.0) AS "科目余额表发生额",
        COALESCE(CAST(j."序时账发生额" AS DOUBLE), 0.0) AS "序时账发生额",
        COALESCE(CAST(j."序时账发生额" AS DOUBLE), 0.0) - COALESCE(CAST(b."科目余额表发生额" AS DOUBLE), 0.0) AS "差异"
    FROM journal_agg j
    FULL OUTER JOIN balance_agg b
        ON  CAST(j."公司名" AS VARCHAR)   = CAST(b."公司名" AS VARCHAR)
        AND CAST(j."科目编号" AS VARCHAR) = CAST(b."科目编号" AS VARCHAR)
        AND CAST(j."科目名称" AS VARCHAR) = CAST(b."科目名称" AS VARCHAR)
    ORDER BY ABS("差异") DESC
"""


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
        self._cf_setup_done = False
        self._leaf_setup_done = False

    # ========== 底层辅助方法 ==========

    def _table_exists(self, table: str) -> bool:
        return self.engine.table_exists(table)

    def _get_schema(self, table: str) -> set:
        return {col['name'] for col in self.engine.get_schema(table)}

    def _fetchone(self, sql: str):
        return self.engine._conn.execute(sql).fetchone()

    def _fetchall(self, sql: str):
        return self.engine._conn.execute(sql).fetchall()

    def _describe(self, sql: str):
        result = self.engine._conn.execute(sql)
        return [desc[0] for desc in result.description], result.fetchall()

    def _fetchdf(self, sql: str) -> pd.DataFrame:
        return self.engine._conn.execute(sql).fetchdf()

    # ========== TRIM 视图（去空格） ==========

    def _drop_trim_views(self):
        """删除 TRIM 临时视图"""
        for view in ['_j_trim', '_b_trim']:
            try:
                self.engine._conn.execute(f'DROP VIEW IF EXISTS "{view}"')
            except Exception:
                pass

    def _setup_trim_views(self):
        """
        创建 TRIM 临时视图，去除所有 VARCHAR 列的前后空格。
        在方向调整之前执行，避免带空格的文本字段导致 JOIN/GROUP BY 匹配失败。
        """
        for tbl_key, view_name in [(self.journal_table, '_j_trim'),
                                    (self.balance_table, '_b_trim')]:
            if not tbl_key or not self._table_exists(tbl_key):
                continue
            schema = self.engine.get_schema(tbl_key)
            text_cols = [col['name'] for col in schema
                         if any(t in col['type'].upper() for t in ['VARCHAR', 'TEXT'])]
            if not text_cols:
                continue
            select_parts = []
            for col in schema:
                cname = col['name']
                if cname in text_cols:
                    select_parts.append(f'TRIM("{cname}") AS "{cname}"')
                else:
                    select_parts.append(f'"{cname}"')
            self.engine._conn.execute(f"""
                CREATE OR REPLACE TEMP VIEW "{view_name}" AS
                SELECT {', '.join(select_parts)}
                FROM "{tbl_key}"
            """)
            # 更新指针
            if tbl_key == self.journal_table:
                self.journal_table = view_name
            elif tbl_key == self.balance_table:
                self.balance_table = view_name

    # ========== 反结转视图管理 ==========

    def _drop_cf_views(self):
        """删除所有反结转临时视图"""
        for view in ['cf_vouchers', 'cf_amounts', 'journal_filtered', 'balance_adjusted']:
            try:
                self.engine._conn.execute(f'DROP VIEW IF EXISTS "{view}"')
            except Exception:
                pass
        self._cf_setup_done = False

    def _setup_carry_forward_views(self, cf_account_code: str = '4103',
                                     cf_keywords: list = None):
        """
        创建反结转临时视图。
        通过 cf_account_code 指定结转损益科目编号（默认 4103），
        通过 cf_keywords 指定摘要关键词（默认 ["结转", "损益"]）。
        """
        if self._cf_setup_done:
            return
        self._drop_cf_views()

        cf_keywords = cf_keywords or ['结转', '损益']

        schema = self._get_schema(self.journal_table)
        has_account_code = '科目编号' in schema
        has_summary = '摘要' in schema

        if not has_account_code and not has_summary:
            raise ValueError("序时账缺少「科目编号」和「摘要」字段，无法执行反结转")

        jt = self.journal_table

        # 构建 WHERE 条件：用户指定的科目编号 OR 摘要包含用户指定的关键词
        conditions = []
        if has_account_code and cf_account_code:
            conditions.append(f'CAST("科目编号" AS VARCHAR) = \'{cf_account_code}\'')
        if has_summary and cf_keywords:
            kw_parts = [f'"摘要" LIKE \'%{kw.strip()}%\''
                       for kw in cf_keywords if kw.strip()]
            if len(kw_parts) >= 2:
                conditions.append('(' + ' AND '.join(kw_parts) + ')')
            elif len(kw_parts) == 1:
                conditions.append(kw_parts[0])

        if not conditions:
            raise ValueError("序时账缺少「科目编号」字段（4103）且无「摘要」字段，无法执行反结转")

        where_clause = ' OR '.join(conditions)
        print(f"[CARRY FORWARD] 结转损益凭证识别条件: {where_clause}")

        # 1. 找出结转损益凭证
        self._orig_journal_table = self.journal_table  # 保存原始表名用于 get_cf_info
        self.engine._conn.execute(f"""
            CREATE TEMP VIEW cf_vouchers AS
            SELECT DISTINCT "公司名", "日期", "凭证号"
            FROM "{jt}"
            WHERE {where_clause}
        """)

        # 2. 汇总结转损益金额（by 公司+科目）
        has_direction = '方向' in schema
        needs_dir = has_direction and jt != '_j_dir'
        if needs_dir:
            cf_amount_sql = f"""
                CREATE TEMP VIEW cf_amounts AS
                SELECT
                    d."公司名",
                    CAST(d."科目编号" AS VARCHAR) AS "科目编号",
                    d."科目名称",
                    SUM(CASE WHEN d."方向" IN ('借', 'Debit', 'D') THEN CAST(d."金额" AS DOUBLE) ELSE -CAST(d."金额" AS DOUBLE) END) AS "结转损益金额"
                FROM "{jt}" d
                JOIN cf_vouchers v
                    ON  d."公司名" = v."公司名"
                    AND d."日期"   = v."日期"
                    AND d."凭证号" = v."凭证号"
                GROUP BY d."公司名", d."科目编号", d."科目名称"
            """
        else:
            cf_amount_sql = f"""
                CREATE TEMP VIEW cf_amounts AS
                SELECT
                    d."公司名",
                    CAST(d."科目编号" AS VARCHAR) AS "科目编号",
                    d."科目名称",
                    SUM(CAST(d."金额" AS DOUBLE)) AS "结转损益金额"
                FROM "{jt}" d
                JOIN cf_vouchers v
                    ON  d."公司名" = v."公司名"
                    AND d."日期"   = v."日期"
                    AND d."凭证号" = v."凭证号"
                GROUP BY d."公司名", d."科目编号", d."科目名称"
            """
        self.engine._conn.execute(cf_amount_sql)

        # 3. 剔除结转损益后的序时账
        self.engine._conn.execute(f"""
            CREATE TEMP VIEW journal_filtered AS
            SELECT d.*
            FROM "{jt}" d
            LEFT JOIN cf_vouchers v
                ON  d."公司名" = v."公司名"
                AND d."日期"   = v."日期"
                AND d."凭证号" = v."凭证号"
            WHERE v."公司名" IS NULL
        """)

        # 4. 创建调整后的科目余额表
        bt = self.balance_table
        if bt and self._table_exists(bt):
            b_schema = self._get_schema(bt)
            if '期初余额' in b_schema and '期末余额' in b_schema:
                self.engine._conn.execute(f"""
                    CREATE TEMP VIEW balance_adjusted AS
                    SELECT
                        b."公司名",
                        CAST(b."科目编号" AS VARCHAR) AS "科目编号",
                        b."科目名称",
                        CAST(SUM(CAST(b."期初余额" AS DOUBLE)) AS DOUBLE) AS "期初余额",
                        CAST(
                            SUM(CAST(b."期末余额" AS DOUBLE)) - COALESCE(SUM(cf."结转损益金额"), 0)
                        AS DOUBLE) AS "期末余额",
                        CAST(
                            SUM(CAST(b."期末余额" AS DOUBLE)) - COALESCE(SUM(cf."结转损益金额"), 0)
                            - SUM(CAST(b."期初余额" AS DOUBLE))
                        AS DOUBLE) AS "发生额",
                        CAST(SUM(CAST(b."期末余额" AS DOUBLE)) AS DOUBLE) AS "原始期末余额",
                        CAST(COALESCE(SUM(cf."结转损益金额"), 0) AS DOUBLE) AS "结转损益金额"
                    FROM "{bt}" b
                    LEFT JOIN cf_amounts cf
                        ON  CAST(b."公司名" AS VARCHAR)   = CAST(cf."公司名" AS VARCHAR)
                        AND CAST(b."科目编号" AS VARCHAR) = CAST(cf."科目编号" AS VARCHAR)
                    GROUP BY b."公司名", b."科目编号", b."科目名称"
                """)

        self._cf_setup_done = True

    def get_cf_info(self) -> dict:
        """返回反结转相关信息"""
        info = {}
        try:
            # 结转损益凭证数
            row = self._fetchone('SELECT COUNT(*) FROM cf_vouchers')
            info['cf_voucher_count'] = int(row[0]) if row else 0

            # 原始序时账行数（从原始表获取，而非过滤后的视图）
            orig_table = getattr(self, '_orig_journal_table', None) or self.journal_table
            orig = self._fetchone(f'SELECT COUNT(*) FROM "{orig_table}"')
            info['original_journal_rows'] = int(orig[0]) if orig else 0

            # 过滤后行数
            filt = self._fetchone('SELECT COUNT(*) FROM journal_filtered')
            info['filtered_journal_rows'] = int(filt[0]) if filt else 0

            # 被剔除的行数
            info['removed_journal_rows'] = info['original_journal_rows'] - info['filtered_journal_rows']

            # 结转损益科目数（受影响的科目数量）
            acct = self._fetchone('SELECT COUNT(*) FROM cf_amounts')
            info['cf_account_count'] = int(acct[0]) if acct else 0

            # 结转损益总额
            total = self._fetchone('SELECT COALESCE(SUM("结转损益金额"), 0) FROM cf_amounts')
            info['cf_total_amount'] = float(round(total[0], 2)) if total else 0.0

            # 是否调整了余额表
            if self.engine._conn.execute(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'balance_adjusted'"
            ).fetchone()[0] > 0:
                info['balance_adjusted'] = True
                row_count = self._fetchone('SELECT COUNT(*) FROM balance_adjusted')
                info['balance_adjusted_rows'] = int(row_count[0]) if row_count else 0
            else:
                info['balance_adjusted'] = False

        except Exception:
            pass
        return info

    # ========== 方向调整视图 ==========

    def _drop_direction_views(self):
        """删除方向调整临时视图"""
        for view in ['_j_dir', '_b_dir']:
            try:
                self.engine._conn.execute(f'DROP VIEW IF EXISTS "{view}"')
            except Exception:
                pass

    def _setup_direction_views(self):
        """
        创建方向调整视图。
        如果数据中含有"方向"字段，根据借贷方向调整金额正负号：
        - 方向为'借'/'Debit'/'D'：金额保持原值
        - 其他方向（贷/Credit/C等）：金额取相反数
        科目余额表的期初余额方向/期末余额方向同理。
        """
        j_schema = self.engine.get_schema(self.journal_table) if self._table_exists(self.journal_table) else []
        b_schema = self.engine.get_schema(self.balance_table) if (self.balance_table and self._table_exists(self.balance_table)) else []
        j_cols = [col['name'] for col in j_schema]
        b_cols = [col['name'] for col in b_schema]

        has_j_dir = '方向' in j_cols
        has_bb_dir = '期初余额方向' in b_cols and '期初余额' in b_cols
        has_be_dir = '期末余额方向' in b_cols and '期末余额' in b_cols

        # 序时账方向调整
        if has_j_dir:
            select_parts = []
            for col in j_cols:
                if col == '金额':
                    select_parts.append(f"""
                        CASE WHEN "方向" IN ('借', 'Debit', 'D')
                             THEN CAST("金额" AS DOUBLE)
                             ELSE -CAST("金额" AS DOUBLE)
                        END AS "金额"
                    """)
                elif col == '科目编号':
                    select_parts.append(f'CAST("科目编号" AS VARCHAR) AS "科目编号"')
                else:
                    select_parts.append(f'"{col}"')
            self.engine._conn.execute(f"""
                CREATE OR REPLACE TEMP VIEW _j_dir AS
                SELECT {', '.join(select_parts)}
                FROM "{self.journal_table}"
            """)
            self.journal_table = '_j_dir'
            print(f"[DIRECTION] 序时账已应用方向调整")

        # 科目余额表方向调整
        if has_bb_dir or has_be_dir:
            select_parts = []
            for col in b_cols:
                if col == '期初余额' and has_bb_dir:
                    select_parts.append(f"""
                        CASE WHEN "期初余额方向" IN ('借', 'Debit', 'D')
                             THEN CAST("期初余额" AS DOUBLE)
                             ELSE -CAST("期初余额" AS DOUBLE)
                        END AS "期初余额"
                    """)
                elif col == '期末余额' and has_be_dir:
                    select_parts.append(f"""
                        CASE WHEN "期末余额方向" IN ('借', 'Debit', 'D')
                             THEN CAST("期末余额" AS DOUBLE)
                             ELSE -CAST("期末余额" AS DOUBLE)
                        END AS "期末余额"
                    """)
                elif col == '科目编号':
                    select_parts.append(f'CAST("科目编号" AS VARCHAR) AS "科目编号"')
                else:
                    select_parts.append(f'"{col}"')
            self.engine._conn.execute(f"""
                CREATE OR REPLACE TEMP VIEW _b_dir AS
                SELECT {', '.join(select_parts)}
                FROM "{self.balance_table}"
            """)
            self.balance_table = '_b_dir'
            print(f"[DIRECTION] 科目余额表已应用方向调整")

    # ========== 末级科目筛选 ==========

    def _drop_leaf_views(self):
        """删除末级科目临时视图"""
        for view in ['balance_leaf', 'balance_sorted']:
            try:
                self.engine._conn.execute(f'DROP VIEW IF EXISTS "{view}"')
            except Exception:
                pass
        self._leaf_setup_done = False

    def _setup_leaf_account_views(self):
        """
        创建末级科目筛选视图：
        1. 剔除科目编号为空/空字符串的行
        2. 剔除科目编号包含"计"的行（如"合计"、"小计"、"总计"）
        3. 按公司名+科目编号升序排列（短编码在前）
        4. 判断末级科目：若N行前4位与N+1行相同，且N行长度 < N+1行，则N不是末级科目
        """
        if self._leaf_setup_done:
            return
        self._drop_leaf_views()

        bt = self.balance_table
        if not bt or not self._table_exists(bt):
            raise ValueError("科目余额表不存在，无法筛选末级科目")

        schema = self._get_schema(bt)
        if '科目编号' not in schema:
            raise ValueError("科目余额表缺少「科目编号」字段，无法筛选末级科目")

        # 用窗口函数 LEAD 判断下一行
        # 末级判断：如果当前编码是下一行的前缀，则当前行不是末级（其下有子级）
        self.engine._conn.execute(f"""
            CREATE TEMP VIEW balance_leaf AS
            WITH sorted AS (
                SELECT * EXCLUDE ("科目编号"),
                    CAST("科目编号" AS VARCHAR) AS "科目编号",
                    LEAD(CAST("科目编号" AS VARCHAR)) OVER (
                        PARTITION BY "公司名"
                        ORDER BY CAST("科目编号" AS VARCHAR) ASC
                    ) AS _next_code
                FROM "{bt}"
                WHERE "科目编号" IS NOT NULL
                  AND CAST("科目编号" AS VARCHAR) != ''
                  AND CAST("科目编号" AS VARCHAR) NOT LIKE '%计%'
            )
            SELECT *
            FROM sorted
            WHERE _next_code IS NULL                                           -- 最后一行（必定是末级）
               OR CAST("科目编号" AS VARCHAR) !=
                  SUBSTR(_next_code, 1, LENGTH(CAST("科目编号" AS VARCHAR)))   -- 下个编码不以当前编码开头 → 当前是末级
        """)

        # 验证结果
        count = self._fetchone('SELECT COUNT(*) FROM balance_leaf')[0]
        orig_count = self._fetchone(f'SELECT COUNT(*) FROM "{bt}"')[0]
        print(f"[LEAF ACCOUNTS] 原始: {orig_count} 行 → 末级科目: {count} 行")

        self._leaf_setup_done = True

    def get_leaf_info(self, orig_table: str = None) -> dict:
        """返回末级科目筛选信息"""
        info = {}
        try:
            info['leaf_count'] = int(self._fetchone('SELECT COUNT(*) FROM balance_leaf')[0] or 0)
            orig = orig_table or self.balance_table
            info['original_count'] = int(
                self._fetchone(f'SELECT COUNT(*) FROM "{orig}"')[0] or 0
            ) if self._table_exists(orig) else 0
        except Exception:
            pass
        return info

    # ========== 导出数据生成（DuckDB SQL → DataFrame） ==========

    def _get_journal_export(self, table_name: str) -> Optional[pd.DataFrame]:
        """Sheet 1: 序时账完整性 — groupby 公司名+凭证号+日期，汇总发生额"""
        try:
            return self._fetchdf(SQL_EXPORT_JOURNAL.format(table=table_name))
        except Exception:
            # 表可能不存在或缺少字段
            pass
        return None

    def _get_balance_export(self, table_name: str) -> Optional[pd.DataFrame]:
        """Sheet 2: 科目余额表完整性 — groupby 公司名+科目编号+科目名称"""
        if not table_name:
            print(f"[BALANCE EXPORT] 科目余额表名为空，跳过导出")
            return None
        try:
            df = self._fetchdf(SQL_EXPORT_BALANCE.format(table=table_name))
            print(f"[BALANCE EXPORT] 成功导出 {len(df)} 行")
            return df
        except Exception as e:
            print(f"[BALANCE EXPORT] 导出失败: {e}")
        return None

    def _get_cross_export(self, j_table: str, b_table: str) -> Optional[pd.DataFrame]:
        """Sheet 3: 交叉验证 — FULL OUTER JOIN 两表按科目匹配"""
        try:
            # 用 try/except 获取 schema（兼容表和临时视图）
            def safe_get_cols(tbl: str) -> set:
                if not tbl:
                    return set()
                try:
                    return self._get_schema(tbl)
                except Exception as e:
                    print(f"[CROSS EXPORT] 无法获取 {tbl} 的 schema: {e}")
                    return set()

            j_cols = safe_get_cols(j_table)
            b_cols = safe_get_cols(b_table)
            print(f"[CROSS EXPORT] j_table={j_table}, j_cols={j_cols}")
            print(f"[CROSS EXPORT] b_table={b_table}, b_cols={b_cols}")

            j_required = {'公司名', '科目编号', '金额'}
            b_required = {'公司名', '科目编号', '科目名称', '期初余额', '期末余额'}
            missing_j = j_required - j_cols
            missing_b = b_required - b_cols
            if missing_j or missing_b:
                msg = []
                if missing_j:
                    msg.append(f"序时账缺少字段: {', '.join(sorted(missing_j))}")
                if missing_b:
                    msg.append(f"科目余额表缺少字段: {', '.join(sorted(missing_b))}")
                print(f"[CROSS EXPORT] 跳过导出：{'；'.join(msg)}")
                return None

            return self._fetchdf(SQL_EXPORT_CROSS.format(
                journal_table=j_table, balance_table=b_table
            ))
        except Exception as e:
            import traceback
            print(f"[CROSS EXPORT ERROR] {e}")
            traceback.print_exc()
        return None

    # ========== 导出报告（供 app.py 调用） ==========

    def export_report(self, reverse_carry_forward: bool = False,
                      leaf_accounts: bool = False,
                      cf_account_code: str = '4103',
                      cf_keywords: list = None) -> dict:
        """
        生成三个 Sheet 的导出数据。

        Args:
            reverse_carry_forward: 是否应用反结转
            leaf_accounts: 是否仅用末级科目
            cf_account_code: 反结转科目编号（默认 4103）
            cf_keywords: 反结转摘要关键词列表（默认 ["结转", "损益"]）

        Returns:
            {
                'journal': DataFrame | None,
                'balance': DataFrame | None,
                'cross_validation': DataFrame | None,
                'reverse_carry_forward_applied': bool,
                'carry_forward_info': dict | None,
                'leaf_accounts_applied': bool,
                'leaf_accounts_info': dict | None,
            }
        """
        orig_jt = self.journal_table
        orig_bt = self.balance_table

        cf_info = None
        leaf_info = None

        # 0. TRIM 文本列去空格（最先执行）
        self._setup_trim_views()

        # 1. 方向调整
        self._setup_direction_views()

        # 先末级科目筛选
        if leaf_accounts and self.balance_table and self._table_exists(self.balance_table):
            try:
                self._setup_leaf_account_views()
                self.balance_table = 'balance_leaf'
                leaf_info = self.get_leaf_info(orig_table=orig_bt)
            except Exception:
                self.balance_table = orig_bt
                leaf_info = {'error': '末级科目筛选失败，使用原始数据'}

        # 再反结转
        if reverse_carry_forward and self.balance_table and self._table_exists(self.journal_table):
            try:
                self._setup_carry_forward_views(cf_account_code=cf_account_code,
                                                 cf_keywords=cf_keywords)
                self.journal_table = 'journal_filtered'
                self.balance_table = 'balance_adjusted'
                cf_info = self.get_cf_info()
            except Exception:
                self.journal_table = orig_jt
                self.balance_table = orig_bt
                cf_info = {'error': '反结转执行失败，使用原始数据'}

        try:
            journal_df = self._get_journal_export(self.journal_table)
            balance_df = self._get_balance_export(self.balance_table)
            cross_df = self._get_cross_export(self.journal_table, self.balance_table)
        finally:
            self.journal_table = orig_jt
            self.balance_table = orig_bt
            self._drop_cf_views()
            self._drop_leaf_views()
            self._drop_direction_views()
            self._drop_trim_views()

        return {
            'journal': journal_df,
            'balance': balance_df,
            'cross_validation': cross_df,
            'reverse_carry_forward_applied': reverse_carry_forward,
            'carry_forward_info': cf_info,
            'leaf_accounts_applied': leaf_accounts,
            'leaf_accounts_info': leaf_info,
        }

    # ========== 原有测试方法（增强：支持反结转） ==========

    def test_journal_integrity(self) -> Dict[str, Any]:
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

        schema = self._get_schema(self.journal_table)
        required = {'公司名', '凭证号', '日期', '金额'}
        missing = required - schema
        if missing:
            result['status'] = 'error'
            result['message'] = f'序时账缺少以下字段: {", ".join(sorted(missing))}，无法完成完整性测试'
            result['missing_fields'] = list(missing)
            return result

        try:
            sql = f'''
                SELECT
                    "公司名",
                    "凭证号",
                    "日期",
                    CAST(SUM(CAST("金额" AS DOUBLE)) AS DOUBLE) AS "汇总发生额"
                FROM "{self.journal_table}"
                WHERE "凭证号" IS NOT NULL
                  AND CAST("凭证号" AS VARCHAR) != ''
                GROUP BY "公司名", "凭证号", "日期"
            '''
            headers, rows = self._describe(sql)
            total_groups = len(rows)
            total_amount = sum(round(r[3] or 0, 2) for r in rows)

            positive_groups = sum(1 for r in rows if round(r[3] or 0, 2) > 0)
            negative_groups = sum(1 for r in rows if round(r[3] or 0, 2) < 0)
            zero_groups = sum(1 for r in rows if round(r[3] or 0, 2) == 0)

            groups_preview = [
                dict(zip(headers, r)) for r in rows[:20]
            ]

            result['status'] = 'completed'
            result['message'] = '序时账完整性测试完成' + (
                '（已剔除结转损益凭证）' if 'journal_filtered' in str(self.journal_table) else ''
            )
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

    def test_balance_integrity(self) -> Dict[str, Any]:
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

        schema = self._get_schema(self.balance_table)
        required = {'期初余额', '期末余额'}
        missing = required - schema
        if missing:
            result['status'] = 'error'
            result['message'] = f'科目余额表缺少以下字段: {", ".join(sorted(missing))}，无法完成完整性测试'
            result['missing_fields'] = list(missing)
            return result

        try:
            row = self._fetchone(f'''
                SELECT
                    CAST(SUM(CAST("期初余额" AS DOUBLE)) AS DOUBLE),
                    CAST(SUM(CAST("期末余额" AS DOUBLE)) AS DOUBLE),
                    CAST(SUM(CAST("期末余额" AS DOUBLE)) - SUM(CAST("期初余额" AS DOUBLE)) AS DOUBLE)
                FROM "{self.balance_table}"
            ''')

            total_beginning = row[0] or 0.0
            total_ending = row[1] or 0.0
            total_occurrence = row[2] or 0.0
            balance_check = abs(total_occurrence) < 0.01

            count_row = self._fetchone(
                f'SELECT COUNT(*) FROM "{self.balance_table}"'
            )

            result['status'] = 'completed'
            result['message'] = '科目余额表完整性测试完成' + (
                '（已执行反结转调整）' if 'balance_adjusted' in str(self.balance_table) else ''
            )
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

    def test_cross_validation(self) -> Dict[str, Any]:
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

        j_schema = self._get_schema(self.journal_table)
        b_schema = self._get_schema(self.balance_table)

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
            sql = f'''
                WITH journal_agg AS (
                    SELECT
                        "公司名",
                        CAST("科目编号" AS VARCHAR) AS "科目编号",
                        "科目名称",
                        CAST(SUM(CAST("金额" AS DOUBLE)) AS DOUBLE) AS "序时账发生额"
                    FROM "{self.journal_table}"
                    WHERE "凭证号" IS NOT NULL
                      AND CAST("凭证号" AS VARCHAR) != ''
                    GROUP BY "公司名", "科目编号", "科目名称"
                ),
                balance_agg AS (
                    SELECT
                        "公司名",
                        CAST("科目编号" AS VARCHAR) AS "科目编号",
                        "科目名称",
                        CAST(
                            SUM(CAST("期末余额" AS DOUBLE)) - SUM(CAST("期初余额" AS DOUBLE))
                        AS DOUBLE) AS "余额表发生额"
                    FROM "{self.balance_table}"
                    GROUP BY "公司名", "科目编号", "科目名称"
                )
                SELECT
                    COALESCE(CAST(j."公司名" AS VARCHAR), CAST(b."公司名" AS VARCHAR)) AS "公司名",
                    COALESCE(CAST(j."科目编号" AS VARCHAR), CAST(b."科目编号" AS VARCHAR)) AS "科目编号",
                    COALESCE(CAST(j."科目名称" AS VARCHAR), CAST(b."科目名称" AS VARCHAR)) AS "科目名称",
                    COALESCE(CAST(j."序时账发生额" AS DOUBLE), 0.0) AS "序时账发生额",
                    COALESCE(CAST(b."余额表发生额" AS DOUBLE), 0.0) AS "余额表发生额",
                    COALESCE(CAST(j."序时账发生额" AS DOUBLE), 0.0) - COALESCE(CAST(b."余额表发生额" AS DOUBLE), 0.0) AS "差异"
                FROM journal_agg j
                FULL OUTER JOIN balance_agg b
                    ON CAST(j."公司名" AS VARCHAR) = CAST(b."公司名" AS VARCHAR)
                    AND CAST(j."科目编号" AS VARCHAR) = CAST(b."科目编号" AS VARCHAR)
                    AND CAST(j."科目名称" AS VARCHAR) = CAST(b."科目名称" AS VARCHAR)
                ORDER BY ABS("差异") DESC
            '''

            headers, rows = self._describe(sql)
            total_accounts = len(rows)

            consistent_count = 0
            difference_count = 0
            only_in_journal = 0
            only_in_balance = 0
            diff_records = []
            only_journal_records = []
            only_balance_records = []
            journal_total = 0.0
            balance_total = 0.0

            for r in rows:
                j_amount = r[3] or 0.0
                b_amount = r[4] or 0.0
                diff_amount = r[5] or 0.0
                journal_total += j_amount
                balance_total += b_amount

                if j_amount > 0 and b_amount == 0:
                    only_in_journal += 1
                elif j_amount == 0 and b_amount > 0:
                    only_in_balance += 1

                is_both = j_amount > 0 and b_amount > 0

                if abs(diff_amount) > 0.01:
                    if is_both:
                        difference_count += 1
                    if len(diff_records) < 20:
                        diff_records.append(dict(zip(headers, r)))
                elif j_amount > 0 and b_amount > 0:
                    consistent_count += 1

                if j_amount > 0 and b_amount == 0 and len(only_journal_records) < 10:
                    only_journal_records.append(dict(zip(headers, r)))
                if j_amount == 0 and b_amount > 0 and len(only_balance_records) < 10:
                    only_balance_records.append(dict(zip(headers, r)))

            is_consistent = difference_count == 0 and only_in_journal == 0 and only_in_balance == 0

            result['status'] = 'completed'
            result['message'] = '交叉验证完成' + (
                '（已应用反结转）' if 'journal_filtered' in str(self.journal_table) else ''
            )
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

    # ========== 运行全部测试（增强：支持反结转 + 末级科目） ==========

    def run_all(self, reverse_carry_forward: bool = False,
                leaf_accounts: bool = False,
                balance_snapshot_table: str = None,
                cf_account_code: str = '4103',
                cf_keywords: list = None) -> Dict[str, Any]:
        """
        运行全部完整性测试。

        Args:
            reverse_carry_forward: 是否应用反结转（金蝶/用友模式）
            leaf_accounts: 是否仅用末级科目（从科目余额表中筛选末级科目）
            balance_snapshot_table: 非空时，在清理前将最终科目余额表快照到该表名
            cf_account_code: 反结转科目编号（默认 4103）
            cf_keywords: 反结转摘要关键词列表（默认 ["结转", "损益"]）
        """
        orig_jt = self.journal_table
        orig_bt = self.balance_table
        cf_info = None
        leaf_info = None

        # 0. TRIM 文本列去空格（最先执行）
        self._setup_trim_views()

        # 1. 方向调整
        self._setup_direction_views()

        # 先应用末级科目筛选（如果有）
        if leaf_accounts and self.balance_table and self._table_exists(self.balance_table):
            try:
                self._setup_leaf_account_views()
                self.balance_table = 'balance_leaf'
                leaf_info = self.get_leaf_info(orig_table=orig_bt)
            except Exception as e:
                self.balance_table = orig_bt
                leaf_info = {'error': str(e)}

        # 再应用反结转（在末级科目之上继续调整）
        if reverse_carry_forward and self.balance_table and self._table_exists(self.journal_table):
            try:
                self._setup_carry_forward_views(cf_account_code=cf_account_code,
                                                 cf_keywords=cf_keywords)
                self.journal_table = 'journal_filtered'
                self.balance_table = 'balance_adjusted'
                cf_info = self.get_cf_info()
            except Exception as e:
                self.journal_table = orig_jt
                self.balance_table = orig_bt
                cf_info = {'error': str(e)}

        try:
            results = {
                'journal_test': self.test_journal_integrity(),
                'balance_test': self.test_balance_integrity(),
                'cross_test': self.test_cross_validation()
            }
            # 在 finally 清理之前，快照当前处理后的科目余额表
            if balance_snapshot_table and self.balance_table:
                try:
                    # 先删除旧表确保干净，再重新从当前处理后的视图/表创建
                    self.engine._conn.execute(
                        f'DROP TABLE IF EXISTS "{balance_snapshot_table}"'
                    )
                    self.engine._conn.execute(
                        f'CREATE TABLE "{balance_snapshot_table}" AS '
                        f'SELECT * FROM "{self.balance_table}"'
                    )
                    import logging
                    logging.getLogger('checker').info(
                        f'[SNAPSHOT] 已从 {self.balance_table} 快照到 {balance_snapshot_table}'
                    )
                except Exception as e:
                    import logging
                    logging.getLogger('checker').warning(
                        f'[SNAPSHOT] 快照失败: {e}'
                    )
        finally:
            self.journal_table = orig_jt
            self.balance_table = orig_bt
            self._drop_cf_views()
            self._drop_leaf_views()
            self._drop_direction_views()
            self._drop_trim_views()

        total = 3
        completed = sum(1 for r in results.values() if r['status'] == 'completed')
        errors = sum(1 for r in results.values() if r['status'] == 'error')
        skipped = sum(1 for r in results.values() if r['status'] == 'skipped')

        output = {
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
            ),
            'reverse_carry_forward_applied': reverse_carry_forward,
            'leaf_accounts_applied': leaf_accounts,
        }
        if cf_info:
            output['carry_forward_info'] = cf_info
        if leaf_info:
            output['leaf_accounts_info'] = leaf_info

        return output
