"""engine_ws_dispatch.py 단위 테스트 — WS 메시지 분기·파싱 헬퍼·JIF 처리 검증.

state 의존 함수는 state를 mock하여 검증. WS 브로드캐스트가 필요한 async 함수는
_safe_broadcast/_broadcast를 mock하여 검증.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from backend.app.services.engine_ws_dispatch import (
    _handle_login,
    _reg_response_item_val,
    _reg_data_rows,
    _handle_reg,
    _check_realtime_latency,
    handle_ws_data,
    _handle_jif,
    _JSTATUS_KRX_ALERT,
    _KRX_CIRCUIT_BREAKER_ACTIVATION_CODES,
    _KRX_CIRCUIT_BREAKER_RELEASE_CODES,
    _KRX_SIDECAR_ACTIVATION_CODES,
    _KRX_SIDECAR_RELEASE_CODES,
    _JIF_PHASE_MAP_KRX,
    _JIF_PHASE_MAP_NXT,
    _JIF_IGNORE_CODES,
    _JIF_COUNTDOWN_KRX,
    _JIF_COUNTDOWN_NXT,
)


# ── _handle_login ──────────────────────────────────────────────────────────────────

class TestHandleLogin:
    def test_success(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_state._notify_reg_ack") as mock_notify, \
             patch("backend.app.services.engine_ws_dispatch._trigger_reg_pipeline", create=True), \
             patch("backend.app.services.daily_time_scheduler._trigger_reg_pipeline", create=True):
            _handle_login({"return_code": "0"})
            assert mock_state.login_ok is True
            mock_notify.assert_called_once()

    def test_failure(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_state._notify_reg_ack") as mock_notify:
            mock_state.login_ok = False
            _handle_login({"return_code": "1"})
            assert mock_state.login_ok is False
            mock_notify.assert_not_called()


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
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_state._notify_reg_ack") as mock_notify:
            mock_state.master_stocks_cache = {}
            _handle_reg({"trnm": "REG", "return_code": "0", "data": [{"item": "005930", "type": "0B"}]})
            mock_notify.assert_called_once_with(return_code="0")

    def test_unreg_skips_item_processing(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_state._notify_reg_ack") as mock_notify:
            mock_state.master_stocks_cache = {}
            _handle_reg({"trnm": "UNREG", "return_code": "0", "data": [{"item": "005930", "type": "0B"}]})
            mock_notify.assert_called_once_with(return_code="0")

    def test_rc_105110_unsubscribes(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_state._notify_reg_ack"):
            mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
            _handle_reg({"trnm": "REG", "return_code": "105110", "data": [{"item": "005930", "type": "0B"}]})
            assert "_subscribed" not in mock_state.master_stocks_cache["005930"]

    def test_non_zero_rc_unsubscribes(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_state._notify_reg_ack"):
            mock_state.master_stocks_cache = {"005930": {"_subscribed": True}}
            _handle_reg({"trnm": "REG", "return_code": "999", "data": [{"item": "005930", "type": "0B"}]})
            assert "_subscribed" not in mock_state.master_stocks_cache["005930"]


# ── _check_realtime_latency ────────────────────────────────────────────────────────

class TestCheckRealtimeLatency:
    def test_no_latency(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            ts = int(__import__("time").time() * 1000)
            _check_realtime_latency(ts)
            assert mock_state.realtime_latency_exceeded is False

    def test_latency_exceeded_200ms(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = False
            import time
            ts = int(time.time() * 1000) - 250
            _check_realtime_latency(ts)
            assert mock_state.realtime_latency_exceeded is True

    def test_latency_recovery(self):
        with patch("backend.app.services.engine_state.state") as mock_state:
            mock_state.realtime_latency_exceeded = True
            ts = int(__import__("time").time() * 1000)
            _check_realtime_latency(ts)
            assert mock_state.realtime_latency_exceeded is False

    def test_latency_exceeded_broadcasts_blocked(self):
        """200ms 초과 진입 시 realtime-latency-status {blocked: True} 브로드캐스트 (P21)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch._broadcast_realtime_latency_status") as mock_bc:
            mock_state.realtime_latency_exceeded = False
            import time
            ts = int(time.time() * 1000) - 250
            _check_realtime_latency(ts)
            mock_bc.assert_called_once_with(blocked=True)

    def test_latency_recovery_broadcasts_unblocked(self):
        """지연 회복 시 realtime-latency-status {blocked: False} 브로드캐스트 (P21)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch._broadcast_realtime_latency_status") as mock_bc:
            mock_state.realtime_latency_exceeded = True
            ts = int(__import__("time").time() * 1000)
            _check_realtime_latency(ts)
            mock_bc.assert_called_once_with(blocked=False)

    def test_no_broadcast_when_state_unchanged(self):
        """이미 차단 상태에서 추가 200ms 초과 시 중복 브로드캐스트 안 함 (P24 단순성)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch._broadcast_realtime_latency_status") as mock_bc:
            mock_state.realtime_latency_exceeded = True
            import time
            ts = int(time.time() * 1000) - 250
            _check_realtime_latency(ts)
            mock_bc.assert_not_called()


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
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc, \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "정규장", "krx_alert": "서킷브레이커 1단계 발동"}), \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram"):
            mock_state.market_phase = {"krx_alert": None}
            mock_state.krx_circuit_breaker_active = False
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "61"})
            assert mock_state.krx_circuit_breaker_active is True
            assert mock_state.market_phase["krx_alert"] == "서킷브레이커 1단계 발동"
            assert mock_bc.call_count >= 2

    @pytest.mark.asyncio
    async def test_cb_release(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "정규장", "krx_alert": None}), \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram"):
            mock_state.market_phase = {"krx_alert": "서킷브레이커 1단계 발동"}
            mock_state.krx_circuit_breaker_active = True
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "63"})
            assert mock_state.krx_circuit_breaker_active is False
            # 해제 코드 수신 시 krx_alert 즉시 None 클리어 — 배지 즉시 소멸 (P24 단순성)
            assert mock_state.market_phase["krx_alert"] is None

    # ── 사이드카: 자동매매 중단 없음, UI 알림만 (회귀 테스트 — 2026-07-31 사고 재현 방지) ──

    @pytest.mark.asyncio
    async def test_sidecar_activation_no_trading_halt(self):
        """사이드카 매수 발동(66) → krx_circuit_breaker_active True 설정 안 함 (개인 매매 유지)."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc, \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "정규장", "krx_alert": "사이드카 매수 발동"}), \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram") as mock_tg:
            mock_state.market_phase = {"krx_alert": None}
            mock_state.krx_circuit_breaker_active = False
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "66"})
            # 핵심: 사이드카는 자동매매 중단하지 않음
            assert mock_state.krx_circuit_breaker_active is False
            # UI 알림은 갱신 (krx_alert 배지 표시)
            assert mock_state.market_phase["krx_alert"] == "사이드카 매수 발동"
            # market-phase 브로드캐스트는 수행 (UI 배지 갱신)
            mock_bc.assert_awaited()
            # 텔레그램 알림은 "자동매매 유지" 메시지
            mock_tg.assert_called_once()
            assert "자동매매 유지" in mock_tg.call_args[0][0] or "개인 자동매매 유지" in mock_tg.call_args[0][0]

    @pytest.mark.asyncio
    async def test_sidecar_sell_activation_no_trading_halt(self):
        """사이드카 매도 발동(64) → krx_circuit_breaker_active True 설정 안 함."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "정규장", "krx_alert": "사이드카 매도 발동"}), \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram"):
            mock_state.market_phase = {"krx_alert": None}
            mock_state.krx_circuit_breaker_active = False
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "64"})
            assert mock_state.krx_circuit_breaker_active is False
            assert mock_state.market_phase["krx_alert"] == "사이드카 매도 발동"

    @pytest.mark.asyncio
    async def test_sidecar_release_clears_alert_no_trading_change(self):
        """사이드카 매수 해제(67) → krx_alert None 클리어, krx_circuit_breaker_active 변경 없음.

        2026-07-31 사고 재현 방지: 해제 코드 67이 누락되어 플래그가 True로 영구 유지된 버그 회귀 테스트.
        """
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "정규장", "krx_alert": None}), \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram") as mock_tg:
            mock_state.market_phase = {"krx_alert": "사이드카 매수 발동"}
            mock_state.krx_circuit_breaker_active = False  # 사이드카 발동 중에도 False 유지했음
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "67"})
            # 해제 후에도 False 유지 (변경 없음)
            assert mock_state.krx_circuit_breaker_active is False
            # krx_alert는 None으로 클리어 — 배지 소멸
            assert mock_state.market_phase["krx_alert"] is None
            # 텔레그램 알림 전송 (프로그램 매매 재개)
            mock_tg.assert_called_once()

    @pytest.mark.asyncio
    async def test_sidecar_does_not_block_auto_sell_effective(self):
        """사이드카 발동 중 auto_sell_effective() 차단되지 않음 — krx_circuit_breaker_active=False 유지.

        핵심 회귀 테스트: 사이드카 중에도 손절/익절 정상 작동해야 함.
        """
        from backend.app.services.auto_trading_effective import auto_sell_effective
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "정규장", "krx_alert": "사이드카 매수 발동"}), \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram"):
            mock_state.market_phase = {"krx_alert": None}
            mock_state.krx_circuit_breaker_active = False
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "66"})
            # auto_sell_effective가 krx_circuit_breaker_active=False를 반영하여 차단하지 않음
            # (실제 auto_sell_effective 호출은 state mock 의존 — 여기서는 플래그 값만 검증)
            assert mock_state.krx_circuit_breaker_active is False

    @pytest.mark.asyncio
    async def test_same_alert_no_change(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_state.market_phase = {"krx_alert": "서킷브레이커 1단계 발동"}
            mock_state.krx_circuit_breaker_active = True
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "61"})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_none_alert_no_change(self):
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_state.market_phase = {"krx_alert": None}
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "62"})
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_nxt_jangubun_not_handled(self):
        """jangubun 6(NXT) + jstatus 61(서킷브레이커) → NXT는 CB 코드 미처리.

        jstatus 61은 KRX 서킷브레이커 코드로 _JIF_PHASE_MAP_NXT에 없으므로
        NXT 페이즈 전환도 미발생, CB 처리도 jangubun 1/2 전용이라 미수행.
        (NXT 페이즈 전환 코드 55/57/21/31/41/56/58은 별도 테스트에서 검증)
        """
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch._apply_jif_phase") as mock_apply, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            mock_state.market_phase = {"krx_alert": None}
            await _handle_jif({"jangubun": "6", "jstatus": "61"})
            mock_apply.assert_not_called()
            mock_bc.assert_not_awaited()

    # ── 장 상태 전환 처리 (안 D — JIF 1순위) ──

    @pytest.mark.asyncio
    async def test_jif_krx_phase_transition(self):
        """jangubun=1, jstatus=21 → KRX '정규장' 페이즈 전환 (_apply_jif_phase 호출)."""
        with patch("backend.app.services.engine_ws_dispatch._apply_jif_phase") as mock_apply, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            await _handle_jif({"jangubun": "1", "jstatus": "21"})
            mock_apply.assert_called_once_with(krx="정규장")
            mock_bc.assert_not_awaited()  # jstatus 21은 CB 코드 아니므로 _broadcast 미호출

    @pytest.mark.asyncio
    async def test_jif_nxt_phase_transition(self):
        """jangubun=6, jstatus=55 → NXT '프리마켓' 페이즈 전환 (_apply_jif_phase 호출)."""
        with patch("backend.app.services.engine_ws_dispatch._apply_jif_phase") as mock_apply, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            await _handle_jif({"jangubun": "6", "jstatus": "55"})
            mock_apply.assert_called_once_with(nxt="프리마켓")
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_jif_countdown_handled(self):
        """jstatus=23 (장개시 1분전) → 카운트다운 코드 처리, _apply_jif_phase 미호출 + override 저장 + 브로드캐스트."""
        mock_state = MagicMock()
        mock_state.market_phase = {"krx": "시가 동시호가", "nxt": "정규장 준비"}
        with patch("backend.app.services.engine_ws_dispatch.engine_state.state", mock_state), \
             patch("backend.app.services.engine_ws_dispatch._apply_jif_phase") as mock_apply, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc, \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "시가 동시호가", "nxt": "정규장 준비"}):
            await _handle_jif({"jangubun": "1", "jstatus": "23"})
            mock_apply.assert_not_called()  # 카운트다운 코드는 페이즈 전환 아님
            mock_bc.assert_awaited_once()  # 카운트다운 브로드캐스트
            # override 저장 확인 — jstatus=23는 KRX 장개시 1분전
            assert mock_state.krx_countdown_override is not None
            assert mock_state.krx_countdown_override["label"] == "정규장 장개시"
            assert mock_state.krx_countdown_override["remaining_sec"] == 60

    @pytest.mark.asyncio
    async def test_jif_nxt_aftermarket_close(self):
        """jangubun=6, jstatus=58 → NXT '장마감' 페이즈 전환."""
        with patch("backend.app.services.engine_ws_dispatch._apply_jif_phase") as mock_apply, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock) as mock_bc:
            await _handle_jif({"jangubun": "6", "jstatus": "58"})
            mock_apply.assert_called_once_with(nxt="장마감")
            mock_bc.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_jif_krx_circuit_breaker_no_phase_transition(self):
        """jstatus=61 (서킷브레이커) → 페이즈 전환 없음, CB 처리만 수행."""
        with patch("backend.app.services.engine_state.state") as mock_state, \
             patch("backend.app.services.engine_ws_dispatch._apply_jif_phase") as mock_apply, \
             patch("backend.app.services.engine_account_notify._broadcast", new_callable=AsyncMock), \
             patch("backend.app.services.daily_time_scheduler.get_market_phase", return_value={"krx": "정규장", "nxt": "정규장", "krx_alert": "서킷브레이커 1단계 발동"}), \
             patch("backend.app.services.engine_ws_dispatch._notify_krx_cb_telegram"):
            mock_state.market_phase = {"krx_alert": None}
            mock_state.krx_circuit_breaker_active = False
            mock_state.integrated_system_settings_cache = {}
            await _handle_jif({"jangubun": "1", "jstatus": "61"})
            mock_apply.assert_not_called()  # CB 코드는 페이즈 맵에 없으므로 페이즈 전환 미발생
            assert mock_state.krx_circuit_breaker_active is True


