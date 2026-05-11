# Requirements Document: HTS 급 최적화 전수조사 및 수정계획

## Introduction

SectorFlow 실시간 주식 자동매매 앱의 전체 코드베이스를 HTS(Home Trading System) 수준의 성능 기준으로 전수조사한 결과, UI 관점에서 일반 사용자가 체감할 수 있는 성능 미달 영역을 식별하고 수정 요구사항을 정의한다.

**전수조사 결과 요약 (확인된 사실 기반):**

| 영역 | 현재 상태 | HTS 기준 미달 사항 |
|------|----------|-------------------|
| 보유종목 테이블 (sell-position.ts) | 모든 store 변경 시 무조건 2회 updateRows 호출 | 불필요한 이중 렌더링 → 프레임 드롭 |
| 매수후보 테이블 (buy-target.ts) | 매 store 변경 시 sort + updateRows (rAF 미사용) | 고빈도 틱에서 정렬 연산 과부하 |
| DataTable renderRow (data-table.ts line 380) | 매 렌더링 시 `rowEl.innerHTML = ''` 후 전체 셀 재생성 | DOM GC 부하 + 레이아웃 thrashing |
| fixed-table.ts updateRows | `tbody.innerHTML = ''` 후 전체 행 재생성 | 초기 마운트 외 사용 시 성능 저하 |
| sector-stock.ts updateUI | `titleH3.innerHTML = ''` 사용 (line 434) | 매 갱신 시 타이틀 DOM 파괴/재생성 |
| applyRealData (appStore.ts) | buyTargets findIndex O(n) 선형 탐색 | 100+ 종목 시 매 틱마다 선형 탐색 |
| applyRealData (appStore.ts) | positions findIndex O(n) 선형 탐색 | 보유종목 많을 시 매 틱마다 선형 탐색 |
| applyRealData (appStore.ts) | `[...bt]` 배열 전체 복사 (splice 미사용) | 워크룰 위반 — splice 기반 증분 미적용 |
| WSClient (ws.ts) | 재연결 시 REST 백필 없음 | 데이터 무결성 위반 (워크룰 8.2) |
| 가상 스크롤러 updateItems | 매 호출 시 recomputeOffsets (O(n) 전체 재계산) | 단일 종목 가격 변경에도 전체 오프셋 재계산 |
| profit-overview.ts | 차트 + 테이블 동시 구독, rAF 미사용 | 고빈도 갱신 시 불필요한 재렌더링 |
| sell-position.ts | 선택적 구독 가드 없음 (모든 state 변경에 반응) | sectorStocks 변경마다 불필요한 테이블 갱신 |
| WS 재연결 (ws.ts) | 재연결 시 유실 구간 REST 백필 없음 | 데이터 무결성 위반 (워크룰 8.2) |
| 백엔드 _is_relevant_code | 매 틱마다 _positions 리스트 순회 + _sector_stock_layout 순회 | O(n) 반복 탐색 → set 캐시 미사용 |

## Glossary

- **DataTable**: `frontend/src/components/common/data-table.ts`의 공통 테이블 컴포넌트 (가상 스크롤 / 고정 모드)
- **Virtual_Scroller**: `frontend/src/components/virtual-scroller.ts`의 DOM 풀 기반 가상 스크롤러
- **AppStore**: `frontend/src/stores/appStore.ts`의 Zustand 기반 전역 상태 저장소
- **WSClient**: `frontend/src/api/ws.ts`의 WebSocket 클라이언트 클래스
- **WSManager**: `backend/app/web/ws_manager.py`의 서버측 WebSocket 브로드캐스트 매니저
- **applyRealData**: AppStore 내 실시간 체결 데이터 적용 함수
- **rAF**: requestAnimationFrame — 브라우저 렌더링 프레임에 맞춘 갱신 예약
- **splice_update**: 배열의 특정 인덱스만 교체하는 증분 갱신 방식
- **Coalescing**: 짧은 시간 내 동일 이벤트를 최신값 하나로 병합하는 기법
- **HTS**: Home Trading System — 증권사 전용 트레이딩 프로그램 (키움 영웅문 등)
- **Sector_Stock_Page**: `frontend/src/pages/sector-stock.ts` 업종별 종목 시세 페이지
- **Buy_Target_Page**: `frontend/src/pages/buy-target.ts` 매수후보 페이지
- **Sell_Position_Page**: `frontend/src/pages/sell-position.ts` 보유종목 페이지
- **Profit_Overview_Page**: `frontend/src/pages/profit-overview.ts` 수익현황 페이지
- **FixedTable**: `frontend/src/components/common/fixed-table.ts` 고정 행 테이블 컴포넌트
- **Router**: `frontend/src/router.ts` SPA 라우터 (동적 import 기반)
- **Page_Aware_Filter**: WSManager 내 per-client active_page 기반 데이터 전송 필터링 로직
- **active_page**: 각 WebSocket 클라이언트가 현재 보고 있는 페이지 식별자 (sector-analysis, buy-target, sell-position, profit-overview, settings)
- **AutoTradeManager**: `backend/app/services/trading.py`의 자동매매 실행 매니저 (100% 백엔드 동작, 프론트엔드 상태와 무관)

