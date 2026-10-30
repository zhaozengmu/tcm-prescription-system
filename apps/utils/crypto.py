"""敏感字段加解密工具。

使用对称加密（Fernet），密钥通过环境变量注入。
开发环境无密钥时使用默认密钥（仅限本地实训）。
"""
import hashlib
import os

from cryptography.fernet import Fernet


def _get_key():
    key = os.environ.get("DATA_ENCRYPTION_KEY", "")
    if not key:
        # 开发环境默认密钥（仅用于模拟数据，生产必须通过环境变量注入）
        key = "u5SXsXqADtrT3SKoISj3o1-rXfdTrl2JzOUkt8LJOlc="
    if isinstance(key, str):
        key = key.encode("utf-8")
    return key


def encrypt(text):
    """加密文本，返回密文字符串。"""
    if not text:
        return ""
    f = Fernet(_get_key())
    return f.encrypt(text.encode("utf-8")).decode("utf-8")


def decrypt(token):
    """解密密文，返回明文。"""
    if not token:
        return ""
    f = Fernet(_get_key())
    return f.decrypt(token.encode("utf-8")).decode("utf-8")


def mask_id_card(id_card):
    """身份证号掩码：保留前 3 位与后 4 位。"""
    if not id_card:
        return ""
    if len(id_card) <= 7:
        return id_card[0] + "*" * (len(id_card) - 1)
    return id_card[:3] + "*" * (len(id_card) - 7) + id_card[-4:]


def mask_phone(phone):
    """手机号掩码：中间 4 位以 * 代替。"""
    if not phone:
        return ""
    if len(phone) < 7:
        return phone[0] + "*" * (len(phone) - 1)
    return phone[:3] + "****" + phone[7:]


def hash_value(value):
    """对敏感字段做哈希，用于等值查询（如身份证号查重）。"""
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
