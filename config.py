import os
import secrets
import sys
from datetime import timedelta
from dotenv import load_dotenv
from modules.crypto_utils import decrypt as _fernet_decrypt

# ── 环境加载 ──
# load_dotenv() 默认 override=False：系统环境变量优先于 .env 同名变量。
# 先记录系统环境是否已有 SECRET_KEY，用于识别其来源（系统 vs .env）。
_had_system_secret = 'SECRET_KEY' in os.environ
load_dotenv()

# 仅显式开启才允许默认 SECRET_KEY（禁止生产）
_DEV_ALLOW_DEFAULT = os.environ.get('DA_DEV_ALLOW_DEFAULT_SECRET', '').strip().lower() in ('1', 'true', 'yes')


def _find_secret_key_file():
    """独立 secret_key 文件（与 .env 不同源，加密工具/启动脚本写入）。"""
    for p in (os.path.join(os.getcwd(), 'secret_key'),
              os.path.join(os.path.expanduser('~'), '.da-cleaner', 'secret_key')):
        if os.path.isfile(p):
            try:
                val = open(p, encoding='utf-8').read().strip()
                if val:
                    return val
            except OSError:
                continue
    return None


def _find_bundle():
    """定位打包注入的 key bundle（dify_bundle.enc）。
    - PyInstaller 冻结态：sys._MEIPASS 根目录
    - Electron / 源码：os.getcwd() 或 config.py 所在目录
    """
    candidates = []
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        candidates.append(os.path.join(sys._MEIPASS, 'dify_bundle.enc'))
    candidates.append(os.path.join(os.getcwd(), 'dify_bundle.enc'))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dify_bundle.enc'))
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _load_bundle():
    """读取打包注入的 key bundle。

    返回 (bundled_secret, bundled_data_dict) 或 (None, {})。
    bundled_data 形如 {"DIFY_MAIN_API_KEY": "enc:...", "DIFY_REVIEW_API_KEY": "enc:...", "secret": "..."}
    """
    path = _find_bundle()
    if not path:
        return None, {}
    try:
        import json as _json
        data = _json.loads(open(path, encoding='utf-8').read())
        return data.get('secret'), data
    except Exception:
        return None, {}


def _load_secret_key():
    """解析 SECRET_KEY。返回 (session_secret, decrypt_key_or_None, source)。

    来源优先级：
      0b. 打包注入的 bundle（零配置分发，exe 内置密钥）
      1. 系统环境变量（真实环境，可信）
      2. 独立 secret_key 文件（加密工具/启动脚本写入，可信）
      3. 开发模式（DA_DEV_ALLOW_DEFAULT_SECRET=1）→ 默认值（警告）
      4. 缺失 → 一次性会话密钥；加密 Dify Key 无法解密，明文 Key 不受影响

    特殊：若 SECRET_KEY 只在 .env 里出现（与密文同源），仅用于会话签名，
          不作为解密密钥，并打警告——堵住"密钥与密文同源"的后门。
    """
    # 0b) 打包注入的 bundle（优先级最高，用户零配置打开即用）
    _bundle_secret, _ = _load_bundle()
    if _bundle_secret:
        return _bundle_secret, _bundle_secret, 'bundle'

    # 1) 系统环境变量
    sys_secret = os.environ.get('SECRET_KEY', '').strip()
    if sys_secret:
        if _had_system_secret:
            return sys_secret, sys_secret, 'system'
        # 系统环境没有、load_dotenv 之后才有 → 来自 .env，同源风险
        print('[警告] 检测到 SECRET_KEY 写在 .env 中！密钥与密文同源会使加密失效，'
              '请将其移出 .env，改为系统环境变量或启动脚本注入。', file=sys.stderr)
        return sys_secret, None, 'envfile'

    # 2) 独立 secret_key 文件
    file_secret = _find_secret_key_file()
    if file_secret:
        return file_secret, file_secret, 'file'

    # 3) 开发模式默认值（显式开启才允许）
    if _DEV_ALLOW_DEFAULT:
        print('[警告] DA_DEV_ALLOW_DEFAULT_SECRET=1：使用开发默认 SECRET_KEY，'
              '仅限本地调试，禁止生产！', file=sys.stderr)
        return 'da-clean-app-secret-key-2026', 'da-clean-app-secret-key-2026', 'dev'

    # 4) 缺失：一次性会话密钥（重启失效）；加密 Key 无法解密，明文 Key 兼容
    print('[警告] 未检测到 SECRET_KEY：加密的 Dify Key 将无法解密（明文 Key 不受影响）。\n'
          '       请设置系统环境变量，或运行 python tools/encrypt_env.py 生成 secret_key 文件。\n'
          '       示例： export SECRET_KEY="$(cat secret_key)"', file=sys.stderr)
    return secrets.token_hex(32), None, 'ephemeral'


