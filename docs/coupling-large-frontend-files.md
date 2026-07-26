# COUPLING-S9 (C-09) — 대형 프론트엔드 파일의 변경 책임 집중 조사

> **세션**: COUPLING-S9  
> **대상 원칙**: P16 살아있는 경로, P21 사용자 투명성, P23 공통 UI 자산, P24 단순성, P25 격리된 실패  
> **조사 일자**: 2026-07-26  
> **조사 방법**: 대상 파일 전수 정독 + import/export grep + git log 변경 이력 카운트 + 테스트 커버리지 확인

---

## 1. 조사 대상 파일 개요

| 파일 | 줄 수 | git 변경 수(2025-01-01~) | 공개 함수/타입 수 |
|------|-------|--------------------------|-------------------|
| `frontend/src/layout/header.ts` | 615 | 39 | 1 (`createHeader`) |
| `frontend/src/stores/hotStore.ts` | 751 | 31 | 18 (함수 16 + 인터페이스 1 + 상수 1) |
| `frontend/src/components/virtual-scroller.ts` | 555 | 12 | 9 (함수 6 + 인터페이스 3) |
| `frontend/src/pages/profit-shared.ts` | 537 | 30 | 14 (함수 8 + 인터페이스 6) |
| `frontend/src/pages/buy-target.ts` | 477 | 52 | 1 (`export default { mount, unmount }`) |
| `frontend/src/pages/sector-stock.ts` | 482 | 53 | 0 (Custom Element 등록만) |
| `frontend/src/components/common/data-table-fixed.ts` | 469 | 5 | 1 (`createFixedMode`) |
| **합계** | **3,886** | — | — |

---

## 2. 파일별 상세 분석

### 2.1 `header.ts` (615줄, 39회 변경)

#### 책임 묶음

| # | 책임 | 줄 범위 | 변경 이유 |
|---|------|---------|-----------|
| A | 스타일 상수 정의 (PHASE_STYLE, STATUS_THEME, CHIP_STYLE) | 12–46 | 장 페이즈명 추가/수정, 색상 체계 변경 |
| B | 인라인 StatusChip 헬퍼 (createChipEl, applyStatusChip) | 48–68 | 칩 스타일 패턴 변경 |
| C | 장 페이즈 카운트다운 포맷 + 칩 렌더링 | 70–119 | 카운트다운 기능 추가, 페이즈명 통일 |
| D | 백그라운드 데이터 갱신 칩 렌더링 (avgAmtProgress) | 126–215 | 다운로드 상태 종류 추가, 프로그레스 바/ETA 표시 |
| E | 업종지수 칩 렌더링 (applyIndexChip) | 217–239 | 지수 표시 포맷 변경 |
| F | spin 키프레임 삽입 | 243–253 | CSS 애니메이션 추가 |
| G | createHeader 팩토리 — DOM 구축 + Store 구독 + 칩 갱신 | 255–615 | **모든 칩 추가/수정 시 이 영역 변경** — 신규 칩 추가, 이벤트 리스너, onStateChange 분기 |

#### Fan-in / Fan-out

- **Fan-in**: 1 — `layout/shell.ts`만 `createHeader`를 호출
- **Fan-out**: 4 — `uiStore`, `uiStore` clear 함수 6종, `types` (IndexData), `broker-badge` (BROKER_LABELS), `ui-styles` (COLOR)

#### 상태·렌더링·이벤트·스타일 경계

| 영역 | 현황 |
|------|------|
| **상태** | `uiStore.subscribe(onStateChange)` 1곳 — UIState 전체 구독 |
| **렌더링** | `onStateChange` 내 15개 try-catch 블록 (칩별 P25 격리) — 각 칩이 독립적 렌더링 단위 |
| **이벤트** | 6개 칩의 click 이벤트 리스너 (circuitBreaker, orderTimeBlocked, riskBlock, testCashFailed, positionBuildFailed, degradedMode) — 모두 clear 함수 호출 |
| **스타일** | 인라인 스타일 상수 3종 (CHIP_STYLE, PHASE_STYLE, STATUS_THEME) + COLOR 참조 |

#### 변경 집중 원인

