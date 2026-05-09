# Data Consistency Fix — Bugfix Design

## Overview

매매적격종목 리스트(`eligible_stocks_cache`)를 단일 진실 소스(Single Source of Truth)로 삼아, 4가지 독립적 결함을 수정한다:

1. **부적격 종목 캐시 잔존** — `rolling_update_v2_from_trade_amounts()`가 `eligible_set` 파라미터를 받아 부적격 종목을 결과에서 제거
2. **high_price 미반영** — `_apply_confirmed_to_memory()`에서 `high_price` 필드를 entry에 저장
3. **UI 적격 필터 미적용** — `get_all_sector_stocks()`에서 `_eligible_stock_codes` 기준 필터링
4. **갱신 후 메모리 원자적 교체** — 모든 저장 완료 후 `_pending_stock_details`를 적격 기준으로 원자적 교체

수정 범위는 최소화하며, 기존 적격종목의 동작은 완전히 보존한다.

## Glossary

- **Bug_Condition (C)**: 부적격 종목이 캐시/메모리/UI에 잔존하는 조건 (4가지 독립 조건)
- **Property (P)**: 적격종목만 캐시/메모리/UI에 존재해야 하는 정합성 속성
- **Preservation**: 적격종목의 기존 동작(롤링 갱신, 시세 반영, UI 표시, 메모리 유지)이 변경되지 않아야 함
- **`eligible_set`**: `_eligible_stock_codes` — `{종목코드: ""}` 딕셔너리. 키만 의미 있음
- **`rolling_update_v2_from_trade_amounts()`**: `avg_amt_cache.py`의 v2 캐시 롤링 갱신 함수
- **`_apply_confirmed_to_memory()`**: `market_close_pipeline.py`의 확정시세 메모리 반영 함수
- **`get_all_sector_stocks()`**: `engine_service.py`의 업종분류 페이지 전종목 반환 함수
- **`_pending_stock_details`**: `engine_service.py`의 전종목 시세/상태 인메모리 딕셔너리
- **원자적 교체**: UI에 중간 상태를 노출하지 않고, 이전 상태 → 새 상태로 한 번에 전환

## Bug Details

### Bug Condition 1: 부적격 종목 캐시 잔존

`rolling_update_v2_from_trade_amounts()`가 `existing_v2` 캐시의 모든 종목을 무조건 유지하여, 이전 세션에서 적격이었으나 현재 부적격으로 전환된 종목이 영구 잔존한다.

**Formal Specification:**
```
FUNCTION isBugCondition_CacheStale(input)
  INPUT: input of type (stock_code, existing_v2_cache, eligible_set)
  OUTPUT: boolean

  RETURN input.stock_code IN input.existing_v2_cache
         AND input.stock_code NOT IN input.eligible_set
END FUNCTION
```

### Bug Condition 2: high_price 미반영

`_apply_confirmed_to_memory()`가 ka10086 응답의 `high_price` 필드를 entry에 저장하지 않아, 이후 `_run_post_confirmed_pipeline()`에서 `int(detail.get("high_price") or 0)`이 항상 0을 반환한다.

**Formal Specification:**
```
FUNCTION isBugCondition_HighPrice(input)
  INPUT: input of type (confirmed_detail)
  OUTPUT: boolean

  RETURN int(input.confirmed_detail.get("high_price") or 0) > 0
END FUNCTION
```

### Bug Condition 3: UI 적격 필터 미적용

`get_all_sector_stocks()`가 `_pending_stock_details`에서 `status == "active"`인 모든 종목을 반환하여, 부적격 종목이 업종분류 페이지에 노출된다.

**Formal Specification:**
```
FUNCTION isBugCondition_UIFilter(input)
  INPUT: input of type (stock_code, pending_details, eligible_set)
  OUTPUT: boolean

  RETURN input.stock_code IN input.pending_details
         AND input.pending_details[input.stock_code].status == "active"
         AND len(input.eligible_set) > 0
         AND input.stock_code NOT IN input.eligible_set
END FUNCTION
```

### Bug Condition 4: 갱신 후 메모리 원자적 교체 미수행

전종목 확정시세 + 5일 거래대금/고가 + 업종 매핑 저장이 모두 완료된 후에도, `_pending_stock_details`에 부적격 종목이 active 상태로 잔존한다.

