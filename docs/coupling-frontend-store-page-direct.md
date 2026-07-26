# C-08 프론트엔드 Store와 페이지 직접 결합

> 작성일: 2026-07-26
> 기준 계획서: `docs/coupling-audit-plan.md` C-08, 실행 태스크: `docs/coupling-audit-tasks.md` COUPLING-S8
> 상태: ☑ 완료 (조사·매트릭스 문서만 작성, 코드 수정 없음)
> 대상 원칙: P10 SSOT, P16 살아있는 경로, P21 사용자 투명성, P23 공통 자산 재사용, P24 단순성, P25 격리된 실패

---

## 1. 조사 범위 및 방법

### 1.1 대상 Store 3종 + 공개 API

| Store | 파일:줄 | 상태 인터페이스 | 필드 수 | 공개 action 수 | 공개 헬퍼 수 |
|-------|---------|----------------|---------|----------------|--------------|
| `hotStore` | `frontend/src/stores/hotStore.ts:60` | `HotState` | 8 | 12 (`applyAccountUpdate`/`applyRealData`/`applyOrderbookUpdate`/`applyProgramUpdate`/`applyRealtimeReset`/`applyBuyTargetsUpdate`/`applySectorScores`/`applySectorStocksRefresh`/`applySectorStocksDelta`/`applySellHistoryUpdate`/`applyBuyHistoryUpdate`/`applyDailySummaryUpdate`/`applyInitialSnapshotHot`) — ~~`applyOrderFilled`~~ 2026-07-27 제거 | 4 (`normalizeStockCode`/`stocksToMap`/`rebuildBuyTargetIndex`/`rebuildPositionIndex`/`getBuyTargetIndex`/`getPositionIndex`/`flushTickBatch`) |
| `uiStore` | `frontend/src/stores/uiStore.ts:116` | `UIState` | 23 | 21 (`applyAvgAmtProgress`/`applySettingsChanged`/`applyEngineReloadComplete`/`applyCircuitBreakerOpen`/`clearCircuitBreakerOpen`/`applyOrderTimeBlocked`/`clearOrderTimeBlocked`/`applyRiskBlockStatus`/`clearRiskBlockStatus`/`applyBuyLimitStatus`/`applyRealtimeLatencyStatus`/`applyDailyBuyStateStatus`/`applyTestCashFailed`/`clearTestCashFailed`/`clearPositionBuildFailed`/`clearDegradedMode`/`applyTestDataResetCompleted`/`applyWsSubscribeStatus`/`applyMarketPhase`/`applyIndexData`/`setSelectedSector`/`applyInitialSnapshotUI`) — ~~`applyBootstrapStage`~~ 2026-07-27 제거 | 0 |
| `stockClassificationStore` | `frontend/src/stores/stockClassificationStore.ts:31` | `StockClassificationState` | 6 | 1 (`applyStockClassificationChanged`) | 1 (`computeEditWindowOpenByTime`) |

공개 API는 `store.ts:createStore<T>`가 반환하는 3개 메서드 (`getState`/`setState`/`subscribe`)와 각 Store 모듈이 추가로 export 하는 action 함수로 이원화. **action 함수는 내부적으로 `store.setState()`를 호출** — 외부에서 `setState`를 직접 부르는 것은 action 우회.

### 1.2 대상 파일 (직접 결합 후보)

- `frontend/src/stores/{hotStore,uiStore,stockClassificationStore}.ts`
- `frontend/src/binding.ts` (339줄) — WS → Store 바인딩 단일 경로
- `frontend/src/settings.ts` (104줄) — `globalSettingsManager` (uiStore 기반)
- `frontend/src/main.ts` — 전역 구독 2곳
- `frontend/src/layout/header.ts` — `uiStore.subscribe` 1곳
- `frontend/src/components/common/data-table.ts:80` — `uiStore.getState().settings` 1곳
- `frontend/src/pages/*.ts` 36개 파일

### 1.3 조사 방법

1. `(hotStore|uiStore|stockClassificationStore)\.(getState|setState|subscribe)` 전수 grep (`frontend/src`) → 174건 식별
2. 각 파일별 호출 줄 + 컨텍스트 추출 (binding 7곳, stores 64곳, pages 96곳, layout 3곳, main 3곳, components 1곳)
3. `unsub(Store|UiStore|Ui|Custom|Sse|Hot)` grep → cleanup 패턴 46건 식별 (10개 페이지)
4. Store 정의부 전체 읽기 (hotStore 751줄 / uiStore 312줄 / stockClassificationStore 54줄 / store 67줄)
5. binding.ts 전체 읽기 → WS 이벤트 → Store action 매핑 + 직접 setState 5곳 식별
6. settings.ts 전체 읽기 → `globalSettingsManager` 간접 setState 경로 확인
7. 테스트 파일 grep (`hotStore|uiStore|stockClassificationStore`) → 3개 테스트 파일 식별

---

## 2. Store 3종 정의 및 공개 API

### 2.1 `createStore<T>` — `frontend/src/stores/store.ts:10`

```typescript
export interface StoreApi<T> {
  getState(): T
  setState(partial: Partial<T> | ((state: T) => Partial<T>)): void
  subscribe(listener: (state: T) => void): () => void
}
```

- **`setState` 내부 격리** (P25 핵심):
  - updater 함수 `try/catch` — throw 시 기존 state 유지 + 콘솔 로깅 (silent pass 아님, P20)
  - shallow merge + `Object.is` 비교 — 실제 변경 키가 있을 때만 상태 교체 + 구독자 통지
  - listener throw `try/catch` — 한 listener 실패가 다른 listener / setState 호출자로 전파 차단 (P16/P21)
- **공개 API 3개만 노출** — 외부에서 `listeners` Set 직접 접근 불가

### 2.2 `hotStore` — 고빈도 실시간 데이터 (mutable, rAF 배칭)

- **8개 상태 필드**: `account` / `positions` / `positionCount` / `sectorStocks` / `sectorScores` / `buyTargets` / `sellHistory` / `buyHistory` / `dailySummary`
- **모듈 스코프 인덱스 캐시** (Zustand state 외부): `_buyTargetIndexCache` / `_positionIndexCache` — `rebuildBuyTargetIndex`/`rebuildPositionIndex`로 재구축, `getBuyTargetIndex`/`getPositionIndex`로 O(1) 조회
- **rAF 배칭 스케줄러**: `_tickDirty`/`_orderbookDirty`/`_programDirty` Set + `requestAnimationFrame(flushTickBatch)` — `applyRealData`/`applyOrderbookUpdate`/`applyProgramUpdate`는 `setState` 호출 ❌, in-place mutation 후 dirty Set에 code 추가 → 다음 rAF 프레임에 1회 `window.dispatchEvent(new CustomEvent('real-data-tick' | 'orderbook-tick' | 'program-tick'))` 디스패치 (last-write-wins coalescing)
- **핵심 계약** (세션 7 — coalescing mutable store 패턴): `applyRealData`는 `hotStore.setState()`를 호출하지 않음 → 일반 `hotStore.subscribe()` 리스너 미발화. 사유: setState 시 scheduleRender가 배열 참조 비교로 전체 재렌더 트리거 → 초저지연 저해. 화면 갱신은 `real-data-tick` window 이벤트를 addEventListener로 수신한 페이지만 row-level O(1) 갱신.

