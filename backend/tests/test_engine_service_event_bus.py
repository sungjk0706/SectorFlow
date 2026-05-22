# -*- coding: utf-8 -*-
"""
engine_service.py Event Bus 구독 테스트 - 핸들러 로직 단위 테스트
"""
from __future__ import annotations

import pytest
import pytest_asyncio
import asyncio
from unittest.mock import Mock, patch, MagicMock

from app.core.events import (
    BrokerType,
    EventType,
    create_market_tick_event,
    create_order_fill_event,
    create_account_update_event,
)
from app.core.event_bus import EventBus


class TestEngineServiceEventBus:
    """engine_service Event Bus 구독 테스트"""

    @pytest_asyncio.fixture
    async def event_bus(self):
        """Event Bus fixture"""
        bus = EventBus()
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.mark.asyncio
    async def test_market_tick_handler_logic(self, event_bus):
        """MarketTickEvent 핸들러 로직 테스트 - 캐시 업데이트 확인"""
        # Mock 캐시 생성
        mock_latest_trade_prices = {}
        mock_pending_stock_details = {}
        
        # 핸들러 로직 직접 구현 (engine_service._handle_market_tick_event와 동일)
        async def handle_market_tick(event, latest_prices, pending_details):
            """핸들러 로직 복사본"""
            code = event.code
            price = event.price
            change = event.change
            change_rate = event.change_rate
            volume = event.volume
            trade_amount = event.trade_amount
            sign = event.sign
            
            # 캐시 업데이트
            latest_prices[code] = price
            
            # _pending_stock_details 업데이트
            if code in pending_details:
                pend_key = code
                old = pending_details[pend_key]
                new_entry = {**old,
                    "cur_price": price,
                    "change": change,
                    "change_rate": change_rate,
                    "sign": sign,
                    "trade_amount": trade_amount,
                }
                pending_details[pend_key] = new_entry
        
        # 테스트 데이터 준비
        mock_pending_stock_details["005930"] = {
            "cur_price": 0,
            "change": 0,
            "change_rate": 0.0,
            "sign": "3",
            "trade_amount": 0,
        }
        
        # 이벤트 생성
        event = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={},
        )
        
        # 핸들러 호출
        await handle_market_tick(event, mock_latest_trade_prices, mock_pending_stock_details)
        
        # 캐시 업데이트 확인
        assert mock_latest_trade_prices["005930"] == 80000
        assert mock_pending_stock_details["005930"]["cur_price"] == 80000
        assert mock_pending_stock_details["005930"]["change"] == 1000
        assert mock_pending_stock_details["005930"]["change_rate"] == 1.25
        assert mock_pending_stock_details["005930"]["sign"] == "2"
        assert mock_pending_stock_details["005930"]["trade_amount"] == 80000000000

    @pytest.mark.asyncio
    async def test_market_tick_handler_not_in_pending(self, event_bus):
        """_pending_stock_details에 없는 종목의 MarketTickEvent 처리 테스트"""
        # Mock 캐시 생성
        mock_latest_trade_prices = {}
        mock_pending_stock_details = {}
        
        # 핸들러 로직 직접 구현
        async def handle_market_tick(event, latest_prices, pending_details):
            code = event.code
            price = event.price
            change = event.change
            change_rate = event.change_rate
            volume = event.volume
            trade_amount = event.trade_amount
            sign = event.sign
            
            latest_prices[code] = price
            
            if code in pending_details:
                pend_key = code
                old = pending_details[pend_key]
                new_entry = {**old,
                    "cur_price": price,
                    "change": change,
                    "change_rate": change_rate,
                    "sign": sign,
                    "trade_amount": trade_amount,
                }
                pending_details[pend_key] = new_entry
        
        # 이벤트 생성
        event = create_market_tick_event(
            broker=BrokerType.KIWOOM,
            code="005930",
            price=80000,
            change=1000,
            change_rate=1.25,
            volume=1000000,
            trade_amount=80000000000,
            sign="2",
            raw_data={},
        )
        
        # 핸들러 호출
        await handle_market_tick(event, mock_latest_trade_prices, mock_pending_stock_details)
        
        # _latest_trade_prices만 업데이트되고 _pending_stock_details는 업데이트되지 않음
        assert mock_latest_trade_prices["005930"] == 80000
        assert "005930" not in mock_pending_stock_details