**신규 칩 추가 시 3곳 동시 수정 필요**: (1) 스타일 상수/헬퍼, (2) createHeader 내 DOM 생성 + 이벤트 리스너, (3) onStateChange 내 렌더링 분기. 이는 헤더의 본질적 특성 — 모든 상태 표시가 단일 컨테이너에 배열되므로 한 함수가 모든 칩의 생명주기를 관리. 각 칩은 서로 독립적이지만 분리 시 공유 컨텍스트(header 컨테이너, Store 구독, destroy)를 매개변수로 전달해야 하는 오버헤드 발생.

#### 분리 가능성 판정: **⊘ 유지**

- 각 칩 렌더링은 이미 try-catch로 P25 격리됨
- 칩 추가 시 3곳 수정은 헤더의 단일 책임(상태 표시) 내에서 자연스러운 변경
- 칩을 개별 파일로 분리하면 공유 컨텍스트(header el, Store 구독, destroy) 전달 오버헤드가 분리 이득을 초과
- 615줄은 상한(500줄)을 초과하나, 각 칩 렌더링이 동일한 패턴의 반복이므로 복잡도는 낮음

---

### 2.2 `hotStore.ts` (751줄, 31회 변경)

#### 책임 묶음

| # | 책임 | 줄 범위 | 변경 이유 |
|---|------|---------|-----------|
| A | 종목코드 정규화 + 배열→Record 변환 헬퍼 | 14–32 | 정규화 규칙 변경 (드물음) |
| B | HotState 인터페이스 + 초기 상태 + store 생성 | 34–60 | 상태 필드 추가/제거 |
| C | 인덱스 캐시 (buyTarget/position) — 모듈 스코프 Map | 62–91 | 캐시 구조 변경 (드물음) |
| D | rAF 배칭 스케줄러 (tick/orderbook/program dirty Set) | 93–131 | 배칭 로직 튜닝 (드물음) |
| E | account-update 처리 (delta + full snapshot) | 134–271 | 계좌 갱신 페이로드 형식 변경, 동등성 비교 로직 |
| F | real-data 틱 처리 (키움 Raw FID 파싱 + in-place mutation) | 273–425 | **가장 빈번한 변경** — FID 필드 추가, 파싱 로직, in-place mutation 대상 변경 |
| G | orderbook/program-update 처리 | 427–482 | 호가잔량/프로그램 갱신 로직 |
| H | realtime-reset (실시간 필드 일괄 초기화) | 484–538 | 초기화 필드 추가 |
| I | buy-targets-update (내용 비교 + SSOT 재결합) | 540–586 | 비교 키 변경, SSOT 재결합 로직 |
| J | sector-scores 갱신 (delta 머지) | 588–622 | delta 머지 로직 |
| K | sector-stocks-refresh/delta (SSOT + buyTargets 재결합) | 624–687 | 재결합 로직, delta 처리 |
| L | order-filled + history 갱신 (단순 setState) | 689–713 | 히스토리 구조 변경 |
| M | initial-snapshot (전체 초기화) | 715–751 | 초기화 필드 추가, 보존 로직 |

#### Fan-in / Fan-out

- **Fan-in**: 16 파일 — `binding.ts`, `stores/index.ts`, 10개 페이지, 2개 컬럼 파일, 1개 공통 모듈
- **Fan-out**: 2 — `store.ts` (createStore), `types` (타입 정의)

#### 상태·렌더링·이벤트·스타일 경계

| 영역 | 현황 |
|------|------|
| **상태** | `hotStore` 인스턴스 + 모듈 스코프 캐시 2종 (Map) + dirty Set 3종 |
| **렌더링** | 없음 (순수 상태 관리) |
| **이벤트** | `window.dispatchEvent` 3종 (real-data-tick, orderbook-tick, program-tick) — rAF 배칭 |
| **스타일** | 없음 |

#### 변경 집중 원인

**WS 이벤트 핸들러가 모두 한 파일에 집중**. 16개 apply* 함수가 각각 하나의 WS 이벤트를 담당하며, 모두 `hotStore.setState()`를 통해 동일한 store를 갱신. 이는 Store의 단일 책임(실시간 데이터 상태 관리)에 해당. apply* 함수 간에는 `rebindBuyTargetsRealtime` 등 공통 헬퍼를 통한 간접 결합 존재 (P10 SSOT + P22 데이터 정합성).

#### 분리 가능성 판정: **⊘ 유지**

