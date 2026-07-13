"""engine_settings.py 단위 테스트 — 엔진 설정 빌더."""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from backend.app.core.engine_settings import (
    get_engine_settings,
    build_engine_settings_dict,
)


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
        assert len(result["ws_subscribe_start"]) == 5
        assert len(result["ws_subscribe_end"]) == 5

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
        assert result["buy_block_strength_on"] is False  # 기본값 0 → 비활성

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

    def test_risk_fields_defaults(self):
        result = build_engine_settings_dict({})
        assert result["max_daily_loss_limit"] == -500000
        assert result["max_single_stock_exposure"] == 20000000

    def test_telegram_fields_defaults(self):
        result = build_engine_settings_dict({})
        assert result["tele_on"] is False
        assert result["telegram_on"] is False
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
        assert result["broker_config"]["account"] == "kiwoom"

    def test_test_virtual_deposit(self):
        result = build_engine_settings_dict({})
        assert result["test_virtual_deposit"] == 10000000

    def test_scheduler_defaults(self):
        result = build_engine_settings_dict({})
        assert result["scheduler_market_close_on"] is True
        assert result["scheduler_5d_download_on"] is True


class TestBuildEngineSettingsDictOverride:
    """flat dict 오버라이드 검증."""

    def test_broker_override(self):
        result = build_engine_settings_dict({"broker": "naver"})
        assert result["broker"] == "naver"
        assert result["broker_config"]["websocket"] == "naver"

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
        result = build_engine_settings_dict({"loss_apply": True, "loss_val": 5.0})
        assert result["loss_cut_apply"] is True
        assert result["loss_cut_value"] == 5.0
        assert result["loss_apply"] is True
        assert result["loss_val"] == 5.0

    def test_trailing_stop(self):
        result = build_engine_settings_dict({
            "ts_apply": True, "ts_start_val": 10.0, "ts_drop_val": 3.0
        })
        assert result["trailing_stop_apply"] is True
        assert result["trailing_start_value"] == 10.0
        assert result["trailing_drop_value"] == 3.0

    def test_max_position_size_none(self):
        result = build_engine_settings_dict({"max_position_size": None})
        assert result["max_position_size"] == 0

    def test_max_position_size_string_none(self):
        result = build_engine_settings_dict({"max_position_size": "None"})
        assert result["max_position_size"] == 0

    def test_max_position_size_value(self):
        result = build_engine_settings_dict({"max_position_size": "5000000"})
        assert result["max_position_size"] == 5000000

    def test_telegram_on(self):
        result = build_engine_settings_dict({"tele_on": True})
        assert result["tele_on"] is True
        assert result["telegram_on"] is True

    def test_kiwoom_credentials_real_mode(self):
        result = build_engine_settings_dict({
            "trade_mode": "real",
            "kiwoom_app_key_real": "real_key",
            "kiwoom_app_secret_real": "real_secret",
            "kiwoom_account_no_real": "12345678",
        })
        assert result["kiwoom_app_key"] == "real_key"
        assert result["kiwoom_app_secret"] == "real_secret"
        assert result["kiwoom_account_no"] == "12345678"

    def test_kiwoom_credentials_test_mode_fallback_legacy(self):
        """test 모드에서 real 키 없으면 레거시 단일 필드 사용."""
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
        """gAAAA로 시작하는 값은 decrypt_value 호출."""
        with patch("backend.app.core.engine_settings.decrypt_value", return_value="decrypted_val"):
            result = build_engine_settings_dict({
                "kiwoom_app_key": "gAAAAAencrypted",
            })
            assert result["kiwoom_app_key"] == "decrypted_val"

    def test_encrypted_field_decrypt_returns_none(self):
        """decrypt_value가 None 반환하면 빈 문자열."""
        with patch("backend.app.core.engine_settings.decrypt_value", return_value=None):
            result = build_engine_settings_dict({
                "kiwoom_app_key": "gAAAAAencrypted",
            })
            assert result["kiwoom_app_key"] == ""

    def test_non_kiwoom_broker_credentials(self):
        """kiwoom 외 증권사 자격증명 동적 수집."""
        result = build_engine_settings_dict({
            "naver_app_key": "naver_key",
            "naver_app_secret": "naver_secret",
            "naver_account_no": "11111111",
        })
        assert result["naver_app_key"] == "naver_key"
        assert result["naver_app_secret"] == "naver_secret"
        assert result["naver_account_no"] == "11111111"

    def test_non_kiwoom_broker_credentials_real_priority(self):
        """non-kiwoom real 키 우선."""
        result = build_engine_settings_dict({
            "naver_app_key": "naver_key",
            "naver_app_key_real": "naver_real_key",
            "naver_app_secret": "naver_secret",
            "naver_app_secret_real": "naver_real_secret",
        })
        assert result["naver_app_key"] == "naver_real_key"
        assert result["naver_app_secret"] == "naver_real_secret"

    def test_decrypt_failure_logs_warning(self):
        """복호화 실패 시 logger.warning 호출 (P21 사용자 투명성)."""
        with patch("backend.app.core.engine_settings.decrypt_value", return_value=None), \
             patch("backend.app.core.engine_settings.logger") as mock_logger:
            result = build_engine_settings_dict({
                "kiwoom_app_key": "gAAAAAencrypted",
            })
            assert result["kiwoom_app_key"] == ""
            mock_logger.warning.assert_called_once()
            assert "복호화 실패" in mock_logger.warning.call_args[0][0]

    def test_real_key_decrypt_failure_blocks_legacy_fallback(self):
        """real 키가 암호문인데 복호화 실패 → 레거시 폴백 금지 + 에러 로그 (P21)."""
        with patch("backend.app.core.engine_settings.decrypt_value", return_value=None), \
             patch("backend.app.core.engine_settings.logger") as mock_logger:
            result = build_engine_settings_dict({
                "trade_mode": "real",
                "kiwoom_app_key_real": "gAAAAAencrypted_real",
                "kiwoom_app_key": "legacy_key",
            })
            # real 키 복호화 실패 → 빈문자열 (레거시 폴백 금지)
            assert result["kiwoom_app_key"] == ""
            mock_logger.error.assert_called_once()
            assert "레거시 폴백 금지" in mock_logger.error.call_args[0][0]

    def test_real_key_empty_falls_back_to_legacy(self):
        """real 키가 빈문자열 → 레거시 폴백 허용 (정상 마이그레이션 유지)."""
        result = build_engine_settings_dict({
            "trade_mode": "real",
            "kiwoom_app_key_real": "",
            "kiwoom_app_key": "legacy_key",
        })
        assert result["kiwoom_app_key"] == "legacy_key"

    def test_non_kiwoom_real_key_decrypt_failure_blocks_legacy(self):
        """non-kiwoom real 키 복호화 실패 → 레거시 폴백 금지 (P21)."""
        with patch("backend.app.core.engine_settings.decrypt_value", return_value=None), \
             patch("backend.app.core.engine_settings.logger") as mock_logger:
            result = build_engine_settings_dict({
                "naver_app_key_real": "gAAAAAencrypted_real",
                "naver_app_key": "naver_legacy_key",
            })
            assert result["naver_app_key"] == ""
            mock_logger.error.assert_called_once()

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

    def test_boost_order_ratio_legacy_side_sell(self):
        """레거시 boost_order_ratio_side=sell → 음수 변환."""
        result = build_engine_settings_dict({
            "boost_order_ratio_pct": 20,
            "boost_order_ratio_side": "sell",
        })
        assert result["boost_order_ratio_pct"] == -20

    def test_boost_order_ratio_legacy_side_buy(self):
        result = build_engine_settings_dict({
            "boost_order_ratio_pct": 20,
            "boost_order_ratio_side": "buy",
        })
        assert result["boost_order_ratio_pct"] == 20

    def test_confirmed_download_time_default(self):
        result = build_engine_settings_dict({})
        assert result["confirmed_download_time"] == "20:40"

    def test_confirmed_download_time_override(self):
        result = build_engine_settings_dict({"confirmed_download_time": "21:00"})
        assert result["confirmed_download_time"] == "21:00"

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

    def test_ws_subscribe_on_default(self):
        result = build_engine_settings_dict({})
        assert result["ws_subscribe_on"] is False

    def test_quote_auto_subscribe_default(self):
        result = build_engine_settings_dict({})
        assert result["quote_auto_subscribe"] is False

    def test_buy_interval_settings(self):
        result = build_engine_settings_dict({"buy_interval_on": True, "buy_interval_min": 30})
        assert result["buy_interval_on"] is True
        assert result["buy_interval_min"] == 30


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
