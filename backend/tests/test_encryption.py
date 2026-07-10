"""encryption.py 단위 테스트 — Fernet 암호화/복호화, 민감 필드 일괄 처리 검증.

_get_fernet()는 get_settings().ENCRYPTION_KEY 기반이므로 patch로 제어.
encrypt_value/decrypt_value는 순수 함수 경로 + Fernet 없을 때 폴백 검증.
encrypt_sensitive/decrypt_sensitive는 SENSITIVE_KEYS 필드만 처리 확인.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from cryptography.fernet import Fernet

from backend.app.core import encryption
from backend.app.core.encryption import (
    SENSITIVE_KEYS,
    _get_fernet,
    encrypt_value,
    decrypt_value,
    encrypt_sensitive,
    decrypt_sensitive,
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


# ── SENSITIVE_KEYS ─────────────────────────────────────────────────────────────

class TestSensitiveKeys:
    def test_contains_kiwoom_keys(self):
        assert "kiwoom_app_key" in SENSITIVE_KEYS
        assert "kiwoom_app_secret" in SENSITIVE_KEYS

    def test_contains_telegram_keys(self):
        assert "telegram_bot_token_test" in SENSITIVE_KEYS
        assert "telegram_bot_token_real" in SENSITIVE_KEYS

    def test_contains_admin_password(self):
        assert "admin_password" in SENSITIVE_KEYS

    def test_is_frozen(self):
        assert isinstance(SENSITIVE_KEYS, frozenset)


# ── encrypt_sensitive ──────────────────────────────────────────────────────────

class TestEncryptSensitive:
    def test_empty_dict_returns_empty(self):
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            assert encrypt_sensitive({}) == {}

    def test_non_sensitive_fields_unchanged(self):
        data = {"broker": "kiwoom", "trade_mode": "test"}
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            result = encrypt_sensitive(data)
        assert result == data

    def test_sensitive_fields_encrypted(self):
        key = Fernet.generate_key()
        f = Fernet(key)
        data = {"kiwoom_app_key": "abc123", "broker": "kiwoom"}
        with patch("backend.app.core.encryption._get_fernet", return_value=f):
            result = encrypt_sensitive(data)
        assert result["kiwoom_app_key"] != "abc123"
        assert result["broker"] == "kiwoom"
        # 복호화로 원문 확인
        assert f.decrypt(result["kiwoom_app_key"].encode()).decode() == "abc123"

    def test_empty_sensitive_field_skipped(self):
        data = {"kiwoom_app_key": "", "broker": "kiwoom"}
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            result = encrypt_sensitive(data)
        assert result["kiwoom_app_key"] == ""

    def test_does_not_mutate_original(self):
        data = {"kiwoom_app_key": "abc123"}
        original = dict(data)
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            encrypt_sensitive(data)
        assert data == original


# ── decrypt_sensitive ──────────────────────────────────────────────────────────

class TestDecryptSensitive:
    def test_empty_dict_returns_empty(self):
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            assert decrypt_sensitive({}) == {}

    def test_non_sensitive_fields_unchanged(self):
        data = {"broker": "kiwoom", "trade_mode": "test"}
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            result = decrypt_sensitive(data)
        assert result == data

    def test_sensitive_fields_decrypted(self):
        key = Fernet.generate_key()
        f = Fernet(key)
        cipher = f.encrypt(b"secret_value").decode()
        data = {"kiwoom_app_secret": cipher, "broker": "kiwoom"}
        with patch("backend.app.core.encryption._get_fernet", return_value=f):
            result = decrypt_sensitive(data)
        assert result["kiwoom_app_secret"] == "secret_value"
        assert result["broker"] == "kiwoom"

    def test_empty_sensitive_field_skipped(self):
        data = {"kiwoom_app_key": "", "broker": "kiwoom"}
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            result = decrypt_sensitive(data)
        assert result["kiwoom_app_key"] == ""

    def test_does_not_mutate_original(self):
        data = {"kiwoom_app_key": "ciphertext"}
        original = dict(data)
        with patch("backend.app.core.encryption._get_fernet", return_value=None):
            decrypt_sensitive(data)
        assert data == original


# ── encrypt_sensitive + decrypt_sensitive roundtrip ─────────────────────────────

class TestSensitiveRoundtrip:
    def test_full_roundtrip(self):
        key = Fernet.generate_key()
        f = Fernet(key)
        original = {
            "kiwoom_app_key": "my_api_key",
            "kiwoom_app_secret": "my_secret",
            "telegram_bot_token_test": "test_token",
            "telegram_bot_token_real": "real_token",
            "admin_password": "pass123",
            "broker": "kiwoom",
            "trade_mode": "test",
        }
        with patch("backend.app.core.encryption._get_fernet", return_value=f):
            encrypted = encrypt_sensitive(original)
            decrypted = decrypt_sensitive(encrypted)
        # 민감 필드 복원
        assert decrypted["kiwoom_app_key"] == "my_api_key"
        assert decrypted["kiwoom_app_secret"] == "my_secret"
        assert decrypted["telegram_bot_token_test"] == "test_token"
        assert decrypted["telegram_bot_token_real"] == "real_token"
        assert decrypted["admin_password"] == "pass123"
        # 비민감 필드 유지
        assert decrypted["broker"] == "kiwoom"
        assert decrypted["trade_mode"] == "test"
