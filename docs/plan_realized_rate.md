# 태스크 파일: 실현 수익률 분모 통일 (매수원금 기반) 구현

> **상태**: 태스크 분할 완료, 사용자 승인 대기
> **작성일**: 2026-07-30
> **설계서 경로**: `docs/architecture_realized_rate_design.md`
> **다단계 진행 상황**: 1세션(설계) ✅ · 2세션(태스크 파일) ✅ · 3세션(구현 1) ⏳ · 4세션(구현 2) ⏳
> **관련 원칙**: P10(SSOT) · P16(살아있는 경로) · P20(폴백 금지) · P21(사용자 투명성) · P22(데이터 정합성) · P23(일관성) · P24(단순성)

---

## 0. 사전조사 결과 요약

> 규칙 0-2 4항목 (의존성·영향범위·아키텍처 원칙 부합·기존 공통 자산) — 설계서 기반 실제 코드 대상 심층 조사 결과.

### 0.1 의존성 (파일 | 변경점 | 기준 라인)

| 파일 | 변경점 | 기준 라인 |
|------|--------|-----------|
| `frontend/src/pages/profit-math.ts` | `extractEarliestBaseAsset` 함수 제거 | 95-104 |
| `frontend/src/pages/profit-math.ts` | `cumulativeRealizedPnlBeforeDate` 함수 제거 | 232-243 |
| `frontend/src/pages/profit-math.ts` | `findBaseAssetForDate` 함수 제거 | 299-317 |
| `frontend/src/pages/profit-math.ts` | `CumulativePnlParams` 인터페이스 축소 — `account`·`baseAsset`·`earliestBaseAsset` 제거, `sellHistory`·`isTestMode`·`dateFrom`·`dateTo`만 잔류 | 245-253 |
| `frontend/src/pages/profit-math.ts` | `computeCumulativePnl` 단순화 — 분모 분기 로직(스냅샷 우선→earliestBaseAsset→투자원금+누적손익 추정) 제거, `aggregatePnl`의 `buyTotal`/`rate` 사용 | 272-297 |
| `frontend/src/pages/profit-math.ts` | 주석 정리 — 제거 함수 docstring·`computeCumulativePnl` 분모 규칙 주석을 매수원금 기반으로 갱신 | 95-97, 232-234, 256-271 |
| `frontend/src/pages/profit-shared.ts` | re-export 목록 정리 — `extractEarliestBaseAsset`·`cumulativeRealizedPnlBeforeDate`·`findBaseAssetForDate` 제거 | 27, 33, 34 |
| `frontend/src/pages/profit-shared.ts` | import 정리 — `cumulativeRealizedPnlBeforeDate`·`findBaseAssetForDate` 제거 | 48, 51 |
| `frontend/src/pages/profit-shared.ts` | `updateSummaryCards` 단순화 — `account`·`earliestBaseAsset` 파라미터 제거, 분모 로직(`findBaseAssetForDate`·`dayBaseAsset`·`fiveBaseAsset`·`monthBaseAsset`·`cumulativeRealizedPnlBeforeDate`) 제거, `aggregatePnl` 기반으로 4카드 계산 | 177-268 |
| `frontend/src/pages/profit-shared.ts` | `AccountValsParams.earliestBaseAsset` 제거 | 286 |
| `frontend/src/pages/profit-shared.ts` | `renderAccountVals` 단순화 — `computeCumulativePnl` 호출 → `aggregatePnl` 사용, `earliestBaseAsset` 의존 제거 | 304-359 |
| `frontend/src/pages/profit-overview-mount.ts` | import 정리 — `findBaseAssetForDate`·`extractEarliestBaseAsset` 제거 | 18, 20 |
| `frontend/src/pages/profit-overview-mount.ts` | `renderAccountVals` 래핑 — `earliestBaseAsset: extractEarliestBaseAsset(...)` 전달 제거 | 37-57 |
| `frontend/src/pages/profit-overview-mount.ts` | `buildDonutCenter` 단순화 — `extractEarliestBaseAsset`·`findBaseAssetForDate` 분모 로직 제거, `aggregatePnl` 사용 | 77-95 |
| `frontend/src/pages/profit-overview-mount.ts` | 차트 타이틀 — `'거래일별 수익률'` → `'거래일별 실현 수익률'` | 136 |
| `frontend/src/pages/profit-detail-display.ts` | import 정리 — `findBaseAssetForDate`·`extractEarliestBaseAsset` 제거 | 23, 24 |
| `frontend/src/pages/profit-detail-display.ts` | `updateStatistics` 단순화 — `extractEarliestBaseAsset`·`findBaseAssetForDate` 분모 로직 제거, `aggregatePnl` 사용 | 331-348 |
| `frontend/src/pages/profit-detail-display.ts` | 드릴다운 테이블 헤더 — `'수익률'` → `'실현 수익률'` | 208 |
| `frontend/src/pages/profit-detail-mount.ts` | import 정리 — `extractEarliestBaseAsset` 제거 | 16 |
| `frontend/src/pages/profit-detail-mount.ts` | `restoreInitialView` — `updateSummaryCards` 호출에서 `extractEarliestBaseAsset` 인자 제거 | 227-234 |
| `frontend/src/pages/profit-detail-mount.ts` | `flushDirtyRender` — `updateSummaryCards` 호출에서 `extractEarliestBaseAsset` 인자 제거 | 259-266 |
| `frontend/src/pages/profit-detail-mount.ts` | `STAT_LABELS` — `'수익률'` → `'실현 수익률'` | 161 |
| `frontend/src/pages/profit-columns.ts` | `SELL_COLS` pnl_rate 라벨 — `'수익률'` → `'실현 수익률'` | 75 |
| `frontend/tests/pages/profit-shared.test.ts` | import 정리 — `findBaseAssetForDate` 제거 | 2 |
| `frontend/tests/pages/profit-shared.test.ts` | `computeCumulativePnl` 테스트 기대값 업데이트 — 스냅샷 분모 기반 → 매수원금 분모 기반 | 262-501 |
| `frontend/tests/pages/profit-shared.test.ts` | `findBaseAssetForDate` 테스트 제거 — 함수 제거로 불필요 | 503-556 |
| `frontend/tests/pages/profit-math.test.ts` | import 정리 — `extractEarliestBaseAsset` 제거 | 4 |
| `frontend/tests/pages/profit-math.test.ts` | `extractEarliestBaseAsset` 테스트 제거 — 함수 제거로 불필요 | 47-67 |

