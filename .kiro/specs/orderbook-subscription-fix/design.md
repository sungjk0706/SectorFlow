# 호가잔량(0D) 구독/해지 로직 Bugfix Design

## Overview

호가잔량(0D) 구독/해지가 업종순위 재계산 경로에 직접 결합되어, 체결 틱마다 불필요한 REMOVE/REG가 반복 전송되는 버그를 수정한다. 수정 후에는 `guard_pass` 상태 변경 시에만 구독/해지가 발생하며, 업종순위 변동과는 완전히 분리된다.

## Glossary

- **Bug_Condition (C)**: 업종순위만 변동하고 guard_pass 상태는 변하지 않았는데도 호가잔량 구독/해지가 발생하는 조건
- **Property (P)**: guard_pass 상태 변경 시에만 해당 종목의 구독/해지가 정확히 1회 수행되는 것
- **Preservation**: 업종 점수 증분 재계산, 매수후보 재산출, delta 전송, WS 미연결 시 스킵 등 기존 동작 유지
- **guard_pass**: 매수후보 종목이 모든 가드 조건(지수가드, 등락률 차단 등)을 통과했는지 여부 (True=통과, False=차단)
- **buy_targets**: `build_buy_targets()`가 산출한 매수후보 리스트 (guard_pass=True/False 모두 포함)
- **`_subscribed_0d_stocks`**: 현재 호가잔량 구독 중인 종목코드 집합 (engine_service 인스턴스 변수)
- **`_flush_sector_recompute_impl()`**: 업종 점수 증분 재계산 + 알림 + 구독 갱신을 수행하는 동기 함수

## Bug Details

### Bug Condition

업종순위 재계산 경로(`_flush_sector_recompute_impl`)에서 호가잔량 구독 갱신이 직접 호출되며, 변경 감지 로직(`_buy_targets_changed`)이 guard_pass 상태를 무시하고 종목코드 집합만 비교한다. 또한 `_sync_0d_subscriptions`가 전체 buy_targets를 구독 대상으로 삼아 guard_pass=False 종목까지 구독한다.

**Formal Specification:**
```
FUNCTION isBugCondition(event)
  INPUT: event of type SectorRecomputeEvent
  OUTPUT: boolean
  
  prev_codes := {bt.stock.code FOR bt IN event.prev_buy_targets}
  new_codes := {bt.stock.code FOR bt IN event.new_buy_targets}
  
  prev_guard_pass := {bt.stock.code FOR bt IN event.prev_buy_targets WHERE bt.guard_pass = True}
  new_guard_pass := {bt.stock.code FOR bt IN event.new_buy_targets WHERE bt.guard_pass = True}
  
  RETURN (prev_codes != new_codes OR prev_guard_pass = new_guard_pass)
         AND subscription_change_triggered(event)
END FUNCTION
```

버그는 두 가지 경우에 발현된다:
1. 종목코드 집합이 변경되었지만 guard_pass 상태는 동일 → 불필요한 REMOVE+REG 발생
2. guard_pass=False 종목이 구독 대상에 포함 → 불필요한 REG 발생

### Examples

- **예시 1**: 업종순위 변동으로 buy_targets 순서가 바뀜 (A,B→B,A). guard_pass 상태 동일. → 현재: REMOVE(A)+REG(A) 반복 / 기대: 구독 변경 없음
- **예시 2**: 종목 C가 buy_targets에 새로 진입하지만 guard_pass=False. → 현재: REG(C) 전송 / 기대: 구독하지 않음
- **예시 3**: 종목 D의 guard_pass가 False→True로 변경. → 현재: 이미 구독 중이거나 무시됨 / 기대: REG(D) 1회 전송
- **예시 4**: 종목 E의 guard_pass가 True→False로 변경. → 현재: 여전히 구독 유지 / 기대: REMOVE(E) 1회 전송

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- 체결 틱 수신 시 업종 점수 증분 재계산이 정상 수행된다
- 업종순위 변경 시 매수후보(buy_targets)가 정상 재산출된다
- guard_pass=True인 종목이 이미 구독 중이면 중복 REG를 전송하지 않는다 (delta 방식 유지)
- WS 미연결 시 구독/해지를 조용히 스킵한다
- `notify_desktop_sector_scores()`, `notify_buy_targets_update()` 등 기존 알림 경로는 변경 없음

**Scope:**
guard_pass 상태 변경이 없는 모든 업종 재계산 이벤트에서는 호가잔량 구독/해지가 전혀 발생하지 않아야 한다. 이는 다음을 포함한다:
- 업종순위만 변동한 경우
- buy_targets 종목 구성은 바뀌었지만 guard_pass 상태는 동일한 경우
- 동일 종목이 순서만 바뀐 경우

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **`_buy_targets_changed()` — 잘못된 비교 기준 (line 76)**:
   종목코드 집합(`{bt.stock.code}`)만 비교하여, 업종순위 변동으로 buy_targets 구성이 바뀌면 guard_pass 상태 변화 없이도 "변경됨"으로 판정한다. 실제로는 guard_pass=True인 종목 집합의 변화만 감지해야 한다.

