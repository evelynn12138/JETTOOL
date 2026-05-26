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
    MAX_CONTENT_LENGTH = 2048 * 1024 * 1024  # 2GB
    UPLOAD_FOLDER = 'temp'
    DUCKDB_DIR = 'temp/db'
    ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}

    # AI API配置
    DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
    DEEPSEEK_MODEL = "deepseek-chat"
    DEEPSEEK_TEMPERATURE = 0.3

    # AI供应商配置
    AI_PROVIDERS = {
        "deepseek": {
            "name": "DeepSeek",
            "api_url": "https://api.deepseek.com/v1/chat/completions",
            "model": "deepseek-chat",
            "doc_url": "https://platform.deepseek.com/api-keys",
        },
        "bailian": {
            "name": "阿里云百炼",
            "api_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            "model": "qwen-plus",
            "doc_url": "https://bailian.console.aliyun.com/",
            # 预置加密 API Key（由 SECRET_KEY 加密），用户无需手动输入
            "encrypted_key": "gAAAAABqECdxLLuKIXVEr5VrpActOhutpUVBdLwSkBpneFTcdkeHcoYOyeiRH4xvShoJNVRRhfaGWI7nlaS7U2CsneGoeNsjosx2ZwcDL-Jo38Z_5rgmDAGYgF5JDcNeBQ1hFKgn7vvW",
            "pre_configured": True,
        },
        "kimi": {
            "name": "Kimi (月之暗面)",
            "api_url": "https://api.moonshot.cn/v1/chat/completions",
            "model": "moonshot-v1-8k",
            "doc_url": "https://platform.moonshot.cn/console/api-keys",
        },
    }

    # 数据预览配置
    PREVIEW_ROWS = 10
    MAX_ROWS_PREVIEW = 10000