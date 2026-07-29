# 설계: 수익 상세/수익현황 기간별 카드 4종 + 드릴다운 리팩토링

> **다단계 워크플로우 1세션(설계)** — 본 파일은 설계만 포함. 2세션(태스크 파일)은 다음 세션에서 작성.
> **작성일**: 2026-07-30
> **선행 설계**: `docs/architecture_base_asset_denominator_design.md`(분모 방식), `docs/architecture_trading_day_premarket_design.md`(프리마켓 거래일)
> **본 설계 위치**: 선행 설계 구현체 위의 **카드 구조(5→4)·당일 계산식(실현+평가)·거래일 기준일 분리·드릴다운 모달화·실전 분모 보정**을 다룸. 선행 설계와 충돌하는 항목은 본 문서가 우선(사용자 신규 결정).

---

## 1. 문제 정의

### 1.1 현상 (사용자 명세 기반)
1. 카드가 5개(당일/전일/5거래일/당월/누적) — 전일 카드 존재. 기획은 4개(당일/5거래일/당월/누적)로 통일 요구.
2. 장 개시 전(00:00~08:00) 당일 카드가 **전일 손익**을 표시(`getTradingToday()`가 PRE_OPEN에 전일 반환 → 당일 dateFrom/dateTo=전일). 기획은 **0원(0.00%) + "개장 전"** 표시 요구.
3. 5거래일/당월 카드의 분모·차트 X축이 "오늘 포함"될 수 있는 경로 점검 필요. 기획은 08:00 전 "오늘 제외, 전일(N-1) 장마감 기준 완료된 과거 거래일만" 요구.
4. 수익률 분모에 매수원가 합(`buyTotal`) 사용(실전 누적·첫거래일 폴백·업종 도넛 rate) — "회전율 착시" 기획 폐지 대상.
5. 드릴다운이 단일 인라인 "당월 거래일별 요약" 토글. 기획은 카드별 독립 드릴다운(바텀시트/모달) 요구.
6. 수익현황(메인) 페이지가 수익 상세 페이지와 카드 구조·거래일 유틸을 공유하지 않음(메인은 차트 quickRange 버튼 5개). 기획은 두 페이지 일관화 요구.

### 1.2 근본 원인
- `getTradingToday()`(`utils/date.ts`)가 단일 기준일을 반환하여 **당일 카드(오늘 기준)와 기간 카드(오늘 제외)의 서로 다른 기준일 요구를 하나로 처리** → PRE_OPEN에서 당일 카드가 전일 데이터 표시.
- `computeCumulativePnl` 실전 누적 분모 = `buyTotal`(매수원가 합). 실전 `AccountSnapshot.accumulated_investment` 미제공(테스트 전용) → 첫거래일 예외도 `buyTotal` 폴백. 기획은 "총자산 스냅샷" 분모 요구.
- 카드 DOM/계산/드릴다운이 5개 카드 전일 포함으로 경직됨.

---

## 2. 사용자 결정 항목 (본 세션 확정)

| # | 결정 사항 | 확정값 | 사유 |
|---|---|---|---|
| 1 | 카드 구조 | **4개**(당일/5거래일/당월/누적). 전일 카드 제거 | 기획 명세. 전일 확인은 5거래일 드릴다운으로 |
| 2 | 드릴다운 형태 | **공통 모달**(`dialog.ts`) 바텀시트/모달. 인라인 토글 제거 | 기획 명세 |
| 3 | 당일 드릴다운 범위 | **실현+평가 둘 다**. 모달 내 영역 구분(`오늘 확정(실현)` / `오늘 보유(평가)`). **당일 카드 총액 = 모달 합계 100% 일치** | 사용자. 카드-상세 정합성(P22) |
| 4 | 누적 드릴다운 범위 | **입금 히스토리(daily_deposit) + 월별 누적 손익**. 출금 0원 표시/텍스트 생략(후순위) | 사용자. 정산 엔진 수정 리스크 최소화 |
| 5 | 실전 분모 기준 | **증권사 API 총자산(total_asset = 평가금+예수금) 스냅샷**. buyTotal 분모 전면 폐지. 과거 거래일도 `account_daily_snapshot.total_asset` 분모 | 사용자. 예수금 변동까지 반영된 정확 계좌 수익률 |
| 6 | 당일 카드 PRE_OPEN 표시 | **0원(0.00%) + "개장 전" 서브 텍스트**. 08:00+ 실시간 반영 | 기획 명세 |
| 7 | 거래일 기준일 분리 | 당일 카드 = `getLocalToday()`(실제 오늘) + PRE_OPEN 강제 0. 기간 카드(5거래일/당월) = "오늘 제외" 기준(전일 N-1 기준) | 기획 명세. 당일과 기간의 PRE_OPEN 의미 차이 반영 |
| 8 | 20:00~24:00 조기 리셋 | **방지**(다음날 전환 금지). PRE_OPEN(08:00 전)에만 전일 마감 데이터 | 기획 명세. 현재 구현도 해당 분기 없음 — 유지 확인 |