### 0.2 영향 범위

- **프론트엔드**: 8파일 수정 (소스 6파일 + 테스트 2파일)
- **백엔드**: 변경 없음 (`get_daily_summary` pnl_rate 유지 — 이미 매수원금 기반)
- **DB**: 변경 없음 (`account_daily_snapshot` 테이블 유지 — 프론트엔드 의존만 제거)
- **거래 로직**: 영향 없음 (수익 표시 전용 — safe-trade 스킬 미연계)
- **리스크**: 거래 로직 변경 아님 → 리스크 낮음. 단순화 방향이므로 실패 시 원인 추적 용이.

### 0.3 아키텍처 원칙 부합

| 원칙 | 부합 | 근거 |
|------|------|------|
| P10 (SSOT) | ✅ | `aggregatePnl` 단일 공식으로 4카드·도넛 중앙·통계·계좌현황 누적 모두 동일 분모. 현재 3경로 혼재(`computeCumulativePnl` 스냅샷 분모 / `aggregatePnl` 매수원금 분모 / dailySummary `pnl_rate`) → 1경로 통합. 결정 5 SSOT 규칙으로 신규 함수 생성 금지. |
| P16 (살아있는 경로) | ✅ | 제거 대상 함수 3개(`extractEarliestBaseAsset`·`findBaseAssetForDate`·`cumulativeRealizedPnlBeforeDate`)는 제거 후 호출처 0건 grep 검증(3세션 검증 게이트). dead code 방치 금지. |
| P20 (폴백 금지) | ✅ | 분모 0(매도 없음) 시 `computeWeightedRate` 0 반환(기존 동일). rate null은 실전모드만. 빈 문자열/None 폴백 분기(스냅샷 미존재 시 투자원금+누적손익 추정) 제거. |
| P21 (사용자 투명성) | ✅ | "실현 수익률" 명칭으로 사용자가 "매도 완료된 거래 기준"임을 인지. 스냅샷 미존재 시 '-' 표시 문제 제거(매도 이력만 있으면 항상 표시). |
| P22 (데이터 정합성) | ✅ | 분자(실현손익)와 분모(매수원금) 모두 매도 완료된 거래에서만 발생 — 논리적 일치. 현재 분모(총자산-평가금 포함)와 분자(실현 only) 불일치 해소. |
| P23 (일관성) | ✅ | 4카드 동일 공식(설계 원칙 5). 드릴다운 테이블(dailySummary pnl_rate 직접 사용)과 요약 카드 동일 분모. 용어 "실현 수익률" 통일. |
| P24 (단순성) | ✅ | 분모 추정 로직(스냅샷 우선→earliestBaseAsset→투자원금+누적손익) 제거. `account_daily_snapshot` 의존 제거. `computeCumulativePnl` 분기 로직 축소. |
| P25 (격리된 실패) | ✅ | 변경 없음 — 계산 함수 실패 시 해당 카드만 영향. |

