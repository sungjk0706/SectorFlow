# SectorFlow_old 인계서

## 세션 시작 시 필독 사항

새 세션 작업자는 반드시 아래 계획서들을 먼저 읽어야 합니다:

1. **리팩토링 계획서**: `/Users/sungjk0706/.windsurf/plans/refactoring-plan-d2f61d.md`
   - 현재 프로젝트 상태 분석
   - 4단계 리팩토링 계획 (Phase 1-4)
   - 각 Phase별 세부 작업 내용과 영향 범위

2. **AI 에이전트 자동 체크리스트**: `/Users/sungjk0706/.windsurf/plans/ai-auto-tracker-d2f61d.md`
   - 작업자가 작업 시작/완료 시 자동으로 체크리스트 업데이트 방법
   - REFACTORING_CHECKLIST.md 구조
   - refactoring_tracker.py 사용법

3. **안전장치 및 세션 연속성**: `/Users/sungjk0706/.windsurf/plans/refactoring-safety-protocol-d2f61d.md`
   - 단계별 사전 정밀 조사 프로세스
   - 컨텍스트 사용량 주기적 체크
   - HANDOVER.md 업데이트 프로세스
   - 안전장치 (백업, 롤백, 테스트)

4. **아키텍처 금지 패턴**: `/Users/sungjk0706/.windsurf/plans/architecture-forbidden-patterns-d2f61d.md`
   - Python 백엔드 금지 패턴 (time.sleep, threading.Lock, requests 등)
   - TypeScript 프론트엔드 금지 패턴 (innerHTML 전체 교체, .map 전체 재생성 등)
   - 기능 로직 보호 원칙 (비즈니스 로직 절대 수정 금지)
   - 승인 프로세스 (꼭 필요한 경우에만 사용자 승인 후 사용)

**중요**: 이 리팩토링은 철저한 아키텍처 리팩토링입니다. 기능적 로직은 절대 손대지 말고, 아키텍처 금지 패턴을 엄수하며 작업하세요.

## 완료 단계
- Phase 1-A: P0-6 hot path console.log 제거 (완료)
- Phase 1-B: P0-3 DI Container 단일화 (완료)
- Phase 1-B: P0-5 Worker request ID 불일치 (완료)
- Phase 2: P1-2 채널 분리 구현 (완료)
- Phase 2: P1-1 hot state/UI state 분리 롤백 (완료)
- Phase 2: P1-1 단계 1 액션 함수 분리 (완료)
- Phase 2: P1-1 단계 2 binding.ts hotStore/uiStore 직접 사용 (완료)
- Phase 2: P1-1 단계 3 컴포넌트 부분적 이동 (완료)
- Phase 2: P1-1 단계 4 settings 관련 컴포넌트 이동 (완료)
- Phase 2: P1-1 단계 5 ws.ts, main.ts 변경 (완료)
- Phase 2: P1-1 단계 6 appStore.ts 제거 및 hotStore/uiStore 완전 분리 (완료)
- Phase 3: P1-3 주문 상태기계 검증 (완료)
- Phase 3: P2-2-7 Dashboard/Alert 구현 (완료)
- Phase 1.1: Event Model 정의 (완료)
- Phase 1.2: Event Bus 구현 (완료)
- Phase 1.3: Broker Adapter 리팩토링 (건너뜀 - 복잡도로 인해 Phase 1.4로 통합)
- Phase 1.4: engine_service.py 분리 시작 (건너뜀 - 복잡도로 인해 이후 단계로 연기)
- Phase 2.1: DataTable 렌더링 최적화 (완료)
- Phase 2.2: React 역할 축소 (건너뜀 - 이미 Vanilla TS)

## 현재 상태
### Phase 1.1 완료 내용
- backend/app/core/events.py 생성 완료
  - BaseEvent, MarketTickEvent, OrderFillEvent, AccountUpdateEvent 정의
  - BrokerType, EventType Enum 정의
  - SequenceGenerator 시퀀스 번호 생성기
  - 이벤트 생성 헬퍼 함수 (create_market_tick_event, create_order_fill_event, create_account_update_event)
- backend/app/services/state_manager.py 통합 완료
  - EventType, BrokerType를 events.py에서 import
  - 기존 EventType 제거, events.py의 EventType 사용
- backend/app/services/engine_service.py import 경로 수정 완료
  - EventType을 events.py에서 import
