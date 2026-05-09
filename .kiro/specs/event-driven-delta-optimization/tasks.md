# Implementation Plan: Event-Driven Delta Optimization

## Overview

SectorFlow 실시간 데이터 파이프라인을 4개 Phase로 최적화한다. 백엔드는 Python(FastAPI + asyncio), 프론트엔드는 TypeScript로 구현한다. 각 Phase는 독립적으로 검증 가능하며, 이벤트 기반·델타 전송·증분 갱신 원칙을 완전히 준수한다.

## Tasks

- [x] 1. Phase 1: 백엔드 캐시 기반 증분 응답
  - [x] 1.1 Implement get_sector_stocks() incremental cache in engine_service.py
    - Add module-level `_sector_stocks_cache: list | None` and `_sector_stocks_dirty: bool` flag
    - Implement cache invalidation triggers: stock added/removed from `_pending_stock_details`, `_sector_summary_cache` reference change, `_filtered_sector_codes` change
    - Implement cache rebuild on access when dirty (filter + sort once, store reference-sharing list)
    - Ensure REAL tick price-only updates do NOT invalidate cache (shared dict references)
    - Return cached list reference directly without copying when valid
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

  - [ ]* 1.2 Write property test for sector_stocks cache correctness
    - **Property 1: Cache equivalence — cached result equals full recomputation**
    - **Validates: Requirements 1.1, 1.5**
    - Generate random sequences of tick updates and membership changes
    - Assert cached result always matches fresh computation

  - [x] 1.3 Implement get_buy_targets_snapshot() incremental cache in engine_service.py
    - Add `_buy_targets_snapshot_cache: list | None` and `_buy_targets_cache_ref: object | None`
    - Implement identity check: `_sector_summary_cache is _buy_targets_cache_ref`
    - Return cached list when reference unchanged, rebuild on reference change
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 1.4 Write property test for buy_targets cache correctness
    - **Property 2: Cache identity — cache returns same result until reference changes**
    - **Validates: Requirements 2.1, 2.2, 2.3**
    - Generate random cache reference swaps and verify rebuild triggers correctly

  - [x] 1.5 Implement _full_recompute() incremental sector calculation in engine_service.py
    - When `__ALL__` flag set AND `_sector_summary_cache` exists: iterate all active codes as dirty, recompute affected sectors only, merge into existing cache
    - When `_sector_summary_cache` is None (cold start): call `compute_full_sector_summary()` once as fallback
    - After cold start full recompute, switch to incremental mode for all subsequent ticks
    - _Requirements: 3.1, 3.2, 3.3_

  - [ ]* 1.6 Write property test for incremental recompute equivalence
    - **Property 3: Incremental equivalence — incremental recompute produces same result as full recompute**
    - **Validates: Requirements 3.1, 3.2**
    - Generate random dirty code sets, compare incremental vs full recompute outputs

- [x] 2. Checkpoint — Phase 1 완료 검증
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: get_sector_stocks() and get_buy_targets_snapshot() return cached references without copy/sort on repeated calls
  - Verify: _full_recompute with __ALL__ flag uses incremental path when cache exists