### 0.4 기존 공통 자산 확인

**재사용 (신규 생성 없음 — 설계 결정 5 SSOT 규칙)**:
- `aggregatePnl(sells, dateFrom?, dateTo?)` — 이미 매수원금 기반 계산 수행 (`pnl / buyTotal * 100`). 실현 수익률의 유일한 계산 함수로 명시.
  - **불변 규칙 (구현자 필수 준수)**: `aggregatePnl`의 계산 공식은 변경하지 않는다. 기존 계산식을 그대로 SSOT로 사용하며 호출부만 통일한다. 내부 로직 최적화·분모 변경·신규 분기 추가 일체 금지.
- `computeWeightedRate(pnl, buyTotal)` (`ui-styles`) — 분모 0 시 0 반환 가드. 변경 없음.
- `getRecent5TradingDays(dailySummary)` — 5거래일 날짜 범위 공통 소스. 변경 없음.
- `filterTradeRows`·`buildMonthlyDrilldown`·`buildFivedayDrilldown` — 이미 dailySummary `pnl_rate` 직접 사용(매수원금 기반). 변경 없음.
- `buildTodayDrilldown` — 오늘 매도 realized_pnl 집계. 변경 없음.

**신규 생성**: 없음 (설계 결정 5 — 동일 계산 수행 신규 함수 생성 금지). `calculateRate()`·`computeRealizedRate()` 등 동일 계산을 수행하는 신규 함수 생성 일체 금지.

---

## 1. 단계 분할

> 세션당 1단계 (규칙 0-1). 총 2세션(3세션·4세션) 예상. 각 세션 종료 시 코드 커밋 + HANDOVER.md 갱신.

### 3세션 (구현 1): 계산 로직 단순화 + 호출처 변경 + UI 명칭 변경 + 기존 테스트 업데이트

**목표**: 스냅샷 분모 의존 제거 + `aggregatePnl` SSOT화 + "실현 수익률" 명칭 적용. typecheck + build + test 통과.

**수정 파일 목록** (8파일):
1. `frontend/src/pages/profit-math.ts`
2. `frontend/src/pages/profit-shared.ts`
3. `frontend/src/pages/profit-overview-mount.ts`
4. `frontend/src/pages/profit-detail-display.ts`
5. `frontend/src/pages/profit-detail-mount.ts`
6. `frontend/src/pages/profit-columns.ts`
7. `frontend/tests/pages/profit-shared.test.ts`
8. `frontend/tests/pages/profit-math.test.ts`

**파일별 변경점**:

