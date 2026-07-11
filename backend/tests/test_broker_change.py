"""증권사 변경 엔진 재기동 경로 단위 테스트 — Phase 1~3 수정 검증.

테스트 항목 (계획서 수정 F):
1. test_reset_broker_session_state_clears_dynamic_flags — 동적 구독 플래그 + 파생 데이터 + sector_summary_cache 초기화
2. test_cancel_all_dynamic_unreg_timers — 타이머 취소 + set 클리어 + 플래그 리셋
3. test_broker_change_sequence_order — stop_engine이 reset_router보다 먼저 실행됨을 검증
4. test_sync_dynamic_subscriptions_after_broker_change — broker 변경 후 DYNAMIC_REG 발행 검증

의존성: state, engine_lifecycle, engine_sector_confirm, engine_service, broker_factory
→ 모두 mock으로 대체 (conftest hang 방지 원칙 준수)
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from backend.app.services.engine_sector_confirm import (
    cancel_all_dynamic_unreg_timers,
    _PENDING_UNREG_TIMERS,
    _UNREG_READY_CODES,
    _UNREG_BATCH_PENDING,
)


# ── 공통 fixture ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_unreg_timers():
    """각 테스트 전후 _PENDING_UNREG_TIMERS / _UNREG_READY_CODES / _UNREG_BATCH_PENDING 초기화."""
    _PENDING_UNREG_TIMERS.clear()
    _UNREG_READY_CODES.clear()
    _UNREG_BATCH_PENDING = False  # _UNREG_BATCH_PENDING은 모듈 레벨 bool — 직접 할당 불가
    yield
    _PENDING_UNREG_TIMERS.clear()
    _UNREG_READY_CODES.clear()


@pytest.fixture(autouse=True)
def _mock_db():
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(side_effect=Exception("DB not available"))
    with patch("backend.app.db.database.get_db_connection", new=AsyncMock(return_value=mock_conn)):
        yield


# ── 1. reset_broker_session_state — 동적 구독 플래그 + 파생 데이터 + sector_summary_cache 초기화 ──

class TestResetBrokerSessionStateClearsDynamicFlags:
    def test_clears_dynamic_subscription_flags(self):
        """reset_broker_session_state 호출 시 master_stocks_cache에서
        _subscribed_dynamic, order_ratio, program_net_buy, _filtered가 제거됨을 검증."""
        from backend.app.services.engine_state import state

        # given: master_stocks_cache에 동적 구독 플래그 + 파생 데이터 존재
        state.master_stocks_cache = {
            "005930": {
                "price": 70000,
                "_subscribed_dynamic": True,
                "order_ratio": 1.5,
                "program_net_buy": 100000,
                "_filtered": True,
            },
            "000660": {
                "price": 120000,
                "_subscribed_dynamic": True,
                "order_ratio": 0.8,
                "program_net_buy": -50000,
                "_filtered": False,
            },
        }
        state.sector_summary_cache = MagicMock(name="old_cache")

        # when: reset_broker_session_state 호출
        with patch("backend.app.services.engine_sector_confirm.cancel_all_dynamic_unreg_timers"):
            from backend.app.services.engine_lifecycle import reset_broker_session_state
            reset_broker_session_state()

        # then: 동적 구독 플래그 + 파생 데이터 제거
        for entry in state.master_stocks_cache.values():
            assert "_subscribed_dynamic" not in entry
            assert "order_ratio" not in entry
            assert "program_net_buy" not in entry
            assert "_filtered" not in entry
            # price 등 일반 데이터는 보존
            assert "price" in entry

    def test_clears_sector_summary_cache(self):
        """reset_broker_session_state 호출 시 sector_summary_cache가 None으로 초기화됨을 검증."""
        from backend.app.services.engine_state import state

        state.master_stocks_cache = {}
        state.sector_summary_cache = MagicMock(name="old_cache")
        assert state.sector_summary_cache is not None

        with patch("backend.app.services.engine_sector_confirm.cancel_all_dynamic_unreg_timers"):
            from backend.app.services.engine_lifecycle import reset_broker_session_state
            reset_broker_session_state()

        assert state.sector_summary_cache is None

    def test_clears_account_and_login_state(self):
        """reset_broker_session_state 호출 시 계좌/로그인 상태가 초기화됨을 검증."""
        from backend.app.services.engine_state import state

        state.master_stocks_cache = {}
        state.sector_summary_cache = None
        state.ws_account_subscribed = True
        state.quote_subscribed = True
        state.ws_connection_status = True
        state.login_ok = True
        state.access_token = "old_token"
        state.positions = [{"code": "005930"}]
        state.account_snapshot = {"balance": 1000000}

        with patch("backend.app.services.engine_sector_confirm.cancel_all_dynamic_unreg_timers"):
            from backend.app.services.engine_lifecycle import reset_broker_session_state
            reset_broker_session_state()

        assert state.ws_account_subscribed is False
        assert state.quote_subscribed is False
        assert state.ws_connection_status is False
        assert state.login_ok is False
        assert state.access_token is None
        assert state.positions == []
        assert state.account_snapshot == {}


# ── 2. cancel_all_dynamic_unreg_timers — 타이머 취소 + set 클리어 ──

class TestCancelAllDynamicUnregTimers:
    def test_cancels_all_pending_timers(self):
        """cancel_all_dynamic_unreg_timers 호출 시 _PENDING_UNREG_TIMERS의 모든 타이머가 취소됨을 검증."""
        import backend.app.services.engine_sector_confirm as mod

        # given: 3개의 가짜 타이머
        timer1 = MagicMock()
        timer2 = MagicMock()
        timer3 = MagicMock()
        mod._PENDING_UNREG_TIMERS.clear()
        mod._PENDING_UNREG_TIMERS["005930"] = timer1
        mod._PENDING_UNREG_TIMERS["000660"] = timer2
        mod._PENDING_UNREG_TIMERS["035420"] = timer3
        mod._UNREG_READY_CODES.add("005930")
        mod._UNREG_READY_CODES.add("000660")
        mod._UNREG_BATCH_PENDING = True

        # when
        cancel_all_dynamic_unreg_timers()

        # then: 모든 타이머 cancel 호출됨
        timer1.cancel.assert_called_once()
        timer2.cancel.assert_called_once()
        timer3.cancel.assert_called_once()
        # set 클리어
        assert len(mod._PENDING_UNREG_TIMERS) == 0
        assert len(mod._UNREG_READY_CODES) == 0
        # 플래그 리셋
        assert mod._UNREG_BATCH_PENDING is False

    def test_empty_state_no_error(self):
        """타이머가 없는 상태에서 호출 시 예외 없이 정상 완료."""
        import backend.app.services.engine_sector_confirm as mod

        mod._PENDING_UNREG_TIMERS.clear()
        mod._UNREG_READY_CODES.clear()
        mod._UNREG_BATCH_PENDING = False

        # when: 예외 없이 호출 가능
        cancel_all_dynamic_unreg_timers()

        # then: 상태 유지 (빈 상태)
        assert len(mod._PENDING_UNREG_TIMERS) == 0
        assert len(mod._UNREG_READY_CODES) == 0
        assert mod._UNREG_BATCH_PENDING is False

    def test_called_from_reset_broker_session_state(self):
        """reset_broker_session_state 호출 시 cancel_all_dynamic_unreg_timers가 호출됨을 검증."""
        from backend.app.services.engine_state import state

        state.master_stocks_cache = {}
        state.sector_summary_cache = None

        with patch("backend.app.services.engine_sector_confirm.cancel_all_dynamic_unreg_timers") as mock_cancel:
            from backend.app.services.engine_lifecycle import reset_broker_session_state
            reset_broker_session_state()

        mock_cancel.assert_called_once()


# ── 3. broker 변경 시 호출 순서 — stop_engine이 reset_router보다 먼저 ──

class TestBrokerChangeSequenceOrder:
    @pytest.mark.asyncio
    async def test_stop_engine_before_reset_router(self):
        """apply_settings_change에서 broker 변경 시
        stop_engine → reset_broker_session_state → reset_router → start_engine 순서 검증."""
        call_order: list[str] = []

        async def fake_stop_engine():
            call_order.append("stop_engine")

        def fake_reset_broker_session_state():
            call_order.append("reset_broker_session_state")

        def fake_reset_router():
            call_order.append("reset_router")

        async def fake_start_engine():
            call_order.append("start_engine")

        # 엔진 실행 중 상태
        with (
            patch("backend.app.services.engine_service.is_engine_running", return_value=True),
            patch("backend.app.services.engine_lifecycle.stop_engine", new=AsyncMock(side_effect=fake_stop_engine)),
            patch("backend.app.services.engine_lifecycle.reset_broker_session_state", side_effect=fake_reset_broker_session_state),
            patch("backend.app.services.engine_lifecycle.start_engine", new=AsyncMock(side_effect=fake_start_engine)),
            patch("backend.app.core.broker_factory.reset_router", side_effect=fake_reset_router),
            patch("backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache", new=AsyncMock()),
            patch("backend.app.services.engine_account_notify.notify_desktop_header_refresh", new=AsyncMock()),
            patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new=AsyncMock()),
        ):
            from backend.app.services.engine_service import apply_settings_change
            await apply_settings_change({"broker"})

        # 순서 검증: stop_engine → reset_broker_session_state → reset_router → start_engine
        assert call_order == ["stop_engine", "reset_broker_session_state", "reset_router", "start_engine"]

    @pytest.mark.asyncio
    async def test_reset_router_only_when_engine_not_running(self):
        """엔진 미실행 시 reset_router만 호출되고 stop_engine/start_engine은 호출되지 않음."""
        async def fake_stop_engine():
            pytest.fail("stop_engine should not be called when engine is not running")

        async def fake_start_engine():
            pytest.fail("start_engine should not be called when engine is not running")

        reset_router_called = MagicMock()

        with (
            patch("backend.app.services.engine_service.is_engine_running", return_value=False),
            patch("backend.app.services.engine_lifecycle.stop_engine", new=AsyncMock(side_effect=fake_stop_engine)),
            patch("backend.app.services.engine_lifecycle.start_engine", new=AsyncMock(side_effect=fake_start_engine)),
            patch("backend.app.core.broker_factory.reset_router", side_effect=reset_router_called),
            patch("backend.app.services.engine_service.refresh_engine_integrated_system_settings_cache", new=AsyncMock()),
            patch("backend.app.services.engine_account_notify.notify_desktop_header_refresh", new=AsyncMock()),
            patch("backend.app.services.engine_account_notify.notify_desktop_settings_toggled", new=AsyncMock()),
        ):
            from backend.app.services.engine_service import apply_settings_change
            await apply_settings_change({"broker"})

        reset_router_called.assert_called_once()


# ── 4. sync_dynamic_subscriptions — broker 변경 후 DYNAMIC_REG 발행 ──

class TestSyncDynamicSubscriptionsAfterBrokerChange:
    def test_sync_dynamic_subscriptions_issues_dynamic_reg(self):
        """sync_dynamic_subscriptions 호출 시 신규 구독 종목에 대해 DYNAMIC_REG 이벤트가 큐에 발행됨을 검증."""
        from backend.app.services.engine_state import state
        from backend.app.services.engine_sector_confirm import sync_dynamic_subscriptions

        # given: WS 연결 + 로그인 OK + buy_targets에 guard_pass 종목 존재
        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        state.connector_manager = mock_ws
        state.login_ok = True
        state.master_stocks_cache = {}  # _subscribed_dynamic 없음 → 전부 신규 구독

        mock_target = MagicMock()
        mock_target.stock.code = "005930"
        mock_target.stock.guard_pass = True
        buy_targets = [mock_target]

        mock_queue = MagicMock()
        mock_queue.put_nowait = MagicMock()

        with (
            patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue),
            patch("backend.app.services.engine_sector_confirm.asyncio.get_running_loop", side_effect=RuntimeError("no loop")),
        ):
            sync_dynamic_subscriptions(buy_targets)

        # then: DYNAMIC_REG 이벤트 발행됨
        # put_nowait 인자: (priority, timestamp, payload) 튜플
        assert mock_queue.put_nowait.called
        queued_item = mock_queue.put_nowait.call_args[0][0]
        payload_arg = queued_item[2]  # 세 번째 요소 = payload dict
        assert payload_arg["type"] == "DYNAMIC_REG"
        assert "005930" in payload_arg["payload"]["codes"]
        assert "0D" in payload_arg["payload"]["types"]
        assert "PGM" in payload_arg["payload"]["types"]

    def test_sync_dynamic_subscriptions_skips_when_ws_not_connected(self):
        """WS 미연결 시 sync_dynamic_subscriptions가 이벤트를 발행하지 않음을 검증."""
        from backend.app.services.engine_state import state
        from backend.app.services.engine_sector_confirm import sync_dynamic_subscriptions

        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = False
        state.connector_manager = mock_ws
        state.login_ok = True

        mock_target = MagicMock()
        mock_target.stock.code = "005930"
        mock_target.stock.guard_pass = True

        mock_queue = MagicMock()
        with patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            sync_dynamic_subscriptions([mock_target])

        # WS 미연결 → 큐 발행 없음
        mock_queue.put_nowait.assert_not_called()

    def test_sync_dynamic_subscriptions_skips_when_not_logged_in(self):
        """로그인 미완료 시 sync_dynamic_subscriptions가 이벤트를 발행하지 않음을 검증."""
        from backend.app.services.engine_state import state
        from backend.app.services.engine_sector_confirm import sync_dynamic_subscriptions

        mock_ws = MagicMock()
        mock_ws.is_connected.return_value = True
        state.connector_manager = mock_ws
        state.login_ok = False  # 로그인 미완료

        mock_target = MagicMock()
        mock_target.stock.code = "005930"
        mock_target.stock.guard_pass = True

        mock_queue = MagicMock()
        with patch("backend.app.services.core_queues.get_control_queue", return_value=mock_queue):
            sync_dynamic_subscriptions([mock_target])

        mock_queue.put_nowait.assert_not_called()