### 결정 상세 보충
- **결정 3 정합성**: 당일 카드 총손익 = `오늘 실현손익(매도 체결)` + `현재 보유종목 평가손익(computeHoldingsSummary.evalPnl)`. 모달 두 영역 합 = 카드 총액. 분모 = 전일 장마감 total_asset + 당일 순입금.
- **결정 5 첫거래일 예외**: baseAsset(전일 스냅샷)이 없는 첫 거래일 — 실전은 `account_daily_snapshot` 중 **가장 오래된 total_asset**을 "최초 투자원금"으로 사용. 테스트는 현행 `accumulated_investment` 유지. `buyTotal` 폴백은 **폐지**(P20 — 정상 경로 빈 값을 폴백으로 덮지 않음; 대신 "데이터 미축적" 시 rate `null`→"-" 표시 검토, 단 첫 스냅샷 있으면 정상).
- **결정 7 분리 근거**: 당일 카드는 "오늘 실시간 손익"이므로 오늘 날짜 기준. 기간 카드는 "완료된 과거 거래일" 집계이므로 08:00 전 오늘 미포함. 단일 `getTradingToday()`로 양쪽을 동시 만족 불가 → 용도 분리.

---

## 3. 카드 구조 변경 (5→4, 두 페이지 통일)

### 3.1 카드 4종 고정
| 순서 | 타이틀 | 분모 | 손익 원천 |
|---|---|---|---|
| 1 | 당일 손익 | 전일 장마감 total_asset + 당일 순입금 | 오늘 실현(매도) + 현재 보유 평가 |
| 2 | 5거래일 손익 | 5거래일 전 장마감 total_asset | 5거래일 실현손익 합 |
| 3 | 당월 손익 | 당월 1일 전일 장마감 total_asset | 당월 실현손익 합 |
| 4 | 누적 손익 | 첫 거래일 기초자산(실전=첫 total_asset / 테스트=accumulated_investment) | 전체 실현손익 합 |

> **전일 카드 제거**: `SUMMARY_CARD_TITLES`, `SummaryCardEls`(prev* 필드), `createSummaryCards`(루프 5→4), `updateSummaryCards`(prevS 계산), `SummaryCardCallbacks.onPrevClick`, `SelectedView='prev'`, `colorMap.prev`, `quickDateRangesConfig` '전일' 항목, `makeCenterTitle` '전일' 분기 — 전부 제거.

### 3.2 두 페이지 모듈화
- **수읉 상세(`profit-detail`)**: 상단 요약 카드 4종(`createSummaryCards` 재사용).
- **수익현황(메인, `profit-overview`)**: 현재 차트 quickRange 버튼 5개 → 4개(전일 제거). 카드 구조는 상세와 동일 4종 명칭·분모·거래일 유틸 공유.
- **공유 SSOT**: `profit-shared.ts`(카드 DOM/계산), `utils/date.ts`(거래일 유틸). 메인의 quickRange 라벨/분모 계산도 `profit-shared`의 카드 계산 함수와 동일 분모 규칙 사용(P10/P23).

---

## 4. 거래일 계산 룰 (당일 vs 기간 분리)

### 4.1 두 기준일 함수 분리
| 함수 | 용도 | PRE_OPEN(08:00 전) | 08:00~20:00 | 20:00~24:00 |
|---|---|---|---|---|
| `getLocalToday()` | 캘린더 오늘(표시·당일 카드 날짜) | 오늘 | 오늘 | 오늘 |
| `getTradingToday()` | **기간 카드 기준일**(5거래일/당월/차트) | 전일(N-1) | 오늘 | 오늘(유지, 다음날 전환 금지) |
| `isPreOpenPhase()` (신규) | 당일 카드 0원 강제 여부 | true | false | false |

