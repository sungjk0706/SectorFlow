# -*- coding: utf-8 -*-
"""
포지션 관리 모듈
- 포지션 조회
- 포지션 업데이트
- 포지션 손익 계산
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PositionManager:
    """포지션 관리자"""

    def __init__(self):
        self._positions = {}  # 종목코드 -> 포지션 정보

    def get_position(self, stock_code: str) -> Optional[dict]:
        """포지션 조회"""
        return self._positions.get(stock_code)

    def get_all_positions(self) -> dict:
        """전체 포지션 조회"""
        return dict(self._positions)

    def update_position(self, stock_code: str, quantity: int, avg_price: float) -> None:
        """포지션 업데이트"""
        if quantity == 0:
            # 포지션 제거
            if stock_code in self._positions:
                del self._positions[stock_code]
                logger.info(f"[포지션] 포지션 제거: {stock_code}")
        else:
            # 포지션 업데이트
            self._positions[stock_code] = {
                "quantity": quantity,
                "avg_price": avg_price,
            }
            logger.info(f"[포지션] 포지션 업데이트: {stock_code} {quantity}주 {avg_price}원")

    def apply_last_price(self, stock_code: str, price: int) -> bool:
        """현재가 적용"""
        position = self.get_position(stock_code)
        if not position:
            return False

        position["cur_price"] = price
        return True

    def get_position_pnl_pct(self, stock_code: str) -> Optional[float]:
        """포지션 손익률 계산"""
        position = self.get_position(stock_code)
        if not position:
            return None

        buy_price = position.get("avg_price", 0)
        cur_price = position.get("cur_price", 0)

        if buy_price == 0:
            return 0.0

        return ((cur_price - buy_price) / buy_price) * 100

    def clear_all_positions(self) -> None:
        """전체 포지션 초기화"""
        self._positions.clear()
        logger.info("[포지션] 전체 포지션 초기화")