### 2.3 `uiStore` — 저빈도 UI 상태 (사용자 인터랙션 + WS 상태)

- **23개 상태 필드**: `settings` / `status` / `sectorStatus` / `selectedSector` / `initialized` / `engineReady` / `avgAmtProgress` / `marketPhase` / `buyLimitStatus` / `wsSubscribeStatus` / `sectorScoresDelta` / `sectorSummary` / `engineReloadComplete` / `receiveRate` / `indexData` / `circuitBreakerOpen` / `orderTimeBlocked` / `riskBlockStatus` / `realtimeLatencyExceeded` / `dailyBuyStateFailed` / `testCashFailed` / `positionBuildFailed` / `degradedMode`
  - ~~`bootstrapStage`~~ — 2026-07-27 제거 (dead subscription `bootstrap-stage` 정리, COUPLING-S3 후속)
- **21개 action 함수**: WS 이벤트 → action → `uiStore.setState()` 단일 경로. 사용자 클릭 해제 action 6개 (`clearCircuitBreakerOpen`/`clearOrderTimeBlocked`/`clearRiskBlockStatus`/`clearTestCashFailed`/`clearPositionBuildFailed`/`clearDegradedMode`).
  - ~~`applyBootstrapStage`~~ — 2026-07-27 제거 (dead subscription `bootstrap-stage` 정리)
- **`applyAvgAmtProgress` 자동 숨김**: `data.done && status === 'completed'|'confirmed'` 시 3초 후 `setTimeout`으로 `avgAmtProgress: null` (하위 호환: status 없이 done=true → 즉시 숨김)
- **`applyIndexData` 다중 patch**: 한 이벤트에서 `indexData` + `status.broker_statuses` + `marketPhase` 3필드 동시 갱신 (단일 setState)

### 2.4 `stockClassificationStore` — 업종분류 커스텀 상태

- **6개 상태 필드**: `sectors` / `stockMoves` / `mergedSectors` / `editWindowOpen` / `noSectorCount` / `filter_summary` / `allStocks`
- **1개 action**: `applyStockClassificationChanged` — SSE `stock-classification-changed` 이벤트 수신 시 `sectors`/`stockMoves`/`mergedSectors`/`noSectorCount`/`filter_summary`/`allStocks` 6필드 동시 갱신
- **1개 헬퍼**: `computeEditWindowOpenByTime` — 항상 `true` 반환 (시간대 제한 제거, 백엔드 응답으로 처리)
- **`editWindowOpen`은 settings 파생**: `stock-classification.ts` mount 시 `uiStore.getState().settings`로 초기화, `uiStore.subscribe` → `computeEditWindowOpenByTime` 재계산 → `stockClassificationStore.setState({ editWindowOpen })` (크로스 스토어 결합, §5.4)

---

## 3. 상태 필드별 producer/consumer 매트릭스

### 3.1 `hotStore.HotState` (8 필드)

| 필드 | producer (action / 직접 setState) | consumer (getState 호출부) | 갱신 빈도 | 사용자 표시 |
|------|-----------------------------------|---------------------------|-----------|--------------|
| `account` | `applyAccountUpdate` / `applyInitialSnapshotHot` | `sell-position:renderSummary` / `profit-overview-mount:renderAccountVals` / `buy-target:computeBadgeContext` | 중빈도 (account-update WS) | O (수익현황 카드, 매도 요약) |
| `positions` | `applyAccountUpdate` / `applyRealData`(cur_price in-place) / `applyRealtimeReset` / `applyInitialSnapshotHot` | `sell-position:dataTable.updateRows` / `profit-overview-mount` | 고빈도 (틱마다 cur_price in-place) | O (보유 종목 테이블) |
| `positionCount` | `applyAccountUpdate` / `applyInitialSnapshotHot` | `sell-position:renderSummary` | 중빈도 | O (보유 종목 수 배지) |
| `sectorStocks` | `applyRealData`(in-place) / `applySectorStocksRefresh` / `applySectorStocksDelta` / `applyRealtimeReset` / `applyInitialSnapshotHot` | `sector-stock:buildRows` / `sell-position`(컬럼 render) / `profit-columns`(컬럼 render) / `stock-classification-master` / `stock-classification-center` / `buy-target`(파생 캐시) | 고빈도 (틱마다 in-place) | O (업종 종목 테이블, 보유 종목 현재가) |
| `sectorScores` | `applySectorScores` / `applyInitialSnapshotHot` | `sector-ranking-list:checkAndRender` / `sector-settings:78` / `sector-settings:393-395` | 중빈도 (sector-scores WS) | O (업종 순위 테이블, 업종 수 표시) |
| `buyTargets` | `applyBuyTargetsUpdate` / `buy-targets-delta`(binding 직접 setState) / `applyRealData`(in-place) / `applyOrderbookUpdate`(in-place) / `applyProgramUpdate`(in-place) / `applyRealtimeReset` / `applyInitialSnapshotHot` | `buy-target:scheduleRender` / `sector-stock?` | 고빈도 (틱마다 in-place) | O (매수 후보 테이블) |
| `sellHistory` | `applyOrderFilled` / `applySellHistoryUpdate` / `sell-history-append`(binding 직접 setState) / `applyInitialSnapshotHot` | `profit-detail:restoreInitialView` / `profit-detail-mount:subscribeProfitDetailStore` / `profit-overview:151` / `profit-overview-mount:351` | 저빈도 (체결 시) | O (매도 내역, 수익 상세) |
| `buyHistory` | `applyOrderFilled` / `applyBuyHistoryUpdate` / `buy-history-append`(binding 직접 setState) / `applyInitialSnapshotHot` | `profit-detail-mount:subscribeProfitDetailStore` / `profit-overview-mount:351` | 저빈도 (체결 시) | O (매수 내역) |
| `dailySummary` | `applyDailySummaryUpdate` / `sell-history-append`(binding 직접 setState) / `applyInitialSnapshotHot` | `profit-detail-display:109` / `profit-detail-mount:62,297,304` / `profit-overview:151` / `profit-overview-mount:351` | 저빈도 | O (일별 요약, 드릴다운) |

### 3.2 `uiStore.UIState` (24 필드)