> `getTradingToday()`는 현행 구현(PRE_OPEN→`_prevWeekday`, 그 외→오늘)을 **기간 카드 전용**으로 유지. 20:00~24:00 다음날 전환 분기는 **도입 금지**(결정 8). `POST_CLOSE_PHASE` 분기는 선행 설계 제안에 있었으나 미구현 상태이며, 본 설계도 명시적으로 배제.

### 4.2 당일 카드 거래일 처리
- 당일 카드 dateFrom/dateTo = `getLocalToday()`(실제 오늘).
- `isPreOpenPhase()` = `PRE_OPEN_PHASES.has(phase.krx) && PRE_OPEN_PHASES.has(phase.nxt)` (현행 `getTradingToday` 판정과 동일 집합 재사용 — P23).
- PRE_OPEN 시: 당일 카드 pnl=0, rate=0, 서브 텍스트 "개장 전" 표시. 실현/평가 집계 수행하지 않음(08:00 전 데이터 없음 전제).
- 08:00+: 실현(오늘 매도) + 평가(현재 보유 evalPnl) 실시간 집계.

### 4.3 기간 카드 거래일 처리 (오늘 제외)
- 5거래일: `getRecent5TradingDays(dailySummary)` — dailySummary는 백엔드 `get_daily_summary(days=N, from_date=get_chart_reference_trading_day())` 기반. `get_chart_reference_trading_day()`(08:00 기준)가 PRE_OPEN에 전일 반환 → dailySummary에서 오늘 점 미포함. 프론트는 dailySummary에서 top5 추출(현행 유지).
- 당월: `monthStart = getTradingToday().slice(0,7)+'-01'`. PRE_OPEN에 getTradingToday=전일 → 전일 소속 월의 1일. 월 경계일 00:00~08:00에 전월 1일(기획 "오늘 제외" 부합).
- 차트 X축 5 포인트: 동일 dailySummary 기반(오늘 제외).

### 4.4 20:00~24:00 조기 리셋 방지 (결정 8)
- 현행 `getTradingToday()`에 `POST_CLOSE_PHASE` 분기 없음 → 20:00~24:00에 오늘 유지. 본 설계도 동일.
- 전수 점검: `get_current_trading_day()`(20:00 기준 다음날)가 카드/차트/당일 집계 경로에 침투하는지 태스크 단계에서 확인. 현재 조사 기준으로 카드 경로는 `getTradingToday()`(phase 기반)만 사용 → 영향 없음. 백엔드 스냅샷 저장(`_save_daily_snapshot`)은 20:00 이후에만 호출되므로 `get_current_trading_day()` 사용이 정합(선행 설계 1.5절 확인).

---

## 5. 분모(Base Asset) 산출 원칙

### 5.1 통일 규칙 (buyTotal 분모 전면 폐지)
```
수익률 = 해당 기간 손익 / 해당 기간 시작 시점 기초자산(total_asset 스냅샷)
```
- **기간 카드(당일/5거래일/당월)**: 분모 = `baseAsset`(전일 장마감 total_asset). 당일 = 전일 baseAsset + 당일 순입금(현행 결정 2 유지).
- **누적 카드**: 분모 = 첫 거래일 기초자산.
  - 테스트: `accumulated_investment`(현행 유지).
  - 실전: `account_daily_snapshot` 중 가장 오래된 `total_asset`(신규 조회 함수).
- **첫거래일 예외(baseAsset null)**: `buyTotal` 폴밭 **폐지**. 첫 스냅샷 total_asset(실전)/accumulated_investment(테스트)로 정의. 첫 스냅샷조차 없으면 rate=`null`→UI "-" 표시(P20/P21 — 빈 값을 폴밭으로 덮지 않음).

### 5.2 백엔드 신규/수정
- **신규**: `get_earliest_base_asset(trade_mode) -> int | None` (`stock_tables.py`) — `account_daily_snapshot`에서 해당 모드의 가장 오래된 `total_asset` 반환. 누적 카드·첫거래일 예외 분모용.
- **수정**: `get_daily_summary` 반환 행의 `base_asset`은 현행 유지(전일 스냅샷). 단, dailySummary 응답에 **누적 카드용 earliest_base_asset**을 별도 필드(예: `earliest_base_asset`)로 1회 포함 검토 — 또는 별도 API. 태스크 단계에서 결정(P24 — dailySummary 확장이 API 추가보다 단순, 선행 설계 4.3.2 권장 준수).
- **실전 total_asset 노출 확인**: `engine_account.py` 실전 계좌 조회 시 `deposit + total_eval` = total_asset 산출 가능(선행 설계 3.1 확인). 스냅샷 저장 시 total_asset에 해당 값 저장됨.

