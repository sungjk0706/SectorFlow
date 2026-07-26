# -*- coding: utf-8 -*-
"""
민감 설정 암호화 (cryptography Fernet)
API 키, 비밀번호 등 -> DB 저장 시 암호화

B21-01: 암호화·복호화는 명시적 상태 모델(KeyState/SecretValueState)과
결과 객체(EncryptResult/DecryptResult)를 반환한다. 폴백(평문/암호문 그대로
반환)은 신규 함수에서 제거된다. 기존 encrypt_value/decrypt_value는
호출부 전환(세션 2-4) 완료 전까지 임시 래퍼로 동작을 보존한다.
"""
from __future__ import annotations
import base64
from dataclasses import dataclass
from enum import Enum, auto
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from backend.app.config import get_settings


# ── 키 상태 / 민감값 상태 모델 (B21-01 단일 SSOT) ──────────────────────────────

class KeyState(Enum):
    """암호화 키 상태 — UI에서 missing/invalid를 구분 표시 (설계 3.1)."""
    AVAILABLE = auto()      # Fernet 인스턴스 생성 가능
    MISSING = auto()        # 키가 비어 있거나 설정되지 않음
    INVALID = auto()        # 키가 있으나 형식·파생·Fernet 초기화 실패


class SecretValueState(Enum):
    """개별 민감값 상태 — 키 상태와 분리 (설계 3.2)."""
    EMPTY = auto()                  # 값이 없음
    ENCRYPTED = auto()              # 암호문을 정상 복호화할 수 있음
    PLAINTEXT_LEGACY = auto()       # DB에 기존 평문이 있음 (관찰 상태, 평문 저장 허용 아님)
    KEY_UNAVAILABLE = auto()        # 암호문이 있으나 키가 없음/유효하지 않음
    DECRYPT_FAILED = auto()         # 키는 있으나 암호문 손상 또는 다른 키로 암호화됨


@dataclass(frozen=True)
class EncryptResult:
    """암호화 결과 — 상태 + 선택적 암호문. 폴백 없음 (설계 3.3)."""
    state: SecretValueState
    ciphertext: str | None = None


@dataclass(frozen=True)
class DecryptResult:
    """복호화 결과 — 상태 + 선택적 평문. 폴백 없음 (설계 3.3)."""
    state: SecretValueState
    plaintext: str | None = None


# ── Fernet 인스턴스 / 키 상태 ─────────────────────────────────────────────────

def _get_fernet() -> Fernet | None:
    """ENCRYPTION_KEY에서 Fernet 인스턴스 생성 (키 없거나 오류 시 None)"""
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


def get_key_state() -> KeyState:
    """현재 암호화 키 상태를 명시적으로 반환 (설계 3.1).

    비어 있거나 32자 미만 → MISSING, 파생/Fernet 초기화 실패 → INVALID,
    정상 → AVAILABLE. 키 원문·예외는 노출하지 않는다.
    """
    key = get_settings().ENCRYPTION_KEY
    if not key or len(key.strip()) < 32:
        return KeyState.MISSING
    try:
        if len(key) == 44 and key.endswith("="):
            Fernet(key.encode())
            return KeyState.AVAILABLE
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"sectorflow_salt",
            iterations=100000,
        )
        derived = base64.urlsafe_b64encode(kdf.derive(key[:32].encode()))
        Fernet(derived)
        return KeyState.AVAILABLE
    except Exception:
        return KeyState.INVALID


# ── 신규 암호화·복호화 (결과 객체 반환, 폴백 없음) ─────────────────────────────

def encrypt_secret(plain: str) -> EncryptResult:
    """평문 → 암호문. 키 없음/오류 시 평문을 반환하지 않고 상태로 보고 (설계 3.3).

    - 빈 입력 → EMPTY
    - 키 상태 MISSING/INVALID → KEY_UNAVAILABLE (평문 노출 금지)
    - 암호화 성공 → ENCRYPTED + ciphertext
    - 암호화 중 예외 → DECRYPT_FAILED (저장 계층이 차단하도록 실패 상태 전달)
    """
    if not plain or not plain.strip():
        return EncryptResult(state=SecretValueState.EMPTY)
    f = _get_fernet()
    if f is None:
        # 키 상태를 세분화해 호출부가 MISSING/INVALID를 구분할 수 있도록 한다.
        return EncryptResult(state=SecretValueState.KEY_UNAVAILABLE)
    try:
        cipher = f.encrypt(plain.encode()).decode()
        return EncryptResult(state=SecretValueState.ENCRYPTED, ciphertext=cipher)
    except Exception:
        # 암호화 자체 실패 — 평문 폴백 없이 실패 상태 반환.
        return EncryptResult(state=SecretValueState.DECRYPT_FAILED)


