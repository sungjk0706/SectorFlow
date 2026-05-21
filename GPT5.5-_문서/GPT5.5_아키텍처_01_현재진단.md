# Cascade 아키텍처 01 - 현재구조 진단

## 조사 기준

이 진단은 코드 기반으로 수행했다. 주요 확인 파일은 다음이다.

```text
backend/main.py
backend/infrastructure/di/container.py
backend/infrastructure/ls/ws_client.py
backend/infrastructure/ls/real_time_provider.py
backend/infrastructure/coalescing/backend_coalescing.py
backend/presentation/websocket/router.py
backend/application/trading/state_sync_service.py
backend/domain/trading/execution_engine.py
backend/presentation/api/download.py
backend/application/services/download_pipeline.py
backend/infrastructure/market_data/hybrid_strategy.py
frontend/src/main.tsx
frontend/src/infrastructure/api/api/ws.ts
frontend/src/infrastructure/websocket/client.ts
frontend/src/infrastructure/binding.ts
frontend/src/infrastructure/coalescing/frontend_coalescing.ts
frontend/src/infrastructure/workers/workerManager.ts
frontend/src/application/stores/stores/appStore.ts
```

---

## 현재 구조 요약

현재 프로젝트는 일반 웹앱이 아니라 HTS형 구조를 일부 지향하고 있다.

현재 흐름은 대략 다음과 같다.

```text
LS/Kiwoom Broker API
→ Backend WS/REST Adapter
→ Backend Coalescing
→ FastAPI WebSocket
→ Frontend WS Client
→ Frontend Coalescing
→ Zustand Store / Snapshot
→ React Layout + Web Components UI
```

주문 흐름은 대략 다음과 같다.

```text
TradeSignal
→ ExecutionEngine
→ SafetyLayer
→ Broker Order API
→ Broker Fill WS
→ handle_fill
→ Position Update
→ StateSyncService
→ Frontend account-update
```

---

## 잘 되어 있는 점

### 1. 하이브리드 브로커 방향성

코드에는 키움증권과 LS증권을 분리하려는 구조가 있다.

```text
키움: 주문/확정 데이터/계좌
LS: 실시간 데이터
```

관련 파일:

```text
backend/infrastructure/market_data/hybrid_strategy.py
backend/infrastructure/di/container.py
```

이 방향은 1인 로컬 자동매매 시스템에 적합하다.

---

### 2. Backend Coalescing 존재

파일:

```text
backend/infrastructure/coalescing/backend_coalescing.py
```

종목 코드 기준으로 최신 이벤트를 덮어쓰기 하는 구조가 있다.

```text
pending_map[code] = event
flush_interval_ms = 10
flush_threshold = 200
```

이는 실시간 burst traffic을 줄이기 위한 좋은 방향이다.

---

### 3. Frontend Coalescing 존재

파일:

```text
frontend/src/infrastructure/coalescing/frontend_coalescing.ts
```

프론트에서도 종목 기준 최신 이벤트만 남기고 `requestAnimationFrame` 기준으로 flush하는 구조가 있다.

이는 React 렌더링 폭주를 줄이기 위한 올바른 방향이다.

---

### 4. Web Worker 구조 존재

파일:

```text
frontend/src/infrastructure/workers/workerManager.ts
```

계산 부하를 메인 스레드에서 분리하려는 구조가 있다.

HTS급 UI에서는 메인 스레드 블로킹 방지가 중요하므로 방향은 좋다.

---

### 5. 주문 실행 fire-and-forget 구조

파일:

```text
backend/domain/trading/execution_engine.py
```

주문 실행을 백그라운드 task로 넘기는 구조가 있다.

```python
asyncio.create_task(self._execute_order_background(order))
```

이는 주문 API 지연이 메인 이벤트 흐름을 직접 막지 않게 하려는 방향이다.

---

## P0 문제: 즉시 개선 대상