| 필드 | producer | consumer | 빈도 | 사용자 표시 |
|------|----------|----------|------|--------------|
| `settings` | `applySettingsChanged` / `applyInitialSnapshotUI` / `settings.ts:saveSection`(간접 setState) | 거의 모든 페이지 + `data-table:80` + `stock-classification.ts:278,291` | 저빈도 | O (설정 화면, 각 페이지 설정 기반 렌더) |
| `status` | `applyIndexData` / `applyInitialSnapshotUI` | (간접 — `status.broker_statuses`만 `applyIndexData`가 patch) | 중빈도 | O (헤더 브로커 상태) |
| `sectorStatus` | `applyInitialSnapshotUI` | (현재 직접 consumer 없음 — 초기 스냅샷만) | 부트 1회 | △ |
| `selectedSector` | `setSelectedSector` | `sector-stock:setupSubscriptions` / `sector-ranking-list:checkAndRender` | 사용자 클릭 | O (업종 선택 토글) |
| `initialized` | `applyInitialSnapshotUI` | (현재 직접 consumer 없음) | 부트 1회 | △ |
| `engineReady` | `applyInitialSnapshotUI` | (현재 직접 consumer 없음) | 부트 1회 | △ |
| `avgAmtProgress` | `applyAvgAmtProgress` | (헤더/설정 화면에서 진행률 표시 — `layout/header.ts` 간접) | 진행률 이벤트 | O (평균거래액 진행률) |
| ~~`bootstrapStage`~~ | ~~`applyBootstrapStage`~~ | ~~(부트스트랩 단계 표시)~~ | ~~부트 단계~~ | ☑ 2026-07-27 제거 (dead subscription 정리) |
| `marketPhase` | `applyMarketPhase` / `applyIndexData` / `applyInitialSnapshotUI` | `layout/header:597,600,604` / `sector-settings:162,230,252,369` | 중빈도 | O (헤더 장 상태 칩, 설정 수신율) |
| `buyLimitStatus` | `applyBuyLimitStatus` / `applyTestDataResetCompleted` / `applyInitialSnapshotUI` | (매수 한도 표시 — `buy-target` 배지 간접) | 중빈도 | O (매수 한도 배지) |
| `wsSubscribeStatus` | `applyWsSubscribeStatus` / `applyInitialSnapshotUI` | `sector-stock:setupSubscriptions` | 중빈도 | O (구독 상태 기반 새로고침) |
| `sectorScoresDelta` | `binding.ts:284`(sector-scores 직접 setState) / `applyInitialSnapshotUI` | (업종 순위 delta 표시) | 중빈도 | △ |
| `sectorSummary` | `applyInitialSnapshotUI` | (현재 직접 consumer 없음) | 부트 1회 | △ |
| `engineReloadComplete` | `applyEngineReloadComplete` / `applyInitialSnapshotUI` | `stock-classification-header:125,173` | 저빈도 | O (설정 재로드 완료 게이트) |
| `receiveRate` | `binding.ts:269,292,294`(직접 setState) / `applyInitialSnapshotUI` | `sector-settings:161,228,250,368` | 중빈도 | O (수신율 진행률 바) |
| `indexData` | `applyIndexData` / `applyInitialSnapshotUI` | (업종지수 표시) | 중빈도 | O (업종지수 실시간) |
| `circuitBreakerOpen` | `applyCircuitBreakerOpen` / `clearCircuitBreakerOpen` / `applyEngineReloadComplete` / `applyInitialSnapshotUI` | (헤더 칩 + `binding.ts:307` showToast) | 저빈도 | O (서킷브레이커 알림) |
| `orderTimeBlocked` | `applyOrderTimeBlocked` / `clearOrderTimeBlocked` / `applyInitialSnapshotUI` | (매도/매수 차단 배지) | 저빈도 | O (주문 일시중단 알림) |
| `riskBlockStatus` | `applyRiskBlockStatus` / `clearRiskBlockStatus` / `applyInitialSnapshotUI` | (리스크 차단 배지) | 저빈도 | O (리스크 차단 알림) |
| `realtimeLatencyExceeded` | `applyRealtimeLatencyStatus` / `applyInitialSnapshotUI` | (지연 차단 배지) | 저빈도 | O (통신 지연 알림) |
| `dailyBuyStateFailed` | `applyDailyBuyStateStatus` / `applyInitialSnapshotUI` | (매수 차단 배지) | 저빈도 | O (매수 상태 로드 실패) |
| `testCashFailed` | `applyTestCashFailed` / `clearTestCashFailed` / `applyInitialSnapshotUI` | (헤더 칩) | 1회성 | O (테스트 잔고 부족) |
| `positionBuildFailed` | `clearPositionBuildFailed` / `applyInitialSnapshotUI` | (헤더 칩) | 부트 1회 | O (포지션 구축 실패) |
| `degradedMode` | `clearDegradedMode` / `applyInitialSnapshotUI` | (헤더 칩) | 부트 1회 | O (감소 모드 기동) |

### 3.3 `stockClassificationStore.StockClassificationState` (6 필드)

| 필드 | producer | consumer | 빈도 | 사용자 표시 |
|------|----------|----------|------|--------------|
| `sectors` | `applyStockClassificationChanged` | `stock-classification-master:104` / `stock-classification-staging:66,164,204` | SSE 이벤트 | O (업종명 해석, 칩) |
| `stockMoves` | `applyStockClassificationChanged` / `stock-classification-right:262`(직접 setState) | `stock-classification-master:104` / `stock-classification-staging:66,164,184,204` | SSE + 사용자 이동 | O (종목→업종 매핑) |
| `mergedSectors` | `applyStockClassificationChanged` | `stock-classification-master:352` / `stock-classification-staging:184` | SSE 이벤트 | O (업종 집합) |
| `editWindowOpen` | `stock-classification.ts:254,280`(직접 setState) / `applyStockClassificationChanged`? | `stock-classification-master:375` / `stock-classification-center:299` / `stock-classification-right:224` | settings 변경 시 | O (편집 컨트롤 비활성화) |
| `noSectorCount` | `applyStockClassificationChanged` | `main.ts:215`(badge) | SSE 이벤트 | O (미분류 종목수 배지) |
| `filter_summary` | `applyStockClassificationChanged` | `stock-classification-header:101` | SSE 이벤트 | O (필터 요약 표시) |
| `allStocks` | `applyStockClassificationChanged` / `stock-classification-right:262`(직접 setState) | `stock-classification-staging:41` | SSE + 사용자 이동 | O (전체 종목 목록) |

---

## 4. 직접 호출 패턴 분류 (174건)

### 4.1 패턴 A — `getState` 읽기 (정상, 다수)

페이지가 렌더링 시 `hotStore.getState()` / `uiStore.getState()`로 현재 상태를 읽어 DataTable 행·배지·카드 구성. **action 우회 아님** — Store의 공개 읽기 API 사용. 모든 페이지가 이 패턴을 사용.

### 4.2 패턴 B — `subscribe` + cleanup (정상, 10개 페이지)

| 페이지 | 구독 Store | cleanup 변수 | unmount 시 해제 |
|--------|-----------|---------------|-----------------|
| `sector-ranking-list.ts` | hotStore + uiStore | `unsubStore` / `unsubUiStore` | O (339-340줄) |
| `buy-target.ts` | hotStore + uiStore | `unsubTargets` / `unsubUiStore` | O (467-468줄) |
| `sell-position.ts` | hotStore + uiStore | `unsubStore` / `unsubUiStore` | O (328-329줄) |
| `sector-stock.ts` | hotStore + uiStore | `this.unsubStore` / `this.unsubUi` | O (458-459줄) |
| `sector-settings.ts` | hotStore + uiStore | `unsubUiStore` / `unsubHotStore` | O (435-436줄) |
| `profit-overview.ts` | hotStore | `state.unsubStore` | O (178줄) |
| `profit-overview-mount.ts` | hotStore | `state.unsubStore` | (호출부에서 해제) |
| `profit-detail.ts` | hotStore | `state.unsubStore` | O (160줄) |
| `profit-detail-mount.ts` | hotStore | `state.unsubStore` | (호출부에서 해제) |
| `stock-classification.ts` | stockClassificationStore + uiStore | `state.unsubCustom` / `state.unsubSse` / `state.unsubSettings` / `state.unsubHot` | O (313-316줄) |
| `layout/header.ts` | uiStore | `unsubscribe` | (헤더는 앱 수명주기 — 해제 없음) |
| `main.ts` | uiStore + stockClassificationStore | (전역 — 앱 수명주기) | 해제 없음 |

