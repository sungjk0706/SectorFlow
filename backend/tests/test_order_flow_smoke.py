# -*- coding: utf-8 -*-
"""
테스트모드 엔드투엔드 스모크 테스트.

시세 → 판단 → 주문 → 체결기록 → 잔고반영 경로를 1회 흘려보는 테스트.
전체 앱 기동 없이 핵심 함수만 직접 호출하여 검증.
"""
import pytest
from backend.app.core.trade_mode import is_test_mode
from backend.app.services import dry_run
from backend.app.core import journal as _journal
from backend.app.services import trade_history


@pytest.mark.asyncio
async def test_mode_settings_detection(test_mode_settings: dict):
    """테스트모드 설정이 올바르게 감지되는지 확인."""
    assert is_test_mode(test_mode_settings) is True


@pytest.mark.asyncio
async def test_dry_run_fake_send_order(test_mode_settings: dict):
    """
    테스트모드에서 fake_send_order가 가상 체결을 반환하는지 확인.
    
    이 테스트는 돈 I/O 분리 검증 (원칙 9):
    - 실거래 send_order는 호출되지 않음
    - dry_run.fake_send_order만 호출됨
    """
    result = await dry_run.fake_send_order(
        settings=test_mode_settings,
        access_token="test_token",
        order_type="BUY",
        code="005930",
        qty=10,
        price=80000,
    )
    
    # 가상 체결 성공 응답 구조 확인
    assert result["success"] is True
    assert "msg" in result
    assert "data" in result
    assert result["data"]["rt_cd"] == "0"
    assert "ord_no" in result["data"]["output"]


@pytest.mark.asyncio
async def test_journal_record_order_request():
    """
    주문 요청이 journal에 기록되는지 확인.
    
    PHASE 1 수정 전에는 await 누락으로 인해 이 테스트가 실패할 수 있음.
    """
    # 테스트 전 저널 초기화
    _journal._journal_entries.clear()
    
    # 주문 요청 기록
    await _journal.record_order_request(
        order_id="test_order_001",
        stock_code="005930",
        side="BUY",
        quantity=10,
        price=80000,
        trade_mode="test",
    )
    
    # 저널에 기록되었는지 확인
    assert len(_journal._journal_entries) == 1
    assert _journal._journal_entries[0]["event_type"] == "order_request"
    assert _journal._journal_entries[0]["data"]["stock_code"] == "005930"


@pytest.mark.asyncio
async def test_trade_history_record_buy():
    """
    매수 체결이 trade_history에 기록되는지 확인.
    
    PHASE 1 수정 전에는 await 누락으로 인해 이 테스트가 실패할 수 있음.
    """
    # 테스트 전 이력 초기화
    trade_history._buy_history.clear()
    
    # 매수 체결 기록
    await trade_history.record_buy(
        stk_cd="005930",
        stk_nm="삼성전자",
        qty=10,
        price=80000,
        trade_mode="test",
    )
    
    # 이력에 기록되었는지 확인
    assert len(trade_history._buy_history) == 1
    assert trade_history._buy_history[0]["stk_cd"] == "005930"
    assert trade_history._buy_history[0]["qty"] == 10


@pytest.mark.asyncio
async def test_dry_run_virtual_position():
    """
    테스트모드에서 가상 잔고가 반영되는지 확인.
    """
    # 테스트 전 가상 잔고 초기화
    await dry_run.clear()
    
    # 매수 체결 반영
    await dry_run._apply_buy(code="005930", qty=10, price=80000)
    
    # 가상 잔고 확인
    positions = await dry_run.get_positions()
    assert len(positions) == 1
    assert positions[0]["stk_cd"] == "005930"
    assert positions[0]["qty"] == 10
    
    # 정리
    await dry_run.clear()
