# -*- coding: utf-8 -*-
"""
주문 실행 루프 (Order Execution Loop) - 시세/업종 루프에서 주문·체결·잔고 처리를 분리.

order_queue에서 주문 실행 요청을 꺼내 순차 처리:
- {type: "sell_check", codes: [...]} → 보유종목 매도 조건 검사 (check_sell_conditions)
- {type: "buy_evaluate"} → 매수 후보 평가 (evaluate_buy_candidates)

시세 처리 루프·업종 재계산 루프가 주문 실행(체결 대기 0.5초+)에 블록되지 않도록
주문 요청을 큐에 넣고 즉시 다음 처리로 넘어가며, 본 루프가 큐에서 순차 소비.
예외 시 개별 요청 격리 (에러 로깅 + continue).
"""
from __future__ import annotations
from typing import Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

# ── 주문 실행 루프 상태 ───────────────────────────────────────────────────────
_order_task: Optional[asyncio.Task] = None
_order_running: bool = False

# 루프 대기 timeout — stop 신호 감지용 (요청 없을 때 주기적으로 루프 조건 재확인)
_ORDER_LOOP_TIMEOUT = 1.0


async def _order_loop_impl() -> None:
    """주문 실행 루프 구현 — order_queue에서 요청을 꺼내 타입별 분기 처리."""
    from backend.app.services.core_queues import get_order_queue
    from backend.app.services.engine_state import state

    order_queue = get_order_queue()

    while _order_running:
        try:
            try:
                request = await asyncio.wait_for(
                    order_queue.get(), timeout=_ORDER_LOOP_TIMEOUT
                )
            except asyncio.TimeoutError:
                # 요청 없음 — stop 신호 감지 후 재대기
                await asyncio.sleep(0)
                continue

            req_type = request.get("type") if isinstance(request, dict) else None

            try:
                if req_type == "sell_check":
                    await _handle_sell_check(request, state)
                elif req_type == "buy_evaluate":
                    await _handle_buy_evaluate(state)
                else:
                    logger.warning("[주문루프] 알 수 없는 요청 타입 — 드롭: %s", request)
            except Exception as e:
                # W9 격리된 실패 — 개별 요청 예외가 루프 전체 중단 유도 금지
                logger.error("[주문루프] 주문 요청 처리 오류 (계속): %s", e, exc_info=True)

            try:
                order_queue.task_done()
            except ValueError:
                # task_done 카운터 불일치 시 무시 (격리된 실패)
                pass

            # W1 — 이벤트 루프 양보
            await asyncio.sleep(0)

        except asyncio.CancelledError:
            logger.info("[주문루프] 취소 신호 수신 — 종료")
            raise
        except Exception as e:
            # 루프 프레임 자체 예외 — 로깅 후 계속 (W9)
            logger.error("[주문루프] 루프 프레임 오류 (계속): %s", e, exc_info=True)
            await asyncio.sleep(0)


async def _handle_sell_check(request: dict, state) -> None:
    """매도 조건 검사 요청 처리 — codes(기준 종목코드) → 보유종목 변환 후 check_sell_conditions 호출.

    1단계에서는 큐에 put하는 지점이 없으므로 본 분기는 실행되지 않음.
    2단계에서 시세 루프가 order_queue에 {type:"sell_check", codes:[nk_px]}를 put하면 호출됨.
    """
    from backend.app.core.trade_mode import is_test_mode
    from backend.app.services import dry_run
    from backend.app.services.auto_trading_effective import auto_sell_effective
    from backend.app.services.engine_symbol_utils import _base_stk_cd

    codes = request.get("codes") or []
    if not (state.auto_trade and auto_sell_effective(state.integrated_system_settings_cache) and state.access_token):
        return

    for nk_px in codes:
        if is_test_mode(state.integrated_system_settings_cache):
            _pos = await dry_run.get_position(nk_px)
            if _pos:
                await state.auto_trade.check_sell_conditions(
                    [_pos], state.integrated_system_settings_cache, state.access_token
                )
        else:
            _matched = [
                p for p in state.positions
                if _base_stk_cd(str(p.get("stk_cd", "") or "")) == nk_px
            ]
            if _matched:
                await state.auto_trade.check_sell_conditions(
                    _matched, state.integrated_system_settings_cache, state.access_token
                )


async def _handle_buy_evaluate(state) -> None:
    """매수 후보 평가 요청 처리 — evaluate_buy_candidates 호출.

    1단계에서는 큐에 put하는 지점이 없으므로 본 분기는 실행되지 않음.
    3단계에서 업종 루프·잔고 회복 이벤트가 order_queue에 {type:"buy_evaluate"}를 put하면 호출됨.
    """
    from backend.app.services.buy_order_executor import evaluate_buy_candidates

    await evaluate_buy_candidates()


async def start_order_loop() -> None:
    """주문 실행 루프 시작 (엔진 기동 시 호출)."""
    global _order_task, _order_running

    if _order_running:
        logger.warning("[주문루프] 이미 실행 중")
        return

    _order_running = True
    _order_task = asyncio.get_running_loop().create_task(_order_loop_impl())
    _order_task.add_done_callback(_on_order_loop_done)
    logger.info("[주문루프] 시작")


def _on_order_loop_done(task: asyncio.Task) -> None:
    """주문 루프 종료 콜백 — cancel된 경우 CancelledError 무시, 실제 예외만 로깅."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("[주문루프] 루프 작업 실패: %s", exc)


async def stop_order_loop() -> None:
    """주문 실행 루프 종료 (엔진 정지 시 호출)."""
    global _order_running, _order_task

    _order_running = False
    if _order_task:
        _order_task.cancel()
        try:
            await _order_task
        except asyncio.CancelledError:
            pass
        _order_task = None
    logger.info("[주문루프] 종료")
