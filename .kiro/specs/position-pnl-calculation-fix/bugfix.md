# Bugfix Requirements Document

## Introduction

매도설정 페이지의 보유종목 테이블에서 평가손익(`pnl_amount`)과 수익률(`pnl_rate`)이 현재가와 불일치하게 표시되는 버그를 수정합니다. 프론트엔드 `applyRealData` 함수가 실시간 체결 데이터(`real-data` 이벤트)를 수신할 때 `cur_price`만 갱신하고 `eval_amount`, `pnl_amount`, `pnl_rate`를 재계산하지 않아, 현재가는 최신이지만 평가손익/수익률은 이전 `account-update` 이벤트 기준의 오래된 값이 표시됩니다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN 실시간 체결 데이터(`real-data` 이벤트, type 01/0B/0H)가 보유종목의 현재가를 변경하면 THEN the system은 `cur_price`만 갱신하고 `eval_amount`, `pnl_amount`, `pnl_rate`는 이전 `account-update` 이벤트에서 받은 값을 그대로 유지하여, 현재가와 평가손익/수익률이 불일치한다

1.2 WHEN 보유종목의 현재가가 실시간으로 변경되었으나 아직 `account-update` 이벤트가 도착하지 않은 상태에서 THEN the system은 화면에 최신 현재가와 과거 기준의 평가손익/수익률을 동시에 표시하여 사용자에게 잘못된 정보를 제공한다

1.3 WHEN Position 타입에서 매수금액 필드로 `buy_amt`를 사용하는데 백엔드에서 `buy_amount`로 전송하면 THEN the system은 필드명 불일치로 인해 프론트엔드에서 매수금액을 정상적으로 참조하지 못할 수 있다

### Expected Behavior (Correct)

2.1 WHEN 실시간 체결 데이터(`real-data` 이벤트, type 01/0B/0H)가 보유종목의 현재가를 변경하면 THEN the system SHALL `cur_price` 갱신과 동시에 `eval_amount = cur_price × qty`, `pnl_amount = eval_amount - buy_amount`, `pnl_rate = (pnl_amount / buy_amount) × 100`을 재계산하여 일관된 값을 표시한다

2.2 WHEN `account-update` 이벤트가 아직 도착하지 않은 상태에서 현재가가 변경되면 THEN the system SHALL 프론트엔드에서 자체적으로 평가손익/수익률을 재계산하여 현재가와 항상 정합성을 유지한다

2.3 WHEN 백엔드에서 `buy_amount` 필드명으로 매수금액을 전송하면 THEN the system SHALL 프론트엔드 Position 타입에서 해당 필드를 올바르게 매핑하여 재계산에 사용한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `account-update` 이벤트가 정상적으로 도착하면 THEN the system SHALL CONTINUE TO 백엔드에서 계산된 `pnl_amount`, `pnl_rate`, `eval_amount` 값을 그대로 반영한다

3.2 WHEN 보유종목이 아닌 종목의 실시간 체결 데이터가 수신되면 THEN the system SHALL CONTINUE TO `sectorStocks`와 `buyTargets`의 현재가/등락률/체결강도만 갱신한다

3.3 WHEN 현재가가 이전과 동일한 값으로 수신되면 THEN the system SHALL CONTINUE TO 불필요한 상태 갱신을 스킵하여 렌더링 성능을 유지한다

3.4 WHEN `buy_amount`가 0이거나 `qty`가 0인 보유종목이면 THEN the system SHALL CONTINUE TO 0으로 나누기 오류 없이 안전하게 처리한다

---

### Bug Condition (Formal)

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type RealDataEvent
  OUTPUT: boolean
  
  // real-data 이벤트로 보유종목의 현재가가 변경될 때 버그 발생
  RETURN X.type IN {'01', '0B', '0H'}
    AND X.code IN positions.map(p => p.stk_cd)
    AND parsePrice(X.values['10']) != positions[X.code].cur_price
END FUNCTION
```

### Fix Checking Property

```pascal
// Property: Fix Checking - 현재가 변경 시 평가손익/수익률 재계산
FOR ALL X WHERE isBugCondition(X) DO
  state' ← applyRealData'(X)
  pos' ← state'.positions.find(p => p.stk_cd == X.code)
  newPrice ← parsePrice(X.values['10'])
  
  ASSERT pos'.cur_price = newPrice
  ASSERT pos'.eval_amount = newPrice * pos'.qty
  ASSERT pos'.pnl_amount = pos'.eval_amount - pos'.buy_amount
  ASSERT pos'.pnl_rate = (pos'.pnl_amount / pos'.buy_amount) * 100  // buy_amount > 0
END FOR
```

### Preservation Checking Property

```pascal
// Property: Preservation Checking - 비보유종목 또는 가격 미변경 시 기존 동작 유지
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT applyRealData(X) = applyRealData'(X)
END FOR
```
