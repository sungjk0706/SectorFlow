#!/usr/bin/env python3
"""
8가지 증권사 조합 자동 검증 스크립트

3개 콤보박스(시세, 주문, 업종) × 2개 증권사(LS, 키움) = 8가지 조합 테스트
"""

import asyncio
import json
import sys
import time
import websockets
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class Status(Enum):
    SUCCESS = "✅ 성공"
    FAILED = "❌ 실패"
    SKIPPED = "⏭️  건너뜀"


@dataclass
class TestResult:
    combination_id: int
    websocket_broker: str
    order_broker: str
    sector_broker: str
    status: Status
    snapshot_received: bool
    broker_config_match: bool
    error_message: Optional[str] = None
    ws_events_received: list = None

    def __post_init__(self):
        if self.ws_events_received is None:
            self.ws_events_received = []


class BrokerCombinationTester:
    """8가지 조합 자동 검증기"""

    COMBINATIONS = [
        # (websocket, order, sector)
        ("ls", "ls", "ls"),      # 1: 전체 LS
        ("ls", "ls", "kiwoom"),  # 2: 시세/주문=LS, 업종=키움
        ("ls", "kiwoom", "ls"),  # 3: 시세/업종=LS, 주문=키움
        ("ls", "kiwoom", "kiwoom"),  # 4: 시세=LS, 주문/업종=키움
        ("kiwoom", "ls", "ls"),  # 5: 시세=키움, 주문/업종=LS
        ("kiwoom", "ls", "kiwoom"),  # 6: 시세/업종=키움, 주문=LS
        ("kiwoom", "kiwoom", "ls"),  # 7: 시세/주문=키움, 업종=LS
        ("kiwoom", "kiwoom", "kiwoom"),  # 8: 전체 키움
    ]

    def __init__(self, settings_path: str = "backend/data/settings.json"):
        self.settings_path = Path(settings_path)
        self.original_settings = None
        self.results: list[TestResult] = []

    def load_settings(self) -> dict:
        """현재 설정 파일 로드"""
        with open(self.settings_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_settings(self, settings: dict):
        """설정 파일 저장"""
        with open(self.settings_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)

    def apply_combination(self, websocket: str, order: str, sector: str):
        """특정 조합을 설정 파일에 적용"""
        settings = self.load_settings()
        
        settings["broker_config"] = {
            "websocket": websocket,
            "order": order,
            "account": order,  # order와 account는 동일
            "sector": sector,
            "auth": order,  # auth도 order와 동일
        }
        
        # broker 필드도 업데이트 (하위호환)
        settings["broker"] = websocket
        
        self.save_settings(settings)
        print(f"\n📋 조합 적용: 시세={websocket}, 주문={order}, 업종={sector}")

    async def test_websocket_connection(self, timeout: int = 15) -> tuple[bool, Optional[dict], list]:
        """WebSocket 연결 테스트 및 initial-snapshot 수신"""
        uri = "ws://localhost:8000/api/ws/prices?token=dev-bypass"
        events = []
        
        try:
            print(f"  🔌 Connecting to {uri}...")
            async with websockets.connect(uri) as ws:
                print(f"  ✅ WebSocket connected")
                start_time = time.time()
                snapshot = None
                
                while time.time() - start_time < timeout:
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        data = json.loads(message)
                        event_type = data.get("event")
                        
                        if event_type:
                            events.append(event_type)
                            print(f"  📨 Received: {event_type}")
                        
                        if event_type == "initial-snapshot":
                            snapshot = data.get("data", {})
                            broker_config = snapshot.get("broker_config", {})
                            print(f"  📊 initial-snapshot received, broker_config: {broker_config}")
                            break
                            
                    except asyncio.TimeoutError:
                        continue
                
                return snapshot is not None, snapshot, events
                
        except Exception as e:
            print(f"  ❌ WebSocket error: {e}")
            return False, None, [f"Error: {str(e)}"]

    def verify_broker_config(self, snapshot: dict, expected: dict) -> bool:
        """snapshot의 broker_config가 예상과 일치하는지 확인"""
        if not snapshot:
            return False
            
        broker_config = snapshot.get("broker_config", {})
        
        expected_config = {
            "websocket": expected["websocket"],
            "order": expected["order"],
            "account": expected["order"],  # account는 order와 동일
            "sector": expected["sector"],
            "auth": expected["order"],  # auth도 order와 동일
        }
        
        match = all(
            broker_config.get(k) == v 
            for k, v in expected_config.items()
        )
        
        if not match:
            print(f"  ⚠️  broker_config 불일치:")
            print(f"     예상: {expected_config}")
            print(f"     실제: {broker_config}")
        
        return match

    async def test_combination(self, combo_id: int, websocket: str, order: str, sector: str) -> TestResult:
        """단일 조합 테스트"""
        print(f"\n{'='*60}")
        print(f"🔍 조합 {combo_id}/8 테스트: 시세={websocket}, 주문={order}, 업종={sector}")
        print(f"{'='*60}")
        
        # 1. 설정 적용
        self.apply_combination(websocket, order, sector)
        
        # 2. 잠시 대기 (설정 저장 시간)
        await asyncio.sleep(0.5)
        
        # 3. WebSocket 연결 테스트
        print("  📡 WebSocket 연결 시도...")
        connected, snapshot, events = await self.test_websocket_connection(timeout=10)
        
        if not connected:
            return TestResult(
                combination_id=combo_id,
                websocket_broker=websocket,
                order_broker=order,
                sector_broker=sector,
                status=Status.FAILED,
                snapshot_received=False,
                broker_config_match=False,
                error_message="WebSocket 연결 실패 또는 initial-snapshot 수신 실패",
                ws_events_received=events
            )
        
        print(f"  ✅ WebSocket 연결 성공, 이벤트: {events}")
        
        # 4. broker_config 검증
        config_match = self.verify_broker_config(snapshot, {
            "websocket": websocket,
            "order": order,
            "sector": sector
        })
        
        if config_match:
            print(f"  ✅ broker_config 일치")
        else:
            print(f"  ❌ broker_config 불일치")
        
        return TestResult(
            combination_id=combo_id,
            websocket_broker=websocket,
            order_broker=order,
            sector_broker=sector,
            status=Status.SUCCESS if config_match else Status.FAILED,
            snapshot_received=True,
            broker_config_match=config_match,
            ws_events_received=events
        )

    async def run_all_tests(self) -> list[TestResult]:
        """8가지 조합 모두 테스트"""
        print("\n" + "="*60)
        print("🚀 8가지 증권사 조합 자동 검증 시작")
        print("="*60)
        
        # 원본 설정 백업
        self.original_settings = self.load_settings()
        
        try:
            for combo_id, (websocket, order, sector) in enumerate(self.COMBINATIONS, 1):
                result = await self.test_combination(combo_id, websocket, order, sector)
                self.results.append(result)
                
        finally:
            # 원본 설정 복원
            if self.original_settings:
                print("\n📋 원본 설정 복원 중...")
                self.save_settings(self.original_settings)
        
        return self.results

    def generate_report(self) -> str:
        """테스트 결과 보고서 생성"""
        lines = []
        lines.append("\n" + "="*70)
        lines.append("📊 8가지 증권사 조합 테스트 결과 보고서")
        lines.append("="*70)
        
        success_count = sum(1 for r in self.results if r.status == Status.SUCCESS)
        failed_count = sum(1 for r in self.results if r.status == Status.FAILED)
        
        lines.append(f"\n✅ 성공: {success_count}개")
        lines.append(f"❌ 실패: {failed_count}개")
        lines.append(f"📊 성공률: {success_count/8*100:.1f}%")
        
        lines.append("\n" + "-"*70)
        lines.append("상세 결과:")
        lines.append("-"*70)
        
        for r in self.results:
            lines.append(f"\n조합 {r.combination_id}: 시세={r.websocket_broker}, 주문={r.order_broker}, 업종={r.sector_broker}")
            lines.append(f"  상태: {r.status.value}")
            lines.append(f"  Snapshot 수신: {'✅' if r.snapshot_received else '❌'}")
            lines.append(f"  BrokerConfig 일치: {'✅' if r.broker_config_match else '❌'}")
            lines.append(f"  수신 이벤트: {r.ws_events_received}")
            if r.error_message:
                lines.append(f"  오류: {r.error_message}")
        
        lines.append("\n" + "="*70)
        lines.append("분석 요약:")
        lines.append("="*70)
        
        if failed_count == 0:
            lines.append("\n✅ 모든 조합이 정상적으로 동작합니다.")
            lines.append("   - 모든 broker_config 설정이 WebSocket을 통해 올바르게 전달됩니다.")
            lines.append("   - 8가지 혼합 조합 모두 문제없이 작동합니다.")
        else:
            lines.append(f"\n⚠️  {failed_count}개 조합에서 문제가 발견되었습니다.")
            
            # 실패 원인 분석
            failed_results = [r for r in self.results if r.status == Status.FAILED]
            
            if any(not r.snapshot_received for r in failed_results):
                lines.append("\n  [WebSocket 연결 문제]")
                lines.append("   - 일부 조합에서 WebSocket 연결이 실패했습니다.")
                lines.append("   - 원인: 백엔드 엔진이 실행 중인지 확인 필요")
            
            if any(r.snapshot_received and not r.broker_config_match for r in failed_results):
                lines.append("\n  [BrokerConfig 불일치 문제]")
                lines.append("   - snapshot은 수신되었으나 broker_config 값이 설정과 다릅니다.")
                lines.append("   - 원인: 백엔드에서 settings.json을 제대로 읽지 못하거나,")
                lines.append("           engine_service.py의 build_initial_snapshot() 로직 문제")
        
        lines.append("\n" + "="*70)
        
        return "\n".join(lines)


async def main():
    """메인 실행"""
    tester = BrokerCombinationTester()
    
    # 앱이 실행 중인지 확인
    print("🔍 백엔드 엔진 상태 확인 중...")
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', 8000))
    sock.close()
    
    if result != 0:
        print("❌ 오류: 백엔드 엔진이 실행 중이지 않습니다.")
        print("   먼저 앱을 기동시킨 후 다시 실행하세요.")
        sys.exit(1)
    
    print("✅ 백엔드 엔진 확인 완료")
    
    # 테스트 실행
    await tester.run_all_tests()
    
    # 보고서 출력
    report = tester.generate_report()
    print(report)
    
    # 보고서 파일 저장
    report_path = Path("scripts/test_report.txt")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n📄 보고서 저장 완료: {report_path.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
