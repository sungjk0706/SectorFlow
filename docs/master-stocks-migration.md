# 마스터 종목 캐시 통합 — 프론트 구현 참조 문서

> **상태**: 사전 조사 완료 → 구현 대기 (코드 수정 전)
> **작성일**: 2026-08-02
> **목적**: 새 세션에서 본 문서만 보고 바로 구현할 수 있도록, 사전 조사 결과를 단일 구현 참조 문서로 정리.
> **관련 문서**: `docs/architecture_master_cache_single_source_design.md` (설계서) · `docs/plan_master_cache_single_source.md` (태스크 파일)
> **선행 완료**: 3세션 백엔드 구현 완료 (커밋 `5bce9d5`) — 백엔드 이벤트 계약 확정됨.

---

## 1. 목적

프론트 실시간 시세의 단일 진실 소스를 `sectorStocks`(필터된 부분집합)에서 `masterStocks`(백엔드 `master_stocks_cache`의 프론트 표시 사본)로 통합.

- **P10 SSOT 강화**: 시세가 `sectorStocks`·`buyTargets`(복사)·`positions.cur_price`(복사) 3곳 중복 → `masterStocks` 1곳(표시) + `positions.cur_price`(계산용 유지, W7).
- **P22 데이터 정합성**: 파생 캐시 동기화 로직 7곳(rebindBuyTargetsRealtime 등) 제거 — 참조로 전환하여 동기화 불필요.
- **052690 결함 근본 해결**: 보유종목이 필터 미달이어도 masterStocks에 있으면 누락 없음.
- **페이지별 구독 Push 모델**: 각 페이지가 mount 시 종목 코드를 백엔드에 직접 신청 → 백엔드가 해당 종목만 push.

### 업계 표준 근거 (조사 검증)
프론트 표시용 사본은 업계 표준 — Bloomberg(edge last-value cache), Engineered.at(external hot state quote store), bitbox.cloud("client-side caches should keep only the last known state"). "백엔드 캐시만 있고 프론트 상태 없는 구조"는 존재하지 않음(브라우저가 원격 메모리 직접 접근 불가, 초당 수십~수백 틱 vs 60fps 렌더 분리 필수).

---

## 2. 백엔드 이벤트 계약 (3세션 구현 완료 — 변경 불가)

### 2.1 `master-cache-snapshot` 이벤트
페이지 구독 신청 시 해당 종목들의 현재 마스터 캐시 값 전송.
```jsonc
// payload
{ "_v": 1, "stocks": [
  { "code", "name", "cur_price", "change", "change_rate", "strength",
    "trade_amount", "sector", "avg_amt_5d", "market_type", "nxt_enable",
    "order_ratio", "program_net_buy", "news_boost", "high_5d" }
] }
```
- 전송 시점: (1) `page-active` 수신 시 `subscribe_codes` 신규 구독 종목, (2) `notify_desktop_sector_stocks_refresh` 각 클라이언트 구독 종목.
- freshness 필드 없음 (build_master_cache_snapshot이 freshness 미포함).

### 2.2 `master-cache-delta` 이벤트
실시간 필드 부분 갱신 — 구독 중인 클라이언트에게만 전송.
```jsonc
// 호가: { "code": "...", "fields": { "order_ratio": [bid, ask] } }
// PGM: { "code": "...", "fields": { "program_net_buy": net_buy } }
```
- `notify_orderbook_update`/`notify_program_update`가 본 이벤트로 대체됨 (기존 orderbook-update/program-update 이벤트 제거).

### 2.3 `real-data` 이벤트
Raw FID 그대로 — **구독자에게만 전송** (`ws_manager.broadcast`가 `get_subscribers_for_code(code)`로 라우팅). 프론트 `applyRealData`가 파싱하여 masterStocks in-place 갱신.