## Requirements

### Requirement 1: 보유종목 테이블 이중 렌더링 제거

**User Story:** 일반 사용자로서, 보유종목 페이지에서 실시간 가격 변동 시 끊김 없이 부드러운 테이블 갱신을 원한다.

**현재 문제 (sell-position.ts line 128~136):**
- store 구독 콜백에서 `dataTable.updateRows(positions)` 호출 후, `sectorStocks.length > 0` 조건으로 동일 데이터를 한 번 더 `updateRows` 호출
- 선택적 구독 가드 없음 — sectorStocks 변경(매 틱)마다 불필요하게 반응
- rAF 미사용 — 동일 프레임 내 다중 갱신 발생

#### Acceptance Criteria

1. WHEN store 상태가 변경될 때, IF positions 참조가 이전 구독 콜백 시점의 참조와 동일하면(`===` reference equality), THEN THE Sell_Position_Page SHALL updateRows를 호출하지 않는다
2. WHEN sectorStocks만 변경되고 positions 참조가 변경되지 않았을 때, THE Sell_Position_Page SHALL 보유종목 테이블의 updateRows를 호출하지 않는다
3. WHEN 단일 애니메이션 프레임(16.67ms) 내에 2회 이상의 store 변경 알림이 발생할 때, THE Sell_Position_Page SHALL requestAnimationFrame을 사용하여 해당 프레임의 마지막 positions 상태로 updateRows를 1회만 호출한다
4. WHEN positions 참조가 변경되어 갱신이 필요할 때, THE Sell_Position_Page SHALL 단일 requestAnimationFrame 콜백 내에서 updateRows를 정확히 1회만 호출한다 (동일 프레임 내 이중 호출 제거)
5. WHEN Sell_Position_Page가 unmount될 때, THE Sell_Position_Page SHALL 대기 중인 requestAnimationFrame 요청을 cancelAnimationFrame으로 취소하고 store 구독을 해제한다

---

### Requirement 2: 매수후보 테이블 고빈도 갱신 최적화

**User Story:** 일반 사용자로서, 매수후보 목록이 실시간 시세 변동 중에도 버벅임 없이 즉각 반영되기를 원한다.

**현재 문제 (buy-target.ts line 186~210):**
- 매 store 변경 시 `[...state.buyTargets].sort()` 전체 복사 + 정렬 수행
- rAF 미사용 — 초당 수십 회 틱 수신 시 매번 sort + updateRows

#### Acceptance Criteria

1. WHEN 하나 이상의 buyTargets store 변경이 발생할 때, THE Buy_Target_Page SHALL requestAnimationFrame 콜백 내에서 sort + updateRows를 수행하되, 동일 애니메이션 프레임(~16ms) 내 후속 변경은 추가 rAF를 예약하지 않고 기존 예약된 1회 콜백에서 최신 상태를 반영한다
2. IF buyTargets 참조가 직전 렌더링 시점의 참조와 동일하면(=== 비교), THEN THE Buy_Target_Page SHALL sort 호출 및 dataTable.updateRows 호출을 생략한다
3. IF buyTargets만 변경되고 positions, settings, wsSubscribeStatus, buyLimitStatus 참조가 모두 직전과 동일하면, THEN THE Buy_Target_Page SHALL updateBadges 호출을 생략한다
4. WHEN Buy_Target_Page가 unmount될 때, THE Buy_Target_Page SHALL 예약된 requestAnimationFrame 핸들을 cancelAnimationFrame으로 취소하여 unmount 이후 콜백 실행을 방지한다

---

### Requirement 3: DataTable renderRow DOM 재사용 최적화

**User Story:** 일반 사용자로서, 200개 이상 종목이 표시되는 테이블에서 스크롤 시 60fps 부드러운 화면을 원한다.

**현재 문제 (data-table.ts createVirtualScrollMode 내 renderRow, line 380):**
- `rowEl.innerHTML = ''` 후 모든 셀을 `document.createElement`로 재생성
- 가상 스크롤러가 같은 키의 행을 재사용할 때도 전체 셀 DOM을 파괴/재생성
- 셀 내용만 변경되었을 때도 전체 레이아웃 재계산 발생

#### Acceptance Criteria

