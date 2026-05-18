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

## 현재 상태
### 빌드 상태
- 빌드 성공 (npm run build)
- binding.ts: hotStore/uiStore 직접 사용, 채널 분리 유지
- main.ts: bindWSToStore 인자 제거

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

### 실수 및 복구 기록
- sector-stock.ts에서 sectorOrder 제거 실수 → uiStore에서 sectorOrder 복구 완료
- sector-analysis.ts에서 sectorScoresDelta 제거 실수 → uiStore에서 sectorScoresDelta 복구 완료
- 빌드 검증 성공

### 아키텍처 부합성 확인
- 채널 분리(P1-2): 유지 - GPT5.5_아키텍처 Phase 2-2 부합
- hotStore/uiStore 분리(P1-1): 단계 4 완료, 단계 5 진행 중 - GPT5.5_아키텍처 Phase 4-1 해당

## 다음 단계

### P1-1 hot state/UI state 분리 (단계적 접근 - 아키텍처 Phase 4-1)
**제안된 접근 방식:**

**단계 1: hotStore/uiStore에 액션 함수 이동** (완료)
- appStore.ts의 액션 함수를 hotStore.ts/uiStore.ts로 분리
- appStore는 호환성을 위해 임시 유지
- 빌드 검증

**단계 2: binding.ts에서 hotStore/uiStore 사용** (완료)
- 이벤트 핸들러를 hotStore/uiStore로 분배
- appStore 호출을 hotStore/uiStore 호출로 변경
- 빌드 검증

**단계 3: 컴포넌트 순차적 이동** (완료)
- header.ts: uiStore로 변경
- profit-overview.ts: hotStore로 변경
- buy-target.ts: hotStore + uiStore로 변경
- sell-position.ts: hotStore로 변경
- 빌드 검증

**단계 4: settings.ts 수정** (완료)
- createSettingsManager를 uiStore로 변경
- 나머지 컴포넌트 이동
- 빌드 검증

**단계 5: appStore 제거** (진행 중)
- ws.ts: setBackfilling을 uiStore로 변경 완료
- main.ts: appStore를 uiStore로 변경 완료
- applyRealData.test.ts: 테스트 파일, appStore 유지
- appStore.ts 파일 제거 (다음 세션)
- 최종 빌드 검증

## 미해결 문제
- P1-1 단계 5: appStore.ts 파일 제거 필요 (applyRealData.test.ts는 테스트 파일로 유지)
- P1-3 주문 상태기계 검증: 대기
- Phase 3: P2 문제 해결: 대기
- Phase 4: 문서 동기화: 대기

## 백업 상태
- 현재 git commit 없음
- 빌드 성공 상태
- P1-1 단계 4 완료, 단계 5 진행 중 (ws.ts, main.ts 변경 완료)

## 참고 프로젝트
- `/Users/sungjk0706/Desktop/SectorFlow` - 구조 참고용
