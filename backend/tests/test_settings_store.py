"""settings_store.py 단위 테스트 — 설정 저장/동기화 (순수 함수 + async)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.app.core.settings_store import (
    normalize_stk_cd_key,
    normalize_symbol_override_map,
    _account_field_or_legacy_flat,
    general_save_payload_from_flat,
    _payload_values_equal,
    changed_keys_general_save,
    apply_settings_updates,
    build_masked_settings_dict,
    load_integrated_system_settings_for_editing,
)


# ── normalize_stk_cd_key ────────────────────────────────────────────

class TestNormalizeStkCdKey:
    def test_digit_padded(self):
        assert normalize_stk_cd_key("5930") == "005930"

    def test_already_6_digits(self):
        assert normalize_stk_cd_key("005930") == "005930"

    def test_non_digit_passthrough(self):
        assert normalize_stk_cd_key("ABC") == "ABC"

    def test_strips_whitespace(self):
        assert normalize_stk_cd_key("  5930  ") == "005930"

    def test_empty(self):
        assert normalize_stk_cd_key("") == ""

    def test_int_input(self):
        assert normalize_stk_cd_key(5930) == "005930"


# ── normalize_symbol_override_map ───────────────────────────────────

class TestNormalizeSymbolOverrideMap:
    def test_normalizes_keys(self):
        v = {"5930": {"tp_val": 10.0}}
        result = normalize_symbol_override_map(v)
        assert "005930" in result
        assert result["005930"] == {"tp_val": 10.0}

    def test_skips_non_dict_values(self):
        v = {"5930": "not_a_dict", "005935": {"tp_val": 5.0}}
        result = normalize_symbol_override_map(v)
        assert "005930" not in result
        assert "005935" in result

    def test_empty(self):
        assert normalize_symbol_override_map({}) == {}


# ── _account_field_or_legacy_flat ───────────────────────────────────

class TestAccountFieldOrLegacyFlat:
    def test_key_present(self):
        d = {"kiwoom_account_no": "12345678"}
        assert _account_field_or_legacy_flat(d, "kiwoom_account_no", "fallback") == "12345678"

    def test_key_absent_returns_legacy(self):
        d = {}
        assert _account_field_or_legacy_flat(d, "kiwoom_account_no", "fallback") == "fallback"

    def test_key_none_returns_empty(self):
        d = {"kiwoom_account_no": None}
        assert _account_field_or_legacy_flat(d, "kiwoom_account_no", "fallback") == ""


# ── general_save_payload_from_flat ──────────────────────────────────

class TestGeneralSavePayloadFromFlat:
    def _full_input(self) -> dict:
        return {
            "ws_subscribe_start": "09:00",
            "ws_subscribe_end": "15:00",
            "confirmed_download_time": "20:40",
            "time_scheduler_on": True,
            "auto_buy_on": False,
            "auto_sell_on": False,
            "buy_time_start": "09:00",
            "buy_time_end": "15:20",
            "sell_time_start": "09:00",
            "sell_time_end": "15:20",
            "telegram_chat_id": "chat123",
            "tele_on": True,
            "trade_mode": "test",
            "kiwoom_account_no": "12345678",
            "broker": "kiwoom",
        }

    def test_basic_fields(self):
        result = general_save_payload_from_flat(self._full_input())
        assert result["ws_subscribe_start"] == "09:00"
        assert result["time_scheduler_on"] is True
        assert result["tele_on"] is True
        assert result["trade_mode"] == "test"
        assert result["broker"] == "kiwoom"

    def test_trade_mode_mock_maps_to_test(self):
        d = self._full_input()
        d["trade_mode"] = "mock"
        result = general_save_payload_from_flat(d)
        assert result["trade_mode"] == "test"

    def test_trade_mode_invalid_defaults_to_test(self):
        d = self._full_input()
        d["trade_mode"] = "invalid"
        result = general_save_payload_from_flat(d)
        assert result["trade_mode"] == "test"

    def test_trade_mode_real(self):
        d = self._full_input()
        d["trade_mode"] = "real"
        result = general_save_payload_from_flat(d)
        assert result["trade_mode"] == "real"

    def test_telegram_token_included_if_present(self):
        d = self._full_input()
        d["telegram_bot_token_test"] = "token_test"
        result = general_save_payload_from_flat(d)
        assert result["telegram_bot_token_test"] == "token_test"

    def test_telegram_token_excluded_if_empty(self):
        d = self._full_input()
        d["telegram_bot_token_test"] = ""
        result = general_save_payload_from_flat(d)
        assert "telegram_bot_token_test" not in result

    def test_kiwoom_app_key_included_if_present(self):
        d = self._full_input()
        d["kiwoom_app_key"] = "mykey"
        result = general_save_payload_from_flat(d)
        assert result["kiwoom_app_key"] == "mykey"

    def test_kiwoom_app_key_excluded_if_empty(self):
        d = self._full_input()
        d["kiwoom_app_key"] = ""
        result = general_save_payload_from_flat(d)
        assert "kiwoom_app_key" not in result

    def test_non_kiwoom_broker_credentials_collected(self):
        d = self._full_input()
        d["naver_app_key"] = "naver_key"
        d["naver_app_secret"] = "naver_secret"
        d["naver_account_no"] = "11111111"
        result = general_save_payload_from_flat(d)
        assert result["naver_app_key"] == "naver_key"
        assert result["naver_app_secret"] == "naver_secret"
        assert result["naver_account_no"] == "11111111"

    def test_non_kiwoom_empty_values_excluded(self):
        d = self._full_input()
        d["naver_app_key"] = ""
        result = general_save_payload_from_flat(d)
        assert "naver_app_key" not in result


# ── _payload_values_equal ───────────────────────────────────────────

class TestPayloadValuesEqual:
    def test_both_bool_true(self):
        assert _payload_values_equal(True, True) is True

    def test_both_bool_false(self):
        assert _payload_values_equal(False, False) is True

    def test_bool_mismatch(self):
        assert _payload_values_equal(True, False) is False

    def test_bool_vs_non_bool(self):
        # bool(True) == bool(1) → True == True → True
        assert _payload_values_equal(True, 1) is True

    def test_string_equal(self):
        assert _payload_values_equal("abc", "abc") is True

    def test_string_with_whitespace(self):
        assert _payload_values_equal("  abc  ", "abc") is True

    def test_none_both(self):
        assert _payload_values_equal(None, None) is True

    def test_one_none(self):
        assert _payload_values_equal(None, "abc") is False
        assert _payload_values_equal("abc", None) is False

    def test_int_equal(self):
        assert _payload_values_equal(42, 42) is True

    def test_int_vs_string(self):
        assert _payload_values_equal(42, "42") is True  # str(42).strip() == "42"


# ── changed_keys_general_save ───────────────────────────────────────

class TestChangedKeysGeneralSave:
    def test_no_changes(self):
        before = {
            "ws_subscribe_start": "09:00",
            "ws_subscribe_end": "15:00",
            "confirmed_download_time": "20:40",
            "time_scheduler_on": True,
            "auto_buy_on": False,
            "auto_sell_on": False,
            "buy_time_start": "09:00",
            "buy_time_end": "15:20",
            "sell_time_start": "09:00",
            "sell_time_end": "15:20",
            "telegram_chat_id": "",
            "tele_on": False,
            "trade_mode": "test",
            "kiwoom_account_no": "12345678",
            "broker": "kiwoom",
        }
        new_payload = general_save_payload_from_flat(before)
        changed = changed_keys_general_save(before, new_payload)
        assert changed == set()

    def test_changed_value(self):
        before = {
            "ws_subscribe_start": "09:00",
            "ws_subscribe_end": "15:00",
            "confirmed_download_time": "20:40",
            "time_scheduler_on": True,
            "auto_buy_on": False,
            "auto_sell_on": False,
            "buy_time_start": "09:00",
            "buy_time_end": "15:20",
            "sell_time_start": "09:00",
            "sell_time_end": "15:20",
            "telegram_chat_id": "",
            "tele_on": False,
            "trade_mode": "test",
            "kiwoom_account_no": "12345678",
            "broker": "kiwoom",
        }
        new_payload = general_save_payload_from_flat(before)
        new_payload["broker"] = "naver"
        changed = changed_keys_general_save(before, new_payload)
        assert "broker" in changed


# ── apply_settings_updates (async) ──────────────────────────────────

class TestApplySettingsUpdates:
    @pytest.fixture(autouse=True)
    def _mock_db(self):
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("DB not available"))
        with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
            yield

    @pytest.mark.asyncio
    async def test_none_values_skipped(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()):
            result = await apply_settings_updates({"key1": None, "key2": "val2"})
            assert "key1" not in result
            assert "key2" in result

    @pytest.mark.asyncio
    async def test_empty_string_skipped(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()):
            result = await apply_settings_updates({"key1": "", "key2": "val2"})
            assert "key1" not in result
            assert "key2" in result

    @pytest.mark.asyncio
    async def test_broker_validation_invalid(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()):
            with patch("backend.app.core.broker_registry.PROVIDER_REGISTRY", {"kiwoom": {}}):
                with pytest.raises(ValueError, match="지원하지 않는 증권사"):
                    await apply_settings_updates({"broker": "invalid_broker"})

    @pytest.mark.asyncio
    async def test_broker_validation_valid(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with patch("backend.app.core.broker_registry.PROVIDER_REGISTRY", {"kiwoom": {}, "naver": {}}):
                result = await apply_settings_updates({"broker": "naver"})
                assert "broker" in result
                # save_selected_settings가 호출되었는지 확인
                mock_save.assert_called_once()
                saved = mock_save.call_args[0][0]
                assert saved["broker"] == "naver"

    @pytest.mark.asyncio
    async def test_time_field_invalid_ignored(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            result = await apply_settings_updates({"buy_time_start": "invalid"})
            assert "buy_time_start" not in result
            # invalid time → 저장되지 않음
            saved = mock_save.call_args[0][0]
            assert "buy_time_start" not in saved

    @pytest.mark.asyncio
    async def test_time_field_valid(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            result = await apply_settings_updates({"buy_time_start": "09:30"})
            assert "buy_time_start" in result
            saved = mock_save.call_args[0][0]
            assert saved["buy_time_start"] == "09:30"

    @pytest.mark.asyncio
    async def test_encrypt_field_plain_text(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save, \
             patch("backend.app.core.settings_store.encrypt_value", return_value="gAAAAencrypted"):
            result = await apply_settings_updates({"kiwoom_app_key": "plaintext_key"})
            assert "kiwoom_app_key" in result
            saved = mock_save.call_args[0][0]
            assert saved["kiwoom_app_key"] == "gAAAAencrypted"

    @pytest.mark.asyncio
    async def test_encrypt_field_masked_skipped(self):
        """*** 마스킹된 값은 암호화하지 않고 그대로 저장."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            result = await apply_settings_updates({"kiwoom_app_key": "***"})
            assert "kiwoom_app_key" in result
            saved = mock_save.call_args[0][0]
            assert saved["kiwoom_app_key"] == "***"

    @pytest.mark.asyncio
    async def test_encrypt_field_already_encrypted(self):
        """gAAAA로 시작하는 값은 재암호화하지 않음."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            result = await apply_settings_updates({"kiwoom_app_key": "gAAAAalready_encrypted"})
            assert "kiwoom_app_key" in result
            saved = mock_save.call_args[0][0]
            assert saved["kiwoom_app_key"] == "gAAAAalready_encrypted"

    @pytest.mark.asyncio
    async def test_changed_keys_returned(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={"key1": "old"})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()), \
             patch("backend.app.core.settings_store._journal.record_settings_change", new=AsyncMock()):
            result = await apply_settings_updates({"key1": "new"})
            assert "key1" in result

    @pytest.mark.asyncio
    async def test_sell_per_symbol_normalized(self):
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            result = await apply_settings_updates({"sell_per_symbol": {"5930": {"tp_val": 10.0}}})
            assert "sell_per_symbol" in result
            saved = mock_save.call_args[0][0]
            assert "005930" in saved["sell_per_symbol"]


# ── build_masked_settings_dict (async) ──────────────────────────────

class TestBuildMaskedSettingsDict:
    @pytest.mark.asyncio
    async def test_encrypted_fields_masked(self):
        flat = {
            "kiwoom_app_key": "gAAAAencrypted",
            "kiwoom_app_secret": "gAAAAencrypted2",
            "broker": "kiwoom",
        }
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value=flat)), \
             patch("backend.app.core.settings_store.auto_trading_effective", return_value=False):
            result = await build_masked_settings_dict()
            assert result["kiwoom_app_key"] == "***"
            assert result["kiwoom_app_secret"] == "***"

    @pytest.mark.asyncio
    async def test_non_encrypted_passthrough(self):
        flat = {"broker": "kiwoom", "trade_mode": "test"}
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value=flat)), \
             patch("backend.app.core.settings_store.auto_trading_effective", return_value=False):
            result = await build_masked_settings_dict()
            assert result["broker"] == "kiwoom"
            assert result["trade_mode"] == "test"

    @pytest.mark.asyncio
    async def test_id_and_profile_set(self):
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.auto_trading_effective", return_value=False):
            result = await build_masked_settings_dict()
            assert result["id"] == "root"
            assert result["profile_name"] == "root"

    @pytest.mark.asyncio
    async def test_auto_trading_effective_included(self):
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.auto_trading_effective", return_value=False):
            result = await build_masked_settings_dict()
            assert "auto_trading_effective" in result


# ── load_integrated_system_settings_for_editing (async) ─────────────

class TestLoadIntegratedSystemSettingsForEditing:
    @pytest.mark.asyncio
    async def test_encrypted_fields_decrypted(self):
        flat = {
            "kiwoom_app_key": "gAAAAencrypted",
            "broker": "kiwoom",
        }
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value=flat)), \
             patch("backend.app.core.settings_store.decrypt_value", return_value="decrypted_key"):
            result = await load_integrated_system_settings_for_editing()
            assert result["kiwoom_app_key"] == "decrypted_key"
            assert result["broker"] == "kiwoom"

    @pytest.mark.asyncio
    async def test_non_encrypted_passthrough(self):
        flat = {"broker": "kiwoom", "trade_mode": "test"}
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value=flat)):
            result = await load_integrated_system_settings_for_editing()
            assert result["broker"] == "kiwoom"
            assert result["trade_mode"] == "test"

    @pytest.mark.asyncio
    async def test_decrypt_returns_none(self):
        flat = {"kiwoom_app_key": "gAAAAencrypted"}
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value=flat)), \
             patch("backend.app.core.settings_store.decrypt_value", return_value=None):
            result = await load_integrated_system_settings_for_editing()
            assert result["kiwoom_app_key"] == ""