1. WHEN 가상 스크롤러가 동일 키의 행을 재렌더링할 때, THE DataTable SHALL 기존 셀 DOM 요소(자식 div)를 유지한 채 각 셀의 textContent 또는 자식 HTMLElement만 교체하고, rowEl.innerHTML 초기화를 수행하지 않는다
2. WHEN 셀의 render 결과(문자열인 경우 textContent, HTMLElement인 경우 outerHTML)가 이전 렌더링 결과와 동일할 때, THE DataTable SHALL 해당 셀의 DOM 속성 및 자식 노드를 변경하지 않는다 (DOM mutation 0건)
3. IF renderRow 내부에서 예외가 발생하면, THEN THE DataTable SHALL 해당 행의 기존 셀 DOM을 그대로 유지하고, 나머지 행의 렌더링을 중단 없이 계속한다
4. WHILE 200개 이상의 행이 로드된 상태에서 스크롤 중일 때, THE DataTable SHALL 단일 renderRow 호출을 2ms 이내에 완료하여 16.6ms 프레임 예산 내에서 최소 8개 행을 처리할 수 있도록 한다
5. WHEN 행이 처음 렌더링될 때(풀에서 새로 획득하거나 행 타입이 GroupRow↔DataRow로 변경된 경우), THE DataTable SHALL columns.length개의 셀 div를 생성하여 rowEl에 추가한다

---

### Requirement 4: applyRealData 선형 탐색 제거 (인덱스 캐시)

**User Story:** 일반 사용자로서, 100개 이상 종목을 동시 모니터링할 때 현재가 갱신이 HTS와 동일한 속도로 반영되기를 원한다.

**현재 문제 (appStore.ts applyRealData line 295~320):**
- `bt.findIndex(t => t.code === code)` — buyTargets 배열 O(n) 선형 탐색
- `positions.findIndex(p => p.stk_cd === code)` — positions 배열 O(n) 선형 탐색
- 매 체결 틱(초당 수십~수백 회)마다 반복 실행

#### Acceptance Criteria

1. THE AppStore SHALL buyTargets 배열의 code→index 매핑을 별도 인덱스(Map 또는 Record)로 유지하여, 종목 코드로부터 배열 인덱스를 O(1)에 조회할 수 있도록 한다
2. THE AppStore SHALL positions 배열의 stk_cd→index 매핑을 별도 인덱스(Map 또는 Record)로 유지하여, 종목 코드로부터 배열 인덱스를 O(1)에 조회할 수 있도록 한다
3. WHEN buyTargets 배열이 변경될 때(applyRealData, applyOrderbookUpdate, applyBuyTargetsUpdate, buy-targets-delta 핸들러 포함), THE AppStore SHALL 동일 setState 호출 내에서 code→index 인덱스 매핑을 갱신하여 배열과 인덱스 간 정합성을 보장한다
4. WHEN positions 배열이 변경될 때(applyRealData, account-update 핸들러 포함), THE AppStore SHALL 동일 setState 호출 내에서 stk_cd→index 인덱스 매핑을 갱신하여 배열과 인덱스 간 정합성을 보장한다
5. WHEN applyRealData 또는 applyOrderbookUpdate가 호출될 때, THE AppStore SHALL findIndex 선형 탐색 대신 인덱스 매핑을 사용하여 O(1)로 대상 항목을 조회한다
6. WHEN buyTargets 또는 positions에 200개 항목이 존재하는 상태에서 applyRealData가 초당 300회 호출될 때, THE AppStore SHALL 단일 applyRealData 호출의 조회 소요 시간이 1ms 미만이어야 한다

---

### Requirement 5: applyRealData splice 기반 증분 갱신 적용

**User Story:** 일반 사용자로서, 실시간 가격 변동 시 불필요한 메모리 할당 없이 즉각적인 UI 반영을 원한다.

**현재 문제 (appStore.ts applyRealData line 300~305):**
- `buyTargets = [...bt]` — 전체 배열 복사 후 인덱스 교체
- `positions = [...positions]` — 전체 배열 복사 후 인덱스 교체
- 워크룰 6번 "❌ `.map()` 전체 재생성 → ✅ splice 기반 증분" 위반

#### Acceptance Criteria

1. WHEN buyTargets 내 항목의 실시간 필드(cur_price, change, change_rate, strength, trade_amount) 중 하나 이상이 기존 값과 다를 때, THE AppStore SHALL 전체 배열 스프레드 복사(`[...arr]`) 없이 `splice(idx, 1, newItem)`를 사용하여 해당 인덱스의 항목만 교체한다
2. WHEN positions 내 항목의 cur_price가 기존 값과 다를 때, THE AppStore SHALL 전체 배열 스프레드 복사(`[...arr]`) 없이 `splice(idx, 1, newItem)`를 사용하여 해당 인덱스의 항목만 교체하고, 교체되는 항목은 eval_amount, pnl_amount, pnl_rate를 재계산한 새 객체여야 한다
3. WHEN applyRealData가 호출되었으나 대상 종목이 buyTargets와 positions 어디에도 존재하지 않거나, 존재하더라도 비교 대상 필드가 모두 기존 값과 동일할 때, THE AppStore SHALL Zustand set()을 호출하지 않고 기존 state를 그대로 유지한다
4. WHEN splice로 배열 항목을 교체한 후, THE AppStore SHALL 동일한 배열 참조를 Zustand set()에 전달하여 변경된 슬라이스의 구독자만 리렌더링을 트리거한다