- 16개 apply* 함수는 모두 동일한 `hotStore` 인스턴스와 모듈 스코프 캐시를 공유
- 분리 시 순환 import 위험 (rebindBuyTargetsRealtime이 sectorStocks와 buyTargets를 동시에 참조)
- 751줄은 상한(500줄)을 초과하나, 각 apply* 함수는 독립적인 이벤트 핸들러로 순환 복잡도 1~3 수준
- 파일 분할 시 공유 상태(store, 캐시, dirty Set)의 접근 경로가 복잡해져 P24 단순성 위반
- **이미 COUPLING-S8에서 38개 상태 필드별 producer/consumer 매트릭스 작성 완료 — 구조적 문제 없음 확인**

---

### 2.3 `virtual-scroller.ts` (555줄, 12회 변경)

#### 책임 묶음

| # | 책임 | 줄 범위 | 변경 이유 |
|---|------|---------|-----------|
| A | 인터페이스 정의 (3종) | 13–41 | API 확장 (드물음) |
| B | 순수 함수 — 고정 높이 감지/오프셋/총높이 | 43–73 | 초기 설계 이후 변경 없음 |
| C | 순수 함수 — 가변 높이 오프셋 계산 | 75–110 | 초기 설계 이후 변경 없음 |
| D | 순수 함수 — visible range 이진 탐색 | 112–154 | 초기 설계 이후 변경 없음 |
| E | createVirtualScroller 팩토리 — DOM 풀 + 렌더링 + 스크롤 | 156–555 | rAF 초기화, drift 검증, P25 격리 추가 |

#### Fan-in / Fan-out

- **Fan-in**: 2 — `data-table-virtual.ts`, `data-table-fixed.ts` (CellWithPrevContent 타입만)
- **Fan-out**: 0 (외부 의존성 없음 — 순수 DOM/TypeScript)

#### 상태·렌더링·이벤트·스타일 경계

| 영역 | 현황 |
|------|------|
| **상태** | 클로저 변수 (items, offsets, totalHeight, fixedMode, activeRows Map, pool 배열) |
| **렌더링** | `renderRange` 함수 — DOM 풀 기반 행 렌더링/재사용 |
| **이벤트** | `container.addEventListener('scroll', onScroll)`, ResizeObserver |
| **스타일** | 인라인 스타일 (position, transform, height, willChange) |

#### 변경 집중 원인

변경 빈도가 낮음(12회/1.5년). 대부분 초기 설계 이후 안정화. 순수 함수(B~D)와 팩토리(E)가 명확히 분리되어 있어 순수 함수는 PBT 테스트 가능. 555줄 중 순수 함수가 100줄, 팩토리가 400줄이지만 팩토리 내부는 풀 관리 + 렌더링 + 스크롤 처리 + API 반환으로 자연스러운 단일 흐름.

#### 분리 가능성 판정: **⊘ 유지**

- 순수 함수(B~D)는 이미 별도 export로 분리되어 테스트 가능
- 팩토리(E)의 클로저 변수들이 서로 밀접하게 연관되어 분할 시 상태 공유 복잡
- 변경 빈도 낮음 — 분할의 실익 없음
- 555줄은 상한(500줄)을 초과하나, 순수 함수/팩토리 경계가 명확하고 복잡도는 낮음

---

### 2.4 `profit-shared.ts` (537줄, 30회 변경)

#### 책임 묶음

| # | 책임 | 줄 범위 | 변경 이유 |
|---|------|---------|-----------|
| A | 타입 정의 (4종 인터페이스) | 11–41 | 데이터 구조 변경 |
| B | 요약 카드 DOM 생성 (buildSummaryCard, createSummaryCards) | 43–148 | 카드 추가/수정, P25 격리 |
| C | 날짜 추출 헬퍼 (getRecent5TradingDays) | 150–158 | 날짜 범위 로직 변경 |
| D | 요약 카드 갱신 (updateSummaryCards) | 160–230 | 집계 로직 변경, SSOT 통일, 라벨 변경 |
| E | 업종별 손익 집계 (buildSectorDonutRows, buildSectorStockPnl) | 232–322 | 집계 로직, 색상 할당, P10 SSOT |
| F | 거래내역 필터 + 손익 집계 (filterTradeRows, aggregatePnl) | 324–362 | 필터 조건 변경 |
| G | 일별 요약 집계 (buildMonthlyDrilldown, buildChartFromDailySummary) | 364–399 | 차트 데이터 변환 로직 |
| H | 보유 종목 요약 (computeHoldingsSummary) | 401–432 | 평가손익 계산 공식 변경 |
| I | 계좌 현황 렌더 (renderAccountVals + 헬퍼 2종) | 434–537 | 계좌 행 추가, 수수료/세금 표시 |

