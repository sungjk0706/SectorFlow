# Bugfix Requirements Document

## Introduction

매매적격종목 리스트(eligible_stocks_cache)를 기준으로 모든 데이터 저장소가 정합적이어야 하나, 4가지 독립적 결함으로 인해 캐시/메모리 간 종목수 불일치가 발생한다. 부적격 종목이 5일 캐시에 잔존하고, 확정시세 반영 시 고가가 누락되며, UI에 부적격 종목이 노출되고, 갱신 완료 후에도 메모리가 적격 기준으로 재로딩되지 않는다.

## Mandatory Ordering Constraint (절대 선행 조건)

아래 순서는 데이터 정합성 보장을 위해 **절대적으로 선행**되어야 하며, 코드에서 이 순서가 위반되면 안 된다.

1. **전종목 리스트 다운로드 (ka10099)** — 코스피+코스닥 전종목 리스트를 키움 서버에서 다운로드한다.
2. **매매부적격 필터링 → 적격종목 리스트 확정 및 저장** — `is_excluded()` 필터를 적용하여 매매적격종목 리스트(`eligible_stocks`)를 만들고 디스크에 저장한다.
3. **이후 모든 API 요청은 적격 리스트 종목만 요청** — 장마감 20:30 이후 갱신이든, 사용자에 의한 데이터 삭제 후 갱신이든, 항상 적격 리스트에 포함된 종목만 서버에 요청한다.
   - ka10086 (전종목 확정시세) → 적격 종목만 요청
   - ka10081 (전종목 5일 거래대금/고가) → 적격 종목만 요청
   - 5일 거래대금과 고가는 같은 API 응답에서 파싱됨
4. **저장 시 적격 리스트 기준으로만 저장** — 다운로드한 데이터는 적격 리스트 기준으로 저장한다. 부적격 종목 데이터는 저장하지 않으며, 기존 캐시에 잔존하는 부적격 종목도 제거한다.
5. **적격 리스트 종목의 모든 매핑 작업 완료 후 메모리 로딩** — 확정시세 + 5일거래대금/고가 + 업종 매핑이 모두 완료된 후에야 메모리(`_pending_stock_details`)를 적격 기준으로 교체한다.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 적격종목 목록이 변경되어 이전 세션에 적격이었던 종목이 부적격으로 전환된 경우, `rolling_update_v2_from_trade_amounts()`가 기존 v2 캐시의 모든 종목을 그대로 유지하여 THEN the system은 avg_amt_5d_cache에 부적격 종목 데이터를 영구 잔존시킨다 (예: 1484 적격 기준에 +41 부적격 잔존 → 1525종목)

1.2 WHEN ka10086 확정시세 응답에 `high_price` 필드가 포함되어 `_apply_confirmed_to_memory()`가 호출될 때, THEN the system은 entry에 `high_price`를 저장하지 않아 이후 `_run_post_confirmed_pipeline()`에서 신규 종목의 고가가 누락된다

1.3 WHEN `get_all_sector_stocks()`가 호출될 때, `_pending_stock_details`에서 `status == "active"`인 모든 종목을 반환하여 THEN the system은 적격 필터를 적용하지 않고 부적격 종목을 UI 업종분류 페이지에 노출한다 (예: 1484 적격 기준에 1520종목 표시)

1.4 WHEN 전종목 확정시세 및 5일 거래대금/고가 갱신이 완료된 후, `_pending_stock_details` 메모리에 부적격 종목이 잔존하여 THEN the system은 적격종목 기준으로 메모리를 재로딩하지 않아 ~1520종목이 메모리에 남아있다

### Expected Behavior (Correct)

2.1 WHEN `rolling_update_v2_from_trade_amounts()`가 v2 캐시를 롤링 갱신할 때, 적격종목 목록을 기준으로 부적격 종목을 제거하여 THEN the system SHALL 갱신 결과에 적격종목만 포함시키고, 부적격 종목 데이터는 캐시에서 완전히 제거한다

2.2 WHEN `_apply_confirmed_to_memory()`가 ka10086 확정시세를 메모리에 반영할 때, `high_price` 필드가 양수이면 THEN the system SHALL entry에 `high_price` 값을 저장하여 이후 롤링 갱신에서 고가 데이터가 정상 수집되도록 한다

2.3 WHEN `get_all_sector_stocks()`가 호출될 때, `_eligible_stock_codes`를 기준으로 필터링하여 THEN the system SHALL 적격종목만 반환하고 부적격 종목은 UI에 노출하지 않는다

2.4 WHEN 전종목 확정시세(ka10086), 5일 거래대금/고가(ka10081), 업종 매핑 저장이 모두 정상 완료된 후, THEN the system SHALL `_pending_stock_details` 메모리를 적격종목 기준으로 원자적으로 교체하여 부적격 종목을 제거한다

2.5 WHEN 확정시세, 5일 거래대금/고가, 업종 매핑 중 하나라도 저장에 실패한 경우, THEN the system SHALL 메모리 교체를 수행하지 않고 기존 상태를 유지하며 오류만 기록한다

2.6 WHEN 메모리 교체가 진행되는 동안, THEN the system SHALL UI에 중간 상태(종목이 잠깐 사라졌다 나타나는 현상)를 노출하지 않고, 이전 상태를 유지하다가 준비 완료 시 한 번에 새 상태로 전환한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 적격종목의 거래대금이 정상적으로 수집된 경우, `rolling_update_v2_from_trade_amounts()`는 THEN the system SHALL CONTINUE TO 해당 종목의 5일치 배열을 정상 롤링 갱신한다 (기존 종목: 가장 오래된 값 제거 → 당일 값 추가)

