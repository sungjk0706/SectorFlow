# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Data Consistency Violations (Ineligible Stock Retention)
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the 4 independent bugs exist
  - **Scoped PBT Approach**: Use Hypothesis to generate random eligible/ineligible stock sets and verify:
    - Bug 1 (Cache Stale): `rolling_update_v2_from_trade_amounts(existing_v2_with_ineligible, trade_amounts, eligible_set=eligible)` → assert ineligible stock codes NOT in result `updated_v2` and `updated_high_arr`
    - Bug 2 (High Price): `_apply_confirmed_to_memory()` with `high_price > 0` in confirmed detail → assert `entry["high_price"] == confirmed_detail["high_price"]`
    - Bug 3 (UI Filter): Populate `_pending_stock_details` with ineligible active stocks + non-empty `_eligible_stock_codes` → call `get_all_sector_stocks()` → assert ineligible stocks NOT in result
    - Bug 4 (Memory Reload): After all saves completed, assert `_pending_stock_details` contains only eligible stocks
  - Test file: `backend/tests/test_data_consistency_bug_condition.py`
  - Use `hypothesis` with `@given` strategies for stock codes (6-digit strings), trade amounts (positive ints), v2 arrays (lists of 1-5 positive ints)
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bugs exist)
  - Document counterexamples found (e.g., "rolling_update_v2 retains ineligible stock '999999' in result")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Eligible Stock Behavior Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe on UNFIXED code:
    - `rolling_update_v2_from_trade_amounts({"005930": [100, 200, 300, 400, 500]}, {"005930": 600_000_000})` → result["005930"] == [200, 300, 400, 500, 600]
    - `rolling_update_v2_from_trade_amounts(None, {"NEW001": 50_000_000})` → result["NEW001"] == [50]
    - `_apply_confirmed_to_memory()` with `cur_price=51000, change=1000, trade_amount=5000000000` → entry fields stored correctly
    - `get_all_sector_stocks()` with empty `_eligible_stock_codes` → returns all active stocks
  - Write property-based tests (Hypothesis) capturing observed behavior:
    - **Preservation A**: For all eligible stocks in `existing_v2`, rolling update produces same shift+append result regardless of `eligible_set` parameter presence
    - **Preservation B**: For all confirmed details, `cur_price`, `change`, `change_rate`, `sign`, `trade_amount` fields are stored identically before and after fix
    - **Preservation C**: When `_eligible_stock_codes` is empty, `get_all_sector_stocks()` returns all active stocks (backward compatibility)
    - **Preservation D**: For eligible stocks, atomic memory swap preserves entry data without modification
  - Test file: `backend/tests/test_data_consistency_preservation.py`
  - Verify tests PASS on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

