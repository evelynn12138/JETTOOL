"""
Dify Workflow API 客户端
通过 Dify Workflow 代理所有非 Function Calling 场景的 AI 调用。
Dify 端配置：Qwen3-30B-A3B, temperature=0.7, max_tokens=4096
"""

import requests
import json


class DifyClient:
    """Dify Workflow API 客户端"""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key

    def chat(self, system_prompt: str, user_prompt: str, timeout: int = 60) -> str:
        """
        发送到 Dify Workflow，返回 LLM 响应文本。

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            timeout: 请求超时秒数

        Returns:
            LLM 响应文本

        Raises:
            Exception: 请求失败或 Workflow 执行失败
        """
        url = f"{self.base_url}/workflows/run"

        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "inputs": {
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                    },
                    "response_mode": "blocking",
                    "user": "flask-app",
                },
                timeout=timeout,
            )
        except requests.exceptions.Timeout:
            raise Exception("Dify 请求超时，请稍后重试")
        except requests.exceptions.ConnectionError:
            raise Exception("无法连接 Dify 服务，请检查网络和 Dify 地址")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Dify 请求失败: {e}")

        if resp.status_code != 200:
            try:
                err_detail = resp.json()
            except Exception:
                err_detail = resp.text[:500]
            raise Exception(
                f"Dify API 返回错误 ({resp.status_code}): {err_detail}"
            )

        data = resp.json()
        run_data = data.get("data", {})

        if run_data.get("status") == "failed":
            error_msg = run_data.get("error", "unknown error")
            raise Exception(f"Dify Workflow 执行失败: {error_msg}")

        outputs = run_data.get("outputs", {}) or {}
        text = outputs.get("text", "")
        if not text:
            # 尝试其他可能的 output key
            for key in ("result", "response", "output", "content"):
                text = outputs.get(key, "")
                if text:
                    break

        if not text:
            raise Exception("Dify Workflow 返回内容为空")

        return text
