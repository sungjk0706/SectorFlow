#!/usr/bin/env python3
"""
실시간 데이터 수신 테스트 (장중/장외 모두 가능)
WebSocket 연결 및 이벤트 수신 확인
"""

import asyncio
import json
import websockets
from datetime import datetime


async def test_realtime_data():
    """실시간 WebSocket 데이터 수신 테스트"""
    
    print("=" * 60)
    print("📡 실시간 데이터 수신 테스트")
    print("=" * 60)
    
    uri = "ws://localhost:8000/api/ws/prices?token=dev-bypass"
    
    try:
        print(f"\n🔌 WebSocket 연결: {uri}")
        async with websockets.connect(uri) as ws:
            print("✅ WebSocket 연결 성공")
            
            # 30초 동안 메시지 수신
            print("\n⏱️ 30초 동안 메시지 수신 대기...")
            print("-" * 60)
            
            start_time = asyncio.get_event_loop().time()
            message_count = 0
            event_types = {}
            
            while asyncio.get_event_loop().time() - start_time < 30:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    data = json.loads(message)
                    event_type = data.get("event", "unknown")
                    
                    message_count += 1
                    event_types[event_type] = event_types.get(event_type, 0) + 1
                    
                    # 주요 이벤트 상세 출력
                    if event_type == "initial-snapshot":
                        snapshot = data.get("data", {})
                        bc = snapshot.get("broker_config", {})
                        print(f"\n📊 [initial-snapshot]")
                        print(f"   broker_config: {bc}")
                        print(f"   계좌: {snapshot.get('account', {}).get('deposit', 0):,}원")
                        print(f"   포지션: {len(snapshot.get('positions', []))}개")
                        print(f"   업종순위: {len(snapshot.get('sector_scores', []))}개")
                        
                    elif event_type == "sector-tick":
                        ticks = data.get("data", {}).get("ticks", [])
                        if ticks:
                            print(f"\n📈 [sector-tick] {len(ticks)}개 종목")
                            # 첫 3개만 샘플 출력
                            for tick in ticks[:3]:
                                print(f"   {tick.get('code')}: {tick.get('cur_price'):,}원 ({tick.get('change_rate', 0):+.2f}%)")
                                
                    elif event_type == "account-update":
                        data_inner = data.get("data", {})
                        changed = len(data_inner.get("changed_positions", []))
                        print(f"\n💰 [account-update] 변경된 포지션: {changed}개")
                        
                    elif event_type == "sector-scores":
                        scores = data.get("data", {}).get("scores", [])
                        print(f"\n🏆 [sector-scores] 업종 {len(scores)}개")
                        
                    elif event_type not in ["ping", "pong"]:
                        print(f"\n📨 [{event_type}]")
                        
                except asyncio.TimeoutError:
                    # 2초마다 타임아웃은 정상 (메시지 없을 때)
                    continue
                except Exception as e:
                    print(f"❌ 메시지 수신 오류: {e}")
                    break
            
            # 결과 요약
            print("\n" + "=" * 60)
            print("📊 테스트 결과 요약")
            print("=" * 60)
            print(f"총 수신 메시지: {message_count}개")
            print(f"\n이벤트별 수신 횟수:")
            for event, count in sorted(event_types.items(), key=lambda x: -x[1]):
                print(f"  - {event}: {count}회")
            
            # 데이터 흐름 확인
            print(f"\n✅ 확인된 데이터 흐름:")
            if "initial-snapshot" in event_types:
                print("  ✓ 초기 설정 데이터 (broker_config, 계좌, 포지션)")
            if "sector-tick" in event_types:
                print("  ✓ 실시간 종목 시세 (현재가, 등락률)")
            if "account-update" in event_types:
                print("  ✓ 계좌/포지션 변경 알림")
            if "sector-scores" in event_types:
                print("  ✓ 업종 순위 데이터")
                
            # 장중 여부 판단
            if "sector-tick" in event_types and event_types["sector-tick"] > 1:
                print(f"\n🟢 장중으로 보입니다 (실시간 틱 데이터 수신 중)")
            else:
                print(f"\n⚪ 장외로 보입니다 (실시간 틱 데이터 없음)")
                print("   단, WebSocket 구조는 정상 작동함")
            
            print(f"\n⏰ 테스트 완료: {datetime.now().strftime('%H:%M:%S')}")
            
    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        return False
    
    return True


if __name__ == "__main__":
    result = asyncio.run(test_realtime_data())
    exit(0 if result else 1)