**profit-math.ts**:
- **`aggregatePnl` 함수 본체는 변경하지 않는다** (불변 규칙 — 0.4절). 기존 계산식을 그대로 SSOT로 사용하며 호출부만 통일. 내부 로직 수정·분모 변경·신규 분기 추가 일체 금지.
- `extractEarliestBaseAsset` 함수 제거 (95-104번 줄 + docstring).
- `cumulativeRealizedPnlBeforeDate` 함수 제거 (232-243번 줄 + docstring).
- `findBaseAssetForDate` 함수 제거 (299-317번 줄 + docstring).
- `CumulativePnlParams` 인터페이스 축소: `account`·`baseAsset`·`earliestBaseAsset` 필드 제거. `sellHistory`·`isTestMode`·`dateFrom`·`dateTo`만 잔류.
- `computeCumulativePnl` 본체 단순화: `aggregatePnl`의 `buyTotal`/`rate`를 그대로 사용. 분모 분기 로직(누적=accumulated_investment / 기간한정=baseAsset??earliestBaseAsset / 추정=투자원금+누적손익) 전체 제거. 실전모드 분기(`!isTestMode` → rate null) 유지.
- `computeCumulativePnl` docstring 갱신: 분모 규칙을 "매수원금 기반(aggregatePnl buyTotal)"으로 갱신, 스냅샷 분모 설명 제거.

**profit-shared.ts**:
- re-export 블록: `extractEarliestBaseAsset`·`cumulativeRealizedPnlBeforeDate`·`findBaseAssetForDate` 제거.
- import 블록: `cumulativeRealizedPnlBeforeDate`·`findBaseAssetForDate` 제거.
- `updateSummaryCards` 시그니처: `account`·`earliestBaseAsset` 파라미터 제거. `dailySummary`·`els`·`sellHistory`·`isTestMode`·`openSubText` 잔류.
- `updateSummaryCards` 본체: `findBaseAssetForDate`·`dayBaseAsset`·`fiveBaseAsset`·`monthBaseAsset`·`cumulativeRealizedPnlBeforeDate` 분모 로직 제거. 4카드 모두 `aggregatePnl(sellHistory, dateFrom, dateTo)` 결과 사용. 당일 카드 PRE OPEN 분기(`isPreOpenPhase`) 유지. 당일 카드 08:00+ 분기: `aggregatePnl(sellHistory, today, today)` 사용.
- `updateSummaryCards` docstring 갱신: 분모 규칙을 "매수원금 기반(aggregatePnl)"으로 갱신.
- `AccountValsParams.earliestBaseAsset` 필드 제거.
- `renderAccountVals`: `computeCumulativePnl` 호출 → `aggregatePnl(sellHistory)` 사용. `earliestBaseAsset` 의존 제거. docstring 갱신.

**profit-overview-mount.ts**:
- import: `findBaseAssetForDate`·`extractEarliestBaseAsset` 제거.
- `renderAccountVals` 래핑: `earliestBaseAsset: extractEarliestBaseAsset(state.analysisDailySummary)` 전달 제거.
- `buildDonutCenter`: `extractEarliestBaseAsset`·`findBaseAssetForDate` 분모 로직 제거. `computeCumulativePnl` 호출 → `aggregatePnl(state.filteredSellHistory, state.localDateFrom, state.localDateTo)` 사용. `account` 파라미터 제거. docstring 갱신.
- 차트 타이틀: `sectionTitle('거래일별 수익률')` → `sectionTitle('거래일별 실현 수익률')`.

**profit-detail-display.ts**:
- import: `findBaseAssetForDate`·`extractEarliestBaseAsset` 제거.
- `updateStatistics`: `extractEarliestBaseAsset`·`findBaseAssetForDate` 분모 로직 제거. `computeCumulativePnl` 호출 → `aggregatePnl(filteredSells, dateRange.from || undefined, dateRange.to || undefined)` 사용. `account`·`baseAsset`·`earliestBaseAsset` 파라미터 제거. docstring 갱신.
- 드릴다운 테이블 헤더: `createDrilldownTable(['날짜', '매도', '매수', '실현손익', '수익률'])` → `[..., '실현 수익률']`.