### 5.3 프론트엔드 `computeCumulativePnl` 수정
```ts
// 실전 initialInvestment 정의 변경 (buyTotal → earliest total_asset)
const initialInvestment = isTestMode
  ? (account?.accumulated_investment ?? account?.initial_deposit ?? 0)
  : (earliestBaseAsset ?? 0)  // 신규: 첫 스냅샷 total_asset
// 기간 카드: baseAsset ?? initialInvestment (buyTotal 폴밭 제거)
// 누적 카드: initialInvestment (위와 동일)
// 단, earliestBaseAsset 없으면 rate=null 반환 (폴밭 금지)
```
- `CumulativePnlParams`에 `earliestBaseAsset?: number` 추가.
- 반환 타입 `{ pnl, rate }` → rate가 `null` 가능하도록 `{ pnl: number; rate: number | null }` 확장. 호출부에서 null 시 "-" 표시.

### 5.4 업종 도넛 rate (buyTotal 분모) 처리
- `buildSectorDonutRows`의 `computeWeightedRate(pnl, buyTotal)` — 업종별 기여도 rate.
- **결정**: 본 리팩토링 범위는 **기간 카드 분모**가 핵심. 업종 도넛은 "업종별 손익 기여율"로서 buyTotal 분모가 가진 의미가 다름(기간 기초자산 대비가 아닌 업종 매입 대비). 단, 기획 "전면 폐지" 문구를 고려, 태스크 단계에서 **(A) 도넛 rate는 buyTotal 유지(업종 기여율 의미) (B) 도넛 rate 제거 후 금액만 표시** 중 사용자 결정 권장. 본 설계는 (A) 임시 권장(도넛은 기간 카드가 아닌 분포 시각화이므로 분모 규칙 대상 아님).

---

## 6. 당일 카드 계산식 (실현+평가, 개장 전 0)

### 6.1 계산식
```
당일 손익 = 오늘 실현손익(매도 체결 realized_pnl 합, date=오늘)
          + 현재 보유종목 평가손익(computeHoldingsSummary.evalPnl)
당일 수익률 = 당일 손익 / (전일 장마감 total_asset + 당일 순입금)
```
- PRE_OPEN: 당일 손익 = 0, 수익률 = 0, "개장 전" 서브 텍스트.
- 08:00+: 실시간 틱 → 평가손익 변동 반영(보유종목 cur_price 연동). 실현손익은 매도 체결 시 갱신.

### 6.2 모달 정합성 (결정 3)
- 모달 영역 1: `오늘 확정(실현) 손익` = 오늘 매도 종목별 realized_pnl 리스트 + 합계.
- 모달 영역 2: `오늘 보유(평가) 손익` = 현재 보유 종목별 평가손익(computePositionValuation) 리스트 + 합계.
- **영역1 합계 + 영역2 합계 = 당일 카드 총액** (P22 — 불일치 시 버그 인지).

### 6.3 카드 DOM 확장
- 현행 카드: 타이틀 + pnl + rate. **서브 텍스트 요소 신규 추가**(당일 카드 "개장 전" 표시용).
- `SummaryCardEls`에 `todaySubTextEl?` 추가(당일 카드 전용). 기간 카드는 서브 텍스트 미사용.

---

## 7. 드릴다운 명세 (4종 모달)

공통 모달(`dialog.ts` `CustomDialogOptions`) 사용. 각 카드 클릭 시 모달 오픈.

| 카드 | 모달 타이틀 | 내용 |
|---|---|---|
| 당일 | 당일 손익 상세 | 탭/영역 구분: [오늘 확정(실현) 손익: 합계] 종목별 realized_pnl 리스트 / [오늘 보유(평가) 손익: 합계] 종목별 evalPnl 리스트 |
| 5거래일 | 5거래일 손익 상세 | 최근 5거래일 날짜별 손익 요약(예: 07/29 -41,255원). `getRecent5TradingDays` + 일별 realized_pnl |
| 당월 | 당월 손익 상세 | 당월 날짜별 손익 요약(`buildMonthlyDrilldown` 재사용) |
| 누적 | 누적 손익 상세 | 월별 누적 손익 요약 + 입금 히스토리(`account_daily_snapshot.daily_deposit`). 출금 0원/텍스트 생략 |