P0는 실시간 데이터 지연, 블로킹, 왜곡, 체결 상태 불일치 가능성이 있는 항목이다.

---

### P0-1. 실시간 수신 루프의 과도한 info 로그 ✅ 완료

파일:

```text
backend/infrastructure/ls/ws_client.py
```

문제:

실시간 수신 루프에서 매 메시지마다 원본/파싱/구독목록 로그를 `info`로 출력한다.

위험:

```text
로그 I/O로 이벤트 루프 지연
장중 burst traffic 처리 지연
디스크/콘솔 병목
데이터 수신 순서 지연 가능성
```

개선:

```text
hot path info 로그 제거
샘플링 로그로 대체
진단 모드일 때만 원본 메시지 출력
metrics counter 사용
```

수정 완료 (2026-05-18):
- `ws_client.py`: info 로그 → debug 로그 변경, 100건당 1건 샘플링 로그 추가
- `ws.ts`: 이벤트 수신/핸들러 console.log 제거
- `binding.ts`: 이벤트 핸들러 console.log 제거
- `appStore.ts`: 상태 변경 console.log 제거
- 검증: logger.info(raw_message) 없음, console.log 없음, npm run build 성공

---

### P0-2. WebSocket 프로토콜 혼재 ✅ 완료

확인된 방식:

```text
JSON text
zlib compressed JSON binary
single Protobuf binary
length-prefixed Protobuf batch binary
```

관련 파일:

```text
backend/infrastructure/coalescing/backend_coalescing.py
frontend/src/infrastructure/api/api/ws.ts
frontend/src/infrastructure/websocket/client.ts
```

위험:

```text
binary frame 디코딩 실패
이벤트 누락
real-data 미도달
데이터 왜곡
디버깅 난이도 증가
```

개선:

```text
Control/State 채널과 Market Tick 채널 분리
Market Tick은 단일 binary batch protocol로 통일
JSON/protobuf/zlib 혼재 제거
프로토콜 문서화
```

수정 완료 (2026-05-18):
- `api/ws.ts`: protobufjs 추가, loadProtobuf 함수 추가, decodeProtobufBatch 함수 추가, _handleBinaryFrame을 length-prefixed Protobuf batch 디코딩으로 변경, raw_data 타입 처리 추가, _extractCode 함수 추가
- `websocket/client.ts`: protobufjs 추가, loadProtobuf 함수 추가, decodeProtobufBatch 함수 추가, onmessage를 length-prefixed Protobuf batch 디코딩으로 변경, send 메서드를 JSON text 전송으로 변경
- 프로토콜 문서 작성: `GPT5.5_아키텍처_02_프로토콜.md`
- 채널 분리 완료: Control/State 채널(JSON text) + Market Tick 채널(length-prefixed Protobuf batch binary)
- 검증: npm run build 성공

---

### P0-3. DI Container 인스턴스 분산 가능성 ✅ 완료

파일:

```text
backend/main.py
backend/presentation/websocket/router.py
backend/presentation/websocket/handlers.py
backend/presentation/api/trading.py
```

문제:

여러 곳에서 `Container()`를 새로 생성한다.

위험:

```text
main.py에서 override한 설정이 다른 Container에 반영되지 않을 수 있음
state_sync_service 인스턴스 분산
backend_coalescing 인스턴스 분산
engine_ready 상태 불일치
실시간 이벤트가 다른 객체에 쌓임
```

개선:

```text
FastAPI app.state.container에 단일 인스턴스 저장
router/handler에서는 app.state 또는 dependency로 주입
Container() 직접 생성 금지
```

수정 완료 (2026-05-18):
- `main.py`: app.state.container에 container 저장, ConnectionManager 초기화 시 app 전달
- `router.py`: ConnectionManager에 app 참조 추가, connect/disconnect 메서드에서 app.state.container 사용
- `handlers.py`: WebSocketHandler에 app 참조 추가, init/가격업데이트에서 app.state.container 사용
- `trading.py`: 모든 엔드포인트에서 request.app.state.container 사용, 모듈 레벨 container 변수 제거
- 검증: Container() 직접 생성 제거 (main.py의 전역 container 제외, 테스트 파일 제외)