### 2.4 `page-active` 메시지 (프론트→백엔드)
```jsonc
{ "type": "page-active", "page": "sell-position", "codes": ["005930", "052690"] }
```
- 백엔드 `ws.py:204-215`: `codes` 배열 수신 → `ws_manager.subscribe_codes(ws, page, codes)` → 신규 구독 종목에 `master-cache-snapshot` 전송.
- `page-inactive`: `{ "type": "page-inactive", "page": "..." }` — 구독 해제.

### 2.5 제거된 백엔드 이벤트 (프론트 핸들러도 제거 대상)
- `sector-stocks-refresh` / `sector-stocks-delta` → `master-cache-snapshot`/`master-cache-delta`로 대체
- `orderbook-update` / `program-update` → `master-cache-delta`로 대체

---

## 3. MasterStock 타입 전체 필드 정의 (15개)

`frontend/src/types/index.ts` 신규 추가. 백엔드 `_MASTER_CACHE_FIELDS`와 1:1 대응.

```ts
export interface MasterStock {
  // ── 식별 (5) ──
  code: string;
  name: string;
  sector?: string;
  market_type?: string;
  nxt_enable?: boolean;
  // ── 실시간 시세 (5) ──
  cur_price: number | null;     // null = 틱 미수신
  change?: number;
  change_rate: number;
  strength?: number;
  trade_amount?: number;
  // ── 5거래일 통계 (2) ──
  avg_amt_5d?: number;          // 백만원→억 단위 변환값 (백엔드)
  high_5d?: number;             // 0 = 원천 부재, >0 = 유효 고가
  // ── 호가·PGM·뉴스 (3) ──
  order_ratio?: [number, number] | null;
  program_net_buy?: number | null;
  news_boost?: number;          // 뉴스 호재 가산점 (0 = 미부여)
}
```

---

## 4. 삭제 대상 전체 목록

### 4.1 타입 (`types/index.ts`)
- `SectorStock` 인터페이스 (84-102행) — MasterStock으로 흡수
- `Position.sectorStock?: SectorStock` 필드 (42행)
- `StockScore` 실시간 필드 7개: `cur_price`, `change`, `change_rate`, `strength`, `trade_amount`, `order_ratio`, `program_net_buy`
  - **유지 필드**(정적 스코어): `code`, `name`, `sector`, `market_type`, `nxt_enable`, `rank`, `guard_pass`, `reject_reason`, `boost_score`, `high_5d`, `news_boost`, `news_boost_title`

### 4.2 상태 (`hotStore.ts`)
- `HotState.sectorStocks: Record<string, SectorStock>` → `masterStocks: Record<string, MasterStock>` 로 교체
- `initialState.sectorStocks: {}` → `masterStocks: {}`

### 4.3 함수 (`hotStore.ts`)
- `applyOrderbookUpdate` (478-496행) — master-cache-delta가 직접 갱신
- `applyProgramUpdate` (507-524행) — 동일
- `rebindBuyTargetsRealtime` (808-824행) — buyTargets에 실시간 필드 없으므로 재결합 불필요
- `applySectorStocksRefresh` (826-837행) → `applyMasterStocksSnapshot`으로 대체
- `applySectorStocksDelta` (843-867행) → `applyMasterStocksDelta`로 대체
- `applySectorStocksSnapshot` (185-189행) → `applyMasterStocksSnapshot` 래퍼로 대체
- `stocksToMap` 헬퍼: `SectorStock` → `MasterStock` 타입만 변경 (로직 유지)

### 4.4 WS 핸들러 (`binding.ts`)
- `sector-stocks-refresh` 핸들러 (102-104행) → `master-cache-snapshot` 핸들러
- `sector-stocks-delta` 핸들러 (107-109행) → `master-cache-delta` 핸들러
- `orderbook-update` 핸들러 (128-130행) — 제거
- `program-update` 핸들러 (132-134행) — 제거
- import: `applyOrderbookUpdate`, `applyProgramUpdate`, `applySectorStocksRefresh`, `applySectorStocksDelta`, `SectorStock` 제거 → `applyMasterStocksSnapshot`, `applyMasterStocksDelta`, `MasterStock` 추가

---