### 7.1 드릴다운 빌더 함수 (profit-shared 신규)
- `buildTodayDrilldown(sellHistory, positions, sectorStocks, today)` → { realizedRows, evalRows, realizedTotal, evalTotal }
- `buildFivedayDrilldown(dailySummary)` → DailyDrilldownRow[] (최근 5거래일)
- `buildMonthlyDrilldown` (현행 재사용)
- `buildCumulativeDrilldown(dailySummary, snapshots)` → { monthlyRows[], depositHistory[] } (신규 — 백엔드 입금 이력 데이터 필요)

### 7.2 인라인 토글 제거
- `profit-detail-mount.ts` `buildFilterRow`의 "당월 거래일별 요약" 토글 버튼 제거.
- `drilldownViewContainer`/`drilldownTable` 인라인 경로 제거 → 모달로 이관.
- `SelectedView='drilldown'` 상태 제거.

---

## 8. 파일별 변경점

### 8.1 백엔드
| 파일 | 변경 |
|---|---|
| `stock_tables.py` | `get_earliest_base_asset(trade_mode)` 신규. 입금 이력 조회 함수 신규(누적 드릴다운용) |
| `trade_history.py` | `get_daily_summary`에 `earliest_base_asset` 포함(또는 별도 API). 당일 실현+평가 합산 데이터 노출 검토 |
| `trade.py` | 필요 시 누적 드릴다운용 입금 이력 라우트 추가 |
| `engine_account.py` | 실전 total_asset 스냅샷 저장 정합성 확인(변경 최소) |

### 8.2 프론트엔드
| 파일 | 변경 |
|---|---|
| `utils/date.ts` | `isPreOpenPhase()` 신규. `getTradingToday()` 기간 카드 전용 명확화. 20:00 전환 분기 도입 금지 명시 |
| `profit-shared.ts` | 카드 4종(전일 제거), `computeCumulativePnl` 분모 buyTotal 폐지+earliestBaseAsset+rate null, 당일 카드 실현+평가 계산식, "개장 전" 서브 텍스트, 드릴다운 빌더 4종, `SummaryCardEls` 정리 |
| `profit-detail.ts` | `SelectedView` 'prev'/'drilldown' 제거 |
| `profit-detail-mount.ts` | `buildSummaryRow` 4카드 콜백(모달 연결), `buildFilterRow` 토글 제거, `restoreInitialView`/`flushDirtyRender` 정리 |
| `profit-detail-display.ts` | `updateCardSelection`/`updateStatCardSelection` prev 제거, 인라인 드릴다운 제거, 모달 드릴다운 표시 함수 신규 |
| `profit-overview-mount.ts` | `quickDateRangesConfig` 4개(전일 제거), `makeCenterTitle` '전일' 제거, 분모 연동(earliestBaseAsset) |
| `profit-overview-date.ts` | 기본 날짜 범위 4종 정합 |
| `dialog.ts` | 드릴다운 모달 적용(변경 최소 — 기존 CustomDialog 재사용) |
| `types/index.ts` | `AccountSnapshot` 확장 확인(실전 total_asset/daily_deposit) |

### 8.3 테스트
| 파일 | 변경 |
|---|---|
| `frontend/tests/utils/date.test.ts` | `isPreOpenPhase`, 당일 vs 기간 기준일 분리 케이스 |
| `profit-shared` 관련 테스트 | 4카드, 분모 buyTotal 폐지, 당일 실현+평가, "개장 전", rate null |
| `backend/tests/test_trade_history.py` | `get_earliest_base_asset`, dailySummary earliest_base_asset, 입금 이력 |

---

## 9. 아키텍처 원칙 점검