- [x] 3. Fix for data consistency — ineligible stock retention across cache/memory/UI

  - [x] 3.1 Add `eligible_set` parameter to `rolling_update_v2_from_trade_amounts()` + filter logic
    - File: `backend/app/core/avg_amt_cache.py`
    - Add keyword parameter: `eligible_set: set[str] | None = None`
    - In trade amount rolling loop (existing stocks): `if eligible_set is not None and code not in eligible_set: continue`
    - In trade amount rolling loop (new stocks): `if eligible_set is not None and code not in eligible_set: continue`
    - In high price rolling loop (existing stocks): `if eligible_set is not None and code not in eligible_set: continue`
    - In high price rolling loop (new stocks): `if eligible_set is not None and code not in eligible_set: continue`
    - When `eligible_set is None` → no filtering (backward compatibility)
    - _Bug_Condition: isBugCondition_CacheStale(input) where stock_code IN existing_v2 AND stock_code NOT IN eligible_set_
    - _Expected_Behavior: result.updated_v2 contains ONLY stocks in eligible_set (when provided)_
    - _Preservation: eligible stocks produce identical rolling results with or without eligible_set_
    - _Requirements: 2.1, 3.1, 3.5_

  - [x] 3.2 Add `high_price` storage to `_apply_confirmed_to_memory()`
    - File: `backend/app/services/market_close_pipeline.py`
    - After the `trade_amount` block, add:
      ```python
      # high_price
      hp = int(detail.get("high_price") or 0)
      if hp > 0:
          entry["high_price"] = hp
      ```
    - _Bug_Condition: isBugCondition_HighPrice(input) where int(confirmed_detail.get("high_price") or 0) > 0_
    - _Expected_Behavior: entry["high_price"] == confirmed_detail["high_price"]_
    - _Preservation: cur_price, change, change_rate, sign, trade_amount fields stored identically_
    - _Requirements: 2.2, 3.2, 3.4_

  - [x] 3.3 Pass `eligible_set` to `rolling_update_v2_from_trade_amounts()` in `_run_post_confirmed_pipeline()`
    - File: `backend/app/services/market_close_pipeline.py`
    - Convert `elig` dict keys to set: `eligible_codes = set(elig.keys()) if elig else None`
    - Pass to rolling update call: `eligible_set=eligible_codes`
    - _Bug_Condition: isBugCondition_CacheStale — ensures rolling update filters ineligible stocks_
    - _Expected_Behavior: v2 cache after rolling contains only eligible stocks_
    - _Preservation: eligible stock rolling results unchanged_
    - _Requirements: 2.1, 3.1_

  - [x] 3.4 Add complete mapping step (Step 6) + atomic memory swap (Step 7) to `fetch_unified_confirmed_data()`
    - File: `backend/app/services/market_close_pipeline.py`
    - After `_run_post_confirmed_pipeline()` completes and before 업종순위 재계산:
    - Step 6: Build `mapped_pending` from `final_eligible` × `_pending_stock_details` (only eligible stocks with entry data)
    - Step 6: Filter `_avg_amt_5d` and `_high_5d_cache` to eligible-only
    - Step 7: Under `es._shared_lock`, atomically clear+update `_pending_stock_details`, `_avg_amt_5d`, `_high_5d_cache`, and filter `_radar_cnsr_order`
    - _Bug_Condition: isBugCondition_MemoryReload — all_saves_completed AND ineligible stock active in pending_
    - _Expected_Behavior: after atomic swap, _pending_stock_details contains only eligible active stocks_
    - _Preservation: eligible stock entry data preserved without modification during swap_
    - _Requirements: 2.4, 2.5, 2.6, 3.6, 3.7_

  - [x] 3.5 Add error handling for partial failure — skip memory swap when `cached == False`
    - File: `backend/app/services/market_close_pipeline.py`
    - Wrap Step 6+7 in condition: only execute if `cached` is truthy (meaning `_save_confirmed_cache()` succeeded)
    - If `cached == False`, log warning and skip atomic swap (preserve existing memory state)
    - _Bug_Condition: partial failure scenario — one or more saves failed_
    - _Expected_Behavior: memory swap NOT performed, existing state maintained, error logged_
    - _Requirements: 2.5_

  - [x] 3.6 Add eligible filter to `get_all_sector_stocks()`
    - File: `backend/app/services/engine_service.py`
    - Import `app.core.industry_map` and reference `_eligible_stock_codes`
    - After `status != "active"` check, add: `if elig and cd not in elig: continue`
    - When `_eligible_stock_codes` is empty → no filtering (backward compatibility)
    - _Bug_Condition: isBugCondition_UIFilter — stock active in pending but NOT in eligible_set (non-empty)_
    - _Expected_Behavior: get_all_sector_stocks() returns only eligible active stocks_
    - _Preservation: when eligible_set empty, returns all active stocks (backward compatible)_
    - _Requirements: 2.3, 3.3_

  - [x] 3.7 Add complete mapping step + atomic memory swap on user-triggered path in `_refresh_avg_amt_5d_cache_inner()`
    - File: `backend/app/services/engine_bootstrap.py`
    - Verify `all_codes` is already constructed from `get_eligible_stocks()` (적격 종목만)
    - After `save_avg_amt_cache_v2()` and before 업종순위 재계산, add complete mapping step:
      - 적격 종목 × 시세 확인: `_pending_stock_details`에 해당 종목 entry 존재 확인
      - 적격 종목 × 5일데이터 매핑: `avg_map` + `high_cache`에서 적격 종목만 추출
      - 적격 종목 × 업종명 매핑: `get_merged_sector(cd)`로 업종 매핑 보강
      - 3가지 모두 매핑된 종목만 최종 확정
    - Atomic memory swap: `_avg_amt_5d`, `_high_5d_cache` 적격 기준으로 교체 + `_pending_stock_details`에서 부적격 종목 제거
    - Ensure no ineligible stocks leak into memory via this path
    - _Bug_Condition: user-triggered refresh could introduce ineligible stocks if not filtered_
    - _Expected_Behavior: only eligible stocks in memory after user-triggered refresh, with complete mapping (시세+5일데이터+업종)_
    - _Preservation: eligible stock data unchanged_
    - _Requirements: 2.1, 2.4_

  - [x] 3.8 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Data Consistency Violations Fixed
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms all 4 bugs are fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.9 Verify preservation tests still pass
    - **Property 2: Preservation** - Eligible Stock Behavior Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `pytest backend/tests/test_data_consistency_bug_condition.py backend/tests/test_data_consistency_preservation.py -v`
  - Verify Property 1 (Bug Condition) tests PASS on fixed code
  - Verify Property 2 (Preservation) tests PASS on fixed code
  - Verify no other existing tests are broken by the changes
  - Ensure mandatory ordering constraint is enforced: ka10099 → filter → eligible save → ka10086 (eligible only) → save (eligible only) → memory swap (eligible only)
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Integration & smoke tests (3개)
  - Test file: `backend/tests/test_data_consistency_integration.py`

  - [x] 5.1 통합 테스트: 적격 종목만 UI에 보이는가
    - 파이프라인 전체 흐름 시뮬레이션: eligible 1484종목 + ineligible 41종목을 `_pending_stock_details`에 세팅
    - `_eligible_stock_codes`에 1484종목만 설정
    - `fetch_unified_confirmed_data()` 완료 후 (또는 동등한 원자적 교체 수행 후):
      - `get_all_sector_stocks()` 반환값이 정확히 eligible 종목만 포함하는지 검증
      - `_avg_amt_5d` 키가 eligible 종목만 포함하는지 검증
      - `_high_5d_cache` 키가 eligible 종목만 포함하는지 검증
    - **이 테스트 1개로 Bug 1(캐시 잔존), Bug 3(UI 필터), Bug 4(메모리 교체) 동시 검증**
    - _Requirements: 2.1, 2.3, 2.4_

  - [x] 5.2 스모크 테스트: 기존 적격 종목 동작 그대로인가
    - 적격 종목 세트로 파이프라인 수행 후:
      - 적격 종목의 `cur_price`, `change_rate`, `trade_amount` 값이 보존되는지 확인
      - 적격 종목의 5일 평균 거래대금 계산 결과가 수정 전과 동일한지 확인
      - 업종 점수 계산(`compute_full_sector_summary`)에 적격 종목이 정상 포함되는지 확인
    - **핵심 로직(매수 조건, 업종 점수) 회귀 방지**
    - _Requirements: 3.1, 3.2, 3.6_

  - [x] 5.3 통합 테스트: 수동 새로고침 후에도 동일한가
    - 자동 경로(`fetch_unified_confirmed_data`) 완료 후 메모리 상태 스냅샷 저장
    - 수동 경로(`_refresh_avg_amt_5d_cache_inner`) 실행 후 메모리 상태 비교:
      - `_avg_amt_5d` 키 집합이 동일한지 (적격 종목만)
      - `_high_5d_cache` 키 집합이 동일한지 (적격 종목만)
      - `_pending_stock_details` 키 집합이 동일한지 (적격 종목만)
    - **두 경로의 최종 결과 정합성 보장**
    - _Requirements: 2.1, 2.4_