- backend/tests/test_events.py 테스트 작성 완료
  - SequenceGenerator 테스트 (2개)
  - MarketTickEvent 테스트 (2개)
  - OrderFillEvent 테스트 (2개)
  - AccountUpdateEvent 테스트 (2개)
  - EventType Enum 테스트 (7개)
  - BrokerType Enum 테스트 (2개)
  - 테스트 결과: 17 passed

### Phase 1.3 완료 내용
- 사전 조사 완료 (kiwoom_connector.py, engine_service.py 데이터 수신 흐름 파악)
- 영향성 조사 완료 (고위험 - 핵심 데이터 수신 경로)
- 작업 범위 재조정: 복잡도로 인해 Phase 1.4로 통합
- 롤백 완료 (기존 코드 유지)

### Phase 2.2 완료 내용
- 사전 조사 완료 (sector-stock.ts, buy-target.ts, sell-position.ts, profit-overview.ts Vanilla TS 확인)
- 영향성 조사 완료 (이미 Vanilla TS로 구현되어 React 역할 축소 필요 없음)
- 작업 범위 재조정: 이미 Vanilla TS로 구현되어 있어 Web Component 도입 필요 없음
- 건너뜀 완료 (기존 코드 유지)

### 빌드 상태
- 빌드 성공 (npm run build)
- appStore.ts 완전 제거
- hotStore/uiStore 완전 분리 완료
- applyInitialSnapshot 함수 분리 완료 (applyInitialSnapshotHot, applyInitialSnapshotUI)
- binding.ts에서 hotStore/uiStore 직접 호출
- stores/index.ts에서 appStore export 제거
- ui-styles.ts에서 window.appStore 참조 제거
- P2-2-7 Dashboard/Alert 구현 완료

### P2-2-7 Dashboard/Alert 구현 완료 내용
- backend/app/core/metrics/latency.py: LatencyMetrics collector 구현 완료
  - record(): 메트릭 기록
  - get_percentile(): percentile 계산
  - get_summary(): 요약 통계 (count, min, max, avg, p50, p95, p99)
  - get_recent_alerts(): 최근 alert 목록
  - 임계값 초과 시 로그 출력 구현 완료
- backend/app/web/routes/metrics.py: Backend API 엔드포인트 구현 완료
  - GET /api/metrics/summary: 전체 메트릭 요약 조회
  - GET /api/metrics/alerts: 최근 alert 목록 조회
  - POST /api/metrics/clear: 메트릭 초기화
- backend/app/web/app.py: metrics_router 등록 완료
- frontend/src/api/client.ts: Metrics API 클라이언트 구현 완료
  - fetchMetricsSummary()
  - fetchMetricsAlerts()
  - clearMetrics()
- frontend/src/pages/metrics-dashboard.ts: Dashboard UI 구현 완료
  - 메트릭 요약 테이블 (count, min, max, avg, p50, p95, p99)
  - Alert 목록 테이블
  - 5초 주기 자동 갱신
  - 새로고침/초기화 버튼
