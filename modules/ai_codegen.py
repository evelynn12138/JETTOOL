import requests
import json
import re
from typing import Dict, List, Any, Optional, Tuple
import time

class AICodeGenerator:
    """AI代码生成模块 - 负责调用AI API生成DuckDB SQL（支持DeepSeek/百炼/Kimi等OpenAI兼容API）"""

    def __init__(self, api_key: str, provider: str = "deepseek", api_url: str = None, model: str = None):
        """
        初始化AI代码生成器

        Args:
            api_key: API密钥
            provider: 供应商ID（deepseek/bailian/kimi）
            api_url: API端点URL（覆盖供应商默认值）
            model: 模型名称（覆盖供应商默认值）
        """
        self.api_key = api_key
        self.provider = provider

        # 加载供应商配置
        from config import Config
        provider_config = Config.AI_PROVIDERS.get(provider, Config.AI_PROVIDERS["deepseek"])

        self.api_url = api_url or provider_config["api_url"]
        self.model = model or provider_config["model"]
        self.temperature = 0.3
        self.max_tokens = 2000

    def generate(self, query: str, fields_info: List[Dict[str, Any]],
                data_preview: Optional[List[Dict]] = None) -> str:
        """
        生成DuckDB SQL查询

        Args:
            query: 用户查询语句
            fields_info: 字段信息列表
            data_preview: 数据预览（可选）

        Returns:
            生成的SQL查询语句
        """
        if not query or not query.strip():
            raise ValueError("查询语句不能为空")

        try:
            prompt = self._build_prompt(query, fields_info, data_preview)
            response = self._call_api(prompt)
            sql = self._extract_code(response)

            if not sql:
                raise ValueError("生成的 SQL 为空")

            sql = self._fix_strftime(sql)

            if not self._validate_sql(sql):
                raise ValueError("生成的 SQL 包含非 SELECT 操作")

            return sql
        except Exception as e:
            raise Exception(f"SQL 生成失败: {str(e)}") from e

    def _build_prompt(self, query: str, fields_info: List[Dict[str, Any]],
                     data_preview: Optional[List[Dict]]) -> str:
        fields_desc = []
        for field in fields_info:
            field_desc = f"- {field['name']} ({field['type']})"
            if field.get('sample'):
                field_desc += f" 示例: {field['sample']}"
            fields_desc.append(field_desc)
        fields_str = "\n".join(fields_desc)

        preview_str = ""
        if data_preview and len(data_preview) > 0:
            preview_lines = ["数据预览:"]
            for i, row in enumerate(data_preview[:3]):
                row_str = ", ".join([f"{k}: {v}" for k, v in row.items()])
                preview_lines.append(f"  行{i+1}: {row_str}")
            preview_str = "\n".join(preview_lines)

        prompt = f"""你是一个专业的财务数据分析专家，专门处理财务序时账数据。

## 任务要求
根据用户的自然语言查询，生成 DuckDB SQL 查询语句来处理财务数据。

## 数据表信息
表名: data
字段信息:
{fields_str}

{preview_str}

## 用户查询
{query}

## 财务数据特点
1. 财务数据通常包含凭证信息，一个凭证可能有多个行项目（借方和贷方）
2. 常见财务字段：日期、凭证号、摘要、科目名称、借方金额、贷方金额、制单人
3. 如果还有科目余额表可用，表名为 balance_data，包含字段：公司名、科目编号、科目名称、期初余额、期末余额等

## SQL 要求
1. **必须只包含 SELECT 查询**，不包含 INSERT/UPDATE/DELETE/CREATE/DROP/ALTER
2. 使用双引号包裹表名和列名（防止中文字符问题）：如 FROM "data"
3. 金额字段可能需要 CAST 为 DOUBLE：CAST("金额" AS DOUBLE)
4. **日期处理**：严禁使用 strftime 函数。替代方案：
   - 提取年份：EXTRACT(YEAR FROM CAST("日期" AS DATE))
   - 提取月份：EXTRACT(MONTH FROM CAST("日期" AS DATE))
   - 年月分组：DATE_TRUNC('month', CAST("日期" AS DATE))
   - 日期筛选：WHERE "日期" >= '2024-01-01'
5. 文本匹配使用：WHERE "摘要" LIKE '%关键词%'
6. 聚合函数：SUM, COUNT, AVG, MAX, MIN
7. 分组使用 GROUP BY，排序使用 ORDER BY
8. **不要使用 LIMIT**，查询结果不限制行数，返回所有匹配记录
9. 有科目余额表时可以用 JOIN：FROM "data" d JOIN "balance_data" b ON ...
10. **保持 SQL 简洁**：能用简单条件表达的就不要写子查询。例如周末判断直接用 `EXTRACT(DOW FROM CAST("日期" AS DATE)) IN (0, 6)`，不要生成日期序列表。
11. **注意：如果查询中的关键词包含括号同义词标注，如"交易(transaction/txn)"，括号内是对主词的说明，只需对主词（如"交易"）生成 LIKE 条件即可，不需要对括号内每个词单独生成条件。**

## 输出要求
请只返回 SQL 代码，不要包含解释或额外文本。SQL 必须完整且可执行。

```sql
```"""

        return prompt

    def _call_api(self, prompt: str) -> str:
        """
        调用DeepSeek API

        Args:
            prompt: 提示词

        Returns:
            API响应内容
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一个专业的SQL数据分析专家，专门生成DuckDB SQL查询。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False
        }

        try:
            response = requests.post(
                self.api_url,
                headers=headers,
                json=data,
                timeout=30  # 30秒超时
            )

            if response.status_code != 200:
                error_msg = f"API请求失败: {response.status_code}"
                try:
                    error_detail = response.json().get('error', {}).get('message', '未知错误')
                    error_msg += f" - {error_detail}"
                except Exception:
                    pass
                raise Exception(error_msg)

            result = response.json()
            content = result['choices'][0]['message']['content']

            return content

        except requests.exceptions.Timeout:
            raise Exception("API请求超时，请稍后重试")
        except requests.exceptions.ConnectionError:
            raise Exception("网络连接失败，请检查网络设置")
        except Exception as e:
            raise Exception(f"API调用异常: {str(e)}")

    def _extract_code(self, response_content: str) -> str:
        """从 API 响应中提取 SQL 代码"""
        content = response_content.strip()

        code_patterns = [
            r"```sql\n(.*?)```",
            r"```\n(.*?)```",
            r"```(?:sql)?\s*\n(.*?)\n```",
            r"```(?:sql)?(.*?)```",
        ]

        matches = []
        for pattern in code_patterns:
            try:
                found = re.findall(pattern, content, re.DOTALL)
                if found:
                    matches.extend(found)
                    break
            except re.error:
                continue

        if matches:
            sql = matches[-1].strip()
        else:
            # 尝试从响应中提取以 SELECT/WITH 开头的内容
            lines = content.split('\n')
            sql_lines = []
            in_sql = False
            for line in lines:
                stripped = line.strip()
                if stripped.upper().startswith('SELECT') or stripped.upper().startswith('WITH'):
                    in_sql = True
                if in_sql:
                    sql_lines.append(line)
            sql = '\n'.join(sql_lines).strip() if sql_lines else content

        sql_lines = [line.rstrip() for line in sql.split('\n') if line.strip()]
        return '\n'.join(sql_lines)

    def _validate_sql(self, sql: str) -> bool:
        """
        验证 SQL 安全性 - 只允许 SELECT 查询

        Returns:
            是否安全
        """
        sql_trimmed = sql.strip()
        if not sql_trimmed:
            return False

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

    def _fix_strftime(self, sql: str) -> str:
        """将 strftime 调用替换为等效的标准 SQL。"""
        # strftime("col", '%Y-%m-%d') → CAST(CAST("col" AS DATE) AS VARCHAR)
        sql = re.sub(
            r'strftime\(\s*"([^"]+)"\s*,\s*\'%Y-%m-%d\'\s*\)',
            r'CAST(CAST("\1" AS DATE) AS VARCHAR)',
            sql
        )
        # strftime("col", '%Y-%m') → DATE_TRUNC
        sql = re.sub(
            r'strftime\(\s*"([^"]+)"\s*,\s*\'%Y-%m\'\s*\)',
            r"CAST(DATE_TRUNC('month', CAST(\"\1\" AS DATE)) AS VARCHAR)",
            sql
        )
        # strftime("col", '%Y') → EXTRACT YEAR
        sql = re.sub(
            r'strftime\(\s*"([^"]+)"\s*,\s*\'%Y\'\s*\)',
            r'CAST(EXTRACT(YEAR FROM CAST("\1" AS DATE)) AS VARCHAR)',
            sql
        )
        # strftime("col", '%m') → EXTRACT MONTH
        sql = re.sub(
            r'strftime\(\s*"([^"]+)"\s*,\s*\'%m\'\s*\)',
            r"LPAD(CAST(EXTRACT(MONTH FROM CAST(\"\1\" AS DATE)) AS VARCHAR), 2, '0')",
            sql
        )
        # 兜底：其他 strftime 调用替换为 CAST(CAST(col AS DATE) AS VARCHAR)
        sql = re.sub(
            r'strftime\(\s*"([^"]+)"\s*,\s*\'[^\']*\'\s*\)',
            r'CAST(CAST("\1" AS DATE) AS VARCHAR)',
            sql
        )
        return sql

    def explain_code(self, sql: str) -> str:
        """
        解释SQL查询功能

        Args:
            sql: SQL查询语句

        Returns:
            SQL功能解释
        """
        prompt = f"""逐行解释以下 DuckDB SQL 查询的关键代码行，每条一句话：

