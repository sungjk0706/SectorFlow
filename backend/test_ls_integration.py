# -*- coding: utf-8 -*-
"""
LS증권 통합 테스트
"""
import asyncio
import sys
import os

# PYTHONPATH 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.ls_rest import LsRestAPI
from app.core.ls_broker import LsBroker
from app.services.state_manager import StateManager, EventType
from app.core.broker_factory import get_broker


async def test_ls_rest_client():
    """LS증권 REST 클라이언트 테스트"""
    print("[테스트] LS증권 REST 클라이언트 초기화")
    
    client = LsRestAPI(
        app_key="test_key",
        app_secret="test_secret",
    )
    
    # 초기화 검증
    assert client.app_key == "test_key"
    assert client.app_secret == "test_secret"
    assert client._token_info is None
    
    print("[성공] LS증권 REST 클라이언트 초기화")
    return True


async def test_ls_broker():
    """LS증권 Broker 테스트"""
    print("[테스트] LS증권 Broker 초기화")
    
    settings = {
        "ls_app_key": "test_key",
        "ls_app_secret": "test_secret",
        "ls_account_no": "test_account",
    }
    
    broker = LsBroker(settings)
    
    # 초기화 검증
    assert broker.broker_name == "ls"
    assert broker._acnt_no == "test_account"
    
    print("[성공] LS증권 Broker 초기화")
    return True


async def test_state_manager():
    """StateManager 테스트"""
    print("[테스트] StateManager 초기화 및 이벤트 처리")
    
    state_manager = StateManager()
    await state_manager.start()
    
    # 이벤트 발행 테스트
    await state_manager.emit_event(
        EventType.ORDER_CREATED,
        {
            "order_id": "test_order_1",
            "stock_code": "005930",
            "side": "buy",
            "quantity": 10,
            "price": 50000,
            "idempotency_key": "test_key_1",
        }
    )
    
    # 잠시 대기하여 이벤트 처리
    await asyncio.sleep(0.1)
    
    # 주문 조회 검증
    order = state_manager.get_order("test_order_1")
    assert order is not None
    assert order.stock_code == "005930"
    assert order.side == "buy"
    assert order.quantity == 10
    
    await state_manager.stop()
    
    print("[성공] StateManager 초기화 및 이벤트 처리")
    return True


def test_broker_factory_ls():
    """broker_factory LS증권 생성 테스트"""
    print("[테스트] broker_factory LS증권 생성")
    
    settings = {
        "broker": "ls",
        "ls_app_key": "test_key",
        "ls_app_secret": "test_secret",
        "ls_account_no": "test_account",
    }
    
    broker = get_broker(settings)
    
    # 검증
    assert broker.broker_name == "ls"
    
    print("[성공] broker_factory LS증권 생성")
    return True


def test_broker_factory_kiwoom():
    """broker_factory 키움증권 생성 테스트 (하위 호환)"""
    print("[테스트] broker_factory 키움증권 생성 (하위 호환)")
    
    settings = {
        "broker": "kiwoom",
        "kiwoom_app_key": "test_key",
        "kiwoom_app_secret": "test_secret",
        "kiwoom_account_no": "test_account",
    }
    
    broker = get_broker(settings)
    
    # 검증
    assert broker.broker_name == "kiwoom"
    
    print("[성공] broker_factory 키움증권 생성 (하위 호환)")
    return True


async def main():
    """메인 테스트 함수"""
    print("=" * 50)
    print("LS증권 하이브리드 구조 통합 테스트 시작")
    print("=" * 50)
    
    results = []
    
    try:
        # LS증권 REST 클라이언트 테스트
        result = await test_ls_rest_client()
        results.append(("LS증권 REST 클라이언트", result))
    except Exception as e:
        print(f"[실패] LS증권 REST 클라이언트 테스트: {e}")
        results.append(("LS증권 REST 클라이언트", False))
    
    try:
        # LS증권 Broker 테스트
        result = await test_ls_broker()
        results.append(("LS증권 Broker", result))
    except Exception as e:
        print(f"[실패] LS증권 Broker 테스트: {e}")
        results.append(("LS증권 Broker", False))
    
    try:
        # StateManager 테스트
        result = await test_state_manager()
        results.append(("StateManager", result))
    except Exception as e:
        print(f"[실패] StateManager 테스트: {e}")
        results.append(("StateManager", False))
    
    try:
        # broker_factory LS증권 생성 테스트
        result = test_broker_factory_ls()
        results.append(("broker_factory LS증권", result))
    except Exception as e:
        print(f"[실패] broker_factory LS증권 테스트: {e}")
        results.append(("broker_factory LS증권", False))
    
    try:
        # broker_factory 키움증권 생성 테스트
        result = test_broker_factory_kiwoom()
        results.append(("broker_factory 키움증권", result))
    except Exception as e:
        print(f"[실패] broker_factory 키움증권 테스트: {e}")
        results.append(("broker_factory 키움증권", False))
    
    # 결과 요약
    print("=" * 50)
    print("테스트 결과 요약")
    print("=" * 50)
    
    for name, result in results:
        status = "[성공]" if result else "[실패]"
        print(f"{status} {name}")
    
    total = len(results)
    passed = sum(1 for _, result in results if result)
    print(f"\n총 {total}개 테스트 중 {passed}개 통과")
    
    if passed == total:
        print("\n모든 테스트 통과!")
        return 0
    else:
        print(f"\n{total - passed}개 테스트 실패")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
