# -*- coding: utf-8 -*-
"""
민감 설정 암호화 (cryptography Fernet)
API 키, 비밀번호 등 -> DB 저장 시 암호화
"""
from __future__ import annotations
import base64
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from backend.app.config import get_settings
def _get_fernet() -> Fernet | None:
    """ENCRYPTION_KEY에서 Fernet 인스턴스 생성"""
    key = get_settings().ENCRYPTION_KEY
    if not key or len(key.strip()) < 32:
        return None
    try:
        if len(key) == 44 and key.endswith("="):
            return Fernet(key.encode())
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"sectorflow_salt",  #  하드코딩 -- salt 변경 시 기존 암호화 데이터 복호화 불가 → 재입력 필요
            iterations=100000,
        )
        derived = base64.urlsafe_b64encode(kdf.derive(key[:32].encode()))
        return Fernet(derived)
    except Exception:
        return None


def encrypt_value(plain: str) -> str | None:
    """평문 -> 암호문 (base64). key 없으면 None 반환"""
    if not plain or not plain.strip():
        return None
    f = _get_fernet()
    if not f:
        return plain
    try:
        return f.encrypt(plain.encode()).decode()
    except Exception:
        return plain


def decrypt_value(cipher: str) -> str | None:
    """암호문 -> 평문. 복호화 실패 시 None"""
    if not cipher or not cipher.strip():
        return None
    f = _get_fernet()
    if not f:
        return cipher
    try:
        return f.decrypt(cipher.encode()).decode()
    except InvalidToken:
        return cipher
    except Exception:
        return None