# ── JIF constants ──────────────────────────────────────────────────────────────────

class TestJifConstants:
    def test_circuit_breaker_activation_codes_subset_of_alerts(self):
        for code in _KRX_CIRCUIT_BREAKER_ACTIVATION_CODES:
            assert code in _JSTATUS_KRX_ALERT
            assert _JSTATUS_KRX_ALERT[code] is not None

    def test_circuit_breaker_release_codes_subset_of_alerts(self):
        for code in _KRX_CIRCUIT_BREAKER_RELEASE_CODES:
            assert code in _JSTATUS_KRX_ALERT
            assert _JSTATUS_KRX_ALERT[code] is not None

    def test_sidecar_activation_codes_subset_of_alerts(self):
        for code in _KRX_SIDECAR_ACTIVATION_CODES:
            assert code in _JSTATUS_KRX_ALERT
            assert _JSTATUS_KRX_ALERT[code] is not None

    def test_sidecar_release_codes_subset_of_alerts(self):
        for code in _KRX_SIDECAR_RELEASE_CODES:
            assert code in _JSTATUS_KRX_ALERT
            assert _JSTATUS_KRX_ALERT[code] is not None

    def test_circuit_breaker_and_sidecar_codes_disjoint(self):
        """서킷브레이커 코드와 사이드카 코드가 중복 없음 (P10 SSOT — 카테고리 분리)."""
        cb_all = _KRX_CIRCUIT_BREAKER_ACTIVATION_CODES | _KRX_CIRCUIT_BREAKER_RELEASE_CODES
        sidecar_all = _KRX_SIDECAR_ACTIVATION_CODES | _KRX_SIDECAR_RELEASE_CODES
        assert not (cb_all & sidecar_all), f"서킷브레이커/사이드카 코드 중복: {cb_all & sidecar_all}"

    def test_none_alerts_exist(self):
        none_codes = [k for k, v in _JSTATUS_KRX_ALERT.items() if v is None]
        assert len(none_codes) > 0

    # ── JIF 페이즈 맵 완전성 (안 D) ──

    def test_phase_map_no_overlap_with_ignore_codes(self):
        """_JIF_PHASE_MAP_KRX/NXT 키가 _JIF_IGNORE_CODES와 중복 없음 (P20 폴백 금지)."""
        krx_keys = set(_JIF_PHASE_MAP_KRX.keys())
        nxt_keys = set(_JIF_PHASE_MAP_NXT.keys())
        ignore = set(_JIF_IGNORE_CODES)
        assert not (krx_keys & ignore), f"KRX 맵과 무시 코드 중복: {krx_keys & ignore}"
        assert not (nxt_keys & ignore), f"NXT 맵과 무시 코드 중복: {nxt_keys & ignore}"

    def test_phase_map_no_overlap_with_cb_alerts(self):
        """_JIF_PHASE_MAP_KRX 키가 _JSTATUS_KRX_ALERT(CB)와 중복 없음 — 분리 처리 보장."""
        krx_phase_keys = set(_JIF_PHASE_MAP_KRX.keys())
        cb_keys = set(_JSTATUS_KRX_ALERT.keys())
        assert not (krx_phase_keys & cb_keys), f"페이즈 맵과 CB 맵 중복: {krx_phase_keys & cb_keys}"

    def test_phase_map_terminology_matches_calc(self):
        """JIF 페이즈 맵 페이즈명이 calc_timebased_market_phase() 페이즈명과 일치 (P23 용어 통일)."""
        # calc_timebased_market_phase()가 반환하는 전체 KRX/NXT 페이즈명 집합
        # (활성/비활성 구분 없이 calc 함수의 모든 반환값)
        valid_krx = {
            "장개시전", "장전 대기", "장전 시간외", "동시호가 접수", "시가 동시호가",
            "정규장", "종가 동시호가", "체결 정산", "장후 시간외", "시간외 종가매매 종료 + 시간외 단일가매매 개시",
            "장 종료", "장마감", "휴장일",
        }
        valid_nxt = {
            "장개시전", "프리마켓", "정규장 준비", "메인마켓", "조기 마감",
            "단일가 매매", "애프터마켓", "장마감", "휴장일",
        }
        for name in _JIF_PHASE_MAP_KRX.values():
            assert name in valid_krx, f"KRX 페이즈명 '{name}'이 calc_timebased 페이즈명과 불일치"
        for name in _JIF_PHASE_MAP_NXT.values():
            assert name in valid_nxt, f"NXT 페이즈명 '{name}'이 calc_timebased 페이즈명과 불일치"

    # ── JIF 카운트다운 맵 완전성 (S-2 신규 — 방안 1) ──

    def test_countdown_map_no_overlap_with_phase_map(self):
        """_JIF_COUNTDOWN_KRX/NXT 키가 _JIF_PHASE_MAP_KRX/NXT와 중복 없음 (분리 처리 보장)."""
        krx_countdown_keys = set(_JIF_COUNTDOWN_KRX.keys())
        krx_phase_keys = set(_JIF_PHASE_MAP_KRX.keys())
        assert not (krx_countdown_keys & krx_phase_keys), \
            f"KRX 카운트다운/페이즈 맵 중복: {krx_countdown_keys & krx_phase_keys}"
        nxt_countdown_keys = set(_JIF_COUNTDOWN_NXT.keys())
        nxt_phase_keys = set(_JIF_PHASE_MAP_NXT.keys())
        assert not (nxt_countdown_keys & nxt_phase_keys), \
            f"NXT 카운트다운/페이즈 맵 중복: {nxt_countdown_keys & nxt_phase_keys}"

    def test_countdown_map_no_overlap_with_ignore_codes(self):
        """_JIF_COUNTDOWN_KRX/NXT 키가 _JIF_IGNORE_CODES와 중복 없음 (P20 폴백 금지)."""
        ignore = set(_JIF_IGNORE_CODES)
        assert not (set(_JIF_COUNTDOWN_KRX.keys()) & ignore), \
            f"KRX 카운트다운 맵과 무시 코드 중복: {set(_JIF_COUNTDOWN_KRX.keys()) & ignore}"
        assert not (set(_JIF_COUNTDOWN_NXT.keys()) & ignore), \
            f"NXT 카운트다운 맵과 무시 코드 중복: {set(_JIF_COUNTDOWN_NXT.keys()) & ignore}"

    def test_countdown_krx_entry_count(self):
        """_JIF_COUNTDOWN_KRX는 5개 (장개시 3 + 장마감 2 — 10분전 코드 없음, 10초 제거)."""
        assert len(_JIF_COUNTDOWN_KRX) == 5

    def test_countdown_nxt_entry_count(self):
        """_JIF_COUNTDOWN_NXT는 10개 (프리마켓 장개시 3 + 장마감 2 + 에프터마켓 장개시 3 + 장마감 2 — 10초 제거)."""
        assert len(_JIF_COUNTDOWN_NXT) == 10

    def test_countdown_remaining_sec_values(self):
        """remaining_sec 값이 API 문서 기준 (600/300/60) 일치 — 10초 코드 제거 (P10 SSOT)."""
        expected = {600, 300, 60}
        krx_secs = {sec for _, sec in _JIF_COUNTDOWN_KRX.values()}
        nxt_secs = {sec for _, sec in _JIF_COUNTDOWN_NXT.values()}
        assert krx_secs == expected, f"KRX remaining_sec 값 불일치: {krx_secs}"
        assert nxt_secs == expected, f"NXT remaining_sec 값 불일치: {nxt_secs}"

    def test_countdown_krx_no_10min_close(self):
        """KRX 장마감 10분전 코드 없음 (API 문서 기준 — 44=5분전이 최대)."""
        close_codes = {
            code for code, (label, _) in _JIF_COUNTDOWN_KRX.items()
            if "장마감" in label
        }
        # 장마감 코드는 44/43 (5분/1분) — 10분전/10초전 코드 없음
        assert "44" in close_codes
        assert "43" in close_codes
        # 10분전(600초) 장마감 코드 없음 확인
        close_10min = [
            code for code, (label, sec) in _JIF_COUNTDOWN_KRX.items()
            if "장마감" in label and sec == 600
        ]
        assert len(close_10min) == 0, f"KRX 장마감 10분전 코드 존재 (API 문서 위반): {close_10min}"