- [x] 3. Phase 2: 백엔드 델타 전용 브로드캐스트
  - [x] 3.1 Implement sector-stocks-delta broadcast in engine_account_notify.py
    - Add `_prev_sector_stock_codes: set[str]` to track previously sent stock codes
    - On filter change: compute `added = new_codes - prev_codes`, `removed = prev_codes - new_codes`
    - Broadcast `"sector-stocks-delta"` with added stocks (full detail) and removed codes (code list)
    - On initial load (prev set empty): broadcast full list as `"sector-stocks-refresh"`
    - Update `_prev_sector_stock_codes` after each broadcast
    - _Requirements: 4.1, 4.2, 4.3, 4.4_

  - [ ]* 3.2 Write property test for sector-stocks delta correctness
    - **Property 4: Delta reconstruction — applying delta to previous state yields new state**
    - **Validates: Requirements 4.1, 4.2**
    - Generate random previous/new stock code sets, verify delta application reconstructs new set

  - [x] 3.3 Implement buy-targets-delta broadcast in engine_account_notify.py
    - Add `_prev_buy_targets_map: dict[str, dict]` for previous target state
    - Define `_BUY_TARGET_CMP_KEYS` tuple for field comparison
    - Compute added (new codes), removed (gone codes), changed (same code, different fields)
    - Broadcast `"buy-targets-delta"` with `{"added": [...], "removed": [...], "changed": [...]}`
    - On initial state (cache None): broadcast full list
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 3.4 Write property test for buy-targets delta correctness
    - **Property 5: Buy-targets delta reconstruction — applying delta to previous map yields new map**
    - **Validates: Requirements 5.1, 5.2, 5.4**
    - Generate random target maps with field variations, verify delta correctness

  - [x] 3.5 Implement single-record trade history broadcast in trade_history.py
    - On buy trade: broadcast `"buy-history-append"` with `{"trade": {new_record}}`
    - On sell trade: broadcast `"sell-history-append"` with `{"trade": {new_record}, "daily_summary": {...}}`
    - Remove full list broadcast on individual trade events
    - Keep full list broadcast only for initial-snapshot
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [ ]* 3.6 Write unit tests for trade history single-record broadcast
    - Test buy trade emits buy-history-append with single record
    - Test sell trade emits sell-history-append with record and daily_summary
    - Test initial-snapshot still sends full lists
    - _Requirements: 6.1, 6.2, 6.4_

  - [x] 3.7 Implement _full_recompute path delta notification in engine_sector_confirm.py
    - After _full_recompute completes: use `notify_sector_tick_single()` for each dirty code
    - Iterate only codes in `_dirty_codes` snapshot (not entire stock list)
    - When `__ALL__` flag present: iterate all active codes in `_pending_stock_details`
    - Remove `notify_desktop_sector_tick()` → `get_sector_stocks()` full-copy path
    - _Requirements: 7.1, 7.2, 7.3_

  - [ ]* 3.8 Write property test for full_recompute delta notification
    - **Property 6: Dirty-code coverage — every dirty code receives exactly one notify_sector_tick_single call**
    - **Validates: Requirements 7.1, 7.2**
    - Generate random dirty_codes sets, verify each code notified exactly once

- [x] 4. Checkpoint — Phase 2 완료 검증
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: single stock change produces delta message (not full list)
  - Verify: WS message payload size reduced for single-item changes

- [x] 5. Phase 3: 비이벤트 패턴 제거 — 지수 REST 폴링 최소화
  - [x] 5.1 Implement 0J REAL-driven poll control in daily_time_scheduler.py / engine_ws_dispatch.py
    - Add `_0j_real_receiving: bool = False` flag
    - On first 0J REAL message received: set flag True, cancel index poll timer immediately
    - Remove fixed 09:00/15:30 timer-based poll start/stop
    - Poll start condition: WS subscribe window active AND `_0j_real_receiving == False`
    - Poll stop condition: first 0J REAL message received
    - On WS subscribe end: stop poll timer
    - On engine start within WS window: start poll → auto-stop on 0J REAL arrival
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

  - [ ]* 5.2 Write unit tests for index poll lifecycle
    - Test poll starts when WS window active and no 0J REAL
    - Test poll stops immediately on first 0J REAL
    - Test poll restarts after 15:30 if WS window still active and 0J stops
    - Test poll does not run during 09:00-15:30 when 0J active
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [x] 6. Checkpoint — Phase 3 완료 검증
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: during 09:00~15:30 with 0J REAL active, REST poll count is 0

