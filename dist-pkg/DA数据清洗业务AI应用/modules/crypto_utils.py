"""API密钥加密工具 - 使用 Fernet 对称加密，密钥派生自 Flask SECRET_KEY"""
import base64
import hashlib
from cryptography.fernet import Fernet


def _derive_key(secret_key: str) -> bytes:
    """从 SECRET_KEY 派生出 32 字节的 Fernet 密钥"""
    raw = hashlib.sha256(secret_key.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(raw)


def encrypt(plaintext: str, secret_key: str) -> str:
    """加密明文，返回 base64 密文字符串"""
    if not plaintext:
        return ''
    f = Fernet(_derive_key(secret_key))
    return f.encrypt(plaintext.encode('utf-8')).decode('utf-8')


def decrypt(ciphertext: str, secret_key: str) -> str:
    """解密密文，返回明文字符串"""
    if not ciphertext:
        return ''
    f = Fernet(_derive_key(secret_key))
    return f.decrypt(ciphertext.encode('utf-8')).decode('utf-8')