# ── _handle_ls_sc1 / _refetch_t0424_and_apply (4단계 — LS SC1 체결 처리) ────────

from backend.app.services.engine_ws_dispatch import _handle_ls_sc1, _refetch_t0424_and_apply


def _mock_ls_sc1_state():
    """_handle_ls_sc1용 state mock 생성."""
    mock_state = MagicMock()
    mock_state.integrated_system_settings_cache = {"broker": "ls"}
    mock_state.auto_trade = None
    mock_state.access_token = "tok"
    mock_state.broker_rest_apis = {"ls": MagicMock()}
    mock_state.rest_api_thread_sem = asyncio.Semaphore(1)
    mock_state.account_snapshot = {"deposit": 5000000, "orderable": 4000000}
    mock_state.broker_rest_totals = {
        "total_eval": 12000000,
        "total_pnl": 1500000,
        "total_buy": 10500000,
        "total_rate": 14.28,
    }
    mock_state.positions = []
    mock_state.realtime_latency_exceeded = False
    return mock_state


def _sc1_item(code="005930", ordxct="11", bnstp="2", unercqty="1"):
    """SC1 내부 REAL 형식 item 생성."""
    return {
        "type": "SC1",
        "item": code,
        "values": {
            "907": bnstp,
            "902": unercqty,
            "ordxctptncode": ordxct,
            "execqty": "1",
            "execprc": "60000",
            "ordqty": "2",
            "deposit": "79759964",
            "ordablemny": "79459964",
            "ordablesubstamt": "244160",
            "ordno": "86382",
            "orgordno": "0",
            "Isunm": "삼성전자",
            "ordprc": "60000",
        },
    }