---

### Requirement 6: sector-stock 타이틀 innerHTML 제거

**User Story:** 일반 사용자로서, 업종별 종목 시세 페이지 상단 타이틀이 깜빡임 없이 안정적으로 표시되기를 원한다.

**현재 문제 (sector-stock.ts updateUI line 434):**
- `titleH3.innerHTML = ''` 후 새 span 생성 — 매 갱신 시 타이틀 DOM 파괴/재생성
- 워크룰 6번 "❌ `innerHTML = ''` 후 재구축 → ✅ CSS display 토글 + 증분 갱신" 위반

#### Acceptance Criteria

1. THE Sector_Stock_Page SHALL 타이틀 영역의 DOM 요소(기본 타이틀 span, 거래대금 필터 span, 종목 수 span)를 mount 시 1회만 생성하고, 이후 updateUI 호출 시 새로운 요소를 생성하거나 기존 요소를 제거하지 않는다
2. WHEN sectorStatus가 true이고 minTradeAmt 또는 stockCount 값이 변경될 때, THE Sector_Stock_Page SHALL 거래대금 필터 span의 textContent와 종목 수 span의 textContent만 새 값으로 갱신하고, innerHTML을 사용하지 않는다
3. WHEN sectorStatus가 false일 때, THE Sector_Stock_Page SHALL 거래대금 필터 span과 종목 수 span을 `display: none`으로 숨기고, 기본 타이틀 span만 표시한다
4. IF sectorStatus가 false에서 true로 변경되면, THEN THE Sector_Stock_Page SHALL 거래대금 필터 span과 종목 수 span을 `display: ''`로 전환하여 표시하고, DOM 요소의 추가/제거 없이 CSS display 토글만 수행한다

---

### Requirement 7: fixed-table updateRows 증분 갱신

**User Story:** 일반 사용자로서, 수익현황 페이지의 체결이력 테이블이 새 데이터 추가 시 깜빡임 없이 부드럽게 갱신되기를 원한다.

**현재 문제 (fixed-table.ts updateRows line 167):**
- `tbody.innerHTML = ''` 후 모든 행을 `renderDataRow`로 재생성
- 체결이력 prepend 시에도 전체 테이블 재구축

#### Acceptance Criteria

1. WHEN 새 행이 추가될 때, THE FixedTable SHALL rowKey 함수로 기존 행과 신규 행을 식별하여, 기존 행의 DOM 노드를 제거하지 않고 신규 행만 tbody의 선두(prepend) 또는 말미(append)에 삽입한다
2. WHEN 행이 제거될 때, THE FixedTable SHALL rowKey 기준으로 더 이상 존재하지 않는 행의 DOM 노드만 tbody에서 제거한다
3. WHEN 행 데이터가 변경될 때, THE FixedTable SHALL 동일 rowKey를 가진 행에서 각 셀의 render 결과를 이전 값과 비교하여, 변경된 셀의 내용만 교체한다
4. IF updateRows 호출 시 기존 tbody에 렌더링된 행이 0개이면(초기 로딩), THEN THE FixedTable SHALL innerHTML 초기화 후 전체 행을 일괄 렌더링한다
5. WHEN 증분 갱신(삽입, 제거, 셀 교체)이 수행될 때, THE FixedTable SHALL 단일 updateRows 호출의 DOM 조작을 16ms 이내에 완료한다

---

### Requirement 8: WS 재연결 시 데이터 백필

**User Story:** 일반 사용자로서, 네트워크 순단 후 재연결 시 누락된 가격 데이터가 자동으로 복구되어 정확한 현재가를 확인할 수 있기를 원한다.

**현재 문제 (ws.ts _scheduleReconnect):**
- 재연결 성공 후 유실 구간에 대한 REST 백필 없음
- 워크룰 8.2 "유실 허용치 0: WS 재연결 시 유실 구간은 REST로 백필" 위반

#### Acceptance Criteria