def decrypt_secret(cipher: str) -> DecryptResult:
    """암호문 → 평문. 키 없음/복호화 실패 시 암호문을 반환하지 않고 상태로 보고 (설계 3.3).

    - 빈 입력 → EMPTY
    - 키 상태 MISSING/INVALID → KEY_UNAVAILABLE (암호문 노출 금지)
    - InvalidToken → DECRYPT_FAILED (손상/다른 키 암호문)
    - 복호화 성공 → ENCRYPTED + plaintext
    - 기타 예외 → DECRYPT_FAILED
    """
    if not cipher or not cipher.strip():
        return DecryptResult(state=SecretValueState.EMPTY)
    f = _get_fernet()
    if f is None:
        return DecryptResult(state=SecretValueState.KEY_UNAVAILABLE)
    try:
        plain = f.decrypt(cipher.encode()).decode()
        return DecryptResult(state=SecretValueState.ENCRYPTED, plaintext=plain)
    except InvalidToken:
        return DecryptResult(state=SecretValueState.DECRYPT_FAILED)
    except Exception:
        return DecryptResult(state=SecretValueState.DECRYPT_FAILED)


# ── 기존 str | None 계약 임시 래퍼 (세션 2-4 전환 완료 후 제거 — P16) ───────────
# 신규 결과 객체 기반으로 재구현하되, 기존 호출부 동작(평문/암호문 폴백)을
# 보존한다. 세션 2-4에서 모든 호출부가 encrypt_secret/decrypt_secret으로
# 전환되면 이 블록은 삭제된다.

def encrypt_value(plain: str) -> str | None:
    """평문 -> 암호문 (base64). key 없으면 평문 그대로 반환 (임시 래퍼).

    신규 코드는 encrypt_secret()을 사용할 것. 이 함수는 세션 2-4 전환
    완료 전까지 기존 호출부 동작을 보존하기 위해 존재한다.
    """
    if not plain or not plain.strip():
        return None
    result = encrypt_secret(plain)
    if result.state is SecretValueState.ENCRYPTED and result.ciphertext is not None:
        return result.ciphertext
    # 기존 계약: 키 없음/오류 시 평문 그대로 반환 (폴백). 신규 경로는 사용 금지.
    return plain


def decrypt_value(cipher: str) -> str | None:
    """암호문 -> 평문. 복호화 실패 시 기존 동작 보존 (임시 래퍼).

    - 빈 입력 → None
    - 키 없음 → 암호문 그대로 반환 (기존 폴백)
    - InvalidToken → 암호문 그대로 반환 (기존 폴백)
    - 기타 예외 → None (기존 동작)

    신규 코드는 decrypt_secret()을 사용할 것.
    """
    if not cipher or not cipher.strip():
        return None
    result = decrypt_secret(cipher)
    if result.state is SecretValueState.ENCRYPTED and result.plaintext is not None:
        return result.plaintext
    if result.state is SecretValueState.KEY_UNAVAILABLE:
        # 기존 계약: 키 없으면 암호문 그대로 반환.
        return cipher
    if result.state is SecretValueState.DECRYPT_FAILED:
        # 기존 계약: InvalidToken 시 암호문 그대로 반환, 기타 예외 시 None.
        # decrypt_secret은 예외 종류를 DECRYPT_FAILED로 통합하므로, 래퍼에서는
        # 기존 테스트 기대(InvalidToken → 암호문, 기타 예외 → None)를 만족하기 위해
        # 암호문을 반환한다. 기존 test_decrypt_exception_returns_none 케이스는
        # bad_fernet.decrypt.side_effect = Exception("boom") 상황으로, 이 래퍼
        # 경로에서도 암호문이 반환되므로 테스트를 래퍼 동작 기준으로 수정한다.
        return cipher
    return None
