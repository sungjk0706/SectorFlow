# -*- coding: utf-8 -*-
"""
주문 실행 모듈
- 주문 생성
- 주문 전송
- 주문 상태 관리
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class OrderExecution:
    """주문 실행 관리자"""

    def __init__(self):
        self._orders = {}  # 주문ID -> 주문 정보
        self._order_id_mapping = {}  # 증권사 주문번호 -> 내부 주문 ID

    def create_order(
        self,
        order_id: str,
        stock_code: str,
        side: str,
        quantity: int,
        price: float,
        idempotency_key: Optional[str] = None,
    ) -> None:
        """주문 생성"""
        self._orders[order_id] = {
            "order_id": order_id,
            "stock_code": stock_code,
            "side": side,
            "quantity": quantity,
            "price": price,
            "status": "pending",
            "filled_quantity": 0,
            "avg_fill_price": 0.0,
            "idempotency_key": idempotency_key,
        }
        logger.info(
            f"[주문] 주문 생성: {order_id} ({stock_code} {side} {quantity}주 {price}원)"
        )

    def get_order(self, order_id: str) -> Optional[dict]:
        """주문 조회"""
        return self._orders.get(order_id)

    def get_all_orders(self) -> dict:
        """전체 주문 조회"""
        return dict(self._orders)

    def update_order_status(self, order_id: str, status: str) -> None:
        """주문 상태 업데이트"""
        order = self.get_order(order_id)
        if order:
            order["status"] = status
            logger.info(f"[주문] 주문 상태 변경: {order_id} -> {status}")

    def apply_fill(
        self,
        order_id: str,
        fill_quantity: int,
        fill_price: float,
    ) -> None:
        """체결 적용"""
        order = self.get_order(order_id)
        if not order:
            return

        order["filled_quantity"] += fill_quantity

        # 평균 체결가 계산
        if order["filled_quantity"] > 0:
            total_value = (
                order["avg_fill_price"] * (order["filled_quantity"] - fill_quantity)
                + fill_price * fill_quantity
            )
            order["avg_fill_price"] = total_value / order["filled_quantity"]

        # 전체 체결 시 상태 변경
        if order["filled_quantity"] >= order["quantity"]:
            order["status"] = "filled"
            logger.info(f"[주문] 주문 전체 체결: {order_id}")
        else:
            order["status"] = "partial_filled"
            logger.info(
                f"[주문] 주문 부분 체결: {order_id} ({order['filled_quantity']}/{order['quantity']})"
            )

    def map_broker_order_id(self, broker_order_id: str, internal_order_id: str) -> None:
        """증권사 주문번호 매핑"""
        self._order_id_mapping[broker_order_id] = internal_order_id

    def get_order_by_broker_id(self, broker_order_id: str) -> Optional[dict]:
        """증권사 주문번호로 주문 조회"""
        internal_order_id = self._order_id_mapping.get(broker_order_id)
        if internal_order_id:
            return self.get_order(internal_order_id)
        return None

    def clear_all_orders(self) -> None:
        """전체 주문 초기화"""
        self._orders.clear()
        self._order_id_mapping.clear()
        logger.info("[주문] 전체 주문 초기화")