**Formal Specification:**
```
FUNCTION isBugCondition_MemoryReload(input)
  INPUT: input of type (stock_code, pending_details, eligible_set, all_saves_completed)
  OUTPUT: boolean

  RETURN input.all_saves_completed == true
         AND input.stock_code IN input.pending_details
         AND input.pending_details[input.stock_code].status == "active"
         AND len(input.eligible_set) > 0
         AND input.stock_code NOT IN input.eligible_set
END FUNCTION
```

### Examples

- **Bug 1**: 적격 1484종목 기준에서 v2 캐시에 1525종목 존재 → 41종목이 부적격 잔존
- **Bug 2**: ka10086 응답 `{"high_price": 52300, "cur_price": 51000, ...}` → entry에 `high_price` 키 없음 → `_run_post_confirmed_pipeline()`에서 `high_prices[code] = 0` → 고가 롤링 누락
- **Bug 3**: `_pending_stock_details`에 1520종목(active) → `get_all_sector_stocks()` 반환 1520종목 → UI에 부적격 36종목 노출
- **Bug 4**: 파이프라인 완료 후 `_pending_stock_details`에 여전히 ~1520종목 → 적격 1484종목 기준으로 교체되지 않음

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- 적격종목의 5일치 거래대금 배열 롤링 갱신 (기존 종목: 가장 오래된 값 제거 → 당일 값 추가, 최대 5개)
- 적격종목의 신규 추가 (`[당일값]` 배열로 추가)
- ka10086 확정시세의 `cur_price`, `change`, `change_rate`, `sign`, `trade_amount` 필드 정상 반영
- `eligible_set`이 비어있을 때(초기 상태) `get_all_sector_stocks()`가 모든 active 종목 반환 (하위 호환)
- 메모리 교체 시 적격종목의 시세/상태 데이터 유실 없음
- 메모리 교체 미완료 시 UI가 이전 상태를 일관되게 반환

**Scope:**
적격종목(`eligible_set`에 포함된 종목)에 대한 모든 기존 동작은 이 수정에 의해 영향받지 않는다. 변경은 오직 부적격 종목의 제거/차단에만 적용된다.

## Hypothesized Root Cause

Based on the bug description, the most likely issues are:

1. **`rolling_update_v2_from_trade_amounts()` — 필터 파라미터 부재**: 함수가 `eligible_set`을 받지 않으므로, `existing_v2`의 모든 종목을 무조건 `updated_v2`에 복사한다. 부적격 전환된 종목을 제거할 메커니즘이 없다.

2. **`_apply_confirmed_to_memory()` — high_price 저장 누락**: 함수가 `cur_price`, `change`, `change_rate`, `sign`, `trade_amount`는 저장하지만, `high_price` 필드에 대한 처리 코드가 없다. ka10086 응답에 `high_price`가 포함되어도 entry에 반영되지 않는다.

3. **`get_all_sector_stocks()` — eligible 필터 미적용**: 함수가 `_pending_stock_details`를 순회하며 `status == "active"`만 체크한다. `_eligible_stock_codes`를 참조하여 부적격 종목을 제외하는 로직이 없다.

4. **파이프라인 완료 후 메모리 교체 미수행**: `fetch_unified_confirmed_data()`와 `_refresh_avg_amt_5d_cache_inner()` 모두 파이프라인 완료 후 `_pending_stock_details`에서 부적격 종목을 제거하는 단계가 없다. 메모리 초기화(`clear()`)는 파이프라인 시작 시에만 수행되며, 완료 후 적격 기준 교체는 구현되어 있지 않다.

## Correctness Properties

Property 1: Bug Condition — 부적격 종목 캐시 제거

_For any_ input where a stock code exists in `existing_v2` cache but NOT in `eligible_set`, the fixed `rolling_update_v2_from_trade_amounts()` SHALL exclude that stock code from the returned `updated_v2` and `updated_high_arr` dictionaries.

**Validates: Requirements 2.1**

Property 2: Bug Condition — high_price 저장

_For any_ confirmed detail where `high_price > 0`, the fixed `_apply_confirmed_to_memory()` SHALL store the `high_price` value in the corresponding entry in `_pending_stock_details`.

**Validates: Requirements 2.2**

Property 3: Bug Condition — UI 적격 필터 적용

_For any_ stock code that is in `_pending_stock_details` with `status == "active"` but NOT in `_eligible_stock_codes` (when non-empty), the fixed `get_all_sector_stocks()` SHALL NOT include that stock in the returned list.

