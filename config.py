import os
from datetime import timedelta

class Config:
    # 重要：SECRET_KEY 也用作 API Key 加密密钥，变更后已加密的 Key 将无法解密
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'da-clean-app-secret-key-2026'
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)

    # 文件上传配置
    MAX_CONTENT_LENGTH = 4096 * 1024 * 1024  # 4GB（原 2GB，根据用户需求调大）
    UPLOAD_FOLDER = 'temp'
    DUCKDB_DIR = 'temp/db'
    ALLOWED_EXTENSIONS = {'xlsx', 'csv', 'xls'}

    # ── Dify Workflow AI 代理配置 ──
    # 所有 AI 调用（SQL生成、字段映射、报表识别等）通过 Dify Workflow 代理。
    # Dify 端配置了模型 Qwen3-235B-A3B（temperature=0.7, max_tokens=4096）。
    #
    # 【维护说明】
    # 如需修改 Dify 地址或 Key，请直接修改下方 DIFY_MAIN_* / DIFY_REVIEW_* 的值。
    #
    # 主要 Dify Workflow — 用于 SQL 生成、字段映射、报表清洗、AI 差异分析等
    DIFY_MAIN_BASE_URL = "https://ai-platform-uat.ey.net/v1"
    DIFY_MAIN_API_KEY = "app-ARr9EIyUv4i5RXPNW2CwdoP5"
    # 复核 Dify Workflow — 用于 SQL 代码复核审查
    DIFY_REVIEW_BASE_URL = "https://ai-platform-uat.ey.net/v1"
    DIFY_REVIEW_API_KEY = "app-uuvpkgtY94HcQLgxDmaR5QLi"

    # 数据预览配置
    PREVIEW_ROWS = 10
    MAX_ROWS_PREVIEW = 10000