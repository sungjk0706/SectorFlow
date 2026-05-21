# Cascade 아키텍처 03 - 실행 로드맵

## 목적

이 문서는 하위 AI가 `SectorFlow`를 Cascade가 제안한 궁극 아키텍처에 도달시키기 위한 단계별 실행 순서를 정의한다.

원칙:

```text
P0부터 해결한다.
실시간 hot path를 먼저 보호한다.
큰 리팩토링보다 작은 검증 가능한 단계로 진행한다.
각 단계는 조사 → 수정 → 검증 → 보고 순서로 수행한다.
```

---

## Phase 0. 작업 전 공통 조사

모든 단계 전 반드시 확인한다.

### 확인 파일

```text
backend/main.py
backend/infrastructure/di/container.py
backend/presentation/websocket/router.py
backend/presentation/websocket/handlers.py
backend/infrastructure/coalescing/backend_coalescing.py
backend/infrastructure/ls/ws_client.py
backend/domain/trading/execution_engine.py
frontend/src/infrastructure/api/api/ws.ts
frontend/src/infrastructure/binding.ts
frontend/src/infrastructure/coalescing/frontend_coalescing.ts
frontend/src/infrastructure/workers/workerManager.ts
frontend/src/application/stores/stores/appStore.ts
```

### 확인 질문

```text
이 코드는 실시간 hot path인가?
이 코드는 매 tick마다 실행되는가?
이 코드는 주문/체결 이벤트에 관여하는가?
이 코드는 UI 렌더링을 직접 유발하는가?
이 코드는 파일/로그/네트워크 I/O를 수행하는가?
```

---

## Phase 1. P0 안정화

### 1-1. 실시간 hot path 로그 제거

대상:

```text
backend/infrastructure/ls/ws_client.py
frontend/src/infrastructure/api/api/ws.ts
frontend/src/infrastructure/binding.ts
frontend/src/application/stores/stores/appStore.ts
```

작업:

```text
매 tick info 로그 제거
console.log 제거 또는 diagnostic flag 뒤로 이동
원본 메시지 출력 제거
샘플링 metrics로 대체
```

검증:

```text
실시간 수신 루프에 logger.info(raw_message) 없음
real-data handler에 console.log 없음
npm run build 성공
```

주의:

로그를 모두 없애면 디버깅이 어려우므로, 진단 모드 flag를 둘 수 있다.

---

### 1-2. Worker request id 불일치 수정

대상:

```text
frontend/src/infrastructure/workers/workerManager.ts
```

문제:

public method와 `sendRequest()`가 서로 다른 id를 만들 가능성이 있다.

목표:

```text
요청 ID 생성 위치 단일화
pendingRequests key와 worker message id 일치
```

검증:

```text
worker 요청 → 응답 id 일치
기존 worker 관련 테스트 실행
npm run build 성공
```

---

### 1-3. DI Container 단일화 설계 및 적용

대상:

```text
backend/main.py
backend/infrastructure/di/container.py
backend/presentation/websocket/router.py
backend/presentation/websocket/handlers.py
backend/presentation/api/download.py
```

목표:

```text
Container() 직접 생성 금지
FastAPI app.state.container 또는 dependency injection 사용
main.py에서 override한 단일 container만 사용
```

검증:

```text
state_sync_service 인스턴스 하나인지 확인
backend_coalescing 인스턴스 하나인지 확인
engine_ready 상태 일관성 확인
backend import 오류 없음
```

주의:

이 단계는 영향 범위가 크므로 반드시 작은 단위로 한다.

---

### 1-4. WebSocket 프로토콜 현황 확정

대상:

```text
backend/infrastructure/coalescing/backend_coalescing.py
frontend/src/infrastructure/api/api/ws.ts
frontend/src/infrastructure/websocket/client.ts
frontend/proto/event.proto
```

작업:

```text
현재 실제 사용 중인 WS client가 어느 파일인지 확인
backend가 실제로 보내는 binary format 확인
frontend decoder가 해당 format을 처리하는지 확인
미사용 WS client 제거 또는 deprecated 표시
```

목표:

```text
Control/Account는 JSON
Market은 단일 binary batch protocol
```

검증:

```text
real-data 이벤트가 누락 없이 도달
binary decode 실패 로그 없음
프로토콜 문서 작성
```

---

### 1-5. WebSocket outbound queue 도입

대상:

```text
backend/infrastructure/coalescing/backend_coalescing.py
backend/application/trading/state_sync_service.py
backend/presentation/websocket/router.py
```

목표:

```text
client별 queue
market 이벤트 latest-only drop 가능
order/fill/account 이벤트 drop 금지
느린 client 격리
```

검증:

```text
느린 클라이언트 시뮬레이션
queue depth metrics 확인
다른 이벤트 전송 지연 없음
```

---

## Phase 2. 실시간 파이프라인 정규화

### 2-1. EventBus/RingBuffer 도입

목표:

```text
브로커 수신 → EventBus → Strategy/UI/Journal로 분기
```

구조:

```text
MarketTickQueue: bounded, latest-by-symbol
OrderEventQueue: ordered, no-drop
AccountQueue: coalesced snapshot
```

검증:

