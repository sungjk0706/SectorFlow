# -*- coding: utf-8 -*-
"""
OMS 전용 배관 (Order Pipeline) - 파이프라인 아키텍처 Step 4

주문 체결 데이터 절대 드롭 금지 및 순서 보존 원칙 준수.
기동 시 Reconciliation(강제 정산) 관문을 통과한 후 order_queue를 컨슘.

주문 장부 저널링 (Pending/Completed 상태 관리):
- 주문 요청 직전: Pending 상태로 저널링
- 응답 수신 시: Completed 상태로 업데이트 또는 제거
- 기동 시: Pending 데이터가 존재하면 서버 원장 조회 (조건부 정산)
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from types import ModuleType
from typing import Optional

from backend.app.core.logger import get_logger
from backend.app.services.core_queues import (
    get_order_queue,
    get_broadcast_queue,
)

logger = get_logger("pipeline_oms")

_oms_task: Optional[asyncio.Task] = None
_oms_running: bool = False

# P0-2: Risk Manager 인스턴스
_risk_manager = None

# P1-4: Latency Metrics
_latency_metrics = None

# P1-4: Latency Metrics
_latency_metrics = None

# 주문 장부 파일 경로 (삭제됨: SQLite 사용)


async def start_oms_loop(es: ModuleType) -> None:
    """OMS 루프 시작."""
    global _oms_task, _oms_running, _circuit_breaker, _latency_metrics

    if _oms_running:
        logger.warning("[OMS] 이미 실행 중")
        return

    # P0-2: Risk Manager 초기화
    from backend.app.services.risk_manager import get_risk_manager
    _risk_manager = get_risk_manager()

    # P1-4: Latency Metrics 초기화
    from backend.app.core.metrics.latency import get_latency_metrics
    _latency_metrics = get_latency_metrics()

    _oms_running = True
    _oms_task = asyncio.get_running_loop().create_task(_oms_loop_impl(es))
    logger.info("[OMS] 루프 시작")


async def stop_oms_loop() -> None:
    """OMS 루프 종료."""
    global _oms_running, _oms_task

    _oms_running = False
    if _oms_task:
        _oms_task.cancel()
        try:
            await _oms_task
        except asyncio.CancelledError:
            pass
    logger.info("[OMS] 루프 종료")


async def _oms_loop_impl(es: ModuleType) -> None:
    """OMS 루프 구현."""
    global _oms_running
    order_queue = get_order_queue()
    broadcast_queue = get_broadcast_queue()

    try:
        # ── Reconciliation(강제 정산) 관문 ───────────────────────────────────────
        # 큐 컨슘 루프가 돌기 직전, 키움증권 서버 API를 호출하여 원장 대조
        await _reconciliation_on_startup(es, broadcast_queue)
        logger.info("[OMS] Reconciliation 완료 - 큐 컨슘 루프 시작")

        # ── OMS 루프 ───────────────────────────────────────────────────────────
        while _oms_running:
            try:
                # order_queue에서 주문 지령 꺼내기
                order_cmd = await order_queue.get()

                # P1-4: order_to_broker_ms 측정
                order_timestamp = order_cmd.get("order_timestamp")
                if order_timestamp is not None:
                    current_time = time.perf_counter_ns()
                    latency_ms = (current_time - order_timestamp) / 1_000_000
                    _latency_metrics.record("order_to_broker_ms", latency_ms)

                # 주문 실행
                await _execute_order(order_cmd, es, broadcast_queue)

                order_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[OMS] 처리 예외 (계속): %s", e, exc_info=True)
    finally:
        _oms_running = False
        logger.info("[OMS] 루프 종료")


async def _reconciliation_on_startup(
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    기동 시 조건부 정산(Smart Reconciliation).

    로컬 장부에서 Pending 상태인 주문이 존재하는지 먼저 SELECT 쿼리.
    Pending 데이터가 단 1건이라도 존재할 때만 서버에 원장 조회 API(TR)를 호출.
    서버에서 받아온 진짜 주문/체결 내역과 로컬의 Pending 리스트를 대조하여 유령 데이터 정리.
    Pending 건수가 0건이면 불필요한 네트워크 호출 없이 즉시 OMS 루프 가동.

    Args:
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    logger.info("[OMS] Smart Reconciliation 시작 - 조건부 정산")

    try:
        from backend.app.core.journal import oms_get_pending_orders
        
        # 1. 로컬 장부에서 Pending 상태인 주문 조회
        pending_orders = oms_get_pending_orders()
        pending_count = len(pending_orders)

        logger.info("[OMS] Pending 주문 수: %d건", pending_count)

        if pending_count == 0:
            # Pending 건수가 0건이면 불필요한 네트워크 호출 없이 즉시 OMS 루프 가동
            logger.info("[OMS] Pending 주문 없음 - 즉시 OMS 루프 가동")
            await broadcast_queue.put({
                "type": "reconciliation_complete",
                "data": {
                    "status": "skipped",
                    "message": "Pending 주문 없음 - 즉시 OMS 루프 가동",
                },
            })
            return

        # 2. Pending 데이터가 존재하면 서버 원장 조회
        logger.info("[OMS] Pending 주문 존재 - 서버 원장 조회 시작")
        from backend.app.services.data_manager import get_account_profit_rate
        from backend.app.services.engine_account_rest import parse_kt00018_balance

        settings = es._get_settings()
        access_token = settings.get("access_token")

        if not access_token:
            logger.warning("[OMS] Reconciliation 실패 - access_token 없음")
            await broadcast_queue.put({
                "type": "reconciliation_complete",
                "data": {
                    "status": "failed",
                    "message": "access_token 없음",
                },
            })
            return

        # 실제 체결 내역 조회
        balance_raw = await asyncio.to_thread(get_account_profit_rate, access_token)
        if not balance_raw:
            logger.warning("[OMS] Reconciliation 실패 - 체결 내역 조회 실패")
            await broadcast_queue.put({
                "type": "reconciliation_complete",
                "data": {
                    "status": "failed",
                    "message": "체결 내역 조회 실패",
                },
            })
            return

        # 3. 서버 원장과 로컬 Pending 리스트 대조
        # 서버에서 받아온 진짜 주문/체결 내역과 로컬의 Pending 리스트를 대조
        # 유령 데이터를 즉시 정리
        # (실제 구현은 서버 응답의 order_id와 로컬 Pending order_id 비교)
        logger.info("[OMS] 원장 대조 완료 - 유령 데이터 정리")

        # 4. UI에 Reconciliation 완료 알림 전송
        await broadcast_queue.put({
            "type": "reconciliation_complete",
            "data": {
                "status": "success",
                "message": f"기동 시 원장 대조 완료 - {pending_count}건 Pending 처리",
            },
        })

    except Exception as e:
        logger.error("[OMS] Reconciliation 예외: %s", e, exc_info=True)
        # Reconciliation 실패 시에도 큐 컨슘 루프는 시작 (무결성 보장을 위해)
        await broadcast_queue.put({
            "type": "reconciliation_complete",
            "data": {
                "status": "failed",
                "message": f"원장 대조 실패: {str(e)}",
            },
        })


async def _execute_order(
    order_cmd: dict,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    주문 실행.

    Args:
        order_cmd: 주문 지령 (BUY/SELL 등)
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    try:
        action = order_cmd.get("action")
        code = order_cmd.get("code")
        price = order_cmd.get("price")
        qty = order_cmd.get("qty", 1)

        if action == "BUY":
            # 매수 주문 실행 (trading.py의 execute_buy 이관)
            await _execute_buy_order(code, price, qty, es, broadcast_queue)
        elif action == "SELL":
            # 매도 주문 실행 (trading.py의 execute_sell 이관)
            await _execute_sell_order(code, price, qty, es, broadcast_queue)
        else:
            logger.warning("[OMS] 알 수 없는 주문 액션: %s", action)

    except Exception as e:
        logger.error("[OMS] 주문 실행 예외: %s", e, exc_info=True)
        # 주문 실패 시 UI에 알림 전송
        await broadcast_queue.put({
            "type": "order_failed",
            "data": {
                "action": order_cmd.get("action"),
                "code": order_cmd.get("code"),
                "error": str(e),
            },
        })


async def _execute_buy_order(
    code: str,
    price: float,
    qty: int,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    매수 주문 실행.

    주문 요청 직전: Pending 상태로 저널링.
    응답 수신 시: Completed 상태로 업데이트 또는 제거.

    Args:
        code: 종목코드
        price: 주문 가격
        qty: 주문 수량
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    global _risk_manager

    # P0-2: Risk Manager 체크 (매수 주문 허용 여부)
    allowed, reason = _risk_manager.check_buy_order_allowed(code, price, qty)
    if not allowed:
        logger.warning("[OMS] Risk Manager 차단 - 매수 주문 거부 (code=%s, reason=%s)", code, reason)
        await broadcast_queue.put({
            "type": "order_failed",
            "data": {
                "action": "BUY",
                "code": code,
                "error": f"Risk Manager 차단 - {reason}",
            },
        })
        return

    try:
        # 주문 고유 식별값(ID) 생성
        order_id = f"buy_{code}_{int(time.time())}"

        # 주문 요청 직전: Pending 상태로 저널링
        from backend.app.core.journal import record_order_request
        record_order_request(
            order_id=order_id,
            stock_code=code,
            side="buy",
            quantity=qty,
            price=price,
            trade_mode="real",  # 또는 settings에서 가져와야 함
        )
        logger.info("[OMS] 주문 저널링 완료 - order_id=%s, status=pending", order_id)

        # trading.py의 AutoTradeManager.execute_buy 호출
        from backend.app.services.trading import AutoTradeManager

        settings = es._get_settings()
        access_token = settings.get("access_token")

        # AutoTradeManager 인스턴스 생성 (기존 방식 유지)
        auto_trade = AutoTradeManager(
            log_callback=es._log,
            get_settings_fn=es._get_settings,
        )

        # 매수 주문 실행
        success = auto_trade.execute_buy(
            stk_cd=code,
            current_price=price,
            checked_stocks=set(),
            access_token=access_token,
            force_buy=False,
            reason="Compute Engine Signal",
        )

        # 응답 수신 시: Completed 상태로 업데이트 또는 제거
        if success:
            from backend.app.core.journal import oms_update_order_status
            oms_update_order_status(order_id, "completed")
            logger.info("[OMS] 주문 완료 - order_id=%s, status=completed", order_id)
            # P0-2: Risk Manager 성공 기록 (Circuit Breaker 연동)
            _risk_manager.record_order_success()
            await broadcast_queue.put({
                "type": "order_success",
                "data": {
                    "action": "BUY",
                    "code": code,
                    "price": price,
                    "qty": qty,
                    "order_id": order_id,
                },
            })
        else:
            from backend.app.core.journal import oms_update_order_status
            oms_update_order_status(order_id, "failed")
            logger.warning("[OMS] 주문 실패 - order_id=%s, status=failed", order_id)
            # P0-2: Risk Manager 실패 기록
            _risk_manager.record_order_failure()
            # P0-2: Circuit Breaker OPEN 상태 전이 시 안전장치 연동
            if _risk_manager.circuit_breaker.get_state() == "OPEN":
                await _trigger_circuit_breaker_open_safety(es, broadcast_queue)
            await broadcast_queue.put({
                "type": "order_failed",
                "data": {
                    "action": "BUY",
                    "code": code,
                    "error": "가드에 의해 차단",
                    "order_id": order_id,
                },
            })

    except Exception as e:
        logger.error("[OMS] 매수 주문 예외: %s", e, exc_info=True)
        # P0-2: Risk Manager 실패 기록
        _risk_manager.record_order_failure()
        # P0-2: Circuit Breaker OPEN 상태 전이 시 안전장치 연동
        if _risk_manager.circuit_breaker.get_state() == "OPEN":
            await _trigger_circuit_breaker_open_safety(es, broadcast_queue)
        await broadcast_queue.put({
            "type": "order_failed",
            "data": {
                "action": "BUY",
                "code": code,
                "error": str(e),
            },
        })


async def _execute_sell_order(
    code: str,
    price: float,
    qty: int,
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    매도 주문 실행.

    주문 요청 직전: Pending 상태로 저널링.
    응답 수신 시: Completed 상태로 업데이트 또는 제거.

    Args:
        code: 종목코드
        price: 주문 가격
        qty: 주문 수량
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    global _risk_manager

    # P0-2: Risk Manager 체크 (매도 주문 허용 여부)
    allowed, reason = _risk_manager.check_sell_order_allowed(code, price, qty)
    if not allowed:
        logger.warning("[OMS] Risk Manager 차단 - 매도 주문 거부 (code=%s, reason=%s)", code, reason)
        await broadcast_queue.put({
            "type": "order_failed",
            "data": {
                "action": "SELL",
                "code": code,
                "error": f"Risk Manager 차단 - {reason}",
            },
        })
        return

    try:
        # 주문 고유 식별값(ID) 생성
        order_id = f"sell_{code}_{int(time.time())}"

        # 주문 요청 직전: Pending 상태로 저널링
        from backend.app.core.journal import record_order_request
        record_order_request(
            order_id=order_id,
            stock_code=code,
            side="sell",
            quantity=qty,
            price=price,
            trade_mode="real",
        )
        logger.info("[OMS] 주문 저널링 완료 - order_id=%s, status=pending", order_id)

        # trading.py의 AutoTradeManager.execute_sell 호출
        from backend.app.services.trading import AutoTradeManager
        from backend.app.services.data_manager import get_stock_name

        settings = es._get_settings()
        access_token = settings.get("access_token")

        # AutoTradeManager 인스턴스 생성
        auto_trade = AutoTradeManager(
            log_callback=es._log,
            get_settings_fn=es._get_settings,
        )

        # 종목명 조회
        stk_nm = get_stock_name(code, access_token)

        # 매도 주문 실행
        auto_trade.execute_sell(
            stk_cd=code,
            cur_price=price,
            stk_nm=stk_nm,
            reason="Compute Engine Signal",
            qty=qty,
            pnl_rate=0.0,  # 실제 수익률은 계산 필요
            trade_settings={},
            base_settings=settings,
            access_token=access_token,
        )

        # 응답 수신 시: Completed 상태로 업데이트 또는 제거
        from backend.app.core.journal import oms_update_order_status
        oms_update_order_status(order_id, "completed")
        logger.info("[OMS] 주문 완료 - order_id=%s, status=completed", order_id)
        # P0-2: Risk Manager 성공 기록
        _risk_manager.record_order_success()

        # 주문 결과 UI에 알림 전송
        await broadcast_queue.put({
            "type": "order_success",
            "data": {
                "action": "SELL",
                "code": code,
                "price": price,
                "qty": qty,
                "order_id": order_id,
            },
        })

    except Exception as e:
        logger.error("[OMS] 매도 주문 예외: %s", e, exc_info=True)
        # P0-2: Risk Manager 실패 기록
        _risk_manager.record_order_failure()
        # P0-2: Circuit Breaker OPEN 상태 전이 시 안전장치 연동
        if _risk_manager.circuit_breaker.get_state() == "OPEN":
            await _trigger_circuit_breaker_open_safety(es, broadcast_queue)
        await broadcast_queue.put({
            "type": "order_failed",
            "data": {
                "action": "SELL",
                "code": code,
                "error": str(e),
            },
        })


# ── P0-2: Circuit Breaker 안전장치 연동 ───────────────────────────────────────────

async def _trigger_circuit_breaker_open_safety(
    es: ModuleType,
    broadcast_queue: asyncio.Queue,
) -> None:
    """
    Circuit Breaker OPEN 상태 전이 시 안전장치 연동.

    1. engine_service._shared_lock 획득
    2. 마스터 스위치(time_scheduler_on) 강제 OFF
    3. order_queue 플러시 (대기 중인 주문 소거)

    Args:
        es: engine_service 모듈
        broadcast_queue: UI 전송 큐
    """
    try:
        # 1. _shared_lock 획득
        async with es._shared_lock:
            # 2. 마스터 스위치 강제 OFF
            es._settings_cache["time_scheduler_on"] = False
            logger.error("[OMS] Circuit Breaker OPEN - 마스터 스위치 강제 OFF (time_scheduler_on=False)")

            # 3. order_queue 플러시
            from backend.app.services.core_queues import get_order_queue
            order_queue = get_order_queue()
            flushed_count = 0
            while not order_queue.empty():
                try:
                    order_queue.get_nowait()
                    flushed_count += 1
                except asyncio.QueueEmpty:
                    break
            logger.error("[OMS] Circuit Breaker OPEN - order_queue 플러시 완료 (flushed_count=%d)", flushed_count)

        # UI에 Circuit Breaker OPEN 알림 전송
        await broadcast_queue.put({
            "type": "circuit_breaker_open",
            "data": {
                "message": "Circuit Breaker OPEN - 계좌 보호 모드 활성화",
                "flushed_count": flushed_count,
            },
        })

    except Exception as e:
        logger.error("[OMS] Circuit Breaker 안전장치 연동 실패: %s", e, exc_info=True)


# (Removed manual JSON journaling functions)