---

### P0-4. WebSocket 브로드캐스트 순차 전송 ✅ 완료

파일:

```text
backend/infrastructure/coalescing/backend_coalescing.py
backend/application/trading/state_sync_service.py
backend/presentation/websocket/router.py
```

문제:

```python
for websocket in connections:
    await websocket.send_text(...)
```

위험:

```text
느린 연결 하나가 전송 루프 지연
상태 이벤트와 시세 이벤트가 같은 통로에서 지연
연결 실패 cleanup 지연
```

개선:

```text
client별 outbound queue
latest-only drop policy
느린 client 격리
시세 채널과 상태 채널 분리
```

수정 완료 (2026-05-18):
- `router.py`: broadcast 메서드를 asyncio.gather로 병렬 전송으로 변경
- `backend_coalescing.py`: flush 메서드를 asyncio.gather로 병렬 전송으로 변경
- `state_sync_service.py`: broadcast_state 메서드를 asyncio.gather로 병렬 전송으로 변경
- 참고: 완전한 해결(client별 outbound queue, latest-only drop policy 등)은 P1으로 이동 필요

---

### P0-5. Worker 요청 ID 불일치 가능성 ✅ 완료

파일:

```text
frontend/src/infrastructure/workers/workerManager.ts
frontend/src/workers/calculationWorker.ts
```

문제:

public method에서 id를 만들고, `sendRequest()` 내부에서도 다른 id를 만든다.

위험:

```text
Worker 응답 id와 pendingRequests id 불일치
응답 유실
계산 결과 반영 실패
타임아웃 증가
```

개선:

```text
id 생성 위치 단일화
sendRequest가 message.id를 직접 설정하거나 외부 id를 그대로 사용
```

수정 완료 (2026-05-18):
- `workerManager.ts`: sendRequest()에서만 ID 생성하도록 단일화 (message.id 없으면 자동 생성)
- `workerManager.ts`: public 메서드에서 id 필드 제거
- `calculationWorker.ts`: WorkerMessage.id를 optional로 변경
- `calculationWorker.ts`: ID가 없는 경우 에러 처리 추가
- 검증: npm run build 성공

---

### P0-6. 프론트 hot path console.log 과다 ✅ 완료

파일:

```text
frontend/src/infrastructure/api/api/ws.ts
frontend/src/infrastructure/binding.ts
frontend/src/application/stores/stores/appStore.ts
frontend/src/main.tsx
```

문제:

실시간 이벤트 수신, 핸들러 실행, real-data 처리마다 console 출력이 있다.

위험:

```text
브라우저 메인 스레드 블로킹
DevTools 열림 상태에서 급격한 성능 저하
실시간 UI 반응 지연
```

개선:

```text
hot path console 제거
diagnostic flag 기반 샘플링
metrics ring buffer 사용
```

수정 완료 (2026-05-18):
- P0-1 수정과 함께 수행됨
- `ws.ts`: 이벤트 수신/핸들러 console.log 제거, 등록되지 않은 이벤트는 debug 모드에서만 로그
- `binding.ts`: 모든 이벤트 핸들러 console.log 제거
- `appStore.ts`: 상태 변경 console.log 제거
- `main.tsx`: FPS 모니터링 로그는 유지 (성능 측정용)
- 검증: npm run build 성공

---

## P1 문제: HTS급 구조 강화 대상

### P1-1. Hot state와 UI state 경계 불명확 ✅ 완료

현재 `applyRealData()`는 mutable update와 Zustand setState를 함께 사용한다.

의도는 성능 최적화로 보이나, React 구독/렌더 트리거와 Web Components 소비 구조가 더 명확해야 한다.