**profit-detail-mount.ts**:
- import: `extractEarliestBaseAsset` 제거.
- `restoreInitialView`: `updateSummaryCards` 호출에서 `initState.account`·`extractEarliestBaseAsset(initState.dailySummary)` 인자 제거.
- `flushDirtyRender`: `updateSummaryCards` 호출에서 `hotState.account`·`extractEarliestBaseAsset(hotState.dailySummary)` 인자 제거.
- `STAT_LABELS`: `'수익률'` → `'실현 수익률'`.

**profit-columns.ts**:
- `SELL_COLS` pnl_rate 컬럼: `label: '수익률'` → `label: '실현 수익률'`.

**profit-shared.test.ts**:
- import: `findBaseAssetForDate` 제거.
- `computeCumulativePnl — 테스트모드` describe 블록: 기대값을 매수원금 분모 기반으로 업데이트.
  - "단일 매도": rate = realized_pnl / buy_total_amt × 100 (예: -100000/1000000 = -10 → 동일, but 분모 의미 변경).
  - "다중 매도 합산": 분모 = 매수원금 합(500000+500000=1000000), rate = -100000/1000000 = -10.
  - "account 누락 시": 매수원금 기반은 account 불필요 → rate 계산 정상 (null 아님). 기대값 변경.
- `computeCumulativePnl — 실전모드` describe 블록: rate=null 유지 (증권사 SSOT — 변경 없음). `earliestBaseAsset` 파라미터 제거.
- `computeCumulativePnl — 날짜 필터` describe 블록: 스냅샷 분모 추정 기대값 → 매수원금 분모 기대값으로 업데이트.
- `computeCumulativePnl — 분모 규칙 (earliestBaseAsset 폴백)` describe 블록: 매수원금 기반으로 업데이트. `earliestBaseAsset`·`baseAsset` 파라미터 제거.
- `computeCumulativePnl — 기초자산 분모 (baseAsset 전달 시)` describe 블록: 매수원금 기반으로 업데이트. `baseAsset` 파라미터 제거.
- `findBaseAssetForDate` describe 블록 전체 제거 (함수 제거로 불필요).
- `makeAccount` 헬퍼: `computeCumulativePnl` 테스트에서 account 불필요 → 제거 검토 (단, 다른 테스트에서 사용 시 유지).

**profit-math.test.ts**:
- import: `extractEarliestBaseAsset` 제거.
- `extractEarliestBaseAsset` describe 블록 전체 제거 (함수 제거로 불필요).

**검증 방법** (3세션 종료 시):
- `cd frontend && npm run typecheck` — 타입 에러 0건 (제거 함수 참조 잔존 확인).
- `cd frontend && npm run build` — 빌드 성공.
- `cd frontend && npm run test` — 기존 테스트 기대값 업데이트로 전체 통과.
- grep 검증 (설계서 7절): `extractEarliestBaseAsset`·`findBaseAssetForDate`·`cumulativeRealizedPnlBeforeDate` 각각 frontend/src 전체에서 0건.
- **SSOT 보호 검증 (필수)**: `aggregatePnl` 함수 본체가 변경되지 않았는지 확인 (git diff에서 `profit-math.ts`의 `aggregatePnl` 함수 본체 라인 제외). 내부 로직 수정·분모 변경·신규 분기 추가 발견 시 즉시 원복.
- **신규 계산 함수 생성 금지 검증 (필수)**: 실현 수익률 계산을 수행하는 신규 함수(`calculateRate`·`computeRealizedRate`·`getRealizedPnl` 등)가 생성되지 않았는지 확인. 실현 수익률 계산은 `aggregatePnl`만 수행해야 함 (설계 결정 5 SSOT 규칙).

### 4세션 (구현 2): 신규 테스트 케이스 추가 + 제거 후 검증 + 최종 검증

**목표**: 설계서 8절 테스트 케이스(계산 정확성 5건·기간별 4건·모드별 2건) 추가 + 7절 제거 후 검증 항목 최종 확인 + 계획서 파일 삭제.

**수정 파일 목록** (2파일):
1. `frontend/tests/pages/profit-shared.test.ts`
2. `frontend/tests/pages/profit-math.test.ts`

**파일별 변경점**:

**profit-shared.test.ts** — 신규 테스트 케이스 추가 (설계서 8절):

*8.1 계산 정확성 케이스* (신규 describe 블록 `aggregatePnl — 실현 수익률 계산 정확성`):
- "매도 없음": sellHistory=[] → pnl=0, rate=0 (분모 0 → computeWeightedRate 0 반환).
- "1건 매도 (수익)": 매수 100만원→매도 105만원 → pnl=+5만원, rate=+5.00%.
- "1건 매도 (손실)": 매수 100만원→매도 98만원 → pnl=-2만원, rate=-2.00%.
- "여러 건 매도 (모두 수익)": 3건(100→105, 200→210, 300→309) → pnl=+24만원, rate=+4.00% (24/600).
- "손익 혼합 (+/-)": 100→105(+5), 200→198(-2), 300→309(+9) → pnl=+12만원, rate=+2.00% (12/600).

*8.2 기간별 케이스* (신규 describe 블록 `aggregatePnl — 기간별 동일 공식 적용 (설계 원칙 5·검증 원칙)`):
- "당일": dateFrom=dateTo=today → 당일 매도만 집계.
- "5거래일": dateFrom=recent5[4], dateTo=recent5[0] → 5거래일 내 매도만 집계.
- "당월": dateFrom=monthStart, dateTo=monthEnd → 당월 매도만 집계.
- "누적": dateFrom/dateTo 없음 → 전체 매도 집계.
- 검증 명제: 4케이스 모두 동일 `aggregatePnl` 함수 호출, 분모 규칙 분기 없음.

*8.3 모드별 케이스* (신규 describe 블록 `computeCumulativePnl — 모드별 (설계 8.3)`):
- "테스트모드": isTestMode=true → 계산된 수익률 (aggregatePnl 결과).
- "실전모드": isTestMode=false → rate=null ('-') (증권사 SSOT — 변경 없음).

**profit-math.test.ts** — 변경 없음 (3세션에서 extractEarliestBaseAsset 테스트 제거 완료).

**검증 방법** (4세션 종료 시):
- `cd frontend && npm run typecheck` — 통과.
- `cd frontend && npm run build` — 성공.
- `cd frontend && npm run test` — 신규 테스트 케이스 포함 전체 통과.
- grep 검증 (설계서 7.2 참조):
  - `base_asset` (frontend/src 전체) → 0건.
  - `earliest_base_asset` (frontend/src 전체) → 0건.
  - `earliestBaseAsset` (frontend/src 전체) → 0건.
  - `baseAsset` (frontend/src 전체, 분모용) → 0건 (다른 맥락 변수 별도 확인).
  - `dayBaseAsset`·`fiveBaseAsset`·`monthBaseAsset` (frontend/src 전체) → 각 0건.
- **SSOT 보호 검증 (필수)**: `aggregatePnl` 함수 본체가 변경되지 않았는지 확인 (git diff에서 `profit-math.ts`의 `aggregatePnl` 함수 본체 라인 제외). 내부 로직 수정·분모 변경·신규 분기 추가 발견 시 즉시 원복.
- **신규 계산 함수 생성 금지 검증 (필수)**: 실현 수익률 계산을 수행하는 신규 함수가 생성되지 않았는지 확인. 실현 수익률 계산은 `aggregatePnl`만 수행해야 함 (설계 결정 5 SSOT 규칙).
- **동일 입력 동일 결과 검증 (필수 — 3.5절 테스트 통과로 확인)**: 동일 `sellHistory` 입력 시 요약카드·도넛 중앙·통계·계좌현황 4곳 모두 동일 `pnl`·`rate`·`buyTotal` 산출 확인.
- **최종 SSOT 보호 선언 (필수)**: 모든 실현 수익률은 동일한 `aggregatePnl` 결과를 사용해야 하며 화면별 별도 계산, 복제 계산, 신규 계산 함수 추가를 금지한다. 본 문장은 향후 유지보수 시 SSOT 위반 회귀 방지 기준선.
- **계획서 파일 삭제** (규칙 10): `docs/architecture_realized_rate_design.md` + `docs/plan_realized_rate.md` 최종 커밋 시 삭제.

