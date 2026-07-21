"""encryption.py 단위 테스트 — Fernet 암호화/복호화 검증.

_get_fernet()는 get_settings().ENCRYPTION_KEY 기반이므로 patch로 제어.
encrypt_value/decrypt_value는 순수 함수 경로 + Fernet 없을 때 폴백 검증.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock
from cryptography.fernet import Fernet

from backend.app.core.encryption import (
    _get_fernet,
    encrypt_value,
    decrypt_value,
)


# ── _get_fernet ──────────────────────────────────────────────────────────────

class TestGetFernet:
    def test_empty_key_returns_none(self):
        with patch("backend.app.core.encryption.get_settings") as mock:
            mock.return_value.ENCRYPTION_KEY = ""
            assert _get_fernet() is None

    def test_short_key_returns_none(self):
        with patch("backend.app.core.encryption.get_settings") as mock:
            mock.return_value.ENCRYPTION_KEY = "short"
            assert _get_fernet() is None

    def test_whitespace_only_key_returns_none(self):
        with patch("backend.app.core.encryption.get_settings") as mock:
            mock.return_value.ENCRYPTION_KEY = "   "
            assert _get_fernet() is None

    def test_valid_fernet_key_44chars(self):
        key = Fernet.generate_key().decode()
        assert len(key) == 44 and key.endswith("=")
        with patch("backend.app.core.encryption.get_settings") as mock:
            mock.return_value.ENCRYPTION_KEY = key
            f = _get_fernet()
            assert f is not None
            assert isinstance(f, Fernet)

    def test_long_key_derives_fernet_via_pbkdf2(self):
        key = "a" * 64
        with patch("backend.app.core.encryption.get_settings") as mock:
            mock.return_value.ENCRYPTION_KEY = key
            f = _get_fernet()
            assert f is not None
            assert isinstance(f, Fernet)

    def test_key_exactly_32_chars_derives_fernet(self):
        key = "a" * 32
        with patch("backend.app.core.encryption.get_settings") as mock:
            mock.return_value.ENCRYPTION_KEY = key
            f = _get_fernet()
            assert f is not None


# ── encrypt_value ─────────────────────────────────────────────────────────────

class TestEncryptValue:
    def test_empty_string_returns_none(self):
        assert encrypt_value("") is None

    def test_whitespace_only_returns_none(self):
        assert encrypt_value("   ") is None

    def test_no_fernet_returns_plain(self):
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            assert encrypt_value("secret123") == "secret123"

    def test_encrypt_returns_ciphertext(self):
        key = Fernet.generate_key()
        f = Fernet(key)
        with patch("backend.app.core.encryption._get_fernet", return_value=f):
            cipher = encrypt_value("my_secret")
        assert cipher is not None
        assert cipher != "my_secret"
        # 복호화로 원문 확인
        assert f.decrypt(cipher.encode()).decode() == "my_secret"

    def test_encrypt_exception_returns_plain(self):
        bad_fernet = MagicMock()
        bad_fernet.encrypt.side_effect = Exception("boom")
        with patch("backend.app.core.encryption._get_fernet", return_value=bad_fernet):
            assert encrypt_value("data") == "data"


# ── decrypt_value ─────────────────────────────────────────────────────────────

class TestDecryptValue:
    def test_empty_string_returns_none(self):
        assert decrypt_value("") is None

    def test_whitespace_only_returns_none(self):
        assert decrypt_value("   ") is None

    def test_no_fernet_returns_cipher(self):
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            assert decrypt_value("ciphertext") == "ciphertext"

    def test_decrypt_returns_plaintext(self):
        key = Fernet.generate_key()
        f = Fernet(key)
        cipher = f.encrypt(b"plaintext_data").decode()
        with patch("backend.app.core.encryption._get_fernet", return_value=f):
            assert decrypt_value(cipher) == "plaintext_data"

    def test_invalid_token_returns_cipher(self):
        key = Fernet.generate_key()
        f = Fernet(key)
        # 다른 키로 암호화한 ciphertext
        other_key = Fernet.generate_key()
        other_f = Fernet(other_key)
        bad_cipher = other_f.encrypt(b"wrong").decode()
        with patch("backend.app.core.encryption._get_fernet", return_value=f):
            assert decrypt_value(bad_cipher) == bad_cipher

    def test_decrypt_exception_returns_none(self):
        bad_fernet = MagicMock()
        bad_fernet.decrypt.side_effect = Exception("boom")
        with patch("backend.app.core.encryption._get_fernet", return_value=bad_fernet):
            assert decrypt_value("garbage") is None


# ── encrypt_decrypt roundtrip ──────────────────────────────────────────────────

class TestEncryptDecryptRoundtrip:
    def test_roundtrip_with_real_fernet(self):
        key = Fernet.generate_key()
        f = Fernet(key)
        with patch("backend.app.core.encryption._get_fernet", return_value=f):
            cipher = encrypt_value("roundtrip_value")
            assert cipher is not None
            assert decrypt_value(cipher) == "roundtrip_value"

    def test_roundtrip_korean_text(self):
        key = Fernet.generate_key()
        f = Fernet(key)
        with patch("backend.app.core.encryption._get_fernet", return_value=f):
            cipher = encrypt_value("한글비밀키123")
            assert decrypt_value(cipher) == "한글비밀키123"
