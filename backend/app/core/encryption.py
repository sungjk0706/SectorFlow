# -*- coding: utf-8 -*-
"""
민감 설정 암호화 (cryptography Fernet)
API 키, 비밀번호 등 -> DB 저장 시 암호화

B21-01: 암호화·복호화는 명시적 상태 모델(KeyState/SecretValueState)과
결과 객체(EncryptResult/DecryptResult)를 반환한다. 폴백(평문/암호문 그대로
반환)은 제거되었다 (세션 2-4 전환 완료 후 임시 래퍼 제거 — P16).
세션 3: EncryptionError 예외 클래스 추가 — 저장 경로 실패 시 구조화된
code/message/field 를 라우터가 422 detail 객체로 변환 (설계 5).
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


# ── 구조화된 오류 (설계 5 — API detail 객체 매핑) ────────────────────────────────

class EncryptionError(Exception):
    """암호화·복호화 실패를 구조화된 코드로 전달 (설계 5).

    code/message/field 를 포함하며, 라우터가 422 detail 객체로 변환.
    평문·암호문·키 원문·traceback 은 포함하지 않는다 (설계 5 — 민감값 노출 금지).
    """

    def __init__(self, code: str, message: str, field: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


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