개선:

```text
Hot Mutable Store
→ Snapshot Publisher
→ UI Read Model
→ React/WebComponent Consumer
```

수정 완료 (2026-05-18):
- appStore.ts: applyRealData에서 setState 제거, 직접 mutation만 수행, createSnapshot 호출 추가. applyInitialSnapshot, applyAccountUpdate, applySectorScores, applyBuyTargetsUpdate, applySectorStocksRefresh에도 createSnapshot 호출 추가
- snapshotStore.ts: JSON deep copy 대신 구조적 공유 기반 deep copy 구현
- frontend_coalescing.ts: flush()에서 중복 createSnapshot 호출 제거
- binding.ts: 이벤트 핸들러에서 중복 createSnapshot 호출 제거
- 검증: npm run build 성공

---

### P1-2. 채널 분리 필요 ✅ 완료

현재 상태 이벤트, 진행률 이벤트, 실시간 시세 이벤트가 같은 WebSocket 경로에 섞일 수 있다.

개선:

```text
/ws/control  : engine-ready, settings, progress
/ws/account  : account, order, fill, position
/ws/market   : tick/orderbook/sector realtime binary
```

1인 로컬 앱이라도 채널 분리는 디버깅과 지연 격리에 유리하다.

수정 완료 (2026-05-18):
- router.py: `/ws/control`, `/ws/account`, `/ws/market` 3개 엔드포인트 추가, `_validate_token` 공통 함수 추출
- handlers.py: `handle_message`에 `channel` 파라미터 추가, 채널별 라우팅
- api/ws.ts: `WSClient`에 `path` 생성자 파라미터 추가, 3개 클라이언트 인스턴스 export
- binding.ts: 이벤트를 3개 채널로 분리 바인딩
- main.tsx: 3개 클라이언트 연결
- 검증: npm run build 성공

---

### P1-3. 주문/체결 상태기계 명확화 필요 ✅ 완료

현재 `ExecutionEngine`은 주문/체결 처리 구조가 있으나 최종 상태기계 문서화가 부족하다.

필요 상태:

```text
NEW → VALIDATED → SUBMITTED → ACKED → PARTIALLY_FILLED → FILLED
  ↓        ↓          ↓         ↓
  └──→ REJECTED ←──────────────┘
```

수정 완료 (2026-05-18):
- state_manager.py: OrderStatus enum 추가, ALLOWED_TRANSITIONS 상태 전이 규칙 정의, _handle_order_status_changed에 전이 검증 로직 추가
- entities.py: OrderStatus enum 통합 (8개 상태로 확장)
- execution_engine.py: 모든 상태 변경을 OrderStatus enum으로 변경, 키움/LS 주문 접수 시 SUBMITTED로 변경
- 검증: npm run build 성공

---

## P2 문제: 운영 안정성 대상

### P2-1. 다운로드/배치 파이프라인 격리 ✅ 완료

파일:

```text
backend/application/services/download_pipeline.py
```

다운로드는 장 마감 또는 백그라운드 작업이다.

개선:

```text
장중 실시간 경로와 완전 격리
취소 기능 구현
진행 상태 저장소 구현
atomic file write
작업 중복 실행 방지 lock
```

수정 완료 (2026-05-18):
- download.py: 중복 실행 방지 lock 구현 (_download_lock, _download_running)
- download.py: 전역 파이프라인 인스턴스 관리 (_current_pipeline)
- download.py: 취소 기능 구현 (/cancel 엔드포인트)
- download.py: 진행 상태 저장소 구현 (_current_progress, /progress 엔드포인트)
- avg_amt_cache.py: atomic file write 구현 (save_avg_amt_cache, save_avg_amt_cache_v2)
- avg_amt_cache.py: 임시 파일 쓰기 후 os.replace 패턴 적용
- 브로커 클라이언트 격리 검토: ws_client.py (실시간) vs rest_client.py (다운로드) 이미 격리됨 확인
- 검증: python -m py_compile 성공