## 5. 소스 파일별 구체적 변경 사항 (16개)

### 5.1 `frontend/src/types/index.ts`
- `MasterStock` 인터페이스 추가 (위 §3)
- `SectorStock` 인터페이스 삭제
- `StockScore`에서 실시간 필드 7개 삭제 (cur_price, change, change_rate, strength, trade_amount, order_ratio, program_net_buy)
- `Position.sectorStock?: SectorStock` 필드 삭제
- `FreshnessMetadata.group` 유니온의 `'sector_stocks'` — **유지** (백엔드 결합, master-cache 이벤트는 freshness 미사용하므로 사실상 미사용되나 타입만 유지 — 범위 최소화)

### 5.2 `frontend/src/stores/hotStore.ts`
- import: `SectorStock` → `MasterStock`
- `HotState`: `sectorStocks` → `masterStocks: Record<string, MasterStock>`
- `initialState`: `sectorStocks: {}` → `masterStocks: {}`
- `stocksToMap(stocks: MasterStock[])`: 타입 변경
- **`applyMasterStocksSnapshot(data: { stocks: MasterStock[] })`** 추가 — `stocksToMap` 후 `hotStore.setState({ masterStocks: {...prev, ...newRecord} })` (기존 보존 + 병합, 재연결 시 빈 배열로 리셋 방지)
- **`applyMasterStocksDelta(data: { code: string; fields: Partial<MasterStock> })`** 추가 — `masterStocks[code]`에 fields 병합 (in-place mutation으로 DataTable 객체 참조 유지, setState 미호출 → rAF 배칭 디스패치)
- **`applyRealData`** 재작성:
  - `state.sectorStocks` → `state.masterStocks`
  - in-place mutation 대상: `masterStocks[code]` (시세 5필드) + `positions[posIdx].cur_price` (계산용) **2곳만**
  - **buyTargets 실시간 필드 분기(424-446행) 제거** — buyTargets에 실시간 필드 없음
  - rAF 배칭(_tickDirty + scheduleTickFlush) 유지 — conflation
- **`applyRealtimeReset`** 재작성:
  - `sectorStocks` null화 → `masterStocks` null화 (cur_price, change, change_rate, trade_amount, strength)
  - `rebindBuyTargetsRealtime` 호출(571-573행) 제거 — buyTargets에 실시간 필드 없음
  - positions null화 유지 (cur_price, change, change_rate)
- **`applyBuyTargetsUpdate`** 재작성 (608-648행):
  - `sectorStocks` 재결합 분기(620-634행) 제거 — incoming `t`를 그대로 사용 (정적 필드만)
  - `prevTitleByCode` 보존 로직 유지 (news_boost_title)
  - same 비교 키에서 `order_ratio`/`program_net_buy` 제거 (이제 StockScore에 없음) — `rank`, `code`, `name`, `guard_pass`, `reject_reason`, `boost_score`, `high_5d`만
- **`applyBuyTargetsDelta`** 재작성 (688-760행):
  - `sectorStocks` 재결합 분기(708-754행) 제거 — added/changed를 incoming 그대로 사용
  - `prev.news_boost`/`prev.news_boost_title` 보존 로직 유지
- **`applyNewsHit`** (661-682행):
  - 기존 buyTargets 갱신 유지 (news_boost, news_boost_title, boost_score — 📰 표시·tooltip용)
  - **추가**: `masterStocks[code].news_boost`도 갱신 (백엔드 master_stocks_cache와 동기화 — news_boost_title은 MasterStock에 없으므로 masterStocks에는 news_boost만)
- **`applyInitialSnapshotHot`** (891-928행):
  - `data.sector_stocks as SectorStock[]` → `data.master_stocks as MasterStock[]` (백엔드 initial-snapshot의 sector_stocks 키 — 백엔드가 아직 키명을 안 바꿨으므로 그대로 읽되 타입만 MasterStock. 단, initial-snapshot은 빈 배열이므로 실질 영향 없음)
  - `prevSectorStocks` → `prevMasterStocks`, `newSectorStocks` → `newMasterStocks`
  - `sectorStocks: newSectorStocks` → `masterStocks: newMasterStocks`