```text
drop count 측정
latency p95 측정
주문/체결 이벤트 drop 없음
```

---

### 2-2. 시세/계좌/제어 채널 분리

권장 채널:

```text
/ws/market
/ws/account
/ws/control
```

효과:

```text
시세 폭주가 설정/진행률/체결 이벤트를 막지 않음
디버깅 용이
프로토콜 단순화
```

---

### 2-3. latency metrics 도입

**상태: ✅ 완료** (2026-05-19 - P2-2-7 Dashboard/Alert 구현)

필수 timestamp:

```text
broker_recv_ts
backend_ingest_ts
backend_flush_ts
frontend_recv_ts
frontend_apply_ts
order_submit_ts
fill_recv_ts
```

검증:

```text
최근 1분 avg/p95 표시
drop count 표시
queue depth 표시
```

---

## Phase 3. Trading Engine 고도화

### 3-1. 주문 상태기계 명확화

상태:

```text
NEW
VALIDATED
SUBMITTED
ACKED
PARTIALLY_FILLED
FILLED
CANCEL_REQUESTED
CANCELED
REJECTED
UNKNOWN_RECOVERY
```

작업:

```text
Order entity 상태 정의 통일
브로커 주문번호 mapping journal화
체결 기준 포지션 업데이트 유지
```

검증:

```text
부분체결
전체체결
거부
취소
재시작 후 복구
```

---

### 3-2. Safety Layer 강화

검증 항목:

```text
자동매매 ON/OFF
장 시간
일일 한도
종목당 한도
최대 보유 종목 수
중복 주문
미체결 주문
브로커 연결 상태
거래정지/주의 종목
```

---

### 3-3. Paper/Live 완전 분리

목표:

```text
테스트모드가 실전 주문 경로를 절대 호출하지 않음
실전모드가 가상 체결 로직을 섞지 않음
```

검증:

```text
mode별 주문 경로 테스트
mode 전환 시 상태 초기화/동기화 확인
```

---

## Phase 4. Frontend HTS 구조 강화

### 4-1. React와 hot path 분리

목표:

```text
React: layout/settings/low frequency
Web Components: realtime table/high frequency
Worker: heavy calculation
Hot Store: mutable realtime state
Snapshot: UI read model
```

검증:

```text
real-data마다 React rerender 발생하지 않음
FPS 안정
WebComponent updateData만 필요한 주기로 호출
```

---

### 4-2. Snapshot Publisher 정리

현재 여러 곳에서 `createSnapshot(appStore.getState())`가 호출된다.

목표:

```text
snapshot 생성 위치 중앙화
프레임당 최대 1회
변경 없는 snapshot skip
```

---

### 4-3. Web Worker 계산 경로 강화

대상:

```text
sector rank
buy target
sell condition
```

목표:

```text
메인 스레드 계산 제거
요청 취소/최신 요청 우선 처리
응답 id 정확성 보장
```

---

## Phase 5. Persistence/Recovery 강화

### 5-1. Atomic JSON Write

현재 JSON 파일 기반 저장소는 atomic write 여부를 확인해야 한다.

목표:

```text
.tmp 파일 작성
fsync
rename
백업 유지
```

---

### 5-2. SQLite WAL 도입 검토

대상:

```text
order journal
fill journal
position snapshot
trade history
```

1인 로컬 앱에서는 SQLite WAL이 복구성과 단순성의 균형이 좋다.

---

### 5-3. 장마감 분석 저장소 분리

대상:

```text
historical daily data
avg trade amount
sector layout
```

후보:

```text
DuckDB
Parquet
SQLite
```

---

## Phase 6. 검증 체계

### 필수 테스트

```text
실시간 tick burst 테스트
WS 재연결 테스트
구독 복구 테스트
부분체결 테스트
주문 거부 테스트
다운로드 중 실시간 수신 영향 테스트
프론트 FPS 테스트
메모리 누수 테스트
```

### 필수 지표

```text
tick ingest latency
backend flush latency
frontend apply latency
UI frame time
worker response time
queue depth
drop count
reconnect count
```

---

## 하위 AI 작업 규칙

1. P0를 먼저 해결한다.
2. 실시간 hot path에 로그, 파일 I/O, 무거운 연산을 넣지 않는다.
3. 주문/체결 이벤트는 절대 drop하지 않는다.
4. 시세 이벤트는 latest-only coalescing 가능하다.
5. 프로토콜을 바꿀 때는 백엔드/프론트 decoder를 함께 확인한다.
6. DI 인스턴스는 하나만 사용한다.
7. React 렌더링과 실시간 tick 처리를 분리한다.
8. 수정 후 반드시 build/test/검색 검증을 한다.

---

## 권장 실행 순서 요약

```text
1. hot path 로그 제거
2. Worker id 버그 수정
3. DI container 단일화
4. WS protocol 실사용 경로 확정
5. outbound queue 도입
6. EventBus/RingBuffer 도입
7. 주문 상태기계 강화
8. frontend hot store/snapshot 정리
9. persistence/recovery 강화
10. latency metrics 기반 최적화
```

이 순서가 Cascade 기준 궁극 아키텍처로 가는 가장 안전한 경로다.
