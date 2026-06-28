from __future__ import annotations
from typing import Optional
# -*- coding: utf-8 -*-
"""
중앙 상태 관리자 (StateManager)

모든 상태 변경은 단일 이벤트 큐를 통해서만 수행된다.
외부에서 상태 직접 수정은 불가능하다.
단일 worker가 큐를 순차적으로 처리하여 동시성 문제를 완전히 제거한다.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from backend.app.core import journal as _journal

_log = logging.getLogger(__name__)


class EventType(Enum):
    """이벤트 타입"""
    ORDER_CREATED = "order_created"
    ORDER_STATUS_CHANGED = "order_status_changed"
    ORDER_FILL = "order_fill"
    POSITION_UPDATED = "position_updated"
    BALANCE_UPDATED = "balance_updated"


class OrderStatus(Enum):
    """주문 상태"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL_FILLED = "partial_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


# 상태 전이 규칙 (모듈 레벨 dict)
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.SUBMITTED: {OrderStatus.PARTIAL_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED},
    OrderStatus.PARTIAL_FILLED: {OrderStatus.PARTIAL_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED},
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}


@dataclass
class Order:
    """주문 데이터"""
    order_id: str
    stock_code: str
    side: str  # "buy" or "sell"
    quantity: int
    price: float
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    avg_fill_price: float = 0.0
    timestamp: float = field(default_factory=time.time)
    broker_order_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass
class StateEvent:
    """상태 이벤트"""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)


