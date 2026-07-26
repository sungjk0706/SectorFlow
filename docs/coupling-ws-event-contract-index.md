# WebSocket 이벤트 계약 인덱스

> 작성일: 2026-07-26
> 세션: COUPLING-S3 (C-03)
> 기준 파일: `backend/app/web/ws_manager.py`, `backend/app/services/engine_account_notify.py`, `frontend/src/binding.ts`, `frontend/src/stores/hotStore.ts`, `frontend/src/stores/uiStore.ts`, `frontend/src/stores/stockClassificationStore.ts`
> 원칙: P5 직접 호출·Queue 경계 유지, P10 SSOT, P16 살아있는 경로, P21 사용자 투명성, P23 일관성, P24 단순성, P25 격리된 실패
> 상태: 조사 전수 완료 (운영 코드 수정 없음, 인덱스 문서만 작성)

---

## 1. 목적과 범위

WebSocket 이벤트의 **이름 · 채널 · producer · payload 필드 · Store 액션 · 화면 consumer · 갱신 빈도**를 실제 코드 참조로 확정한다. 각 이벤트별 계약을 고정하여:

- 문자열 이벤트명 오타, producer/consumer 누락, payload 필드명·필수성 불일치를 식별한다.
- 백엔드 → binding → Store → 화면(CustomEvent) 다단 연결의 단일 목록을 제공한다 (P10 SSOT).
- 반복되거나 안전상 중요한 이벤트만 명시 타입·공통 상수로 승격할 후보를 정한다. 새 EventBus는 도입하지 않는다 (P5).
- 주문 차단·엔진 저하·진행률 등 사용자에게 중요한 상태가 화면에서 사라지지 않는지 점검한다 (P21).

본 세션은 인덱스 작성까지만 수행하며, 한 이벤트군의 명시 계약 승격은 후속 세션에서 별도 승인 후 진행한다.

### 조사 범위 (실제 코드 기준)

