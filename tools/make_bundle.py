#!/usr/bin/env python3
"""生成 dify_bundle.enc — 打包分发用，内含加密 Dify key + 内置密钥。

读本地 .env / secret_key 生成 bundle，写入项目根（已 gitignore）。
生成的 bundle 随 exe 打包注入，用户打开即用、零配置。

用法:
  python tools/make_bundle.py            # 读 .env + secret_key，生成 bundle
  python tools/make_bundle.py --env-file .env   # 指定环境文件
  python tools/make_bundle.py --dry-run         # 只展示，不写入
"""
import argparse
import json
import os
import secrets
import sys
from pathlib import Path

# 允许从 tools/ 目录运行
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.crypto_utils import encrypt as _enc, decrypt as _dec

TARGET_KEYS = ['DIFY_MAIN_API_KEY', 'DIFY_REVIEW_API_KEY']
BUNDLE_NAME = 'dify_bundle.enc'


def read_env(env_path):
    """从 .env 读指定 key 的值（支持明文或 enc: 密文）。"""
    result = {}
    if not env_path.exists():
        return result
    for ln in env_path.read_text(encoding='utf-8').splitlines():
        s = ln.strip()
        if s and not s.startswith('#') and '=' in s:
            k, _, v = s.partition('=')
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k in TARGET_KEYS and v:
                result[k] = v
    return result


def resolve_secret():
    """从 secret_key 文件读，或生成新密钥。"""
    skf = _PROJECT_ROOT / 'secret_key'
    if skf.exists():
        val = skf.read_text(encoding='utf-8').strip()
        if val:
            return val
    return secrets.token_urlsafe(32)


def main():
    ap = argparse.ArgumentParser(description='生成 dify_bundle.enc（打包分发用）')
    ap.add_argument('--env-file', default='.env')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    env_path = _PROJECT_ROOT / args.env_file
    bundle_path = _PROJECT_ROOT / BUNDLE_NAME

    if not env_path.exists():
        print(f'[错误] 未找到 {env_path}，请先配置 .env（含 Dify API Key）', file=sys.stderr)
        sys.exit(1)

    # 读取 .env 中的 key（明文或 enc: 密文都支持）
    raw_keys = read_env(env_path)
    missing = [k for k in TARGET_KEYS if k not in raw_keys or not raw_keys[k]]
    if missing:
        print(f'[警告] .env 缺少以下 key（将生成空占位）：{missing}', file=sys.stderr)

    secret = resolve_secret()

    # 加密为 bundle 格式：enc: 密文 + secret
    bundle_data = {'secret': secret}
    for k in TARGET_KEYS:
        v = raw_keys.get(k, '')
        if v.startswith('enc:'):
            # 已是密文：需先解出明文再重新加密（用本机 secret）
            try:
                plain = _dec(v[4:], secret)
            except Exception:
                print(f'[错误] {k} 已是密文但无法用本机 secret 解密，'
                      '请先运行 tools/encrypt_env.py 同步密钥。', file=sys.stderr)
                sys.exit(1)
            v = plain
        bundle_data[k] = 'enc:' + _enc(v, secret) if v else ''

    if args.dry_run:
        print(f'[dry-run] 将写入 {bundle_path}')
        print('  secret:', secret[:8] + '...')
        for k in TARGET_KEYS:
            print(f'  {k}: {bundle_data[k][:35]}...' if bundle_data[k] else f'  {k}: (空)')
        return

    bundle_path.write_text(json.dumps(bundle_data), encoding='utf-8')
    os.chmod(bundle_path, 0o600)

    print(f'[完成] bundle 已写入 {bundle_path} (权限 600, 已 gitignore)')
    print('[提示] 现在运行打包脚本即可让 exe 自带 Dify key，用户打开即用：')
    print('       Windows: build_win.bat')
    print('       Electron: electron/build.js')
    print('[安全] 本机 secret_key 与 .env 不入库，bundle 含密钥——仅限内部分发')


if __name__ == '__main__':
    main()
