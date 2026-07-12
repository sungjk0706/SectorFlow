"""engine_ws_dispatch.py 단위 테스트 — WS 메시지 분기·파싱 헬퍼·JIF 처리 검증.

state 의존 함수는 state를 mock하여 검증. WS 브로드캐스트가 필요한 async 함수는
_safe_broadcast/_broadcast를 mock하여 검증.
"""
from __future__ import annotations

from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from backend.app.services.engine_ws_dispatch import (
    _get_wl_codes_cached,
    _update_trade_amount_fid14,
    _handle_login,
    _reg_response_item_val,
    _reg_data_rows,
    _handle_reg,
    _check_realtime_latency,
    _handle_real_00,
    _handle_real_balance,
    handle_ws_data,
    _handle_jif,
    _JSTATUS_KRX_ALERT,
    _JSTATUS_KRX_EVENT,
    _JSTATUS_NXT_EVENT,
    _KRX_CB_ACTIVATION_CODES,
    _KRX_CB_RELEASE_CODES,
)


# ── _get_wl_codes_cached ──────────────────────────────────────────────────────────

class TestGetWlCodesCached:
    def test_first_call(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state:
            mock_state.integrated_system_settings_cache = {
                "sector_stock_layout": [("code", "005930"), ("name", "삼성전자"), ("code", "000660")]
            }
            import backend.app.services.engine_ws_dispatch as mod
            mod._wl_codes_cache = set()
            mod._wl_codes_layout_len = -1
            result = _get_wl_codes_cached()
            assert result == {"005930", "000660"}

    def test_cached_same_len(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state:
            mock_state.integrated_system_settings_cache = {
                "sector_stock_layout": [("code", "005930"), ("code", "000660")]
            }
            import backend.app.services.engine_ws_dispatch as mod
            mod._wl_codes_cache = {"005930", "000660"}
            mod._wl_codes_layout_len = 2
            result = _get_wl_codes_cached()
            assert result == {"005930", "000660"}

    def test_layout_changed_rebuilds(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state:
            mock_state.integrated_system_settings_cache = {
                "sector_stock_layout": [("code", "005930"), ("code", "000660"), ("code", "035420")]
            }
            import backend.app.services.engine_ws_dispatch as mod
            mod._wl_codes_cache = {"005930"}
            mod._wl_codes_layout_len = 1
            result = _get_wl_codes_cached()
            assert result == {"005930", "000660", "035420"}


# ── _update_trade_amount_fid14 ────────────────────────────────────────────────────

class TestUpdateTradeAmountFid14:
    def test_positive(self):
        assert _update_trade_amount_fid14("005930", 500) == 500_000_000

    def test_zero(self):
        assert _update_trade_amount_fid14("005930", 0) == 0

    def test_negative(self):
        assert _update_trade_amount_fid14("005930", -1) == 0


# ── _handle_login ──────────────────────────────────────────────────────────────────

class TestHandleLogin:
    def test_success(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_ws_dispatch._trigger_reg_pipeline", create=True), \
             patch("backend.app.services.daily_time_scheduler._trigger_reg_pipeline", create=True) as mock_trigger:
            _handle_login({"return_code": "0"})
            assert mock_state.login_ok is True
            mock_es._notify_reg_ack.assert_called_once()

    def test_failure(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es:
            mock_state.login_ok = False
            _handle_login({"return_code": "1"})
            assert mock_state.login_ok is False
            mock_es._notify_reg_ack.assert_not_called()


# ── _reg_response_item_val ────────────────────────────────────────────────────────

class TestRegResponseItemVal:
    def test_string(self):
        assert _reg_response_item_val({"item": "005930"}) == "005930"

    def test_list(self):
        assert _reg_response_item_val({"item": ["005930"]}) == "005930"

    def test_empty_list(self):
        assert _reg_response_item_val({"item": []}) is None

    def test_none(self):
        assert _reg_response_item_val({"item": None}) is None

    def test_missing_key(self):
        assert _reg_response_item_val({}) is None

    def test_empty_string(self):
        assert _reg_response_item_val({"item": ""}) is None

    def test_list_with_none(self):
        assert _reg_response_item_val({"item": [None]}) is None

    def test_whitespace_string(self):
        assert _reg_response_item_val({"item": "  005930  "}) == "005930"


# ── _reg_data_rows ──────────────────────────────────────────────────────────────────

class TestRegDataRows:
    def test_list(self):
        d = {"data": [{"a": 1}, {"b": 2}]}
        assert _reg_data_rows(d) == [{"a": 1}, {"b": 2}]

    def test_dict(self):
        d = {"data": {"a": 1}}
        assert _reg_data_rows(d) == [{"a": 1}]

    def test_non_list_non_dict(self):
        assert _reg_data_rows({"data": "string"}) == []

    def test_missing(self):
        assert _reg_data_rows({}) == []

    def test_filters_non_dict(self):
        d = {"data": [{"a": 1}, "not_dict", {"b": 2}]}
        assert _reg_data_rows(d) == [{"a": 1}, {"b": 2}]


# ── _handle_reg ────────────────────────────────────────────────────────────────────

class TestHandleReg:
    def test_success_rc0(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es:
            mock_state.master_stocks_cache = {}
            mock_state.REG_REAL_DEBUG_EXTRA_LOG = False
            _handle_reg({"trnm": "REG", "return_code": "0", "data": [{"item": "005930", "type": "0B"}]})
            mock_es._notify_reg_ack.assert_called_once_with(return_code="0")

    def test_unreg_skips_item_processing(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es:
            mock_state.master_stocks_cache = {}
            mock_state.REG_REAL_DEBUG_EXTRA_LOG = False
            _handle_reg({"trnm": "UNREG", "return_code": "0", "data": [{"item": "005930", "type": "0B"}]})
            mock_es._notify_reg_ack.assert_called_once_with(return_code="0")

    def test_rc_105110_unsubscribes(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es:
            mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
            mock_state.REG_REAL_DEBUG_EXTRA_LOG = False
            _handle_reg({"trnm": "REG", "return_code": "105110", "data": [{"item": "005930", "type": "0B"}]})
            assert "_subscribed" not in mock_state.master_stocks_cache["005930"]

    def test_non_zero_rc_unsubscribes(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es:
            mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
            mock_state.REG_REAL_DEBUG_EXTRA_LOG = False
            _handle_reg({"trnm": "REG", "return_code": "999", "data": [{"item": "005930", "type": "0B"}]})
            assert "_subscribed" not in mock_state.master_stocks_cache["005930"]


# ── _check_realtime_latency ────────────────────────────────────────────────────────

class TestCheckRealtimeLatency:
    def test_no_latency(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            ts = int(__import__("time").time() * 1000)
            _check_realtime_latency(ts)
            assert mock_state.realtime_latency_exceeded is False

    def test_latency_exceeded_200ms(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            import time
            ts = int(time.time() * 1000) - 250
            _check_realtime_latency(ts)
            assert mock_state.realtime_latency_exceeded is True

    def test_latency_recovery(self):
        with patch("backend.app.services.engine_ws_dispatch.state") as mock_state:
            mock_state.realtime_latency_exceeded = True
            ts = int(__import__("time").time() * 1000)
            _check_realtime_latency(ts)
            assert mock_state.realtime_latency_exceeded is False


# ── handle_ws_data ──────────────────────────────────────────────────────────────────

class TestHandleWsData:
    @pytest.mark.asyncio
    async def test_login(self):
        with patch("backend.app.services.engine_ws_dispatch._handle_login") as mock_login:
            await handle_ws_data({"trnm": "LOGIN", "return_code": "0"})
            mock_login.assert_called_once()

    @pytest.mark.asyncio
    async def test_reg(self):
        with patch("backend.app.services.engine_ws_dispatch._handle_reg") as mock_reg:
            await handle_ws_data({"trnm": "REG", "return_code": "0"})
            mock_reg.assert_called_once()

    @pytest.mark.asyncio
    async def test_unreg(self):
        with patch("backend.app.services.engine_ws_dispatch._handle_reg") as mock_reg:
            await handle_ws_data({"trnm": "UNREG", "return_code": "0"})
            mock_reg.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove(self):
        with patch("backend.app.services.engine_ws_dispatch._handle_reg") as mock_reg:
            await handle_ws_data({"trnm": "REMOVE", "return_code": "0"})
            mock_reg.assert_called_once()

    @pytest.mark.asyncio
    async def test_jif(self):
        with patch("backend.app.services.engine_ws_dispatch._handle_jif", new_callable=AsyncMock) as mock_jif:
            await handle_ws_data({"trnm": "JIF", "jangubun": "1", "jstatus": "61"})
            mock_jif.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_trnm(self):
        await handle_ws_data({"trnm": "UNKNOWN"})

    @pytest.mark.asyncio
    async def test_missing_trnm(self):
        await handle_ws_data({})

    @pytest.mark.asyncio
    async def test_exception_handled(self):
        with patch("backend.app.services.engine_ws_dispatch._handle_login", side_effect=RuntimeError("test")):
            await handle_ws_data({"trnm": "LOGIN"})


# ── _handle_jif ────────────────────────────────────────────────────────────────────

class TestHandleJif:
    @pytest.mark.asyncio
    async def test_empty_jangubun(self):
        with patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            await _handle_jif({"jangubun": "", "jstatus": "61"})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_jstatus(self):
        with patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            await _handle_jif({"jangubun": "1", "jstatus": ""})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_jangubun(self):
        with patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            await _handle_jif({"jangubun": "3", "jstatus": "61"})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_jstatus(self):
        with patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            await _handle_jif({"jangubun": "1", "jstatus": "99"})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cb_activation(self):
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc, \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram"):
            mock_es.state.market_phase = {"krx_alert": None}
            mock_es.state.krx_circuit_breaker_active = False
            mock_es.state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "61"})
            assert mock_es.state.krx_circuit_breaker_active is True
            assert mock_es.state.market_phase["krx_alert"] == "서킷브레이커 1단계 발동"
            assert mock_bc.call_count >= 2

    @pytest.mark.asyncio
    async def test_cb_release(self):
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc, \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram"):
            mock_es.state.market_phase = {"krx_alert": "서킷브레이커 1단계 발동"}
            mock_es.state.krx_circuit_breaker_active = True
            mock_es.state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "63"})
            assert mock_es.state.krx_circuit_breaker_active is False
            assert mock_es.state.market_phase["krx_alert"] == "서킷브레이커 1단계 동시호가 종료"

    @pytest.mark.asyncio
    async def test_same_alert_no_change(self):
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"krx_alert": "서킷브레이커 1단계 발동"}
            mock_es.state.krx_circuit_breaker_active = True
            mock_es.state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "61"})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_none_alert_no_change(self):
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"krx_alert": None}
            mock_es.state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "62"})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_krx_event_sets_krx_event(self):
        """jangubun 1 + jstatus 24(정규장 장개시 5분 전) → krx_event 갱신 + 브로드캐스트."""
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"krx_event": None}
            await _handle_jif({"jangubun": "1", "jstatus": "24"})
            assert mock_es.state.market_phase["krx_event"] == "정규장 장개시 5분 전"
            mock_bc.assert_awaited_once()
            assert mock_bc.call_args.args[0] == "market-phase"
            assert mock_bc.call_args.args[1] == {"krx_event": "정규장 장개시 5분 전"}

    @pytest.mark.asyncio
    async def test_krx_event_same_no_rebroadcast(self):
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"krx_event": "정규장 장개시 5분 전"}
            await _handle_jif({"jangubun": "2", "jstatus": "24"})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_krx_boundary_event_not_stored(self):
        """jangubun 1 + jstatus 21(장시작, 경계) → 시계가 인계하므로 JIF는 저장하지 않음."""
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"krx_event": None}
            await _handle_jif({"jangubun": "1", "jstatus": "21"})
            assert mock_es.state.market_phase.get("krx_event") is None
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_nxt_event_sets_nxt_event(self):
        """jangubun 6 + jstatus A4(프리마켓 장개시 5분 전) → nxt_event 갱신."""
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"nxt_event": None}
            await _handle_jif({"jangubun": "6", "jstatus": "A4"})
            assert mock_es.state.market_phase["nxt_event"] == "프리마켓 장개시 5분 전"
            mock_bc.assert_awaited_once()
            assert mock_bc.call_args.args[1] == {"nxt_event": "프리마켓 장개시 5분 전"}

    @pytest.mark.asyncio
    async def test_nxt_event_aftermarket_countdown(self):
        """jangubun 6 + jstatus B3(에프터마켓 장개시 1분 전) → nxt_event 갱신."""
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"nxt_event": None}
            await _handle_jif({"jangubun": "6", "jstatus": "B3"})
            assert mock_es.state.market_phase["nxt_event"] == "에프터마켓 장개시 1분 전"

    @pytest.mark.asyncio
    async def test_nxt_boundary_event_not_stored(self):
        """jangubun 6 + jstatus 55(프리마켓 개시, 경계) → 시계가 인계하므로 저장하지 않음."""
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"nxt_event": None}
            await _handle_jif({"jangubun": "6", "jstatus": "55"})
            assert mock_es.state.market_phase.get("nxt_event") is None
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_nxt_cb_code_not_handled(self):
        """jangubun 6 + jstatus 61(서킷브레이커) → CB는 KRX(1/2) 전용이므로 NXT에서 미처리."""
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_es.state.market_phase = {"nxt_event": None, "krx_alert": None}
            await _handle_jif({"jangubun": "6", "jstatus": "61"})
            mock_bc.assert_not_awaited()


# ── JIF constants ──────────────────────────────────────────────────────────────────

class TestJifConstants:
    def test_activation_codes_subset_of_alerts(self):
        for code in _KRX_CB_ACTIVATION_CODES:
            assert code in _JSTATUS_KRX_ALERT
            assert _JSTATUS_KRX_ALERT[code] is not None

    def test_release_codes_subset_of_alerts(self):
        for code in _KRX_CB_RELEASE_CODES:
            assert code in _JSTATUS_KRX_ALERT
            assert _JSTATUS_KRX_ALERT[code] is not None

    def test_none_alerts_exist(self):
        none_codes = [k for k, v in _JSTATUS_KRX_ALERT.items() if v is None]
        assert len(none_codes) > 0