---

### P2-2. latency metrics 부족

필요 지표:

```text
broker_recv_ts
backend_ingest_ts
coalescing_flush_ts
frontend_recv_ts
ui_apply_ts
order_submit_ts
fill_recv_ts
state_sync_ts
```

목표는 감이 아니라 숫자로 지연을 판단하는 것이다.

---

#### 단계별 계획

**P2-2-1: Latency tracing 데이터 구조 정의 ✅ 완료**

수정 완료 (2026-05-18):
- infrastructure/metrics/latency.py: LatencyStage enum, LatencyTrace dataclass, LatencyThresholds dataclass, LatencyMetrics collector 클래스 정의
- 검증: python -m py_compile 성공
- LatencyTrace dataclass 정의 (각 단계 timestamp 포함)
- LatencyMetrics collector 클래스 정의
- 환경별 임계값 설정 (dev/prod)

**P2-2-2: Backend latency 측정 포인트 추가**
- broker_recv_ts: ws_client.py 메시지 수신 시점
- backend_ingest_ts: coalescing.py 이벤트 ingest 시점
- coalescing_flush_ts: coalescing.py flush 시점

**P2-2-3: Frontend latency 측정 포인트 추가**
- frontend_recv_ts: ws.ts 메시지 수신 시점
- ui_apply_ts: appStore.ts 상태 적용 완료 시점

**P2-2-4: 주문/체결 latency 측정**
- order_submit_ts: execution_engine.py 주문 제출 시점
- fill_recv_ts: fill 이벤트 수신 시점
- state_sync_ts: state_sync_service.py 동기화 완료 시점

**P2-2-5: Metrics collector 구현**
- latency 수집 및 집계
- percentile 계산 (p50, p95, p99)
- 로그/메트릭 export

**P2-2-6: Protobuf 확장**
- 이벤트 메시지에 latency tracing 필드 추가
- frontend/backend 동기화

**P2-2-7: Dashboard/Alert 구현 ✅ 완료**

수정 완료 (2026-05-19):
- backend/app/core/metrics/latency.py: LatencyMetrics collector 구현 완료
- backend/app/web/routes/metrics.py: Backend API 엔드포인트 구현 완료
- frontend/src/api/client.ts: Metrics API 클라이언트 구현 완료
- frontend/src/pages/metrics-dashboard.ts: Dashboard UI 구현 완료
- frontend/src/main.ts: 라우트 등록 완료
- frontend/src/layout/sidebar.ts: 메뉴 항목 추가 완료
- 검증: python -m py_compile 성공, npm run build 성공

---

### P2-3. 재연결 후 구독 복구 검증 필요

LS WebSocket에는 pending subscription 복구 구조가 있으나, 실제 재연결 후 listen loop 재시작과 구독 복구 타이밍은 별도 검증이 필요하다.

---

## P3 문제: 장기 고도화 대상

- Rust 또는 native extension hot path 검토
- SQLite WAL 기반 이벤트 저널
- DuckDB/Parquet 장마감 분석 저장소
- SharedArrayBuffer 기반 프론트 tick buffer
- WebAssembly 계산 엔진
- pyzmq/Redis Stream 도입 여부 재평가

---

## 현재 진단 결론

현재 프로젝트는 HTS형 방향성이 있으나, 아직 다음 문제가 궁극 목표를 방해한다.

```text
1. hot path 로그와 console 과다
2. WebSocket 프로토콜 혼재
3. DI 인스턴스 분산 가능성
4. 순차 브로드캐스트 구조
5. Worker request id 불일치 가능성
6. 실시간 state와 UI snapshot 경계 불명확
7. 다운로드/배치와 장중 실시간 경로 격리 부족
```

가장 먼저 P0 항목을 제거해야 한다.
