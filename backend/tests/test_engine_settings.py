"""engine_settings.py 단위 테스트 — 엔진 설정 빌더."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from backend.app.core.encryption import SecretValueState, DecryptResult
from backend.app.core.engine_settings import (
    get_engine_settings,
    build_engine_settings_dict,
)
from backend.app.core.trade_mode import normalize_trade_mode


# ── trade mode normalization ────────────────────────────────────────

class TestNormalizeTradeMode:
    def test_test_and_mock_map_to_test(self):
        assert normalize_trade_mode("test") == "test"
        assert normalize_trade_mode("mock") == "test"

    def test_real_is_preserved(self):
        assert normalize_trade_mode("real") == "real"

    def test_normalizes_case_and_whitespace(self):
        assert normalize_trade_mode(" REAL ") == "real"
        assert normalize_trade_mode(" MOCK ") == "test"

    def test_invalid_values_fail_closed_to_test(self):
        assert normalize_trade_mode("invalid") == "test"
        assert normalize_trade_mode(None) == "test"


# ── build_engine_settings_dict ──────────────────────────────────────

class TestBuildEngineSettingsDictDefaults:
    """DEFAULT_USER_SETTINGS 기반 기본값 검증."""

    def test_defaults_returned(self):
        result = build_engine_settings_dict({})
        assert result["broker"] == "kiwoom"
        assert result["trade_mode"] == "test"
        assert result["time_scheduler_on"] is False
        assert result["auto_buy_on"] is False
        assert result["auto_sell_on"] is False

    def test_time_fields_truncated_to_5_chars(self):
        result = build_engine_settings_dict({})
        assert len(result["buy_time_start"]) == 5
        assert len(result["buy_time_end"]) == 5
        assert len(result["sell_time_start"]) == 5
        assert len(result["sell_time_end"]) == 5

    def test_buy_amount_default(self):
        result = build_engine_settings_dict({})
        assert result["buy_amount"] == 1000000  # 안전 기본값 (P21: 신규 사용자 보호)
        assert result["buy_amount_on"] is True
        assert result["max_stock_count"] == 5
        assert result["max_stock_count_on"] is True

    def test_buy_block_toggle_defaults(self):
        result = build_engine_settings_dict({})
        assert result["buy_block_rise_on"] is True
        assert result["buy_block_fall_on"] is True
        assert result["buy_block_rise_pct"] == 7.0
        assert result["buy_block_fall_pct"] == -7.0

    def test_buy_amt_on_migration_from_zero(self):
        # 기존 buy_amt=0 → buy_amt_on=False (한도 없음)
        result = build_engine_settings_dict({"buy_amt": 0})
        assert result["buy_amt_on"] is False
        assert result["buy_amt"] == 0

    def test_buy_amt_on_migration_from_value(self):
        # 기존 buy_amt>0 → buy_amt_on=True
        result = build_engine_settings_dict({"buy_amt": 500000})
        assert result["buy_amt_on"] is True
        assert result["buy_amt"] == 500000

    def test_max_stock_cnt_on_migration_from_zero(self):
        # 기존 max_stock_cnt=0 → max_stock_cnt_on=False (제한 없음)
        result = build_engine_settings_dict({"max_stock_cnt": 0})
        assert result["max_stock_cnt_on"] is False
        assert result["max_stock_cnt"] == 0

    def test_max_stock_cnt_on_migration_from_value(self):
        result = build_engine_settings_dict({"max_stock_cnt": 10})
        assert result["max_stock_cnt_on"] is True
        assert result["max_stock_cnt"] == 10

    def test_buy_block_rise_on_migration_from_zero(self):
        result = build_engine_settings_dict({"buy_block_rise_pct": 0})
        assert result["buy_block_rise_on"] is False

    def test_buy_block_rise_on_migration_from_value(self):
        result = build_engine_settings_dict({"buy_block_rise_pct": 5.0})
        assert result["buy_block_rise_on"] is True

    def test_buy_block_fall_on_migration_from_zero(self):
        result = build_engine_settings_dict({"buy_block_fall_pct": 0})
        assert result["buy_block_fall_on"] is False

    def test_buy_block_fall_on_migration_from_value(self):
        result = build_engine_settings_dict({"buy_block_fall_pct": -7.0})
        assert result["buy_block_fall_on"] is True

    def test_risk_fields_defaults(self):
        result = build_engine_settings_dict({})
        assert result["max_single_stock_exposure"] == 20000000
        assert result["daily_loss_limit_on"] is True  # 기본 ON — 기존 항상 실행 동작 유지
        # 시장 지수 급락 가드 — KOSPI/KOSDAQ 개별 토글이 독립 제어 (그룹 마스터 없음)
        assert result["market_guard_kospi_on"] is False
        assert result["market_guard_kospi_drop_threshold_pct"] == -5.0
        assert result["market_guard_kosdaq_on"] is False
        assert result["market_guard_kosdaq_drop_threshold_pct"] == -5.0

    def test_telegram_fields_defaults(self):
        result = build_engine_settings_dict({})
        assert result["tele_on"] is False
        assert result["telegram_bot_token_test"] == ""
        assert result["telegram_bot_token_real"] == ""

    def test_kiwoom_credentials_empty(self):
        result = build_engine_settings_dict({})
        assert result["kiwoom_app_key"] == ""
        assert result["kiwoom_app_secret"] == ""
        assert result["kiwoom_account_no"] == ""

    def test_sector_settings_defaults(self):
        result = build_engine_settings_dict({})
        assert result["sector_max_targets"] == 3
        assert result["sector_min_rise_ratio_pct"] == 60.0
        assert result["sector_min_trade_amt"] == 0.0

    def test_sector_sort_keys_default(self):
        result = build_engine_settings_dict({})
        assert result["sector_sort_keys"] == ["score"]

    def test_boost_settings_defaults(self):
        result = build_engine_settings_dict({})
        assert result["boost_high_breakout_on"] is False
        assert result["boost_high_breakout_score"] == 1.0
        assert result["boost_order_ratio_on"] is False
        assert result["boost_order_ratio_pct"] == 20
        assert result["boost_order_ratio_score"] == 1.0

    def test_broker_config(self):
        result = build_engine_settings_dict({})
        assert result["broker_config"]["websocket"] == "kiwoom"
        assert result["broker_config"]["order"] == "kiwoom"
        assert result["broker_config"]["auth"] == "kiwoom"

    def test_test_virtual_deposit(self):
        result = build_engine_settings_dict({})
        assert result["test_virtual_deposit"] == 10000000

    def test_scheduler_defaults(self):
        result = build_engine_settings_dict({})
        assert result["scheduler_market_close_on"] is True


class TestBuildEngineSettingsDictOverride:
    """flat dict 오버라이드 검증."""

    def test_broker_override(self):
        result = build_engine_settings_dict({"broker": "testbroker"})
        assert result["broker"] == "testbroker"
        assert result["broker_config"]["websocket"] == "testbroker"

    def test_trade_mode_real(self):
        result = build_engine_settings_dict({"trade_mode": "real"})
        assert result["trade_mode"] == "real"

    def test_trade_mode_mock_maps_to_test(self):
        result = build_engine_settings_dict({"trade_mode": "mock"})
        assert result["trade_mode"] == "test"

    def test_buy_amount_override(self):
        result = build_engine_settings_dict({"buy_amt": 100000})
        assert result["buy_amount"] == 100000
        assert result["buy_amt"] == 100000

    def test_max_stock_count_override(self):
        result = build_engine_settings_dict({"max_stock_cnt": 10})
        assert result["max_stock_count"] == 10
        assert result["max_stock_cnt"] == 10

    def test_loss_cut(self):
        result = build_engine_settings_dict({"loss_apply": True, "loss_val": -5.0})
        assert result["loss_cut_apply"] is True
        assert result["loss_cut_value"] == -5.0
        assert result["loss_apply"] is True
        assert result["loss_val"] == -5.0

    def test_trailing_stop(self):
        result = build_engine_settings_dict({
            "ts_apply": True, "ts_start_val": 10.0, "ts_drop_val": -3.0
        })
        assert result["trailing_stop_apply"] is True
        assert result["trailing_start_value"] == 10.0
        assert result["trailing_drop_value"] == -3.0

    def test_telegram_on(self):
        result = build_engine_settings_dict({"tele_on": True})
        assert result["tele_on"] is True

    def test_kiwoom_credentials(self):
        result = build_engine_settings_dict({
            "trade_mode": "test",
            "kiwoom_app_key": "test_key",
            "kiwoom_app_secret": "test_secret",
            "kiwoom_account_no": "87654321",
        })
        assert result["kiwoom_app_key"] == "test_key"
        assert result["kiwoom_app_secret"] == "test_secret"
        assert result["kiwoom_account_no"] == "87654321"

    def test_encrypted_field_decrypted(self):
        """gAAAA로 시작하는 값은 decrypt_secret 호출 — ENCRYPTED 시 평문 반환."""
        with patch("backend.app.core.engine_settings.decrypt_secret",
                   return_value=DecryptResult(state=SecretValueState.ENCRYPTED, plaintext="decrypted_val")):
            result = build_engine_settings_dict({
                "kiwoom_app_key": "gAAAAAencrypted",
            })
            assert result["kiwoom_app_key"] == "decrypted_val"
            assert result["_credential_states"]["kiwoom"]["app_key"] == "ENCRYPTED"

    def test_encrypted_field_decrypt_key_unavailable(self):
        """decrypt_secret KEY_UNAVAILABLE → 빈값 + 상태 기록 (P20 폴백 제거, P25 기동 차단 없음)."""
        with patch("backend.app.core.engine_settings.decrypt_secret",
                   return_value=DecryptResult(state=SecretValueState.KEY_UNAVAILABLE)):
            with patch("backend.app.core.engine_settings.logger") as mock_logger:
                result = build_engine_settings_dict({
                    "kiwoom_app_key": "gAAAAAencrypted",
                })
                assert result["kiwoom_app_key"] == ""
                assert result["_credential_states"]["kiwoom"]["app_key"] == "KEY_UNAVAILABLE"
                mock_logger.warning.assert_called_once()
                assert "암호화 키 없음/오류" in mock_logger.warning.call_args[0][0]

    def test_encrypted_field_decrypt_failed(self):
        """decrypt_secret DECRYPT_FAILED → 빈값 + 상태 기록."""
        with patch("backend.app.core.engine_settings.decrypt_secret",
                   return_value=DecryptResult(state=SecretValueState.DECRYPT_FAILED)):
            with patch("backend.app.core.engine_settings.logger") as mock_logger:
                result = build_engine_settings_dict({
                    "kiwoom_app_key": "gAAAAAencrypted",
                })
                assert result["kiwoom_app_key"] == ""
                assert result["_credential_states"]["kiwoom"]["app_key"] == "DECRYPT_FAILED"
                mock_logger.warning.assert_called_once()
                assert "암호문 손상" in mock_logger.warning.call_args[0][0]

    def test_plaintext_legacy_field(self):
        """gAAAA 접두 아닌 값은 PLAINTEXT_LEGACY — 평문 그대로 반환 (레거시 호환)."""
        result = build_engine_settings_dict({
            "kiwoom_app_key": "plain_key",
        })
        assert result["kiwoom_app_key"] == "plain_key"
        assert result["_credential_states"]["kiwoom"]["app_key"] == "PLAINTEXT_LEGACY"

    def test_empty_credential_field(self):
        """빈 자격값은 EMPTY 상태."""
        result = build_engine_settings_dict({})
        assert result["kiwoom_app_key"] == ""
        assert result["_credential_states"]["kiwoom"]["app_key"] == "EMPTY"
        assert result["_credential_states"]["kiwoom"]["app_secret"] == "EMPTY"

    def test_encrypted_field_with_pre_computed_states(self):
        """B21-01 bugfix: _secret_field_states가 있으면 _decrypt_field 재호출 없이 상태 사용 —
        평문 치환된 값을 PLAINTEXT_LEGACY로 오분류하지 않음."""
        merged = {
            "broker": "kiwoom",
            "trade_mode": "test",
            "kiwoom_app_key": "decrypted_plaintext",
            "kiwoom_app_secret": "decrypted_secret",
            "_secret_field_states": {
                "kiwoom_app_key": "ENCRYPTED",
                "kiwoom_app_secret": "ENCRYPTED",
            },
        }
        result = build_engine_settings_dict(merged)
        assert result["kiwoom_app_key"] == "decrypted_plaintext"
        assert result["kiwoom_app_secret"] == "decrypted_secret"
        assert result["_credential_states"]["kiwoom"]["app_key"] == "ENCRYPTED"
        assert result["_credential_states"]["kiwoom"]["app_secret"] == "ENCRYPTED"

    def test_non_kiwoom_broker_credentials(self):
        """kiwoom 외 증권사 자격증명 동적 수집."""
        result = build_engine_settings_dict({
            "testbroker_app_key": "testbroker_key",
            "testbroker_app_secret": "testbroker_secret",
            "testbroker_account_no": "11111111",
        })
        assert result["testbroker_app_key"] == "testbroker_key"
        assert result["testbroker_app_secret"] == "testbroker_secret"
        assert result["testbroker_account_no"] == "11111111"

    def test_decrypt_failure_logs_warning(self):
        """복호화 실패 시 logger.warning 호출 — DECRYPT_FAILED 상태 (P21 사용자 투명성)."""
        with patch("backend.app.core.engine_settings.decrypt_secret",
                   return_value=DecryptResult(state=SecretValueState.DECRYPT_FAILED)), \
             patch("backend.app.core.engine_settings.logger") as mock_logger:
            result = build_engine_settings_dict({
                "kiwoom_app_key": "gAAAAAencrypted",
            })
            assert result["kiwoom_app_key"] == ""
            mock_logger.warning.assert_called_once()
            assert "복호화 실패" in mock_logger.warning.call_args[0][0]

    def test_sector_sort_keys_migration(self):
        """foreign_net / institution_net 제거 마이그레이션."""
        result = build_engine_settings_dict({
            "sector_sort_keys": ["score", "foreign_net", "institution_net", "rise_ratio"],
        })
        assert "foreign_net" not in result["sector_sort_keys"]
        assert "institution_net" not in result["sector_sort_keys"]
        assert "score" in result["sector_sort_keys"]
        assert "rise_ratio" in result["sector_sort_keys"]

    def test_boost_order_ratio_pct_clamped(self):
        """boost_order_ratio_pct 범위 -100~100 클램프."""
        result = build_engine_settings_dict({"boost_order_ratio_pct": 150})
        assert result["boost_order_ratio_pct"] == 100

    def test_boost_order_ratio_pct_negative_clamped(self):
        result = build_engine_settings_dict({"boost_order_ratio_pct": -150})
        assert result["boost_order_ratio_pct"] == -100

    def test_timetable_confirmed_download_default(self):
        result = build_engine_settings_dict({})
        assert result["timetable.confirmed_download"] == "20:40"

    def test_timetable_confirmed_download_override(self):
        result = build_engine_settings_dict({"timetable.confirmed_download": "21:00"})
        assert result["timetable.confirmed_download"] == "21:00"

    def test_broker_specs_passthrough(self):
        """_broker_specs가 merged에 있으면 result에 포함."""
        result = build_engine_settings_dict({"_broker_specs": {"kiwoom": {"ws": True}}})
        assert result["_broker_specs"] == {"kiwoom": {"ws": True}}

    def test_sell_per_symbol_default(self):
        result = build_engine_settings_dict({})
        assert result["sell_per_symbol"] == {}

    def test_sell_per_symbol_override(self):
        sps = {"005930": {"tp_val": 10.0}}
        result = build_engine_settings_dict({"sell_per_symbol": sps})
        assert result["sell_per_symbol"] == sps

    def test_quote_auto_subscribe_default(self):
        result = build_engine_settings_dict({})
        assert result["quote_auto_subscribe"] is False

    def test_buy_interval_settings(self):
        result = build_engine_settings_dict({"buy_interval_on": True, "buy_interval_sec": 30})
        assert result["buy_interval_on"] is True
        assert result["buy_interval_sec"] == 30

    def test_sell_interval_settings(self):
        result = build_engine_settings_dict({"sell_interval_on": True, "sell_interval_sec": 60})
        assert result["sell_interval_on"] is True
        assert result["sell_interval_sec"] == 60


# ── get_engine_settings (async) ─────────────────────────────────────

class TestGetEngineSettings:
    @pytest.mark.asyncio
    async def test_loads_from_db_and_builds(self):
        """get_engine_settings가 load_integrated_system_settings 호출 후 build."""
        mock_flat = {"broker": "kiwoom", "trade_mode": "test"}
        with patch(
            "backend.app.core.engine_settings.load_integrated_system_settings",
            new=AsyncMock(return_value=mock_flat),
        ):
            result = await get_engine_settings()
        assert result["broker"] == "kiwoom"
        assert result["trade_mode"] == "test"

    @pytest.mark.asyncio
    async def test_user_id_profile_ignored(self):
        """user_id / profile 인자는 호환용으로 무시됨."""
        with patch(
            "backend.app.core.engine_settings.load_integrated_system_settings",
            new=AsyncMock(return_value={}),
        ):
            result = await get_engine_settings(user_id="user1", profile="custom")
        assert result["broker"] == "kiwoom"


# ── apply_settings_change — 타임테이블 재빌드/재예약 배선 (Step 3) ──────

class TestApplySettingsChangeTimetableRebuild:
    """_TIMETABLE_KEYS 변경 시 _TIMETABLE 재빌드 + 타이머 재예약 검증.

    시나리오: 사용자가 설정 화면에서 장 시작 전 사전 준비 시간 3개 중
    하나를 변경하면, 저장 직후 백엔드가 타임테이블을 새 시각으로 다시
    만들고 다음 이벤트 타이머를 다시 예약해야 함 (P14 단일 타이머).
    """

    def setup_method(self):
        """테스트 전 _TIMETABLE 모듈 전역 백업 (P22 정합성)."""
        from backend.app.services import daily_time_scheduler as _dts_mod
        self._orig_timetable = list(_dts_mod._TIMETABLE)

    def teardown_method(self):
        """테스트 후 _TIMETABLE 모듈 전역 복원."""
        from backend.app.services import daily_time_scheduler as _dts_mod
        _dts_mod._TIMETABLE = self._orig_timetable

    @pytest.mark.asyncio
    async def test_nxt_start_triggers_rebuild(self):
        """timetable.nxt_start 변경 → 재빌드 + 재예약 호출."""
        from backend.app.services.engine_service import apply_settings_change
        from backend.app.services import daily_time_scheduler as _dts_mod

        dummy_built = [{"time": (7, 58), "kind": "direct", "ctx": "test"}]
        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.daily_time_scheduler.build_timetable_from_cache",
                return_value=dummy_built,
            ) as mock_build,
            patch(
                "backend.app.services.daily_time_scheduler._schedule_next_timetable_event",
            ) as mock_sched,
        ):
            await apply_settings_change({"timetable.nxt_start"})

        mock_build.assert_called_once()
        mock_sched.assert_called_once()
        assert _dts_mod._TIMETABLE == dummy_built

    @pytest.mark.asyncio
    async def test_nxt_end_triggers_rebuild(self):
        """timetable.nxt_end 변경 → 재빌드 + 재예약 호출."""
        from backend.app.services.engine_service import apply_settings_change
        from backend.app.services import daily_time_scheduler as _dts_mod

        dummy_built = [{"time": (20, 0), "kind": "direct", "ctx": "test"}]
        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.daily_time_scheduler.build_timetable_from_cache",
                return_value=dummy_built,
            ) as mock_build,
            patch(
                "backend.app.services.daily_time_scheduler._schedule_next_timetable_event",
            ) as mock_sched,
        ):
            await apply_settings_change({"timetable.nxt_end"})

        mock_build.assert_called_once()
        mock_sched.assert_called_once()
        assert _dts_mod._TIMETABLE == dummy_built

    @pytest.mark.asyncio
    async def test_krx_start_triggers_rebuild(self):
        """timetable.krx_start 변경 → 재빌드 + 재예약 호출."""
        from backend.app.services.engine_service import apply_settings_change
        from backend.app.services import daily_time_scheduler as _dts_mod

        dummy_built = [{"time": (8, 59), "kind": "direct", "ctx": "test"}]
        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.daily_time_scheduler.build_timetable_from_cache",
                return_value=dummy_built,
            ) as mock_build,
            patch(
                "backend.app.services.daily_time_scheduler._schedule_next_timetable_event",
            ) as mock_sched,
        ):
            await apply_settings_change({"timetable.krx_start"})

        mock_build.assert_called_once()
        mock_sched.assert_called_once()
        assert _dts_mod._TIMETABLE == dummy_built

    @pytest.mark.asyncio
    async def test_confirmed_download_triggers_rebuild(self):
        """timetable.confirmed_download 변경 → 재빌드 + 재예약 호출 (4세션 통합)."""
        from backend.app.services.engine_service import apply_settings_change
        from backend.app.services import daily_time_scheduler as _dts_mod

        dummy_built = [{"time": (20, 40), "kind": "direct", "ctx": "test"}]
        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.daily_time_scheduler.build_timetable_from_cache",
                return_value=dummy_built,
            ) as mock_build,
            patch(
                "backend.app.services.daily_time_scheduler._schedule_next_timetable_event",
            ) as mock_sched,
        ):
            await apply_settings_change({"timetable.confirmed_download"})

        mock_build.assert_called_once()
        mock_sched.assert_called_once()
        assert _dts_mod._TIMETABLE == dummy_built

    @pytest.mark.asyncio
    async def test_scheduler_market_close_on_triggers_rebuild(self):
        """scheduler_market_close_on 토글 변경 → 재빌드 + 재예약 호출 (4세션 — 11번째 항목 스킵/추가)."""
        from backend.app.services.engine_service import apply_settings_change
        from backend.app.services import daily_time_scheduler as _dts_mod

        dummy_built = [{"time": (7, 58), "kind": "direct", "ctx": "test"}]
        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.daily_time_scheduler.build_timetable_from_cache",
                return_value=dummy_built,
            ) as mock_build,
            patch(
                "backend.app.services.daily_time_scheduler._schedule_next_timetable_event",
            ) as mock_sched,
        ):
            await apply_settings_change({"scheduler_market_close_on"})

        mock_build.assert_called_once()
        mock_sched.assert_called_once()
        assert _dts_mod._TIMETABLE == dummy_built

    @pytest.mark.asyncio
    async def test_non_timetable_key_no_rebuild(self):
        """관련 없는 키 변경 → 재빌드/재예약 미호출."""
        from backend.app.services.engine_service import apply_settings_change

        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.daily_time_scheduler.build_timetable_from_cache",
            ) as mock_build,
            patch(
                "backend.app.services.daily_time_scheduler._schedule_next_timetable_event",
            ) as mock_sched,
        ):
            await apply_settings_change({"tele_on"})

        mock_build.assert_not_called()
        mock_sched.assert_not_called()

    @pytest.mark.asyncio
    async def test_rebuild_exception_does_not_propagate(self):
        """재빌드 중 예외 시 apply_settings_change 정상 반환 (P20/P21).

        예외가 사용자에게 전파되지 않고 warning 로그로 처리되어야 함.
        단, 저장 자체는 이미 routes/settings.py에서 완료되었으므로
        다음 기동 시 start_daily_time_scheduler() 빌드로 복구됨.
        """
        from backend.app.services.engine_service import apply_settings_change

        with (
            patch(
                "backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_header_refresh",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.engine_account_notify.notify_desktop_settings_toggled",
                AsyncMock(),
            ),
            patch(
                "backend.app.services.daily_time_scheduler.build_timetable_from_cache",
                side_effect=ValueError("테스트용 예외"),
            ),
            patch(
                "backend.app.services.daily_time_scheduler._schedule_next_timetable_event",
            ),
        ):
            # 예외 전파 없이 정상 반환해야 함
            result = await apply_settings_change({"timetable.nxt_start"})

        assert result is None
