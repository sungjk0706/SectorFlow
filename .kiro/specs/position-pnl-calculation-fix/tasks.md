# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - Position PnL not recalculated on cur_price change
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: For any position with `buy_amt > 0` and `qty > 0`, when a real-data event changes `cur_price`, the resulting `eval_amount`, `pnl_amount`, `pnl_rate` must be recalculated
  - Create test file `frontend/src/stores/applyRealData.test.ts`
  - Use `fast-check` to generate: positions with varying `stk_cd`, `qty`, `buy_amt`, `cur_price`; and RealDataEvents with type '01'/'0B'/'0H' and a different price in `values['10']`
  - Bug Condition from design: `X.type IN {'01','0B','0H'} AND X.code IN positions AND parsePrice(X.values['10']) != pos.cur_price`
  - Assert after `applyRealData`: `pos.eval_amount === newPrice * qty`, `pos.pnl_amount === evalAmount - buyAmt`, `pos.pnl_rate === Math.round((pnlAmount / buyAmt) * 10000) / 100`
  - Run test on UNFIXED code with `cd frontend && npx vitest --run src/stores/applyRealData.test.ts`
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists because `applyRealData` only sets `cur_price` without recalculating PnL)
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 2.1_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-position stocks and unchanged prices preserve state
  - **IMPORTANT**: Follow observation-first methodology
  - Observe: when `real-data` event arrives for a code NOT in positions, `positions` array reference is unchanged
  - Observe: when `real-data` event arrives with same price as `pos.cur_price`, `positions` array reference is unchanged
  - Observe: `sectorStocks` and `buyTargets` continue to update normally for non-position codes
  - Write property-based test with `fast-check`: generate RealDataEvents where code is NOT in positions OR price equals current `cur_price`
  - Assert: `state.positions` reference identity is preserved (no unnecessary re-render)
  - Also test edge case: position with `buy_amt = 0` or `qty = 0` does not cause division-by-zero
  - Run tests on UNFIXED code with `cd frontend && npx vitest --run src/stores/applyRealData.test.ts`
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Fix for position PnL not recalculated on real-time price update

  - [x] 3.1 Add `buy_amount` field to Position interface
    - In `frontend/src/types/index.ts`, add `buy_amount?: number` to the Position interface
    - This maps the backend field name for compatibility
    - _Requirements: 1.3, 2.3_

  - [x] 3.2 Implement PnL recalculation in `applyRealData`
    - In `frontend/src/stores/appStore.ts`, replace the position update block:
    - From: `positions[posIdx] = { ...pos, cur_price: price };`
    - To: calculate `buyAmt = pos.buy_amt ?? (pos as any).buy_amount ?? 0`, `qty = pos.qty ?? 0`, `evalAmount = price * qty`, `pnlAmount = buyAmt > 0 ? evalAmount - buyAmt : 0`, `pnlRate = buyAmt > 0 ? Math.round((pnlAmount / buyAmt) * 10000) / 100 : 0`
    - Then: `positions[posIdx] = { ...pos, cur_price: price, eval_amount: evalAmount, pnl_amount: pnlAmount, pnl_rate: pnlRate };`
    - _Bug_Condition: isBugCondition(X) where X.type IN {'01','0B','0H'} AND X.code matches a position AND price differs_
    - _Expected_Behavior: eval_amount = price * qty, pnl_amount = evalAmount - buyAmt, pnl_rate = round((pnlAmount/buyAmt)*100, 2)_
    - _Preservation: Non-position codes and unchanged prices do not trigger recalculation_
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.3, 3.4_

  - [x] 3.3 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Position PnL recalculated correctly
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test: `cd frontend && npx vitest --run src/stores/applyRealData.test.ts`
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2_

  - [x] 3.4 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-position stocks and unchanged prices preserve state
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests: `cd frontend && npx vitest --run src/stores/applyRealData.test.ts`
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `cd frontend && npx vitest --run`
  - Ensure all tests pass, ask the user if questions arise.