1. WHEN WebSocket 재연결이 성공할 때, THE WSClient SHALL 장중 실시간 데이터 필드를 비우고 서버로부터 initial-snapshot 이벤트 수신을 대기한다
2. WHEN 서버가 initial-snapshot을 전송할 때, THE AppStore SHALL 현재 상태를 스냅샷으로 전체 교체(applyInitialSnapshot)하고 정상 실시간 수신 모드로 전환한다
3. WHILE 재연결 후 initial-snapshot 수신 대기 중, THE AppStore SHALL connected 상태를 true로 유지하되 별도 backfilling 플래그를 true로 설정하여 UI가 동기화 진행 상태를 표시할 수 있도록 한다
4. WHEN initial-snapshot이 AppStore에 반영 완료될 때, THE WSClient SHALL backfilling 플래그를 false로 설정하고 정상 실시간 수신 모드(수신 즉시 Store 반영)로 전환한다

---

### Requirement 9: 백엔드 _is_relevant_code 성능 최적화

**User Story:** 일반 사용자로서, 서버가 실시간 데이터를 지연 없이 전달하여 HTS와 동일한 현재가를 확인할 수 있기를 원한다.

**현재 문제 (engine_account_notify.py _is_relevant_code line 253~268):**
- 매 틱마다 `_es._positions` 리스트 전체 순회 (`any(...)`)
- 매 틱마다 `_es._sector_stock_layout` 리스트 전체 순회 (`any(...)`)
- 초당 수백 회 호출 시 O(n) × 2 반복 탐색

#### Acceptance Criteria

1. THE WSManager SHALL `_positions`의 각 항목에서 `stk_cd` 필드를 6자리 정규화하여 `set[str]` 자료구조로 캐시한다
2. THE WSManager SHALL `_sector_stock_layout`에서 타입이 "code"인 튜플의 값을 `set[str]` 자료구조로 캐시한다
3. WHEN `_positions`가 재할당되거나 `_sector_stock_layout`이 재할당 또는 clear될 때, THE WSManager SHALL 해당 캐시 set을 동일 호출 내에서(별도 비동기 태스크 없이) 재구축한다
4. WHEN `_is_relevant_code`가 호출될 때, THE WSManager SHALL `_pending_stock_details` dict의 `in` 연산과 캐시 set의 `in` 연산(각 O(1))만으로 관련 여부를 판별하며, 리스트 순회(`any(...)`)를 사용하지 않는다
5. IF `_positions` 캐시 set과 `_sector_stock_layout` 캐시 set 모두에 해당 종목코드가 없고 `_pending_stock_details`에도 없으면, THEN THE WSManager SHALL `False`를 반환하여 해당 틱의 브로드캐스트를 생략한다
6. WHEN `_is_relevant_code`가 초당 500회 호출될 때, THE WSManager SHALL 호출당 평균 처리 시간을 10μs 이하로 유지한다

---

### Requirement 10: 가상 스크롤러 오프셋 증분 계산

**User Story:** 일반 사용자로서, 200개 이상 종목 테이블에서 실시간 가격 변동 시에도 스크롤이 끊기지 않기를 원한다.

**현재 문제 (virtual-scroller.ts updateItems line 218):**
- 매 updateItems 호출 시 `recomputeOffsets()` — O(n) 전체 오프셋 재계산
- 행 높이가 고정(32px/48px)인 경우에도 매번 전체 순회

#### Acceptance Criteria

1. IF getRowHeight가 모든 인덱스에 대해 동일한 값을 반환하는 것이 초기화 시점에 확인되면, THEN THE Virtual_Scroller SHALL offsets 배열 순회 없이 산술 계산(index × rowHeight)으로 오프셋을 반환하고, getRowHeight 호출을 생략한다
2. WHEN updateItems가 호출되고 새 items 배열의 길이가 이전과 동일하며 고정 높이 모드가 활성 상태일 때, THE Virtual_Scroller SHALL 오프셋 재계산을 생략하고 sentinel 높이를 유지한다
3. WHEN updateItems가 호출되고 새 items 배열의 길이가 이전과 다를 때, THE Virtual_Scroller SHALL 고정 높이 모드에서는 산술 계산으로 totalHeight와 sentinel 높이만 갱신하고, 가변 높이 모드에서는 전체 오프셋을 재계산한다
4. WHEN updateItem이 호출되고 해당 행의 높이가 변경되지 않았을 때, THE Virtual_Scroller SHALL 오프셋 재계산을 생략한다
5. WHEN updateItem이 호출되고 해당 행의 높이가 변경되었을 때, THE Virtual_Scroller SHALL 해당 행 이후의 오프셋만 증분 갱신하여 O(n−index) 이내에 완료한다
6. IF 최적화 적용 후 computeVisibleRange에 전달되는 offsets 값이 전체 재계산 결과와 1px 이상 차이가 발생하면, THEN THE Virtual_Scroller SHALL 전체 재계산으로 폴백하여 스크롤 위치 정합성을 보장한다

---

### Requirement 11: profit-overview 페이지 rAF 갱신 병합

**User Story:** 일반 사용자로서, 수익현황 페이지에서 실시간 계좌 잔고 변동이 부드럽게 반영되기를 원한다.