#### Fan-in / Fan-out

- **Fan-in**: 8 — `profit-overview.ts`, `profit-overview-mount.ts`, `profit-overview-sector-pnl.ts`, `profit-detail.ts`, `profit-detail-mount.ts`, `profit-detail-display.ts`, `profit-columns.ts`, `sell-position.ts`
- **Fan-out**: 5 — `ui-styles` (COLOR, fmtWon, pnlColor, computeWeightedRate 등), `hotStore` (normalizeStockCode), `date` (getLocalToday), `types`, `canvas-sector-donut` (SectorDonutRow, assignSectorColors)

#### 상태·렌더링·이벤트·스타일 경계

| 영역 | 현황 |
|------|------|
| **상태** | 없음 (순수 함수 + 매개변수 기반) |
| **렌더링** | DOM 생성 (createSummaryCards) + DOM 갱신 (updateSummaryCards, renderAccountVals) |
| **이벤트** | 카드 클릭 콜백 (SummaryCardCallbacks — 외부에서 주입) |
| **스타일** | SUMMARY_CARD_STYLE 상수 + COLOR/FONT_SIZE/FONT_WEIGHT 참조 |

#### 변경 집중 원인

**수익현황/수익상세 페이지 공통 로직의 유일한 소스**. 8개 파일이 이 모듈의 함수를 import. 변경 이유가 (1) 집계 로직 변경, (2) 라벨/용어 통일, (3) SSOT 위반 해결로 다양하지만, 모두 "수익 계산/표시"라는 단일 도메인에 속함.

#### 분리 가능성 판정: **⊘ 유지**

- 14개 export 함수가 모두 "수익 도메인"에 속하는 응집력 있는 모듈
- 분할 시 8개 consumer의 import 경로가 분산되어 오히려 결합도 증가
- 537줄은 상한(500줄)을 초과하나, 순수 함수와 DOM 렌더링이 명확히 구분됨
- 이미 F-05 세션에서 폴백/중복/비동기 안전 7건 해결 완료

---

### 2.5 `buy-target.ts` (477줄, 52회 변경)

#### 책임 묶음

| # | 책임 | 줄 범위 | 변경 이유 |
|---|------|---------|-----------|
| A | 모듈 변수 (렌더링 참조 상태 10종 + 핸들 7종) | 20–46 | 상태 필드 추가/제거 |
| B | 배지 컨텍스트 계산 (computeBadgeContext) | 48–105 | 배지 계산 로직, 매수 한도 조건 변경 |
| C | 통합 매수상태 배지 판정 (computeCombinedStatus) | 107–161 | 차단 상태 추가, 매수 가능 수량 계산 |
| D | 일일/보유 배지 갱신 (updateDailyBadge, updateHoldingBadge) | 163–201 | 배지 표시 로직 |
| E | DOM 빌더 (buildHeader, buildSearchRow, buildTableArea) | 203–277 | UI 레이아웃 변경 |
| F | 렌더링 상태 관리 + rAF 배칭 (scheduleRender, renderFrame) | 279–383 | 렌더링 최적화, 참조 비교 로직 |
| G | 틱 리스너 (real-data/orderbook/program) | 385–422 | 이벤트 종류 추가 |
| H | mount / unmount | 424–477 | 생명주기 관리 |

#### Fan-in / Fan-out

- **Fan-in**: 1 — `main.ts`에서 lazy import (`import('./pages/buy-target').then(m => m.default)`)
- **Fan-out**: 9 — `data-table`, `hotStore`, `uiStore`, `ws`, `card-header`, `search-input`, `settings`, `ui-styles`, `badge`, `order-block-status`, `stock-search`, `buy-target-columns`, `types`

#### 상태·렌더링·이벤트·스타일 경계