> **주의**: 백엔드 initial-snapshot의 키가 `sector_stocks`인지 `master_stocks`인지 확인 필요. 3세션에서 initial-snapshot의 sector_stocks는 빈 배열 유지(`build_initial_snapshot`의 `sector_stocks: []`). 키명이 안 바뀌었으면 `data.sector_stocks` 그대로 읽고 타입만 `MasterStock[]` 캐스팅. 구현 시 `engine_initial_data.py:65` 확인.

### 5.3 `frontend/src/api/ws.ts`
- `notifyPageActive(page: string, codes: string[])`로 확장 — payload에 `codes` 추가
- `_currentPageCodes: string[] = []` 추적 변수 추가
- `notifyPageActive`: `_currentPage = page; _currentPageCodes = codes;` 설정 후 `{ type: 'page-active', page, codes }` 전송 (wsClient + wsSettingsClient 양쪽)
- `notifyPageInactive(page)`: `_currentPageCodes = []` 초기화 (해당 page일 때)
- `getCurrentPageCodes(): string[]` getter 추가 (재연결용)
- **재연결**: binding.ts의 `setConnectionCallbacks`에서 `getCurrentPage()` + `getCurrentPageCodes()`로 `page-active` 재전송

### 5.4 `frontend/src/binding.ts`
- import 정리 (§4.4)
- `sector-stocks-refresh` 핸들러 → `master-cache-snapshot` 핸들러: `applyMasterStocksSnapshot(data as { stocks: MasterStock[] })`
- `sector-stocks-delta` 핸들러 → `master-cache-delta` 핸들러: `applyMasterStocksDelta(data as { code: string; fields: Partial<MasterStock> })`
- `orderbook-update`/`program-update` 핸들러 제거 (128-134행)
- `news-hit` 핸들러 유지 (applyNewsHit — 내부에서 masterStocks도 갱신)
- 재연결 콜백(75-81, 137-144행): `pricesClient.send(JSON.stringify({ type: 'page-active', page, codes: getCurrentPageCodes() }))` — codes 포함. `getCurrentPageCodes` import 추가.

### 5.5 `frontend/src/pages/sell-position.ts`
- import: `notifyPageActive` 시그니처 변경 반영 (이미 import 중)
- **render**: `state.sectorStocks[normalizeStockCode(p.stk_cd)]` → `state.masterStocks[...]` (34, 49행 — 종목명 market_type/nxt_enable, 현재가 cur_price/change_rate)
- `_prevSectorStocks: HotState['sectorStocks']` → `_prevMasterStocks: HotState['masterStocks']` (151행)
- store 구독 핸들러에서 `_prevSectorStocks` → `_prevMasterStocks` 참조 교체
- **mount**: positions 로드 후 `notifyPageActive('sell-position', positionCodes)` — positionCodes = `positions.map(p => normalizeStockCode(p.stk_cd))`
- **positions 변경 시 재구독**: store 구독 핸들러에서 positions 참조 변경 감지 시 `notifyPageActive('sell-position', newPositionCodes)` 재전송 (신규 보유종목 구독)
- **unmount**: `notifyPageInactive('sell-position')` (기존 유지)
- 주석(43-45행) sectorStocks → masterStocks 로 갱신

### 5.6 `frontend/src/pages/buy-target.ts`
- **`computeBadgeContext`** (139-140행): `topTarget.cur_price` → `hotStore.getState().masterStocks[normalizeStockCode(topTarget.code)]?.cur_price` (1위 종목 매수 가능 수량 계산)
- **mount**: buyTargets 로드 후 `notifyPageActive('buy-target', buyTargetCodes)` — buyTargetCodes = `buyTargets.map(t => normalizeStockCode(t.code))`
- **buyTargets 변경 시 재구독**: store 구독 핸들러에서 buyTargets 참조 변경 시 재전송
- **unmount**: `notifyPageInactive('buy-target')`
- `_rsBuyTargets` 등 참조 상태 유지

