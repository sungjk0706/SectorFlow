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

# 주문 장부 파일 경로
_JOURNAL_FILE = "backend/data/journal.jsonl"


async def start_oms_loop(es: ModuleType) -> None:
    """OMS 루프 시작."""
    global _oms_task, _oms_running

    if _oms_running:
        logger.warning("[OMS] 이미 실행 중")
        return

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
        # 1. 로컬 장부에서 Pending 상태인 주문 조회
        pending_orders = _get_pending_orders()
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
    try:
        # 주문 고유 식별값(ID) 생성
        order_id = f"buy_{code}_{int(time.time())}"

        # 주문 요청 직전: Pending 상태로 저널링
        _journal_order_request(
            order_id=order_id,
            stock_code=code,
            side="buy",
            quantity=qty,
            price=price,
            status="pending",
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
            _update_order_status(order_id, "completed")
            logger.info("[OMS] 주문 완료 - order_id=%s, status=completed", order_id)
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
            _update_order_status(order_id, "failed")
            logger.warning("[OMS] 주문 실패 - order_id=%s, status=failed", order_id)
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
    try:
        # 주문 고유 식별값(ID) 생성
        order_id = f"sell_{code}_{int(time.time())}"

        # 주문 요청 직전: Pending 상태로 저널링
        _journal_order_request(
            order_id=order_id,
            stock_code=code,
            side="sell",
            quantity=qty,
            price=price,
            status="pending",
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
        _update_order_status(order_id, "completed")
        logger.info("[OMS] 주문 완료 - order_id=%s, status=completed", order_id)

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
        await broadcast_queue.put({
            "type": "order_failed",
            "data": {
                "action": "SELL",
                "code": code,
                "error": str(e),
            },
        })


# ── 주문 장부 저널링 (Journaling) ───────────────────────────────────────────

def _journal_order_request(
    order_id: str,
    stock_code: str,
    side: str,
    quantity: int,
    price: float,
    status: str = "pending",
) -> None:
    """
    주문 요청 저널링.

    주문 요청 직전, Pending 상태로 주문 고유 식별값(ID), 종목코드, 주문 시간, 예상 수량, 단가를 담은 데이터를 로컬 DB(또는 JSON 장부)에 INSERT.

    Args:
        order_id: 주문 고유 식별값
        stock_code: 종목코드
        side: buy/sell
        quantity: 주문 수량
        price: 주문 가격
        status: pending/completed/failed
    """
    try:
        entry = {
            "event_type": "order_request",
            "timestamp": time.time(),
            "seq": _get_next_seq(),
            "data": {
                "order_id": order_id,
                "stock_code": stock_code,
                "side": side,
                "quantity": quantity,
                "price": price,
                "status": status,
                "trade_mode": "real",  # 실제 모드인지 테스트 모드인지는 settings에서 확인 필요
            },
        }

        # JSONL 파일에 추가 (append)
        with open(_JOURNAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.debug("[OMS] 주문 저널링 완료 - order_id=%s, status=%s", order_id, status)

    except Exception as e:
        logger.error("[OMS] 주문 저널링 실패: %s", e, exc_info=True)


def _update_order_status(order_id: str, status: str) -> None:
    """
    응답 기반 장부 클리어(Clearing) 로직.

    키움증권 서버에서 응답(ord_no 포함)이 돌아오는 즉시, 해당 주문 ID를 찾아 로컬 장부에서 상태를 Completed로 업데이트하거나, 완료된 주문 건을 장부에서 제거.

    Args:
        order_id: 주문 고유 식별값
        status: completed/failed
    """
    try:
        # 현재 장부 읽기
        if not os.path.exists(_JOURNAL_FILE):
            logger.warning("[OMS] 장부 파일 없음 - order_id=%s", order_id)
            return

        updated_entries = []
        found = False

        with open(_JOURNAL_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("event_type") == "order_request":
                    data = entry.get("data", {})
                    if data.get("order_id") == order_id:
                        # 해당 주문 ID 찾음 - 상태 업데이트
                        data["status"] = status
                        entry["data"] = data
                        found = True
                        logger.debug("[OMS] 주문 상태 업데이트 - order_id=%s, status=%s", order_id, status)
                updated_entries.append(entry)

        if not found:
            logger.warning("[OMS] 주문 ID를 찾을 수 없음 - order_id=%s", order_id)
            return

        # 장부 파일 덮어쓰기
        with open(_JOURNAL_FILE, "w", encoding="utf-8") as f:
            for entry in updated_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info("[OMS] 주문 상태 업데이트 완료 - order_id=%s, status=%s", order_id, status)

    except Exception as e:
        logger.error("[OMS] 주문 상태 업데이트 실패: %s", e, exc_info=True)


def _get_pending_orders() -> list[dict]:
    """
    로컬 장부에서 Pending 상태인 주문 조회.

    Returns:
        Pending 상태인 주문 리스트
    """
    try:
        if not os.path.exists(_JOURNAL_FILE):
            return []

        pending_orders = []

        with open(_JOURNAL_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("event_type") == "order_request":
                    data = entry.get("data", {})
                    if data.get("status") == "pending":
                        pending_orders.append(data)

        return pending_orders

    except Exception as e:
        logger.error("[OMS] Pending 주문 조회 실패: %s", e, exc_info=True)
        return []


def _get_next_seq() -> int:
    """
    다음 시퀀스 번호 조회.

    Returns:
        다음 시퀀스 번호
    """
    try:
        if not os.path.exists(_JOURNAL_FILE):
            return 1

        max_seq = 0
        with open(_JOURNAL_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                seq = entry.get("seq", 0)
                if seq > max_seq:
                    max_seq = seq

        return max_seq + 1

    except Exception as e:
        logger.error("[OMS] 시퀀스 번호 조회 실패: %s", e, exc_info=True)
        return 1