**모든 페이지 마운트 컴포넌트가 unmount 시 구독 해제** — P25 격리된 실패 준수. `layout/header.ts`와 `main.ts`는 앱 수명주기이므로 해제 불필요.

### 4.3 패턴 C — 페이지에서 직접 `setState` (3곳, 5건)

| 파일:줄 | 대상 Store | 필드 | 사유 |
|---------|-----------|------|------|
| `stock-classification.ts:280` | stockClassificationStore | `editWindowOpen` | mount 시 `uiStore.getState().settings`로 초기값 계산 |
| `stock-classification.ts:254` | stockClassificationStore | `editWindowOpen` | `uiStore.subscribe` 콜백에서 settings 변경 시 재계산 (크로스 스토어, §5.4) |
| `stock-classification-right.ts:262` | stockClassificationStore | `allStocks` + `stockMoves` | `/api/stock-classification/move-stocks` 응답 기반 로컬 상태 업데이트 (낙관적 적용) |

**판정**: 3곳 모두 action 우회. `editWindowOpen` 2곳은 settings 파생값이므로 `applyEditWindowOpen(settings)` action 추출 후보 (§7.1). `allStocks + stockMoves`는 `applyMoveStocksResult(response)` action 추출 후보 (§7.2).

### 4.4 패턴 D — `binding.ts` 직접 `setState` (5곳)

| 파일:줄 | 대상 Store | WS 이벤트 | 내용 | action 추출 후보 |
|---------|-----------|-----------|------|------------------|
| `binding.ts:103-146` | hotStore | `buy-targets-delta` | 44줄 인라인 delta 머지 (removed/changed/added + sectorStocks 실시간 필드 결합) | `applyBuyTargetsDelta(data)` (§7.3) |
| `binding.ts:152` | hotStore | `buy-history-append` | `buyHistory: [trade, ...state.buyHistory]` prepend | `applyBuyHistoryAppend(trade)` (§7.4) |
| `binding.ts:222-227` | hotStore | `sell-history-append` | `sellHistory` prepend + `dailySummary` 교체 (2필드 patch) | `applySellHistoryAppend(data)` (§7.4) |
| `binding.ts:269` | uiStore | `receive-rate` | `receiveRate: { krx, nxt }` 단일 필드 | `applyReceiveRate(data)` (§7.5) |
| `binding.ts:284-294` | uiStore | `sector-scores` | `sectorScoresDelta` + `receiveRate` 2회 setState (한 이벤트에서 2회) | `applySectorScoresDelta(delta)` + `applyReceiveRate(rate)` (§7.5) |

**판정**: 5곳 모두 action 우회. `buy-targets-delta`는 44줄 복잡 로직이므로 `applyBuyTargetsDelta` action 추출 시 `applyBuyTargetsUpdate`/`applySectorStocksDelta`와 패턴 일치 (P23). 나머지 4곳은 단순 prepend/patch라 실익 낮음.

### 4.5 패턴 E — 크로스 스토어 결합 (1곳)

`stock-classification.ts:291-294`:

```typescript
state.unsubSse = uiStore.subscribe((uiState) => {
  handleUiStoreChange(uiState, prevSettingsRef)
})
// handleUiStoreChange 내부:
//   uiState.settings 변경 시 computeEditWindowOpenByTime(uiState.settings)
//   → stockClassificationStore.setState({ editWindowOpen })
```

- **구조**: `uiStore` 구독 → `stockClassificationStore` 갱신 (크로스 스토어)
- **사유**: `editWindowOpen`이 `settings` 파생값이므로 `uiStore.settings` 변경 시 `stockClassificationStore.editWindowOpen` 재계산 필요
- **현재 `computeEditWindowOpenByTime`은 항상 `true` 반환** (시간대 제거) — 크로스 스토어 결합이 사실상 dead path에 가까움. 단, 향후 시간대 제한 복원 시 활성화되므로 제거 금지 (P16 살아있는 경로 — 현재는 호출되나 항상 동일값).
- **판정**: `applyEditWindowOpen(settings)` action 추출 시에도 크로스 스토어 구조 자체는 유지 필요 (settings 파생값이므로). 다만 페이지가 직접 `stockClassificationStore.setState`를 호출하는 것을 action으로 대체 가능 (§7.1).

### 4.6 패턴 F — `settings.ts` 간접 `setState` (1곳)

`settings.ts:77`:

```typescript
async function saveSection(data: Record<string, unknown>): Promise<SaveResult> {
  // ... API 저장 성공 시
  const current = store.getState().settings
  if (current) {
    store.setState({ settings: { ...current, ...data } })
  }
}
```

- **구조**: `globalSettingsManager.saveSection()` 성공 시 `uiStore.setState({ settings })` 간접 호출
- **사유**: API 저장 성공을 로컬 store에 즉시 반영 (WS `settings-changed`는 외부 변경 감지용 보조). 설계 7.3: 서버 거부 시 store 반영 안 함 (catch 경로).
- **판정**: P10 SSOT 준수 — `settings`의 단일 진실 소스는 `uiStore.settings`이며, `saveSection`은 그 소스를 갱신하는 공식 경로. `applySettingsChanged` action과 중복되나, action은 WS 이벤트용 (delta 지원), `saveSection`은 API 응답용 (전체 병합)으로 용도 차이. **action 추출 불필요** — `settings.ts`가 `uiStore`를 주입받아 사용하는 설계적 단일 경로.

### 4.7 패턴 G — 전역 구독 (`main.ts`, 2곳)

- `main.ts:198` — `uiStore.subscribe` (settings === null일 때 로딩 오버레이 표시)
- `main.ts:215` — `stockClassificationStore.subscribe` (noSectorCount → `shell.setBadge('#/stock-classification', ...)`)

**판정**: 앱 수명주기 구독 — 해제 불필요. P21 사용자 투명성 (로딩 상태 + 미분류 배지) 준수.

---

## 5. 페이지별 결합 매트릭스

### 5.1 고빈도 실시간 페이지 (hotStore + rAF 배칭)

| 페이지 | hotStore 호출 | uiStore 호출 | subscribe | rAF 배칭 | real-data-tick 리스너 |
|--------|---------------|--------------|-----------|----------|----------------------|
| `buy-target.ts` | getState 5 | getState 5 | 2 (hot + ui) | O (scheduleRender) | O (onRealDataTick) |
| `sell-position.ts` | getState 8 | getState 2 | 2 (hot + ui) | O (scheduleStatusUpdate) | O (onRealDataTick) |
| `sector-stock.ts` | getState 5 | getState 5 | 2 (hot + ui) | O (checkAndRefresh) | O (onRealDataTick) |
| `sector-ranking-list.ts` | getState 5 | getState 5 | 2 (hot + ui) | O (checkAndRender) | X |