2. **`_sync_0d_subscriptions()` — 잘못된 구독 대상 (line 237)**:
   `new_codes = {bt.stock.code for bt in new_buy_targets}` 로 전체 buy_targets를 구독 대상으로 삼는다. guard_pass=False인 종목은 아직 매수 조건을 충족하지 않으므로 호가잔량을 구독할 필요가 없다.

3. **구독 호출 위치 — 업종 재계산 경로에 직접 결합**:
   `_flush_sector_recompute_impl()` 내부에서 `create_task(_sync_0d_subscriptions(...))`를 호출한다. 이 경로는 체결 틱마다 실행되므로, 변경 감지가 부정확하면 매 틱마다 구독/해지가 반복된다.

4. **`create_task` 사용 — 워크룰 위반**:
   체결 경로에서 `asyncio.create_task()`를 사용하고 있어 워크룰(체결 경로에 create_task/큐 금지)을 위반한다.

## Correctness Properties

Property 1: Bug Condition - guard_pass 상태 변경 시에만 구독/해지 발생

_For any_ 업종 재계산 이벤트에서 guard_pass=True인 종목 집합이 변경된 경우, 수정된 코드 SHALL 새로 guard_pass=True가 된 종목에 대해서만 REG를, guard_pass=True에서 벗어난 종목에 대해서만 REMOVE를 전송한다.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4**

Property 2: Preservation - 업종 재계산 및 매수후보 산출 정상 동작

_For any_ 체결 틱 수신 이벤트에서, 수정된 코드 SHALL 업종 점수 증분 재계산, 매수후보 재산출, delta 알림 전송을 기존과 동일하게 수행하며, guard_pass 상태 변경이 없는 경우 호가잔량 구독/해지를 전혀 수행하지 않는다.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `backend/app/services/engine_sector_confirm.py`

**Specific Changes**:

1. **`_buy_targets_changed()` → `_guard_pass_codes_changed()`로 교체**:
   - 종목코드 집합 비교 대신, guard_pass=True인 종목코드 집합의 변화를 감지
   - 반환값: `(changed: bool, new_guard_pass_codes: set[str])` 또는 단순 bool + 별도 추출

   ```python
   def _get_guard_pass_codes(buy_targets) -> set[str]:
       """buy_targets에서 guard_pass=True인 종목코드 집합 추출."""
       if not buy_targets:
           return set()
       return {bt.stock.code for bt in buy_targets if bt.guard_pass}
   ```

2. **`_sync_0d_subscriptions()` — 구독 대상을 guard_pass=True 종목으로 제한**:
   - `new_codes = {bt.stock.code for bt in new_buy_targets}` →
   - `new_codes = {bt.stock.code for bt in new_buy_targets if bt.guard_pass}`

3. **`_flush_sector_recompute_impl()` 내 구독 호출 조건 변경**:
   - `_buy_targets_changed()` 호출 → `_get_guard_pass_codes()` 비교로 교체
   - guard_pass=True 종목 집합이 실제로 변경된 경우에만 `_sync_0d_subscriptions()` 호출

4. **`create_task` 제거 — 동기 직접 호출로 변경**:
   - `loop.create_task(_sync_0d_subscriptions(...))` → 동기 함수로 변환하여 직접 호출
   - `_sync_0d_subscriptions()`를 `async` → 동기 함수로 변경하거나, 동기 래퍼 사용
   - WS 전송(`_ws_send_reg_unreg_and_wait_ack`)이 async이므로, 구독 페이로드 구성까지만 동기로 수행하고 전송은 fire-and-forget으로 처리

5. **`_full_recompute()` 내 동일 패턴 수정**:
   - `_full_recompute()`에서도 동일한 `_buy_targets_changed()` + `create_task` 패턴이 사용되므로 동일하게 수정

## Testing Strategy

### Validation Approach

테스트 전략은 두 단계로 진행한다: 먼저 수정 전 코드에서 버그를 재현하는 반례를 확인하고, 수정 후 코드에서 올바른 동작과 기존 동작 보존을 검증한다.

### Exploratory Bug Condition Checking

**Goal**: 수정 전 코드에서 버그를 재현하여 근본 원인을 확인/반박한다. 반박 시 재분석이 필요하다.

**Test Plan**: 업종순위만 변동하고 guard_pass 상태는 동일한 시나리오를 구성하여, 불필요한 구독/해지가 발생하는지 확인한다.

