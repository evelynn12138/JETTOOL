import os
from datetime import timedelta
from dotenv import load_dotenv

# 加载 .env 文件（开发环境 / 本地部署）
# 优先读 .env 中的环境变量，再读系统环境变量
load_dotenv()

class Config:
    # 重要：SECRET_KEY 也用作 API Key 加密密钥，变更后已加密的 Key 将无法解密
    SECRET_KEY = os.environ.get('SECRET_KEY', 'da-clean-app-secret-key-2026')
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)

    # 文件上传配置
    MAX_CONTENT_LENGTH = 4096 * 1024 * 1024  # 4GB
    UPLOAD_FOLDER = 'temp'
    DUCKDB_DIR = 'temp/db'
    ALLOWED_EXTENSIONS = {'xlsx', 'csv', 'xls'}

    # ── Dify Workflow AI 代理配置（优先读环境变量，回退到占位值） ──
    # 部署前请在 .env 文件或系统环境变量中配置真实 Key。
    # 所有 AI 调用（SQL 生成、字段映射、报表识别等）通过 Dify Workflow 代理。
    # Dify 端配置了模型 Qwen3-235B-A3B（temperature=0.7, max_tokens=4096）。
    #
    # 主要 Dify Workflow — 用于 SQL 生成、字段映射、报表清洗、AI 差异分析等
    DIFY_MAIN_BASE_URL = os.environ.get('DIFY_MAIN_BASE_URL', 'https://ai-platform-uat.ey.net/v1')
    DIFY_MAIN_API_KEY = os.environ.get('DIFY_MAIN_API_KEY', 'your-dify-main-api-key-here')
    # 复核 Dify Workflow — 用于 SQL 代码复核审查
    DIFY_REVIEW_BASE_URL = os.environ.get('DIFY_REVIEW_BASE_URL', 'https://ai-platform-uat.ey.net/v1')
    DIFY_REVIEW_API_KEY = os.environ.get('DIFY_REVIEW_API_KEY', 'your-dify-review-api-key-here')

    # 数据预览配置
    PREVIEW_ROWS = 10
    MAX_ROWS_PREVIEW = 10000