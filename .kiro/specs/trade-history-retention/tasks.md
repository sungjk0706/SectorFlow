# Implementation Plan: Trade History Retention

## Overview

체결 이력 파일(`trade_history.json`)의 무한 증가를 방지하기 위해 모드별 보관 기한을 적용하는 자동 트림 메커니즘을 구현한다. 백엔드에서 `_trim_expired()` 함수를 추가하고 저장/로드 시점에 적용하며, 프론트엔드에서 보관 범위 라벨을 표시한다.

## Tasks

- [x] 1. Add retention constants and implement `_trim_expired()` function
  - [x] 1.1 Add module-level constants `RETENTION_TRADING_DAYS_TEST = 60` and `RETENTION_TRADING_DAYS_REAL = 5` to `backend/app/services/trade_history.py`
    - Define constants at the top of the module after existing imports/constants
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 Implement `_compute_retained_dates(records: list[dict]) -> dict[str, set[str]]` helper function
    - Collect unique `date` values per `trade_mode` from the records
    - Treat missing `trade_mode` as `"test"` (레거시 데이터는 테스트모드로 간주)
    - Sort each mode's dates descending and keep only the most recent N (60 for test, 5 for real)
    - Return `{mode: set_of_retained_dates}` — 보관 규칙 변경 시 이 함수만 수정
    - _Requirements: 1.3, 1.4, 2.3_

  - [x] 1.3 Implement `_trim_expired(records: list[dict]) -> list[dict]` function
    - Call `_compute_retained_dates(records)` to get retained date sets per mode
    - Remove records with missing/invalid `date` field
    - Keep records whose `date` is in their mode's retained date set
    - If a mode has no records (empty retained set), do not delete any records for that mode
    - Preserve original chronological order of remaining records
    - Return a new list (do not mutate input)
    - _Requirements: 2.1, 2.2, 2.4, 2.6, 5.1, 5.2, 5.3, 5.4_

  - [ ]* 1.4 Write property test: Mode-specific trim correctness
    - **Property 1: Mode-specific trim correctness**
    - **Validates: Requirements 1.3, 1.4, 2.1, 2.2, 2.3, 5.1, 5.2**
    - Test file: `backend/tests/test_trade_history_retention_properties.py`
    - Use hypothesis to generate records with varying dates and trade modes
    - Assert unique dates per mode ≤ limit after trim, all recent-N records preserved, all older records removed

  - [ ]* 1.5 Write property test: Mode isolation
    - **Property 2: Mode isolation**
    - **Validates: Requirements 2.6**
    - Test file: `backend/tests/test_trade_history_retention_properties.py`
    - Generate mixed test/real records, verify trimming one mode does not affect the other

  - [ ]* 1.6 Write property test: Chronological order invariant
    - **Property 3: Chronological order invariant**
    - **Validates: Requirements 5.3**
    - Test file: `backend/tests/test_trade_history_retention_properties.py`
    - Generate chronologically ordered records, verify order is preserved after trim

- [x] 2. Integrate trim into save and load paths
  - [x] 2.1 Modify `_coalesced_save()` to apply `_trim_expired()` before saving
    - Apply trim to shallow copies of `_buy_history` and `_sell_history`
    - Replace in-memory lists with trimmed results (using slice assignment `[:]`)
    - Pass trimmed copies to `_save_to_file()`
    - _Requirements: 2.1, 2.2, 2.5_

  - [x] 2.2 Modify `_ensure_loaded()` to apply `_trim_expired()` after loading
    - Apply trim after `_load_from_file()` and `_patch_sell_history()`
    - If any records were removed, call `_schedule_save()` to persist trimmed result
    - Log the number of removed records
    - _Requirements: 3.1, 3.2_

  - [ ]* 2.3 Write property test: Save-load round-trip
    - **Property 4: Save-load round-trip**
    - **Validates: Requirements 2.5, 5.5**
    - Test file: `backend/tests/test_trade_history_retention_properties.py`
    - Generate valid records within retention window, save then load, verify equivalence

  - [ ]* 2.4 Write property test: Trim on load removes expired records
    - **Property 5: Trim on load removes expired records**
    - **Validates: Requirements 3.1, 3.2**
    - Test file: `backend/tests/test_trade_history_retention_properties.py`
    - Generate records with more unique dates than retention limit, write to file, load, verify expired records absent

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Add retention indicator to profit-overview page
  - [x] 4.1 Add retention indicator `<span>` to the summary cards area in `frontend/src/pages/profit-overview.ts`
    - Create an inline `<span>` element with subdued style (fontSize: 11px, color: #999)
    - Set text based on current trade_mode: "최근 60거래일 데이터" for test, "최근 5거래일 데이터" for real
    - Insert into `summaryRow` before the first child card
    - _Requirements: 4.1, 4.2, 4.4, 4.5, 4.6_

  - [x] 4.2 Update retention indicator text on trade mode change
    - In the existing `appStore.subscribe()` callback, update `retentionLabel.textContent` when `tradeModeChanged` is true
    - _Requirements: 4.3_

- [x] 5. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Property tests use `hypothesis` library (already available in the project)
- `_compute_retained_dates()` — 보관할 날짜 목록 계산만 담당하는 보조 함수 (보관 규칙 변경 시 이 함수만 수정)
- `_trim_expired()` — `_compute_retained_dates()` 결과를 받아 필터링만 수행하는 순수 함수
- 외부 캘린더 의존 없음 — 저장된 레코드의 고유 날짜만 사용
- The frontend change is minimal: a single `<span>` element with CSS display toggle on mode change
- All property tests: `backend/tests/test_trade_history_retention_properties.py`
