# Implementation Plan: Test Mode Cash Settlement

## Overview

Settlement Engine 모듈을 신규 생성하고, 기존 `dry_run.py`의 예수금 로직을 대체하여 D+2 정산 시뮬레이션을 구현한다. 백엔드(Python)와 프론트엔드(TypeScript) 양쪽을 수정하며, 각 단계는 이전 단계 위에 증분적으로 구축된다.

## Tasks

- [x] 1. Create Settlement Engine core module
  - [x] 1.1 Create `backend/app/services/settlement_engine.py` with state variables and data model
    - Define `PendingWithdrawal` dataclass with fields: `sell_date`, `stk_cd`, `stk_nm`, `amount`, `settlement_date`
    - Define module-level state: `_available_cash`, `_pending_withdrawals`, `_timer_handles`, `_loaded`, `_initial_deposit`
    - Define constants: `BUY_COMMISSION = 0.00015`, `SELL_COMMISSION = 0.00015`, `SECURITIES_TAX = 0.002`
    - Define persistence path: `backend/data/settlement_state.json`
    - _Requirements: 1.1, 1.4, 2.1, 2.2_

  - [x] 1.2 Implement `init()`, `get_available_cash()`, `get_withdrawable_cash()`, `get_pending_withdrawal_total()`, `get_pending_withdrawals()`
    - `init(initial_deposit)`: set `_available_cash = initial_deposit`, clear pending list
    - `get_withdrawable_cash()`: return `_available_cash - sum(pw.amount for pw in _pending_withdrawals)`
    - `get_pending_withdrawals()`: return list of dicts with sell_date, stk_cd, stk_nm, amount, settlement_date
    - _Requirements: 1.1, 2.3, 6.1, 6.5_

  - [x] 1.3 Implement `on_buy_fill(price, qty)` and `check_buy_power(order_amount)`
    - `on_buy_fill`: calculate cost = price×qty + round(price×qty×0.00015), deduct from `_available_cash`, persist, broadcast delta
    - `check_buy_power`: return `(False, reason)` if cost > available_cash
    - Ensure `_available_cash` never goes negative (integer arithmetic)
    - _Requirements: 1.2, 1.3, 1.4, 3.1, 3.2_

  - [x] 1.4 Implement `on_sell_fill(price, qty, stk_cd, stk_nm)` with D+2 scheduling
    - Calculate net_proceeds = price×qty - round(price×qty×0.002) - round(price×qty×0.00015)
    - Add net_proceeds to `_available_cash`
    - Create PendingWithdrawal with settlement_date from `_calc_settlement_date()`
    - Call `_schedule_settlement(pw)` to set up call_later timer
    - Persist state and broadcast delta
    - _Requirements: 2.1, 2.2, 2.5, 2.6_

  - [x] 1.5 Implement `_calc_settlement_date(sell_date)` and `_seconds_until_settlement(settlement_date)`
    - Use `trading_calendar._next_business_date()` called twice for D+2
    - `_seconds_until_settlement`: calculate seconds from now until settlement_date 09:00 KST
    - _Requirements: 4.1, 4.2, 4.3_

  - [x] 1.6 Implement `_schedule_settlement(pw)` and `_settle(pw)`
    - `_schedule_settlement`: use `asyncio.get_running_loop().call_later(seconds, callback)` one-shot timer
    - `_settle`: remove pw from `_pending_withdrawals`, cancel timer handle, persist, broadcast delta
    - Handle RuntimeError (no event loop) gracefully
    - _Requirements: 2.4, 2.6_

  - [x] 1.7 Implement `_persist()` and `_load()` for file-based state persistence
    - `_persist`: write `{available_cash, pending_withdrawals, initial_deposit}` to settlement_state.json
    - `_load`: read from file, restore state, remove expired entries (settlement_date <= today), reschedule active timers
    - Handle file not found / corrupt gracefully (init with default deposit)
    - _Requirements: 2.7, 7.3_

  - [x] 1.8 Implement `charge(amount)`, `withdraw(amount)`, `get_effective_buy_power(daily_limit, daily_spent)`
    - `charge`: add amount to `_available_cash`, persist, broadcast, return new balance
    - `withdraw`: check amount <= withdrawable_cash, deduct from `_available_cash` if valid, return (success, balance)
    - `get_effective_buy_power`: return `min(available_cash, max(0, daily_limit - daily_spent))` (0 = unlimited → available_cash only)
    - _Requirements: 1.6, 3.1, 3.3, 8.1, 8.3, 8.4_

  - [x] 1.9 Implement `reset(initial_deposit)`, `save_state()`, `restore_state()`
    - `reset`: set available_cash = initial_deposit, clear pending_withdrawals, cancel all timers, persist
    - `save_state`: persist current state to file (for mode switch)
    - `restore_state`: load from file, remove expired entries, reschedule timers
    - _Requirements: 5.1, 5.2, 7.2, 7.3_

  - [x] 1.10 Implement `_broadcast_delta()` for WebSocket notification
    - Trigger `account-update` event via existing `_broadcast_account()` pattern in engine_service
    - Include deposit, withdrawable, pending_withdrawal fields in account snapshot
    - _Requirements: 6.2_