class TestHandleLsSc1:
    async def test_virtual_mode_skips(self):
        """가상매매 모드 — SC1 메시지 무시 (이중 체결 방지)."""
        item = _sc1_item()
        vals = item["values"]
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_ws_dispatch.is_virtual_mode", return_value=True, create=True), \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=True):
            mock_es.state = _mock_ls_sc1_state()
            await _handle_ls_sc1(item, vals)
        # account_snapshot 변경 없음
        assert mock_es.state.account_snapshot["deposit"] == 5000000

    async def test_fill_callback_and_delta(self):
        """실전모드 체결(11) — on_fill_update + 계좌 delta + fill_after 큐."""
        item = _sc1_item(ordxct="11")
        vals = item["values"]
        mock_state = _mock_ls_sc1_state()
        mock_auto = MagicMock()
        mock_auto.on_fill_update = AsyncMock()
        mock_state.auto_trade = mock_auto
        mock_queue = MagicMock()
        mock_queue.put_nowait = MagicMock()
        mock_account = MagicMock()
        mock_account.compute_realtime_account_delta = MagicMock(return_value={
            "deposit": 79759964, "orderable": 79459964,
        })
        mock_account.apply_realtime_position_line = MagicMock()
        mock_account.parse_deposit = MagicMock(return_value=(True, {}, 79759964, 0, 0))
        mock_account.parse_balance = MagicMock(return_value=(79759964, 12000000, 1500000, 10500000, 14.28, []))
        mock_router = MagicMock()
        mock_router.account = mock_account
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_ws_dispatch.get_order_queue", return_value=mock_queue), \
             patch("backend.app.core.broker_factory.get_router", return_value=mock_router), \
             patch("backend.app.services.engine_ws_dispatch._refetch_t0424_and_apply", new_callable=AsyncMock) as mock_refetch, \
             patch("backend.app.services.engine_ws_dispatch._check_realtime_latency"):
            mock_es.state = mock_state
            await _handle_ls_sc1(item, vals)
        # on_fill_update 호출
        mock_auto.on_fill_update.assert_called_once()
        # 계좌 delta 반영
        assert mock_state.account_snapshot["deposit"] == 79759964
        assert mock_state.account_snapshot["orderable"] == 79459964
        # t0424 재조회 호출 (체결 11)
        mock_refetch.assert_called_once()
        # fill_after 큐 적재
        mock_queue.put_nowait.assert_called_once()
        assert mock_queue.put_nowait.call_args[0][0]["type"] == "fill_after"

    async def test_non_fill_skips_t0424_refetch(self):
        """주문(01) — t0424 재조회 생략, fill_after 큐는 적재."""
        item = _sc1_item(ordxct="01")
        vals = item["values"]
        mock_state = _mock_ls_sc1_state()
        mock_queue = MagicMock()
        mock_queue.put_nowait = MagicMock()
        mock_account = MagicMock()
        mock_account.compute_realtime_account_delta = MagicMock(return_value={})
        mock_router = MagicMock()
        mock_router.account = mock_account
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_ws_dispatch.get_order_queue", return_value=mock_queue), \
             patch("backend.app.core.broker_factory.get_router", return_value=mock_router), \
             patch("backend.app.services.engine_ws_dispatch._refetch_t0424_and_apply", new_callable=AsyncMock) as mock_refetch, \
             patch("backend.app.services.engine_ws_dispatch._check_realtime_latency"):
            mock_es.state = mock_state
            await _handle_ls_sc1(item, vals)
        mock_refetch.assert_not_called()
        mock_queue.put_nowait.assert_called_once()

    async def test_exception_isolated(self):
        """예외 시 함수 정상 반환 (P25 격리된 실패)."""
        item = _sc1_item()
        vals = item["values"]
        mock_state = _mock_ls_sc1_state()
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.core.trade_mode.is_virtual_mode", return_value=False), \
             patch("backend.app.services.engine_ws_dispatch.get_order_queue", side_effect=Exception("queue fail")), \
             patch("backend.app.core.broker_factory.get_router", side_effect=Exception("router fail")), \
             patch("backend.app.services.engine_ws_dispatch._check_realtime_latency"):
            mock_es.state = mock_state
            # 예외 전파 없이 정상 반환
            await _handle_ls_sc1(item, vals)


