# -*- coding: utf-8 -*-
"""
BackendCoalescing 테스트
"""
import asyncio
import sys
import os

# PYTHONPATH 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.backend_coalescing import BackendCoalescing
from app.services.core_queues import initialize_queues, clear_all_queues
import pytest


class MockWebSocket:
    """Mock WebSocket for testing"""
    def __init__(self):
        self.messages = []
    
    async def send_text(self, message: str):
        self.messages.append(message)
        
    async def send_bytes(self, message: bytes):
        self.messages.append(message)


@pytest.mark.asyncio
async def test_backend_coalescing():
    """BackendCoalescing 테스트"""
    print("[테스트] BackendCoalescing 초기화 및 이벤트 처리")
    
    initialize_queues()
    coalescing = BackendCoalescing(flush_interval_ms=10, flush_threshold=200)
    
    # Mock WebSocket 추가
    ws = MockWebSocket()
    coalescing.add_websocket(ws)
    
    # 시작
    await coalescing.start()
    
    # 이벤트 추가
    for i in range(10):
        coalescing.add_raw_data({
            "code": f"0059{i}",
            "type": "01",
            "values": {"10": 50000 + i},
        })
    
    # 잠시 대기하여 flush 실행
    await asyncio.sleep(0.05)
    
    # 중지
    await coalescing.stop()
    
    # 검증
    assert len(ws.messages) > 0, "WebSocket 메시지가 전송되어야 함"
    
    print(f"[성공] BackendCoalescing 초기화 및 이벤트 처리 (전송 메시지: {len(ws.messages)}개)")
    return True


@pytest.mark.asyncio
async def test_backend_coalescing_threshold():
    """BackendCoalescing threshold 테스트"""
    print("[테스트] BackendCoalescing threshold (200개) 테스트")
    
    initialize_queues()
    coalescing = BackendCoalescing(flush_interval_ms=1000, flush_threshold=200)
    
    # Mock WebSocket 추가
    ws = MockWebSocket()
    coalescing.add_websocket(ws)
    
    # 시작
    await coalescing.start()
    
    # 200개 이벤트 추가 (즉시 flush 트리거)
    for i in range(200):
        coalescing.add_raw_data({
            "code": f"0059{i % 10}",
            "type": "01",
            "values": {"10": 50000 + i},
        })
    
    # flush_event가 set되기를 기다림
    await asyncio.sleep(0.1)
    
    # 중지
    await coalescing.stop()
    
    # 검증
    assert len(ws.messages) > 0, "WebSocket 메시지가 전송되어야 함"
    
    print(f"[성공] BackendCoalescing threshold 테스트 (전송 메시지: {len(ws.messages)}개)")
    return True


async def main():
    """메인 테스트 함수"""
    print("=" * 50)
    print("BackendCoalescing 통합 테스트 시작")
    print("=" * 50)
    
    results = []
    
    try:
        # BackendCoalescing 테스트
        result = await test_backend_coalescing()
        results.append(("BackendCoalescing 기본", result))
    except Exception as e:
        print(f"[실패] BackendCoalescing 테스트: {e}")
        results.append(("BackendCoalescing 기본", False))
    
    try:
        # BackendCoalescing threshold 테스트
        result = await test_backend_coalescing_threshold()
        results.append(("BackendCoalescing threshold", result))
    except Exception as e:
        print(f"[실패] BackendCoalescing threshold 테스트: {e}")
        results.append(("BackendCoalescing threshold", False))
    
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