### 5.7 `frontend/src/pages/buy-target-columns.ts`
- 모든 실시간 필드 참조를 `masterStocks[t.code]`로 전환:
  - `t.cur_price` → `hotStore.getState().masterStocks[normalizeStockCode(t.code)]?.cur_price` (38-39, 129행 — 현재가, 5일고가 비교)
  - `t.change_rate` → `masterStocks[...]?.change_rate` (52행)
  - `t.change` → `masterStocks[...]?.change` (51행)
  - `t.order_ratio` → `masterStocks[...]?.order_ratio` (56-57행)
  - `t.program_net_buy` → `masterStocks[...]?.program_net_buy` (87-96행)
- **유지 필드**(StockScore에 남음): `t.code`, `t.name`, `t.market_type`, `t.nxt_enable`, `t.high_5d`, `t.news_boost`, `t.news_boost_title`, `t.boost_score`, `t.guard_pass`, `t.reject_reason`, `t.rank`
- render 함수 내에서 `hotStore.getState()` 호출 (sell-position.ts 패턴과 동일)
- `normalizeStockCode` import 추가

### 5.8 `frontend/src/pages/sector-stock.ts`
- import: `applySectorStocksSnapshot` → `applyMasterStocksSnapshot`, `SectorStock` → `MasterStock`
- `rowCache: Map<string, { stock: SectorStock; row: DataRowItem }>` → `MasterStock`
- **`buildRows`** (63-82행): `state.sectorStocks` → `state.masterStocks` (66, 67, 73행)
- **`updateUI`** (91-138행): `state.sectorStocks` → `state.masterStocks` (94행)
- **mount/refresh**: `applySectorStocksSnapshot(response.data, ...)` → `applyMasterStocksSnapshot({ stocks: response.data })` (466행) — HTTP getSectorStocks 응답으로 필터 통과 종목 masterStocks 채움
- **mount 시 구독 신청**: refresh 완료 후 `notifyPageActive('sector-stock', filteredCodes)` — filteredCodes = `response.data.map(s => normalizeStockCode(s.code))` (또는 `Object.keys(masterStocks)`)
- **unmount**: `notifyPageInactive('sector-stock')`
- `currentMatchedCodes`/`currentMatchedSectors` 로직 유지

### 5.9 `frontend/src/pages/sector-stock-rows.ts`
- import: `SectorStock` → `MasterStock`
- `DataRowItem.stock: SectorStock` → `MasterStock`
- `filterSectorsByName(stocks: Record<string, SectorStock>, ...)` → `Record<string, MasterStock>`
- `computeRows(stockMap: Record<string, SectorStock>, ...)` → `Record<string, MasterStock>`
- `rowCache: Map<string, { stock: SectorStock; ... }>` → `MasterStock`
- 컬럼 render의 `item.stock.cur_price` 등은 그대로 (MasterStock에 동일 필드 존재)

### 5.10 `frontend/src/pages/profit-columns.ts`
- `state.sectorStocks[normalizeStockCode(...)]` → `state.masterStocks[...]` (17, 41행 — market_type/nxt_enable)

### 5.11 `frontend/src/pages/profit-detail-mount.ts`
- `prevSectorStocksRef = initState.sectorStocks` → `prevMasterStocksRef = initState.masterStocks` (268행)
- `sectorStocksChanged = curr.sectorStocks !== prevSectorStocksRef` → `masterStocksChanged = curr.masterStocks !== prevMasterStocksRef` (274행)
- `prevSectorStocksRef = curr.sectorStocks` → `prevMasterStocksRef = curr.masterStocks` (290행)
- `state.dirtySectorStocks` → `state.dirtyMasterStocks` (257, 289-291행 — profit-detail.ts의 플래그와 짝)

