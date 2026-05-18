# -*- coding: utf-8 -*-
"""
WebSocket 처리 모듈
- WebSocket 메시지 수신
- WebSocket 메시지 분기
- 실시간 데이터 처리
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """WebSocket 처리 관리자"""

    def __init__(self):
        self._message_handlers = {}  # 메시지 타입 -> 핸들러
        self._subscribed_stocks = set()  # 구독 중인 종목

    def register_handler(self, message_type: str, handler: Callable) -> None:
        """메시지 핸들러 등록"""
        self._message_handlers[message_type] = handler
        logger.debug(f"[WS] 핸들러 등록: {message_type}")

    async def handle_message(self, data: dict) -> None:
        """WebSocket 메시지 처리"""
        message_type = data.get("type", "")
        handler = self._message_handlers.get(message_type)

        if handler:
            try:
                await handler(data)
            except Exception as e:
                logger.error(f"[WS] 메시지 처리 오류 ({message_type}): {e}", exc_info=True)
        else:
            logger.warning(f"[WS] 핸들러 없음: {message_type}")

    def subscribe_stock(self, stock_code: str) -> None:
        """종목 구독"""
        self._subscribed_stocks.add(stock_code)
        logger.debug(f"[WS] 종목 구독: {stock_code}")

    def unsubscribe_stock(self, stock_code: str) -> None:
        """종목 구독 해제"""
        self._subscribed_stocks.discard(stock_code)
        logger.debug(f"[WS] 종목 구독 해제: {stock_code}")

    def get_subscribed_stocks(self) -> set:
        """구독 중인 종목 조회"""
        return set(self._subscribed_stocks)

    def clear_all_subscriptions(self) -> None:
        """전체 구독 초기화"""
        self._subscribed_stocks.clear()
        logger.info("[WS] 전체 구독 초기화")