**공통 패턴** (P23 일관성):
1. mount 시 `hotStore.getState()` + `uiStore.getState()`로 초기 렌더
2. `hotStore.subscribe(checkAndRender)` + `uiStore.subscribe(checkAndRender)` — 동일 콜백으로 두 Store 변경 모두 감지
3. `checkAndRender` 내부에서 reference equality guard (`prevSectorStocks !== state.sectorStocks` 등)로 불필요한 재렌더 차단
4. 변경 시 `requestAnimationFrame`으로 프레임당 1회 갱신 예약
5. 고빈도 페이지는 추가로 `window.addEventListener('real-data-tick', onRealDataTick)` — `dataTable.updateItemByKey(code)`로 O(1) row 갱신
6. unmount 시 `unsubStore()` + `unsubUiStore()` + `removeEventListener` + `cancelAnimationFrame`

### 5.2 저빈도 페이지 (수익 화면)

| 페이지 | hotStore 호출 | uiStore 호출 | subscribe | 특징 |
|--------|---------------|--------------|-----------|------|
| `profit-overview.ts` | getState 1 | 0 | 1 (hot) | `localDailySummary` = `initState.dailySummary` 복사 |
| `profit-overview-mount.ts` | getState 4 | 0 | 1 (hot) | `renderAccountVals` / `subscribeProfitOverviewStore` |
| `profit-detail.ts` | getState 1 | 0 | 1 (hot) | `restoreInitialView(state, todayStr, initState)` |
| `profit-detail-mount.ts` | getState 6 | 0 | 1 (hot) | `subscribeProfitDetailStore` — sellHistory/buyHistory/dailySummary 변경 감지 |
| `profit-detail-display.ts` | getState 1 | 0 | 0 | `buildMonthlyDrilldown(hotStore.getState().dailySummary, yearMonth)` |
| `profit-columns.ts` | getState 2 | 0 | 0 | 컬럼 render 시 `sectorStocks` 조회 (현재가 표시) |

**판정**: 수익 화면은 `hotStore`만 구독 (uiStore 구독 없음). `profit-overview`/`profit-detail`은 mount/unmount 분할 (`*-mount.ts`가 구독 설정, 메인 페이지가 unmount 시 해제). P24 단순성 준수 — 불필요한 uiStore 구독 없음.

### 5.3 설정 페이지 (uiStore 중심)

| 페이지 | hotStore 호출 | uiStore 호출 | subscribe | 특징 |
|--------|---------------|--------------|-----------|------|
| `sector-settings.ts` | getState 4 + subscribe 1 | getState 12 + subscribe 1 | 2 (hot + ui) | `startUiStoreSubscription` / `startHotStoreSubscription` 분리 — receiveRate/marketPhase/sectorScores 변경 감지 |
| `general-settings*.ts` (7개 탭) | 0 | 0 (간접 — `globalSettingsManager` 사용) | 0 | `settings.ts` 경유 간접 결합 |

**판정**: `sector-settings.ts`는 유일하게 `hotStore.sectorScores.length`를 구독 (업종 수 표시). `general-settings*.ts`는 `globalSettingsManager`를 통해 간접 결합 — 직접 Store 호출 0건 (P23 공통 자산 재사용).

### 5.4 업종분류 페이지 (크로스 스토어)

| 파일 | stockClassificationStore | hotStore | uiStore | subscribe |
|------|--------------------------|----------|---------|-----------|
| `stock-classification.ts` (main) | getState 2 + setState 2 + subscribe 1 | 0 | getState 2 + subscribe 1 | 2 (custom + ui) |
| `stock-classification-master.ts` | getState 3 | getState 1 | 0 | 0 |
| `stock-classification-center.ts` | getState 1 | getState 1 | 0 | 0 |
| `stock-classification-right.ts` | getState 2 + setState 1 | 0 | 0 | 0 |
| `stock-classification-staging.ts` | getState 5 | 0 | 0 | 0 |
| `stock-classification-header.ts` | getState 1 | 0 | getState 2 | 0 |

**크로스 스토어 결합**: `stock-classification.ts`가 `uiStore.subscribe` → `stockClassificationStore.setState({ editWindowOpen })` (§4.5). `editWindowOpen`은 settings 파생값이므로 구조적 불가피.

**직접 setState 3건** (§4.3):
- `stock-classification.ts:254,280` — editWindowOpen (settings 파생)
- `stock-classification-right.ts:262` — allStocks + stockMoves (API 응답)

**판정**: 6개 분할 모듈이 `stockClassificationStore.getState()`를 빈번 호출 (11건). `stock-classification.ts`가 단일 구독 지점으로 분할 모듈에 콜백 주입 (`initStagingCallbacks`/`initMasterCallbacks`/`initCenterCallbacks`/`initRightCallbacks`) — 순환 참조 해결 (F-04 분할). P23 일관성 + P24 단순성 준수.

---

## 6. binding.ts 직접 setState 상세 분석

### 6.1 `buy-targets-delta` (binding.ts:103-146) — 44줄 인라인

```typescript
pricesClient.onEvent('buy-targets-delta', (data) => {
  const { added, removed, changed } = data
  hotStore.setState((state) => {
    let buyTargets = state.buyTargets
    // removed: filter
    // changed: findIndex + sectorStocks 실시간 필드 결합
    // added: sectorStocks 실시간 필드 결합 + push
    if (buyTargets === state.buyTargets) return state
    rebuildBuyTargetIndex(buyTargets)
    return { buyTargets }
  })
})
```

- **복잡도**: 44줄, 3단계 (removed/changed/added) + sectorStocks 결합 + 인덱스 재구축
- **일관성 위반**: `applyBuyTargetsUpdate`(552줄) / `applySectorStocksDelta`(665줄)는 hotStore action인데, `buy-targets-delta`만 binding에 인라인 — P23 일관성 위반
- **개선 후보**: `applyBuyTargetsDelta(data)` action을 hotStore에 추가 → binding은 `applyBuyTargetsDelta(data as ...)` 1줄 호출. §7.3.

### 6.2 `buy-history-append` / `sell-history-append` (binding.ts:152, 222-227) — 단순 prepend

```typescript
// buy-history-append (152)
hotStore.setState((state) => ({ buyHistory: [trade, ...state.buyHistory] }))

// sell-history-append (222-227)
hotStore.setState((state) => {
  const patch: Partial<typeof state> = {}
  if (trade) patch.sellHistory = [trade, ...state.sellHistory]
  if (daily_summary) patch.dailySummary = daily_summary
  return patch
})
```

- **복잡도**: 1줄 / 6줄 — 단순 prepend
- **일관성**: `applyOrderFilled`(690줄)가 동일 prepend 패턴을 action으로 제공 — `buy-history-append`/`sell-history-append`는 action 없이 binding 직접
- **개선 후보**: `applyBuyHistoryAppend(trade)` / `applySellHistoryAppend({ trade, daily_summary })` action 추가. 단, 단순 prepend라 실익 낮음 (§7.4).

### 6.3 `receive-rate` / `sector-scores` (binding.ts:269, 284-294) — uiStore 직접

```typescript
// receive-rate (269)
uiStore.setState({ receiveRate: { krx: d.krx, nxt: d.nxt } })

// sector-scores (284-294) — 한 이벤트에서 2회 setState
uiStore.setState({ sectorScoresDelta: ... })
const rawRate = d.status?.receive_rate
if (rawRate) uiStore.setState({ receiveRate: { krx: rawRate.krx, nxt: rawRate.nxt } })
else uiStore.setState({ receiveRate: null })
```

