# 태스크 파일: 보유종목 화면 표시 소스 분리 구현

> **상태**: 1단계 구현 완료, 4세션 독립 검증(코드 리뷰+기계적 게이트+정적 시나리오 검증) 완료, 사용자 모의 관찰 대기
> **작성일**: 2026-08-01
> **설계서 경로**: `docs/architecture_position_display_source_separation_design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ · 2세션(태스크 파일) ✅ · 3세션(1단계 구현) ✅ (커밋 `08efb81`) · 4세션(1단계 독립 검증) ✅ (코드 변경 없음, 사용자 모의 관찰 대기) · 별세션(2단계 이름 변경 태스크·구현) 대기
> **관련 원칙**: P10(SSOT) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성) · P25(격리된 실패) · W7(시뮬레이터/증권사 응답 동일 구조)
> **위험도**: 낮음 (프론트엔드 표시 소스 참조 및 역할 주석만 변경, 백엔드·DB·계산·주문 경로 미변경)

---

## 목표

보유종목 화면의 현재가 표시만 `hotStore.sectorStocks`(master_stocks_cache 기반)에서 읽도록 변경한다. 손익·평가금액·수익률·매도 조건 계산은 기존 `positions.cur_price`를 계속 사용하여 표시 소스와 계산 소스를 분리한다.

---

## 변경 대상 파일

| 파일 | 수정 목적 | 수정 포인트 | 수정 범위 |
|---|---|---|---|
| `frontend/src/pages/sell-position.ts` | 보유종목 현재가 컬럼을 표시용 업종 종목 캐시와 연결 | `COLUMNS`의 `cur_price` 컬럼 render, 현재 `computePositionValuation(p)` 호출부 | `hotStore.getState().sectorStocks[normalizeStockCode(p.stk_cd)]`를 조회하여 `cur_price`와 `change_rate`를 `createPriceCell`에 전달. `sectorStocks` 종목 또는 `cur_price`가 없으면 `createPriceCell(null, null)` 반환. `p.cur_price`를 표시용 폴백으로 참조하지 않으며 표시 가격·등락률 모두 업종 종목 캐시를 사용한다. |
| `frontend/src/pages/profit-math.ts` | 계산용 `Position.cur_price`의 책임을 코드 문서에 명시 | `computePositionValuation` 설명 주석 및 필드 설명 | `p.cur_price`가 손익·평가금액·수익률 계산 입력값이며 화면 표시 소스가 아니라는 설명으로 갱신. 계산식, null 처리, 반환 타입은 변경하지 않음. |
| `frontend/src/types/index.ts` | Position 필드 역할을 타입 계약에 명시 | `Position.cur_price` 주석 | `cur_price`를 계산 기준가로 설명하고 화면 표시 소스가 아님을 명시. 타입(`number | null`)과 WS 계약 필드는 변경하지 않음. |
| `frontend/tests/pages/profit-math.test.ts` | 기존 계산 SSOT의 null 처리 회귀 확인 | `computePositionValuation`·`computeHoldingsSummary` 관련 테스트 | 기존 테스트를 확인하고, 구현으로 계산 경로가 변경되지 않았음을 검증. 필요한 경우 `cur_price: null`의 `isNull`·요약 `hasNullPrice` 동작을 검증하는 최소 단위 테스트만 추가한다. |

> `frontend/src/stores/hotStore.ts`는 수정하지 않는다. `sectorStocks` Record와 `normalizeStockCode`는 이미 표시용 공통 자산으로 존재하므로 `sell-position.ts`에서 기존 헬퍼를 재사용한다.

---

## 작업 순서

### 1단계: 표시 소스 분리 구현 (3세션) — ✅ 완료 (커밋 `08efb81`)

- [x] `architecture_position_display_source_separation_design.md`의 1단계 범위와 금지사항을 다시 대조한다.
- [x] `sell-position.ts`의 현재가 컬럼에서 표시값을 `sectorStocks[normalizeStockCode(p.stk_cd)]?.cur_price`로 읽도록 변경한다.
- [x] 보유종목 코드가 `sectorStocks`에 없거나 해당 종목의 `cur_price`가 `null`/`undefined`이면 `-`가 표시되도록 처리한다.
- [x] 표시용 현재가 조회에서 `p.cur_price`를 조건부 폴백으로 사용하지 않는다.
- [x] `computePositionValuation`, `computeHoldingsSummary`, 평가손익 컬럼, 수익률 컬럼, 요약 행은 계산 소스인 `positions.cur_price`를 계속 사용하도록 보존한다.
- [x] `hotStore` 구독 및 `real-data-tick` 갱신 배선은 변경하지 않는다. `sectorStocks` 변경 시 행과 요약이 갱신되는 기존 경로를 재사용한다.
- [x] `profit-math.ts`와 `types/index.ts`의 `cur_price` 역할 주석을 계산용 필드로 정렬한다.
- [x] 구현 범위를 벗어난 백엔드·DB·WS payload·매매 로직 변경이 없는지 확인한다.

**1단계 검증 방법:**

- [x] `cd frontend && npm run typecheck` — ✅ 통과
- [x] `cd frontend && npm run test` — ✅ 403 passed
- [x] `cd frontend && npm run build` — ✅ 통과
- [x] 변경 diff에서 `sell-position.ts`의 현재가 표시가 `sectorStocks`를 직접 참조하고 `p.cur_price` 폴백을 참조하지 않는지 확인한다.
- [x] 변경 diff에서 `profit-math.ts`의 계산 공식과 null 처리 로직이 변경되지 않았는지 확인한다.

### 2단계: 독립 검증 및 모의 관찰 (4세션)

- [x] 3세션 구현 커밋과 본 태스크 파일만 기준으로 독립 검토를 수행한다. — ✅ 4세션 완료 (코드 리뷰 + 기계적 게이트 + 정적 시나리오 검증). 코드 변경 없음.
- [ ] 설계서 5.1의 사용자 관점 완료 기준 7개 시나리오를 브라우저에서 확인한다. — 사용자 모의 관찰 대기 (정적 코드 검증은 완료 — 아래 2단계 검증 방법 항목별 근거 참조)
- [x] 독립 검증 결과와 사용자 직접 확인 결과를 `HANDOVER.md`에 기록한다. — 독립 검증 결과 기록 완료 (사용자 직접 확인 결과는 모의 관찰 후 추가 예정)
- [ ] 이상이 없으면 1단계 태스크를 완료 처리하고, 이상이 있으면 해당 세션에서 원인을 보고한 뒤 수정 승인 여부를 확인한다. — 사용자 모의 관찰 완료 후 판정

**2단계 검증 방법:**

> 4세션 정적 코드 검증 결과 (브라우저 런타임 확인은 사용자 모의 관찰 대기):

- [x] **정적✅** 비거래일 또는 장마감 후 기동 시 positions의 계산용 가격이 없어도 보유종목 화면에 sectorStocks의 확정가가 표시되는지 확인한다. — `sell-position.ts:47-54` render가 `sectorStocks[normalizeStockCode(p.stk_cd)]?.cur_price`를 읽음. sectorStocks는 `sector-stocks-refresh` WS로 master_stocks_cache 기반 확정가 수신 (변경 없음). positions.cur_price=None(백엔드 reset)과 무관하게 확정가 표시.
- [x] **정적✅** 거래일 07:58 리셋 후 첫 틱 전에는 sectorStocks 가격이 없어져 보유종목 현재가가 `-`인지 확인한다. — `applyRealtimeReset`(hotStore.ts:548-589)이 sectorStocks의 `cur_price`를 null화. render의 `curPrice == null` 가드 → `createPriceCell(null, null)` → '-'.
- [x] **정적✅** 첫 틱 수신 후 보유종목 현재가가 실시간 값으로 갱신되는지 확인한다. — `applyRealData`(hotStore.ts:321-)가 sectorStocks[code].cur_price를 in-place 갱신. hotStore 구독 render 재실행 → 실시간 값 표시.
- [x] **정적✅** 확정가가 표시되는 동안 평가손익·수익률·요약 행이 확정가를 계산에 사용하지 않고 기존 null 정책대로 `-`인지 확인한다. — pnl/rate 컬럼(`sell-position.ts:67,81`)과 요약(`renderSummary:171`)은 `computePositionValuation(p)`/`computeHoldingsSummary` 사용 → `p.cur_price`(None) 기반. isNull=true → '-'. 계산 소스와 표시 소스 분리 확인 (설계서 결정 2).
- [x] **정적✅** 매수후보·업종별 종목·보유종목 화면의 현재가 표시 기준이 일치하는지 확인한다. — `sector-stock-rows.ts:27-28`이 `item.stock.cur_price`/`change_rate`(sectorStocks 원소) 사용. `sell-position.ts:49-51`도 동일 `sectorStocks[code].cur_price`/`change_rate` 사용. 동일 소스 (P23).
- [x] **정적✅** sectorStocks에 없는 보유종목은 `-`로 표시되고 positions 가격으로 되돌아가지 않는지 확인한다. — `sectorStocks[code]` = undefined → `curPrice` = undefined → `curPrice == null` true → '-'. `p.cur_price` 참조 경로 없음 (P20 폴백 금지).

### 별도 단계: positions 가격 필드명 변경

- [ ] 본 태스크에서는 수행하지 않는다.
- [ ] 별도 태스크에서 `positions.cur_price → calc_cur_price` 전면 변경, 증권사 응답 매핑, WS 계약, 백엔드·프론트엔드·테스트 회귀를 다룬다.

---

## 금지사항 (Not To Do)

- [ ] 백엔드 서비스·계산 로직·리셋 로직을 변경하지 않는다.
- [ ] `computePositionValuation`과 `computeHoldingsSummary`의 계산 소스 및 공식을 변경하지 않는다.
- [ ] `positions.cur_price`를 표시용 fallback으로 사용하지 않는다.
- [ ] `applyRealData` 또는 `real-data-tick` 배선을 변경하지 않는다.
- [ ] 신규 `confirmed_cur_price` 필드·컬럼·플래그를 추가하지 않는다.
- [ ] 신규 시장상태 상태머신이나 표시 전용 상태를 추가하지 않는다.
- [ ] DB 스키마·마이그레이션을 변경하지 않는다.
- [ ] WS payload 필드명이나 `Position` 필드명을 이번 단계에서 변경하지 않는다.
- [ ] 매수·매도·리스크 판단 로직을 변경하지 않는다.
- [ ] 신규 공통 헬퍼를 만들지 않는다. 기존 `normalizeStockCode`, `hotStore.sectorStocks`, 공통 가격 셀 렌더러를 재사용한다.
- [ ] 설계서에 없는 UI 라벨·배지·상태 표시를 추가하지 않는다.
- [ ] 2단계 `cur_price → calc_cur_price` 이름 변경을 함께 수행하지 않는다.

---

## 완료 조건 (Done Criteria)

- [ ] `sell-position.ts`의 보유종목 현재가 컬럼이 `sectorStocks`의 정규화된 종목코드로 현재가를 조회한다.
- [ ] `sectorStocks`에 종목이 없거나 가격이 null/undefined이면 현재가 셀에 `-`가 표시된다.
- [ ] 현재가 표시 코드에 `positions.cur_price` 폴백 경로가 없다.
- [ ] `computePositionValuation`은 계속 `positions.cur_price`를 계산 입력값으로 사용한다.
- [ ] `computePositionValuation`의 null 처리와 `computeHoldingsSummary`의 `hasNullPrice` 동작이 유지된다.
- [ ] 평가손익·수익률·요약 행이 확정가 표시 소스를 계산에 사용하지 않는다.
- [ ] `sectorStocks` 변경 및 실시간 틱 이후 보유종목 행이 기존 갱신 배선으로 다시 렌더링된다.
- [ ] `Position.cur_price` 타입과 WS payload 필드명은 변경되지 않는다.
- [ ] 백엔드·DB·주문 경로 변경이 없다.
- [ ] 프론트엔드 typecheck가 통과한다.
- [ ] 프론트엔드 테스트가 통과한다.
- [ ] 프론트엔드 build가 통과한다.
- [ ] 독립 검증에서 설계서 5.1의 7개 사용자 관점 시나리오가 충족된다.

---

## 테스트 계획

- **단위 테스트:** `frontend/tests/pages/profit-math.test.ts`의 기존 계산·null 처리 테스트를 실행한다. 구현으로 계산 모듈을 변경하지 않으므로 테스트 추가는 실제 회귀 공백이 확인되는 경우에만 최소 범위로 한다.
- **페이지 회귀:** `sell-position.ts`의 현재가 셀 렌더 경로를 타입체크·빌드로 확인하고, 브라우저에서 sectorStocks 가격 생명주기별 표시를 확인한다.
- **상태 갱신 회귀:** `hotStore`의 sectorStocks 변경 및 `real-data-tick` 기존 테스트/동작을 확인한다. hotStore 배선 자체는 변경하지 않는다.
- **범위 회귀:** 프론트엔드 전체 테스트와 빌드로 표시 소스 변경에 따른 페이지·공통 컴포넌트 회귀를 확인한다.

---

## 바로잡음 로그

- 없음.

---

## 사전 롤백 계획

> 위험도는 낮지만, 화면 표시 소스 변경에 대한 즉시 되돌림 기준을 명시한다.

- **롤백 방법:** 구현 커밋 해시를 확인한 뒤 `git revert <구현 커밋 해시>`로 단일 커밋을 되돌린다. `HANDOVER.md`는 커밋 대상이 아니므로 별도로 현재 상태를 갱신한다.
- **즉시 롤백 트리거:**
  - sectorStocks에 정상 가격이 있는데 보유종목 화면이 계속 `-`로 표시되는 경우
  - 첫 틱 이후 보유종목 현재가가 갱신되지 않는 경우
  - 평가손익·수익률 계산이 확정가 표시값을 사용하거나 기존 null 표시 정책과 달라지는 경우
  - 현재가 표시 변경으로 다른 페이지 또는 공통 가격 셀 렌더링이 깨지는 경우
- **롤백 후 확인:** 롤백 뒤 `cd frontend && npm run typecheck`, `cd frontend && npm run test`, `cd frontend && npm run build`를 다시 실행한다.

---

## 사용자 결정 항목

- 1단계 표시 소스 분리와 2단계 `cur_price → calc_cur_price` 이름 변경을 독립 태스크로 진행한다는 설계 결정을 따른다.
- 1단계 구현 후 다음 세션에서 독립 검증과 모의 관찰을 진행한다.
- 본 태스크에는 추가 사용자 결정 항목이 없다.