| 영역 | 현황 |
|------|------|
| **상태** | 모듈 스코프 변수 17종 (렌더링 참조 10 + 핸들 7) — mount/unmount 시 초기화/reset |
| **렌더링** | `renderTableRows` (DataTable updateRows) + `updateBadges` (배지 textContent) |
| **이벤트** | Store 구독 2종 (hotStore, uiStore) + window 이벤트 3종 (tick류) |
| **스타일** | 인라인 스타일 (scrollContainer, searchRow, emptyEl) + COLOR 참조 |

#### 변경 집중 원인

**가장 빈번한 변경 (52회)**. 매수 로직/배지/설정/컬럼/차단 상태 변경이 모두 이 파일에 집중. 배지 계산 로직(B~D)이 약 150줄을 차지하며, 매수 설정 변경 시마다 수정됨. 그러나 배지 계산은 `hotStore`/`uiStore`/`globalSettingsManager` 상태를 종합적으로 조회하므로 페이지 생명주기와 분리하기 어려움.

#### 분리 가능성 판정: **⊘ 유지**

- 배지 계산 로직(B~D, 약 150줄) 분리 가능성 검토:
  - `computeBadgeContext`가 `hotStore.getState()`, `uiStore.getState()`, `globalSettingsManager.getSettings()`를 직접 호출 → Store 의존성을 매개변수로 전달하려면 시그니처가 3개 상태 객체 + 파생 계산으로 과도하게 복잡
  - `computeCombinedStatus`는 `computeOrderBlockStatus`를 호출하며, 이는 `UIState` + `AppSettings`를 매개변수로 받음 — 이미 공통 추출됨
  - 배지 계산을 별도 파일로 분리하면 `buy-target.ts`가 330줄로 감소하나, 분리된 파일이 다시 150줄의 배지 전용 모듈이 되며 consumer는 `buy-target.ts` 1곳뿐 → 공통화 실익 없음
- 477줄은 상한(500줄) 이하
- mount/unmount 구조가 명확하고 모듈 변수 관리가 정돈되어 있음

---

### 2.6 `sector-stock.ts` (482줄, 53회 변경)

#### 책임 묶음

| # | 책임 | 줄 범위 | 변경 이유 |
|---|------|---------|-----------|
| A | Web Component 클래스 정의 (SectorStockTable extends HTMLElement) | 27–56 | 클래스 구조 변경 (드물음) |
| B | 행 빌드 + UI 갱신 (buildRows, refreshRows, updateUI) | 58–135 | 행 계산 로직, 업종 필터, NXT 안내 |
| C | DOM 빌더 (buildSummaryBar, buildFilterBadge, buildNxtNoticeBadge, buildSearchRow, buildEmptyAndScroll) | 137–330 | UI 레이아웃, 배지/검색 추가 |
| D | Store 구독 (setupSubscriptions — 선택적 구독 가드) | 332–380 | 구독 필드 추가/변경 |
| E | connectedCallback / disconnectedCallback (mount/unmount) | 382–477 | 생명주기 관리 |

#### Fan-in / Fan-out

- **Fan-in**: 1 — `sector-ranking-page.ts`에서 `<sector-stock-table>` Custom Element로 사용
- **Fan-out**: 9 — `data-table`, `hotStore`, `uiStore`, `ws`, `card-title`, `button`, `search-input`, `market-count-row`, `ui-styles`, `types`, `stock-search`, `sector-stock-rows`

#### 상태·렌더링·이벤트·스타일 경계

| 영역 | 현황 |
|------|------|
| **상태** | 인스턴스 필드 15종 (DOM 참조 + 검색어 + 캐시 + rafId) |
| **렌더링** | `refreshRows` (DataTable updateRows) + `updateUI` (카운트/배지/빈 상태) |
| **이벤트** | Store 구독 2종 + window 이벤트 1종 (real-data-tick) |
| **스타일** | 인라인 스타일 (summaryBar, filterBadge, nxtNoticeBadge, searchRow, scrollContainer) + COLOR 참조 |

#### 변경 집중 원인

**가장 빈번한 변경 (53회)**. 업종별 종목 시세 페이지는 핵심 기능이므로 기능 추가/수정이 빈번. 그러나 순수 로직(컬럼 정의, 행 계산, 검색 필터)은 이미 `sector-stock-rows.ts`로 분리되어 있음 (P24 단순성). 남은 482줄은 Web Component 생명주기 + DOM 빌더 + Store 구독으로 구성.