**현재 문제 (profit-overview.ts mount 내 store 구독):**
- 차트 + 계좌현황 + 요약카드 + 체결이력 테이블이 동일 store 구독에서 동시 갱신
- rAF 미사용 — 고빈도 positions/account 변경 시 매번 전체 UI 갱신

#### Acceptance Criteria

1. WHEN 동일 애니메이션 프레임(16.6ms) 내에 2회 이상의 store 상태 변경이 발생할 때, THE Profit_Overview_Page SHALL requestAnimationFrame을 사용하여 해당 프레임의 모든 변경을 1회의 DOM 갱신으로 병합한다
2. WHEN positions 또는 account 필드만 변경될 때, THE Profit_Overview_Page SHALL 계좌현황 숫자와 요약카드만 갱신하고, 차트 및 이력 테이블의 DOM은 갱신하지 않는다
3. WHEN sellHistory 또는 buyHistory 필드만 변경될 때, THE Profit_Overview_Page SHALL 해당 이력 테이블과 요약카드만 갱신하고, 차트 및 계좌현황 숫자의 DOM은 갱신하지 않는다
4. WHEN dailySummary 필드만 변경될 때, THE Profit_Overview_Page SHALL 차트만 갱신하고, 계좌현황·요약카드·이력 테이블의 DOM은 갱신하지 않는다
5. WHEN unmount가 호출될 때, THE Profit_Overview_Page SHALL 대기 중인 requestAnimationFrame 콜백을 cancelAnimationFrame으로 취소하고, 이후 어떠한 DOM 갱신도 실행하지 않는다
6. WHILE Profit_Overview_Page가 마운트된 상태에서, THE Profit_Overview_Page SHALL 초당 60회(매 rAF 프레임당 최대 1회)를 초과하는 DOM 갱신을 실행하지 않는다

---

### Requirement 12: 비활성 페이지 구독 해제

**User Story:** 일반 사용자로서, 현재 보고 있지 않은 페이지의 백그라운드 처리로 인한 앱 전체 성능 저하가 없기를 원한다.

**현재 상태 (확인된 사실):**
- 각 페이지는 unmount 시 store 구독을 해제함 (정상)
- 라우터가 페이지 전환 시 이전 페이지 unmount → 새 페이지 mount 순서 보장 (정상)
- 그러나 applyRealData는 모든 페이지와 무관하게 매 틱마다 sectorStocks/buyTargets/positions 전체를 갱신

#### Acceptance Criteria

1. WHILE 사용자가 특정 페이지를 보고 있을 때, THE AppStore SHALL 해당 페이지의 구독 콜백에서 관심 필드의 참조가 변경되지 않은 경우 DOM 갱신 로직을 실행하지 않는다
2. WHEN 페이지가 unmount될 때, THE 페이지 모듈 SHALL 동기적으로(같은 이벤트 루프 턴 내) 해당 페이지의 모든 store 구독 해제와 예약된 requestAnimationFrame 취소를 완료한다
3. THE AppStore SHALL applyRealData 내에서 각 상태 필드(sectorStocks, buyTargets, positions)에 대해 실제 값 변경이 없으면 이전 객체 참조를 유지하여, 해당 필드를 관심 필드로 등록한 구독자의 콜백이 트리거되지 않도록 한다
4. IF unmount 후 이전 페이지가 예약한 requestAnimationFrame 콜백이 실행될 때, THEN THE 콜백 SHALL DOM 조작 없이 즉시 반환한다
5. WHEN applyRealData가 틱 데이터를 처리할 때, THE AppStore SHALL unmount된 페이지의 구독자 수가 0임을 보장하여, 비활성 페이지로 인한 추가 콜백 호출이 발생하지 않는다

---

### Requirement 13: 가격 변동 시각적 피드백 (플래시 효과)

**User Story:** 일반 사용자로서, HTS처럼 가격이 변동된 셀이 순간적으로 색상 강조되어 어떤 종목이 움직이는지 즉시 인지할 수 있기를 원한다.

**현재 상태:**
- 가격 변동 시 숫자만 갱신됨 — 시각적 피드백 없음
- HTS는 가격 변동 셀에 0.3~0.5초 배경색 플래시 제공

#### Acceptance Criteria