- **일관성 위반**: `applyWsSubscribeStatus`/`applyBuyLimitStatus` 등은 uiStore action인데, `receiveRate`/`sectorScoresDelta`는 action 없이 binding 직접
- **2회 setState**: `sector-scores` 이벤트에서 `sectorScoresDelta` + `receiveRate`를 2회 분리 setState — `applySectorScores`(hotStore)와 `applySectorScoresDelta`+`applyReceiveRate`(uiStore)로 분리 시 한 이벤트에서 3회 action 호출될 수 있으나, action 내부에서 `Object.is` 비교로 불필요 통지 차단되므로 무방
- **개선 후보**: `applyReceiveRate(data)` / `applySectorScoresDelta(delta)` action 추가 (§7.5)

---

## 7. cleanup 패턴 점검

### 7.1 모든 페이지 마운트 컴포넌트 cleanup 확인

| 페이지 | unsub 변수 | unmount 시 해제 | rAF 취소 | 이벤트 리스너 해제 | settingsMgr.destroy |
|--------|-----------|-----------------|----------|-------------------|---------------------|
| `sector-ranking-list.ts` | 2 | O (339-340) | O (338) | O (rowClickHandler) | X |
| `buy-target.ts` | 2 | O (467-468) | O (466) | O (onRealDataTick 465) | X |
| `sell-position.ts` | 3 | O (328-330) | O (331) | O (onRealDataTick 325-326) | O (settingsMgr 330) |
| `sector-stock.ts` | 2 | O (458-459) | O (460) | O (onRealDataTick 456-457) | X |
| `sector-settings.ts` | 2 | O (435-436) | X | X | O (433) |
| `profit-overview.ts` | 1 | O (178) | X | O (179) | X |
| `profit-detail.ts` | 1 | O (160) | O (164-165) | X | X |
| `stock-classification.ts` | 4 | O (313-316) | X | O (closeContextPopup 318) | O (317) |

**판정**: 모든 페이지가 unmount 시 구독 해제 + rAF 취소 + 이벤트 리스너 해제 수행. P25 격리된 실패 준수 — 페이지 전환 후 잔존 구독으로 인한 메모리 누수/스테일 렌더 없음.

### 7.2 `stock-classification-right.ts` race condition 방지

```typescript
// stock-classification-right.ts:253
if (!state.mounted) return  // unmount 후 응답 도착 시 store 업데이트 차단 (P19)
```

- **P19 (unmount 후 async 응답 차단)**: `/api/stock-classification/move-stocks` 응답 도착 시 `state.mounted` 체크 — unmount 후에는 `stockClassificationStore.setState` 호출 안 함
- **판정**: P25 격리된 실패 + P19 준수. 단, `state.mounted` 체크 후 `stockClassificationStore.setState`가 여전히 페이지에서 직접 호출되는 것은 §4.3 패턴 C.

---

## 8. 테스트 커버리지

### 8.1 Store 직접 테스트

| 테스트 파일 | 대상 | 케이스 수 | 비고 |
|-------------|------|-----------|------|
| `frontend/tests/stores/store.test.ts` | `createStore` | (미확인 — 파일 존재) | setState/subscribe/getState 기본 계약 |
| `frontend/tests/stores/hotStore.test.ts` | `hotStore` + actions | 다수 (세션 3/4/7) | `applyRealData` 갱신 계약 + rAF 배칭, sectorStocks↔buyTargets 정합성, 이벤트 계약 정합성 |
| `frontend/tests/utils/order-block-status.test.ts` | `UIState` 타입 | (타입 import만) | `UIState` 타입 사용 |
| `frontend/tests/settings.test.ts` | `globalSettingsManager` | (미확인) | `UIState` 타입 사용 |

### 8.2 직접 결합 패턴 테스트 커버리지

| 패턴 | 테스트 커버 | 비고 |
|------|-------------|------|
| A (getState 읽기) | 간접 (hotStore.test.ts가 action 후 getState 검증) | 페이지 렌더링 자체 테스트 부재 |
| B (subscribe + cleanup) | hotStore.test.ts:445-475 (subscribe 미발화 3건) | cleanup 테스트 부재 |
| C (페이지 직접 setState) | X | stock-classification.ts editWindowOpen / right.ts allStocks 직접 테스트 부재 |
| D (binding 직접 setState) | X | binding.ts 자체 테스트 부재 — WS 바인딩 통합 테스트 없음 |
| E (크로스 스토어) | X | uiStore → stockClassificationStore 크로스 스토어 테스트 부재 |
| F (settings.ts 간접) | settings.test.ts 존재 | saveSection 성공 시 store 반영 테스트 추정 |
| G (전역 구독) | X | main.ts 오버레이/배지 테스트 부재 |

**판정**: hotStore action 계약 테스트는 양호하나, **binding.ts 직접 setState 5곳과 페이지 직접 setState 3곳의 통합 테스트 부재**. 특히 `buy-targets-delta` 44줄 인라인 로직 (§6.1)은 테스트 없이 binding에 방치 — action 추출 시 hotStore.test.ts에 단위 테스트 추가 가능 (§7.3).

---

## 9. 아키텍처 원칙 점검

### 9.1 P10 (SSOT) 준수

- **hotStore.sectorStocks**: 실시간 시세 단일 진실 소스. `buyTargets` 실시간 필드는 파생 캐시 (in-place mutation + rebindBuyTargetsRealtime으로 동기화). `positions.cur_price`도 sectorStocks 기반 갱신.
- **uiStore.settings**: 설정 단일 진실 소스. `globalSettingsManager.saveSection`과 `applySettingsChanged` 모두 동일 소스 갱신.
- **stockClassificationStore**: 업종분류 커스텀 상태 단일 진실 소스. SSE 이벤트와 API 응답 모두 동일 소스 갱신.
- **위반 후보 0건**: 각 상태 필드의 producer가 단일 Store로 수렴.

### 9.2 P16 (살아있는 경로) 준수

- **dead code 0건**: 모든 직접 setState 호출부가 실제 실행 경로.
- **`computeEditWindowOpenByTime` 항상 `true` 반환**: 현재는 dead path에 가까우나, 향후 시간대 제한 복원 시 활성화 — 호출부는 살아있으므로 P16 위반 아님 (함수 본문이 단순화된 것).

### 9.3 P21 (사용자 투명성) 준수

- **모든 백엔드 상태가 UI에 표시**: `circuitBreakerOpen`/`orderTimeBlocked`/`riskBlockStatus`/`realtimeLatencyExceeded`/`dailyBuyStateFailed`/`testCashFailed`/`positionBuildFailed`/`degradedMode` 8개 차단 상태가 모두 헤더 칩/배지로 표시.
- **`engineReloadComplete` 게이트**: `stock-classification-header.ts:125,173`에서 설정 재로드 완료 전에는 편집 허용 안 함 — 사용자가 "왜 편집이 안 되지?" 의문 갖지 않도록.
- **위반 후보 0건**.

### 9.4 P23 (일관성) 부분 준수