---

## 2. 사용자 결정 항목

> 설계서 "3. 사용자 결정 항목"에서 이관. 구현 중 추가 결정 시 누적 기록.

**질문 1: 수익률 분모 설계 방향**
- 사용자 결정: **매수원금 기반 실현 수익률 통일** — 당일/5거래일/당월/누적 모두 동일 원칙.
- 근거 (사용자): "이 앱은 자동매매 엔진의 성과를 보여주는 앱. 사용자가 궁금한 것은 '이 기간에 자동매매가 투입한 자본으로 얼마를 벌었는가'. Capital At Risk = 매수원금. 총자산/주문가능금액/투자원금은 자동매매 성과가 아님."
- 분자 = 해당 기간 매도 완료된 종목들의 실현손익 합
- 분모 = 해당 기간 매도 완료된 종목들의 총 매수원금 합
- 투자원금, 총자산, 주문가능금액, 평가손익, account_daily_snapshot은 수익률 계산에 사용하지 않음

**질문 2: 누적 카드 분모**
- 사용자 결정: **매수원금 기반 통일** (투자원금 분모 기각)
- 근거 (사용자): "계좌 전체 자산의 증감이 아니라 매매가 완료된 거래의 성과를 보여주는 것이 목적. 전 기간 동일하게 유지."

**질문 3: UI 명칭**
- 사용자 결정: **"실현 수익률"** 표시
- 근거 (사용자): "사용자도 '매도된 거래 기준이구나'라고 이해. 명확히 표시."

---

## 3. 테스트 계획

> 설계서 8절 테스트 케이스. 4세션에서 `profit-shared.test.ts`에 추가.

### 3.1 계산 정확성 케이스 (5건)

| 케이스 | 입력 | 기대 결과 | 비고 |
|--------|------|-----------|------|
| 매도 없음 | sellHistory=[] | pnl=0, rate=0 | 분모 0 → computeWeightedRate 0 반환 |
| 1건 매도 (수익) | 매수 100만원 → 매도 105만원 | pnl=+5만원, rate=+5.00% | 단일 거래 정확성 |
| 1건 매도 (손실) | 매수 100만원 → 매도 98만원 | pnl=-2만원, rate=-2.00% | 단일 거래 손실 |
| 여러 건 매도 (모두 수익) | 3건: 100→105, 200→210, 300→309 | pnl=+24만원, rate=+4.00% (24/600) | 매수원금 합 분모 — 개별 평균 아님 |
| 손익 혼합 (+/-) | 100→105(+5), 200→198(-2), 300→309(+9) | pnl=+12만원, rate=+2.00% (12/600) | 손익 상쇄 + 매수원금 합 분모 |

### 3.2 기간별 케이스 (4건 — 설계 원칙 5·검증 원칙)

| 케이스 | dateFrom/dateTo | 기대 | 비고 |
|--------|-----------------|------|------|
| 당일 | today ~ today | 당일 매도만 집계 | PRE OPEN 분기 유지 — 0원 + "개장 전" |
| 5거래일 | recent5[4] ~ recent5[0] | 5거래일 내 매도만 집계 | getRecent5TradingDays 공통 소스 |
| 당월 | monthStart ~ monthEnd | 당월 매도만 집계 | — |
| 누적 | (없음) | 전체 매도 집계 | aggregatePnl(sellHistory) 전체 범위 |

**검증 명제**: 4기간 케이스 모두 동일 `aggregatePnl` 함수 호출, 분모 규칙 분기 없음. 기간 필터(`dateFrom`/`dateTo`)만 입력 차이.

### 3.3 모드별 케이스 (2건)

| 케이스 | isTestMode | 기대 rate | 비고 |
|--------|------------|-----------|------|
| 테스트모드 | true | 계산된 수익률 | aggregatePnl 결과 사용 |
| 실전모드 | false | null ('-') | 증권사 SSOT — 앱 재계산 금지 (변경 없음) |

### 3.4 기존 테스트 업데이트 (3세션 수행)