### 5.12 `frontend/src/pages/profit-detail.ts`
- `dirtySectorStocks: boolean` → `dirtyMasterStocks: boolean` (88행 타입, 123행 초기값, 209행 리셋)
- `state.dirtySectorStocks` → `state.dirtyMasterStocks` (profit-detail-mount.ts와 짝)

### 5.13 `frontend/src/pages/stock-classification-center.ts`
- `hotState.sectorStocks[normalizeStockCode(row.code)]` → `hotState.masterStocks[...]` (146행 — market_type/nxt_enable)

### 5.14 `frontend/src/pages/stock-classification-master.ts`
- `hotState.sectorStocks[normalizeStockCode(row.code)]` → `hotState.masterStocks[...]` (203행 — market_type/nxt_enable)

### 5.15 `frontend/src/api/client.ts`
- import: `SectorStock` → `MasterStock`
- `getSectorStocks: (pageContext?) => request<FreshnessResponse<SectorStock[]>>(...)` → `MasterStock[]` (150-151행)
- 엔드포인트 경로 `/api/market/sector-stocks` 유지 (백엔드 변경 없음)

### 5.16 `frontend/src/utils/stock-search.ts`
- 제네릭 `{ code: string; name?: string }` 제약 — 타입 영향 없음
- 주석(3-4행) `SectorStock` 언급 → `MasterStock`으로 갱신 (선택, 정확성)

### 변경 불필요 파일 (조사 확인)
- `profit-overview-sector-pnl.ts` — `SectorStockPnl`/`buildSectorStockPnl`은 profit-math의 별도 타입(state.sectorStocks 무관)
- `profit-math.ts` — `SectorStockPnl` 타입, `buildSectorStockPnl` 함수 (state 무관). 주석(234-235행) sectorStocks 언급은 정확성 갱신 권장(선택)
- `profit-overview-mount.ts` — `renderSectorStockPnl` 함수명만 (state 무관)
- `stock-classification-staging.ts`/`stock-classification.ts` — `cachedSectorStocksRef`는 `stockClassificationStore.allStocks` 캐시 (hotStore.sectorStocks 무관, 이름만 유사)
- `stock-detail.ts` — `bars[idx].trade_amount`는 5일봉 객체 (SectorStock 무관)

---

## 6. 테스트 파일 수정 항목 (3개)

### 6.1 `frontend/tests/stores/hotStore.test.ts` (130매치 — 대폭 갱신)
- `sectorStocks` → `masterStocks` 전체 치환 (상태명)
- `SectorStock` → `MasterStock` 타입 치환
- `applySectorStocksRefresh`/`applySectorStocksDelta`/`applySectorStocksSnapshot` 테스트 → `applyMasterStocksSnapshot`/`applyMasterStocksDelta` 테스트로 재작성
- `applyOrderbookUpdate`/`applyProgramUpdate` 테스트 — **삭제** (함수 제거)
- `rebindBuyTargetsRealtime` 테스트 — **삭제**
- `applyRealData` 테스트 — buyTargets 실시간 필드 갱신 검증 제거, masterStocks + positions 2곳 갱신 검증으로 변경
- `applyRealtimeReset` 테스트 — masterStocks null화 검증, rebind 호출 제거 검증
- `applyBuyTargetsUpdate`/`applyBuyTargetsDelta` 테스트 — sectorStocks 재결합 검증 제거
- `applyNewsHit` 테스트 — masterStocks news_boost 갱신 추가 검증

### 6.2 `frontend/tests/pages/profit-shared.test.ts` (1매치 — 12행)
- sectorStocks 참조 → masterStocks (문맥 확인 후 갱신)

### 6.3 `frontend/tests/api/client.test.ts` (1매치 — 47행)
- `SectorStock` → `MasterStock` (getSectorStocks 반환 타입)

---

## 7. WebSocket 변경 상세