#### 분리 가능성 판정: **⊘ 유지**

- 순수 로직은 이미 `sector-stock-rows.ts`로 분리 완료
- DOM 빌더(C, 약 190줄) 분리 가능성 검토:
  - 각 빌더가 인스턴스 필드(this.titleFilterNumSpan, this.filterBadge 등)를 직접 설정 → 분리 시 인스턴스 필드 접근 경로 복잡
  - 빌더 간 순서 의존성 존재 (buildSummaryBar → buildFilterBadge → buildNxtNoticeBadge → buildSearchRow → buildEmptyAndScroll)
  - consumer는 1곳(클래스 자신)이므로 공통화 실익 없음
- 482줄은 상한(500줄) 이하

---

### 2.7 `data-table-fixed.ts` (469줄, 5회 변경)

#### 책임 묶음

| # | 책임 | 줄 범위 | 변경 이유 |
|---|------|---------|-----------|
| A | createFixedMode 팩토리 — 테이블 DOM 구축 | 22–94 | 초기 설계 (드물게 수정) |
| B | 행 렌더링 (renderGroupRow, renderDataRow) | 96–163 | 셀 렌더링 로직, P25 격리 |
| C | rAF 렌더링 스케줄러 + updateRows (keyFn 기반 증분 갱신) | 165–406 | 증분 갱신 로직, 빈 데이터 처리 |
| D | updateItemByKey (O(1) 실시간 갱신) | 420–466 | 실시간 갱신 로직 |
| E | destroy | 414–418 | 정리 로직 |

#### Fan-in / Fan-out

- **Fan-in**: 1 — `data-table.ts`에서 `createFixedMode`를 import
- **Fan-out**: 3 — `ui-styles`, `data-table` (ColumnDef 등 타입 + 유틸 함수), `virtual-scroller` (CellWithPrevContent 타입만)

#### 상태·렌더링·이벤트·스타일 경계

| 영역 | 현황 |
|------|------|
| **상태** | 클로저 변수 (currentRows, rowCaches, pendingRows, rafId, destroyed) |
| **렌더링** | `scheduleRender` → rAF 콜백 내 keyFn 기반 증분 갱신 또는 인덱스 기반 갱신 |
| **이벤트** | 없음 (외부에서 API 호출로 갱신) |
| **스타일** | 인라인 스타일 (table, th, td) + COLOR/FONT_SIZE 참조 |

#### 변경 집중 원인

변경 빈도가 매우 낮음(5회/1.5년). F06-01 세션에서 `data-table.ts` 분할 시 생성된 파일. 469줄 중 약 240줄이 keyFn 기반 증분 갱신 로직(C)이고, 약 100줄이 인덱스 기반 갱신 로직(C 내 else 블록). 두 경로는 `options.keyFn` 유무로 분기되며, 셀 렌더링 패턴은 양쪽에 중복 존재 (P24 중복 — 그러나 분리 시 함수 매개변수가 과도하게 늘어남).

#### 분리 가능성 판정: **⊘ 유지**

- 469줄은 상한(500줄) 이하
- 변경 빈도 매우 낮음 — 분할의 실익 없음
- keyFn 경로와 인덱스 경로의 셀 렌더링 중복은 P24 위반이나, 분리 시 `columns`, `rowStyle`, `zebraStriping`, `triggerFlash` 등 클로저 변수를 매개변수로 전달해야 하여 함수 시그니처가 과도하게 복잡해짐
- `updateItemByKey`의 셀 렌더링도 동일 패턴 중복 — 동일한 이유로 분리 비효율

---

## 3. 종합 분석

### 3.1 변경 빈도 vs 줄 수

| 파일 | 줄 수 | 변경 수 | 변경/줄 비율 | 판정 |
|------|-------|---------|-------------|------|
| `sector-stock.ts` | 482 | 53 | **0.110** | 변경 집중도 최고 — 핵심 기능 페이지 |
| `buy-target.ts` | 477 | 52 | **0.109** | 변경 집중도 최고 — 핵심 기능 페이지 |
| `header.ts` | 615 | 39 | 0.063 | 상태 표시 추가 누적 |
| `hotStore.ts` | 751 | 31 | 0.041 | WS 이벤트 핸들러 추가 |
| `profit-shared.ts` | 537 | 30 | 0.056 | 수익 도메인 로직 변경 |
| `virtual-scroller.ts` | 555 | 12 | 0.022 | 안정화된 인프라 |
| `data-table-fixed.ts` | 469 | 5 | 0.011 | 안정화된 인프라 |