3.2 WHEN ka10086 확정시세 응답의 `cur_price`, `change`, `change_rate`, `sign`, `trade_amount` 필드가 반영될 때, `_apply_confirmed_to_memory()`는 THEN the system SHALL CONTINUE TO 기존 필드들을 정상적으로 entry에 저장한다

3.3 WHEN `get_all_sector_stocks()`가 호출되고 적격종목 캐시가 비어있는 경우(초기 상태), THEN the system SHALL CONTINUE TO `status == "active"`인 모든 종목을 반환한다 (적격 필터 미적용 — 하위 호환)

3.4 WHEN 적격종목의 고가가 0 이하인 경우, `_apply_confirmed_to_memory()`는 THEN the system SHALL CONTINUE TO 기존 entry의 `high_price` 값을 덮어쓰지 않는다

3.5 WHEN 신규 적격종목이 v2 캐시에 없는 상태에서 당일 거래대금이 수집된 경우, `rolling_update_v2_from_trade_amounts()`는 THEN the system SHALL CONTINUE TO 해당 종목을 `[당일값]` 배열로 신규 추가한다

3.6 WHEN 메모리 원자적 교체 시 적격종목에 해당하는 종목의 시세/상태 데이터는 THEN the system SHALL CONTINUE TO 기존 값을 그대로 유지한다 (적격종목 데이터 유실 없음)

3.7 WHEN 메모리 교체가 아직 완료되지 않은 상태에서 UI가 데이터를 조회하면, THEN the system SHALL CONTINUE TO 이전(교체 전) 상태의 데이터를 일관되게 반환한다

---

## Bug Condition (Formal)

### Bug Condition 1: 부적격 종목 캐시 잔존

```pascal
FUNCTION isBugCondition_CacheStale(X)
  INPUT: X of type (stock_code, existing_v2_cache, eligible_set)
  OUTPUT: boolean

  // 기존 캐시에 존재하지만 적격 목록에 없는 종목
  RETURN X.stock_code IN X.existing_v2_cache AND X.stock_code NOT IN X.eligible_set
END FUNCTION
```

```pascal
// Property: Fix Checking — 부적격 종목 제거
FOR ALL X WHERE isBugCondition_CacheStale(X) DO
  result ← rolling_update_v2_from_trade_amounts'(X.existing_v2_cache, X.trade_amounts, eligible=X.eligible_set)
  ASSERT X.stock_code NOT IN result.updated_v2
END FOR
```

### Bug Condition 2: high_price 미반영

```pascal
FUNCTION isBugCondition_HighPrice(X)
  INPUT: X of type (confirmed_detail)
  OUTPUT: boolean

  // ka10086 응답에 양수 high_price가 포함된 경우
  RETURN X.confirmed_detail.high_price > 0
END FUNCTION
```

```pascal
// Property: Fix Checking — high_price 저장
FOR ALL X WHERE isBugCondition_HighPrice(X) DO
  entry ← _apply_confirmed_to_memory'(X)
  ASSERT entry.high_price == X.confirmed_detail.high_price
END FOR
```

### Bug Condition 3: 적격 필터 미적용

```pascal
FUNCTION isBugCondition_UIFilter(X)
  INPUT: X of type (stock_code, pending_details, eligible_set)
  OUTPUT: boolean

  // active 상태이지만 적격 목록에 없는 종목
  RETURN X.stock_code IN X.pending_details
    AND X.pending_details[X.stock_code].status == "active"
    AND X.eligible_set IS NOT EMPTY
    AND X.stock_code NOT IN X.eligible_set
END FUNCTION
```

```pascal
// Property: Fix Checking — UI에서 부적격 종목 제외
FOR ALL X WHERE isBugCondition_UIFilter(X) DO
  result ← get_all_sector_stocks'()
  ASSERT X.stock_code NOT IN result
END FOR
```

### Bug Condition 4: 갱신 후 메모리 원자적 교체 미수행

```pascal
FUNCTION isBugCondition_MemoryReload(X)
  INPUT: X of type (stock_code, pending_details, eligible_set, all_saves_completed)
  OUTPUT: boolean

  // 모든 저장(확정시세 + 5일거래대금/고가 + 업종매핑)이 완료된 후,
  // 메모리에 부적격 종목이 active로 잔존
  RETURN X.all_saves_completed == true
    AND X.stock_code IN X.pending_details
    AND X.pending_details[X.stock_code].status == "active"
    AND X.eligible_set IS NOT EMPTY
    AND X.stock_code NOT IN X.eligible_set
END FUNCTION
```

```pascal
// Property: Fix Checking — 갱신 후 메모리에서 부적격 종목 제거 (원자적 교체)
FOR ALL X WHERE isBugCondition_MemoryReload(X) DO
  pending ← _pending_stock_details' (after atomic swap)
  ASSERT X.stock_code NOT IN pending OR pending[X.stock_code].status != "active"
END FOR
```

```pascal
// Property: Atomicity — 교체 중 중간 상태 미노출
FOR ALL T WHERE swap_in_progress(T) DO
  ui_view ← get_all_sector_stocks'(at time T)
  ASSERT ui_view == pre_swap_state OR ui_view == post_swap_state
  // 부분 교체 상태(일부 종목만 제거된 상태)는 절대 노출되지 않음
END FOR
```

### Preservation Property (공통)

```pascal
// Property: Preservation Checking — 적격종목 동작 보존
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```