_session_secret, _dify_enc_key, _secret_source = _load_secret_key()

# 打包注入的 bundle 数据（供 Config 读 key，bundle 优先于 env/.env）
_bundle_secret, _bundle_data = _load_bundle()


def _resolve_dify_key(raw_value, key_name):
    """读取 Dify API Key：
    - enc: 前缀 → 用 _dify_enc_key 解密；缺密钥/解密失败 → 返回 ''（优雅降级，AI 禁用）
    - 其他值 → 视为明文直接使用（向后兼容）
    """
    raw = (raw_value or '').strip()
    if not raw:
        return ''
    if raw.startswith('enc:'):
        ciphertext = raw[4:]
        if not _dify_enc_key:
            print(f'[错误] {key_name} 为加密格式(enc:)，但缺少有效 SECRET_KEY，无法解密。'
                  'AI 功能将不可用，请正确配置 SECRET_KEY 后重启。', file=sys.stderr)
            return ''
        try:
            return _fernet_decrypt(ciphertext, _dify_enc_key)
        except Exception as e:
            print(f'[错误] {key_name} 解密失败(SECRET_KEY 不匹配或密文损坏?)：{e}。'
                  'AI 功能将不可用，请检查 SECRET_KEY 是否与加密时一致。', file=sys.stderr)
            return ''
    return raw


class Config:
    # 会话签名密钥：始终为字符串（缺省时一次性，重启失效）
    SECRET_KEY = _session_secret

    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    SESSION_USE_SIGNER = True
    PERMANENT_SESSION_LIFETIME = timedelta(hours=1)

    # 文件上传配置
    MAX_CONTENT_LENGTH = 4096 * 1024 * 1024  # 4GB
    UPLOAD_FOLDER = 'temp'
    DUCKDB_DIR = 'temp/db'
    ALLOWED_EXTENSIONS = {'xlsx', 'csv', 'xls'}

    # ── Dify Workflow AI 代理配置（支持 enc: 加密 / 明文兼容） ──
    # 所有 AI 调用（SQL 生成、字段映射、报表识别等）通过 Dify Workflow 代理。
    # Dify 端配置了模型 Qwen3-235B-A3B（temperature=0.7, max_tokens=4096）。
    #
    # API Key 建议加密存放：运行 python tools/encrypt_env.py 把明文转为 enc: 密文。
    # SECRET_KEY 请通过系统环境变量或 secret_key 文件注入，不要写在 .env 里（避免与密文同源）。
    #
    # 主要 Dify Workflow — 用于 SQL 生成、字段映射、报表清洗、AI 差异分析等
    DIFY_MAIN_BASE_URL = os.environ.get('DIFY_MAIN_BASE_URL', 'https://ai-platform-uat.ey.net/v1')
    DIFY_MAIN_API_KEY = _resolve_dify_key(
        os.environ.get('DIFY_MAIN_API_KEY') or _bundle_data.get('DIFY_MAIN_API_KEY', '')
        or 'your-dify-main-api-key-here',
        'DIFY_MAIN_API_KEY')
    # 复核 Dify Workflow — 用于 SQL 代码复核审查
    DIFY_REVIEW_BASE_URL = os.environ.get('DIFY_REVIEW_BASE_URL', 'https://ai-platform-uat.ey.net/v1')
    DIFY_REVIEW_API_KEY = _resolve_dify_key(
        os.environ.get('DIFY_REVIEW_API_KEY') or _bundle_data.get('DIFY_REVIEW_API_KEY', '')
        or 'your-dify-review-api-key-here',
        'DIFY_REVIEW_API_KEY')

    # 数据预览配置
    PREVIEW_ROWS = 10
    MAX_ROWS_PREVIEW = 10000
