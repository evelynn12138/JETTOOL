#!/usr/bin/env python3
"""把 .env 中的 Dify API Key 加密为 enc: 密文，并生成/复用 SECRET_KEY。

用法:
  python tools/encrypt_env.py                      # 交互式：读 .env，加密，生成密钥
  python tools/encrypt_env.py --env-file .env      # 指定环境文件
  python tools/encrypt_env.py --secret <KEY>       # 复用指定密钥（保证前后一致）
  python tools/encrypt_env.py --print-secret       # 只打印当前生效的 SECRET_KEY
  python tools/encrypt_env.py --dry-run            # 只展示改动，不写入
  python tools/encrypt_env.py --reencrypt --secret <新密钥>  # 用新密钥重加密（密钥轮换）

幂等保证:
  - 已是 enc: 的值跳过，绝不二次加密
  - 密钥优先级: --secret > 系统环境变量 SECRET_KEY > 本地 secret_key 文件 > 新生成
  - 已存在密文但找不到原密钥 → 拒绝执行，避免新旧密钥混用导致无法解密
"""
import argparse
import os
import secrets
import sys
from pathlib import Path

# 允许从 tools/ 目录运行：把项目根目录加入 sys.path，以便 import modules.*
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.crypto_utils import encrypt as _enc, decrypt as _dec

TARGET_KEYS = ['DIFY_MAIN_API_KEY', 'DIFY_REVIEW_API_KEY']


def read_lines(path):
    return Path(path).read_text(encoding='utf-8').splitlines()


def find_key(lines, name):
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith('#') and '=' in s:
            k, _, v = s.partition('=')
            if k.strip() == name:
                return v.strip().strip('"').strip("'")
    return None


def set_key(lines, name, value):
    out, found = [], False
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith('#') and '=' in s:
            k, _, _ = s.partition('=')
            if k.strip() == name:
                out.append(f'{name}={value}')  # Fernet 密文无空格/特殊字符，免引号
                found = True
                continue
        out.append(ln)
    if not found:
        out.append(f'{name}={value}')
    return out


def remove_key(lines, name):
    return [ln for ln in lines
            if not (ln.strip() and not ln.strip().startswith('#') and '=' in ln
                    and ln.strip().partition('=')[0].strip() == name)]


def resolve_secret(args, env_path):
    if args.secret:
        return args.secret, 'arg'
    if os.environ.get('SECRET_KEY'):
        return os.environ['SECRET_KEY'], 'env'
    f = env_path.parent / 'secret_key'
    if f.exists():
        val = f.read_text(encoding='utf-8').strip()
        if val:
            return val, 'file'
    return secrets.token_urlsafe(32), 'generated'


def main():
    ap = argparse.ArgumentParser(description='加密 .env 中的 Dify API Key')
    ap.add_argument('--env-file', default='.env')
    ap.add_argument('--secret', help='复用指定 SECRET_KEY')
    ap.add_argument('--print-secret', action='store_true', help='只打印当前生效的 SECRET_KEY')
    ap.add_argument('--dry-run', action='store_true', help='只展示改动，不写入')
    ap.add_argument('--reencrypt', action='store_true', help='用新密钥重加密已有密文（密钥轮换）')
    args = ap.parse_args()

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f'[错误] 未找到 {env_path}，请先复制 .env.example 为 .env', file=sys.stderr)
        sys.exit(1)

    lines = read_lines(env_path)

    # 存在密文时，校验/复用原密钥，防止混合密钥
    enc_vals = [v for k in TARGET_KEYS if (v := find_key(lines, k)) and v.startswith('enc:')]
    if enc_vals:
        if not args.reencrypt:
            # 复用模式：校验原密钥能解开已有密文
            secret, source = resolve_secret(args, env_path)
            if source == 'generated':
                print('[错误] .env 已存在加密 Key，但未找到原 SECRET_KEY。'
                      '请用 --secret 传入原密钥（或 --reencrypt 换新密钥）。', file=sys.stderr)
                sys.exit(1)
            for v in enc_vals[:1]:  # 抽样试解密，验证密钥匹配
                try:
                    _dec(v[4:], secret)
                except Exception:
                    print('[错误] --secret 无法解密已有密文，密钥不匹配。', file=sys.stderr)
                    sys.exit(1)
        else:
            # 轮换模式：需要新密钥 + 能找到旧密钥解开旧密文
            if not args.secret:
                print('[错误] --reencrypt 需要 --secret <新密钥>。', file=sys.stderr)
                sys.exit(1)
            old_secret, old_source = resolve_secret(args, env_path)
            if old_source == 'generated':
                # 旧密钥缺失：无法解开旧密文，无法轮换
                print('[错误] --reencrypt 但找不到原密钥（secret_key 文件/环境变量），无法解开旧密文。',
                      file=sys.stderr)
                sys.exit(1)
            # 用旧密钥解密 → 用新密钥重加密
            plain_vals = []
            for v in enc_vals:
                try:
                    plain_vals.append(_dec(v[4:], old_secret))
                except Exception:
                    print('[错误] 旧密钥无法解密已有密文，轮换终止。', file=sys.stderr)
                    sys.exit(1)
            for k, v in zip([x for x in TARGET_KEYS if find_key(lines, x) and find_key(lines, x).startswith('enc:')],
                            plain_vals):
                lines = set_key(lines, k, 'enc:' + _enc(v, args.secret))
            print(f'[完成] 已用新密钥重加密 {len(plain_vals)} 个 Key。')

    secret, source = resolve_secret(args, env_path)
    changed = 0
    for k in TARGET_KEYS:
        v = find_key(lines, k)
        if v and not v.startswith('enc:'):
            lines = set_key(lines, k, 'enc:' + _enc(v, secret))
            changed += 1
    lines = remove_key(lines, 'SECRET_KEY')  # 密钥不得与密文同存
    # 同时清理含 SECRET_KEY 的注释行（避免误导用户以为还要写 .env）
    lines = [ln for ln in lines if 'SECRET_KEY' not in ln.upper().replace(' ', '')]

    if args.print_secret:
        print(secret)
        return

    if args.dry_run:
        print(f'[dry-run] 将改动 {changed} 个 Key，写回 {env_path}')
        print('\n'.join(lines))
        return

    env_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    skf = env_path.parent / 'secret_key'
    skf.write_text(secret + '\n', encoding='utf-8')
    os.chmod(skf, 0o600)

    print(f'[完成] 加密 {changed} 个 Key → {env_path}')
    print(f'[密钥] 写入 {skf} (权限 600，已加入 .gitignore)')
    print('[提示] 请勿把 SECRET_KEY 写进 .env。注入方式任选其一：')
    print(f'        export SECRET_KEY="{secret}"    # 当前会话')
    print(f'        或：在 start.sh / start.command 中自动读取 {skf}')


if __name__ == '__main__':
    main()