1. WHEN 종목의 현재가가 이전 값과 다른 값으로 갱신될 때, THE DataTable SHALL 해당 행의 현재가, 대비, 등락률 셀에 배경색 플래시 효과를 적용한다 (배경색이 즉시 적용된 후 300ms에 걸쳐 투명으로 페이드아웃)
2. WHEN 가격이 상승할 때 (현재가 > 직전 현재가), THE DataTable SHALL 빨간색 계열 배경색 플래시를 표시한다
3. WHEN 가격이 하락할 때 (현재가 < 직전 현재가), THE DataTable SHALL 파란색 계열 배경색 플래시를 표시한다
4. THE DataTable SHALL 플래시 효과에 CSS transition (background-color 속성)을 사용하며, JavaScript setTimeout/setInterval 타이머를 사용하지 않는다
5. IF 300ms 이내에 동일 종목의 가격이 재차 변경되면, THEN THE DataTable SHALL 진행 중인 플래시를 즉시 중단하고 새로운 방향(상승/하락)의 플래시를 처음부터 다시 시작한다
6. WHEN 가상 스크롤에서 뷰포트 밖에 있던 행이 스크롤로 다시 표시될 때, THE DataTable SHALL 이미 300ms가 경과한 플래시는 표시하지 않는다 (플래시 없이 최종 가격만 표시)

---

### Requirement 14: WebSocket 메시지 최소화

**User Story:** 일반 사용자로서, 모바일 네트워크나 저대역폭 환경에서도 실시간 데이터가 지연 없이 수신되기를 원한다.

**현재 상태 (ws_manager.py broadcast):**
- 모든 메시지를 JSON 텍스트로 전송
- real-data 메시지에 불필요한 필드(type, item, values 전체 FID) 포함
- 압축 미적용

#### Acceptance Criteria

1. WHEN real-data 메시지를 전송할 때, THE WSManager SHALL values 딕셔너리에서 프론트엔드에서 사용하는 FID(10, 11, 12, 14, 228)만 포함하고, 원본 데이터에 해당 FID가 존재하지 않는 경우 해당 키를 생략한다
2. WHEN real-data 메시지를 전송할 때, THE WSManager SHALL 다음 고정 매핑에 따라 키 이름을 단축형으로 변환하여 전송한다: "type" → "t", "item" → "i", "values" → "v"
3. WHEN 직렬화된 real-data JSON 메시지의 바이트 크기가 512바이트를 초과할 때, THE WSManager SHALL zlib 압축을 적용하여 바이너리 프레임으로 전송한다
4. IF 직렬화된 real-data JSON 메시지의 바이트 크기가 512바이트 이하일 때, THEN THE WSManager SHALL 압축 없이 텍스트 프레임으로 전송한다
5. WHEN 프론트엔드가 WebSocket 메시지를 수신할 때, THE WSClient SHALL 바이너리 프레임이면 zlib 해제 후 JSON 파싱하고, 텍스트 프레임이면 직접 JSON 파싱하여 단축 키를 원래 키로 복원한다

---

### Requirement 15: 초기 로딩 성능 최적화

**User Story:** 일반 사용자로서, 앱 시작 후 3초 이내에 실시간 시세 화면을 확인할 수 있기를 원한다.

**현재 상태 (router.ts):**
- 모듈 캐시 비활성화 (주석 처리됨, line 100~103)
- 매 페이지 전환 시 동적 import 재실행
- 스피너 표시 후 비동기 로딩

#### Acceptance Criteria

1. WHEN 페이지 모듈이 최초 동적 import로 로딩된 후, THE Router SHALL 해당 모듈 참조를 Map에 캐시하여 재방문 시 동적 import를 재실행하지 않고 캐시된 모듈로 즉시 마운트한다
2. WHEN 캐시된 페이지로 전환할 때, THE Router SHALL 스피너를 표시하지 않고 동기적으로 mount 함수를 호출한다
3. WHEN 초기 스냅샷 수신이 완료될 때, THE AppStore SHALL 2초 이내에 첫 번째 페이지의 UI 렌더링을 완료한다

---

### Requirement 16: 메모리 누수 방지 강화

**User Story:** 일반 사용자로서, 앱을 장시간(8시간+) 사용해도 메모리 증가로 인한 성능 저하가 없기를 원한다.

**현재 상태 (확인된 사실):**
- 각 페이지 unmount 시 구독 해제 구현됨 (정상)
- virtual-scroller destroy 시 DOM 정리 구현됨 (정상)
- 그러나 sell-position.ts에 console.log 디버그 출력 잔존 (line 121~122)
- rowCache (sector-stock.ts)가 unmount 시 clear되지 않을 가능성

#### Acceptance Criteria

1. WHEN 페이지가 unmount될 때, THE Virtual_Scroller SHALL destroy() 호출 후 내부 DOM 풀(pool)의 요소 수를 0으로 만들고, 풀에서 제거된 요소가 document에 연결되지 않은 상태(detached)임을 보장한다
2. WHEN Sector_Stock_Page가 unmount될 때, THE Sector_Stock_Page SHALL rowCache(Map)에 대해 clear()를 호출하여 저장된 모든 DOM 행 참조를 해제한다
3. IF 빌드 모드가 프로덕션(production)이면, THEN THE Sell_Position_Page SHALL sell-position.ts line 121~122의 console.log 호출이 번들 출력에 포함되지 않는다
4. WHILE 앱이 8시간 연속 실행 중이고 WebSocket을 통해 실시간 시세를 수신하는 상태일 때, THE AppStore SHALL 기동 후 5분 경과 시점의 힙 메모리 사용량을 기준으로, 이후 힙 메모리 증가량이 50MB를 초과하지 않는다
5. WHILE 앱이 8시간 연속 실행 중일 때, THE AppStore SHALL 가비지 컬렉션으로 인한 메인 스레드 정지(GC pause)가 1회당 100ms를 초과하지 않는다

