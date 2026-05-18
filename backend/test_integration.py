# -*- coding: utf-8 -*-
"""
통합 테스트 - 모든 모듈 import 및 초기화 테스트
"""
import sys
import os

# PYTHONPATH 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """모든 모듈 import 테스트"""
    print("[테스트] 모든 모듈 import 테스트")
    
    try:
        from app.core.ls_rest import LsRestAPI
        print("[성공] ls_rest import")
    except Exception as e:
        print(f"[실패] ls_rest import: {e}")
        return False
    
    try:
        from app.core.ls_broker import LsBroker
        print("[성공] ls_broker import")
    except Exception as e:
        print(f"[실패] ls_broker import: {e}")
        return False
    
    try:
        from app.services.state_manager import StateManager
        print("[성공] state_manager import")
    except Exception as e:
        print(f"[실패] state_manager import: {e}")
        return False
    
    try:
        from app.services.backend_coalescing import BackendCoalescing
        print("[성공] backend_coalescing import")
    except Exception as e:
        print(f"[실패] backend_coalescing import: {e}")
        return False
    
    try:
        from app.core.broker_factory import get_broker
        print("[성공] broker_factory import")
    except Exception as e:
        print(f"[실패] broker_factory import: {e}")
        return False
    
    try:
        from app.services.engine_service import start_engine
        print("[성공] engine_service import")
    except Exception as e:
        print(f"[실패] engine_service import: {e}")
        return False
    
    try:
        import protobuf.event_pb2 as event_pb2
        print("[성공] protobuf event_pb2 import")
    except Exception as e:
        print(f"[실패] protobuf event_pb2 import: {e}")
        return False
    
    return True


def test_initialization():
    """모듈 초기화 테스트"""
    print("\n[테스트] 모듈 초기화 테스트")
    
    try:
        from app.core.ls_rest import LsRestAPI
        client = LsRestAPI("test_key", "test_secret")
        assert client.app_key == "test_key"
        print("[성공] LsRestAPI 초기화")
    except Exception as e:
        print(f"[실패] LsRestAPI 초기화: {e}")
        return False
    
    try:
        from app.core.ls_broker import LsBroker
        broker = LsBroker({
            "ls_app_key": "test_key",
            "ls_app_secret": "test_secret",
            "ls_account_no": "test_account",
        })
        assert broker.broker_name == "ls"
        print("[성공] LsBroker 초기화")
    except Exception as e:
        print(f"[실패] LsBroker 초기화: {e}")
        return False
    
    try:
        from app.services.backend_coalescing import BackendCoalescing
        coalescing = BackendCoalescing()
        assert coalescing.flush_interval_ms == 10
        assert coalescing.flush_threshold == 200
        print("[성공] BackendCoalescing 초기화")
    except Exception as e:
        print(f"[실패] BackendCoalescing 초기화: {e}")
        return False
    
    return True


def main():
    """메인 테스트 함수"""
    print("=" * 50)
    print("통합 테스트 시작")
    print("=" * 50)
    
    results = []
    
    # Import 테스트
    result = test_imports()
    results.append(("Import 테스트", result))
    
    # 초기화 테스트
    result = test_initialization()
    results.append(("초기화 테스트", result))
    
    # 결과 요약
    print("\n" + "=" * 50)
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
    sys.exit(main())