- 백엔드 WS 매니저: `backend/app/web/ws_manager.py` `WSManager`(broadcast / broadcast_to_pages / send_to / _send_realdata_encoded)
- 백엔드 WS 라우트: `backend/app/web/routes/ws.py`(prices) · `ws_settings.py`(settings) · `ws_orders.py`(orders)
- 백엔드 producer 허브: `backend/app/services/engine_account_notify.py`(`_broadcast`/`_safe_broadcast` 래퍼 + 11개 notify_* 함수)
- 백엔드 페이지 분리: `backend/app/services/engine_account_broadcast.py`(account-update 경량화/전체)
- 백엔드 큐 기반 producer: `backend/app/pipelines/pipeline_gateway.py`(`broadcast_queue` 컨슘 → ws_manager.broadcast)
- 백엔드 직접 producer: `trade_history.py`, `engine_loop.py`, `trading.py`, `daily_time_scheduler.py`, `engine_ws_dispatch.py`, `engine_account.py`, `ws_subscribe_control.py`, `engine_snapshot.py`, `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `market_close_pipeline.py`, `stock_classification.py`(라우트), `settings.py`(라우트)
- 프론트엔드 바인딩: `frontend/src/binding.ts` `bindWSToStore()` (36개 onEvent 핸들러)
- 프론트엔드 WS 클라: `frontend/src/api/ws.ts` `WSClient`(3 채널 분리, onEvent Map)
- 프론트엔드 Store: `hotStore.ts`(14 액션), `uiStore.ts`(15 액션), `stockClassificationStore.ts`(1 액션)
- 프론트엔드 CustomEvent 배칭: `hotStore.ts` `flushTickBatch()` (rAF coalescing, 3종 tick)
- 프론트엔드 페이지 consumer: `buy-target.ts`, `sell-position.ts`, `profit-overview-mount.ts`, `sector-stock.ts`

### 조사 방법

- `ws_manager.broadcast(` / `broadcast_to_pages(` / `send_to(` 3패턴으로 `backend/app` 전수 grep
- `engine_account_notify._broadcast` / `_safe_broadcast` 래퍼 경유 간접 producer 추적
- `broadcast_queue.put` / `get_broadcast_queue` 큐 기반 producer 추적 (`core_queue.py`, `pipeline_gateway.py`, `pipeline_compute.py`, `pipeline_compute_tick_handlers.py`, `market_close_pipeline.py`, `stock_classification.py`)
- `binding.ts` `onEvent(` 36개 핸들러 전수 추출 → 각 핸들러가 호출하는 Store 액션과 수정 상태 필드 추적
- `window.dispatchEvent` / `new CustomEvent` / `addEventListener` 프론트엔드 전수 grep → WS→CustomEvent 배칭 경로 추적
- 프론트엔드 구독 36개 이벤트와 백엔드 producer 1:1 대조 → 누락 producer 식별
- 이벤트명 문자열 하이픈/언더스코어 네이밍 컨벤션 분석
- payload 필드명 백엔드 producer ↔ 프론트엔드 기대값 대조

### WS 채널 구조 (3 채널 분리)

| 채널 | 엔드포인트 | WSClient | 목적 | 클라이언트→서버 메시지 |
|------|-----------|----------|------|----------------------|
| prices | `/api/ws/prices` | `pricesClient` | 시세·계좌·업종·차단 상태 (대부분) | `ping`, `page-active`, `page-inactive`, `subscribe-fids` |
| settings | `/api/ws/settings` | `settingsClient` | 설정·진행률 (시세 폭주 격리) | `ping`, `page-active`, `page-inactive` |
| orders | `/api/ws/orders` | `ordersClient` | 체결 (시세 폭주 격리) | `ping` |

> 주의: 3개 채널 모두 동일 `ws_manager` 싱글턴을 공유하므로, `broadcast()`는 3개 채널의 모든 클라이언트에게 전송한다. 채널 분리는 TCP 연결 분리(헤드오브라인 블로킹 방지)일 뿐 이벤트 라우팅 분리가 아니다. `broadcast_to_pages()`만 활성 페이지 기반 필터링을 수행한다.

---

## 2. 전체 이벤트 인덱스 (40개 = 36 구독 + 4 누락 producer)

### 2.1 요약

| 분류 | 이벤트 수 | 비고 |
|------|----------|------|
| **정상 계약 (producer + consumer 일치)** | 30 | payload 필드 일치 또는 부분 일치 |
| **payload 필드 불일치** | 2 | `ws-subscribe-status`(`index_subscribed` 누락), `account-update`(경량화/전체 분기) |
| **다중 producer (동일 이벤트 다른 파일)** | 6 | `index-data`(4곳), `market-phase`(3곳), `stock-classification-changed`(3곳), `buy-targets-update`(2곳), `sector-stocks-refresh`(2곳), `engine-ready`(2곳), `circuit_breaker_open`(2곳) |
| **프론트엔드 구독 + 백엔드 producer 누락 (P16/P21 위반)** | 4 | `engine-reload-complete`, `bootstrap-stage`, `avg-amt-progress`, `order-filled` |
| **네이밍 컨벤션 불일치 (P23)** | 6 | `circuit_breaker_open`, `order_time_blocked`, `risk_block_status`, `realtime_latency_status`, `daily_buy_state_status`, `test_cash_failed` (나머지 34개는 hyphen) |

### 2.2 이벤트 전체 목록 (이름 · 채널 · producer · consumer · 갱신 빈도)

| # | 이벤트 이름 | 채널 | Producer (백엔드) | Consumer (프론트) | Store 액션 | 갱신 빈도 |
|---|-----------|------|------------------|------------------|-----------|----------|
| 1 | `initial-snapshot` | prices | `ws.py:85` (send_to, 연결 시 1회) | binding.ts:79 | `applyInitialSnapshotHot` + `applyInitialSnapshotUI` | 연결 시 1회 |
| 2 | `account-update` | prices | `engine_account_broadcast.py:47,66,70` (broadcast_to_pages/broadcast) | binding.ts:84 | `applyAccountUpdate` | 체결/잔고/시세 변경 시 (delta) |
| 3 | `buy-targets-update` | prices | `ws.py:138` (send_to), `engine_account_notify.py:418` (broadcast) | binding.ts:89 | `applyBuyTargetsUpdate` | 매수 후보 변경 시 (초기/전체) |
| 4 | `sector-stocks-refresh` | prices | `ws.py:91` (send_to), `engine_account_notify.py:349` (broadcast) | binding.ts:93 | `applySectorStocksRefresh` | 종목 목록 변경 시 (전체) |
| 5 | `sector-stocks-delta` | prices | `engine_account_notify.py:360` (broadcast) | binding.ts:98 | `applySectorStocksDelta` | 종목 목록 변경 시 (증분) |
| 6 | `buy-targets-delta` | prices | `engine_account_notify.py:447` (broadcast) | binding.ts:102 | 인라인 setState (rebuildBuyTargetIndex) | 매수 후보 변경 시 (증분) |
| 7 | `buy-history-append` | prices | `trade_history.py:201` (broadcast) | binding.ts:150 | 인라인 setState (`buyHistory`) | 매수 체결 시 단건 |
| 8 | `real-data` | prices | `pipeline_compute_tick_handlers.py:237` (broadcast_queue → gateway) | binding.ts:157 | `applyRealData` | 틱마다 (고빈도) |
| 9 | `orderbook-update` | prices | `engine_account_notify.py:334` (broadcast) | binding.ts:161 | `applyOrderbookUpdate` | 호가잔량 변경 시 |
| 10 | `program-update` | prices | `engine_account_notify.py:460` (broadcast) | binding.ts:165 | `applyProgramUpdate` | 프로그램 순매수 변경 시 |
| 11 | `stock-classification-changed` | prices | `ws.py:76` (send_to), `stock_classification.py:130` (broadcast_queue), `stock_classification.py:132` (broadcast 폴백) | binding.ts:217 | `applyStockClassificationChanged` | 종목 분류 변경 시 |
| 12 | `sell-history-append` | prices | `trade_history.py:192` (broadcast) | binding.ts:221 | 인라인 setState (`sellHistory`, `dailySummary`) | 매도 체결 시 단건 |
| 13 | `engine-ready` | prices | `engine_loop.py:41` (broadcast), `ws.py:42` (send_to) | binding.ts:231 | `applyEngineReloadComplete` | 엔진 데이터 준비 완료 시 1회 |
| 14 | `confirmed-progress` | prices | `market_close_pipeline.py:65` (broadcast_queue → gateway) | binding.ts:235 | `applyAvgAmtProgress` | 장마감 파이프라인 진행 시 |
| 15 | `sell-history-update` | prices | `trade_history.py:212` (broadcast) | binding.ts:239 | `applySellHistoryUpdate` | 매도 내역 전체 갱신 시 |
| 16 | `buy-history-update` | prices | `trade_history.py:225` (broadcast) | binding.ts:243 | `applyBuyHistoryUpdate` | 매수 내역 전체 갱신 시 |
| 17 | `realtime-reset` | prices | `engine_snapshot.py:209` (broadcast) | binding.ts:247 | `applyRealtimeReset` | 엔진 재초기화 시 |
| 18 | `market-phase` | prices | `daily_time_scheduler.py:761,1137` (broadcast), `engine_ws_dispatch.py:343,372` (broadcast) | binding.ts:252 | `applyMarketPhase` | 장 페이즈/카운트다운 변경 시 |
| 19 | `receive-rate` | prices | `pipeline_compute.py:97` (broadcast_queue → gateway) | binding.ts:265 | 인라인 setState (`receiveRate`) | 수신율 계산 시 |
| 20 | `sector-scores` | prices | `engine_account_notify.py:267` (broadcast) | binding.ts:274 | `applySectorScores` + 인라인 setState (`sectorScoresDelta`, `receiveRate`) | 업종순위 변경 시 (delta/전체) |
| 21 | `ws-subscribe-status` | prices | `ws_subscribe_control.py:62` (broadcast) | binding.ts:300 | `applyWsSubscribeStatus` | WS 구독 상태 변경 시 |
| 22 | `circuit_breaker_open` | prices | `trading.py:438,647` (broadcast) | binding.ts:305 | `applyCircuitBreakerOpen` + showToast | 서킷브레이커 차단 시 |
| 23 | `order_time_blocked` | prices | `daily_time_scheduler.py:766` (broadcast) | binding.ts:312 | `applyOrderTimeBlocked` | 체결 불가 시간대 (10초 주기) |
| 24 | `risk_block_status` | prices | `trading.py:742` (broadcast) | binding.ts:317 | `applyRiskBlockStatus` | 리스크 매니저 차단 시 |
| 25 | `buy-limit-status` | prices | `engine_account.py:87` (broadcast) | binding.ts:322 | `applyBuyLimitStatus` | 매수 한도 상태 변경 시 |
| 26 | `realtime_latency_status` | prices | `engine_ws_dispatch.py:120` (broadcast) | binding.ts:327 | `applyRealtimeLatencyStatus` | 실시간 지연 200ms 초과 시 |
| 27 | `daily_buy_state_status` | prices | `trading.py:118` (broadcast) | binding.ts:332 | `applyDailyBuyStateStatus` | 일일 매수 상태 로드 실패 시 |
| 28 | `test_cash_failed` | prices | `trading.py:132` (broadcast) | binding.ts:337 | `applyTestCashFailed` | 테스트 예수금 검증 실패 시 (1회성) |
| 29 | `settings-changed` | settings | `engine_account_notify.py:237` (broadcast) | binding.ts:180 | `applySettingsChanged` | 설정 변경 시 (전체/delta) |
| 30 | `engine-reload-complete` | settings | **❌ 백엔드 producer 없음** | binding.ts:184 | `applyEngineReloadComplete` | (구독만 존재, dead subscription) |
| 31 | `index-data` | settings | `engine_account_notify.py:195,215` (broadcast), `ws.py:146,155` (send_to) | binding.ts:188 | `applyIndexData` | 엔진 상태/업종지수 변경 시 |
| 32 | `bootstrap-stage` | settings | **❌ 백엔드 producer 없음** | binding.ts:192 | `applyBootstrapStage` | (구독만 존재, dead subscription) |
| 33 | `avg-amt-progress` | settings | **❌ 백엔드 producer 없음** | binding.ts:196 | `applyAvgAmtProgress` | (구독만 존재, dead subscription) |
| 34 | `daily-summary-update` | settings | `trade_history.py:215` (broadcast) | binding.ts:201 | `applyDailySummaryUpdate` | 일일 요약 갱신 시 |
| 35 | `order-filled` | orders | **❌ 백엔드 producer 없음** | binding.ts:207 | `applyOrderFilled` | (구독만 존재, dead subscription) |
| 36 | `test-data-reset-completed` | orders | `settings.py:188` (broadcast) | binding.ts:212 | `applyTestDataResetCompleted` | 테스트 데이터 초기화 완료 시 |

---

## 3. 이벤트별 상세 계약 (payload 필드)

### 3.1 prices 채널 — 시세·계좌·업종 (이벤트 1~28)

#### `initial-snapshot` (연결 시 1회 유니캐스트)
- **Producer**: `ws.py:85` `ws_manager.send_to(websocket, "initial-snapshot", snapshot)` — `build_initial_snapshot()` 반환값
- **Payload**: `build_initial_snapshot()` 결과 전체 (account, positions, sectorStocks, sectorScores, buyTargets, sellHistory, buyHistory, dailySummary + UI 상태 필드들)
- **Consumer**: binding.ts:79 → `applyInitialSnapshotHot(data)` + `applyInitialSnapshotUI(data)`
- **수정 상태**: hotStore(`account`, `positionCount`, `positions`, `sectorStocks`, `sectorScores`, `buyTargets`, `sellHistory`, `buyHistory`, `dailySummary`) + uiStore(`settings`, `status`, `sectorStatus`, `sectorSummary`, `buyLimitStatus`, `wsSubscribeStatus`, `initialized`, `circuitBreakerOpen`, `orderTimeBlocked`, `riskBlockStatus`, `realtimeLatencyExceeded`, `dailyBuyStateFailed`, `testCashFailed`, `positionBuildFailed`, `degradedMode`, `engineReady`, `marketPhase`, `receiveRate`)
- **계약 상태**: ✅ 단일 producer, 단일 consumer

#### `account-update` (체결/잔고/시세 변경 시 delta)
- **Producer**: `engine_account_broadcast.py:47` (경량화, `broadcast_to_pages({"profit-overview"})`), `engine_account_broadcast.py:66` (전체, `broadcast_to_pages({"sell-position"})` 또는 `{"profit-overview","sell-position"}`), `engine_account_broadcast.py:70` (폴백, `broadcast` 전체)
- **Payload (경량화)**: `{"snapshot": {deposit, orderable, accumulated_investment, initial_deposit, total_eval_amount, total_pnl, total_pnl_rate}, "position_count": number, "changed_positions": [{_POSITION_CMP_KEYS}], "removed_codes": [str]}`
- **Payload (전체)**: `{"snapshot": dict, "changed_positions": [dict], "removed_codes": [str]}`
- **Consumer**: binding.ts:84 → `applyAccountUpdate(data as AccountUpdateEvent)`
- **수정 상태**: hotStore(`account`, `positions`, `positionCount`)
- **계약 상태**: ⚠️ 단일 producer 파일이지만 3개 분기 (경량화/전체/폴백). payload 구조가 분기별 상이. 프론트엔드 `AccountUpdateEvent` 타입이 두 분기를 모두 수용하는지 별도 검증 필요.

#### `buy-targets-update` (매수 후보 전체)
- **Producer**: `ws.py:138` (send_to, 연결 시), `engine_account_notify.py:418` (broadcast, 초기 상태)
- **Payload**: `{"_v": 1, "buy_targets": [SectorStock]}` (실시간 필드 포함)
- **Consumer**: binding.ts:89 → `applyBuyTargetsUpdate({buy_targets})`
- **수정 상태**: hotStore(`buyTargets`)
- **계약 상태**: ✅ 다중 producer이나 payload 일치

#### `sector-stocks-refresh` (종목 목록 전체)
- **Producer**: `ws.py:91` (send_to, 연결 시), `engine_account_notify.py:349` (broadcast, force/초기)
- **Payload**: `{"stocks": [SectorStock]}`
- **Consumer**: binding.ts:93 → `applySectorStocksRefresh({stocks})`
- **수정 상태**: hotStore(`sectorStocks`, `buyTargets` rebind)
- **계약 상태**: ✅ 다중 producer이나 payload 일치

#### `sector-stocks-delta` (종목 목록 증분)
- **Producer**: `engine_account_notify.py:360` (broadcast)
- **Payload**: `{"added": [SectorStock], "removed": [str]}`
- **Consumer**: binding.ts:98 → `applySectorStocksDelta({added, removed})`
- **수정 상태**: hotStore(`sectorStocks`, `buyTargets` rebind)
- **계약 상태**: ✅ 단일 producer

#### `buy-targets-delta` (매수 후보 증분)
- **Producer**: `engine_account_notify.py:447` (broadcast)
- **Payload**: `{"added": [SectorStock], "removed": [str], "changed": [SectorStock]}` — 정적 필드만 (실시간 필드 `_BUY_TARGET_REALTIME_KEYS` 제거)
- **Consumer**: binding.ts:102 → 인라인 setState (sectorStocks에서 실시간 필드 재결합)
- **수정 상태**: hotStore(`buyTargets`) + `rebuildBuyTargetIndex`
- **계약 상태**: ✅ 단일 producer. 실시간 필드는 sectorStocks SSOT에서 파생 (P10)

#### `buy-history-append` (매수 체결 단건)
- **Producer**: `trade_history.py:201` (broadcast)
- **Payload**: `{"trade": dict}`
- **Consumer**: binding.ts:150 → 인라인 setState (`buyHistory: [trade, ...state.buyHistory]`)
- **수정 상태**: hotStore(`buyHistory`)
- **계약 상태**: ✅ 단일 producer

#### `real-data` (틱 데이터, 고빈도)
- **Producer**: `pipeline_compute_tick_handlers.py:237` (broadcast_queue → `pipeline_gateway.py:120` ws_manager.broadcast) — FID 필터 + key shortening (`type→t`, `item→i`, `values→v`)은 `ws_manager._send_realdata_encoded`에서 수행
- **Payload (원본)**: `{"type": "real-data", "item": stk_cd, "values": {fid: val}, "_ts": number}`
- **Payload (전송, key shorten)**: `{"event": "real-data", "data": {"t": "real-data", "i": stk_cd, "v": {fid: val}, "_v": 1}}`
- **Consumer**: binding.ts:157 → `applyRealData(data as RealDataEvent)`
- **수정 상태**: hotStore(`sectorStocks`, `buyTargets`, `positions` in-place mutation) → dirty Set → rAF `flushTickBatch()` → CustomEvent `real-data-tick`
- **계약 상태**: ✅ 단일 producer. 고빈도 이벤트 rAF 배칭 적용.

#### `orderbook-update` (호가잔량 변경)
- **Producer**: `engine_account_notify.py:334` (broadcast)
- **Payload**: `{"code": str, "bid": int, "ask": int}`
- **Consumer**: binding.ts:161 → `applyOrderbookUpdate({code, bid, ask})`
- **수정 상태**: hotStore(`buyTargets[].order_ratio` in-place) → CustomEvent `orderbook-tick`
- **계약 상태**: ✅ 단일 producer

#### `program-update` (프로그램 순매수 변경)
- **Producer**: `engine_account_notify.py:460` (broadcast)
- **Payload**: `{"code": str, "net_buy": int}`
- **Consumer**: binding.ts:165 → `applyProgramUpdate({code, net_buy})`
- **수정 상태**: hotStore(`buyTargets[].program_net_buy` in-place) → CustomEvent `program-tick`
- **계약 상태**: ✅ 단일 producer

#### `stock-classification-changed` (종목 분류 변경)
- **Producer**: `ws.py:76` (send_to, 연결 시), `stock_classification.py:130` (broadcast_queue → gateway), `stock_classification.py:132` (broadcast 폴백)
- **Payload**: `{"_v": 1, "custom_data": {sectors: dict, stock_moves: dict}, "merged_sectors": dict, "no_sector_count": int, "filter_summary": str, "all_stocks": [dict]}`
- **Consumer**: binding.ts:217 → `applyStockClassificationChanged(data)`
- **수정 상태**: stockClassificationStore(`sectors`, `stockMoves`, `mergedSectors`, `noSectorCount`, `filter_summary`, `allStocks`)
- **계약 상태**: ✅ 다중 producer이나 payload 일치

#### `sell-history-append` (매도 체결 단건)
- **Producer**: `trade_history.py:192` (broadcast)
- **Payload**: `{"trade": dict, "daily_summary": [dict]}`
- **Consumer**: binding.ts:221 → 인라인 setState (`sellHistory`, `dailySummary`)
- **수정 상태**: hotStore(`sellHistory`, `dailySummary`)
- **계약 상태**: ✅ 단일 producer

#### `engine-ready` (엔진 데이터 준비 완료)
- **Producer**: `engine_loop.py:41` (broadcast), `ws.py:42` (send_to, 연결 시)
- **Payload**: `{"_v": 1, "ready": True}`
- **Consumer**: binding.ts:231 → `applyEngineReloadComplete()`
- **수정 상태**: uiStore(`engineReloadComplete`, `circuitBreakerOpen`)
- **계약 상태**: ✅ 다중 producer이나 payload 일치. `engine-reload-complete`와 동일 액션 호출 (중복 구독, §4 참조)

#### `confirmed-progress` (장마감 파이프라인 진행률)
- **Producer**: `market_close_pipeline.py:65` (broadcast_queue → gateway)
- **Payload**: `{"_v": 1, "current": int, "total": int, "message": str, "eta_sec": int, "status": str, "step": int, "failed_count": int}`
- **Consumer**: binding.ts:235 → `applyAvgAmtProgress(data)` — `avg-amt-progress`와 동일 액션
- **수정 상태**: uiStore(`avgAmtProgress`)
- **계약 상태**: ✅ 단일 producer. `avg-amt-progress`와 동일 액션 호출 (중복 구독, §4 참조)

#### `sell-history-update` / `buy-history-update` (전체 갱신)
- **Producer**: `trade_history.py:212` / `trade_history.py:225` (broadcast)
- **Payload**: `{"sell_history": [dict]}` / `{"buy_history": [dict]}`
- **Consumer**: binding.ts:239 / 243 → `applySellHistoryUpdate` / `applyBuyHistoryUpdate`
- **수정 상태**: hotStore(`sellHistory` / `buyHistory`)
- **계약 상태**: ✅ 단일 producer

#### `realtime-reset` (실시간 데이터 리셋)
- **Producer**: `engine_snapshot.py:209` (broadcast)
- **Payload**: `{}` (빈 dict)
- **Consumer**: binding.ts:247 → `applyRealtimeReset()`
- **수정 상태**: hotStore(`sectorStocks`, `buyTargets`, `positions`)
- **계약 상태**: ✅ 단일 producer

#### `market-phase` (장 상태/카운트다운)
- **Producer**: `daily_time_scheduler.py:761,1137` (broadcast), `engine_ws_dispatch.py:343,372` (broadcast)
- **Payload**: `{"krx": str, "nxt": str, "krx_alert": str|null, "is_nxt_only": bool, "krx_countdown": {label, remaining_sec}|null, "nxt_countdown": {label, remaining_sec}|null}` (전체) 또는 `{"krx_alert": str}` (부분, engine_ws_dispatch.py:372)
- **Consumer**: binding.ts:252 → `applyMarketPhase(data as Partial<{krx, nxt, krx_alert, is_nxt_only, krx_countdown, nxt_countdown}>)`
- **수정 상태**: uiStore(`marketPhase`)
- **계약 상태**: ⚠️ 다중 producer (3곳), 부분 payload 전송 존재. 프론트엔드가 `Partial<>`로 수용.

#### `receive-rate` (수신율)
- **Producer**: `pipeline_compute.py:97` (broadcast_queue → gateway)
- **Payload**: `{"krx": ReceiveRateEntry, "nxt": ReceiveRateEntry}` (크롭 구조: `{pct, received, total}`)
- **Consumer**: binding.ts:265 → 인라인 setState (`receiveRate: {krx, nxt}`)
- **수정 상태**: uiStore(`receiveRate`)
- **계약 상태**: ✅ 단일 producer. `sector-scores`의 `status.receive_rate`에서도 동일 데이터 전송 (중복 경로, §5 참조)

#### `sector-scores` (업종순위, delta/전체)
- **Producer**: `engine_account_notify.py:267` (broadcast)
- **Payload (전체)**: `{"scores": [SectorScoreRow], "status": {total_stocks, max_targets, ranked_sectors_count, receive_rate}}`
- **Payload (delta)**: `{"changed_scores": [SectorScoreRow], "status": {...}, "delta": true, "changed_sectors": [str], "removed_sectors": [str]}`
- **Consumer**: binding.ts:274 → `applySectorScores(d)` + 인라인 setState (`sectorScoresDelta`, `receiveRate` from `status.receive_rate`)
- **수정 상태**: hotStore(`sectorScores`) + uiStore(`sectorScoresDelta`, `receiveRate`)
- **계약 상태**: ✅ 단일 producer. `receive-rate` 이벤트와 `status.receive_rate` 필드가 동일 데이터 (중복 경로)

#### `ws-subscribe-status` (WS 구독 상태) — ⚠️ payload 불일치
- **Producer**: `ws_subscribe_control.py:62` (broadcast)
- **Payload (백엔드)**: `{"_v": 1, "quote_subscribed": bool}`
- **Consumer**: binding.ts:300 → `applyWsSubscribeStatus(data as {index_subscribed: boolean; quote_subscribed: boolean})`
- **수정 상태**: uiStore(`wsSubscribeStatus`)
- **계약 상태**: ❌ **payload 필드 불일치** — 프론트엔드가 `index_subscribed` 필드를 기대하지만 백엔드가 전송하지 않음. `applyWsSubscribeStatus`가 `index_subscribed`를 `undefined`로 처리할 것. P21/P23 위반 후보.

#### `circuit_breaker_open` (서킷브레이커 차단) — ⚠️ 네이밍 underscore
- **Producer**: `trading.py:438` (매수), `trading.py:647` (매도) (broadcast)
- **Payload**: `{"message": str}`
- **Consumer**: binding.ts:305 → `applyCircuitBreakerOpen(d)` + `showToast('error', d.message ?? '서킷브레이커 발동 — 자동매매 중지', 8000)`
- **수정 상태**: uiStore(`circuitBreakerOpen`)
- **계약 상태**: ✅ 다중 producer이나 payload 일치. 네이밍 underscore (P23 위반 후보, §6 참조)

#### `order_time_blocked` (체결 불가 시간대, 10초 주기) — ⚠️ 네이밍 underscore
- **Producer**: `daily_time_scheduler.py:766` (broadcast)
- **Payload**: `{"blocked": bool, "reason": str}`
- **Consumer**: binding.ts:312 → `applyOrderTimeBlocked({blocked?, reason?})`
- **수정 상태**: uiStore(`orderTimeBlocked`)
- **계약 상태**: ✅ 단일 producer. 네이밍 underscore.

#### `risk_block_status` (리스크 매니저 차단) — ⚠️ 네이밍 underscore
- **Producer**: `trading.py:742` (broadcast)
- **Payload**: `{"blocked": bool, "side": str, "reason": str}`
- **Consumer**: binding.ts:317 → `applyRiskBlockStatus({blocked?, side?, reason?})`
- **수정 상태**: uiStore(`riskBlockStatus`)
- **계약 상태**: ✅ 단일 producer. 네이밍 underscore.

#### `buy-limit-status` (매수 한도 상태)
- **Producer**: `engine_account.py:87` (broadcast)
- **Payload**: `{"daily_buy_spent": number}` (`get_buy_limit_status()` 반환값)
- **Consumer**: binding.ts:322 → `applyBuyLimitStatus({daily_buy_spent})`
- **수정 상태**: uiStore(`buyLimitStatus`)
- **계약 상태**: ✅ 단일 producer

#### `realtime_latency_status` (실시간 지연 200ms 초과) — ⚠️ 네이밍 underscore
- **Producer**: `engine_ws_dispatch.py:120` (broadcast)
- **Payload**: `{"blocked": bool}`
- **Consumer**: binding.ts:327 → `applyRealtimeLatencyStatus({blocked?})`
- **수정 상태**: uiStore(`realtimeLatencyExceeded`)
- **계약 상태**: ✅ 단일 producer. 네이밍 underscore.

#### `daily_buy_state_status` (일일 매수 상태 로드 실패) — ⚠️ 네이밍 underscore
- **Producer**: `trading.py:118` (broadcast)
- **Payload**: `{"failed": bool}`
- **Consumer**: binding.ts:332 → `applyDailyBuyStateStatus({failed?})`
- **수정 상태**: uiStore(`dailyBuyStateFailed`)
- **계약 상태**: ✅ 단일 producer. 네이밍 underscore.

#### `test_cash_failed` (테스트 예수금 검증 실패, 1회성) — ⚠️ 네이밍 underscore
- **Producer**: `trading.py:132` (broadcast)
- **Payload**: `{"failed": bool, "stk_cd": str, "reason": str}`
- **Consumer**: binding.ts:337 → `applyTestCashFailed({failed?, stk_cd?, reason?})`
- **수정 상태**: uiStore(`testCashFailed`)
- **계약 상태**: ✅ 단일 producer. 네이밍 underscore.

### 3.2 settings 채널 — 설정·진행률 (이벤트 29~34)

#### `settings-changed` (설정 변경, 전체/delta)
- **Producer**: `engine_account_notify.py:237` (broadcast)
- **Payload (전체)**: `get_settings_snapshot()` + `{"_v": 1}`
- **Payload (delta)**: `{"_v": 1, "delta": true, "changed": {key: value}}`
- **Consumer**: binding.ts:180 → `applySettingsChanged(data as AppSettings)`
- **수정 상태**: uiStore(`settings`)
- **계약 상태**: ⚠️ 단일 producer이나 두 분기 (전체/delta). 프론트엔드 `AppSettings` 타입이 delta 분기(`{delta: true, changed: {...}}`)를 수용하는지 별도 검증 필요.

#### `engine-reload-complete` — ❌ 백엔드 producer 없음
- **Consumer**: binding.ts:184 → `applyEngineReloadComplete()`
- **수정 상태**: uiStore(`engineReloadComplete`, `circuitBreakerOpen`)
- **계약 상태**: ❌ **dead subscription (P16 위반)** — 백엔드에 producer 전혀 없음. `engine-ready`가 동일 액션 `applyEngineReloadComplete`를 호출하므로 기능적으로 중복 구독. §4 참조.

#### `index-data` (엔진 상태/업종지수)
- **Producer**: `engine_account_notify.py:195` (`notify_desktop_header_refresh`, broadcast), `engine_account_notify.py:215` (`notify_index_data`, broadcast), `ws.py:146` (send_to, 연결 시 엔진 상태), `ws.py:155` (send_to, 연결 시 업종지수 캐시 재전송)
- **Payload (엔진 상태)**: `get_engine_status()` + `{"_v": 1}` (broker_statuses 포함)
- **Payload (업종지수)**: `{"_v": 1, "upcode": str, "jisu": str, "change": str, "drate": str, "sign": str, "broker_statuses": dict}`
- **Consumer**: binding.ts:188 → `applyIndexData(data as IndexData)`
- **수정 상태**: uiStore(`indexData`, `status`, `marketPhase`)
- **계약 상태**: ⚠️ 다중 producer (4곳), 두 가지 payload 형태 (엔진 상태/업종지수). 프론트엔드 `IndexData` 타입이 두 형태를 모두 수용하는지 별도 검증 필요.

#### `bootstrap-stage` — ❌ 백엔드 producer 없음
- **Consumer**: binding.ts:192 → `applyBootstrapStage({stage_id, stage_name, total, progress?})`
- **수정 상태**: uiStore(`bootstrapStage`)
- **계약 상태**: ❌ **dead subscription (P16/P21 위반)** — 백엔드에 producer 전혀 없음. 부트스트랩 단계 진행이 화면에 표시되지 않음.

#### `avg-amt-progress` — ❌ 백엔드 producer 없음
- **Consumer**: binding.ts:196 → `applyAvgAmtProgress({current, total, done, message?, eta_sec?, status?, step?, failed_count?})`
- **수정 상태**: uiStore(`avgAmtProgress`)
- **계약 상태**: ❌ **dead subscription (P16 위반)** — 백엔드에 producer 전혀 없음. `confirmed-progress`가 동일 액션 `applyAvgAmtProgress`를 호출하므로 기능적으로 중복 구독. §4 참조.

#### `daily-summary-update` (일일 요약 갱신)
- **Producer**: `trade_history.py:215` (broadcast)
- **Payload**: `{"daily_summary": [dict]}`
- **Consumer**: binding.ts:201 → `applyDailySummaryUpdate({daily_summary})`
- **수정 상태**: hotStore(`dailySummary`)
- **계약 상태**: ✅ 단일 producer

### 3.3 orders 채널 — 체결 (이벤트 35~36)

#### `order-filled` — ❌ 백엔드 producer 없음
- **Consumer**: binding.ts:207 → `applyOrderFilled(data)`
- **수정 상태**: hotStore(`buyHistory`, `sellHistory`)
- **계약 상태**: ❌ **dead subscription (P16/P21 위반)** — 백엔드에 producer 전혀 없음. 체결 관련은 `buy-history-append`/`sell-history-append`로 대체된 것으로 추정. orders 채널의 유일한 비-ping 이벤트가 dead subscription이면 채널 자체가 사실상 미사용.

#### `test-data-reset-completed` (테스트 데이터 초기화 완료)
- **Producer**: `settings.py:188` (broadcast)
- **Payload**: `{"_v": 1}`
- **Consumer**: binding.ts:212 → `applyTestDataResetCompleted()`
- **수정 상태**: uiStore(`buyLimitStatus`)
- **계약 상태**: ✅ 단일 producer. 단, 이 이벤트는 `settings.py` 라우트에서 `broadcast`로 전송되므로 3개 채널 모든 클라이언트에게 전송됨. orders 채널에서만 수신되는 것 아님.

---

## 4. P16/P21 위반 후보 — 4개 dead subscription (프론트엔드 구독 + 백엔드 producer 누락)

| 이벤트 | 채널 | 프론트엔드 구독 | 백엔드 producer | 동일 액션 대체 이벤트 | 위반 원칙 |
|--------|------|----------------|----------------|---------------------|----------|
| `engine-reload-complete` | settings | binding.ts:184 | ❌ 없음 | `engine-ready` (동일 `applyEngineReloadComplete`) | P16 (dead code), P24 (중복 구독) |
| `bootstrap-stage` | settings | binding.ts:192 | ❌ 없음 | ❌ 대체 없음 | **P16 + P21** (사용자 투명성 위반 — 부트스트랩 진행이 화면에 표시되지 않음) |
| `avg-amt-progress` | settings | binding.ts:196 | ❌ 없음 | `confirmed-progress` (동일 `applyAvgAmtProgress`) | P16 (dead code), P24 (중복 구독) |
| `order-filled` | orders | binding.ts:207 | ❌ 없음 | `buy-history-append`/`sell-history-append` (유사 기능) | P16 (dead code), P21 (체결 알림 경로 불명확) |

### 4.1 분석

- `engine-reload-complete` / `avg-amt-progress`: 동일 Store 액션을 호출하는 대체 이벤트가 존재하므로 기능 손실 없이 dead subscription 제거 가능. P24(단순성) 관점에서 중복 구독 정리 권장.
- `bootstrap-stage`: 대체 이벤트가 없으며, 부트스트랩 단계 진행이 사용자에게 표시되지 않음. **P21(사용자 투명성) 위반**. 백엔드에서 부트스트랩 단계를 전송하는 producer를 추가하거나, 구독을 제거하고 `initial-snapshot`의 `bootstrapStage` 필드로 대체해야 함.
- `order-filled`: 체결 알림이 `buy-history-append`/`sell-history-append`로 대체된 것으로 추정되나, orders 채널의 유일한 비-ping 이벤트가 dead subscription이면 orders 채널 자체가 사실상 미사용 상태. 채널 분리 목적(시세 폭주 격리)이 무의미해짐.

### 4.2 후속 조치 우선순위

| 순위 | 이벤트 | 조치 | 위험도 |
|------|--------|------|--------|
| 1 | `bootstrap-stage` | producer 추가 또는 구독 제거 + `initial-snapshot` 필드 대체 | 높음 (P21 위반, 사용자 투명성) |
| 2 | `order-filled` | 구독 제거 + orders 채널 존재 의미 검토 | 중간 (채널 분리 설계 영향) |
| 3 | `engine-reload-complete` | 구독 제거 (`engine-ready`로 충분) | 낮음 (중복 제거) |
| 4 | `avg-amt-progress` | 구독 제거 (`confirmed-progress`로 충분) | 낮음 (중복 제거) |

---

## 5. 다중 producer 이벤트 (P10 SSOT 관점)

| 이벤트 | Producer 수 | Producer 위치 | payload 일치 여부 | 비고 |
|--------|------------|--------------|------------------|------|
| `index-data` | 4 | `engine_account_notify.py:195,215`, `ws.py:146,155` | ⚠️ 두 가지 형태 (엔진 상태/업종지수) | 단일화 후보 — `notify_index_data`와 `broadcast_engine_status_ws`가 동일 이벤트로 혼용 |
| `market-phase` | 3 | `daily_time_scheduler.py:761,1137`, `engine_ws_dispatch.py:343,372` | ⚠️ 부분 payload 존재 (`{krx_alert}`만 전송) | 단일화 후보 — 부분 payload 전송을 전체 payload로 통일 검토 |
| `stock-classification-changed` | 3 | `ws.py:76`, `stock_classification.py:130,132` | ✅ 일치 | 자연스러운 다중 producer (연결 시 유니캐스트 + 변경 시 브로드캐스트) |
| `buy-targets-update` | 2 | `ws.py:138`, `engine_account_notify.py:418` | ✅ 일치 | 자연스러운 다중 producer (연결 시 + 초기 상태) |
| `sector-stocks-refresh` | 2 | `ws.py:91`, `engine_account_notify.py:349` | ✅ 일치 | 자연스러운 다중 producer (연결 시 + 변경 시) |
| `engine-ready` | 2 | `engine_loop.py:41`, `ws.py:42` | ✅ 일치 | 자연스러운 다중 producer (브로드캐스트 + 연결 시 유니캐스트) |
| `circuit_breaker_open` | 2 | `trading.py:438,647` | ✅ 일치 | 자연스러운 다중 producer (매수/매도 분기) |
| `account-update` | 1 (3분기) | `engine_account_broadcast.py:47,66,70` | ⚠️ 경량화/전체 분기 | 단일 파일 내 3분기 — 자연스러운 페이지별 최적화 |

### 5.1 단일화 후보

| 순위 | 이벤트 | 이유 |
|------|--------|------|
| 1 | `index-data` | 4곳 producer, 두 가지 payload 형태 (엔진 상태/업종지수) 혼용 — 의미 분리 또는 단일 producer 허브 검토 |
| 2 | `market-phase` | 3곳 producer, 부분 payload 전송 존재 — 전체 payload 통일 검토 |

---

## 6. 네이밍 컨벤션 불일치 (P23 일관성)

| 이벤트 이름 | 구분자 | 채널 |
|------------|--------|------|
| `circuit_breaker_open` | underscore | prices |
| `order_time_blocked` | underscore | prices |
| `risk_block_status` | underscore | prices |
| `realtime_latency_status` | underscore | prices |
| `daily_buy_state_status` | underscore | prices |
| `test_cash_failed` | underscore | prices |

나머지 34개 이벤트는 모두 hyphen 사용.

### 6.1 패턴 분석

- 6개 underscore 이벤트는 모두 **trading.py / engine_ws_dispatch.py / daily_time_scheduler.py**에서 생산되는 **상태 차단 알림** 계열.
- hyphen 이벤트는 `engine_account_notify.py`, `trade_history.py`, `ws.py` 등에서 생산되는 **데이터 갱신** 계열.
- 두 계열이 네이밍 컨벤션을 따로 따름 — P23(일관성) 위반 후보.
- 단, 6개 underscore 이벤트는 모두 프론트엔드 binding.ts에서 동일 underscore로 구독하므로 **기능적 불일치는 아님** (오타 아님).
- 후속 세션에서 hyphen 통일 검토 시 producer 6곳 + binding.ts 6곳 + 테스트 파일 전수 수정 필요.

---

## 7. CustomEvent 배칭 (WS → Store → rAF → 페이지)

### 7.1 CustomEvent 발행 (hotStore.ts `flushTickBatch()`)

| CustomEvent 이름 | 발행 위치 | Payload | 발행 빈도 |
|-----------------|----------|---------|----------|
| `real-data-tick` | `hotStore.ts:113` | `{code: string}` (정규화 종목코드) | rAF 프레임당 1회 (coalescing) |
| `orderbook-tick` | `hotStore.ts:117` | `{code: string}` | rAF 프레임당 1회 |
| `program-tick` | `hotStore.ts:121` | `{code: string}` | rAF 프레임당 1회 |

### 7.2 CustomEvent 수신 (페이지)

| CustomEvent 이름 | Consumer 파일:줄 | 동작 |
|-----------------|-----------------|------|
| `real-data-tick` | `pages/buy-target.ts:397` | `dataTable.updateItemByKey(code)` |
| `orderbook-tick` | `pages/buy-target.ts:409` | `dataTable.updateItemByKey(code)` |
| `program-tick` | `pages/buy-target.ts:421` | `dataTable.updateItemByKey(code)` |
| `real-data-tick` | `pages/sell-position.ts:284` | `dataTable.updateItemByKey(code)` + 요약 배지 갱신 |
| `real-data-tick` | `pages/profit-overview-mount.ts:392` | 계좌현황 평가손익/수익률 갱신 |
| `real-data-tick` | `pages/sector-stock.ts:446` | `dataTable.updateItemByKey(code)` |

### 7.3 배칭 경로

```
WS 이벤트 (real-data / orderbook-update / program-update)
  → binding.ts → Store 액션 (applyRealData / applyOrderbookUpdate / applyProgramUpdate)
  → hotStore in-place mutation + dirty Set 추가
  → rAF 배칭 (flushTickBatch)
  → window.dispatchEvent(CustomEvent)
  → 페이지 addEventListener 수신 → DOM 갱신
```

- binding.ts에서 직접 CustomEvent 재발행은 없음.
- CustomEvent는 hotStore 내부에서만 발행 (단일 소스, P10).
- 3종 CustomEvent 모두 `{code: string}` 단일 필드 payload — 페이지가 code로 Store에서 최종 상태를 조회하는 패턴 (이벤트는 "갱신 알림" 역할만).

---

## 8. payload 필드 불일치 상세

### 8.1 `ws-subscribe-status` — `index_subscribed` 필드 누락

- **백엔드 payload**: `{"_v": 1, "quote_subscribed": bool}` (`ws_subscribe_control.py:62`)
- **프론트엔드 기대**: `{index_subscribed: boolean; quote_subscribed: boolean}` (binding.ts:300)
- **영향**: `applyWsSubscribeStatus`가 `index_subscribed`를 `undefined`로 처리. uiStore `wsSubscribeStatus.index_subscribed`가 항상 falsy.
- **위반 원칙**: P21 (사용자 투명성 — 업종지수 구독 상태가 화면에 반영되지 않음), P23 (일관성 — payload 계약 불일치)
- **조치**: 백엔드에 `index_subscribed` 필드 추가 또는 프론트엔드 기대 타입에서 제거. 백엔드가 `index_subscribed`를 추적하지 않는다면 프론트엔드 타입에서 제거가 단순.

### 8.2 `account-update` — 경량화/전체 payload 분기

- **경량화 payload**: `{"snapshot": {7필드}, "position_count": number, "changed_positions": [{_POSITION_CMP_KEYS}], "removed_codes": [str]}`
- **전체 payload**: `{"snapshot": dict, "changed_positions": [dict], "removed_codes": [str]}`
- **영향**: 프론트엔드 `AccountUpdateEvent` 타입이 두 분기를 모두 수용해야 함. `position_count` 필드가 전체 payload에는 없음.
- **위반 원칙**: P23 (일관성 — 동일 이벤트의 payload 구조가 분기별 상이)
- **조치**: 전체 payload에도 `position_count` 포함 또는 프론트엔드가 optional로 처리. 현재 `applyAccountUpdate`가 optional 처리로 수용 가능한지 별도 검증 필요.

### 8.3 `settings-changed` — 전체/delta payload 분기

- **전체 payload**: `get_settings_snapshot()` + `{"_v": 1}` (AppSettings 전체)
- **delta payload**: `{"_v": 1, "delta": true, "changed": {key: value}}`
- **영향**: 프론트엔드 `applySettingsChanged(data as AppSettings)`가 delta 분기(`{delta: true, changed: {...}}`)를 `AppSettings`로 캐스팅 — 타입 불일치.
- **위반 원칙**: P23 (일관성 — payload 계약 불일치), 잠재적 런타임 오류
- **조치**: delta 분기를 별도 이벤트(`settings-changed-delta`)로 분리 또는 프론트엔드가 `delta` 필드로 분기 처리. 현재 `applySettingsChanged` 구현 확인 필요.

### 8.4 `index-data` — 엔진 상태/업종지수 payload 혼용

- **엔진 상태 payload**: `get_engine_status()` + `{"_v": 1}` (broker_statuses 포함, upcode 없음)
- **업종지수 payload**: `{"_v": 1, "upcode": str, "jisu": str, "change": str, "drate": str, "sign": str, "broker_statuses": dict}`
- **영향**: 프론트엔드 `IndexData` 타입이 두 형태를 모두 수용해야 함. `upcode` 유무로 분기 처리 필요.
- **위반 원칙**: P23 (일관성 — 동일 이벤트의 payload 구조가 producer별 상이), P24 (단순성 — 의미 분리 미수행)
- **조치**: 엔진 상태와 업종지수를 별도 이벤트로 분리 검토 (예: `engine-status` / `index-data`). 단, 프론트엔드 `applyIndexData`가 `upcode` 유무로 이미 분기 처리 중일 수 있음.

---

## 9. 중복 데이터 전송 경로 (P24 단순성)

### 9.1 `receive-rate` vs `sector-scores.status.receive_rate`

- `receive-rate` 이벤트: `pipeline_compute.py:97` → `{"krx": {...}, "nxt": {...}}`
- `sector-scores` 이벤트: `engine_account_notify.py:267` → `status.receive_rate` 필드에 동일 데이터 포함
- 프론트엔드 binding.ts:265 (`receive-rate`)와 binding.ts:290 (`sector-scores`의 `status.receive_rate`)가 모두 `uiStore.receiveRate`를 갱신
- **영향**: 동일 데이터가 두 경로로 전송되어 `receiveRate` 상태가 이벤트 순서에 따라 덮어쓰기됨. P10(SSOT) 관점에서 단일 경로 권장.
- **조치**: `sector-scores`의 `status.receive_rate` 제거 또는 `receive-rate` 이벤트 제거 검토. 단, `sector-scores`가 delta 전송 시 `status` 블록이 항상 포함되므로 `receive-rate` 단독 이벤트가 더 적합할 수 있음.

### 9.2 `engine-ready` vs `engine-reload-complete` (동일 액션)

- `engine-ready`: 백엔드 producer 존재, `applyEngineReloadComplete()` 호출
- `engine-reload-complete`: 백엔드 producer 없음 (dead subscription), 동일 `applyEngineReloadComplete()` 호출
- **영향**: `engine-reload-complete` 구독 제거 시 기능 손실 없음.
- **조치**: `engine-reload-complete` 구독 제거 권장 (§4 순위 3).

### 9.3 `confirmed-progress` vs `avg-amt-progress` (동일 액션)

- `confirmed-progress`: 백엔드 producer 존재, `applyAvgAmtProgress()` 호출
- `avg-amt-progress`: 백엔드 producer 없음 (dead subscription), 동일 `applyAvgAmtProgress()` 호출
- **영향**: `avg-amt-progress` 구독 제거 시 기능 손실 없음.
- **조치**: `avg-amt-progress` 구독 제거 권장 (§4 순위 4).

---

## 10. 단일화 우선순위 (후속 세션 권장)

| 순위 | 항목 | 조치 | 위험도 | 관련 원칙 |
|------|------|------|--------|----------|
| 1 | `bootstrap-stage` dead subscription | producer 추가 또는 구독 제거 + `initial-snapshot` 필드 대체 | 높음 | P21, P16 |
| 2 | `ws-subscribe-status` payload 불일치 | `index_subscribed` 필드 추가 또는 프론트엔드 타입 제거 | 중간 | P21, P23 |
| 3 | `order-filled` dead subscription + orders 채널 검토 | 구독 제거 + orders 채널 존재 의미 검토 | 중간 | P16, P24 |
| 4 | `index-data` 다중 producer + payload 혼용 | 엔진 상태/업종지수 이벤트 분리 검토 | 중간 | P10, P23, P24 |
| 5 | `engine-reload-complete` / `avg-amt-progress` 중복 구독 제거 | 구독 제거 (동일 액션 대체 이벤트 존재) | 낮음 | P16, P24 |
| 6 | `receive-rate` / `sector-scores.status.receive_rate` 중복 경로 | 단일 경로로 통일 | 낮음 | P10, P24 |
| 7 | `market-phase` 부분 payload 통일 | 부분 payload 전송을 전체 payload로 통일 | 낮음 | P23 |
| 8 | 6개 underscore 이벤트 hyphen 통일 | 네이밍 컨벤션 통일 (producer 6곳 + binding 6곳 + 테스트) | 낮음 | P23 |
| 9 | `account-update` / `settings-changed` payload 분기 정리 | 분기를 별도 이벤트로 분리 또는 optional 필드 명시 | 낮음 | P23 |

> 후속 세션에서는 위 9개 항목 중 1개만 별도 승인 후 진행 권장. 규칙 0-1(세션당 1단계) 준수.

---

## 11. 검증 결과

### 11.1 정적 대조 (이벤트명 + payload 필드)

- 프론트엔드 구독 36개 이벤트 ↔ 백엔드 producer 1:1 대조 완료
- 4개 dead subscription 식별 (`engine-reload-complete`, `bootstrap-stage`, `avg-amt-progress`, `order-filled`) — 백엔드 `backend/` 전체 grep으로 producer 0건 확인
- 2개 payload 필드 불일치 식별 (`ws-subscribe-status`, `account-update` 분기)
- 6개 네이밍 컨벤션 불일치 식별 (underscore 6개 vs hyphen 34개)
- 3개 중복 데이터 전송 경로 식별 (`receive-rate`/`sector-scores`, `engine-ready`/`engine-reload-complete`, `confirmed-progress`/`avg-amt-progress`)

### 11.2 코드 수정 없음

본 세션은 조사·인덱스 문서 작성만 수행. 운영 코드(backend/frontend) 수정 없음. 후속 세션에서 위 9개 우선순위 항목 중 1개만 별도 승인 후 진행.

### 11.3 검증 명령어 (후속 세션에서 코드 수정 시)

- `.venv/bin/python -m pytest backend/tests -q` (WS·Store 관련 테스트)
- `cd frontend && npm run typecheck`
- `cd frontend && npm run build`
- `.venv/bin/python -W error::RuntimeWarning main.py` 기동 후 잔존 프로세스 0건
- 브라우저에서 실시간 계좌·진행률·주문 차단 상태 갱신 확인