---

### Requirement 17: 보고 있는 화면만 데이터 받기 (Page-Aware Data Filtering)

**User Story:** 일반 사용자로서, 현재 보고 있는 페이지에 필요한 데이터만 서버에서 수신하여 프론트엔드 부하와 네트워크 대역폭을 최소화하고 싶다.

**현재 문제 (ws_manager.py _send_realdata_immediate):**
- 모든 연결된 클라이언트에 real-data 틱을 무조건 전송 (페이지 구분 없음)
- 사용자가 수익현황 페이지를 보고 있어도 업종별 종목 시세 데이터가 전송됨
- 프론트엔드에서 렌더링을 생략해도 WS 수신 + JSON 파싱 + Store 갱신 부하 발생

**핵심 원칙:**
- 자동매매 로직(AutoTradeManager in trading.py)은 100% 백엔드에서 실행됨
- 프론트엔드 데이터 전송 필터링은 자동매매에 영향 없음 (ZERO impact)
- 전송 자체를 차단 — 렌더링 생략이 아닌 서버 측 전송 필터링

#### Acceptance Criteria

1. WHEN 프론트엔드 페이지가 mount될 때, THE WSClient SHALL "page-active" WebSocket 메시지를 서버에 전송하며, 메시지에는 해당 페이지의 식별자(sector-analysis, buy-target, sell-position, profit-overview, settings)를 포함한다
2. WHEN 프론트엔드 페이지가 unmount될 때, THE WSClient SHALL "page-inactive" WebSocket 메시지를 서버에 전송하며, 메시지에는 해제되는 페이지의 식별자를 포함한다
3. WHEN "page-active" 메시지를 수신할 때, THE WSManager SHALL 해당 WebSocket 클라이언트의 active_page 상태를 수신된 페이지 식별자로 갱신한다
4. WHILE 클라이언트의 active_page가 "sector-analysis"일 때, THE WSManager SHALL 해당 클라이언트에 현재 sector layout에 포함된 모든 종목의 real-data 틱을 전송하고, sector-scores 이벤트를 전송한다
5. WHILE 클라이언트의 active_page가 "buy-target"일 때, THE WSManager SHALL 해당 클라이언트에 buyTargets 목록에 포함된 종목의 real-data 틱만 전송한다
6. WHILE 클라이언트의 active_page가 "sell-position"일 때, THE WSManager SHALL 해당 클라이언트에 positions 목록에 포함된 종목의 real-data 틱만 전송한다
7. WHILE 클라이언트의 active_page가 "profit-overview"일 때, THE WSManager SHALL 해당 클라이언트에 real-data 틱을 전송하지 않고, account-update 및 sell/buy history 이벤트만 전송한다
8. WHILE 클라이언트의 active_page가 "settings" 또는 미설정 상태일 때, THE WSManager SHALL 해당 클라이언트에 real-data 틱을 전송하지 않는다
9. WHEN 페이지 전환이 발생할 때(page-inactive → page-active 순서), THE WSManager SHALL 새 페이지에 해당하는 데이터를 10ms 이내에 전송 시작한다 (로컬 환경 기준, 서버가 이미 모든 데이터를 계산 완료한 상태)
10. THE WSManager SHALL per-client active_page 상태를 Map<WebSocket, string> 자료구조로 관리하며, 클라이언트 연결 해제(unregister) 시 해당 항목을 제거한다
11. WHILE 프론트엔드 데이터 필터링이 활성화된 상태에서, THE 백엔드(AutoTradeManager, engine_sector_confirm, engine_account_notify) SHALL 모든 업종 재계산, 매수/매도 조건 판단, 주문 실행을 프론트엔드 페이지 상태와 무관하게 정상 수행한다
12. WHEN _send_realdata_immediate가 호출될 때, THE WSManager SHALL 각 클라이언트의 active_page를 확인하여 해당 페이지에 필요한 종목 코드인 경우에만 전송하고, 불필요한 클라이언트에는 전송을 생략한다
13. WHILE 클라이언트의 active_page가 "sector-analysis"일 때, THE WSManager SHALL 왼쪽 업종순위 테이블에는 sector-scores 이벤트(집계된 업종 순위 데이터)만 전송하고, 개별 종목 real-data 틱은 오른쪽 업종별종목실시간시세 테이블용으로만 전송한다
