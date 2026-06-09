# -*- coding: utf-8 -*-
"""
안전장치 단위 테스트.

PHASE 2 구현 전이므로 이 테스트들은 처음엔 실패(RED)해야 정상.
PHASE 2에서 수정하며 하나씩 통과(GREEN)시킨다.
"""
import time
import pytest
from backend.app.services.engine_state import state as engine_state
from backend.app.services.trading import AutoTradeManager


@pytest.fixture(autouse=True)
def _reset_latency_flag():
    """테스트 간 전역 지연 플래그 오염 방지."""
    engine_state.realtime_latency_exceeded = False
    yield
    engine_state.realtime_latency_exceeded = False


@pytest.mark.asyncio
async def test_latency_gate_blocks_buy_when_exceeded():
    """
    200ms 지연 초과 시 실제 매수 경로(AutoTradeManager.execute_buy)가 차단되는지 검증.

    이 테스트는 가드를 직접 호출하므로, reader/writer 변수가 단절되면(과거 버그)
    '[실시간지연]' 로그가 남지 않아 실패한다 — 즉 단절을 실제로 잡아낸다.
    """
    logs: list[str] = []
    mgr = AutoTradeManager(
        log_callback=logs.append,
        get_settings_fn=lambda: {"trade_mode": "test", "is_auto": True},
    )
    engine_state.realtime_latency_exceeded = True

    result = await mgr.execute_buy("005930", 80000.0, set(), "test_token")

    assert result is False
    assert any("실시간지연" in m for m in logs), f"지연 차단 로그 없음 — 가드 미작동: {logs}"


@pytest.mark.asyncio
async def test_latency_flag_single_source_set_and_recover():
    """
    플래그 단일 소스(원칙 8) 검증: 설정 측(engine_ws_dispatch)과 판단 측(trading)이
    동일한 engine_state.state 인스턴스를 공유하는지 확인.
    """
    from backend.app.services import engine_ws_dispatch

    # 200ms 초과 → 소유자가 플래그 set
    engine_ws_dispatch._check_realtime_latency(int(time.time() * 1000) - 300)
    assert engine_state.realtime_latency_exceeded is True

    # 정상 처리(<200ms) → 소유자가 플래그 해제(회복)
    engine_ws_dispatch._check_realtime_latency(int(time.time() * 1000) - 5)
    assert engine_state.realtime_latency_exceeded is False


def test_circuit_breaker_opens_and_blocks_after_failures():
    """
    연속 주문 실패 N회 후 서킷브레이커가 OPEN되고 이후 요청을 실제로 거부하는지 검증.
    """
    from backend.app.services.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(failure_threshold=3)
    assert cb.allow_request() is True

    for _ in range(3):
        cb.record_failure()

    assert cb.get_state() == "OPEN"
    assert cb.allow_request() is False


def test_risk_manager_buy_blocked_when_breaker_open():
    """
    RiskManager.check_buy_order_allowed가 서킷브레이커 OPEN 시 매수를 거부하는지 검증.
    (trading.py 실거래 경로가 호출하는 바로 그 메서드)
    """
    from backend.app.services.risk_manager import RiskManager
    from backend.app.services.account_manager import AccountManager

    rm = RiskManager(AccountManager())
    _orig_threshold = rm.circuit_breaker.failure_threshold
    try:
        rm.circuit_breaker.failure_threshold = 1
        rm.circuit_breaker.record_failure()

        allowed, reason = rm.check_buy_order_allowed("005930", 80000.0, 1)
        assert allowed is False
        assert "Circuit Breaker" in reason
    finally:
        # 서킷브레이커는 싱글톤이므로 테스트 후 반드시 초기화(오염 방지)
        rm.circuit_breaker.failure_threshold = _orig_threshold
        rm.circuit_breaker.reset()


@pytest.mark.asyncio
async def test_reconciliation_on_startup_skips_in_test_mode():
    """
    테스트모드에서 Reconciliation이 skip되는지 검증.
    테스트모드는 가상잔고이므로 서버 원장 대조 불필요 (원칙 9: 돈 I/O 차이).
    """
    from backend.app.pipelines.pipeline_oms import _reconciliation_on_startup
    from backend.app.services import engine_service as es
    from backend.app.services.core_queues import get_broadcast_queue, initialize_queues
    from backend.app.services.engine_state import state

    # 큐 초기화
    initialize_queues()

    # 테스트모드 설정 (state.integrated_system_settings_cache 직접 수정)
    original_trade_mode = state.integrated_system_settings_cache.get("trade_mode", "real")
    state.integrated_system_settings_cache["trade_mode"] = "test"

    broadcast_queue = get_broadcast_queue()

    try:
        # Reconciliation 호출 (테스트모드이므로 skip되어야 함)
        await _reconciliation_on_startup(es, broadcast_queue)

        # broadcast_queue에서 reconciliation_complete 메시지 확인
        msg = await broadcast_queue.get()
        assert msg["type"] == "reconciliation_complete"
        assert msg["data"]["status"] == "skipped"
        assert "테스트모드" in msg["data"]["message"]
    finally:
        # 원래 값 복원
        state.integrated_system_settings_cache["trade_mode"] = original_trade_mode