**Validates: Requirements 2.3**

Property 4: Bug Condition — 메모리 원자적 교체

_For any_ state where all saves (확정시세 + 5일거래대금/고가 + 업종매핑) have completed successfully, the fixed pipeline SHALL atomically replace `_pending_stock_details` so that only eligible stocks with `status == "active"` remain, and no intermediate state is visible to UI queries.

**Validates: Requirements 2.4, 2.5, 2.6**

Property 5: Preservation — 적격종목 롤링 갱신 보존

_For any_ stock code that IS in `eligible_set`, the fixed `rolling_update_v2_from_trade_amounts()` SHALL produce the same rolling update result as the original function (existing array shift + new value append, or new `[value]` array for new stocks).

**Validates: Requirements 3.1, 3.5**

Property 6: Preservation — 확정시세 기존 필드 보존

_For any_ confirmed detail, the fixed `_apply_confirmed_to_memory()` SHALL continue to store `cur_price`, `change`, `change_rate`, `sign`, `trade_amount` fields exactly as the original function does.

**Validates: Requirements 3.2, 3.4**

Property 7: Preservation — eligible 비어있을 때 하위 호환

_For any_ call to `get_all_sector_stocks()` when `_eligible_stock_codes` is empty, the fixed function SHALL return all stocks with `status == "active"`, identical to the original behavior.

**Validates: Requirements 3.3**

Property 8: Preservation — 메모리 교체 시 적격종목 데이터 보존

_For any_ stock code in `eligible_set`, the atomic memory swap SHALL preserve the stock's existing entry data (시세, 상태, 이름 등) without modification.

**Validates: Requirements 3.6, 3.7**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

---

**File**: `backend/app/core/avg_amt_cache.py`

**Function**: `rolling_update_v2_from_trade_amounts()`

**Specific Changes**:

1. **새 파라미터 추가**: `eligible_set: set[str] | None = None` 키워드 인자 추가

2. **부적격 종목 필터링 (거래대금)**: `updated_v2` 구성 시, `eligible_set`이 제공되면 결과에 포함할 종목을 `eligible_set`에 있는 것만으로 제한
   - 기존 종목 롤링 루프: `if eligible_set is not None and code not in eligible_set: continue`
   - 신규 종목 추가 루프: `if eligible_set is not None and code not in eligible_set: continue`

3. **부적격 종목 필터링 (고가)**: `updated_high` 구성 시 동일 패턴 적용
   - 기존 고가 롤링 루프: `if eligible_set is not None and code not in eligible_set: continue`
   - 신규 고가 추가 루프: `if eligible_set is not None and code not in eligible_set: continue`

**변경 후 시그니처**:
```python
def rolling_update_v2_from_trade_amounts(
    existing_v2: dict[str, list[int]] | None,
    trade_amounts: dict[str, int],
    *,
    high_prices: dict[str, int] | None = None,
    high_5d_arr: dict[str, list[int]] | None = None,
    eligible_set: set[str] | None = None,  # NEW
) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
```

---

**File**: `backend/app/services/market_close_pipeline.py`

**Function**: `_apply_confirmed_to_memory()`

**Specific Changes**:

4. **high_price 저장 추가**: 기존 필드 반영 블록(`cur_price`, `change`, `change_rate`, `sign`, `trade_amount`) 뒤에 `high_price` 저장 로직 추가
   ```python
   # high_price
   hp = int(detail.get("high_price") or 0)
   if hp > 0:
       entry["high_price"] = hp
   ```

---

**Function**: `_run_post_confirmed_pipeline()`

**Specific Changes**:

5. **eligible_set 전달**: `rolling_update_v2_from_trade_amounts()` 호출 시 `eligible_set` 파라미터 전달
   ```python
   eligible_codes = set(elig.keys()) if elig else None
   updated_v2, updated_high_arr = rolling_update_v2_from_trade_amounts(
       existing_v2, trade_amounts,
       high_prices=high_prices,
       high_5d_arr=existing_high_arr,
       eligible_set=eligible_codes,  # NEW
   )
   ```

---

**Function**: `fetch_unified_confirmed_data()`

**Specific Changes**:

6. **완전한 매핑 단계 + 원자적 메모리 교체 추가**: 파이프라인 마지막 단계(`_run_post_confirmed_pipeline()` 완료 후, 업종순위 재계산 전)에 매핑 검증 + 메모리 교체 로직 삽입

   ```python
   # ── Step 6: 완전한 매핑 단계 (적격종목 × 시세 × 5일데이터 × 업종) ──
   import app.core.industry_map as _ind_mod
   from app.core.sector_mapping import get_merged_sector
   
   final_eligible = set(_ind_mod._eligible_stock_codes.keys())
   if not final_eligible:
       _log.warning("[파이프라인] 적격종목 비어있음 — 메모리 교체 생략")
   else:
       # 매핑 검증: 각 적격 종목에 대해 시세 + 5일데이터 + 업종 존재 확인
       pending = es._pending_stock_details
       avg_map = es._avg_amt_5d
       high_cache = es._high_5d_cache
       
       mapped_pending = {}
       for cd in final_eligible:
           entry = pending.get(cd)
           if entry is None:
               continue  # 시세 데이터 없는 종목은 제외
           # 업종 매핑 보강
           if not entry.get("sector"):
               sector = get_merged_sector(cd) or ""
               if sector:
                   entry["sector"] = sector
           mapped_pending[cd] = entry
       
       # 5일 데이터도 적격 기준으로 필터
       new_avg = {cd: v for cd, v in avg_map.items() if cd in final_eligible}
       new_high = {cd: v for cd, v in high_cache.items() if cd in final_eligible}
       
       # ── Step 7: 원자적 메모리 교체 (_shared_lock 내부) ──
       async with es._shared_lock:
           es._pending_stock_details.clear()
           es._pending_stock_details.update(mapped_pending)
           es._avg_amt_5d.clear()
           es._avg_amt_5d.update(new_avg)
           es._high_5d_cache.clear()
           es._high_5d_cache.update(new_high)
           es._radar_cnsr_order[:] = [
               cd for cd in es._radar_cnsr_order if cd in final_eligible
           ]
       
       _log.info("[파이프라인] 원자적 메모리 교체 완료 — %d종목 (avg=%d, high=%d)",
                 len(mapped_pending), len(new_avg), len(new_high))
   ```

7. **부분 실패 시 교체 스킵**: `_run_post_confirmed_pipeline()` 또는 `_save_confirmed_cache()` 실패 시 메모리 교체를 수행하지 않음 (기존 `cached` 변수로 판단)

---

**File**: `backend/app/services/engine_service.py`

**Function**: `get_all_sector_stocks()`

**Specific Changes**:

8. **eligible 필터 추가**: `_eligible_stock_codes` 참조하여 부적격 종목 제외
   ```python
   import app.core.industry_map as _ind_mod
   elig = _ind_mod._eligible_stock_codes  # {코드: ""} or {}

   for cd, entry in snapshot.items():
       if entry.get("status") != "active":
           continue
       # 적격 필터: eligible이 비어있으면 필터 미적용 (하위 호환)
       if elig and cd not in elig:
           continue
       ...
   ```

---

**File**: `backend/app/services/engine_bootstrap.py`

**Function**: `_refresh_avg_amt_5d_cache_inner()`

**Specific Changes**:

9. **eligible_set 전달 (사용자 트리거 경로)**: `_chunked_fetch_full_5d()` 완료 후 `save_avg_amt_cache_v2()` 호출 시, 이미 `get_eligible_stocks()`로 `all_codes`를 구성하므로 추가 필터 불필요. 단, `rolling_update_v2_from_trade_amounts()`를 직접 호출하는 경로가 있다면 동일하게 `eligible_set` 전달.

---

### Data Flow Summary (Mandatory Ordering)