- [x] 7. Phase 4: 프론트엔드 증분 DOM 및 상태 관리
  - [x] 7.1 Implement incremental table update in profit-overview.ts
    - On `buy-history-append` / `sell-history-append`: prepend new row to existing table (no innerHTML clear)
    - Use `DataTable.updateRows()` for incremental DOM diffing on tab data changes
    - Replace `innerHTML = ''` + full rebuild with CSS display toggle for view switching (table↔drilldown)
    - Pre-create both containers on mount, toggle visibility
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

  - [ ]* 7.2 Write unit tests for profit-overview incremental updates
    - Test new trade row prepended without innerHTML clear
    - Test view toggle uses CSS display, not DOM destruction
    - _Requirements: 9.1, 9.4_

  - [x] 7.3 Implement incremental panel update in sector-custom.ts
    - Reuse existing DOM elements on center panel update (update textContent/value only)
    - Add/remove only changed sector row elements in right panel
    - Use CSS display toggle for panel visibility (not innerHTML clear)
    - Allow innerHTML only for initial mount (buildTripleLeft/Center/Right)
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [x] 7.4 Implement tab pre-rendering in general-settings.ts
    - Pre-render all tab content panels on mount (display: none)
    - Tab switch: hide current panel, show selected panel via CSS display
    - Remove `tabContent.innerHTML = ''` on tab switch
    - Settings value changes: update existing DOM element values only (no DOM recreation)
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

  - [x] 7.5 Implement incremental array update in appStore.ts applyAccountUpdate()
    - `changed_positions`: find by stk_cd index, splice-replace existing or push new
    - `removed_codes`: reverse-index splice removal
    - No change (both empty): skip setState, keep array reference
    - Replace `.map()` full array recreation with in-place operations
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

  - [ ]* 7.6 Write property test for applyAccountUpdate incremental correctness
    - **Property 7: Array update equivalence — incremental splice produces same result as full rebuild**
    - **Validates: Requirements 12.1, 12.2, 12.5**
    - Generate random position arrays and change/remove operations, compare incremental vs full rebuild

  - [x] 7.7 Change store internal container from Map to plain object
    - Replace the Map-based container for real-time stock data with a plain object (Record<string, SectorStock>)
    - Keys are stock codes, values are the stock data objects
    - Store itself (Zustand) remains unchanged — only the internal data structure changes
    - _Requirements: 13.1, 13.4_

  - [x] 7.8 Implement shallow-copy + single-key replacement update logic
    - On real-time tick arrival: shallow-copy the existing object, then replace only the changed stock code's value with the new data object
    - This preserves immutability (new top-level reference) while avoiding full collection rebuild
    - Do NOT create a new object from scratch or iterate all keys — only the changed key is reassigned
    - _Requirements: 13.2, 13.4_

  - [ ]* 7.9 Write property test for store update correctness
    - **Property 8: Single-key update — after update, only the target key's value differs from previous state; all other keys reference the same objects**
    - **Validates: Requirements 13.2, 13.4**
    - Generate random stock collections and single-key updates, verify unchanged keys retain reference identity

  - [x] 7.10 Migrate data read patterns across pages (sequential, page-by-page)
    - Convert all stock data reads from Map `.get(code)` to plain object bracket access `obj[code]`
    - Convert all full-list reads from `Map.values()` / spread to `Object.values(obj)`
    - Proceed page by page: verify each page works correctly before moving to the next
    - _Requirements: 13.5_

  - [x] 7.11 Remove residual Map-related code
    - After all pages are confirmed working with the new object-based access pattern, remove Map type declarations, Map construction, and any Map-specific utility code
    - Ensure no `new Map()` or `Map<string, ...>` references remain for real-time stock data
    - _Requirements: 13.1, 13.4_

  - [x] 7.12 Wire frontend delta event handlers in binding.ts
    - Handle `"sector-stocks-delta"` event: apply added/removed to local state
    - Handle `"buy-targets-delta"` event: apply added/removed/changed to store
    - Handle `"buy-history-append"` event: prepend to buy history array
    - Handle `"sell-history-append"` event: prepend to sell history array
    - Maintain backward compatibility with initial-snapshot full list events
    - _Requirements: 4.2, 5.2, 6.1, 6.2, 9.1_

- [x] 8. Final checkpoint — 전체 Phase 완료 검증
  - Ensure all tests pass, ask the user if questions arise.
  - Verify: no innerHTML = '' calls remain (except initial mount)
  - Verify: no full Map/array copy on each tick
  - Verify: tab switch uses CSS display toggle without DOM destruction

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation per phase
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- Backend: Python (FastAPI + asyncio), Frontend: TypeScript
- All implementations must follow event-driven architecture (no polling, no asyncio.create_task in tick path)
- Single-thread model: no locks in real-time tick processing path