**Test Cases**:
1. **순위 변동 테스트**: buy_targets 순서만 변경 → `_buy_targets_changed()`가 True 반환하는지 확인 (수정 전 코드에서 실패 예상)
2. **guard_pass=False 구독 테스트**: guard_pass=False 종목이 포함된 buy_targets로 `_sync_0d_subscriptions()` 호출 → 해당 종목이 구독되는지 확인 (수정 전 코드에서 실패 예상)
3. **반복 호출 테스트**: 동일 buy_targets로 연속 재계산 → REMOVE+REG가 반복되는지 확인 (수정 전 코드에서 실패 예상)
4. **guard_pass 전환 테스트**: guard_pass False→True 전환 시 구독이 발생하는지 확인

**Expected Counterexamples**:
- `_buy_targets_changed()`가 종목코드 집합만 비교하여 순위 변동만으로도 True 반환
- `_sync_0d_subscriptions()`가 guard_pass=False 종목까지 구독 등록

### Fix Checking

**Goal**: guard_pass 상태가 변경된 모든 입력에 대해, 수정된 함수가 올바른 구독/해지를 수행하는지 검증한다.

**Pseudocode:**
```
FOR ALL event WHERE guard_pass_codes_changed(event) DO
  result := sync_0d_subscriptions_fixed(event)
  new_guard_pass := {bt.stock.code FOR bt IN event.new_buy_targets WHERE bt.guard_pass}
  prev_guard_pass := {bt.stock.code FOR bt IN event.prev_buy_targets WHERE bt.guard_pass}
  ASSERT result.registered = new_guard_pass - prev_guard_pass
  ASSERT result.removed = prev_guard_pass - new_guard_pass
END FOR
```

### Preservation Checking

**Goal**: guard_pass 상태가 변경되지 않은 모든 입력에 대해, 수정된 함수가 구독/해지를 수행하지 않는지 검증한다.

**Pseudocode:**
```
FOR ALL event WHERE NOT guard_pass_codes_changed(event) DO
  ASSERT no_subscription_change(event)
  ASSERT sector_recompute_result_fixed(event) = sector_recompute_result_original(event)
END FOR
```

**Testing Approach**: Property-based testing은 preservation checking에 적합하다:
- 다양한 buy_targets 구성을 자동 생성하여 guard_pass 상태 변경 없는 경우를 광범위하게 검증
- 수동 테스트로 놓칠 수 있는 엣지 케이스(빈 리스트, 단일 종목, 전체 guard_pass=False 등)를 자동 탐색
- 업종 재계산 결과가 구독 로직 변경에 영향받지 않음을 강하게 보장

**Test Plan**: 수정 전 코드에서 업종 재계산 결과(매수후보, 알림 등)를 관찰한 후, 수정 후에도 동일한 결과가 나오는지 property-based test로 검증한다.

**Test Cases**:
1. **업종 재계산 보존**: guard_pass 변경 없는 재계산 이벤트에서 sector_summary_cache가 동일하게 갱신되는지 검증
2. **매수후보 산출 보존**: buy_targets 리스트가 동일하게 산출되는지 검증
3. **중복 REG 방지 보존**: 이미 구독 중인 종목에 대해 중복 REG가 발생하지 않는지 검증
4. **WS 미연결 스킵 보존**: WS 미연결 시 구독/해지가 스킵되는지 검증

### Unit Tests

- `_get_guard_pass_codes()`: 다양한 buy_targets 입력에 대해 guard_pass=True 종목만 추출하는지 검증
- guard_pass 상태 변경 감지: prev/new guard_pass 집합 비교 로직 검증
- `_sync_0d_subscriptions()`: guard_pass=True 종목만 구독 대상으로 삼는지 검증
- 엣지 케이스: buy_targets가 빈 리스트, 전체 guard_pass=False, 전체 guard_pass=True

### Property-Based Tests

- 임의의 buy_targets 쌍을 생성하여, guard_pass=True 집합이 동일하면 구독 변경이 없음을 검증
- 임의의 buy_targets 쌍을 생성하여, guard_pass=True 집합이 다르면 정확한 delta(REG/REMOVE)가 산출됨을 검증
- 임의의 재계산 이벤트를 생성하여, 업종 점수/매수후보 산출이 구독 로직과 무관하게 동일함을 검증

### Integration Tests

- 체결 틱 연속 수신 시나리오에서 guard_pass 변경 없으면 REMOVE/REG 페이로드가 0건인지 검증
- guard_pass False→True 전환 시나리오에서 정확히 1회 REG가 전송되는지 검증
- guard_pass True→False 전환 시나리오에서 정확히 1회 REMOVE가 전송되는지 검증