- [x] 2. Integrate Settlement Engine with dry_run.py
  - [x] 2.1 Replace `_deduct_virtual_balance()` and `_add_virtual_balance()` calls with Settlement Engine
    - In `_apply_buy()`: replace `_deduct_virtual_balance(cost + fee)` with `settlement_engine.on_buy_fill(price, qty)`
    - In `_apply_sell()`: replace `_add_virtual_balance(proceeds)` with `settlement_engine.on_sell_fill(price, qty, code, stk_nm)`
    - Remove fee calculation from dry_run (now handled by settlement_engine)
    - _Requirements: 1.2, 2.1_

  - [x] 2.2 Update `get_virtual_balance()` to delegate to Settlement Engine
    - Return `settlement_engine.get_available_cash()` instead of `_virtual_balance`
    - Update `charge_virtual_balance()` to call `settlement_engine.charge(amount)`
    - Update `reset_virtual_balance()` to call `settlement_engine.reset(deposit)`
    - _Requirements: 1.6, 5.1, 6.1_

- [x] 3. Integrate Settlement Engine with engine_strategy_core.py
  - [x] 3.1 Add buy power check before buy execution
    - Import `settlement_engine.get_effective_buy_power` and `settlement_engine.check_buy_power`
    - In test mode, before executing buy: check if order_amount fits within effective buy power
    - Reject buy with log message if insufficient funds
    - _Requirements: 1.3, 3.1, 3.2_

- [x] 4. Integrate Settlement Engine with engine_service.py
  - [x] 4.1 Update `get_account_snapshot()` to include settlement fields in test mode
    - Add `deposit` = `settlement_engine.get_available_cash()`
    - Add `withdrawable` = `settlement_engine.get_withdrawable_cash()`
    - Add `pending_withdrawal` = `settlement_engine.get_pending_withdrawal_total()`
    - _Requirements: 6.1, 6.6_

  - [x] 4.2 Add pending withdrawals list API endpoint
    - Add GET endpoint returning `settlement_engine.get_pending_withdrawals()` list
    - Each item: sell_date, stk_cd, stk_nm, amount, settlement_date
    - _Requirements: 6.3, 6.5_

- [x] 5. Integrate Settlement Engine with engine_bootstrap.py
  - [x] 5.1 Load settlement state on engine startup
    - Call `settlement_engine._load()` during bootstrap sequence
    - Reschedule timers for pending items whose settlement_date is in the future
    - Remove expired entries and update withdrawable cash
    - _Requirements: 2.7, 7.3_

- [x] 6. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Integrate Settlement Engine with mode switching
  - [x] 7.1 Wire mode switch (test→real) to `save_state()` and timer cancellation
    - In `settings_store.after_settings_persisted()` trade mode change handler: call `settlement_engine.save_state()` when leaving test mode
    - Cancel all active settlement timers
    - _Requirements: 7.2_

  - [x] 7.2 Wire mode switch (real→test) to `restore_state()`
    - Call `settlement_engine.restore_state()` when entering test mode
    - Remove expired pending entries, reschedule active timers
    - _Requirements: 7.3, 7.5_