### 3.2 줄 수 초과 파일 (500줄 기준)

| 파일 | 줄 수 | 초과 | 분리 판정 |
|------|-------|------|-----------|
| `hotStore.ts` | 751 | +251 | ⊘ 유지 — 공유 상태(store, 캐시, dirty Set) 분할 시 접근 복잡도 증가 |
| `header.ts` | 615 | +115 | ⊘ 유지 — 칩 렌더링 패턴 반복, 분리 시 공유 컨텍스트 전달 오버헤드 |
| `virtual-scroller.ts` | 555 | +55 | ⊘ 유지 — 순수 함수/팩토리 경계 명확, 변경 빈도 낮음 |
| `profit-shared.ts` | 537 | +37 | ⊘ 유지 — 14개 export가 동일 도메인에 응집, 8개 consumer 분산 위험 |

### 3.3 분리 불가능 공통 원인

1. **공유 클로저/모듈 스코프 상태**: `hotStore.ts`(store + 캐시 + dirty Set), `virtual-scroller.ts`(items + offsets + pool + activeRows), `data-table-fixed.ts`(currentRows + rowCaches + pendingRows) — 분할 시 상태 접근 경로가 복잡해져 P24 단순성 위반
2. **단일 consumer**: `header.ts`(shell.ts 1곳), `buy-target.ts`(main.ts 1곳), `sector-stock.ts`(sector-ranking-page.ts 1곳), `data-table-fixed.ts`(data-table.ts 1곳) — 공통화 실익 없음
3. **이미 분리된 순수 로직**: `sector-stock.ts`는 `sector-stock-rows.ts`로 분리 완료, `data-table-fixed.ts`는 `data-table.ts`에서 분할 생성 — 잔여 분량은 생명주기/DOM/Store 구독으로 분리 불가

### 3.4 중복 패턴 식별 (P24 관찰)

| 패턴 | 위치 | 중복 횟수 | 분리 가능성 |
|------|------|-----------|-------------|
| 셀 렌더링 (textContent 비교 + flash) | `data-table-fixed.ts` | 3회 (keyFn 경로, 인덱스 경로, updateItemByKey) | ⊘ — 클로저 변수 매개변수화 시 시그니처 과도 |
| 칩 렌더링 (style 배경/색/border + textContent) | `header.ts` | 15회 (onStateChange 내 try-catch 블록) | ⊘ — 각 칩이 고유한 상태 필드/포맷 사용 |
| 배지 갱신 (updateBadge 호출) | `buy-target.ts` | 3회 (combined, daily, holding) | ⊘ — 각 배지가 고유한 계산 로직 사용 |
| tick 리스너 (addEventListener + updateItemByKey) | `buy-target.ts` | 3회 (real-data, orderbook, program) | ⊘ — 이벤트명만 다르고 패턴 동일하나 3회는 추출 임계치 미만 |

---

## 4. 권장 사항

### 4.1 즉시 분리 대상: **없음**

모든 대상 파일이 ⊘ 유지 판정. 줄 수 초과 4개 파일 모두 분리 시 실익이 없거나 복잡도가 증가.

### 4.2 장기적 관찰 항목

| 항목 | 현재 상태 | 임계 도달 시 권장 |
|------|-----------|------------------|
| `hotStore.ts` 줄 수 증가 | 751줄 — WS 이벤트 핸들러 추가 시 증가 | 900줄 도달 시 이벤트 그룹별 분할 검토 (단, 공유 상태 접근 방안 먼저 설계) |
| `header.ts` 칩 추가 | 15개 칩 — 신규 상태 표시 시 증가 | 20개 칩 도달 시 칩 렌더링을 팩토리 패턴으로 통일 검토 |
| `buy-target.ts` 배지 추가 | 3개 배지 | 5개 배지 도달 시 배지 계산 로직 별도 모듈 검토 |
| `data-table-fixed.ts` 셀 렌더링 중복 | 3회 중복 | 4회 도달 시 셀 렌더링 헬퍼 추출 검토 (단, 클로저 변수 매개변수화 포함) |