```sql
{sql}
```

要求：
- 只解释 SQL 中实际使用的子句，没出现的不要提
- 每行格式：{{代码行}} — {{一句话说明}}
- 简洁，不要多余内容"""

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "你是一个专业的 SQL 解释器。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 500
            }
            response = requests.post(
                self.api_url,
                headers=headers,
                json=data,
                timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                explanation = result['choices'][0]['message']['content']
                return explanation.strip()
            else:
                return "无法生成 SQL 解释。"
        except Exception:
            return "解释生成失败。"

    def optimize_query(self, query: str, local_expanded: str = None) -> str:
        """
        优化自然语言查询，扩展同义词，使其更清晰、更具体

        Args:
            query: 原始查询语句
            local_expanded: 本地词典初步扩展后的查询（可选，供AI参考）

        Returns:
            优化后的查询语句
        """
        extra_context = ""
        if local_expanded and local_expanded != query:
            extra_context = f"""

本地词典初步扩展参考:
{local_expanded}
"""

        prompt = f"""你是一个财务数据分析专家，负责优化用户的自然语言查询。

原始查询: "{query}"{extra_context}

请按以下规则优化：

1. **把模糊概念变成具体可搜索的表达**
   - "月底" → "每个月最后五天"
   - "月初" → "每个月前五天"
   - "最近" → "近30天"
   让表达可直接对应 SQL 条件。