- **일관성 위반 1건**: `buy-targets-delta`가 binding에 44줄 인라인 (§6.1) — `applyBuyTargetsUpdate`/`applySectorStocksDelta`는 action인데 `buy-targets-delta`만 action 없이 binding 직접. P23 위반.
- **일관성 위반 2건**: `receiveRate`/`sectorScoresDelta`가 action 없이 binding 직접 (§6.3) — 다른 uiStore 필드는 action 제공. P23 위반.
- **공통 자산 재사용**: `globalSettingsManager`가 `general-settings*.ts` 7개 탭에서 재사용 — P23 준수.
- **페이지 패턴 일관성**: 고빈도 4개 페이지가 동일 패턴 (subscribe + rAF + reference equality guard + real-data-tick 리스너) — P23 준수.

### 9.5 P24 (단순성) 부분 준수

- **중복 1건**: `buy-targets-delta` 44줄 인라인이 `applyBuyTargetsUpdate`/`applySectorStocksDelta`와 유사 패턴 (sectorStocks 결합 + 인덱스 재구축) — action 추출 시 중복 제거 가능.
- **2회 setState**: `sector-scores` 이벤트에서 `sectorScoresDelta` + `receiveRate` 2회 분리 setState — 단일 `applySectorScoresEvent(data)` action으로 통합 시 1회 setState 가능. 단, action 내부에서 `Object.is` 비교로 불필요 통지 차단되므로 성능 영향 미미.
- **함수 길이**: `binding.ts:bindWSToStore` 276줄 (63-339) — 50줄 초과이나 WS 바인딩 단일 경로이므로 분할 시 결합 증가. P24 분할 검토 기준이나 자동 위반 아님.
- **파일 길이**: `hotStore.ts` 751줄 — 500줄 초과이나 action 함수 묶음이므로 분할 시 응집도 저하. P24 분할 검토 기준이나 자동 위반 아님.

### 9.6 P25 (격리된 실패) 준수

- **store.ts setState 격리**: updater throw + listener throw 모두 try/catch — P25 핵심.
- **페이지 cleanup**: 모든 페이지 마운트 컴포넌트가 unmount 시 구독 해제 — 페이지 전환 후 잔존 구독으로 인한 전체 화면 블로킹 없음.
- **`stock-classification-right.ts:253` race condition 방지**: `state.mounted` 체크로 unmount 후 async 응답 차단.
- **위반 후보 0건**.

---

## 10. 개선 후보

> 우선순위: 중간 = P23/P24 동시 개선 + 테스트 추가 가능 / 낮음 = 단순 중복 제거 + 실익 낮음

### 10.1 (중간) `applyEditWindowOpen(settings)` action 추가 — `stockClassificationStore`

- **현재**: `stock-classification.ts:254,280`에서 `stockClassificationStore.setState({ editWindowOpen })` 직접 호출 2곳
- **개선**: `stockClassificationStore`에 `applyEditWindowOpen(settings: AppSettings | null): void` action 추가 → 페이지는 `applyEditWindowOpen(uiState.settings)` 1줄 호출
- **효과**: P23 일관성 (페이지 직접 setState 제거) + P24 단순성 (editWindowOpen 계산 로직 중앙화)
- **테스트**: `stockClassificationStore.test.ts` 신규 — `applyEditWindowOpen` 단위 테스트
- **위험**: 낮음 — `computeEditWindowOpenByTime`은 항상 `true` 반환하므로 현재 동작 변경 없음. 향후 시간대 제한 복원 시 action 본문만 수정.
- **크로스 스토어 구조 유지**: `uiStore.subscribe` → `applyEditWindowOpen` 호출 구조는 유지 (settings 파생값이므로).

### 10.2 (중간) `applyMoveStocksResult(response)` action 추가 — `stockClassificationStore`

- **현재**: `stock-classification-right.ts:262`에서 `stockClassificationStore.setState({ allStocks, stockMoves })` 직접 호출
- **개선**: `stockClassificationStore`에 `applyMoveStocksResult(codes: string[], targetSector: string, allStocks: Array<...>): void` action 추가
- **효과**: P23 일관성 (페이지 직접 setState 제거) + P22 데이터 정합성 (allStocks + stockMoves 동시 갱신 보장)
- **테스트**: `stockClassificationStore.test.ts` 신규 — `applyMoveStocksResult` 단위 테스트
- **위험**: 낮음 — 기존 동작과 동일, action으로 래핑만.

### 10.3 (중간) `applyBuyTargetsDelta(data)` action 추가 — `hotStore`

- **현재**: `binding.ts:103-146`에서 44줄 인라인 `hotStore.setState`
- **개선**: `hotStore`에 `applyBuyTargetsDelta(data: { added, removed, changed }): void` action 추가 → binding은 `applyBuyTargetsDelta(data as ...)` 1줄 호출
- **효과**: P23 일관성 (`applyBuyTargetsUpdate`/`applySectorStocksDelta`와 패턴 일치) + P24 단순성 (44줄 인라인 제거) + 테스트 추가 가능
- **테스트**: `hotStore.test.ts` 신규 — `applyBuyTargetsDelta` 단위 테스트 (removed/changed/added + sectorStocks 결합 + 인덱스 재구축)
- **위험**: 중간 — 44줄 로직 이동 시 참조 동등성 (`buyTargets === state.buyTargets`) 보존 필요. 단, 기존 로직 그대로 이동이므로 동작 변경 없음.

### 10.4 (낮음) `applyBuyHistoryAppend(trade)` / `applySellHistoryAppend(data)` action 추가 — `hotStore`

- **현재**: `binding.ts:152,222-227`에서 단순 prepend `hotStore.setState`
- **개선**: `hotStore`에 `applyBuyHistoryAppend(trade)` / `applySellHistoryAppend({ trade, daily_summary })` action 추가
- **효과**: P23 일관성 (`applyOrderFilled`와 패턴 일치)
- **위험**: 낮음 — 단순 prepend. 단, 실익 낮음 (1-6줄).

### 10.5 (낮음) `applyReceiveRate(data)` / `applySectorScoresDelta(delta)` action 추가 — `uiStore`

- **현재**: `binding.ts:269,284-294`에서 `uiStore.setState` 직접 5건
- **개선**: `uiStore`에 `applyReceiveRate(data)` / `applySectorScoresDelta(delta | null)` action 추가
- **효과**: P23 일관성 (다른 uiStore 필드는 action 제공)
- **위험**: 낮음 — 단순 patch. 단, `sector-scores` 이벤트에서 3회 action 호출 (applySectorScores + applySectorScoresDelta + applyReceiveRate) 증가. action 내부 `Object.is` 비교로 불필요 통지 차단되므로 무방.

---

## 11. 변경 금지 항목