```
┌─────────────────────────────────────────────────────────────────────┐
│ Pipeline Path (fetch_unified_confirmed_data)                         │
├─────────────────────────────────────────────────────────────────────┤
│ Step 1: ka10099 전종목 리스트 다운로드                                │
│    ↓                                                                 │
│ Step 3: is_excluded() 필터 → confirmed_codes (적격 리스트) 확정       │
│    ↓                                                                 │
│ Step 4: eligible_stocks_cache 저장 + 종목명/시장구분 캐시 저장         │
│    ↓                                                                 │
│ Step 5: ka10086 확정시세 (적격 종목만 요청)                           │
│    ↓ _apply_confirmed_to_memory() — high_price 포함 저장             │
│    ↓                                                                 │
│ _run_post_confirmed_pipeline():                                      │
│    ├─ trade_amounts/high_prices 수집 (적격만)                        │
│    ├─ rolling_update_v2(eligible_set=적격) → 부적격 제거             │
│    ├─ save_avg_amt_cache_v2() → 디스크 저장                          │
│    └─ _save_confirmed_cache() → 스냅샷 저장                         │
│    ↓                                                                 │
│ ★ Step 6: 완전한 매핑 단계 (적격종목 × 시세 × 5일데이터 × 업종):     │
│    ├─ 적격 종목별 확정시세 존재 확인 (cur_price > 0)                  │
│    ├─ 적격 종목별 5일거래대금/고가 매핑 (avg_amt_5d + high_5d)        │
│    ├─ 적격 종목별 업종명 매핑 (get_merged_sector)                     │
│    ├─ 3가지 모두 매핑 완료된 종목만 최종 데이터셋으로 확정             │
│    └─ 레이아웃 캐시 재구성 (종목+업종 매핑 반영)                      │
│    ↓                                                                 │
│ ★ Step 7: 원자적 메모리 교체 (_shared_lock 내부):                    │
│    ├─ new_pending = {cd: entry for cd in eligible, 매핑 완료}        │
│    ├─ _pending_stock_details.clear() + update(new_pending)           │
│    ├─ _avg_amt_5d 교체 (적격만)                                      │
│    ├─ _high_5d_cache 교체 (적격만)                                   │
│    └─ _radar_cnsr_order 필터                                         │
│    ↓                                                                 │
│ 업종순위 재계산 + WS 브로드캐스트                                     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│ User-Triggered Refresh Path (_refresh_avg_amt_5d_cache_inner)        │
├─────────────────────────────────────────────────────────────────────┤
│ get_eligible_stocks() → all_codes (이미 적격만)                      │
│    ↓                                                                 │
│ _chunked_fetch_full_5d(all_codes) — ka10081 적격 종목만 요청         │
│    ↓                                                                 │
│ save_avg_amt_cache_v2() → 디스크 저장 (적격만 포함)                   │
│    ↓                                                                 │
│ ★ 완전한 매핑 단계:                                                  │
│    ├─ 적격 종목 × 시세 확인 (_pending_stock_details에 존재)           │
│    ├─ 적격 종목 × 5일데이터 매핑 (avg_map + high_cache)              │
│    ├─ 적격 종목 × 업종명 매핑 (get_merged_sector)                    │
│    └─ 3가지 모두 매핑된 종목만 최종 확정                              │
│    ↓                                                                 │
│ ★ 원자적 메모리 교체:                                                │
│    ├─ _avg_amt_5d 적격 기준으로 교체                                 │
│    ├─ _high_5d_cache 적격 기준으로 교체                              │
│    └─ _pending_stock_details에서 부적격 종목 제거                    │
│    ↓                                                                 │
│ 업종순위 재계산 + WS 브로드캐스트                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Error Handling

- **부분 실패 → 메모리 교체 스킵**: `_run_post_confirmed_pipeline()` 예외 발생 시 `cached = False` → 원자적 교체 미수행 → 기존 메모리 유지
- **ka10086 전체 실패**: `confirmed = {}` → `_apply_confirmed_to_memory()` 미호출 → 메모리 교체 미수행
- **eligible_set 비어있음**: `eligible_set is None` 또는 `len == 0` → 필터 미적용 (하위 호환)
- **_shared_lock 내부 예외**: `clear()` + `update()` 사이 예외 시 데이터 유실 가능 → `new_pending` 구성을 lock 밖에서 수행, lock 안에서는 `clear()` + `update()`만 실행하여 예외 가능성 최소화

### UI Atomicity (중간 상태 미노출)

1. `get_all_sector_stocks()`는 `snapshot = dict(_pending_stock_details)`로 스냅샷을 먼저 복사
2. 원자적 교체는 `_shared_lock` 내부에서 `clear()` + `update()`를 연속 실행
3. 교체 전: UI는 이전 상태(부적격 포함)를 반환
4. 교체 후: UI는 새 상태(적격만)를 반환
5. 교체 중: `_shared_lock`에 의해 동시 읽기 차단 → 중간 상태 미노출

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that call the unfixed functions with inputs containing both eligible and ineligible stocks, and assert that ineligible stocks are improperly retained. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Cache Stale Test**: Call `rolling_update_v2_from_trade_amounts()` with `existing_v2` containing ineligible stocks → assert ineligible stocks remain in result (will pass on unfixed code, demonstrating the bug)
2. **High Price Test**: Call `_apply_confirmed_to_memory()` with `high_price > 0` in confirmed detail → assert entry lacks `high_price` key (will pass on unfixed code)
3. **UI Filter Test**: Populate `_pending_stock_details` with ineligible active stocks → call `get_all_sector_stocks()` → assert ineligible stocks appear in result (will pass on unfixed code)
4. **Memory Reload Test**: After pipeline completion, check `_pending_stock_details` for ineligible active stocks → assert they remain (will pass on unfixed code)

**Expected Counterexamples**:
- `rolling_update_v2_from_trade_amounts({"INELIGIBLE": [100, 200]}, {})` → result contains "INELIGIBLE"
- `_apply_confirmed_to_memory({"005930": {"high_price": 52300, ...}})` → entry["high_price"] KeyError
- `get_all_sector_stocks()` returns stocks not in `_eligible_stock_codes`

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition_CacheStale(input) DO
  result := rolling_update_v2_from_trade_amounts'(input.existing_v2, input.trade_amounts, eligible_set=input.eligible_set)
  ASSERT input.stock_code NOT IN result.updated_v2
END FOR

FOR ALL input WHERE isBugCondition_HighPrice(input) DO
  entry := _apply_confirmed_to_memory'(input)
  ASSERT entry["high_price"] == input.confirmed_detail["high_price"]
END FOR

FOR ALL input WHERE isBugCondition_UIFilter(input) DO
  result := get_all_sector_stocks'()
  ASSERT input.stock_code NOT IN [r["code"] for r in result]
END FOR

FOR ALL input WHERE isBugCondition_MemoryReload(input) DO
  pending := _pending_stock_details' (after atomic swap)
  ASSERT input.stock_code NOT IN pending OR pending[input.stock_code].status != "active"
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT F(input) = F'(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain (random eligible stock codes, random trade amounts, random v2 cache states)
- It catches edge cases that manual unit tests might miss (empty eligible set, single-element arrays, boundary values)
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for eligible stocks, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Rolling Update Preservation**: For eligible stocks in `existing_v2`, verify the rolling logic (shift + append) produces identical results with and without `eligible_set` parameter
2. **Confirmed Fields Preservation**: For all confirmed details, verify `cur_price`, `change`, `change_rate`, `sign`, `trade_amount` are stored identically before and after fix
3. **UI Empty Eligible Preservation**: When `_eligible_stock_codes` is empty, verify `get_all_sector_stocks()` returns all active stocks (identical to unfixed behavior)
4. **Memory Swap Data Preservation**: For eligible stocks, verify their entry data is byte-for-byte identical after atomic swap

### Unit Tests

- `rolling_update_v2_from_trade_amounts()` with `eligible_set` containing subset of `existing_v2` keys
- `rolling_update_v2_from_trade_amounts()` with `eligible_set=None` (하위 호환)
- `_apply_confirmed_to_memory()` with `high_price > 0` → entry contains `high_price`
- `_apply_confirmed_to_memory()` with `high_price == 0` → entry unchanged
- `get_all_sector_stocks()` with non-empty `_eligible_stock_codes` → only eligible returned
- `get_all_sector_stocks()` with empty `_eligible_stock_codes` → all active returned
- Atomic swap with partial failure → no swap performed

### Property-Based Tests

- Generate random `existing_v2` caches and `eligible_set` subsets → verify all returned keys are in `eligible_set`
- Generate random confirmed details with various `high_price` values → verify storage correctness
- Generate random `_pending_stock_details` and `_eligible_stock_codes` → verify `get_all_sector_stocks()` output is subset of eligible
- Generate random eligible/ineligible stock mixes → verify atomic swap preserves eligible data and removes ineligible

### Integration Tests

- Full pipeline flow: ka10099 → filter → ka10086 → save → memory reload → verify final state
- Pipeline with partial ka10086 failure → verify no memory swap
- User-triggered refresh (`_refresh_avg_amt_5d_cache_inner`) → verify only eligible stocks in v2 cache
- UI query during pipeline execution → verify consistent state (no intermediate)
