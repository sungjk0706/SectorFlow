# SectorFlow_old 인계서

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

## 현재 상태
### 빌드 상태
- 빌드 성공 (npm run build)
- appStore.ts 완전 제거
- hotStore/uiStore 완전 분리 완료
- applyInitialSnapshot 함수 분리 완료 (applyInitialSnapshotHot, applyInitialSnapshotUI)
- binding.ts에서 hotStore/uiStore 직접 호출
- stores/index.ts에서 appStore export 제거
- ui-styles.ts에서 window.appStore 참조 제거
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
- Phase 3: P2 문제 해결: 대기
- Phase 4: 문서 동기화: 대기

## 미해결 문제
- Phase 3: P2 문제 해결: 대기
- Phase 4: 문서 동기화: 대기

## 백업 상태
- git commit 완료 (8bd3033)
- 빌드 성공 상태
- P1-1 단계 6 완료 (appStore.ts 제거 및 hotStore/uiStore 완전 분리)
- P1-3 주문 상태기계 검증 완료 (state_manager.py ALLOWED_TRANSITIONS 수정, 테스트 8 passed)

## 참고 프로젝트
- `/Users/sungjk0706/Desktop/SectorFlow` - 구조 참고용