| 원칙 | 부합 | 비고 |
|---|---|---|
| P10 (SSOT) | ✅ | 카드 구조·분모·거래일 유틸 두 페이지 공유. 분모 SSOT=`computeCumulativePnl`. 거래일 SSOT=백엔드 phase |
| P16 (살아있는 경로) | ✅ | 드릴다운 모달이 카드 클릭 실제 경로에 연결. dead code(전일 카드/인라인 토글) 제거 |
| P20 (폴백 금지) | ✅ | buyTotal 폴밭 폐지. baseAsset 없으면 rate null("-") 표시. "개장 전" 명시적 상태 |
| P21 (사용자 투명성) | ✅ | "개장 전" 표시, 당일 카드-모달 정합, 분모 회전율 착시 제거 |
| P22 (데이터 정합성) | ✅ | 당일 카드=실현+평가=모달 합. 분모 단일 소스. 파생 데이터 중복 저장 금지 |
| P23 (일관성) | ✅ | 두 페이지 동일 카드 4종/용어/네이밍. 공통 모달 재사용. `isPreOpenPhase` 기존 phase 집합 패턴 재사용 |
| P24 (단순성) | ✅ | 전일 카드/인라인 토글 제거로 중복 축소. 기준일 함수 용도 분리(단일 함수 인자 분기보다 명확) |
| P25 (격리된 실패) | ✅ | 카드/모달 단위 격리 유지. 백엔드 스냅샷 조회 실패 시 rate null(블로킹 아님) |

### P20 상세 — 첫거래일 예외
- baseAsset null + earliestBaseAsset 없음(스냅샷 미축적) → rate `null` → UI "-". **buyTotal로 덮지 않음**(회전율 착시 재발 방지).
- earliestBaseAsset 있으면 정상 분모(첫 total_asset). 이는 "첫 거래일 기초자산 = 최초 투자원금" 금융 정의(폴백 아님).

---

## 10. 구현 범위 (태스크 파일 2세션에서 분해)

### 10.1 백엔드
1. `get_earliest_base_asset()` 구현 + 테스트
2. `get_daily_summary`에 earliest_base_asset 포함(또는 별도 API) + 테스트
3. 누적 드릴다운용 입금 이력 조회 함수 + 라우트 + 테스트
4. 실전 total_asset 스냅샷 정합성 확인(변경 최소)

### 10.2 프론트엔드
1. `utils/date.ts` — `isPreOpenPhase`, 기준일 분리 + 테스트
2. `profit-shared.ts` — 카드 4종, 분모 폐지, 당일 실현+평가, "개장 전", 드릴다운 빌더 + 테스트
3. `profit-detail-*` — 4카드, 모달 드릴다운, prev/인라인 토글 제거
4. `profit-overview-*` — quickRange 4, 분모 연동, 메인-상세 일관화
5. `dialog.ts` 드릴다운 모달 적용

### 10.3 검증
- 백엔드: `.venv/bin/python -m pytest backend/tests -q` (관련 파일 회귀)
- 프론트엔드: `cd frontend && npm run typecheck && npm run build && npm run test`
- 런타임: `.venv/bin/python -W error::RuntimeWarning main.py` (await 누락)
- DB: 신규 컬럼/테이블 없음(기존 `account_daily_snapshot` 재사용) → 백업 불필요. 단, 조회 함수 추가만으로 스키마 변경 없음 확인.

---

## 11. 후순위 (본 설계 범위 외)
- 실전 출금 추적(`daily_withdrawal`) — 결정 4에서 후순위 명시.
- 업종 도넛 rate 분모 변경(5.4) — 태스크 단계 사용자 결정 권장.
- 백엔드 `get_current_trading_day()` 08:00 기준 미반영 — 선행 설계 1.5절에서 수정 제외 확정(스냅샷 저장은 20:00+만 호출). 본 설계도 유지.

---

## 12. 다음 세션(태스크 파일) 인계 사항
1. 본 설계 10.1~10.3 구현 범위 태스크 단위 분해
2. 업종 도넛 rate 분모(5.4) 사용자 결정 항목 기재
3. `earliest_base_asset` 전달 방식(dailySummary 확장 vs 별도 API) 태스크 단계 확정 — P24 권장: dailySummary 확장
4. 당일 실현+평가 합산 데이터를 프론트에서 조립(현행 sellHistory + positions/sectorStocks)할지 백엔드 제공할지 — 현행 프론트 보유 데이터로 조립 가능(P10 — positions/sectorStocks SSOT 이미 프론트에 있음) → 백엔드 추가 최소 방향
5. 모달 내 "오늘 보유(평가)" 종목 리스트 — `computePositionValuation` 재사용(보유 종목 페이지와 동일 공식, P23)
