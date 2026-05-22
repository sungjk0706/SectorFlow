# -*- coding: utf-8 -*-
"""
전역 이벤트 버스 (Queues) - 파이프라인 아키텍처 핵심 배관

HTS급 실시간 처리를 위한 4개 코어 큐:
- tick_queue: 시세 수신 전용 (드롭 정책 적용)
- order_queue: 주문/체결 전용 (무결성 보장)
- broadcast_queue: UI 프론트엔드 전송 전용
- control_queue: 사용자 설정 제어 전용 (최우선순위)

외부 브로커(Redis 등) 미사용 - 순수 asyncio.Queue 기반 프로세스 내 배관.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from backend.app.core.logger import get_logger

logger = get_logger("core_queues")


# ── 큐 크기 설정 ─────────────────────────────────────────────────────────────
TICK_QUEUE_MAXSIZE = 5000  # 시세 수신 전용 (드롭 정책 적용)
ORDER_QUEUE_MAXSIZE = 1000  # 주문/체결 전용 (무결성 보장, 드롭 미적용)
BROADCAST_QUEUE_MAXSIZE = 2000  # UI 전송 전용
CONTROL_QUEUE_MAXSIZE = 500  # 제어 전용 (최우선순위)


# ── 전역 큐 인스턴스 ───────────────────────────────────────────────────────────
_tick_queue: Optional[asyncio.Queue] = None
_order_queue: Optional[asyncio.Queue] = None
_broadcast_queue: Optional[asyncio.Queue] = None
_control_queue: Optional[asyncio.Queue] = None


def initialize_queues() -> None:
    """전역 큐 인스턴스 초기화 (엔진 기동 시 1회 호출)."""
    global _tick_queue, _order_queue, _broadcast_queue, _control_queue

    if _tick_queue is not None:
        logger.warning("[core_queues] 이미 초기화됨 - 재초기화 생략")
        return

    _tick_queue = asyncio.Queue(maxsize=TICK_QUEUE_MAXSIZE)
    _order_queue = asyncio.Queue(maxsize=ORDER_QUEUE_MAXSIZE)
    _broadcast_queue = asyncio.Queue(maxsize=BROADCAST_QUEUE_MAXSIZE)
    _control_queue = asyncio.Queue(maxsize=CONTROL_QUEUE_MAXSIZE)

    logger.info(
        "[core_queues] 초기화 완료 - "
        f"tick={TICK_QUEUE_MAXSIZE}, order={ORDER_QUEUE_MAXSIZE}, "
        f"broadcast={BROADCAST_QUEUE_MAXSIZE}, control={CONTROL_QUEUE_MAXSIZE}"
    )


def get_tick_queue() -> asyncio.Queue:
    """시세 수신 전용 큐 반환."""
    if _tick_queue is None:
        raise RuntimeError("tick_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _tick_queue


def get_order_queue() -> asyncio.Queue:
    """주문/체결 전용 큐 반환."""
    if _order_queue is None:
        raise RuntimeError("order_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _order_queue


def get_broadcast_queue() -> asyncio.Queue:
    """UI 전송 전용 큐 반환."""
    if _broadcast_queue is None:
        raise RuntimeError("broadcast_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _broadcast_queue


def get_control_queue() -> asyncio.Queue:
    """제어 전용 큐 반환."""
    if _control_queue is None:
        raise RuntimeError("control_queue가 초기화되지 않음 - initialize_queues() 먼저 호출")
    return _control_queue


# ── Tick Queue 드롭 정책 (무손실 최신화) ─────────────────────────────────────────
async def put_tick_with_drop_policy(data: dict) -> None:
    """
    tick_queue에 데이터 삽입 - 드롭 정책 적용.

    정책:
    - 큐가 가득 찼을 때 (QueueFull), 가장 오래된 데이터를 즉시 버리고 최신 시세를 밀어넣음.
    - 시장 폭락 시 틱 폭주 대비 - 무손실 최신화 보장.

    Args:
        data: 시세 데이터 (dict)
    """
    queue = get_tick_queue()

    try:
        await queue.put(data)
    except asyncio.QueueFull:
        # 큐가 가득 찼으면 가장 오래된 데이터 버리고 최신 데이터 밀어넣기
        try:
            queue.get_nowait()  # 가장 오래된 데이터 제거
            await queue.put(data)  # 최신 데이터 삽입
            logger.debug("[core_queues] tick_queue 드롭 발생 - 최신 데이터 유지")
        except asyncio.QueueEmpty:
            # 경합 조건: 다른 태스크가 이미 데이터를 꺼낸 경우
            await queue.put(data)


# ── Order Queue 무결성 주석 ─────────────────────────────────────────────────────
# order_queue(주문/체결 전용)는 데이터 유실이 절대 불가하므로 드롭 정책을 적용하지 않음.
# 향후 Step 4에서 구현할 '기동 시 증권사 원장 대조(Reconciliation) 후 큐 처리 시작'이라는
# 강제 정산 원칙을 준수하여 큐 처리를 시작해야 함.
# ────────────────────────────────────────────────────────────────────────────────


def clear_all_queues() -> None:
    """모든 큐 비우기 (엔진 정지 시 호출)."""
    global _tick_queue, _order_queue, _broadcast_queue, _control_queue

    if _tick_queue:
        while not _tick_queue.empty():
            _tick_queue.get_nowait()
    if _order_queue:
        while not _order_queue.empty():
            _order_queue.get_nowait()
    if _broadcast_queue:
        while not _broadcast_queue.empty():
            _broadcast_queue.get_nowait()
    if _control_queue:
        while not _control_queue.empty():
            _control_queue.get_nowait()

    logger.info("[core_queues] 모든 큐 비우기 완료")
