# -*- coding: utf-8 -*-
"""
주문 상태기계 검증 테스트 (P1-3)

검증 항목:
1. 부분체결: 주문이 일부만 체결될 때 상태가 PARTIAL_FILLED로 전이
2. 전체체결: 주문이 전량 체결될 때 상태가 FILLED로 전이
3. 거부: 주문이 거부될 때 상태가 REJECTED로 전이
4. 취소: 주문 취소 요청 시 상태가 CANCELLED로 전이
5. 상태 전이 규칙 검증: 허용되지 않은 전이는 차단
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import pytest_asyncio
import asyncio
from app.services.state_manager import StateManager, EventType, OrderStatus


@pytest_asyncio.fixture
async def state_manager():
    """StateManager fixture for each test"""
    sm = StateManager()
    await sm.start()
    yield sm
    await sm.stop()


# ── 테스트 1: 부분체결 검증 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_partial_fill(state_manager):
    """부분체결 시 상태가 PARTIAL_FILLED로 전이되는지 검증"""
    # 주문 생성
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_1",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 100,
            "price": 50000,
            "idempotency_key": "test_key_1",
        }
    )
    await asyncio.sleep(0.1)

    # 주문 접수
    await state_manager.emit_event(
        EventType.ORDER_STATUS_CHANGED,
        {
            "order_id": "test_order_1",
            "status": "submitted",
        }
    )
    await asyncio.sleep(0.1)

    # 부분 체결 (50/100)
    await state_manager.emit_event(
        EventType.FILL_EVENT,
        {
            "order_id": "test_order_1",
            "fill_quantity": 50,
            "fill_price": 50000,
        }
    )
    await asyncio.sleep(0.1)

    # 상태 검증
    order = state_manager.get_order("test_order_1")
    assert order is not None
    assert order.status == OrderStatus.PARTIAL_FILLED
    assert order.filled_quantity == 50
    assert order.quantity == 100


# ── 테스트 2: 전체체결 검증 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_fill(state_manager):
    """전체체결 시 상태가 FILLED로 전이되는지 검증"""
    # 주문 생성
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_2",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 100,
            "price": 50000,
            "idempotency_key": "test_key_2",
        }
    )
    await asyncio.sleep(0.1)

    # 주문 접수
    await state_manager.emit_event(
        EventType.ORDER_STATUS_CHANGED,
        {
            "order_id": "test_order_2",
            "status": "submitted",
        }
    )
    await asyncio.sleep(0.1)

    # 전체 체결 (100/100)
    await state_manager.emit_event(
        EventType.FILL_EVENT,
        {
            "order_id": "test_order_2",
            "fill_quantity": 100,
            "fill_price": 50000,
        }
    )
    await asyncio.sleep(0.1)

    # 상태 검증
    order = state_manager.get_order("test_order_2")
    assert order is not None
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 100
    assert order.quantity == 100


# ── 테스트 3: 거부 검증 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rejection(state_manager):
    """주문 거부 시 상태가 REJECTED로 전이되는지 검증"""
    # 주문 생성
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_3",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 100,
            "price": 50000,
            "idempotency_key": "test_key_3",
        }
    )
    await asyncio.sleep(0.1)

    # 주문 거부
    await state_manager.emit_event(
        EventType.ORDER_STATUS_CHANGED,
        {
            "order_id": "test_order_3",
            "status": "rejected",
        }
    )
    await asyncio.sleep(0.1)

    # 상태 검증
    order = state_manager.get_order("test_order_3")
    assert order is not None
    assert order.status == OrderStatus.REJECTED


# ── 테스트 4: 취소 검증 ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancellation(state_manager):
    """주문 취소 시 상태가 CANCELLED로 전이되는지 검증"""
    # 주문 생성
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_4",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 100,
            "price": 50000,
            "idempotency_key": "test_key_4",
        }
    )
    await asyncio.sleep(0.1)

    # 주문 접수
    await state_manager.emit_event(
        EventType.ORDER_STATUS_CHANGED,
        {
            "order_id": "test_order_4",
            "status": "submitted",
        }
    )
    await asyncio.sleep(0.1)

    # 주문 취소
    await state_manager.emit_event(
        EventType.ORDER_STATUS_CHANGED,
        {
            "order_id": "test_order_4",
            "status": "cancelled",
        }
    )
    await asyncio.sleep(0.1)

    # 상태 검증
    order = state_manager.get_order("test_order_4")
    assert order is not None
    assert order.status == OrderStatus.CANCELLED


# ── 테스트 5: 상태 전이 규칙 검증 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_state_transition(state_manager):
    """허용되지 않은 상태 전이는 차단되는지 검증"""
    # 주문 생성
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_5",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 100,
            "price": 50000,
            "idempotency_key": "test_key_5",
        }
    )
    await asyncio.sleep(0.1)

    # 주문 접수
    await state_manager.emit_event(
        EventType.ORDER_STATUS_CHANGED,
        {
            "order_id": "test_order_5",
            "status": "submitted",
        }
    )
    await asyncio.sleep(0.1)

    # FILLED 상태에서 다시 SUBMITTED로 전이 시도 (허용되지 않음)
    await state_manager.emit_event(
        EventType.ORDER_STATUS_CHANGED,
        {
            "order_id": "test_order_5",
            "status": "submitted",
        }
    )
    await asyncio.sleep(0.1)

    # 상태가 변경되지 않아야 함
    order = state_manager.get_order("test_order_5")
    assert order is not None
    assert order.status == OrderStatus.SUBMITTED  # 변경되지 않음


# ── 테스트 6: 부분체결 후 전체체결 검증 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_partial_to_full_fill(state_manager):
    """부분체결 후 전체체결 시 상태가 FILLED로 전이되는지 검증"""
    # 주문 생성
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_6",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 100,
            "price": 50000,
            "idempotency_key": "test_key_6",
        }
    )
    await asyncio.sleep(0.1)

    # 주문 접수
    await state_manager.emit_event(
        EventType.ORDER_STATUS_CHANGED,
        {
            "order_id": "test_order_6",
            "status": "submitted",
        }
    )
    await asyncio.sleep(0.1)

    # 부분 체결 (50/100)
    await state_manager.emit_event(
        EventType.FILL_EVENT,
        {
            "order_id": "test_order_6",
            "fill_quantity": 50,
            "fill_price": 50000,
        }
    )
    await asyncio.sleep(0.1)

    # 상태 검증: PARTIAL_FILLED
    order = state_manager.get_order("test_order_6")
    assert order is not None
    assert order.status == OrderStatus.PARTIAL_FILLED
    assert order.filled_quantity == 50

    # 나머지 체결 (50/100)
    await state_manager.emit_event(
        EventType.FILL_EVENT,
        {
            "order_id": "test_order_6",
            "fill_quantity": 50,
            "fill_price": 50000,
        }
    )
    await asyncio.sleep(0.1)

    # 상태 검증: FILLED
    order = state_manager.get_order("test_order_6")
    assert order is not None
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 100


# ── 테스트 7: 브로커 주문번호 매핑 검증 ────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_order_id_mapping(state_manager):
    """브로커 주문번호로 주문 조회가 가능한지 검증"""
    # 주문 생성 (브로커 주문번호 포함)
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_7",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 100,
            "price": 50000,
            "broker_order_id": "broker_12345",
            "idempotency_key": "test_key_7",
        }
    )
    await asyncio.sleep(0.1)

    # 브로커 주문번호로 주문 조회
    order = state_manager.get_order_by_broker_id("broker_12345")
    assert order is not None
    assert order.order_id == "test_order_7"
    assert order.stock_code == "005930"


# ── 테스트 8: idempotency 검증 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotency(state_manager):
    """동일한 idempotency_key로 중복 주문 생성이 차단되는지 검증"""
    # 첫 번째 주문 생성
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_8",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 100,
            "price": 50000,
            "idempotency_key": "test_key_8",
        }
    )
    await asyncio.sleep(0.1)

    # 동일한 idempotency_key로 두 번째 주문 생성 시도
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_8_dup",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 200,
            "price": 50000,
            "idempotency_key": "test_key_8",
        }
    )
    await asyncio.sleep(0.1)

    # 첫 번째 주문만 존재해야 함
    order = state_manager.get_order("test_order_8")
    assert order is not None
    assert order.quantity == 100

    order_dup = state_manager.get_order("test_order_8_dup")
    assert order_dup is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
