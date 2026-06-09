# -*- coding: utf-8 -*-
"""
SectorFlow 테스트 설정 및 공통 픽스처.

테스트는 운영 DB(backend/data/stocks.db)를 절대 건드리지 않으며,
임시 DB(:memory: 또는 별도 파일)를 사용하여 격리된 환경에서 실행된다.
"""
import asyncio
import os
import pytest
from typing import AsyncGenerator, Generator

# 테스트 실행 시 PYTEST_CURRENT_TEST 환경변수를 설정하여
# database.py가 테스트 전용 DB 경로를 사용하도록 함
os.environ["PYTEST_CURRENT_TEST"] = "1"


# 주의: pytest-asyncio 1.x에서 event_loop 픽스처 재정의는 deprecated이며,
# 함수별 루프와 충돌해 모듈 전역 Lock 교착을 유발한다.
# 루프 스코프는 pytest.ini의 asyncio_default_*_loop_scope=session 으로 일원화한다.


@pytest.fixture(scope="function")
async def test_db_connection() -> AsyncGenerator:
    """
    테스트 전용 DB 연결 픽스처.
    
    database.py의 get_db_connection()는 PYTEST_CURRENT_TEST 환경변수를 감지하여
    stocks_test.db를 사용하도록 이미 구현되어 있음.
    이 픽스처는 테스트 시작/종료 시 DB 연결을 초기화/정리한다.
    """
    from backend.app.db.database import get_db_connection, close_db_connection
    
    # 테스트 시작 시 연결 초기화
    conn = await get_db_connection()
    
    yield conn
    
    # 테스트 종료 시 연결 정리
    await close_db_connection()


@pytest.fixture(scope="function")
def test_mode_settings() -> dict:
    """
    테스트모드 설정 픽스처.
    
    trade_mode가 "test"로 설정된 설정 딕셔너리를 반환하여
    is_test_mode()가 True를 반환하도록 함.
    """
    return {
        "trade_mode": "test",
        "test_mode": True,
        "mock_mode": True,
        # 기타 필요한 기본 설정
        "auto_trade_on": False,
        "time_scheduler_on": False,
    }


@pytest.fixture(scope="function", autouse=True)
def mock_settlement_engine():
    """
    settlement_engine DB 쓰기를 mock하여 테스트에서 DB 의존성 제거.
    autouse=True로 모든 테스트에 자동 적용.
    """
    import pytest
    from unittest.mock import AsyncMock, patch
    
    # save_settlement_state, load_settlement_state를 mock
    with patch('backend.app.services.settlement_engine.save_settlement_state', new_callable=AsyncMock):
        with patch('backend.app.services.settlement_engine.load_settlement_state', new_callable=AsyncMock):
            # settlement_engine 초기화
            from backend.app.services import settlement_engine
            settlement_engine.init(10_000_000)
            yield