- 직전 세션에서 추가된 스냅샷 분모 추정 테스트(`profit-shared.test.ts` 실전모드 4건 rate=null, 테스트모드 스냅샷 미존재 2건) → 매수원금 기반 기대값으로 업데이트.
- 스냅샷 의존 테스트 케이스 제거 (분모 추정 로직 제거로 인해 불필요).
- `extractEarliestBaseAsset` 테스트(`profit-math.test.ts`) 제거.
- `findBaseAssetForDate` 테스트(`profit-shared.test.ts`) 제거.

### 3.5 동일 입력 동일 결과 검증 (4곳 일관성 — P10 SSOT 회귀 방지)

> 설계서 0절 검증 원칙 + 결정 5 SSOT 규칙의 실행 검증. 본 설계의 핵심은 `computeCumulativePnl` → `aggregatePnl` 통합이므로, 동일 `sellHistory` 입력 시 4곳(요약카드·도넛 중앙·통계·계좌현황) 모두 동일 결과가 산출되어야 함.

신규 describe 블록 `실현 수익률 SSOT 일관성 — 동일 입력 동일 결과 (4곳)`:

| 케이스 | 입력 | 기대 | 비고 |
|--------|------|------|------|
| 4곳 동일 결과 (누적 범위) | 동일 sellHistory, dateFrom/dateTo 없음 | 요약카드 누적·도넛 중앙(필터 없음)·통계(필터 없음)·계좌현황 누적 모두 동일 pnl·rate·buyTotal | 4곳 모두 `aggregatePnl(sellHistory)` 결과 사용 |
| 4곳 동일 결과 (기간 한정) | 동일 sellHistory, 동일 dateFrom/dateTo | 요약카드(당일/5거래일/당월)·도넛 중앙(동일 필터)·통계(동일 필터) 모두 동일 pnl·rate·buyTotal | 4곳 모두 `aggregatePnl(sellHistory, dateFrom, dateTo)` 결과 사용 |

**검증 명제**: 동일 `sellHistory` + 동일 기간 필터 입력 시 4곳(요약카드·도넛 중앙·통계·계좌현황)의 `pnl`·`rate`·`buyTotal`이 완전히 동일해야 함. 한 곳이라도 다르면 SSOT 위반 (별도 계산 경로 존재 의미). 본 테스트는 향후 유지보수 시 우회 계산 경로 회귀를 자동 감지.

---

## 4. 런타임 검증 방법

> 프론트엔드 전용 변경 — 백엔드 런타임 기동 불필요. 브라우저 화면 확인은 사용자 수행.

- **typecheck**: `cd frontend && npm run typecheck` (각 세션 종료 시)
- **build**: `cd frontend && npm run build` (각 세션 종료 시)
- **test**: `cd frontend && npm run test` (각 세션 종료 시)
- **브라우저 화면 확인 (사용자)** — 4세션 완료 후:
  - **문구 확인**: 테스트모드 4카드·도넛 중앙·통계·계좌현황 누적 수익률 영역이 "실현 수익률" 맥락으로 표시. 드릴다운 테이블 헤더 "실현 수익률". 거래내역 컬럼 헤더 "실현 수익률". 차트 타이틀 "거래일별 실현 수익률".
  - **숫자 일관성 확인 (필수 — P10 SSOT 회귀 검증)**: 동일 기간(예: 누적) 선택 시 요약카드 누적·도넛 중앙(필터 없음)·통계(필터 없음)·계좌현황 누적 4곳의 수익률 숫자가 완전히 동일한지 확인. 한 곳이라도 다르면 우회 계산 경로 존재(SSOT 위반) → 5. 바로잡음 로그 기재 후 원인 추적.
  - **기간 전환 시 숫자 일관성**: 당일/5거래일/당월/누적 전환 시 각 카드의 수익률이 동일 `aggregatePnl` 결과(기간 필터만 차이)로 산출되는지 확인. 기간별 분모 규칙 분기가 없는지 검증.

---

## 5. 바로잡음 로그

> 구현 중 태스크 기재 오류 발견 시 원인+수정 기록. (구현 단계에서 업데이트)
