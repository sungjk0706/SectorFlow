"""settings_store.py 단위 테스트 — 설정 저장/동기화 (순수 함수 + async)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from backend.app.core.encryption import DecryptResult, EncryptionError, SecretValueState
from backend.app.core.settings_store import (
    normalize_stk_cd_key,
    normalize_symbol_override_map,
    apply_settings_updates,
    build_masked_settings_dict,
    _validate_timetable_order,
    _validate_numeric_fields,
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


# ── _validate_timetable_order (async) ───────────────────────────────

class TestValidateTimetableOrder:
    """타임테이블 시간 순서 검증 (P20/P22) — 2그룹 분리.

    그룹1 (개장 전): nxt_start < krx_start
    그룹2 (장마감 후): krx_end < nxt_end < confirmed_download
    """

    @pytest.mark.asyncio
    async def test_valid_order(self):
        # 07:58 < 08:59 → 통과
        data = {
            "timetable.nxt_start": "07:58",
            "timetable.krx_start": "08:59",
        }
        await _validate_timetable_order(data, before={})  # 예외 없음

    @pytest.mark.asyncio
    async def test_reverse_order(self):
        # 08:59, 07:58 → ValueError (nxt_start < krx_start 위반)
        data = {
            "timetable.nxt_start": "08:59",
            "timetable.krx_start": "07:58",
        }
        with pytest.raises(ValueError, match="타임테이블 시간 순서 오류"):
            await _validate_timetable_order(data, before={})

    @pytest.mark.asyncio
    async def test_equal_values(self):
        # 07:58 = 07:58 → ValueError (< 엄격, 동일 불가)
        data = {
            "timetable.nxt_start": "07:58",
            "timetable.krx_start": "07:58",
        }
        with pytest.raises(ValueError, match="타임테이블 시간 순서 오류"):
            await _validate_timetable_order(data, before={})

    @pytest.mark.asyncio
    async def test_missing_in_data_uses_before(self):
        # data에 1개만, before에 나머지 1개 → 통과
        data = {"timetable.nxt_start": "07:58"}
        before = {
            "timetable.krx_start": "08:59",
        }
        await _validate_timetable_order(data, before)

    @pytest.mark.asyncio
    async def test_missing_in_data_uses_default(self):
        # data에 1개만, before도 비어 있음 → DEFAULT_USER_SETTINGS 기본값 사용 → 통과
        data = {"timetable.nxt_start": "07:58"}
        await _validate_timetable_order(data, before={})

    @pytest.mark.asyncio
    async def test_no_timetable_keys_skipped(self):
        # data에 일반 키만 → 검증 생략 (통과)
        data = {"broker": "kiwoom", "buy_time_start": "09:00"}
        await _validate_timetable_order(data, before={})

    # ── 그룹2: 장마감 후 (krx_end < nxt_end < confirmed_download) ──

    @pytest.mark.asyncio
    async def test_post_close_valid(self):
        # 15:20 < 20:00 < 20:40 → 통과
        data = {
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "20:40",
        }
        await _validate_timetable_order(data, before={})  # 예외 없음

    @pytest.mark.asyncio
    async def test_post_close_nxt_end_equal_confirmed_raises(self):
        # 15:20 < 20:00 = 20:00 → ValueError (nxt_end < confirmed_download 엄격)
        data = {
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "20:00",
        }
        with pytest.raises(ValueError, match="타임테이블 시간 순서 오류"):
            await _validate_timetable_order(data, before={})

    @pytest.mark.asyncio
    async def test_post_close_krx_end_equal_nxt_end_raises(self):
        # 20:00 = 20:00 < 20:40 → ValueError (krx_end < nxt_end 엄격)
        data = {
            "timetable.krx_end": "20:00",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "20:40",
        }
        with pytest.raises(ValueError, match="타임테이블 시간 순서 오류"):
            await _validate_timetable_order(data, before={})

    @pytest.mark.asyncio
    async def test_post_close_confirmed_before_nxt_end_raises(self):
        # 15:20 < 20:40 < 20:00 → ValueError (순서 위반)
        data = {
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:40",
            "timetable.confirmed_download": "20:00",
        }
        with pytest.raises(ValueError, match="타임테이블 시간 순서 오류"):
            await _validate_timetable_order(data, before={})

    @pytest.mark.asyncio
    async def test_post_close_late_evening_valid(self):
        # 15:20 < 20:00 < 23:50 → 통과 (상한선 없음 — 증권사 확정 데이터 준비 지연 대비)
        data = {
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "23:50",
        }
        await _validate_timetable_order(data, before={})

    @pytest.mark.asyncio
    async def test_post_close_key_not_in_data_skipped(self):
        # data에 일반 키만 → 그룹2 검증 생략 (통과)
        data = {"buy_time_start": "09:00"}
        before = {"timetable.confirmed_download": "20:40"}
        await _validate_timetable_order(data, before)

    @pytest.mark.asyncio
    async def test_both_groups_independent(self):
        # 그룹1 + 그룹2 동시에 data에 있어도 각각 독립 검증 → 통과
        data = {
            "timetable.nxt_start": "07:58",
            "timetable.krx_start": "08:59",
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "20:40",
        }
        await _validate_timetable_order(data, before={})

    @pytest.mark.asyncio
    async def test_both_groups_violation_in_group2_only(self):
        # 그룹1 통과 + 그룹2 위반 → 그룹2에서만 ValueError
        data = {
            "timetable.nxt_start": "07:58",
            "timetable.krx_start": "08:59",
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "19:00",  # < nxt_end → 위반
        }
        with pytest.raises(ValueError, match="타임테이블 시간 순서 오류"):
            await _validate_timetable_order(data, before={})


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
            with patch("backend.app.core.broker_registry.PROVIDER_REGISTRY", {"kiwoom": {}, "testbroker": {}}):
                result = await apply_settings_updates({"broker": "testbroker"})
                assert "broker" in result
                # save_selected_settings가 호출되었는지 확인
                mock_save.assert_called_once()
                saved = mock_save.call_args[0][0]
                assert saved["broker"] == "testbroker"

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
             patch("backend.app.core.settings_store._encrypt_field_or_raise", return_value="gAAAAencrypted"):
            result = await apply_settings_updates({"kiwoom_app_key": "plaintext_key"})
            assert "kiwoom_app_key" in result
            saved = mock_save.call_args[0][0]
            assert saved["kiwoom_app_key"] == "gAAAAencrypted"

    @pytest.mark.asyncio
    async def test_encrypt_field_failure_raises(self):
        """암호화 실패 시 EncryptionError 전파 — 평문 저장 차단 (P20/보안, B21-01 세션3)."""
        err = EncryptionError(code="ENCRYPTION_KEY_MISSING", message="키 없음", field="kiwoom_app_key")
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save, \
             patch("backend.app.core.settings_store._encrypt_field_or_raise", side_effect=err):
            with pytest.raises(EncryptionError) as exc_info:
                await apply_settings_updates({"kiwoom_app_key": "plaintext_key"})
            assert exc_info.value.code == "ENCRYPTION_KEY_MISSING"
            assert exc_info.value.field == "kiwoom_app_key"
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_encrypt_field_error_propagates_without_save(self):
        """EncryptionError 전파 시 save_selected_settings 호출 금지 — 평문 저장 차단 (P20/보안)."""
        err = EncryptionError(code="ENCRYPTION_FAILED", message="암호화 처리 실패", field="ls_app_secret")
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save, \
             patch("backend.app.core.settings_store._encrypt_field_or_raise", side_effect=err):
            with pytest.raises(EncryptionError, match="암호화 처리 실패"):
                await apply_settings_updates({"ls_app_secret": "plaintext_secret"})
            mock_save.assert_not_called()

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

    @pytest.mark.asyncio
    async def test_timetable_order_violation_raises(self):
        """타임테이블 순서 위반 시 ValueError → 저장 차단 (P20/P22). 그룹1 검증."""
        before = {
            "timetable.nxt_start": "07:58",
            "timetable.krx_start": "08:59",
        }
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value=before)), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="타임테이블 시간 순서 오류"):
                await apply_settings_updates({"timetable.krx_start": "07:00"})
            # 저장이 호출되지 않아야 함 (검증에서 차단)
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_timetable_post_close_violation_raises(self):
        """그룹2 위반 시 ValueError → 저장 차단 (P20/P22). confirmed_download <= nxt_end."""
        before = {
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "20:40",
        }
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value=before)), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="타임테이블 시간 순서 오류"):
                await apply_settings_updates({"timetable.confirmed_download": "20:00"})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_timetable_order_valid_saves(self):
        """정상 시각 → 저장 호출 확인. 그룹1."""
        before = {
            "timetable.nxt_start": "07:58",
            "timetable.krx_start": "08:59",
        }
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value=before)), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            result = await apply_settings_updates({"timetable.krx_start": "08:30"})
            assert "timetable.krx_start" in result
            saved = mock_save.call_args[0][0]
            assert saved["timetable.krx_start"] == "08:30"

    @pytest.mark.asyncio
    async def test_timetable_post_close_valid_saves(self):
        """그룹2 정상 시각(krx_end < nxt_end < confirmed_download) → 저장 호출 확인."""
        before = {
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "20:40",
        }
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value=before)), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            result = await apply_settings_updates({"timetable.confirmed_download": "21:00"})
            assert "timetable.confirmed_download" in result
            saved = mock_save.call_args[0][0]
            assert saved["timetable.confirmed_download"] == "21:00"

    @pytest.mark.asyncio
    async def test_timetable_select_keys_includes_all_pre_open(self):
        """타임테이블 키 1개만 변경해도 그룹1 전체가 load_selected_settings에 전달 (순서 검증용)."""
        before = {
            "timetable.nxt_start": "07:58",
            "timetable.krx_start": "08:59",
            "broker": "kiwoom",
        }
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value=before)) as mock_load, \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()):
            await apply_settings_updates({"timetable.nxt_start": "07:50"})
            # load_selected_settings에 전달된 키 집합에 그룹1 전체 포함 확인
            called_keys = mock_load.call_args[0][0]
            assert "timetable.nxt_start" in called_keys
            assert "timetable.krx_start" in called_keys

    @pytest.mark.asyncio
    async def test_timetable_select_keys_includes_post_close(self):
        """그룹2 키 변경 시에도 해당 그룹 전체가 load_selected_settings에 전달됨 (순서 검증용)."""
        before = {
            "timetable.krx_end": "15:20",
            "timetable.nxt_end": "20:00",
            "timetable.confirmed_download": "20:40",
            "broker": "kiwoom",
        }
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value=before)) as mock_load, \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()):
            await apply_settings_updates({"timetable.confirmed_download": "21:00"})
            called_keys = mock_load.call_args[0][0]
            assert "timetable.confirmed_download" in called_keys
            assert "timetable.krx_end" in called_keys
            assert "timetable.nxt_end" in called_keys


# ── subscribe.max_0b_count 범위 검증 (apply_settings_updates) ──────────────────────

class TestSubscribeMax0bCountValidation:
    """subscribe.max_0b_count 범위 검증 (신규 — 1~1000 외 값 저장 차단)."""

    @pytest.mark.asyncio
    async def test_rejects_zero(self):
        """0 값 저장 시 ValueError → 저장 차단 (P20/P22)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="구독 한도는 1~1000 사이여야 합니다"):
                await apply_settings_updates({"subscribe.max_0b_count": 0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_over_1000(self):
        """1001 값 저장 시 ValueError → 저장 차단 (P20/P22)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="구독 한도는 1~1000 사이여야 합니다"):
                await apply_settings_updates({"subscribe.max_0b_count": 1001})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_integer(self):
        """정수가 아닌 값 저장 시 ValueError → 저장 차단 (P20/P22)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="구독 한도는 정수여야 합니다"):
                await apply_settings_updates({"subscribe.max_0b_count": "abc"})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_valid_range(self):
        """1~1000 범위 내 값 저장 성공 (경계값 1과 1000 포함)."""
        for valid_val in (1, 500, 1000):
            with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
                 patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
                result = await apply_settings_updates({"subscribe.max_0b_count": valid_val})
                assert "subscribe.max_0b_count" in result
                saved = mock_save.call_args[0][0]
                assert saved["subscribe.max_0b_count"] == valid_val


# ── 리스크 매니저 설정 범위 검증 (apply_settings_updates) ──────────────────────

class TestRiskManagerSettingsValidation:
    """리스크 매니저 신규 키 범위/부호 검증 (P20/P22 — 범위 위반 시 422 차단)."""

    @pytest.mark.asyncio
    async def test_rejects_positive_daily_loss_limit(self):
        """daily_loss_limit 양수 입력 시 ValueError (음수만 허용)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="daily_loss_limit는 -1000000000~0 사이여야 합니다"):
                await apply_settings_updates({"daily_loss_limit": 100000})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_zero_consecutive_loss_limit(self):
        """consecutive_loss_limit 0 입력 시 ValueError (1~100만 허용)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="consecutive_loss_limit는 1~100 사이여야 합니다"):
                await apply_settings_updates({"consecutive_loss_limit": 0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_positive_daily_loss_rate_limit(self):
        """daily_loss_rate_limit 양수 입력 시 ValueError (음수만 허용)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="daily_loss_rate_limit는 -100.0~0.0 사이여야 합니다"):
                await apply_settings_updates({"daily_loss_rate_limit": 5.0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_integer_daily_loss_limit(self):
        """daily_loss_limit 정수가 아닌 값 입력 시 ValueError."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="daily_loss_limit는 정수여야 합니다"):
                await apply_settings_updates({"daily_loss_limit": "abc"})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_float_daily_loss_rate_limit(self):
        """daily_loss_rate_limit 숫자가 아닌 값 입력 시 ValueError."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="daily_loss_rate_limit는 숫자여야 합니다"):
                await apply_settings_updates({"daily_loss_rate_limit": "abc"})
            mock_save.assert_not_called()

    # ── 후안 B 부호 규칙 — 하락/손실 음수 키 검증 (loss_val/ts_drop_val/buy_block_fall_pct) ──

    @pytest.mark.asyncio
    async def test_rejects_positive_loss_val(self):
        """loss_val 양수 입력 시 ValueError (음수만 허용 — 후안 B 부호 규칙)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="loss_val는 -100.0~0.0 사이여야 합니다"):
                await apply_settings_updates({"loss_val": 5.0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_float_loss_val(self):
        """loss_val 숫자가 아닌 값 입력 시 ValueError."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="loss_val는 숫자여야 합니다"):
                await apply_settings_updates({"loss_val": "abc"})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_positive_ts_drop_val(self):
        """ts_drop_val 양수 입력 시 ValueError (음수만 허용 — 후안 B 부호 규칙)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="ts_drop_val는 -100.0~0.0 사이여야 합니다"):
                await apply_settings_updates({"ts_drop_val": 2.0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_float_ts_drop_val(self):
        """ts_drop_val 숫자가 아닌 값 입력 시 ValueError."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="ts_drop_val는 숫자여야 합니다"):
                await apply_settings_updates({"ts_drop_val": "abc"})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_positive_buy_block_fall_pct(self):
        """buy_block_fall_pct 양수 입력 시 ValueError (음수만 허용 — 후안 B 부호 규칙)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="buy_block_fall_pct는 -100.0~0.0 사이여야 합니다"):
                await apply_settings_updates({"buy_block_fall_pct": 7.0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_float_buy_block_fall_pct(self):
        """buy_block_fall_pct 숫자가 아닌 값 입력 시 ValueError."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="buy_block_fall_pct는 숫자여야 합니다"):
                await apply_settings_updates({"buy_block_fall_pct": "abc"})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_valid_risk_values(self):
        """유효한 경계값 저장 성공 (P20 — 0/음수 유효값 허용)."""
        valid_cases = [
            ("daily_loss_limit", 0),               # 상한 경계 (0 포함)
            ("daily_loss_limit", -1_000_000_000),  # 하한 경계
            ("consecutive_loss_limit", 1),         # 하한 경계
            ("consecutive_loss_limit", 100),       # 상한 경계
            ("daily_loss_rate_limit", 0.0),        # 상한 경계
            ("daily_loss_rate_limit", -100.0),     # 하한 경계
            # 후안 B 부호 규칙 — 하락/손실 음수 키 경계값
            ("loss_val", 0.0),                     # 상한 경계 (0 포함 — 손절 미설정)
            ("loss_val", -100.0),                  # 하한 경계
            ("ts_drop_val", 0.0),                  # 상한 경계 (0 포함 — T/S 미설정)
            ("ts_drop_val", -100.0),               # 하한 경계
            ("buy_block_fall_pct", 0.0),           # 상한 경계 (0 포함 — 차단 미설정)
            ("buy_block_fall_pct", -100.0),        # 하한 경계
        ]
        for k, v in valid_cases:
            with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
                 patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
                result = await apply_settings_updates({k: v})
                assert k in result
                saved = mock_save.call_args[0][0]
                assert saved[k] == v


# ── 매매·가상잔고 설정 범위 검증 (COUPLING-S2 잔여 — P20/P22) ──

class TestTradeAndVirtualBalanceValidation:
    """매매·가상잔고 키 범위 검증 (P20/P22 — 범위 위반 시 422 차단).
    후안 B 부호 규칙 — 상승/익절은 양수 (P23 일관성)."""

    @pytest.mark.asyncio
    async def test_rejects_negative_buy_block_rise_pct(self):
        """buy_block_rise_pct 음수 입력 시 ValueError (양수만 허용 — 후안 B 부호 규칙)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="buy_block_rise_pct는 0.0~100.0 사이여야 합니다"):
                await apply_settings_updates({"buy_block_rise_pct": -7.0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_negative_tp_val(self):
        """tp_val 음수 입력 시 ValueError (양수만 허용 — 0=비활성)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="tp_val는 0.0~100.0 사이여야 합니다"):
                await apply_settings_updates({"tp_val": -5.0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_negative_ts_start_val(self):
        """ts_start_val 음수 입력 시 ValueError (양수만 허용 — 0=비활성)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="ts_start_val는 0.0~100.0 사이여야 합니다"):
                await apply_settings_updates({"ts_start_val": -3.0})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_negative_sell_offset(self):
        """sell_offset 음수 입력 시 ValueError (0 이상만 허용)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="sell_offset는 0~100000 사이여야 합니다"):
                await apply_settings_updates({"sell_offset": -1})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_negative_sell_custom_qty(self):
        """sell_custom_qty 음수 입력 시 ValueError (0 이상만 허용)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="sell_custom_qty는 0~10000000 사이여야 합니다"):
                await apply_settings_updates({"sell_custom_qty": -10})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_negative_max_daily_total_buy_amt(self):
        """max_daily_total_buy_amt 음수 입력 시 ValueError (0 이상만 허용)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="max_daily_total_buy_amt는 0~1000000000000 사이여야 합니다"):
                await apply_settings_updates({"max_daily_total_buy_amt": -1000})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_negative_test_virtual_deposit(self):
        """test_virtual_deposit 음수 입력 시 ValueError (0 이상만 허용)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="test_virtual_deposit는 0~1000000000000 사이여야 합니다"):
                await apply_settings_updates({"test_virtual_deposit": -1})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_negative_test_virtual_balance(self):
        """test_virtual_balance 음수 입력 시 ValueError (0 이상만 허용)."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="test_virtual_balance는 0~1000000000000 사이여야 합니다"):
                await apply_settings_updates({"test_virtual_balance": -1})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_float_buy_block_rise_pct(self):
        """buy_block_rise_pct 숫자가 아닌 값 입력 시 ValueError."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="buy_block_rise_pct는 숫자여야 합니다"):
                await apply_settings_updates({"buy_block_rise_pct": "abc"})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_rejects_non_int_sell_offset(self):
        """sell_offset 정수가 아닌 값 입력 시 ValueError."""
        with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
            with pytest.raises(ValueError, match="sell_offset는 정수여야 합니다"):
                await apply_settings_updates({"sell_offset": "abc"})
            mock_save.assert_not_called()

    @pytest.mark.asyncio
    async def test_accepts_valid_trade_and_virtual_balance_values(self):
        """유효한 경계값 저장 성공 (P20 — 0/양수 유효값 허용)."""
        valid_cases = [
            ("buy_block_rise_pct", 0.0),           # 하한 경계 (0 포함 — 차단 미설정)
            ("buy_block_rise_pct", 100.0),         # 상한 경계
            ("tp_val", 0.0),                       # 하한 경계 (0 포함 — 익절 미설정)
            ("tp_val", 100.0),                     # 상한 경계
            ("ts_start_val", 0.0),                 # 하한 경계 (0 포함 — T/S 미설정)
            ("ts_start_val", 100.0),               # 상한 경계
            ("sell_offset", 0),                    # 하한 경계 (0=비활성)
            ("sell_offset", 100_000),              # 상한 경계
            ("sell_custom_qty", 0),                # 하한 경계 (0=비활성)
            ("sell_custom_qty", 10_000_000),       # 상한 경계
            ("max_daily_total_buy_amt", 0),        # 하한 경계 (0=비활성)
            ("max_daily_total_buy_amt", 1_000_000_000_000),  # 상한 경계
            ("test_virtual_deposit", 0),           # 하한 경계
            ("test_virtual_deposit", 1_000_000_000_000),     # 상한 경계
            ("test_virtual_balance", 0),           # 하한 경계
            ("test_virtual_balance", 1_000_000_000_000),     # 상한 경계
        ]
        for k, v in valid_cases:
            with patch("backend.app.core.settings_store.load_selected_settings", new=AsyncMock(return_value={})), \
                 patch("backend.app.core.settings_store.save_selected_settings", new=AsyncMock()) as mock_save:
                result = await apply_settings_updates({k: v})
                assert k in result
                saved = mock_save.call_args[0][0]
                assert saved[k] == v


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

    @pytest.mark.asyncio
    async def test_encryption_key_state_included(self):
        """B21-01 세션7: encryption_key_state 포함 (UI 상태 배너 — 설계 7.1)."""
        from backend.app.core.encryption import KeyState
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value={})), \
             patch("backend.app.core.settings_store.auto_trading_effective", return_value=False), \
             patch("backend.app.core.encryption.get_key_state", return_value=KeyState.AVAILABLE):
            result = await build_masked_settings_dict()
            assert result["encryption_key_state"] == "AVAILABLE"

    @pytest.mark.asyncio
    async def test_secret_field_states_included(self):
        """B21-01 세션7: secret_field_states 포함 (UI 필드별 상태 — 설계 7.2)."""
        flat = {"kiwoom_app_key": "gAAAAencrypted", "kiwoom_app_secret": "plaintext_legacy"}
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value=flat)), \
             patch("backend.app.core.settings_store.auto_trading_effective", return_value=False), \
             patch(
                 "backend.app.core.encryption.decrypt_secret",
                 return_value=DecryptResult(state=SecretValueState.ENCRYPTED, plaintext="secret"),
             ):
            result = await build_masked_settings_dict()
            states = result["secret_field_states"]
            assert states["kiwoom_app_key"] == "ENCRYPTED"
            assert states["kiwoom_app_secret"] == "PLAINTEXT_LEGACY"

    @pytest.mark.asyncio
    async def test_secret_field_states_classified_before_masking(self):
        """B21-01 세션7: 상태 분류는 마스킹 전 원본 값 기준 (P22 — 마스킹 후 ***는 분류 불가)."""
        flat = {"kiwoom_app_key": "gAAAAencrypted"}
        with patch("backend.app.core.settings_store.load_integrated_system_settings", new=AsyncMock(return_value=flat)), \
             patch("backend.app.core.settings_store.auto_trading_effective", return_value=False), \
             patch(
                 "backend.app.core.encryption.decrypt_secret",
                 return_value=DecryptResult(state=SecretValueState.ENCRYPTED, plaintext="secret"),
             ) as mock_decrypt:
            result = await build_masked_settings_dict()
            # 마스킹 전 원본 gAAAA 값으로 분류 호출됨 (*** 가 아닌 gAAAAencrypted)
            mock_decrypt.assert_called_once_with("gAAAAencrypted")
            assert result["kiwoom_app_key"] == "***"
            assert result["secret_field_states"]["kiwoom_app_key"] == "ENCRYPTED"


