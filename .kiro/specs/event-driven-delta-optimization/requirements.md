# Requirements Document

## Introduction

SectorFlow 실시간 주식 자동매매 앱에서 발견된 15개의 "이벤트 기반, 델타 전용 브로드캐스트, 증분 DOM 업데이트" 원칙 위반 사항을 체계적으로 수정한다. 수정 대상은 백엔드 전체 재계산/전체 브로드캐스트 8건, 프론트엔드 전체 DOM 재렌더링 3건, 프론트엔드 전체 배열 복사 1건이며, 유지 대상 3건(#9, #10, #15)은 제외한다.

작업은 독립적으로 검증 가능한 4개 Phase로 분할하여 다중 세션에 걸쳐 완료한다.

## Glossary

- **Engine**: SectorFlow 백엔드의 실시간 데이터 처리 엔진 (engine_service.py 중심)
- **Delta_Broadcast**: 변경된 항목만 WebSocket으로 전송하는 방식
- **Full_Broadcast**: 전체 목록을 WebSocket으로 전송하는 방식
- **Incremental_DOM**: 변경된 셀/행만 DOM에서 갱신하는 방식
- **Full_Recompute**: 전체 데이터를 처음부터 다시 계산하는 방식
- **Sector_Summary_Cache**: 업종별 점수·순위를 보관하는 인메모리 캐시 (_sector_summary_cache)
- **Pending_Stock_Details**: 종목별 실시간 시세를 보관하는 인메모리 딕셔너리 (_pending_stock_details)
- **Buy_Targets**: 매수후보 종목 목록
- **WS_Manager**: WebSocket 연결 관리 및 브로드캐스트 담당 모듈
- **DataTable**: 프론트엔드 공통 테이블 컴포넌트 (data-table.ts)
- **AppStore**: 프론트엔드 전역 상태 관리 스토어 (Zustand 기반)

## Requirements

### Phase 1: 백엔드 — 캐시 기반 증분 응답 (Priority High)

---

### Requirement 1: get_sector_stocks() 증분 캐시

**User Story:** As a 프론트엔드 클라이언트, I want 업종별 종목 시세를 빠르게 조회하고 싶다, so that 매 호출마다 전체 딕셔너리 복사+정렬 비용이 제거된다.

#### Acceptance Criteria

1. THE Engine SHALL maintain a cached result list for get_sector_stocks() that is rebuilt only when _pending_stock_details membership or _sector_summary_cache ranking changes.
2. WHEN a REAL tick updates a stock's price fields only (cur_price, change, change_rate, strength, trade_amount), THE Engine SHALL NOT rebuild the get_sector_stocks() cache.
3. WHEN a stock is added to or removed from _pending_stock_details, THE Engine SHALL invalidate and rebuild the get_sector_stocks() cache on next access.
4. WHEN _sector_summary_cache ranking order changes, THE Engine SHALL invalidate and rebuild the get_sector_stocks() cache on next access.
5. THE Engine SHALL return the cached list reference directly without copying when the cache is valid.

---

### Requirement 2: get_buy_targets_snapshot() 증분 캐시

**User Story:** As a 프론트엔드 클라이언트, I want 매수후보 목록을 빠르게 조회하고 싶다, so that 매 호출마다 전체 리스트 재구축 비용이 제거된다.

#### Acceptance Criteria

1. THE Engine SHALL maintain a cached buy_targets list that is rebuilt only when _sector_summary_cache.buy_targets reference changes.
2. WHEN _sector_summary_cache is replaced with a new object, THE Engine SHALL rebuild the buy_targets snapshot cache.
3. WHEN _sector_summary_cache has not changed, THE Engine SHALL return the previously cached buy_targets list without rebuilding.

---

### Requirement 3: _full_recompute() 증분 섹터 계산

**User Story:** As a 시스템 운영자, I want 캐시 미스 시에도 가능한 한 증분 계산을 수행하고 싶다, so that 56개 전체 업종 재계산 빈도가 최소화된다.

#### Acceptance Criteria

1. WHEN the __ALL__ flag is set in _dirty_codes AND _sector_summary_cache exists, THE Engine SHALL perform incremental recalculation for all active sectors instead of full recomputation.
2. WHEN _sector_summary_cache is None (cold start), THE Engine SHALL perform full recomputation as fallback.
3. WHEN the cache is missing due to engine restart, THE Engine SHALL perform full recomputation exactly once, then switch to incremental mode for subsequent ticks.

---

### Phase 2: 백엔드 — 델타 전용 브로드캐스트 (Priority High)

---

### Requirement 4: notify_desktop_sector_stocks_refresh() 델타 전송

**User Story:** As a 프론트엔드 클라이언트, I want 필터 변경 시 추가/제거된 종목만 받고 싶다, so that 전체 종목 리스트 재전송이 제거된다.

#### Acceptance Criteria

1. WHEN a filter change occurs, THE Engine SHALL compute the difference between the previous stock code set and the new stock code set.
2. THE Engine SHALL broadcast a "sector-stocks-delta" event containing only added_stocks (full detail) and removed_codes (code list).
3. IF the previous stock code set is empty (initial load), THEN THE Engine SHALL broadcast the full stock list as a "sector-stocks-refresh" event.
4. THE Engine SHALL update _prev_sent_cache to reflect only the stocks in the new filtered set.

---

### Requirement 5: notify_buy_targets_update() 델타 전송

**User Story:** As a 프론트엔드 클라이언트, I want 매수후보 변경 시 변경된 항목만 받고 싶다, so that 1개 종목 변경에도 전체 목록 재전송이 발생하지 않는다.

#### Acceptance Criteria

1. WHEN buy_targets composition changes, THE Engine SHALL compute the delta (added targets, removed codes, changed targets).
2. THE Engine SHALL broadcast a "buy-targets-delta" event containing added, removed, and changed items only.
3. IF _prev_buy_targets_cache is None (initial state), THEN THE Engine SHALL broadcast the full buy_targets list.
4. THE Engine SHALL compare targets using the _BUY_TARGET_CMP_KEYS tuple to determine changes.

---

### Requirement 6: trade_history.py 단건 브로드캐스트

**User Story:** As a 프론트엔드 클라이언트, I want 새 체결 발생 시 해당 건만 받고 싶다, so that 전체 이력 리스트 재전송이 제거된다.

#### Acceptance Criteria

1. WHEN a buy trade is recorded, THE Engine SHALL broadcast a "buy-history-append" event containing only the new trade record.
2. WHEN a sell trade is recorded, THE Engine SHALL broadcast a "sell-history-append" event containing only the new sell record and the updated daily_summary for that date.
3. THE Engine SHALL NOT broadcast the full buy_history or sell_history list on individual trade events.
4. WHEN the frontend connects for the first time (initial-snapshot), THE Engine SHALL send the full history lists.

---

### Requirement 7: notify_desktop_sector_tick() _full_recompute 경로 최적화

**User Story:** As a 시스템 운영자, I want _full_recompute 경로에서도 개별 종목 단위 delta 전송을 사용하고 싶다, so that get_sector_stocks() 전체 복사가 제거된다.

#### Acceptance Criteria

1. WHEN _full_recompute completes, THE Engine SHALL use notify_sector_tick_single() for each dirty code instead of calling notify_desktop_sector_tick() which invokes get_sector_stocks().
2. THE Engine SHALL iterate only over the codes that were in _dirty_codes snapshot, not the entire stock list.
3. IF _dirty_codes contained __ALL__ flag, THEN THE Engine SHALL iterate over all active codes in _pending_stock_details for delta comparison.

---

### Phase 3: 백엔드 — 비이벤트 패턴 제거 (Priority Medium)

---

### Requirement 8: 지수 REST 폴링 최소화

**User Story:** As a 시스템 운영자, I want 0J REAL 미수신 구간에서만 지수 REST 폴링을 수행하고 싶다, so that 불필요한 60초 주기 REST 호출이 제거된다.

#### Acceptance Criteria

1. WHEN the first 0J REAL message is received after WS subscribe start, THE Engine SHALL stop the index poll timer immediately.
2. WHILE 0J REAL messages are being received (KRX regular session 09:00~15:30), THE Engine SHALL NOT perform REST polling for index data.
3. WHEN 0J REAL messages stop (after 15:30 KRX close), THE Engine SHALL restart the index poll timer only if the WS subscribe window is still active.
4. WHEN the WS subscribe window starts before 09:00 (pre-market), THE Engine SHALL start the index poll timer and stop it upon receiving the first 0J REAL message.
5. THE Engine SHALL fetch index data via REST only once per poll interval (60 seconds) during active polling periods.

---

### Phase 4: 프론트엔드 — 증분 DOM 업데이트 (Priority High/Medium)

---

### Requirement 9: profit-overview.ts 증분 테이블 갱신

**User Story:** As a 사용자, I want 수익현황 페이지에서 새 체결 발생 시 테이블이 깜빡이지 않고 자연스럽게 갱신되길 원한다, so that innerHTML 전체 클리어 후 재구축이 제거된다.

#### Acceptance Criteria

1. WHEN a new trade record arrives (buy-history-append or sell-history-append), THE profit-overview page SHALL prepend the new row to the existing table without clearing innerHTML.
2. WHEN the active tab's data changes, THE profit-overview page SHALL use DataTable.updateRows() which performs incremental DOM diffing internally.
3. THE profit-overview page SHALL NOT use innerHTML = '' followed by full table rebuild for showTable() or showDrilldown() operations.
4. WHEN switching between drilldown and table views, THE profit-overview page SHALL toggle CSS display property instead of destroying and recreating DOM elements.

---

### Requirement 10: sector-custom.ts 증분 패널 갱신

**User Story:** As a 사용자, I want 업종분류 커스텀 페이지에서 패널 전환 시 깜빡임 없이 부드럽게 전환되길 원한다, so that innerHTML 전체 클리어가 제거된다.

#### Acceptance Criteria

1. WHEN updating the center panel content, THE sector-custom page SHALL reuse existing DOM elements and update their content instead of clearing innerHTML.
2. WHEN the right panel target sector list changes, THE sector-custom page SHALL add/remove only the changed sector row elements.
3. THE sector-custom page SHALL use CSS display toggle for panel visibility changes instead of innerHTML = '' followed by rebuild.
4. WHEN the page is first mounted (buildTripleLeft, buildTripleCenter, buildTripleRight), THE sector-custom page MAY use innerHTML = '' for initial construction only.

---

### Requirement 11: general-settings.ts 탭 전환 최적화

**User Story:** As a 사용자, I want 일반설정 페이지에서 탭 전환 시 깜빡임 없이 즉시 전환되길 원한다, so that 탭 콘텐츠 전체 파괴 후 재생성이 제거된다.

#### Acceptance Criteria

1. THE general-settings page SHALL pre-render all tab content panels on mount and toggle visibility via CSS display property on tab switch.
2. WHEN a tab is selected, THE general-settings page SHALL hide the current tab panel and show the selected tab panel without destroying DOM elements.
3. THE general-settings page SHALL NOT clear tabContent.innerHTML on tab switch.
4. WHEN settings values change via store subscription, THE general-settings page SHALL update only the values of existing DOM elements in the active tab.

---

### Requirement 12: appStore.ts applyAccountUpdate() 증분 배열 갱신

**User Story:** As a 프론트엔드 상태 관리자, I want 계좌 업데이트 시 변경된 포지션만 교체하고 싶다, so that 전체 positions 배열 .map() 재생성이 제거된다.

#### Acceptance Criteria

1. WHEN an account-update event contains changed_positions, THE AppStore SHALL replace only the changed position objects in the existing array without recreating the entire array.
2. WHEN an account-update event contains removed_codes, THE AppStore SHALL remove only those positions from the array.
3. WHEN no positions have changed (changed_positions is empty AND removed_codes is empty), THE AppStore SHALL NOT create a new positions array reference.
4. THE AppStore SHALL use in-place splice operations or indexed replacement instead of .map() over the entire array.
5. WHEN new positions are added (codes not in existing array), THE AppStore SHALL append them to the existing array.

---

### Requirement 13: 실시간 데이터 상태 관리 — 내부 컨테이너 변경

**User Story:** As a 프론트엔드 개발자, I want 매 틱마다 전체 Map 복사가 발생하지 않도록 하고 싶다, so that 실시간 데이터 갱신 시 불필요한 메모리 할당과 GC 부하가 제거된다.

#### Acceptance Criteria

1. THE Frontend SHALL replace the Map<string, SectorStock> container inside the existing store with a plain JavaScript object (Record<string, SectorStock>).
2. WHEN a real-data tick arrives, THE Frontend SHALL shallow-copy the existing object and replace only the changed stock code's value with the new data object.
3. THE Frontend SHALL NOT use new Map() or full object spread that iterates all keys for each tick — only the changed key is reassigned after shallow copy.
4. THE Frontend SHALL maintain the existing store (Zustand) as-is — only the internal container type and update mechanism change.
5. THE Frontend SHALL maintain backward compatibility with existing page components by providing equivalent read access (bracket notation for single stock, Object.values for full list).

---

## Phase 구분 및 독립 검증 기준

| Phase | 범위 | 검증 기준 |
|-------|------|-----------|
| Phase 1 | Req 1~3 (백엔드 캐시) | get_sector_stocks(), get_buy_targets_snapshot() 호출 시 불필요한 복사/정렬 없음. _full_recompute 호출 빈도 감소 확인 |
| Phase 2 | Req 4~7 (백엔드 델타 브로드캐스트) | WS 메시지 크기 감소. 단일 변경 시 전체 리스트 미전송 확인 |
| Phase 3 | Req 8 (비이벤트 패턴) | 09:00~15:30 구간 REST 폴링 0회 확인 |
| Phase 4 | Req 9~13 (프론트엔드 증분 DOM + 상태 관리) | innerHTML = '' 호출 제거. 탭 전환 시 DOM 재생성 없음. 매 틱 Map/배열 전체 복사 없음 확인 |

## 시간 기반 스케줄러 분석 결과

### 현행 유지 판정

시간 기반 WS 연결/해제 스케줄러는 `call_later` 일회성 타이머로 구현되어 있으며, 폴링 루프가 아닙니다.
- 엔진 기동 시 1회 호출, "현재 시각 → 목표 시각" 남은 초를 계산하여 타이머 등록
- 각 타이머는 단 1회만 실행되고 소멸
- "설정 시각 도달"을 OS/이벤트 루프가 제공하는 이벤트 알림으로 취급 → 이벤트 기반 원칙에 부합

**예외:** 지수 60초 재귀 폴링(`_do_index_poll_tick`)은 원칙 위반이나, 0J REAL 미수신 구간의 유일한 대안이므로 Req 8에서 최소화 처리.