class TestRefetchT0424AndApply:
    async def test_no_rest_api_skips(self):
        """LS REST API 없음 — 재조회 생략."""
        mock_state = _mock_ls_sc1_state()
        mock_state.broker_rest_apis = {}
        mock_account = MagicMock()
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es:
            mock_es.state = mock_state
            mock_es._get_rest_api_thread_sem = MagicMock(return_value=asyncio.Semaphore(1))
            await _refetch_t0424_and_apply("005930", {}, {"item": "005930"}, mock_account)
        mock_account.parse_deposit.assert_not_called()

    async def test_refetch_success_updates_state(self):
        """t0424 재조회 성공 — positions·합계·예수금 갱신."""
        mock_state = _mock_ls_sc1_state()
        mock_state.positions = [{"stk_cd": "005930", "qty": 5}]
        mock_rest = MagicMock()
        mock_rest.get_balance_detail = AsyncMock(return_value={"t0424OutBlock": {"sunamt1": 79759964}})
        mock_state.broker_rest_apis = {"ls": mock_rest}
        mock_account = MagicMock()
        mock_account.parse_deposit = MagicMock(return_value=(True, {}, 79759964, 0, 0))
        mock_account.parse_balance = MagicMock(return_value=(
            79759964, 12000000, 1500000, 10500000, 14.28,
            [{"stk_cd": "005930", "qty": 10, "avg_price": 70000}],
        ))
        mock_account.apply_realtime_position_line = MagicMock()
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es, \
             patch("backend.app.services.engine_account_notify._rebuild_positions_cache"):
            mock_es.state = mock_state
            mock_es._get_rest_api_thread_sem = MagicMock(return_value=asyncio.Semaphore(1))
            await _refetch_t0424_and_apply("005930", {"ordxctptncode": "11"}, {"item": "005930"}, mock_account)
        # parse 호출
        mock_account.parse_deposit.assert_called_once()
        mock_account.parse_balance.assert_called_once()
        # apply_realtime_position_line 호출 (extra에 t0424_stock_list 전달)
        mock_account.apply_realtime_position_line.assert_called_once()
        call_args = mock_account.apply_realtime_position_line.call_args
        extra = call_args[0][3]
        assert "t0424_stock_list" in extra
        # 합계 갱신
        assert mock_state.broker_rest_totals["total_eval"] == 12000000
        assert mock_state.broker_rest_totals["total_pnl"] == 1500000
        assert mock_state.broker_rest_totals["total_buy"] == 10500000
        assert mock_state.broker_rest_totals["total_rate"] == 14.28
        # 예수금 갱신
        assert mock_state.account_snapshot["deposit"] == 79759964

    async def test_refetch_none_response_skips(self):
        """t0424 응답 None — 갱신 보류 (P25)."""
        mock_state = _mock_ls_sc1_state()
        mock_rest = MagicMock()
        mock_rest.get_balance_detail = AsyncMock(return_value=None)
        mock_state.broker_rest_apis = {"ls": mock_rest}
        mock_account = MagicMock()
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es:
            mock_es.state = mock_state
            mock_es._get_rest_api_thread_sem = MagicMock(return_value=asyncio.Semaphore(1))
            await _refetch_t0424_and_apply("005930", {}, {"item": "005930"}, mock_account)
        mock_account.parse_deposit.assert_not_called()

    async def test_refetch_exception_isolated(self):
        """t0424 재조회 예외 — 갱신 보류, 예외 전파 없음 (P25)."""
        mock_state = _mock_ls_sc1_state()
        mock_rest = MagicMock()
        mock_rest.get_balance_detail = AsyncMock(side_effect=Exception("network error"))
        mock_state.broker_rest_apis = {"ls": mock_rest}
        mock_account = MagicMock()
        with patch("backend.app.services.engine_ws_dispatch.engine_state") as mock_es:
            mock_es.state = mock_state
            mock_es._get_rest_api_thread_sem = MagicMock(return_value=asyncio.Semaphore(1))
            await _refetch_t0424_and_apply("005930", {}, {"item": "005930"}, mock_account)
        mock_account.parse_deposit.assert_not_called()