### 7.1 notifyPageActive 확장 (`ws.ts`)
```ts
let _currentPage: string | null = null
let _currentPageCodes: string[] = []  // 신규

export function notifyPageActive(page: string, codes: string[] = []): void {
  _currentPage = page
  _currentPageCodes = codes
  const payload = JSON.stringify({ type: 'page-active', page, codes })
  wsClient.send(payload)
  wsSettingsClient.send(payload)
}

export function notifyPageInactive(page: string): void {
  if (_currentPage === page) { _currentPage = null; _currentPageCodes = [] }
  wsClient.send(JSON.stringify({ type: 'page-inactive', page }))
  wsSettingsClient.send(JSON.stringify({ type: 'page-inactive', page }))
}

export function getCurrentPageCodes(): string[] { return _currentPageCodes }  // 신규
```

### 7.2 재연결 시 codes 재전송 (`binding.ts`)
```ts
pricesClient.setConnectionCallbacks(
  () => {
    const page = getCurrentPage()
    if (page) pricesClient.send(JSON.stringify({ type: 'page-active', page, codes: getCurrentPageCodes() }))
  },
  () => {},
)
```
- settingsClient 콜백(137-144행)도 동일 — 단, settings 채널은 codes 전송 불필요할 수 있으나 백엔드 ws.py가 동일 처리하므로 일관성 위해 양채널 전송 유지(기존 패턴).

### 7.3 이벤트 핸들러 교체 (`binding.ts`)
```ts
pricesClient.onEvent('master-cache-snapshot', (data) => {
  applyMasterStocksSnapshot(data as { stocks: MasterStock[] })
})
pricesClient.onEvent('master-cache-delta', (data) => {
  applyMasterStocksDelta(data as { code: string; fields: Partial<MasterStock> })
})
// orderbook-update, program-update 핸들러 제거
```

---

## 8. 설계 결정 근거

### 8.1 news_boost 양쪽 갱신 (applyNewsHit)
- **buyTargets** 갱신: `news_boost`, `news_boost_title`, `boost_score` — 📰 표시 + tooltip(title)용. `news_boost_title`은 MasterStock에 없음(백엔드 `_MASTER_CACHE_FIELDS`에 news_boost만).
- **masterStocks** 갱신: `news_boost`만 — 백엔드 `master_stocks_cache[code]["news_boost"]`와 동기화.
- 사유: news-hit 이벤트는 백엔드가 master_stocks_cache 필드 갱신 후 전송하지만, master-cache-delta로 news_boost가 push되지 않으므로 프론트가 news-hit에서 masterStocks도 갱신해야 표시 일관성 유지. tooltip title은 buyTargets에만 존재하므로 buyTargets 갱신 필수.

### 8.2 positions.cur_price 유지 (W7 금지)
- `positions.cur_price`는 **계산용** 유지 — `computePositionValuation`(손익·평가금액), `computeHoldingsSummary`(요약) 입력값.
- 화면 표시용 현재가만 `masterStocks[code].cur_price` 참조 (기존 sectorStocks → masterStocks 교체).
- 역할 분리 유지: 표시 소스 = masterStocks, 계산 소스 = positions.cur_price.
- 금지사항: `positions.cur_price` 필드 자체 제거 금지 (W7).

### 8.3 freshness 구조 유지
- `FreshnessMetadata.group` 유니온의 `'sector_stocks'` 키 유지.
- master-cache-snapshot/delta 이벤트는 freshness 미포함(백엔드 구현). `applyMasterStocksSnapshot/Delta`는 freshness 처리 안 함.
- `freshness.sector_stocks`는 사실상 미갱신(revision 0 유지) — 범위 최소화 위해 타입만 유지. 백엔드 `get_freshness("sector_stocks")` 결합 유지.
- P16(dead code) 측면: 미사용 필드이나 백엔드 결합 분리 위해 별도 태스크에서 정리 권장(본 태스크 범위 외).

