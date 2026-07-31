# 태스크 파일: 보유종목 현재가 배선 교정 — sectorStocks → positions 주 소스 전환

> **상태**: 구현 세션 진행 중
> **작성일**: 2026-07-31
> **위험도**: 낮음 (프론트엔드 표시 배선만 변경, 주문·전략·리스크·DB 미변경)
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 0. 사전조사 결과 요약

### 0.1 버그 현상

보유종목 페이지에서 052690 한전기술만 현재가가 '-'로 표시됨. 다른 3종목(131970, 420770, 010120)은 정상 표시.

### 0.2 근본 원인 (배선 실수 한 곳)

`computePositionValuation`(<ref_file file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/pages/profit-math.ts" />)이 보유종목의 현재가를 `sectorStocks[code].cur_price`에서 읽음. `sectorStocks`는 5거래일 평균 거래대금 필터를 통과한 종목만 포함하므로, 052690(197억, 임계값 200억 미달)은 sectorStocks에 엔트리 자체가 없어 null → '-' 표시.

반면 `positions[i].cur_price`는 틱 핸들러(<ref_snippet file="/Users/sungjk0706/Desktop/SectorFlow/frontend/src/stores/hotStore.ts" lines="448-457" />)가 필터와 무관하게 항상 갱신하지만, **아무도 읽지 않는 dead read** 상태였음.

### 0.3 priceStore 통합(Option A)은 보류

"병렬 3곳 쓰기(sectorStocks/buyTargets/positions) 자체가 문제"라는 진단은 과잉. 세 저장소는 각각 다른 도메인(필터 통과 목록 / 매수후보 / 보유종목)을 담당하며 이는 의도된 설계. 진짜 문제는 "보유종목 화면이 엉뚱한 저장소(sectorStocks)를 읽고 있었다"는 배선 실수 한 곳. priceStore 통합은 별도 리팩토링 태스크로 분리.

### 0.4 해결 방안 (최소 수정)

`computePositionValuation`/`computeHoldingsSummary`가 sectorStocks 대신 `positions[i].cur_price`를 주 소스로 읽도록 배선 교정. 이는 `?? p.cur_price` 폴백 복원과 다름 — 폴백은 "sectorStocks가 주 소스, positions는 보조"라는 잘못된 위계가 남음. 주 소스를 positions로 정정하는 것이 정답 (보유종목 현재가는 보유종목 자체의 실시간 갱신 값에서 나와야 함).

---

## 1. 사용자 결정 항목

| 항목 | 확정 기준 | 사용자 영향 |
|---|---|---|
| 주 소스 전환 | sectorStocks 참조 제거, `p.cur_price`를 유일 소스로 | 052690 케이스 해결 — 필터 탈락 종목도 현재가 정상 표시 |
| Position.cur_price 타입 | `number` → `number \| null` 승격 | 백엔드 `_reset_realtime_fields`의 `None` 설정과 타입 일치 (P22) |
| sectorStocks 파라미터 | `computePositionValuation`/`computeHoldingsSummary`에서 제거 | 호출처 4곳 + 테스트 파일 시그니처 전파 |
| priceStore 통합 | 별도 태스크로 분리 (본 태스크 범위 외) | — |

---

## 2. 의존성 및 재사용 자산

| 파일 | 역할 | 태스크 적용 기준 |
|---|---|---|
| `frontend/src/types/index.ts` | `Position` 인터페이스 정의 | `cur_price: number` → `number \| null` 승격 (P22) |
| `frontend/src/pages/profit-math.ts` | `computePositionValuation`/`computeHoldingsSummary` SSOT | sectorStocks 파라미터 제거, `p.cur_price` 주 소스로 전환 |
| `frontend/src/pages/sell-position.ts` | 보유종목 페이지 (cur_price/pnl/rate 컬럼 + 요약행) | 호출처 4곳 시그니처 전파 |
| `frontend/src/pages/profit-shared.ts` | `renderAccountVals` (수익현황 계좌현황) | `computeHoldingsSummary` 호출 시그니처 전파 + `AccountValsParams.sectorStocks` 제거 |
| `frontend/tests/pages/profit-shared.test.ts` | 회귀 테스트 28건 | `makePosition`에 curPrice 파라미터 추가, sectorStocks 인자 제거 |

---

## 3. 구현 단계

### 3-1. types/index.ts — Position.cur_price 타입 승격

```ts
// Before
export interface Position {
  ...
  cur_price: number;
  ...
}

// After
export interface Position {
  ...
  cur_price: number | null;  // null = 틱 미수신 (백엔드 _reset_realtime_fields와 일치, P22)
  ...
}
```

### 3-2. profit-math.ts — computePositionValuation 시그니처 변경

```ts
// Before
export function computePositionValuation(
  p: Position,
  sectorStocks: Record<string, SectorStock>,
): PositionValuation {
  const qty = p.qty ?? 0
  const buyPrice = p.avg_price
  const code = normalizeStockCode(p.stk_cd)
  const curPriceRaw = sectorStocks[code]?.cur_price ?? null
  if (curPriceRaw == null) { ... }
  ...
}

// After
export function computePositionValuation(
  p: Position,
): PositionValuation {
  const qty = p.qty ?? 0
  const buyPrice = p.avg_price
  const curPriceRaw = p.cur_price  // 보유종목 자체의 실시간 갱신 값 (P10 SSOT 정정)
  if (curPriceRaw == null) { ... }
  ...
}
```

주석 업데이트: "현재가: sectorStocks[code].cur_price" → "현재가: p.cur_price (보유종목 실시간 갱신, 필터 무관)".

### 3-3. profit-math.ts — computeHoldingsSummary 시그니처 변경

```ts
// Before
export function computeHoldingsSummary(
  positions: Position[],
  sectorStocks: Record<string, SectorStock>,
): { ... } {
  ...
  const v = computePositionValuation(p, sectorStocks)
  ...
}

// After
export function computeHoldingsSummary(
  positions: Position[],
): { ... } {
  ...
  const v = computePositionValuation(p)
  ...
}
```

### 3-4. sell-position.ts — 호출처 4곳 시그니처 전파

- 45줄: `computePositionValuation(p, hotStore.getState().sectorStocks)` → `computePositionValuation(p)`
- 61줄: 동일
- 75줄: 동일
- 165줄: `computeHoldingsSummary(state.positions, state.sectorStocks)` → `computeHoldingsSummary(state.positions)`

### 3-5. profit-shared.ts — renderAccountVals 시그니처 전파

- 240줄: `computeHoldingsSummary(params.positions, params.sectorStocks)` → `computeHoldingsSummary(params.positions)`
- `AccountValsParams` 인터페이스에서 `sectorStocks` 필드 제거 (205줄)
- profit-overview.ts 호출처 확인 — `renderAccountVals(state)` 호출 시 sectorStocks 전달 부분 제거 필요

### 3-6. profit-math.ts — 미사용 import 정리

`SectorStock` 타입 import가 computePositionValuation/computeHoldingsSummary에서 더 이상 사용되지 않음. 단, profit-math.ts 내 다른 함수에서 SectorStock을 사용하는지 확인 후 제거 (P16 dead code 금지).

### 3-7. 테스트 파일 시그니처 전파

`frontend/tests/pages/profit-shared.test.ts`:
- `makePosition(code, qty, avgPrice)` → `makePosition(code, qty, avgPrice, curPrice)` (curPrice 파라미터 추가)
- 모든 `computePositionValuation(p, sectorStocks)` → `computePositionValuation(p)`
- 모든 `computeHoldingsSummary(positions, sectorStocks)` → `computeHoldingsSummary(positions)`
- `makeSectorStock` 헬퍼는 더 이상 위 두 함수에 필요 없음 — 테스트에서 제거 또는 다른 용도 확인
- 테스트 시나리오 의미 보존: "sectorStocks 비어있음" → "p.cur_price null"로 재해석

---

## 4. 검증 기준

| 단계 | 명령어 | 기대 결과 |
|---|---|---|
| 타입체크 | `cd frontend && npm run typecheck` | 통과 |
| 빌드 | `cd frontend && npm run build` | 통과 |
| 테스트 | `cd frontend && npm run test` | 116 tests 통과 (시그니처 변경 후 테스트 수정 포함) |

---

## 5. 위험/주의점

1. **Position.cur_price 타입 승격 전파**: `cur_price: number | null` 변경 시 Position.cur_price를 읽는 다른 곳이 있는지 확인 (조사 결과 0곳이지만 타입체크로 검증).
2. **profit-overview.ts 호출처**: `renderAccountVals`에 sectorStocks를 전달하는 호출처 확인 — `AccountValsParams.sectorStocks` 제거 시 전파 필요.
3. **테스트 시나리오 의미 보존**: "sectorStocks 비어있음 → isNull=true" 테스트는 "p.cur_price null → isNull=true"로 재해석. 동일한 사용자 의미(시세 미수신 시 '-' 표시) 보존.
4. **SectorStock import 정리**: profit-math.ts에서 SectorStock이 다른 함수에 사용되지 않으면 import 제거 (P16).