1. **`hotStore.applyRealData` in-place mutation + rAF 배칭 패턴** — 변경 시 초저지연 저해 (P7/P16). `setState` 호출 시 scheduleRender가 배열 참조 비교로 전체 재렌더 트리거.
2. **`store.ts:setState` 내 try/catch 격리** — P25 격리된 실패 핵심. updater throw 시 기존 state 유지 + listener throw 시 다른 listener 전파 차단.
3. **페이지 subscribe + cleanup 패턴** — P25 격리된 실패. 모든 페이지 마운트 컴포넌트가 unmount 시 구독 해제. cleanup 제거 시 페이지 전환 후 잔존 구독 → 메모리 누수 + 스테일 렌더.
4. **`settings.ts:saveSection` 성공 시 `store.setState({ settings })`** — P10 SSOT. API 저장 성공을 로컬 store에 즉시 반영하는 공식 경로. WS `settings-changed`는 외부 변경 감지용 보조. 제거 시 API 저장 후 UI 갱신 지연.
5. **`stock-classification.ts` uiStore → stockClassificationStore 크로스 스토어** — `editWindowOpen`이 settings 파생값이므로 구조적 불가피. action 추출 시에도 크로스 스토어 구조 유지 필요 (§10.1).
6. **`stock-classification-right.ts:253` `state.mounted` 체크** — P19 race condition 방지. unmount 후 async 응답 도착 시 store 업데이트 차단. 제거 시 unmount 후 스테일 렌더.
7. **`computeEditWindowOpenByTime` 항상 `true` 반환** — 시간대 제한 제거 의도적 결정. 향후 복원 시 별도 승인 필요. 현재 dead path에 가까우나 제거 금지 (P16 — 호출부 살아있음).
8. **`hotStore` 모듈 스코프 인덱스 캐시** — `_buyTargetIndexCache`/`_positionIndexCache`는 Zustand state 외부에서 O(1) 조회 제공. state로 이동 시 매 틱마다 setState 트리거 → 초저지연 저해.
9. **4개 고빈도 페이지의 `real-data-tick` window 이벤트 리스너** — `dataTable.updateItemByKey(code)`로 O(1) row 갱신. 제거 시 `hotStore.subscribe` 기반 전체 재렌더로 성능 저하.

---

## 12. 핵심 발견 요약

1. **Store 3종 공개 API 이원화**: `createStore` 3메서드 (getState/setState/subscribe) + 각 Store action 함수. action은 내부적으로 `setState` 호출 — 외부에서 `setState` 직접 호출은 action 우회.
2. **직접 `setState` 8건 식별**: 페이지 3건 (stock-classification.ts 2 + right.ts 1) + binding 5건 (buy-targets-delta + buy-history-append + sell-history-append + receive-rate + sector-scores 2). 모두 action 우회.
3. **`buy-targets-delta` 44줄 인라인** (binding.ts:103-146)이 가장 큰 일관성 위반 — `applyBuyTargetsUpdate`/`applySectorStocksDelta`는 action인데 `buy-targets-delta`만 binding 직접. P23 위반 + 테스트 부재.
4. **크로스 스토어 결합 1건** (stock-classification.ts): `uiStore.subscribe` → `stockClassificationStore.setState({ editWindowOpen })`. `editWindowOpen`이 settings 파생값이므로 구조적 불가피. 현재 `computeEditWindowOpenByTime`이 항상 `true`라 dead path에 가까움.
5. **모든 페이지 cleanup 준수** (P25): 10개 페이지 마운트 컴포넌트가 unmount 시 구독 해제 + rAF 취소 + 이벤트 리스너 해제. `stock-classification-right.ts`는 `state.mounted` 체크로 race condition 방지 (P19).
6. **고빈도 4개 페이지 공통 패턴** (P23): subscribe + rAF 배칭 + reference equality guard + real-data-tick 리스너. `buy-target`/`sell-position`/`sector-stock`/`sector-ranking-list`가 동일 구조.
7. **`globalSettingsManager` 간접 결합** (settings.ts): `general-settings*.ts` 7개 탭이 직접 Store 호출 0건 — `globalSettingsManager` 경유. P23 공통 자산 재사용 준수.
8. **테스트 커버리지 부재**: binding.ts 직접 setState 5곳 + 페이지 직접 setState 3곳의 통합 테스트 없음. hotStore action 계약 테스트는 양호.
9. **P10/P16/P21/P25 준수**: 각 상태 필드 단일 진실 소스, dead code 0건, 모든 차단 상태 UI 표시, 모든 페이지 cleanup. P23/P24 부분 준수 (일관성 위반 3건 + 중복 1건).

---

## 13. 판정 요약

| 항목 | 판정 | 비고 |
|------|------|------|
| Store 3종 공개 API 설계 | ⊚ 준수 | createStore 3메서드 + action 이원화, setState 내부 격리 (P25) |
| 페이지 getState 읽기 (패턴 A) | ⊚ 준수 | 공개 읽기 API 사용, action 우회 아님 |
| 페이지 subscribe + cleanup (패턴 B) | ⊚ 준수 | 10개 페이지 모두 unmount 시 해제 (P25) |
| 페이지 직접 setState (패턴 C) | △ 부분 준수 | 3건 action 우회 — 개선 후보 §10.1, §10.2 |
| binding 직접 setState (패턴 D) | △ 부분 준수 | 5건 action 우회 — 개선 후보 §10.3, §10.4, §10.5 |
| 크로스 스토어 결합 (패턴 E) | ⊚ 준수 | settings 파생값이므로 구조적 불가피 |
| settings.ts 간접 setState (패턴 F) | ⊚ 준수 | P10 SSOT 공식 경로 |
| 전역 구독 (패턴 G) | ⊚ 준수 | 앱 수명주기, P21 사용자 투명성 |
| P10 SSOT | ⊚ 준수 | 각 상태 필드 단일 Store |
| P16 살아있는 경로 | ⊚ 준수 | dead code 0건 |
| P21 사용자 투명성 | ⊚ 준수 | 8개 차단 상태 모두 UI 표시 |
| P23 일관성 | △ 부분 준수 | 일관성 위반 3건 (buy-targets-delta + receiveRate + sectorScoresDelta) |
| P24 단순성 | △ 부분 준수 | 중복 1건 (buy-targets-delta 44줄) |
| P25 격리된 실패 | ⊚ 준수 | setState 격리 + 페이지 cleanup + race condition 방지 |

**종합 판정**: Store-페이지 직접 결합은 대부분 정상 패턴 (getState 읽기 + subscribe + cleanup). **개선 후보 5건** 중 중간 우선순위 3건 (§10.1, §10.2, §10.3)이 P23/P24 동시 개선 + 테스트 추가 효과. 낮음 2건 (§10.4, §10.5)은 단순 중복 제거. **새 Store 생성 불필요** — 기존 3종 Store에 action 추가로 해결. **실행 승인 후 한 상태군의 직접 쓰기만 기존 action 또는 공통 자산으로 최소 전환** 권장 (태스크 수정 내용 4항).

---

## 14. 참조

- `docs/coupling-audit-plan.md` C-08
- `docs/coupling-audit-tasks.md` COUPLING-S8
- `frontend/src/stores/store.ts` (67줄)
- `frontend/src/stores/hotStore.ts` (751줄)
- `frontend/src/stores/uiStore.ts` (312줄)
- `frontend/src/stores/stockClassificationStore.ts` (54줄)
- `frontend/src/binding.ts` (339줄)
- `frontend/src/settings.ts` (104줄)
- `frontend/src/main.ts` (전역 구독 2곳)
- `frontend/src/layout/header.ts` (uiStore.subscribe 1곳)
- `frontend/src/components/common/data-table.ts:80` (uiStore.getState 1곳)
- `frontend/tests/stores/hotStore.test.ts` (action 계약 테스트)
- `ARCHITECTURE.md` 제1부 불변 원칙 25개 (P10/P16/P21/P23/P24/P25)