# ── _validate_numeric_fields: daily_summary_days 범위 검증 (FIX-WS-04 6세션) ──

class TestValidateDailySummaryDays:
    """daily_summary_days 범위 검증 (0=전체, 1~365=최근 N거래일). P20/P22."""

    def test_zero_allowed(self):
        """0 = 전체 허용."""
        _validate_numeric_fields({"daily_summary_days": 0})  # 예외 없음

    def test_max_365_allowed(self):
        _validate_numeric_fields({"daily_summary_days": 365})  # 예외 없음

    def test_typical_20_allowed(self):
        _validate_numeric_fields({"daily_summary_days": 20})  # 예외 없음

    def test_negative_rejected(self):
        with pytest.raises(ValueError, match="0~365"):
            _validate_numeric_fields({"daily_summary_days": -1})

    def test_over_365_rejected(self):
        with pytest.raises(ValueError, match="0~365"):
            _validate_numeric_fields({"daily_summary_days": 366})

    def test_non_integer_rejected(self):
        with pytest.raises(ValueError, match="정수"):
            _validate_numeric_fields({"daily_summary_days": "abc"})

    def test_none_rejected(self):
        with pytest.raises(ValueError, match="정수"):
            _validate_numeric_fields({"daily_summary_days": None})

    def test_key_absent_skips_validation(self):
        """키가 없으면 검증 스킵 (다른 필드만 있어도 OK)."""
        _validate_numeric_fields({"other_field": 100})  # 예외 없음