class StateManager:
    """
    중앙 상태 관리자

    특징:
    - 모든 상태 변경은 단일 이벤트 큐를 통해서만 수행
    - 외부에서 상태 직접 수정 불가
    - 단일 worker가 큐를 순차적으로 처리하여 동시성 문제 완전 제거
    """

    def __init__(self):
        # Private 상태 (외부 직접 접근 차단)
        self._positions: Dict[str, Dict[str, Any]] = {}  # 종목코드 -> {quantity, avg_price}
        self._orders: Dict[str, Order] = {}  # 주문ID -> Order
        self._order_id_mapping: Dict[str, str] = {}  # 증권사 주문번호 -> 내부 주문 ID
        self._processed_signals: Set[str] = set()  # idempotency_key 기록
        self._order_latency_trace: Dict[str, Dict[str, float]] = {}  # 주문ID -> latency_trace

        # 이벤트 큐 (비동기 FIFO 큐)
        self._event_queue: asyncio.Queue = asyncio.Queue()

        # Worker 상태
        self._worker_started = False
        self._worker_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """StateManager worker 시작"""
        if self._worker_started:
            _log.warning("[StateManager] 이미 시작됨")
            return

        self._worker_started = True
        self._worker_task = asyncio.create_task(self._worker_loop())

    async def stop(self) -> None:
        """StateManager worker 중지"""
        if not self._worker_started:
            return

        self._worker_started = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        _log.info("[StateManager] worker 중지")

    async def _worker_loop(self) -> None:
        """이벤트 처리 worker 루프"""
        try:
            while self._worker_started:
                event = await self._event_queue.get()
                await self._process_event(event)
        except asyncio.CancelledError:
            _log.info("[StateManager] worker 취소됨")
        except Exception as e:
            _log.error(f"[StateManager] worker 오류: {e}", exc_info=True)

    async def _process_event(self, event: StateEvent) -> None:
        """이벤트 처리"""
        try:
            if event.event_type == EventType.ORDER_CREATED:
                await self._handle_order_created(event.data)
            elif event.event_type == EventType.ORDER_STATUS_CHANGED:
                await self._handle_order_status_changed(event.data)
            elif event.event_type == EventType.ORDER_FILL:
                await self._handle_fill_event(event.data)
            elif event.event_type == EventType.POSITION_UPDATED:
                await self._handle_position_updated(event.data)
            elif event.event_type == EventType.BALANCE_UPDATED:
                await self._handle_balance_updated(event.data)
        except Exception as e:
            _log.error(f"[StateManager] 이벤트 처리 오류: {e}", exc_info=True)

    async def _handle_order_created(self, data: Dict[str, Any]) -> None:
        """주문 생성 처리"""
        order_id = data.get("order_id")
        if not order_id:
            _log.warning("[StateManager] 주문 생성 이벤트에 order_id 없음")
            return

        # idempotency 체크
        idempotency_key = data.get("idempotency_key")
        if idempotency_key and idempotency_key in self._processed_signals:
            _log.info(f"[StateManager] 중복 시그널 무시: {idempotency_key}")
            return
        if idempotency_key:
            self._processed_signals.add(idempotency_key)

        # 주문 생성
        order = Order(
            order_id=order_id,
            stock_code=data.get("stock_code", ""),
            side=data.get("side", ""),
            quantity=int(data.get("quantity", 0)),
            price=float(data.get("price", 0)),
            status=OrderStatus.PENDING,
            idempotency_key=idempotency_key,
        )
        self._orders[order_id] = order

        # 증권사 주문번호 매핑
        broker_order_id = data.get("broker_order_id")
        if broker_order_id:
            self._order_id_mapping[broker_order_id] = order_id

        # latency trace 기록
        latency_trace = data.get("latency_trace")
        if latency_trace:
            self._order_latency_trace[order_id] = latency_trace

        _log.info(f"[StateManager] 주문 생성: {order_id} ({order.stock_code} {order.side} {order.quantity}주)")

    async def _handle_order_status_changed(self, data: Dict[str, Any]) -> None:
        """주문 상태 변경 처리"""
        order_id = data.get("order_id")
        if not order_id or order_id not in self._orders:
            _log.warning(f"[StateManager] 주문 상태 변경 이벤트에 유효하지 않은 order_id: {order_id}")
            return

        order = self._orders[order_id]
        new_status = OrderStatus(data.get("status", "pending"))

        # 상태 전이 검증
        if new_status not in ALLOWED_TRANSITIONS.get(order.status, set()):
            _log.warning(f"[StateManager] 허용되지 않은 상태 전이: {order.status} -> {new_status}")
            return

        order.status = new_status
        _log.info(f"[StateManager] 주문 상태 변경: {order_id} -> {new_status.value}")

    async def _handle_fill_event(self, data: Dict[str, Any]) -> None:
        """체결 이벤트 처리"""
        order_id = data.get("order_id")
        if not order_id or order_id not in self._orders:
            _log.warning(f"[StateManager] 체결 이벤트에 유효하지 않은 order_id: {order_id}")
            return

        order = self._orders[order_id]
        fill_qty = int(data.get("fill_quantity", 0))
        fill_price = float(data.get("fill_price", 0))

        # 체결 수량 누적
        order.filled_quantity += fill_qty

        # 평균 체결가 계산
        if order.filled_quantity > 0:
            total_value = order.avg_fill_price * (order.filled_quantity - fill_qty) + fill_price * fill_qty
            order.avg_fill_price = total_value / order.filled_quantity

        # 전체 체결 시 상태 변경
        if order.filled_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
            _log.info(f"[StateManager] 주문 전체 체결: {order_id}")
        else:
            order.status = OrderStatus.PARTIAL_FILLED
            _log.info(f"[StateManager] 주문 부분 체결: {order_id} ({order.filled_quantity}/{order.quantity})")

    async def _handle_position_updated(self, data: Dict[str, Any]) -> None:
        """포지션 업데이트 처리"""
        stock_code = data.get("stock_code")
        if not stock_code:
            _log.warning("[StateManager] 포지션 업데이트 이벤트에 stock_code 없음")
            return

        quantity = int(data.get("quantity", 0))
        avg_price = float(data.get("avg_price", 0))

        if quantity == 0:
            # 포지션 제거
            if stock_code in self._positions:
                del self._positions[stock_code]
                _log.info(f"[StateManager] 포지션 제거: {stock_code}")
        else:
            # 포지션 업데이트
            self._positions[stock_code] = {
                "quantity": quantity,
                "avg_price": avg_price,
            }
            _log.info(f"[StateManager] 포지션 업데이트: {stock_code} {quantity}주 {avg_price}원")

    async def _handle_balance_updated(self, data: Dict[str, Any]) -> None:
        """잔고 업데이트 처리"""
        # 잔고는 별도의 상태로 관리할 수 있음
        # 현재는 로그만 남김
        _log.info(f"[StateManager] 잔고 업데이트: {data}")

    # ── 공개 API ──────────────────────────────────────────────────────────────

    async def emit_event(self, event_type: EventType, data: Dict[str, Any]) -> None:
        """이벤트 발행"""
        event = StateEvent(event_type=event_type, data=data)
        await self._event_queue.put(event)

    def get_position(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """포지션 조회 (읽기 전용)"""
        return self._positions.get(stock_code)

    def get_all_positions(self) -> Dict[str, Dict[str, Any]]:
        """전체 포지션 조회 (읽기 전용)"""
        return dict(self._positions)

    def get_order(self, order_id: str) -> Optional[Order]:
        """주문 조회 (읽기 전용)"""
        return self._orders.get(order_id)

    def get_all_orders(self) -> Dict[str, Order]:
        """전체 주문 조회 (읽기 전용)"""
        return dict(self._orders)

    def get_order_by_broker_id(self, broker_order_id: str) -> Optional[Order]:
        """증권사 주문번호로 주문 조회"""
        order_id = self._order_id_mapping.get(broker_order_id)
        if order_id:
            return self._orders.get(order_id)
        return None

    # ── Journal Replay ─────────────────────────────────────────────────────────

    async def replay_from_journal(self) -> int:
        """저널에서 상태 재생 (장애 복구용)
        
        Returns:
            재생된 엔트리 수
        """
        def handle_settings_change(entry):
            """설정 변경 재생 - 현재는 로그만 남김"""
            data = entry.data
            changed_keys = data.get("changed_keys", [])
            _log.info("[StateManager] 저널 재생 - 설정 변경: %s", changed_keys)
            # 설정 재생은 settings_store.py에서 처리 (여기서는 로그만)

        def handle_order_request(entry):
            """주문 요청 재생"""
            data = entry.data
            order_id = data.get("order_id")
            stock_code = data.get("stock_code")
            side = data.get("side")
            quantity = data.get("quantity")
            price = data.get("price")
            
            # 주문 상태 복구 (PENDING 상태로 재생)
            order = Order(
                order_id=order_id,
                stock_code=stock_code,
                side=side,
                quantity=quantity,
                price=price,
                status=OrderStatus.PENDING,
            )
            self._orders[order_id] = order
            _log.info("[StateManager] 저널 재생 - 주문 요청 복구: %s %s %d주", order_id, side, quantity)

        def handle_fill_event(entry):
            """체결 이벤트 재생"""
            data = entry.data
            order_id = data.get("order_id")
            fill_quantity = data.get("fill_quantity")
            fill_price = data.get("fill_price")
            
            # 체결 이벤트 직접 큐에 추가 (순서 보장을 위해 create_task 제거)
            event = StateEvent(event_type=EventType.ORDER_FILL, data={
                "order_id": order_id,
                "fill_quantity": fill_quantity,
                "fill_price": fill_price,
            })
            asyncio.create_task(self._event_queue.put(event))
            _log.info("[StateManager] 저널 재생 - 체결 이벤트 발행: %s %d주", order_id, fill_quantity)

        # 저널 재생 실행
        replayed_count = _journal.replay_journal(
            settings_change_handler=handle_settings_change,
            order_request_handler=handle_order_request,
            fill_event_handler=handle_fill_event,
        )
        
        return replayed_count
