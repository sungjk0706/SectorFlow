# Phase E: WebSocket 브로드캐스트 완전한 해결 수정계획서

## 작업 목표
WebSocket 브로드캐스트의 완전한 해결을 통해 느린 클라이언트가 전체 시스템의 성능을 저하시키는 문제를 근본적으로 해결

## 현재 상태
- P0-4에서 기본 개선 완료 (asyncio.gather로 병렬 전송)
- 하지만 여전히 문제:
  - 느린 클라이언트가 메시지 처리를 지연시키면 연결이 맺힌 상태로 유지됨
  - outbound queue가 없어 메시지가 누적될 수 있음
  - latest-only drop policy가 없어 오래된 메시지가 전송됨
  - 느린 클라이언트를 격리하는 메커니즘 부족

## 요구사항

### 1. Client별 Outbound Queue
- 각 WebSocket 연결에 별도의 outbound queue 생성
- queue 크기 제한 (최대 N개 메시지)
- queue가 가득 차면 oldest 메시지 드롭

### 2. Latest-only Drop Policy
- 실시간 시계 데이터: 최신 데이터만 유지
- queue에 동일 종목의 데이터가 있으면 최신으로 교체
- 오래된 데이터는 자동 드롭

### 3. 느린 Client 격리
- 전송 시간 모니터링
- 연속 N회 전송 지연 시 연결 종료
- 느린 클라이언트 목록 관리 및 일정 시간 블록

### 4. 채널별 우선순위
- Control 채널: 높은 우선순위 (필수 메시지)
- Account 채널: 중간 우선순위 (계좌/주문)
- Market 채널: 낮은 우선순위 (실시간 시계, drop 허용)

## 설계

### Backend 구조
```
backend/infrastructure/websocket/outbound_queue.py (신규)
  - OutboundQueue 클래스
  - enqueue(): 메시지 추가 (latest-only drop)
  - dequeue(): 메시지 꺼내기
  - size(): queue 크기

backend/infrastructure/websocket/client_manager.py (신규)
  - ClientManager 클래스
  - 각 클라이언트별 OutboundQueue 관리
  - 전송 시간 모니터링
  - 느린 클라이언트 격리 로직

backend/presentation/websocket/router.py 수정
  - ConnectionManager → ClientManager로 대체
  - broadcast() 메서드 수정 (queue 기반 전송)
```

### Frontend 구조
- 변경 없음 (기존 WebSocket 클라이언트 호환)

## 단계별 실행 계획

### 단계 1: OutboundQueue 구현
- `backend/infrastructure/websocket/outbound_queue.py` 생성
- OutboundQueue 클래스 구현
  - enqueue(): latest-only drop 로직
  - dequeue(): 메시지 꺼내기
  - size(): queue 크기
  - clear(): queue 초기화
- 검증: python -m py_compile 성공

### 단계 2: ClientManager 구현
- `backend/infrastructure/websocket/client_manager.py` 생성
- ClientManager 클래스 구현
  - add_client(): 클라이언트 추가 (OutboundQueue 생성)
  - remove_client(): 클라이언트 제거
  - broadcast(): 모든 클라이언트에 메시지 전송 (queue 기반)
  - monitor_slow_clients(): 느린 클라이언트 감지 및 격리
- 검증: python -m py_compile 성공

### 단계 3: Router에서 ClientManager 통합
- `backend/presentation/websocket/router.py` 수정
- ConnectionManager → ClientManager로 대체
- broadcast() 메서드 수정
- 검증: python -m py_compile 성공

### 단계 4: Handlers에서 ClientManager 사용
- `backend/presentation/websocket/handlers.py` 수정
- ClientManager 사용으로 변경
- 검증: python -m py_compile 성공

### 단계 5: 검증 및 인계서 업데이트
- 기능 검증
- HANDOVER.md 업데이트
- 현재진단.md에 완료 표시

## 기술적 결정 사항
- Queue 구현: collections.deque 사용 (O(1) 연산)
- Latest-only drop: 종목 코드 기반 교체 (시계 데이터)
- 느린 클라이언트 감지: 전송 시간 > 1초 기준, 연속 3회 시 격리
- Queue 크기 제한: 최대 100개 메시지

## 검증 기준
- Backend API 정상 응답
- WebSocket 연결 정상
- 느린 클라이언트 격리 동작
- Latest-only drop 동작
- 빌드 성공 (python)