- [x] 8. Wire data reset to Settlement Engine
  - [x] 8.1 Update test data reset flow to include settlement reset
    - In the existing reset API handler: call `settlement_engine.reset(initial_deposit)`
    - Ensure trade_history.clear_test_history() and dry_run.clear() are also called
    - Broadcast account-update after reset
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 9. Add REST API endpoints for settlement operations
  - [x] 9.1 Add POST `/api/settlement/charge` endpoint
    - Accept `{ amount: int }`, call `settlement_engine.charge(amount)`
    - Return updated available_cash
    - Broadcast account-update
    - _Requirements: 1.6, 8.1, 8.2_

  - [x] 9.2 Add POST `/api/settlement/withdraw` endpoint
    - Accept `{ amount: int }`, call `settlement_engine.withdraw(amount)`
    - Return `{ success: bool, balance: int, reason?: str }`
    - Broadcast account-update on success
    - _Requirements: 8.3, 8.4_

  - [x] 9.3 Add GET `/api/settlement/pending-withdrawals` endpoint
    - Return list of pending withdrawal items
    - _Requirements: 6.3, 6.5_

- [x] 10. Checkpoint - Ensure all backend integration works
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Frontend: Update appStore and binding for settlement data
  - [x] 11.1 Ensure `AccountSnapshot` type includes `withdrawable` and `pending_withdrawal` fields
    - These fields are already received via account-update event
    - Verify appStore correctly stores and exposes them
    - _Requirements: 6.1, 6.2_

  - [x] 11.2 No additional WS event handler needed
    - Settlement data flows through existing `account-update` event
    - Verify `applyAccountUpdate` correctly handles new fields
    - _Requirements: 6.2_

- [x] 12. Frontend: Update profit-overview.ts for test mode cash display
  - [x] 12.1 Display 3 cash items in test mode instead of single "예수금"
    - When `settings.trade_mode === 'test'`: show "매수 가능" (deposit), "인출 가능" (withdrawable), "정산 대기" (pending_withdrawal)
    - When real mode: keep existing "예수금" display
    - Use existing `accountValRefs` pattern with conditional labels
    - _Requirements: 6.4_

- [x] 13. Frontend: Verify general-settings.ts charge integration
  - [x] 13.1 Update charge button to call new settlement charge API
    - Change charge button handler to POST `/api/settlement/charge` with input amount
    - Update balance display on success
    - _Requirements: 1.6, 8.1_

- [x] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x]* 15. Property-based tests for Settlement Engine
  - [ ]* 15.1 Write property test for buy fill deduction
    - **Property 1: Buy fill deduction is exact and preserves non-negativity**
    - **Validates: Requirements 1.2, 1.4**

  - [ ]* 15.2 Write property test for buy power check
    - **Property 2: Buy power check correctly enforces effective limit**
    - **Validates: Requirements 1.3, 3.1, 3.2, 3.3**

  - [ ]* 15.3 Write property test for sell fill proceeds and pending withdrawal
    - **Property 3: Sell fill adds correct net proceeds and creates matching pending withdrawal**
    - **Validates: Requirements 2.1, 2.2, 2.5**

  - [ ]* 15.4 Write property test for withdrawable cash invariant
    - **Property 4: Withdrawable cash invariant**
    - **Validates: Requirements 2.3**

  - [ ]* 15.5 Write property test for settlement removes pending withdrawal
    - **Property 5: Settlement removes pending withdrawal and increases withdrawable cash**
    - **Validates: Requirements 2.4**

  - [ ]* 15.6 Write property test for D+2 settlement date calculation
    - **Property 6: D+2 settlement date skips non-business days**
    - **Validates: Requirements 4.1, 4.2**

  - [ ]* 15.7 Write property test for state persistence round-trip
    - **Property 7: State persistence round-trip with expired entry cleanup**
    - **Validates: Requirements 2.7, 7.3**

  - [ ]* 15.8 Write property test for reset
    - **Property 8: Reset restores initial state completely**
    - **Validates: Requirements 5.1, 5.2**

  - [ ]* 15.9 Write property test for charge
    - **Property 9: Charge increases Available_Cash by exact amount**
    - **Validates: Requirements 1.6, 8.1**

  - [ ]* 15.10 Write property test for withdrawal bounded by withdrawable
    - **Property 10: Withdrawal bounded by withdrawable cash**
    - **Validates: Requirements 8.3, 8.4**

  - [ ]* 15.11 Write property test for mode isolation
    - **Property 11: Mode isolation — test operations do not affect saved real state**
    - **Validates: Requirements 7.2, 7.3, 7.5**

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- All monetary values use integer arithmetic (원 단위) — no floating point
- Event-driven architecture: call_later timers, no polling
- File persistence via `backend/data/settlement_state.json`
- Settlement Engine is test-mode only; real mode bypasses all settlement logic