### 8.4 sector-stock 필터링 (설계서 282·319행)
- HTTP `getSectorStocks`(`/api/market/sector-stocks`)로 필터 통과 종목 코드 + 정적 필드(name, sector, avg_amt_5d, market_type, nxt_enable) 확보.
- `applyMasterStocksSnapshot({ stocks: response.data })`로 masterStocks 채움.
- `notifyPageActive('sector-stock', filteredCodes)`로 구독 신청 → 백엔드가 master-cache-snapshot으로 실시간 필드 push.
- render는 masterStocks 사용 (필터된 부분집합이 masterStocks에 채워져 있음).
- "5거래일 평균 거래대금 필터링은 백엔드에서 수행" — HTTP 엔드포인트가 필터된 결과 반환하므로 프론트는 재필터 불필요.

### 8.5 2단계+3단계 통합 진행 (사용자 결정)
- 태스크 파일 2단계(sectorStocks/SectorStock/StockScore 실시간 필드 제거)와 3단계(render 전환)는 typecheck 게이트 때문에 강결합 — 분할 불가능.
- 4세션에서 통합 수행(상태 제거 + binding + 구독 + render 전환). 5세션은 잔여 dead code 정리로 축소(실제로는 본 통합에서 대부분 완료).

### 8.6 상태명 `masterStocks` (사용자 결정 — 태스크 결정 A에서 변경)
- 기존 `sectorStocks`↔`SectorStock` 패턴 계승: `masterStocks: Record<string, MasterStock>`.
- "마스터 종목" 의미 명확, 캐시 접미사 없음(기존 sectorStocks와 동일 기준).
- WS 이벤트명 `master-cache-*`와는 독립(백엔드 3세션 확정, 프론트 상태명과 무관).

---

## 9. 검증 게이트

```bash
# 프론트엔드 (프로젝트 루트에서)
cd frontend && npm run typecheck   # tsc --noEmit — 통과 필수
cd frontend && npm run test        # vitest, 116 tests — 갱신 후 통과 필수
cd frontend && npm run build       # tsc -b && vite build — 통과 필수

# 백엔드 (변경 없음 — 회귀 확인용)
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python -W error::RuntimeWarning main.py
```

### 검증 자동화 루프 (AGENTS.md 0-1-2)
typecheck + test + build 중 실패 시 통과까지 자동 반복. 종료 조건: 3개 전부 pass.

### 완료 확인 항목 (grep 검증)
- `grep -r "sectorStocks" frontend/src` → 0건 (주석 제외)
- `grep -r "SectorStock" frontend/src` → 0건 (stock-classification의 cachedSectorStocksRef는 별도 store — 제외)
- `grep -r "rebindBuyTargetsRealtime" frontend/src` → 0건
- `grep -r "applyOrderbookUpdate\|applyProgramUpdate" frontend/src` → 0건
- `grep -r "applySectorStocksRefresh\|applySectorStocksDelta" frontend/src` → 0건
- `grep -r "t\.cur_price\|t\.change_rate\|t\.order_ratio\|t\.program_net_buy" frontend/src/pages/buy-target-columns.ts` → 0건 (masterStocks 참조로 전환)
- `grep -r "notifyPageActive" frontend/src` → codes 포함 호출만

---

## 10. 금지사항 (태스크 파일 준수)

- `positions.cur_price` 필드 자체 제거 금지 (W7 — 계산용 유지)
- 매수후보 정적 스코어(rank, guard_pass, reject_reason, boost_score)를 masterStocks로 이동 금지
- news_boost를 masterStocks와 buyTargets 양쪽에 "독립 계산"으로 유지 금지 — news-hit 단일 이벤트로 갱신 (P10)
- DB 스키마 변경 금지 (메모리 상태만)
- 거래 로직(execute_buy/execute_sell)·리스크 매니저·서킷브레이커 수정 금지
- 백엔드 코드 수정 금지 (3세션 완료 — 본 태스크는 프론트만)

---

## 11. 사전 롤백

- 4세션 구현 커밋 해시는 구현 후 기재.
- 롤백: `git revert <해시>`
- 즉시 롤백 트리거: 보유종목 가격 "-" 증가, 매수후보 랭킹 순서 변화, 틱 수신 시 화면 끊김, 07:58 리셋 후 잔류, 자동매매 동작 변화, 뉴스 가산점 미표시/잔류.