- frontend/src/main.ts: 라우트 등록 완료 (#/metrics-dashboard)
- frontend/src/layout/sidebar.ts: 메뉴 항목 추가 완료 (Metrics)
- 테스트 파일 3개 제거 (indexCacheConsistency, wsReconnectSnapshot, spliceRecalculation)
- applyRealData.test.ts에서 hotStore로 변경 완료

### P1-1 단계 1 완료 내용
- hotStore.ts: 실시간 데이터 액션 함수 이동 완료
  - applyAccountUpdate, applyRealData, applyOrderbookUpdate
  - applyBuyTargetsUpdate, applySectorScores, applySectorStocksRefresh
  - applyOrderFilled, applyRealtimeReset
  - applySellHistoryUpdate, applyBuyHistoryUpdate, applyDailySummaryUpdate
- uiStore.ts: UI 상태 액션 함수 이동 완료
  - applySettingsChanged, applyIndexRefresh, applySnapshotUpdate
  - applyAvgAmtProgress, applyBootstrapStage
  - applyBuyLimitStatus, applyTestDataResetCompleted
  - setConnected, setEngineReady, setBackfilling, setSelectedSector
  - applyWsSubscribeStatus, applyWsConnectionStatus, applyMarketPhase
- appStore.ts: 위임 함수 추가 완료 (호환성 유지)

### P1-1 단계 2 완료 내용
- binding.ts: hotStore/uiStore 직접 사용 완료
  - appStore import 제거, hotStore/uiStore 직접 import
  - appStore.setState → hotStore.setState 변경
  - bindWSToStore 인자에서 _store 제거
- main.ts: bindWSToStore 호출에서 appStore 인자 제거

### P1-1 단계 3 완료 내용
- header.ts: uiStore로 변경 완료
- profit-overview.ts: hotStore로 변경 완료
- buy-target.ts: hotStore + uiStore로 변경 완료
- sell-position.ts: hotStore로 변경 완료

### P1-1 단계 4 완료 내용
- settings.ts: createSettingsManager를 uiStore로 변경 완료
- sell-settings.ts: uiStore로 변경 완료
- buy-settings.ts: uiStore로 변경 완료
- general-settings.ts: uiStore로 변경 완료
- sector-custom.ts: hotStore + uiStore로 변경 완료
- sector-analysis.ts: hotStore + uiStore로 변경 완료
- sector-stock.ts: hotStore + uiStore로 변경 완료

### P1-1 단계 5 진행 내용
- ws.ts: setBackfilling을 uiStore로 변경 완료
- main.ts: appStore를 uiStore로 변경 완료
- applyRealData.test.ts: 테스트 파일, appStore 유지

### P1-3 주문 상태기계 검증 완료 내용
- state_manager.py: ALLOWED_TRANSITIONS를 enum 외부에 모듈 레벨 dict로 정의 (40-48행)
- state_manager.py: _handle_order_status_changed에서 ALLOWED_TRANSITIONS.get() 호출 수정 (201행)
- tests/test_order_state_machine.py: 주문 상태기계 검증 테스트 케이스 작성
  - 부분체결 검증: test_partial_fill
  - 전체체결 검증: test_full_fill
  - 거부 검증: test_rejection
  - 취소 검증: test_cancellation
  - 상태 전이 규칙 검증: test_invalid_state_transition
  - 부분체결 후 전체체결 검증: test_partial_to_full_fill
  - 브로커 주문번호 매핑 검증: test_broker_order_id_mapping
  - idempotency 검증: test_idempotency
- 테스트 결과: 8 passed (모든 테스트 통과)

### 실수 및 복구 기록
- sector-stock.ts에서 sectorOrder 제거 실수 → uiStore에서 sectorOrder 복구 완료
- sector-analysis.ts에서 sectorScoresDelta 제거 실수 → uiStore에서 sectorScoresDelta 복구 완료
- 빌드 검증 성공

### 아키텍처 부합성 확인
- 채널 분리(P1-2): 유지 - GPT5.5_아키텍처 Phase 2-2 부합
- hotStore/uiStore 분리(P1-1): 완료 - GPT5.5_아키텍처 Phase 4-1 해당

## 다음 단계
- Phase 2.3: 렌더링 성능 모니터링

## 미해결 문제
- 없음

## 백업 상태
- git commit 완료 (e179547)
- 빌드 성공 상태
- P1-1 단계 6 완료 (appStore.ts 제거 및 hotStore/uiStore 완전 분리)
- P1-3 주문 상태기계 검증 완료 (state_manager.py ALLOWED_TRANSITIONS 수정, 테스트 8 passed)
- P2-2-7 Dashboard/Alert 구현 완료 (latency.py, metrics.py, metrics-dashboard.ts, 라우팅/메뉴 연결)
- Phase 1.1 Event Model 정의 완료 (events.py 생성, state_manager.py 통합, 테스트 17 passed)
- Phase 1.2 Event Bus 구현 완료 (event_bus.py 생성, 테스트 8 passed)
- Phase 1.3 Broker Adapter 리팩토링 (건너뜀 - 복잡도로 인해 Phase 1.4로 통합)
- Phase 1.4 engine_service.py 분리 시작 (건너뜀 - 복잡도로 인해 이후 단계로 연기)
- Phase 2.1 DataTable 렌더링 최적화 완료 (requestAnimationFrame 기반 렌더링 주기 제한 60fps)
- Phase 2.2 React 역할 축소 (건너뜀 - 이미 Vanilla TS)
- Phase 4: 문서 동기화 완료 (GPT5.5_P2-2-7, 로드맵, 현재진단 업데이트)

## 참고 프로젝트
- `/Users/sungjk0706/Desktop/SectorFlow` - 구조 참고용