2. **扩展中文关键词的英文/缩写/常见变体**
   - "调整" → "调整、adj、adjustment、reverse"
   - "冲销" → "冲销、reverse、reversal"
   - "费用报销" → "费用报销、报销、expense"
   - 只扩展**具体的查询关键词**，不要扩展字段名（如"摘要"、"制单人"不扩展）。

3. **识别具体的人名（2~3字），补充拼音/首字母变体**
   - "周健" → "周健（含 zhoujian、zhou jian、zj、ZJ 等变体）"
   - 仅在明确的人名值上做此操作。

4. **优化后的语句保持中文，清晰可读，可直接用于生成 SQL**
   - 不需要用等号或引号括起关键词。
   - 不要添加原查询没有的新条件。
   - 用"等"或"等相关关键词"收尾列举。

优化后的查询:"""

        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            data = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": '你是财务数据查询优化专家。把模糊概念变具体（月底→最后五天），扩展关键词的英文/缩写变体（调整→adj、adjustment），识别人名加拼音变体。不扩展字段名。'},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 800
            }

            response = requests.post(
                self.api_url,
                headers=headers,
                json=data,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                optimized_query = result['choices'][0]['message']['content'].strip()
                # 清理响应内容，只保留查询语句
                optimized_query = optimized_query.replace('优化后的查询:', '').replace('优化查询:', '').strip()
                return optimized_query
            else:
                return query  # 如果失败，返回原始查询

        except Exception:
            return query  # 如果失败，返回原始查询

    def test_generation(self, sample_query: str = None) -> Tuple[bool, str]:
        """
        测试SQL生成功能

        Args:
            sample_query: 测试查询（可选）

        Returns:
            (是否成功, 消息)
        """
        try:
            test_query = sample_query or "统计每个科目的总金额"
            test_fields = [
                {'name': '科目名称', 'type': 'text', 'sample': '管理费用'},
                {'name': '金额', 'type': 'number', 'sample': 1000.00}
            ]
            sql = self.generate(test_query, test_fields)

            if not sql or len(sql) < 10:
                return False, "生成的 SQL 过短或无内容"

            if not sql.upper().lstrip().startswith('SELECT') and not sql.upper().lstrip().startswith('WITH'):
                return False, "生成的代码不是 SELECT 查询"

            return True, f"测试成功！生成的 SQL 长度: {len(sql)} 字符"

        except Exception as e:
            return False, f"测试失败: {str(e)}"