### 4.3 기존 분할 효과 확인

이미 수행된 분할이 효과적으로 작동 중:

| 분할 | 시기 | 효과 |
|------|------|------|
| `data-table.ts` → `data-table-fixed.ts` + `data-table-virtual.ts` | F06-01 | `data-table-fixed.ts` 5회 변경 (매우 안정) |
| `sector-stock.ts` → `sector-stock-rows.ts` | 사전 분할 | 순수 로직 분리로 테스트 용이성 확보 |
| `buy-target.ts` → `buy-target-columns.ts` | 사전 분할 | 컬럼 정의 독립 관리 |

---

## 5. 검증 결과

### 5.1 Fan-in/Fan-out 대조

| 파일 | grep fan-in | 코드 확인 | 일치 |
|------|-------------|-----------|------|
| `header.ts` | 3 파일 (shell, buy-target, sell-position) | shell.ts만 `createHeader` 호출, 나머지는 header 변수명 충돌 | ✓ |
| `hotStore.ts` | 16 파일 | 16개 파일에서 import 확인 | ✓ |
| `virtual-scroller.ts` | 2 파일 | data-table-virtual + data-table-fixed (타입만) | ✓ |
| `profit-shared.ts` | 8 파일 | 8개 수익 페이지에서 import | ✓ |
| `buy-target.ts` | 1 파일 (main.ts lazy import) | 라우터에서 dynamic import | ✓ |
| `sector-stock.ts` | 2 파일 (sector-ranking-page + 자체) | Custom Element로 등록/사용 | ✓ |
| `data-table-fixed.ts` | 1 파일 (data-table.ts) | createFixedMode import | ✓ |

### 5.2 테스트 커버리지

| 파일 | 테스트 파일 | 비고 |
|------|------------|------|
| `hotStore.ts` | `tests/stores/hotStore.test.ts` (40 matches) | 상세 테스트 존재 |
| `data-table-fixed.ts` | `tests/components/data-table.ui.test.ts` (6 matches) | UI 통합 테스트 |
| `buy-target.ts` | `tests/utils/order-block-status.test.ts` (1 match) | 간접 테스트 (배지 판정 로직) |
| `header.ts` | 없음 | — |
| `virtual-scroller.ts` | 없음 (순수 함수는 PBT 가능 구조) | — |
| `profit-shared.ts` | 없음 | — |
| `sector-stock.ts` | 없음 | — |

### 5.3 금지 패턴 확인

| 패턴 | 대상 파일 | 확인 결과 |
|------|-----------|-----------|
| `asyncio.run()` | 해당 없음 (프론트엔드) | — |
| `create_task` 무분별 분리 | 해당 없음 (프론트엔드) | — |
| `except Exception: pass` | 7개 파일 전수 | **위반 없음** — 모든 catch 블록이 `console.error` 로깅 |
| `await` 누락 | 해당 없음 (프론트엔드) | — |
| dead code | 7개 파일 전수 | **위반 없음** — 모든 export 함수가 실제 import됨 |

---

## 6. 결론

COUPLING-S9 대상 7개 파일(총 3,886줄)의 변경 책임 집중 조사 결과:

1. **줄 수 초과 4개 파일 모두 ⊘ 유지 판정** — 분리 시 공유 상태 접근 복잡도 증가 또는 단일 consumer로 공통화 실익 없음
2. **변경 빈도 최고 2개 파일**(`sector-stock.ts` 53회, `buy-target.ts` 52회)은 **이미 순수 로직이 분리되어 있으며** 잔여 분량은 생명주기/DOM/Store 구독으로 분리 불가
3. **중복 패턴 4종 식별**되었으나 모두 추출 임계치 미만(3회)이거나 클로저 변수 매개변수화 비용이 분리 이득을 초과
4. **금지 패턴 5개 중 0건 위반** — P25 격리(try-catch + 로깅)가 모든 파일에 일관적으로 적용됨
5. **장기적 관찰 항목 4개**만 추적 대상으로 지정

> **최종 판정**: 모든 대상 파일 ⊘ 유지. 분리 보다 관찰 우선.
