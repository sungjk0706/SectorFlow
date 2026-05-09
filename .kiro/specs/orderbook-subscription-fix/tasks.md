# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - guard_pass 무시한 구독/해지 발생
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: 업종순위만 변동하고 guard_pass 상태는 동일한 시나리오를 구성하여 불필요한 구독/해지가 발생하는지 확인
  - Test 1: buy_targets 순서만 변경(A,B→B,A), guard_pass 동일 → `_buy_targets_changed()`가 False를 반환해야 하지만 True 반환 (버그)
  - Test 2: guard_pass=False 종목이 포함된 buy_targets로 `_sync_0d_subscriptions()` 호출 → guard_pass=False 종목이 구독되면 안 되지만 구독됨 (버그)
  - Test 3: guard_pass False→True 전환 시 해당 종목만 REG 발생해야 함을 검증
  - Test 4: guard_pass True→False 전환 시 해당 종목만 REMOVE 발생해야 함을 검증
  - isBugCondition: `(prev_codes != new_codes OR prev_guard_pass = new_guard_pass) AND subscription_change_triggered`
  - Expected behavior: guard_pass=True 집합이 변경된 경우에만 delta(REG/REMOVE) 발생
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples: `_buy_targets_changed()`가 종목코드 집합만 비교하여 순위 변동만으로도 True 반환, `_sync_0d_subscriptions()`가 guard_pass=False 종목까지 구독
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - 업종 재계산 및 매수후보 산출 보존
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: 수정 전 코드에서 guard_pass 변경 없는 재계산 이벤트 시 sector_summary_cache 갱신 결과 관찰
  - Observe: 수정 전 코드에서 buy_targets 리스트 산출 결과 관찰
  - Observe: 수정 전 코드에서 이미 구독 중인 종목에 대해 중복 REG 미발생 확인
  - Observe: 수정 전 코드에서 WS 미연결 시 구독/해지 스킵 확인
  - Write property-based test: 임의의 buy_targets 쌍을 생성하여 guard_pass=True 집합이 동일하면 구독 변경이 없음을 검증
  - Write property-based test: 업종 점수 증분 재계산 결과가 구독 로직 변경과 무관하게 동일함을 검증
  - Write property-based test: WS 미연결 시 구독/해지가 항상 스킵됨을 검증
  - Verify tests pass on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Fix for guard_pass 기반 호가잔량 구독/해지 로직 수정

  - [x] 3.1 Implement the fix
    - `_buy_targets_changed()` 함수를 `_get_guard_pass_codes(buy_targets) -> set[str]` 헬퍼로 교체: guard_pass=True인 종목코드 집합만 추출
    - `_flush_sector_recompute_impl()` 내 구독 호출 조건을 guard_pass=True 집합 비교로 변경
    - `_sync_0d_subscriptions()` 내 `new_codes` 산출을 `{bt.stock.code for bt in new_buy_targets if bt.guard_pass}`로 변경
    - `create_task(_sync_0d_subscriptions(...))` 제거 → 동기 직접 호출로 변경 (구독 페이로드 구성은 동기, WS 전송은 fire-and-forget)
    - `_full_recompute()` 내 동일 패턴(`_buy_targets_changed` + `create_task`)도 동일하게 수정
    - _Bug_Condition: isBugCondition(event) where (prev_codes != new_codes OR prev_guard_pass = new_guard_pass) AND subscription_change_triggered_
    - _Expected_Behavior: guard_pass=True 집합이 변경된 경우에만 해당 종목의 REG/REMOVE delta 전송_
    - _Preservation: 업종 점수 증분 재계산, 매수후보 재산출, delta 알림, WS 미연결 스킵 동작 유지_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - guard_pass 상태 변경 시에만 구독/해지 발생
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - 업종 재계산 및 매수후보 산출 보존
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite to confirm no regressions
  - Verify bug condition test (Property 1) passes
  - Verify preservation tests (Property 2) pass
  - Ensure no `create_task` in 체결 경로
  - Ensure 이벤트 기반 (폴링 없음)
  - Ensure Lock 미사용
  - Ask the user if questions arise
