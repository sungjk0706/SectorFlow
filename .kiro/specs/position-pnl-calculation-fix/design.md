# Bugfix Design Document

## Bug Summary

매도설정 페이지의 보유종목 테이블에서 실시간 체결 데이터(`real-data` 이벤트)로 `cur_price`가 갱신될 때 `eval_amount`, `pnl_amount`, `pnl_rate`가 재계산되지 않아 현재가와 평가손익/수익률이 불일치하는 버그.

## Root Cause

`frontend/src/stores/appStore.ts`의 `applyRealData` 함수에서 보유종목의 현재가를 갱신할 때:
```typescript
positions[posIdx] = { ...pos, cur_price: price };
```
`cur_price`만 업데이트하고 `eval_amount`, `pnl_amount`, `pnl_rate`를 재계산하지 않음.

추가로, 백엔드에서 `buy_amount` 필드명으로 매수금액을 전송하지만 프론트엔드 Position 타입에는 `buy_amt`만 정의되어 있어 필드 매핑 불일치 가능성 존재.

---

## Bug Condition

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

**Concrete failing cases:**
- Position: `{ stk_cd: '005930', qty: 10, buy_amt: 700000, cur_price: 70000 }`
- RealDataEvent: `{ type: '01', item: '005930', values: { '10': '72000' } }`
- After `applyRealData`: `cur_price` = 72000, but `eval_amount` remains old value (not 720000), `pnl_amount` remains old (not 20000), `pnl_rate` remains old (not 2.86)

---

## Expected Behavior Properties

```pascal
// Property: 현재가 변경 시 평가손익/수익률이 올바르게 재계산됨
FOR ALL X WHERE isBugCondition(X) DO
  state' ← applyRealData'(X)
  pos' ← state'.positions.find(p => p.stk_cd == X.code)
  newPrice ← parsePrice(X.values['10'])
  buyAmt ← pos.buy_amt ?? pos.buy_amount ?? 0
  qty ← pos.qty ?? 0
  
  ASSERT pos'.cur_price = newPrice
  ASSERT pos'.eval_amount = newPrice * qty
  ASSERT pos'.pnl_amount = (newPrice * qty) - buyAmt           // when buyAmt > 0
  ASSERT pos'.pnl_rate = round((pnl_amount / buyAmt) * 100, 2) // when buyAmt > 0
  ASSERT pos'.pnl_amount = 0 AND pos'.pnl_rate = 0             // when buyAmt = 0
END FOR
```

---

## Preservation Requirements

```pascal
// Property: 비보유종목 또는 가격 미변경 시 기존 동작 유지
FOR ALL X WHERE NOT isBugCondition(X) DO
  // Case 1: 보유종목이 아닌 종목의 실시간 데이터 → sectorStocks/buyTargets만 갱신
  // Case 2: 현재가가 동일한 값으로 수신 → positions 배열 참조 변경 없음
  ASSERT applyRealData(X).positions = applyRealData'(X).positions
END FOR

// Property: account-update 이벤트 동작 불변
// account-update 핸들러는 수정 대상이 아니므로 기존 동작 유지

// Property: buy_amount=0 또는 qty=0인 경우 안전 처리
FOR ALL pos WHERE pos.buy_amt = 0 OR pos.qty = 0 DO
  ASSERT NO division-by-zero error
  ASSERT pos'.pnl_rate = 0
END FOR
```

---

## Fix Design

### 1. Position 타입 확장 (`frontend/src/types/index.ts`)

```typescript
export interface Position {
  stk_cd: string;
  stk_nm: string;
  qty: number;
  buy_price?: number;
  avg_price?: number;
  cur_price: number;
  eval_amount?: number;
  eval_amt?: number;
  buy_amt?: number;
  buy_amount?: number;  // ← 추가: 백엔드 필드명 매핑
  pnl_amount?: number;
  pnl_rate: number;
  market_type?: string;
  nxt_enable?: boolean;
}
```

### 2. `applyRealData` 수정 (`frontend/src/stores/appStore.ts`)

현재가 갱신 시 PnL 재계산 로직 추가:

```typescript
// 보유종목 현재가 실시간 반영 (account-update 없이 직접 갱신)
let positions = state.positions;
const posIdx = positions.findIndex(p => p.stk_cd === code);
if (posIdx >= 0) {
  const pos = positions[posIdx];
  if (pos.cur_price !== price) {
    const buyAmt = pos.buy_amt ?? (pos as any).buy_amount ?? 0;
    const qty = pos.qty ?? 0;
    const evalAmount = price * qty;
    const pnlAmount = buyAmt > 0 ? evalAmount - buyAmt : 0;
    const pnlRate = buyAmt > 0 ? Math.round((pnlAmount / buyAmt) * 10000) / 100 : 0;
    positions = [...positions];
    positions[posIdx] = { ...pos, cur_price: price, eval_amount: evalAmount, pnl_amount: pnlAmount, pnl_rate: pnlRate };
  }
}
```

### Key Design Decisions

1. **`buy_amt ?? buy_amount` fallback**: 백엔드 필드명(`buy_amount`)과 프론트엔드 필드명(`buy_amt`) 모두 지원
2. **Division-by-zero guard**: `buyAmt > 0` 체크로 0 나누기 방지, 0일 때 pnl_rate = 0
3. **`Math.round(...* 10000) / 100`**: 소수점 2자리 반올림 (예: 2.857... → 2.86)
4. **기존 최적화 유지**: `pos.cur_price !== price` 체크로 불필요한 상태 갱신 스킵

---

## Affected Files

| File | Change |
|------|--------|
| `frontend/src/types/index.ts` | Position 인터페이스에 `buy_amount?: number` 필드 추가 |
| `frontend/src/stores/appStore.ts` | `applyRealData` 함수에서 보유종목 현재가 갱신 시 PnL 재계산 로직 추가 |

---

## Test Strategy

- **Property-based testing** with `fast-check` (already installed) + `vitest`
- Test file: `frontend/src/stores/applyRealData.test.ts`
- Bug condition test: 보유종목의 현재가 변경 시 PnL 재계산 검증
- Preservation test: 비보유종목 또는 가격 미변경 시 positions 불변 검증
